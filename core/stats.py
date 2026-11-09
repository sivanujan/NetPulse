"""Analytical statistics, outage calculation, and network comparison for NetPulse."""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from core.config import DEFAULT_BUSY_KBPS, DEFAULT_CHECK_INTERVAL_SEC
from core.storage import NetRecord, SpeedRecord


@dataclass
class SummaryStats:
    """Summary statistics for network records."""

    checks: int = 0
    hours: float = 0.0
    uptime_pct: float = 0.0
    good_pct: float = 0.0
    down_count: int = 0
    bad_count: int = 0
    ok_count: int = 0
    ping_median: Optional[float] = None
    ping_avg: Optional[float] = None
    loss_avg: float = 0.0
    speed_avg: Optional[float] = None
    speed_max: Optional[float] = None
    speed_min: Optional[float] = None
    speed_count: int = 0


@dataclass
class OutageEvent:
    """A period of downtime or sustained bad performance."""

    start_time: datetime
    end_time: datetime
    duration_sec: float
    status: str
    network: str
    conn: str
    checks_count: int


@dataclass
class GapEvent:
    """A period of missing data (e.g. PC sleep/shutdown or monitor stopped)."""

    start_time: datetime
    end_time: datetime
    duration_sec: float


def summarize(
    net_records: Sequence[NetRecord],
    speed_records: Optional[Sequence[SpeedRecord]] = None,
    check_interval_sec: int = DEFAULT_CHECK_INTERVAL_SEC,
) -> SummaryStats:
    """Compute overall summary statistics from net and speed records."""
    total = len(net_records)
    if total == 0:
        return SummaryStats()

    down = sum(1 for r in net_records if r.status == "DOWN")
    bad = sum(1 for r in net_records if r.status == "BAD")
    ok = sum(1 for r in net_records if r.status == "OK")

    lats = [r.latency_ms for r in net_records if r.latency_ms is not None]
    losses = [r.loss_pct for r in net_records if r.loss_pct is not None]

    speeds: List[float] = []
    if speed_records:
        speeds = [s.download_mbps for s in speed_records if s.download_mbps is not None]

    uptime = 100.0 * (total - down) / total
    good = 100.0 * (total - down - bad) / total

    return SummaryStats(
        checks=total,
        hours=round(total * check_interval_sec / 3600.0, 2),
        uptime_pct=round(uptime, 2),
        good_pct=round(good, 2),
        down_count=down,
        bad_count=bad,
        ok_count=ok,
        ping_median=round(statistics.median(lats), 1) if lats else None,
        ping_avg=round(statistics.mean(lats), 1) if lats else None,
        loss_avg=round(statistics.mean(losses), 2) if losses else 0.0,
        speed_avg=round(statistics.mean(speeds), 3) if speeds else None,
        speed_max=round(max(speeds), 3) if speeds else None,
        speed_min=round(min(speeds), 3) if speeds else None,
        speed_count=len(speeds),
    )


def find_outages(
    net_records: Sequence[NetRecord],
    gap_limit_sec: int = 120,
    check_interval_sec: int = DEFAULT_CHECK_INTERVAL_SEC,
    include_bad: bool = False,
    min_bad_duration_sec: int = 300,
) -> List[OutageEvent]:
    """Identify outage periods (DOWN status) and optionally sustained BAD periods."""
    if not net_records:
        return []

    valid = [r for r in net_records if r.dt is not None]
    if len(valid) > 1:
        is_sorted = all(valid[i].dt <= valid[i + 1].dt for i in range(len(valid) - 1))  # type: ignore[operator]
        sorted_records = valid if is_sorted else sorted(valid, key=lambda r: r.dt)  # type: ignore[arg-type, return-value]
    else:
        sorted_records = valid

    outages: List[OutageEvent] = []
    cur_down: Optional[List[NetRecord]] = None

    for r in sorted_records:
        if cur_down:
            gap = (r.dt - cur_down[-1].dt).total_seconds()  # type: ignore[operator]
            if gap > gap_limit_sec:
                # Close previous outage due to gap
                _append_outage(outages, cur_down, "DOWN", check_interval_sec)
                cur_down = None

        if r.status == "DOWN":
            if cur_down is None:
                cur_down = [r]
            else:
                cur_down.append(r)
        else:
            if cur_down is not None:
                _append_outage(outages, cur_down, "DOWN", check_interval_sec)
                cur_down = None

    if cur_down is not None:
        _append_outage(outages, cur_down, "DOWN", check_interval_sec)

    # Optional: detect sustained BAD periods > min_bad_duration_sec
    if include_bad:
        cur_bad: Optional[List[NetRecord]] = None
        for r in sorted_records:
            if cur_bad:
                gap = (r.dt - cur_bad[-1].dt).total_seconds()  # type: ignore[operator]
                if gap > gap_limit_sec:
                    _check_and_append_bad(
                        outages, cur_bad, min_bad_duration_sec, check_interval_sec
                    )
                    cur_bad = None

            if r.status == "BAD":
                if cur_bad is None:
                    cur_bad = [r]
                else:
                    cur_bad.append(r)
            else:
                if cur_bad is not None:
                    _check_and_append_bad(
                        outages, cur_bad, min_bad_duration_sec, check_interval_sec
                    )
                    cur_bad = None

        if cur_bad is not None:
            _check_and_append_bad(
                outages, cur_bad, min_bad_duration_sec, check_interval_sec
            )

    # Return sorted chronologically
    outages.sort(key=lambda o: o.start_time)
    return outages


def _append_outage(
    outages: List[OutageEvent],
    records: List[NetRecord],
    status: str,
    check_interval_sec: int,
) -> None:
    """Helper to convert list of contiguous records into an OutageEvent."""
    if not records or not records[0].dt or not records[-1].dt:
        return
    start = records[0].dt
    end = records[-1].dt
    duration = max(check_interval_sec, (end - start).total_seconds() + check_interval_sec)
    network = records[0].network
    conn = records[0].conn
    outages.append(
        OutageEvent(
            start_time=start,
            end_time=end,
            duration_sec=duration,
            status=status,
            network=network,
            conn=conn,
            checks_count=len(records),
        )
    )


def _check_and_append_bad(
    outages: List[OutageEvent],
    records: List[NetRecord],
    min_bad_duration_sec: int,
    check_interval_sec: int,
) -> None:
    """Helper to append sustained BAD period if it exceeds duration threshold."""
    if not records or not records[0].dt or not records[-1].dt:
        return
    start = records[0].dt
    end = records[-1].dt
    duration = max(check_interval_sec, (end - start).total_seconds() + check_interval_sec)
    if duration >= min_bad_duration_sec:
        _append_outage(outages, records, "BAD", check_interval_sec)


def find_gaps(
    net_records: Sequence[NetRecord], gap_limit_sec: int = 120
) -> List[GapEvent]:
    """Find missing periods where no records were logged (PC asleep, monitor stopped)."""
    if len(net_records) < 2:
        return []

    valid = [r for r in net_records if r.dt is not None]
    if len(valid) > 1:
        is_sorted = all(valid[i].dt <= valid[i + 1].dt for i in range(len(valid) - 1))  # type: ignore[operator]
        sorted_records = valid if is_sorted else sorted(valid, key=lambda r: r.dt)  # type: ignore[arg-type, return-value]
    else:
        sorted_records = valid

    gaps: List[GapEvent] = []
    for prev, cur in zip(sorted_records, sorted_records[1:]):
        assert prev.dt is not None and cur.dt is not None
        diff = (cur.dt - prev.dt).total_seconds()
        if diff > gap_limit_sec:
            gaps.append(
                GapEvent(
                    start_time=prev.dt,
                    end_time=cur.dt,
                    duration_sec=diff,
                )
            )
    return gaps


def hourly_distribution(
    records: Sequence[Union[NetRecord, SpeedRecord]],
    key: str = "latency_ms",
) -> Dict[int, Dict[str, Any]]:
    """Compute hourly metrics (0-23) for a given attribute in a single O(n) pass."""
    by_hour: List[List[float]] = [[] for _ in range(24)]
    for r in records:
        if r.dt is not None:
            v = getattr(r, key, None)
            if v is not None:
                by_hour[r.dt.hour].append(float(v))

    result: Dict[int, Dict[str, Any]] = {}
    for h in range(24):
        vals = by_hour[h]
        if vals:
            result[h] = {
                "count": len(vals),
                "avg": round(statistics.mean(vals), 2),
                "median": round(statistics.median(vals), 2),
                "min": round(min(vals), 2),
                "max": round(max(vals), 2),
            }
        else:
            result[h] = {
                "count": 0,
                "avg": None,
                "median": None,
                "min": None,
                "max": None,
            }
    return result


def best_and_worst_hours(
    records: Sequence[Union[NetRecord, SpeedRecord]],
    key: str = "latency_ms",
) -> Tuple[Optional[Tuple[int, float]], Optional[Tuple[int, float]]]:
    """Return ((best_hour, best_val), (worst_hour, worst_val)).

    For latency: lowest is best, highest is worst.
    For speed: highest is best, lowest is worst.
    """
    dist = hourly_distribution(records, key=key)
    valid = [(h, d["avg"]) for h, d in dist.items() if d["avg"] is not None]
    if not valid:
        return None, None

    if key == "download_mbps":
        best = max(valid, key=lambda x: x[1])
        worst = min(valid, key=lambda x: x[1])
    else:
        best = min(valid, key=lambda x: x[1])
        worst = max(valid, key=lambda x: x[1])

    return best, worst


def compare_networks(
    net_records: Sequence[NetRecord],
    speed_records: Optional[Sequence[SpeedRecord]] = None,
    check_interval_sec: int = DEFAULT_CHECK_INTERVAL_SEC,
) -> Dict[str, Any]:
    """Compare performance across all detected providers and evening hours (18:00-22:00) in O(n)."""
    from collections import defaultdict

    net_by_prov: Dict[str, List[NetRecord]] = defaultdict(list)
    eve_net_by_prov: Dict[str, List[NetRecord]] = defaultdict(list)

    for r in net_records:
        if r.network and r.network != "unknown":
            net_by_prov[r.network].append(r)
            if r.dt is not None and 18 <= r.dt.hour < 22:
                eve_net_by_prov[r.network].append(r)

    spd_by_prov: Dict[str, List[SpeedRecord]] = defaultdict(list)
    eve_spd_by_prov: Dict[str, List[SpeedRecord]] = defaultdict(list)

    if speed_records:
        for s in speed_records:
            if s.network and s.network != "unknown":
                spd_by_prov[s.network].append(s)
                if s.dt is not None and 18 <= s.dt.hour < 22:
                    eve_spd_by_prov[s.network].append(s)

    providers = sorted(net_by_prov.keys())
    per_provider: Dict[str, Dict[str, Any]] = {}

    for prov in providers:
        net_sub = net_by_prov[prov]
        spd_sub = spd_by_prov[prov]
        overall_summary = summarize(net_sub, spd_sub, check_interval_sec)

        evening_net = eve_net_by_prov[prov]
        evening_spd = eve_spd_by_prov[prov]
        evening_summary = summarize(evening_net, evening_spd, check_interval_sec)

        per_provider[prov] = {
            "overall": overall_summary,
            "evening": evening_summary,
            "evening_checks": len(evening_net),
            "evening_hours": round(len(evening_net) * check_interval_sec / 3600.0, 2),
        }

    # Best provider overall: prioritize good_pct then lowest ping_median
    best_overall: Optional[str] = None
    if per_provider:
        ranked = sorted(
            per_provider.items(),
            key=lambda item: (
                -(item[1]["overall"].good_pct or 0),
                item[1]["overall"].ping_median if item[1]["overall"].ping_median is not None else 9999,
            ),
        )
        best_overall = ranked[0][0]

    # Best provider evening
    best_evening: Optional[str] = None
    valid_evening = [
        item for item in per_provider.items() if item[1]["evening"].checks > 0
    ]
    if valid_evening:
        ranked_eve = sorted(
            valid_evening,
            key=lambda item: (
                -(item[1]["evening"].good_pct or 0),
                item[1]["evening"].ping_median if item[1]["evening"].ping_median is not None else 9999,
            ),
        )
        best_evening = ranked_eve[0][0]

    # Detect if comparison covers drastically different time distribution
    warning: Optional[str] = None
    if len(per_provider) > 1:
        hours_list = [item["overall"].hours for item in per_provider.values()]
        eve_ratio = [
            item["evening_hours"] / max(0.1, item["overall"].hours)
            for item in per_provider.values()
        ]
        if max(hours_list) > 3 * min(hours_list) or (max(eve_ratio) - min(eve_ratio)) > 0.35:
            warning = "Caution: Providers have significantly different sample volumes or evening proportions. Comparison may be skewed."

    return {
        "providers": per_provider,
        "best_overall": best_overall,
        "best_evening": best_evening,
        "warning": warning,
    }


def busy_vs_idle(
    net_records: Sequence[NetRecord],
    busy_threshold_kbps: float = DEFAULT_BUSY_KBPS,
    check_interval_sec: int = DEFAULT_CHECK_INTERVAL_SEC,
) -> Dict[str, Any]:
    """Segregate records into PC busy vs idle to isolate PC usage from ISP problems."""
    busy_records: List[NetRecord] = []
    idle_records: List[NetRecord] = []

    for r in net_records:
        if r.pc_down_kbps is None and r.pc_up_kbps is None:
            continue
        total_kbps = (r.pc_down_kbps or 0.0) + (r.pc_up_kbps or 0.0)
        if total_kbps > busy_threshold_kbps:
            busy_records.append(r)
        else:
            idle_records.append(r)

    return {
        "busy": summarize(busy_records, check_interval_sec=check_interval_sec),
        "idle": summarize(idle_records, check_interval_sec=check_interval_sec),
        "threshold_kbps": busy_threshold_kbps,
    }


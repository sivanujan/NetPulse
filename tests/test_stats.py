"""Unit tests for NetPulse statistical analysis: median, uptime, outages, gaps, and comparisons."""

import unittest
from datetime import datetime, timedelta

from core.stats import (
    GapEvent,
    OutageEvent,
    SummaryStats,
    best_and_worst_hours,
    busy_vs_idle,
    compare_networks,
    find_gaps,
    find_outages,
    hourly_distribution,
    summarize,
)
from core.storage import NetRecord, SpeedRecord


class TestNetPulseStats(unittest.TestCase):
    """Test suite for core/stats.py functions."""

    def test_summarize_empty(self) -> None:
        """Empty records return default zeroed summary without raising exceptions."""
        res = summarize([])
        self.assertEqual(res.checks, 0)
        self.assertEqual(res.uptime_pct, 0.0)
        self.assertEqual(res.good_pct, 0.0)
        self.assertIsNone(res.ping_median)
        self.assertIsNone(res.ping_avg)
        self.assertEqual(res.loss_avg, 0.0)

    def test_median_and_average_ping(self) -> None:
        """Verify median and mean calculations on odd, even, and None-containing latency lists."""
        base_time = datetime(2026, 11, 8, 12, 0, 0)
        # Latencies: 50.0, 70.0, 90.0 -> median 70.0, avg 70.0
        records_odd = [
            NetRecord(
                time=(base_time + timedelta(seconds=i * 30)).strftime("%Y-%m-%d %H:%M:%S"),
                latency_ms=lat,
                loss_pct=0.0,
                dns_ms=5.0,
                status="OK",
            )
            for i, lat in enumerate([50.0, 70.0, 90.0])
        ]
        res_odd = summarize(records_odd)
        self.assertEqual(res_odd.ping_median, 70.0)
        self.assertEqual(res_odd.ping_avg, 70.0)

        # Even count: 50.0, 60.0, 80.0, 100.0 -> median 70.0, avg 72.5
        records_even = [
            NetRecord(
                time=(base_time + timedelta(seconds=i * 30)).strftime("%Y-%m-%d %H:%M:%S"),
                latency_ms=lat,
                loss_pct=0.0,
                dns_ms=5.0,
                status="OK",
            )
            for i, lat in enumerate([50.0, 60.0, 80.0, 100.0])
        ]
        res_even = summarize(records_even)
        self.assertEqual(res_even.ping_median, 70.0)
        self.assertEqual(res_even.ping_avg, 72.5)

        # Mixed with None / missing latency (e.g. timeout / down)
        records_with_none = [
            NetRecord(
                time=(base_time + timedelta(seconds=i * 30)).strftime("%Y-%m-%d %H:%M:%S"),
                latency_ms=lat,
                loss_pct=loss,
                dns_ms=None,
                status=st,
            )
            for i, (lat, loss, st) in enumerate([
                (40.0, 0.0, "OK"),
                (None, 100.0, "DOWN"),
                (60.0, 0.0, "OK"),
                (80.0, 0.0, "OK"),
            ])
        ]
        res_none = summarize(records_with_none)
        # Valid latencies are [40.0, 60.0, 80.0] -> median 60.0, avg 60.0
        self.assertEqual(res_none.ping_median, 60.0)
        self.assertEqual(res_none.ping_avg, 60.0)
        self.assertEqual(res_none.checks, 4)

    def test_uptime_and_good_pct(self) -> None:
        """Verify uptime % and good % calculation under mixed network states."""
        base_time = datetime(2026, 11, 8, 10, 0, 0)
        # 10 checks total: 7 OK, 2 BAD, 1 DOWN
        # Uptime = 100 * (10 - 1) / 10 = 90.0%
        # Good   = 100 * (10 - 1 - 2) / 10 = 70.0%
        statuses = ["OK", "OK", "BAD", "OK", "OK", "DOWN", "OK", "OK", "BAD", "OK"]
        records = [
            NetRecord(
                time=(base_time + timedelta(seconds=i * 30)).strftime("%Y-%m-%d %H:%M:%S"),
                latency_ms=50.0 if st == "OK" else (350.0 if st == "BAD" else None),
                loss_pct=0.0 if st == "OK" else (30.0 if st == "BAD" else 100.0),
                dns_ms=5.0,
                status=st,
            )
            for i, st in enumerate(statuses)
        ]
        res = summarize(records)
        self.assertEqual(res.checks, 10)
        self.assertEqual(res.down_count, 1)
        self.assertEqual(res.bad_count, 2)
        self.assertEqual(res.ok_count, 7)
        self.assertEqual(res.uptime_pct, 90.0)
        self.assertEqual(res.good_pct, 70.0)

    def test_find_outages(self) -> None:
        """Verify grouping of contiguous DOWN events into single outage intervals."""
        t0 = datetime(2026, 11, 8, 14, 0, 0)
        # Timeline (every 30s):
        # 0s: OK
        # 30s: DOWN  \ Outage 1 (30s -> 90s, approx 90s duration)
        # 60s: DOWN   |
        # 90s: DOWN  /
        # 120s: OK
        # 150s: OK
        # 180s: DOWN \ Outage 2 (180s -> 180s, single check 30s duration)
        # 210s: OK
        records = [
            NetRecord(time=(t0 + timedelta(seconds=0)).strftime("%Y-%m-%d %H:%M:%S"), latency_ms=50.0, loss_pct=0.0, dns_ms=5.0, status="OK", network="Dialog", conn="iPhone USB", dt=t0 + timedelta(seconds=0)),
            NetRecord(time=(t0 + timedelta(seconds=30)).strftime("%Y-%m-%d %H:%M:%S"), latency_ms=None, loss_pct=100.0, dns_ms=None, status="DOWN", network="Dialog", conn="iPhone USB", dt=t0 + timedelta(seconds=30)),
            NetRecord(time=(t0 + timedelta(seconds=60)).strftime("%Y-%m-%d %H:%M:%S"), latency_ms=None, loss_pct=100.0, dns_ms=None, status="DOWN", network="Dialog", conn="iPhone USB", dt=t0 + timedelta(seconds=60)),
            NetRecord(time=(t0 + timedelta(seconds=90)).strftime("%Y-%m-%d %H:%M:%S"), latency_ms=None, loss_pct=100.0, dns_ms=None, status="DOWN", network="Dialog", conn="iPhone USB", dt=t0 + timedelta(seconds=90)),
            NetRecord(time=(t0 + timedelta(seconds=120)).strftime("%Y-%m-%d %H:%M:%S"), latency_ms=55.0, loss_pct=0.0, dns_ms=5.0, status="OK", network="Dialog", conn="iPhone USB", dt=t0 + timedelta(seconds=120)),
            NetRecord(time=(t0 + timedelta(seconds=150)).strftime("%Y-%m-%d %H:%M:%S"), latency_ms=52.0, loss_pct=0.0, dns_ms=5.0, status="OK", network="Dialog", conn="iPhone USB", dt=t0 + timedelta(seconds=150)),
            NetRecord(time=(t0 + timedelta(seconds=180)).strftime("%Y-%m-%d %H:%M:%S"), latency_ms=None, loss_pct=100.0, dns_ms=None, status="DOWN", network="Dialog", conn="iPhone USB", dt=t0 + timedelta(seconds=180)),
            NetRecord(time=(t0 + timedelta(seconds=210)).strftime("%Y-%m-%d %H:%M:%S"), latency_ms=51.0, loss_pct=0.0, dns_ms=5.0, status="OK", network="Dialog", conn="iPhone USB", dt=t0 + timedelta(seconds=210)),
        ]

        outages = find_outages(records, gap_limit_sec=120, check_interval_sec=30)
        self.assertEqual(len(outages), 2)

        outage1 = outages[0]
        self.assertEqual(outage1.start_time, t0 + timedelta(seconds=30))
        self.assertEqual(outage1.end_time, t0 + timedelta(seconds=90))
        self.assertEqual(outage1.checks_count, 3)
        self.assertEqual(outage1.duration_sec, 90.0)
        self.assertEqual(outage1.network, "Dialog")
        self.assertEqual(outage1.conn, "iPhone USB")

        outage2 = outages[1]
        self.assertEqual(outage2.start_time, t0 + timedelta(seconds=180))
        self.assertEqual(outage2.end_time, t0 + timedelta(seconds=180))
        self.assertEqual(outage2.checks_count, 1)
        self.assertEqual(outage2.duration_sec, 30.0)

    def test_outage_split_by_gap(self) -> None:
        """A DOWN check separated by a large time gap (> gap_limit) starts a new outage."""
        t0 = datetime(2026, 11, 8, 10, 0, 0)
        # Record 1 at 0s: DOWN
        # PC sleeps or loses power for 1 hour
        # Record 2 at 3600s: DOWN
        records = [
            NetRecord(time=t0.strftime("%Y-%m-%d %H:%M:%S"), latency_ms=None, loss_pct=100.0, dns_ms=None, status="DOWN", dt=t0),
            NetRecord(time=(t0 + timedelta(seconds=3600)).strftime("%Y-%m-%d %H:%M:%S"), latency_ms=None, loss_pct=100.0, dns_ms=None, status="DOWN", dt=t0 + timedelta(seconds=3600)),
        ]
        outages = find_outages(records, gap_limit_sec=120, check_interval_sec=30)
        # Should be two separate outages because of the 1-hour gap
        self.assertEqual(len(outages), 2)
        self.assertEqual(outages[0].duration_sec, 30.0)
        self.assertEqual(outages[1].duration_sec, 30.0)

    def test_find_gaps(self) -> None:
        """Verify detection of missing data intervals when PC is off/asleep."""
        t0 = datetime(2026, 11, 8, 8, 0, 0)
        # Regular 30s checks, then a 20-minute jump (1200s), then regular checks
        records = [
            NetRecord(time=(t0 + timedelta(seconds=0)).strftime("%Y-%m-%d %H:%M:%S"), latency_ms=50.0, loss_pct=0.0, dns_ms=5.0, status="OK", dt=t0 + timedelta(seconds=0)),
            NetRecord(time=(t0 + timedelta(seconds=30)).strftime("%Y-%m-%d %H:%M:%S"), latency_ms=52.0, loss_pct=0.0, dns_ms=5.0, status="OK", dt=t0 + timedelta(seconds=30)),
            # 20-minute gap: next check at 1230s
            NetRecord(time=(t0 + timedelta(seconds=1230)).strftime("%Y-%m-%d %H:%M:%S"), latency_ms=48.0, loss_pct=0.0, dns_ms=5.0, status="OK", dt=t0 + timedelta(seconds=1230)),
            NetRecord(time=(t0 + timedelta(seconds=1260)).strftime("%Y-%m-%d %H:%M:%S"), latency_ms=49.0, loss_pct=0.0, dns_ms=5.0, status="OK", dt=t0 + timedelta(seconds=1260)),
        ]

        gaps = find_gaps(records, gap_limit_sec=120)
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].start_time, t0 + timedelta(seconds=30))
        self.assertEqual(gaps[0].end_time, t0 + timedelta(seconds=1230))
        self.assertEqual(gaps[0].duration_sec, 1200.0)

    def test_hourly_distribution_and_best_worst(self) -> None:
        """Verify 24-hour bucketing and selection of best and worst hours."""
        records = [
            # Hour 10: 60 ms avg
            NetRecord(time="2026-11-08 10:10:00", latency_ms=50.0, loss_pct=0.0, dns_ms=5.0, status="OK", dt=datetime(2026, 11, 8, 10, 10, 0)),
            NetRecord(time="2026-11-08 10:40:00", latency_ms=70.0, loss_pct=0.0, dns_ms=5.0, status="OK", dt=datetime(2026, 11, 8, 10, 40, 0)),
            # Hour 20 (evening peak): 250 ms avg
            NetRecord(time="2026-11-08 20:15:00", latency_ms=220.0, loss_pct=0.0, dns_ms=5.0, status="OK", dt=datetime(2026, 11, 8, 20, 15, 0)),
            NetRecord(time="2026-11-08 20:45:00", latency_ms=280.0, loss_pct=0.0, dns_ms=5.0, status="OK", dt=datetime(2026, 11, 8, 20, 45, 0)),
        ]
        dist = hourly_distribution(records, key="latency_ms")
        self.assertEqual(dist[10]["count"], 2)
        self.assertEqual(dist[10]["avg"], 60.0)
        self.assertEqual(dist[20]["count"], 2)
        self.assertEqual(dist[20]["avg"], 250.0)
        self.assertEqual(dist[0]["count"], 0)
        self.assertIsNone(dist[0]["avg"])

        best, worst = best_and_worst_hours(records, key="latency_ms")
        self.assertIsNotNone(best)
        self.assertIsNotNone(worst)
        assert best is not None and worst is not None
        self.assertEqual(best[0], 10)   # 10:00 is lowest ping (best)
        self.assertEqual(best[1], 60.0)
        self.assertEqual(worst[0], 20)  # 20:00 is highest ping (worst)
        self.assertEqual(worst[1], 250.0)

    def test_compare_networks(self) -> None:
        """Verify comparison across providers and evening filter identification."""
        records = [
            # Dialog daytime (10:00)
            NetRecord(time="2026-11-08 10:00:00", latency_ms=60.0, loss_pct=0.0, dns_ms=5.0, status="OK", network="Dialog", conn="iPhone USB", dt=datetime(2026, 11, 8, 10, 0, 0)),
            # Dialog evening (20:00)
            NetRecord(time="2026-11-08 20:00:00", latency_ms=90.0, loss_pct=0.0, dns_ms=5.0, status="OK", network="Dialog", conn="iPhone USB", dt=datetime(2026, 11, 8, 20, 0, 0)),
            # Mobitel daytime (10:00)
            NetRecord(time="2026-11-08 10:00:00", latency_ms=80.0, loss_pct=0.0, dns_ms=5.0, status="OK", network="Mobitel", conn="iPhone USB", dt=datetime(2026, 11, 8, 10, 0, 0)),
            # Mobitel evening (20:00) - congested
            NetRecord(time="2026-11-08 20:00:00", latency_ms=250.0, loss_pct=10.0, dns_ms=15.0, status="OK", network="Mobitel", conn="iPhone USB", dt=datetime(2026, 11, 8, 20, 0, 0)),
        ]
        res = compare_networks(records)
        self.assertIn("Dialog", res["providers"])
        self.assertIn("Mobitel", res["providers"])

        dialog_stats = res["providers"]["Dialog"]
        mobitel_stats = res["providers"]["Mobitel"]

        self.assertEqual(dialog_stats["overall"].checks, 2)
        self.assertEqual(mobitel_stats["overall"].checks, 2)

        # Dialog evening median ping (90.0) vs Mobitel evening median ping (250.0)
        self.assertEqual(dialog_stats["evening"].ping_median, 90.0)
        self.assertEqual(mobitel_stats["evening"].ping_median, 250.0)

        # Dialog has lower latency and 100% good in evening
        self.assertEqual(res["best_overall"], "Dialog")
        self.assertEqual(res["best_evening"], "Dialog")

    def test_busy_vs_idle(self) -> None:
        """Verify segmentation of records into PC busy vs idle based on threshold."""
        records = [
            # Idle records (total <= 300 kbps)
            NetRecord(time="2026-11-08 12:00:00", latency_ms=50.0, loss_pct=0.0, dns_ms=5.0, status="OK", pc_down_kbps=20.0, pc_up_kbps=10.0, dt=datetime(2026, 11, 8, 12, 0, 0)),
            NetRecord(time="2026-11-08 12:00:30", latency_ms=55.0, loss_pct=0.0, dns_ms=5.0, status="OK", pc_down_kbps=40.0, pc_up_kbps=30.0, dt=datetime(2026, 11, 8, 12, 0, 30)),
            # Busy record (total > 300 kbps)
            NetRecord(time="2026-11-08 12:01:00", latency_ms=180.0, loss_pct=5.0, dns_ms=12.0, status="OK", pc_down_kbps=450.0, pc_up_kbps=120.0, dt=datetime(2026, 11, 8, 12, 1, 0)),
        ]
        res = busy_vs_idle(records, busy_threshold_kbps=300.0)
        self.assertEqual(res["idle"].checks, 2)
        self.assertEqual(res["idle"].ping_median, 52.5)
        self.assertEqual(res["busy"].checks, 1)
        self.assertEqual(res["busy"].ping_median, 180.0)


if __name__ == "__main__":
    unittest.main()


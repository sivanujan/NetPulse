"""Complaint and diagnostic report generator for NetPulse.

Produces high-resolution PDF and PNG reports suitable for ISP / TRCSL dispute submission,
plus CSV exports of the filtered data slice.
"""

from __future__ import annotations

import csv
import os
import sys
from datetime import datetime, timedelta
from typing import List, Optional, Sequence, Tuple

from core.config import NET_HEADER, Config
from core.stats import find_gaps, find_outages, hourly_distribution, summarize
from core.storage import NetRecord, SpeedRecord


def export_filtered_csv(records: Sequence[NetRecord], out_csv_path: str) -> None:
    """Export filtered net records to standard CSV file."""
    os.makedirs(os.path.dirname(os.path.abspath(out_csv_path)), exist_ok=True)
    with open(out_csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(NET_HEADER)
        for r in records:
            writer.writerow(r.to_csv_row())


def generate_complaint_report(
    net_records: Sequence[NetRecord],
    speed_records: Sequence[SpeedRecord],
    config: Config,
    out_pdf_path: str,
    out_png_path: str,
    date_label: str = "All Time",
    provider_filter: Optional[str] = None,
) -> Tuple[str, str]:
    """Generate both PDF and PNG complaint reports using pure object-oriented matplotlib."""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    import matplotlib.dates as mdates
    from matplotlib.figure import Figure

    if not net_records:
        raise ValueError("Cannot generate report: no network records match the selected filter.")

    sorted_net = sorted([r for r in net_records if r.dt is not None], key=lambda r: r.dt)
    if not sorted_net:
        raise ValueError("No valid timestamped records in selection.")

    sorted_spd = sorted([s for s in speed_records if s.dt is not None], key=lambda s: s.dt)

    t_start = sorted_net[0].dt
    t_end = sorted_net[-1].dt

    stats = summarize(sorted_net, sorted_spd)
    outages = find_outages(sorted_net, gap_limit_sec=180, include_bad=True)
    down_outages = [o for o in outages if o.status == "DOWN"]
    gaps = find_gaps(sorted_net, gap_limit_sec=180)

    # 1. Figure Setup (A4 proportioned, thread-safe OO Figure without pyplot)
    # Using clean white background with high contrast for printing/formal submission
    fig = Figure(figsize=(14, 20), dpi=150)
    FigureCanvasAgg(fig)
    axes = fig.subplots(5, 1)
    fig.patch.set_facecolor("#ffffff")

    # Header details
    sub_name = config.user_name if config.user_name else "Not Specified"
    sub_addr = config.user_address if config.user_address else "Not Specified"
    prov_str = provider_filter if provider_filter else "All Detected Networks"

    header_text = (
        f"NETPULSE — NETWORK QUALITY & OUTAGES COMPLAINT REPORT\n"
        f"Generated for Submission to: TRCSL (Telecommunications Regulatory Commission) / Service Provider\n"
        f"Subscriber Name: {sub_name}  |  Connection Location: {sub_addr}\n"
        f"Analysis Period: {date_label} ({t_start:%Y-%m-%d %H:%M} to {t_end:%Y-%m-%d %H:%M})  |  Network Filter: {prov_str}"
    )
    fig.suptitle(header_text, fontsize=12, fontweight="bold", y=0.985, linespacing=1.4)

    # Helper function for shading outages (red) and gaps (grey)
    def apply_shading(ax: Any) -> None:
        for out in down_outages:
            ax.axvspan(out.start_time, out.end_time, facecolor="#ef4444", edgecolor="none", alpha=0.35, zorder=1)
        for gap in gaps:
            ax.axvspan(gap.start_time, gap.end_time, facecolor="#9ca3af", edgecolor="none", alpha=0.25, hatch="//", zorder=1)

    # Subplot 1: Executive KPI Summary Box
    ax_table = axes[0]
    ax_table.axis("off")
    summary_data = [
        ["Total Duration", f"{stats.hours:.1f} hours ({stats.checks:,} checks)", "Overall Uptime", f"{stats.uptime_pct:.1f}%"],
        ["Good Quality Checks", f"{stats.good_pct:.0f}% (ping <300ms & loss <25%)", "Complete Outages (DOWN)", f"{len(down_outages)} ({sum(o.duration_sec for o in down_outages)/60.0:.1f} mins downtime)"],
        ["Median Ping Latency", f"{stats.ping_median or 0:.0f} ms (avg {stats.ping_avg or 0:.0f} ms)", "Average Packet Loss", f"{stats.loss_avg:.1f}%"],
        ["Avg Download Speed", f"{stats.speed_avg or 0:.1f} Mbps (best {stats.speed_max or 0:.1f} / worst {stats.speed_min or 0:.1f})", "Speed Tests Logged", f"{stats.speed_count} completed tests"],
    ]
    table = ax_table.table(
        cellText=summary_data,
        colWidths=[0.24, 0.26, 0.24, 0.26],
        loc="center",
        cellLoc="left",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(10)
    table.scale(1.0, 1.8)
    for (r_idx, c_idx), cell in table.get_celld().items():
        cell.set_edgecolor("#d1d5db")
        if c_idx in (0, 2):
            cell.set_facecolor("#f3f4f6")
            cell.set_text_props(weight="bold", color="#111827")
        else:
            cell.set_facecolor("#ffffff")
            cell.set_text_props(color="#1f2937")

    # Helper to insert NaNs over gaps so lines don't falsely bridge sleep/gaps
    def clean_timeseries(times: List[datetime], vals: List[float], max_gap_sec: float = 180.0):
        ot, ov = [], []
        for i, (ti, v) in enumerate(zip(times, vals)):
            if i and (ti - times[i - 1]).total_seconds() > max_gap_sec:
                ot.append(times[i - 1] + (ti - times[i - 1]) / 2)
                ov.append(float("nan"))
            ot.append(ti)
            ov.append(v)
        return ot, ov

    # Subplot 2: Download Speed (Mbps)
    ax_spd = axes[1]
    apply_shading(ax_spd)
    spd_times = [s.dt for s in sorted_spd if s.download_mbps is not None]
    spd_vals = [s.download_mbps for s in sorted_spd if s.download_mbps is not None]
    if spd_times:
        t_clean, v_clean = clean_timeseries(spd_times, spd_vals, max_gap_sec=3600.0)
        ax_spd.plot(t_clean, v_clean, marker="o", color="#2563eb", linewidth=1.5, markersize=4, label="Download Speed (Mbps)")
        ax_spd.legend(loc="upper right", framealpha=0.9)
    ax_spd.set_ylabel("Speed (Mbps)", fontweight="bold")
    ax_spd.set_title("1. Download Speed (Cloudflare Diagnostics)", fontsize=11, fontweight="bold", loc="left")
    ax_spd.grid(True, linestyle="--", alpha=0.5)

    # Subplot 3: Ping Latency & Loss
    ax_ping = axes[2]
    apply_shading(ax_ping)
    p_times = [r.dt for r in sorted_net]
    p_lats = [r.latency_ms if r.latency_ms is not None else float("nan") for r in sorted_net]
    t_clean_p, v_clean_p = clean_timeseries(p_times, p_lats, max_gap_sec=180.0)
    ax_ping.plot(t_clean_p, v_clean_p, color="#059669", linewidth=1.2, label="Ping Latency (ms)")
    ax_ping.axhline(150, color="#f59e0b", linestyle="--", linewidth=1.0, label="150ms Amber Threshold")
    ax_ping.axhline(300, color="#ef4444", linestyle="--", linewidth=1.2, label="300ms Unusable/Degraded Threshold")
    ax_ping.set_ylabel("Latency (ms)", fontweight="bold")
    ax_ping.set_title("2. Ping Latency (ms) [Red Shading = Outage, Grey Hatch = No Data / PC Off]", fontsize=11, fontweight="bold", loc="left")
    ax_ping.grid(True, linestyle="--", alpha=0.5)
    ax_ping.set_ylim(bottom=0)
    ax_ping.legend(loc="upper right", framealpha=0.9)

    # Subplot 4: PC Upload & Download Usage (Proves latency wasn't caused by PC upload)
    ax_pc = axes[3]
    apply_shading(ax_pc)
    pc_down = [r.pc_down_kbps if r.pc_down_kbps is not None else 0.0 for r in sorted_net]
    pc_up = [r.pc_up_kbps if r.pc_up_kbps is not None else 0.0 for r in sorted_net]
    t_pc, v_down = clean_timeseries(p_times, pc_down, max_gap_sec=180.0)
    _, v_up = clean_timeseries(p_times, pc_up, max_gap_sec=180.0)
    ax_pc.plot(t_pc, v_down, color="#0284c7", linewidth=1.0, alpha=0.8, label="PC Download (kbps)")
    ax_pc.plot(t_pc, v_up, color="#ea580c", linewidth=1.0, alpha=0.8, label="PC Upload (kbps)")
    ax_pc.axhline(500, color="#71717a", linestyle=":", linewidth=1.0, label="500 kbps High Upload Line")
    ax_pc.set_ylabel("Traffic (kbps)", fontweight="bold")
    ax_pc.set_title("3. Local PC Network Traffic (Confirms external network vs local saturation)", fontsize=11, fontweight="bold", loc="left")
    ax_pc.grid(True, linestyle="--", alpha=0.5)
    ax_pc.set_ylim(bottom=0)
    ax_pc.legend(loc="upper right", framealpha=0.9)

    # Format date axis across timeseries subplots
    for a in [ax_spd, ax_ping, ax_pc]:
        a.xaxis.set_major_formatter(mdates.DateFormatter("%d %b\n%H:%M"))
        if t_start == t_end:
            a.set_xlim(t_start - timedelta(minutes=5), t_end + timedelta(minutes=5))
        else:
            a.set_xlim(t_start, t_end)

    # Subplot 5: 24-Hour Hour-of-Day Congestion Profile
    ax_hourly = axes[4]
    dist = hourly_distribution(sorted_net, key="latency_ms")
    hours = list(range(24))
    avg_lats = [dist[h]["avg"] if dist[h]["avg"] is not None else 0.0 for h in hours]
    colors = [
        "#ef4444" if lat > 300 else ("#f59e0b" if lat >= 100 else "#10b981")
        for lat in avg_lats
    ]
    ax_hourly.bar(hours, avg_lats, width=0.65, color=colors, edgecolor="#374151", linewidth=0.5)
    ax_hourly.axvspan(17.5, 21.5, facecolor="#fef3c7", alpha=0.7, lw=1, linestyle="--", edgecolor="#f59e0b", label="Evening Peak Congestion (18:00–22:00)")
    ax_hourly.set_xlabel("Hour of Day (00:00 – 23:00)", fontweight="bold")
    ax_hourly.set_ylabel("Avg Ping (ms)", fontweight="bold")
    ax_hourly.set_title("4. 24-Hour Hourly Congestion Profile (Evidence of Evening Peak Congestion)", fontsize=11, fontweight="bold", loc="left")
    ax_hourly.set_xticks(hours)
    ax_hourly.grid(True, linestyle="--", alpha=0.5, axis="y")
    ax_hourly.legend(loc="upper right", framealpha=0.9)

    fig.tight_layout(rect=[0.02, 0.02, 0.98, 0.97])

    # Save PNG and PDF
    os.makedirs(os.path.dirname(os.path.abspath(out_png_path)), exist_ok=True)
    os.makedirs(os.path.dirname(os.path.abspath(out_pdf_path)), exist_ok=True)

    fig.savefig(out_png_path, dpi=180, facecolor=fig.get_facecolor(), edgecolor="none")
    fig.savefig(out_pdf_path, dpi=200, facecolor=fig.get_facecolor(), edgecolor="none")

    return out_pdf_path, out_png_path

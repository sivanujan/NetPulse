"""Downsampling utilities for dense time-series chart data."""

from __future__ import annotations

import math
from typing import List, Tuple


def downsample_series(
    times: List[float],
    values: List[float],
    max_points: int = 2000,
    gap_limit_sec: float = 180.0,
) -> Tuple[List[float], List[float]]:
    """Downsample time series to at most `max_points` points.

    Maintains peaks and breaks lines across gaps (inserting NaN).
    """
    n = len(times)
    if n <= max_points:
        return times, values

    bin_size = int(math.ceil(n / (max_points / 2.0)))
    if bin_size <= 1:
        return times, values

    out_times: List[float] = []
    out_vals: List[float] = []

    for i in range(0, n, bin_size):
        chunk_t = times[i : i + bin_size]
        chunk_v = values[i : i + bin_size]
        if not chunk_t:
            continue

        # Check for gap between previous point and chunk
        if out_times and (chunk_t[0] - out_times[-1]) > gap_limit_sec:
            out_times.append((out_times[-1] + chunk_t[0]) / 2.0)
            out_vals.append(float("nan"))

        # Filter out NaNs for min/max
        valid = [(t, v) for t, v in zip(chunk_t, chunk_v) if not math.isnan(v)]
        if not valid:
            out_times.append(chunk_t[0])
            out_vals.append(float("nan"))
            continue

        # Pick min and max to retain critical network peaks/drops
        min_pt = min(valid, key=lambda x: x[1])
        max_pt = max(valid, key=lambda x: x[1])

        # Preserve chronological order of min and max points in chunk
        if min_pt[0] <= max_pt[0]:
            out_times.extend([min_pt[0], max_pt[0]])
            out_vals.extend([min_pt[1], max_pt[1]])
        else:
            out_times.extend([max_pt[0], min_pt[0]])
            out_vals.extend([max_pt[1], min_pt[1]])

    return out_times, out_vals

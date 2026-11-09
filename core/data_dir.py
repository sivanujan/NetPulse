"""Data directory management and initial CSV migration helper for NetPulse."""

from __future__ import annotations

import glob
import os
import shutil
import sys
from typing import List, Optional


def get_default_data_dir() -> str:
    """Determine the appropriate data directory.

    When running as a packaged executable (frozen), defaults to %APPDATA%/NetPulse.
    When running from source, defaults to the project working directory.
    """
    if getattr(sys, "frozen", False):
        appdata = os.environ.get("APPDATA")
        if appdata:
            path = os.path.join(appdata, "NetPulse")
            os.makedirs(path, exist_ok=True)
            return path

    return os.path.abspath(".")


def migrate_existing_data_if_needed(target_dir: str, source_dir: Optional[str] = None) -> List[str]:
    """Safely copy (never move or delete) existing logs to target data directory if missing."""
    target_dir = os.path.abspath(target_dir)
    os.makedirs(target_dir, exist_ok=True)

    # If target already has net_log.csv, no migration needed
    target_net_csv = os.path.join(target_dir, "net_log.csv")
    if os.path.exists(target_net_csv) and os.path.getsize(target_net_csv) > 0:
        return []

    # Potential source directories to discover existing logs
    sources_to_try: List[str] = []
    if source_dir:
        sources_to_try.append(os.path.abspath(source_dir))

    # Also check directory next to executable / script
    exe_dir = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
    sources_to_try.append(exe_dir)
    sources_to_try.append(os.path.abspath("."))

    copied_files: List[str] = []

    for src in sources_to_try:
        if src == target_dir or not os.path.isdir(src):
            continue

        src_net_log = os.path.join(src, "net_log.csv")
        if os.path.exists(src_net_log):
            # Found existing logs! Copy files safely without deleting original
            files_to_copy = ["net_log.csv", "speed_log.csv", "netpulse_settings.json"]
            for fname in files_to_copy:
                src_file = os.path.join(src, fname)
                dest_file = os.path.join(target_dir, fname)
                if os.path.exists(src_file) and not os.path.exists(dest_file):
                    shutil.copy2(src_file, dest_file)
                    copied_files.append(fname)

            # Copy old/ folder logs if present
            src_old = os.path.join(src, "old")
            dest_old = os.path.join(target_dir, "old")
            if os.path.isdir(src_old):
                os.makedirs(dest_old, exist_ok=True)
                for f in glob.glob(os.path.join(src_old, "*.*")):
                    fname = os.path.basename(f)
                    dest_f = os.path.join(dest_old, fname)
                    if not os.path.exists(dest_f):
                        shutil.copy2(f, dest_f)
                        copied_files.append(f"old/{fname}")

            if copied_files:
                break

    return copied_files

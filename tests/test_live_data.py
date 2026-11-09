"""Test verifying core modules against real workspace data logs in strictly READ-ONLY mode."""

import os
import shutil
import tempfile
import unittest

from core.stats import (
    best_and_worst_hours,
    busy_vs_idle,
    compare_networks,
    find_gaps,
    find_outages,
    summarize,
)
from core.storage import Storage


class TestRealWorkspaceData(unittest.TestCase):
    """Verify that storage and stats execute cleanly on actual logs without modifying anything."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.mkdtemp()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_sync_and_analyze_workspace_logs(self) -> None:
        workspace_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        temp_db_path = os.path.join(self.tmp_dir, "temp_test_cache.db")

        # Storage reads CSVs from workspace_dir but writes cache ONLY to temp_db_path
        storage = Storage(base_dir=workspace_dir, db_path=temp_db_path)

        net_synced, speed_synced = storage.sync_from_csvs()
        self.assertGreater(net_synced, 0, "Should have synced records from net_log.csv")
        self.assertGreater(speed_synced, 0, "Should have synced records from speed_log.csv")

        # Load all records
        all_net = storage.get_net_records()
        all_speed = storage.get_speed_records()
        self.assertGreater(len(all_net), 1000)

        # Run summary
        summary = summarize(all_net, all_speed)
        self.assertGreater(summary.checks, 1000)
        self.assertGreater(summary.uptime_pct, 0.0)
        self.assertIsNotNone(summary.ping_median)

        # Find outages and gaps
        outages = find_outages(all_net)
        gaps = find_gaps(all_net)

        # Compare networks
        comparison = compare_networks(all_net, all_speed)
        self.assertTrue(len(comparison["providers"]) > 0)

        # Busy vs idle
        b_vs_i = busy_vs_idle(all_net)
        self.assertIsNotNone(b_vs_i["idle"])

        # Best / worst hours
        best, worst = best_and_worst_hours(all_net)
        self.assertIsNotNone(best)


if __name__ == "__main__":
    unittest.main()

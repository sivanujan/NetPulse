"""Unit tests for NetPulse monitor functions and calculations."""

import unittest
from unittest.mock import patch

from core.monitor import (
    TrafficTracker,
    clean_provider_name,
    ping_multiple,
)


class TestNetPulseMonitor(unittest.TestCase):
    """Test suite for monitor logic and measurements."""

    def test_clean_provider_name(self) -> None:
        """Verify that various ISP org strings map to expected short names."""
        self.assertEqual(clean_provider_name("AS8544 Dialog Axiata PLC"), "Dialog")
        self.assertEqual(clean_provider_name("AS45356 Mobitel Pvt Ltd"), "Mobitel")
        self.assertEqual(clean_provider_name("AS9329 Sri Lanka Telecom Internet"), "SLT")
        self.assertEqual(clean_provider_name("Hutchison Telecommunications Lanka"), "Hutch")
        self.assertEqual(clean_provider_name("Bharti Airtel Lanka (Private) Limited"), "Airtel")
        self.assertEqual(clean_provider_name("SpaceX Starlink"), "Starlink")
        self.assertEqual(clean_provider_name("Lanka Bell Limited"), "Lanka Bell")
        self.assertEqual(clean_provider_name("AS12345 CustomISP"), "CustomISP")

    @patch("core.monitor.ping_host")
    def test_ping_multiple_better_loss(self, mock_ping: unittest.mock.MagicMock) -> None:
        """Verify that multi-host ping uses the BETTER host's loss.

        If host 1 (8.8.8.8) has 0% loss (60ms) and host 2 (1.1.1.1) is blocked with 100% loss (None),
        the overall status should be OK with 0.0% loss, not BAD with 50% loss.
        """
        def fake_ping(host, count=4, timeout_ms=2000):
            if host == "8.8.8.8":
                return 60.0, 0.0
            else:
                return None, 100.0

        mock_ping.side_effect = fake_ping

        res = ping_multiple(["8.8.8.8", "1.1.1.1"])
        self.assertEqual(res["loss_pct"], 0.0)
        self.assertEqual(res["latency_ms"], 60.0)
        self.assertEqual(res["status"], "OK")

    @patch("core.monitor.ping_host")
    def test_ping_multiple_all_down(self, mock_ping: unittest.mock.MagicMock) -> None:
        """When all ping hosts fail, status is DOWN."""
        mock_ping.return_value = (None, 100.0)
        res = ping_multiple(["8.8.8.8", "1.1.1.1"])
        self.assertEqual(res["loss_pct"], 100.0)
        self.assertIsNone(res["latency_ms"])
        self.assertEqual(res["status"], "DOWN")

    @patch("core.monitor.ping_host")
    def test_ping_multiple_bad_status(self, mock_ping: unittest.mock.MagicMock) -> None:
        """Status is BAD if loss >= 25% or latency > 300ms."""
        # High latency (> 300 ms)
        mock_ping.return_value = (350.0, 0.0)
        res = ping_multiple(["8.8.8.8", "1.1.1.1"])
        self.assertEqual(res["status"], "BAD")

        # High loss (e.g. 50%)
        mock_ping.return_value = (80.0, 50.0)
        res = ping_multiple(["8.8.8.8", "1.1.1.1"])
        self.assertEqual(res["status"], "BAD")

    def test_traffic_tracker_rate_and_spike_rejection(self) -> None:
        """Verify PC traffic rate calculation and spike rejection."""
        tracker = TrafficTracker()

        # Mock internal byte counter fetching
        tracker._get_bytes = lambda ip: (1_000_000, 500_000)  # type: ignore[assignment]
        # Initial baseline check
        down, up = tracker.update("172.20.10.2")
        self.assertIsNone(down)
        self.assertIsNone(up)

        # After 10 seconds: received +1,000,000 bytes (8 Mbps = 8000 kbps), sent +200,000 bytes
        tracker.prev_time -= 10.0
        tracker._get_bytes = lambda ip: (2_000_000, 700_000)  # type: ignore[assignment]
        down, up = tracker.update("172.20.10.2")
        self.assertIsNotNone(down)
        self.assertIsNotNone(up)
        assert down is not None and up is not None
        self.assertAlmostEqual(down, 800.0, delta=10.0)  # 1MB in 10s = 800 kbps
        self.assertAlmostEqual(up, 160.0, delta=5.0)

        # Impossible spike test: e.g. 50 GB in 1 second (> 1 Gbps)
        tracker.prev_time -= 1.0
        tracker._get_bytes = lambda ip: (52_000_000_000, 700_000)  # type: ignore[assignment]
        down, up = tracker.update("172.20.10.2")
        self.assertIsNone(down, "Spike > 1 Gbps should be rejected")


if __name__ == "__main__":
    unittest.main()


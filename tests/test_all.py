"""
Unit tests for NetworkMonitor core modules.
"""

import os
import sys
import tempfile
import unittest
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import StatsDatabase
from core.throne import ThroneMonitor
from core.wifi import get_wifi_details, get_default_gateway_and_iface
from core.collector import NetworkCollector, format_bytes, format_speed


class TestStatsDatabase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_stats.db")
        self.db = StatsDatabase(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_record_and_query(self):
        # Record normal and vpn traffic
        self.db.record_traffic(normal_rx=1000, normal_tx=500, vpn_rx=2000, vpn_tx=1000)

        today = self.db.get_today_stats()
        self.assertEqual(today["normal_rx"], 1000)
        self.assertEqual(today["normal_tx"], 500)
        self.assertEqual(today["vpn_rx"], 2000)
        self.assertEqual(today["vpn_tx"], 1000)
        self.assertEqual(today["total_rx"], 3000)
        self.assertEqual(today["total_tx"], 1500)

        # Record more traffic
        self.db.record_traffic(normal_rx=500, normal_tx=200, vpn_rx=500, vpn_tx=200)
        today_updated = self.db.get_today_stats()
        self.assertEqual(today_updated["normal_rx"], 1500)
        self.assertEqual(today_updated["vpn_rx"], 2500)

        # Test history
        daily = self.db.get_daily_history(7)
        self.assertGreaterEqual(len(daily), 1)

        hourly = self.db.get_hourly_history(24)
        self.assertGreaterEqual(len(hourly), 1)

    def test_settings_persistence(self):
        self.db.set_setting("theme", "1")
        self.assertEqual(self.db.get_setting("theme"), "1")
        self.db.set_setting("theme", "2")
        self.assertEqual(self.db.get_setting("theme"), "2")

    def test_reset_data(self):
        self.db.record_traffic(100, 100, 200, 200)
        today = self.db.get_today_stats()
        self.assertGreater(today["total_rx"], 0)

        self.db.reset_today_stats()
        today_after = self.db.get_today_stats()
        self.assertEqual(today_after["total_rx"], 0)


class TestFormatting(unittest.TestCase):
    def test_format_bytes(self):
        self.assertEqual(format_bytes(500), "500 B")
        self.assertEqual(format_bytes(1024), "1.0 KB")
        self.assertEqual(format_bytes(1024 * 1024), "1.00 MB")
        self.assertEqual(format_bytes(1024 * 1024 * 1024 * 2), "2.00 GB")

    def test_format_speed(self):
        self.assertEqual(format_speed(500), "500 B/s")
        self.assertEqual(format_speed(1024 * 50), "50.0 KB/s")
        self.assertEqual(format_speed(1024 * 1024 * 3.5), "3.50 MB/s")


class TestWifiAndGateway(unittest.TestCase):
    def test_gateway_detection(self):
        iface, gw = get_default_gateway_and_iface()
        self.assertIsNotNone(iface)

    def test_wifi_details(self):
        details = get_wifi_details()
        self.assertIn("connected", details)
        self.assertIn("ssid", details)
        self.assertIn("signal", details)


class TestThroneIntegration(unittest.TestCase):
    def test_throne_read_only(self):
        tm = ThroneMonitor()
        summary = tm.get_status_summary()
        self.assertIn("is_running", summary)
        self.assertIn("tun_active", summary)
        self.assertIn("status_text", summary)

    def test_vpn_detector(self):
        from core.vpn_detector import VpnDetector
        vd = VpnDetector()
        summary = vd.get_status_summary()
        self.assertIn("is_running", summary)
        self.assertIn("tun_active", summary)
        self.assertIn("client_name", summary)
        self.assertIn("profile_type", summary)
        self.assertIn("running_tools", summary)


class TestCollector(unittest.TestCase):
    def test_collector_snapshot(self):
        collector = NetworkCollector(sample_interval=0.5)
        time.sleep(1.2)
        snap = collector.get_snapshot()
        self.assertIn("speeds", snap)
        self.assertIn("session_usage", snap)
        self.assertIn("today_usage", snap)
        self.assertIn("wifi", snap)
        self.assertIn("throne", snap)
        collector.stop()


if __name__ == "__main__":
    unittest.main()

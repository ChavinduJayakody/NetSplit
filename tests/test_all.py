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
from core.wifi import (
    get_wifi_details,
    get_default_gateway_and_iface,
    is_wireless_interface,
    is_virtual_interface,
    _get_lan_details_linux,
)
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

    def test_tray_and_startup_preferences(self):
        # Test defaults
        self.assertTrue(self.db.get_tray_enabled())
        self.assertTrue(self.db.get_minimize_to_tray())
        self.assertFalse(self.db.get_start_minimized())

        # Test toggling
        self.db.set_tray_enabled(False)
        self.assertFalse(self.db.get_tray_enabled())

        self.db.set_minimize_to_tray(False)
        self.assertFalse(self.db.get_minimize_to_tray())

        self.db.set_start_minimized(True)
        self.assertTrue(self.db.get_start_minimized())

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
        self.assertIn("conn_type", details)
        self.assertIn(details["conn_type"], ["LAN", "WLAN"])
        self.assertIn("type_label", details)
        self.assertIn(details["type_label"], ["Ethernet (LAN)", "Wi-Fi (WLAN)"])

    def test_virtual_interface_detection(self):
        virtual_ifaces = ["lo", "tun0", "throne-tun", "wg0", "tap0", "docker0", "br0", "veth01"]
        for iface in virtual_ifaces:
            self.assertTrue(is_virtual_interface(iface), f"{iface} should be identified as virtual")

        physical_ifaces = ["eth0", "eno1", "enp3s0", "wlan0", "wlp2s0"]
        for iface in physical_ifaces:
            self.assertFalse(is_virtual_interface(iface), f"{iface} should not be identified as virtual")

    def test_wireless_vs_lan_interface_detection(self):
        self.assertTrue(is_wireless_interface("wlan0"))
        self.assertTrue(is_wireless_interface("wlp2s0"))
        self.assertFalse(is_wireless_interface("eno1"))
        self.assertFalse(is_wireless_interface("eth0"))

    def test_lan_details_structure(self):
        # Test wired LAN details parser
        lan_info = _get_lan_details_linux("eno1")
        required_keys = [
            "connected", "conn_type", "type_label", "ssid", "bssid",
            "signal", "bars", "bitrate", "channel", "band", "security"
        ]
        for key in required_keys:
            self.assertIn(key, lan_info)
        self.assertEqual(lan_info["conn_type"], "LAN")
        self.assertEqual(lan_info["type_label"], "Ethernet (LAN)")


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


class TestUniversalVpnAndProxyDetection(unittest.TestCase):
    def setUp(self):
        from core.vpn_detector import VpnDetector
        self.vd = VpnDetector()

    def test_universal_adapter_auto_detection(self):
        """Test that diverse VPN/tunnel adapters are detected automatically."""
        test_adapters = [
            ("wg0", "WireGuard"),
            ("tailscale0", "Tailscale"),
            ("nordlynx", "NordVPN (NordLynx)"),
            ("proton0", "Proton VPN"),
            ("cscotun0", "Cisco AnyConnect"),
            ("tun3", "VPN / Proxy Tunnel"),
            ("fct_tun", "FortiClient"),
        ]
        for iface, expected_name in test_adapters:
            self.vd._cached_tun = None
            detected = self.vd.get_tun_interface_name(active_adapters=["wlan0", "eno1", iface])
            self.assertEqual(detected, iface, f"Expected {iface} to be detected as active TUN")
            inferred = self.vd._infer_client_name_from_adapter(detected)
            self.assertEqual(inferred, expected_name)

    def test_universal_client_process_detection(self):
        """Test that various VPN client processes are detected from the process table."""
        from unittest.mock import MagicMock, patch

        mock_procs = [
            {"name": "tailscaled", "cmdline": ["/usr/bin/tailscaled"]},
            {"name": "warp-svc", "cmdline": ["/usr/bin/warp-svc"]},
            {"name": "wireguard-go", "cmdline": ["wireguard-go", "wg0"]},
            {"name": "custom-vpn-client", "cmdline": ["/opt/custom-vpn-client"]},
        ]
        proc_objects = []
        for p in mock_procs:
            m = MagicMock()
            m.info = p
            proc_objects.append(m)

        with patch("psutil.process_iter", return_value=proc_objects):
            clients = self.vd.get_running_clients(force=True)
            client_names = [c["name"] for c in clients]
            self.assertIn("Tailscale", client_names)
            self.assertIn("Cloudflare WARP", client_names)
            self.assertIn("WireGuard", client_names)
            self.assertIn("custom-vpn-client", client_names)

    def test_synthesized_client_when_tun_is_active(self):
        """When an adapter is active but no process is found, synthesize client name from adapter."""
        from unittest.mock import patch
        with patch("psutil.process_iter", return_value=[]):
            clients = self.vd.get_running_clients(force=True, tun_iface="nordlynx")
            self.assertEqual(len(clients), 1)
            self.assertEqual(clients[0]["name"], "NordVPN (NordLynx)")


class TestWindowsCompatibility(unittest.TestCase):
    def test_windows_hidden_kwargs(self):
        from core.platform_utils import get_windows_hidden_kwargs
        import unittest.mock as mock
        import subprocess

        dummy_startupinfo = mock.MagicMock()
        dummy_startupinfo.dwFlags = 0
        dummy_startupinfo.wShowWindow = 0

        with mock.patch("platform.system", return_value="Windows"), \
             mock.patch.object(subprocess, "STARTUPINFO", return_value=dummy_startupinfo, create=True):
            kwargs = get_windows_hidden_kwargs()
            self.assertIn("creationflags", kwargs)
            self.assertEqual(kwargs["creationflags"], 0x08000000)
            self.assertIn("startupinfo", kwargs)
            self.assertEqual(kwargs["startupinfo"].wShowWindow, 0)

    def test_ensure_std_streams(self):
        from core.platform_utils import ensure_std_streams
        orig_stdout = sys.stdout
        try:
            sys.stdout = None
            ensure_std_streams()
            self.assertIsNotNone(sys.stdout)
        finally:
            if sys.stdout is not None and sys.stdout != orig_stdout:
                sys.stdout.close()
            sys.stdout = orig_stdout

    def test_windows_route_print_splits_physical_and_vpn(self):
        """Verify that on Windows, physical Wi-Fi and VPN TAP adapter are cleanly separated."""
        from unittest.mock import patch, MagicMock
        from core.wifi import get_default_gateway_and_iface
        from core.vpn_detector import VpnDetector

        sample_route_print = (
            "===========================================================================\n"
            "Interface List\n"
            " 15...00 ff 12 34 56 78 ......TAP-Windows Adapter V9\n"
            " 12...64 bc 58 16 a1 e3 ......Intel(R) Wi-Fi 6 AX201 160MHz\n"
            "===========================================================================\n"
            "IPv4 Route Table\n"
            "===========================================================================\n"
            "Active Routes:\n"
            "Network Destination        Netmask          Gateway       Interface  Metric\n"
            "          0.0.0.0          0.0.0.0         10.8.0.1        10.8.0.2       5\n"
            "          0.0.0.0          0.0.0.0      192.168.1.1     192.168.1.15     25\n"
            "===========================================================================\n"
        )
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = sample_route_print

        def mock_addrs():
            addr_vpn = MagicMock()
            addr_vpn.address = "10.8.0.2"
            addr_wifi = MagicMock()
            addr_wifi.address = "192.168.1.15"
            return {
                "Ethernet 2": [addr_vpn],
                "Wi-Fi": [addr_wifi],
            }

        with patch("platform.system", return_value="Windows"):
            with patch("core.wifi.run_command_hidden", return_value=mock_proc):
                with patch("psutil.net_if_addrs", side_effect=mock_addrs):
                    # 1. Physical gateway must pick Wi-Fi (not the TAP VPN)
                    iface, gw = get_default_gateway_and_iface(force=True)
                    self.assertEqual(iface, "Wi-Fi")
                    self.assertEqual(gw, "192.168.1.1")

        with patch("platform.system", return_value="Windows"):
            with patch("core.vpn_detector.run_command_hidden", return_value=mock_proc):
                with patch("psutil.net_if_addrs", side_effect=mock_addrs):
                    # 2. TUN detection must identify Ethernet 2 (the metric 5 VPN tunnel)
                    vd = VpnDetector()
                    vpn_iface = vd.get_tun_interface_name(active_adapters=["Wi-Fi", "Ethernet 2"])
                    self.assertEqual(vpn_iface, "Ethernet 2")


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


class TestAutostartAndTray(unittest.TestCase):
    def test_autostart_toggle(self):
        from core.autostart import is_autostart_supported, is_autostart_enabled, set_autostart
        self.assertTrue(is_autostart_supported())

        initial_state = is_autostart_enabled()
        try:
            # Test enabling
            res = set_autostart(True)
            self.assertTrue(res)
            self.assertTrue(is_autostart_enabled())

            # Test disabling
            res = set_autostart(False)
            self.assertTrue(res)
            self.assertFalse(is_autostart_enabled())
        finally:
            # Restore initial state
            set_autostart(initial_state)

    def test_tray_controller_lifecycle(self):
        from core.tray import create_tray_controller
        activated = []
        tray = create_tray_controller(on_activate=lambda: activated.append(True))
        tray.start()
        tray.update_stats("5.2 MB/s", "1.1 MB/s", True)
        tray.update_tooltip("Testing Tray Tooltip")
        tray.stop()
        self.assertFalse(tray.is_running)


class TestSecurityAndPrivacy(unittest.TestCase):
    def test_mask_ip(self):
        from core.security import mask_ip
        # IPv4
        self.assertEqual(mask_ip("192.168.1.100"), "192.168.***.***")
        self.assertEqual(mask_ip("112.134.72.19"), "112.134.***.***")
        # Sentinels
        self.assertEqual(mask_ip("Checking..."), "Checking...")
        self.assertEqual(mask_ip("N/A"), "N/A")
        self.assertEqual(mask_ip("Disconnected"), "Disconnected")
        self.assertEqual(mask_ip("--"), "--")
        # IPv6
        v6_masked = mask_ip("2402:4000:21c0:1234:5678:9abc:def0:1234")
        self.assertTrue(v6_masked.startswith("2402:4000:****"))

    def test_validate_host(self):
        from core.security import validate_host
        self.assertTrue(validate_host("1.1.1.1"))
        self.assertTrue(validate_host("google.com"))
        self.assertTrue(validate_host("192.168.1.1"))
        # Injections & dangerous values
        self.assertFalse(validate_host("-c 1"))
        self.assertFalse(validate_host("; cat /etc/passwd"))
        self.assertFalse(validate_host("host & reboot"))
        self.assertFalse(validate_host(""))
        self.assertFalse(validate_host(None))

    def test_validate_ip(self):
        from core.security import validate_ip
        self.assertTrue(validate_ip("127.0.0.1"))
        self.assertTrue(validate_ip("1.1.1.1"))
        self.assertTrue(validate_ip("::1"))
        self.assertFalse(validate_ip("invalid_ip"))
        self.assertFalse(validate_ip("256.256.256.256"))
        self.assertFalse(validate_ip("1.1.1.1; rm"))

    def test_sanitize_static_path(self):
        import tempfile
        from core.security import sanitize_static_path
        with tempfile.TemporaryDirectory() as td:
            test_file = os.path.join(td, "app.js")
            with open(test_file, "w") as f:
                f.write("console.log(1);")

            # Normal path
            res = sanitize_static_path(td, "app.js")
            self.assertEqual(res, test_file)

            # Traversal attempts
            self.assertIsNone(sanitize_static_path(td, "../../../etc/passwd"))
            self.assertIsNone(sanitize_static_path(td, "..\\..\\windows\\system32"))

    def test_db_mask_setting(self):
        import tempfile
        from core.database import StatsDatabase
        with tempfile.TemporaryDirectory() as td:
            db = StatsDatabase(os.path.join(td, "test_mask.db"))
            # Default is True
            self.assertTrue(db.get_mask_ips())
            db.set_mask_ips(False)
            self.assertFalse(db.get_mask_ips())
            db.set_mask_ips(True)
            self.assertTrue(db.get_mask_ips())

    def test_db_exclusive_mode_setting(self):
        import tempfile
        from core.database import StatsDatabase
        with tempfile.TemporaryDirectory() as td:
            db = StatsDatabase(os.path.join(td, "test_excl.db"))
            # Default is True
            self.assertTrue(db.get_exclusive_mode())
            db.set_exclusive_mode(False)
            self.assertFalse(db.get_exclusive_mode())
            db.set_exclusive_mode(True)
            self.assertTrue(db.get_exclusive_mode())


class TestNoVpnDirectOnly(unittest.TestCase):
    """
    Scenario A — Wi-Fi connected, VPN client NOT running, no TUN interface.
    All traffic must be classified as Direct. VPN speeds must be 0.
    """

    def setUp(self):
        import unittest.mock as mock
        self.mock = mock

    def test_vpn_detector_no_vpn_running(self):
        """VpnDetector reports nothing running and no TUN when no proxy process exists."""
        from core.vpn_detector import VpnDetector
        with self.mock.patch("psutil.process_iter", return_value=[]):
            with self.mock.patch("psutil.net_io_counters", return_value={}):
                vd = VpnDetector()
                self.assertFalse(vd.is_vpn_running())
                self.assertIsNone(vd.get_tun_interface_name())
                self.assertFalse(vd.is_tun_active())

    def test_status_summary_disconnected(self):
        """status_summary returns 'Disconnected' with no tools and no TUN."""
        from core.vpn_detector import VpnDetector
        with self.mock.patch("psutil.process_iter", return_value=[]):
            with self.mock.patch("psutil.net_io_counters", return_value={}):
                vd = VpnDetector()
                summary = vd.get_status_summary()
                self.assertFalse(summary["tun_active"])
                self.assertFalse(summary["is_running"])
                self.assertEqual(summary["status_text"], "Disconnected")
                self.assertEqual(summary["running_tools"], [])
                self.assertEqual(summary["top_apps"], [])

    def test_collector_no_vpn_all_traffic_is_direct(self):
        """
        When VPN is not active, _sample_traffic must put 100% of delta into
        normal_rx/tx and 0 into vpn_rx/tx.
        """
        import tempfile
        from core.collector import NetworkCollector
        from core.database import StatsDatabase

        # Fake interfaces: only eth0 (or wlan0), no tun
        fake_counters = {
            "wlan0": self.mock.MagicMock(bytes_recv=10_000, bytes_sent=5_000)
        }

        with tempfile.TemporaryDirectory() as td:
            with self.mock.patch("core.collector.get_wifi_details", return_value={"ssid": "TestNet", "connected": True}):
                with self.mock.patch("core.collector.get_default_gateway_and_iface", return_value=("wlan0", "192.168.1.1")):
                    with self.mock.patch("psutil.net_io_counters", return_value=fake_counters):
                        with self.mock.patch("core.collector.PingProbe"):
                            with self.mock.patch("core.collector.VpnDetector") as MockVpn:
                                MockVpn.return_value.get_tun_interface_name.return_value = None
                                MockVpn.return_value.get_status_summary.return_value = {
                                    "tun_active": False, "is_running": False,
                                    "status_text": "Disconnected", "client_name": "VPN / Proxy",
                                    "active_profile": "None", "profile_type": "VPN/Proxy",
                                    "running_tools": [], "top_apps": [],
                                }

                                db_path = os.path.join(td, "no_vpn.db")
                                db = StatsDatabase(db_path)

                                c = NetworkCollector.__new__(NetworkCollector)
                                c.wifi_iface = "wlan0"
                                c.is_windows = False
                                c.db = db
                                c.vpn = MockVpn.return_value
                                c.throne = c.vpn
                                c._lock = __import__("threading").Lock()
                                c.prev_wifi_rx = 8_000
                                c.prev_wifi_tx = 4_000
                                c.prev_vpn_rx = 0
                                c.prev_vpn_tx = 0
                                c.prev_timestamp = time.time() - 1.0
                                c.session_normal_rx = 0
                                c.session_normal_tx = 0
                                c.session_vpn_rx = 0
                                c.session_vpn_tx = 0
                                c.session_total_rx = 0
                                c.session_total_tx = 0
                                from collections import deque
                                c.speed_history = deque(maxlen=60)

                                c._sample_traffic(time.time())

                                # All delta goes to normal, nothing to VPN
                                self.assertEqual(c.session_vpn_rx, 0)
                                self.assertEqual(c.session_vpn_tx, 0)
                                self.assertEqual(c.session_normal_rx, 2_000)  # 10000 - 8000
                                self.assertEqual(c.session_normal_tx, 1_000)  # 5000 - 4000
                                self.assertEqual(c.vpn_rx_speed, 0.0)
                                self.assertEqual(c.vpn_tx_speed, 0.0)
                                self.assertGreater(c.normal_rx_speed, 0.0)

    def test_snapshot_keys_present_no_vpn(self):
        """get_snapshot() must always return all required keys even with no VPN."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            collector = NetworkCollector.__new__(NetworkCollector)
            # Minimal init via real NetworkCollector, but stopped immediately
            with self.mock.patch("core.collector.get_wifi_details", return_value={"ssid": "TestNet", "connected": True}):
                with self.mock.patch("core.collector.get_default_gateway_and_iface", return_value=("wlan0", "192.168.1.1")):
                    from core.database import StatsDatabase
                    db = StatsDatabase(os.path.join(td, "snap_test.db"))

                    with self.mock.patch("core.collector.VpnDetector") as MockVpn:
                        MockVpn.return_value.get_tun_interface_name.return_value = None
                        MockVpn.return_value.get_status_summary.return_value = {
                            "tun_active": False, "is_running": False,
                            "status_text": "Disconnected", "client_name": "VPN / Proxy",
                            "active_profile": "None", "profile_type": "VPN/Proxy",
                            "running_tools": [], "top_apps": [],
                        }
                        with self.mock.patch("core.collector.PingProbe") as MockPing:
                            MockPing.return_value.get_stats.return_value = {
                                "gateway_ping_ms": None,
                                "internet_ping_ms": None,
                                "public_ip": "N/A",
                            }
                            import threading
                            from collections import deque
                            collector.wifi_iface = "wlan0"
                            collector.is_windows = False
                            collector.db = db
                            collector.vpn = MockVpn.return_value
                            collector.throne = collector.vpn
                            collector.ping_probe = MockPing.return_value
                            collector.wifi_info = {"ssid": "TestNet", "connected": True}
                            collector._lock = threading.Lock()
                            collector.normal_rx_speed = 0.0
                            collector.normal_tx_speed = 0.0
                            collector.vpn_rx_speed = 0.0
                            collector.vpn_tx_speed = 0.0
                            collector.total_rx_speed = 0.0
                            collector.total_tx_speed = 0.0
                            collector.session_normal_rx = 0
                            collector.session_normal_tx = 0
                            collector.session_vpn_rx = 0
                            collector.session_vpn_tx = 0
                            collector.session_total_rx = 0
                            collector.session_total_tx = 0
                            collector.speed_history = deque(maxlen=60)

                            snap = collector.get_snapshot()
                            for key in ["speeds", "session_usage", "today_usage", "wifi", "ping", "vpn", "throne"]:
                                self.assertIn(key, snap, f"Missing key: {key}")
                            self.assertEqual(snap["speeds"]["vpn_down_bps"], 0.0)
                            self.assertEqual(snap["speeds"]["vpn_up_bps"], 0.0)


class TestNoToolsInstalled(unittest.TestCase):
    """
    Scenario B — Bare system with NO VPN/proxy tools installed at all.
    No Throne DB, no running proxy process, no tun interface.
    App must start, collect, and display without any crash or exception.
    """

    def setUp(self):
        import unittest.mock as mock
        self.mock = mock

    def test_no_throne_db_get_top_apps_returns_empty(self):
        """get_top_apps() returns [] when Throne stats DB doesn't exist."""
        from core.vpn_detector import VpnDetector
        vd = VpnDetector()
        # Point throne_stats_db to a path that doesn't exist
        vd.throne_stats_db = "/nonexistent/path/throne_stats.db"
        result = vd.get_top_apps()
        self.assertEqual(result, [])

    def test_no_throne_db_profile_returns_none(self):
        """get_active_profile_and_protocol() returns (None, None) with no DB and no running tools."""
        from core.vpn_detector import VpnDetector
        with self.mock.patch("psutil.process_iter", return_value=[]):
            vd = VpnDetector()
            vd.throne_db = "/nonexistent/throne.db"
            profile, proto = vd.get_active_profile_and_protocol()
            self.assertIsNone(profile)
            self.assertIsNone(proto)

    def test_no_tun_interface_on_clean_system(self):
        """get_tun_interface_name() returns None when only eth/wlan adapters exist."""
        from core.vpn_detector import VpnDetector
        clean_adapters = {
            "wlan0": self.mock.MagicMock(),
            "eth0": self.mock.MagicMock(),
            "lo": self.mock.MagicMock(),
        }
        with self.mock.patch("psutil.net_io_counters", return_value=clean_adapters):
            # Patch /sys/class/net to return only those interfaces
            with self.mock.patch("os.path.exists", side_effect=lambda p: False if "tun_flags" in p else os.path.exists.__wrapped__(p) if hasattr(os.path.exists, "__wrapped__") else True):
                vd = VpnDetector()
                vd.custom_iface = None
                # Override sysfs check entirely — directly test name matching
                result = vd.get_tun_interface_name()
                # wlan0 / eth0 / lo should never match TUN prefix heuristics
                self.assertIsNone(result)

    def test_status_summary_fully_bare_system(self):
        """Full status_summary on a bare system: all False, status Disconnected, empty lists."""
        from core.vpn_detector import VpnDetector
        with self.mock.patch("psutil.process_iter", return_value=[]):
            with self.mock.patch("psutil.net_io_counters", return_value={}):
                vd = VpnDetector()
                vd.throne_db = "/nonexistent/throne.db"
                vd.throne_stats_db = "/nonexistent/throne_stats.db"
                summary = vd.get_status_summary()
                self.assertFalse(summary["tun_active"])
                self.assertFalse(summary["is_running"])
                self.assertEqual(summary["status_text"], "Disconnected")
                self.assertIsNone(summary["tun_interface"])
                self.assertEqual(summary["running_tools"], [])
                self.assertEqual(summary["top_apps"], [])

    def test_database_works_with_no_vpn_traffic(self):
        """Database correctly handles session with zero VPN traffic recorded."""
        import tempfile
        from core.database import StatsDatabase
        with tempfile.TemporaryDirectory() as td:
            db = StatsDatabase(os.path.join(td, "bare.db"))
            # Record only direct traffic, no VPN
            db.record_traffic(normal_rx=5000, normal_tx=2000, vpn_rx=0, vpn_tx=0)
            today = db.get_today_stats()
            self.assertEqual(today["normal_rx"], 5000)
            self.assertEqual(today["vpn_rx"], 0)
            self.assertEqual(today["vpn_tx"], 0)
            self.assertEqual(today["total_rx"], 5000)   # only direct

class TestPerformanceAndAccuracyOptimizations(unittest.TestCase):
    """Verify enhanced accuracy and CPU/memory optimizations."""

    def setUp(self):
        import unittest.mock as mock
        self.mock = mock

    def test_db_in_memory_accuracy_and_batch_flush(self):
        """Deltas are immediately available in memory with 100% accuracy, and flush commits to disk."""
        import tempfile
        from core.database import StatsDatabase

        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "cache_test.db")
            db = StatsDatabase(db_path)

            # Record deltas
            db.record_traffic(normal_rx=1000, normal_tx=200, vpn_rx=5000, vpn_tx=1000)

            # Immediately query from in-memory cache without waiting for flush
            today = db.get_today_stats()
            self.assertEqual(today["normal_rx"], 1000)
            self.assertEqual(today["vpn_rx"], 5000)
            self.assertEqual(today["total_rx"], 6000)

            # Now flush to SQLite and verify on-disk consistency
            db.flush()
            import sqlite3
            conn = sqlite3.connect(db_path)
            try:
                c = conn.cursor()
                c.execute("SELECT normal_rx, vpn_rx FROM daily_stats")
                row = c.fetchone()
                self.assertIsNotNone(row)
                self.assertEqual(row[0], 1000)
                self.assertEqual(row[1], 5000)
            finally:
                conn.close()

    def test_vpn_connection_baseline_no_spike(self):
        """When VPN connects, pre-existing bytes on the TUN interface must NOT trigger a false spike."""
        import tempfile
        from core.collector import NetworkCollector
        from core.database import StatsDatabase

        with tempfile.TemporaryDirectory() as td:
            db = StatsDatabase(os.path.join(td, "spike_test.db"))

            c = NetworkCollector.__new__(NetworkCollector)
            c.wifi_iface = "wlan0"
            c.is_linux = False
            c.is_windows = False
            c.db = db
            c._lock = __import__("threading").Lock()

            # Mock VPN detector
            c.vpn = self.mock.MagicMock()
            c.throne = c.vpn

            # Tick 1: VPN is NOT active. Wi-Fi has 10,000 bytes.
            fake_counters_tick1 = {
                "wlan0": self.mock.MagicMock(bytes_recv=10_000, bytes_sent=2_000)
            }
            c.vpn.get_tun_interface_name.return_value = None
            c.prev_wifi_rx = 10_000
            c.prev_wifi_tx = 2_000
            c.prev_vpn_rx = None
            c.prev_vpn_tx = None
            c.prev_vpn_active = False
            c.prev_timestamp = time.monotonic() - 1.0
            c.session_normal_rx = 0
            c.session_normal_tx = 0
            c.session_vpn_rx = 0
            c.session_vpn_tx = 0
            c.session_total_rx = 0
            c.session_total_tx = 0
            from collections import deque
            c.speed_history = deque(maxlen=60)

            # Tick 2: VPN connects! tun0 appears with 50,000,000 pre-existing bytes.
            # Physical wlan0 has transferred 5,000 bytes since tick 1.
            fake_counters_tick2 = {
                "wlan0": self.mock.MagicMock(bytes_recv=15_000, bytes_sent=3_000),
                "tun0": self.mock.MagicMock(bytes_recv=50_000_000, bytes_sent=10_000_000),
            }
            c.vpn.get_tun_interface_name.return_value = "tun0"

            with self.mock.patch("psutil.net_io_counters", return_value=fake_counters_tick2):
                c._sample_traffic(time.monotonic())

            # The 50 MB existing on the tunnel should NOT be counted as a 50 MB spike
            # In Exclusive Mode (default), vpn delta = physical delta (5,000 bytes)
            # Not 50,000,000!
            self.assertLess(c.session_vpn_rx, 100_000)
            self.assertEqual(c.session_vpn_rx, 5_000)

    def test_vpn_detector_process_cache(self):
        """VpnDetector caches get_running_clients to avoid scanning process table repeatedly."""
        from core.vpn_detector import VpnDetector
        vd = VpnDetector()

        mock_procs = [
            self.mock.MagicMock(info={"name": "sing-box"})
        ]

        with self.mock.patch("psutil.process_iter", return_value=mock_procs) as mock_iter:
            # First call: hits process_iter
            res1 = vd.get_running_clients(force=True)
            self.assertEqual(len(res1), 1)
            self.assertEqual(res1[0]["name"], "Sing-Box")
            initial_count = mock_iter.call_count

            # Second call immediately after: uses cache, does NOT call process_iter again
            res2 = vd.get_running_clients(force=False)
            self.assertEqual(len(res2), 1)
            self.assertEqual(mock_iter.call_count, initial_count)

    def test_wifi_gateway_cache(self):
        """get_default_gateway_and_iface returns cached value within TTL."""
        from core.wifi import get_default_gateway_and_iface
        # Call once to populate cache
        res1 = get_default_gateway_and_iface(force=True)
        # Call again without force
        res2 = get_default_gateway_and_iface(force=False)
        self.assertEqual(res1, res2)


if __name__ == "__main__":
    unittest.main()


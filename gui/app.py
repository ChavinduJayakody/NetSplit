"""
Native GNOME / Libadwaita Desktop Application for NetworkMonitor.
Provides a modern, dark-mode-ready GUI displaying real-time speeds, normal vs VPN split,
Wi-Fi signal diagnostics, and Throne per-application statistics.
"""

import sys
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib

from core.collector import NetworkCollector, format_bytes, format_speed


CSS_STYLES = """
.metric-card {
    background-color: alpha(@window_fg_color, 0.05);
    border: 1px solid alpha(@borders, 0.7);
    border-radius: 14px;
    padding: 18px;
    margin: 4px;
}

.card-title {
    font-size: 11pt;
    font-weight: 700;
    color: alpha(@window_fg_color, 0.75);
}

.speed-value-normal {
    font-size: 24pt;
    font-weight: 800;
    color: #3584e4; /* Sky Blue */
}

.speed-value-vpn {
    font-size: 24pt;
    font-weight: 800;
    color: #c084fc; /* Purple */
}

.speed-value-total {
    font-size: 24pt;
    font-weight: 800;
    color: #33d17a; /* Green */
}

.badge-vpn-active {
    background-color: #26a269;
    color: white;
    border-radius: 12px;
    padding: 3px 12px;
    font-size: 9pt;
    font-weight: 800;
}

.badge-vpn-inactive {
    background-color: alpha(@window_fg_color, 0.12);
    color: alpha(@window_fg_color, 0.8);
    border-radius: 12px;
    padding: 3px 12px;
    font-size: 9pt;
}

.info-label {
    font-size: 10pt;
    color: alpha(@window_fg_color, 0.65);
}

.info-val {
    font-size: 10pt;
    font-weight: 700;
}
"""


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app, collector: NetworkCollector):
        super().__init__(application=app, title="NetSplit")
        self.collector = collector
        self.set_default_size(840, 680)

        # Apply CSS
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(CSS_STYLES.encode('utf-8'))
        Gtk.StyleContext.add_provider_for_display(
            self.get_display(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        self._build_ui()

        # Immediate first update
        self._on_tick()

        # Refresh timer every 1000ms
        GLib.timeout_add(1000, self._on_tick)

    def _build_ui(self):
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(main_box)

        # Header bar
        header = Adw.HeaderBar()
        title_widget = Adw.WindowTitle(title="NetSplit", subtitle="Wi-Fi and Throne VPN Split")
        header.set_title_widget(title_widget)

        # Status badge in header
        self.vpn_badge = Gtk.Label(label="Checking...")
        self.vpn_badge.add_css_class("badge-vpn-inactive")
        header.pack_end(self.vpn_badge)

        main_box.append(header)

        # View Switcher Bar (Tabs)
        self.view_stack = Adw.ViewStack()
        self.view_stack.set_vexpand(True)
        self.view_stack.set_hexpand(True)

        switcher = Adw.ViewSwitcher(
            stack=self.view_stack,
            policy=Adw.ViewSwitcherPolicy.WIDE
        )
        switcher_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, halign=Gtk.Align.CENTER)
        switcher_box.set_margin_top(8)
        switcher_box.set_margin_bottom(8)
        switcher_box.append(switcher)
        main_box.append(switcher_box)

        # 1. Overview Page
        self.overview_page = self._build_overview_page()
        self.view_stack.add_titled_with_icon(self.overview_page, "overview", "Live Monitor", "network-transmit-receive-symbolic")

        # 2. Wi-Fi & Diagnostics Page
        self.wifi_page = self._build_wifi_page()
        self.view_stack.add_titled_with_icon(self.wifi_page, "wifi", "Wi-Fi & Health", "network-wireless-symbolic")

        # 3. Throne & Apps Page
        self.throne_page = self._build_throne_page()
        self.view_stack.add_titled_with_icon(self.throne_page, "throne", "Throne & Apps", "network-vpn-symbolic")

        # 4. History Page
        self.history_page = self._build_history_page()
        self.view_stack.add_titled_with_icon(self.history_page, "history", "History", "document-open-recent-symbolic")

        main_box.append(self.view_stack)

    # --- Page 1: Overview ---
    def _build_overview_page(self) -> Gtk.Widget:
        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        scroller.set_hexpand(True)

        clamp = Adw.Clamp(maximum_size=780)
        clamp.set_vexpand(True)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        box.set_margin_start(16)
        box.set_margin_end(16)
        box.set_margin_top(12)
        box.set_margin_bottom(24)

        # 3 Cards Grid
        cards_grid = Gtk.Grid(column_spacing=12, row_spacing=12, column_homogeneous=True)

        # Card 1: Normal Internet
        c1 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        c1.add_css_class("metric-card")
        t1 = Gtk.Label(label="Direct Wi-Fi (Normal)", halign=Gtk.Align.START)
        t1.add_css_class("card-title")
        self.norm_down_lbl = Gtk.Label(label="0.0 KB/s", halign=Gtk.Align.START)
        self.norm_down_lbl.add_css_class("speed-value-normal")
        self.norm_sub_lbl = Gtk.Label(label="↓ 0.0 KB/s   ↑ 0.0 KB/s", halign=Gtk.Align.START)
        self.norm_sub_lbl.add_css_class("info-label")
        c1.append(t1)
        c1.append(self.norm_down_lbl)
        c1.append(self.norm_sub_lbl)
        cards_grid.attach(c1, 0, 0, 1, 1)

        # Card 2: Throne VPN
        c2 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        c2.add_css_class("metric-card")
        t2 = Gtk.Label(label="Throne VPN Traffic", halign=Gtk.Align.START)
        t2.add_css_class("card-title")
        self.vpn_down_lbl = Gtk.Label(label="0.0 KB/s", halign=Gtk.Align.START)
        self.vpn_down_lbl.add_css_class("speed-value-vpn")
        self.vpn_sub_lbl = Gtk.Label(label="↓ 0.0 KB/s   ↑ 0.0 KB/s", halign=Gtk.Align.START)
        self.vpn_sub_lbl.add_css_class("info-label")
        c2.append(t2)
        c2.append(self.vpn_down_lbl)
        c2.append(self.vpn_sub_lbl)
        cards_grid.attach(c2, 1, 0, 1, 1)

        # Card 3: Total Combined
        c3 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        c3.add_css_class("metric-card")
        t3 = Gtk.Label(label="Total Physical Wi-Fi", halign=Gtk.Align.START)
        t3.add_css_class("card-title")
        self.tot_down_lbl = Gtk.Label(label="0.0 KB/s", halign=Gtk.Align.START)
        self.tot_down_lbl.add_css_class("speed-value-total")
        self.tot_sub_lbl = Gtk.Label(label="↓ 0.0 KB/s   ↑ 0.0 KB/s", halign=Gtk.Align.START)
        self.tot_sub_lbl.add_css_class("info-label")
        c3.append(t3)
        c3.append(self.tot_down_lbl)
        c3.append(self.tot_sub_lbl)
        cards_grid.attach(c3, 2, 0, 1, 1)

        box.append(cards_grid)

        # Traffic Split Progress Bar
        bar_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        bar_lbl_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        lbl_split = Gtk.Label(label="Traffic Split (Direct vs VPN)", halign=Gtk.Align.START)
        lbl_split.add_css_class("card-title")
        self.split_pct_lbl = Gtk.Label(label="0% VPN", halign=Gtk.Align.END, hexpand=True)
        self.split_pct_lbl.add_css_class("info-label")
        bar_lbl_box.append(lbl_split)
        bar_lbl_box.append(self.split_pct_lbl)
        bar_box.append(bar_lbl_box)

        self.vpn_prog_bar = Gtk.ProgressBar()
        self.vpn_prog_bar.set_fraction(0.0)
        bar_box.append(self.vpn_prog_bar)
        box.append(bar_box)

        # Usage Statistics Group (Today & Session)
        usage_group = Adw.PreferencesGroup(title="Usage Breakdown")

        self.row_today_normal = Adw.ActionRow(title="Today: Direct Internet")
        self.val_today_normal = Gtk.Label(label="0 B", halign=Gtk.Align.END)
        self.val_today_normal.add_css_class("info-val")
        self.row_today_normal.add_suffix(self.val_today_normal)
        usage_group.add(self.row_today_normal)

        self.row_today_vpn = Adw.ActionRow(title="Today: Throne VPN")
        self.val_today_vpn = Gtk.Label(label="0 B", halign=Gtk.Align.END)
        self.val_today_vpn.add_css_class("info-val")
        self.row_today_vpn.add_suffix(self.val_today_vpn)
        usage_group.add(self.row_today_vpn)

        self.row_today_tot = Adw.ActionRow(title="Today: Grand Total")
        self.val_today_tot = Gtk.Label(label="0 B", halign=Gtk.Align.END)
        self.val_today_tot.add_css_class("info-val")
        self.row_today_tot.add_suffix(self.val_today_tot)
        usage_group.add(self.row_today_tot)

        self.row_sess_tot = Adw.ActionRow(title="Current Session Total")
        self.val_sess_tot = Gtk.Label(label="0 B", halign=Gtk.Align.END)
        self.val_sess_tot.add_css_class("info-val")
        self.row_sess_tot.add_suffix(self.val_sess_tot)
        usage_group.add(self.row_sess_tot)

        box.append(usage_group)

        clamp.set_child(box)
        scroller.set_child(clamp)
        return scroller

    # --- Page 2: Wi-Fi & Health ---
    def _build_wifi_page(self) -> Gtk.Widget:
        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        scroller.set_hexpand(True)

        clamp = Adw.Clamp(maximum_size=780)
        clamp.set_vexpand(True)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        box.set_margin_start(16)
        box.set_margin_end(16)
        box.set_margin_top(12)
        box.set_margin_bottom(24)

        wifi_group = Adw.PreferencesGroup(title="Wi-Fi Connection Details")

        self.row_ssid = Adw.ActionRow(title="Network SSID")
        self.val_ssid = Gtk.Label(label="Loading...", halign=Gtk.Align.END)
        self.val_ssid.add_css_class("info-val")
        self.row_ssid.add_suffix(self.val_ssid)
        wifi_group.add(self.row_ssid)

        self.row_signal = Adw.ActionRow(title="Signal Strength")
        self.val_signal = Gtk.Label(label="0%", halign=Gtk.Align.END)
        self.val_signal.add_css_class("info-val")
        self.row_signal.add_suffix(self.val_signal)
        wifi_group.add(self.row_signal)

        self.row_bitrate = Adw.ActionRow(title="Link Speed (Bitrate)")
        self.val_bitrate = Gtk.Label(label="N/A", halign=Gtk.Align.END)
        self.val_bitrate.add_css_class("info-val")
        self.row_bitrate.add_suffix(self.val_bitrate)
        wifi_group.add(self.row_bitrate)

        self.row_band = Adw.ActionRow(title="Frequency Band and Channel")
        self.val_band = Gtk.Label(label="N/A", halign=Gtk.Align.END)
        self.val_band.add_css_class("info-val")
        self.row_band.add_suffix(self.val_band)
        wifi_group.add(self.row_band)

        self.row_security = Adw.ActionRow(title="Security")
        self.val_security = Gtk.Label(label="N/A", halign=Gtk.Align.END)
        self.val_security.add_css_class("info-val")
        self.row_security.add_suffix(self.val_security)
        wifi_group.add(self.row_security)

        box.append(wifi_group)

        diag_group = Adw.PreferencesGroup(title="Diagnostics and Latency")

        self.row_ping_gw = Adw.ActionRow(title="Gateway Ping (Router Latency)")
        self.val_ping_gw = Gtk.Label(label="-- ms", halign=Gtk.Align.END)
        self.val_ping_gw.add_css_class("info-val")
        self.row_ping_gw.add_suffix(self.val_ping_gw)
        diag_group.add(self.row_ping_gw)

        self.row_ping_inet = Adw.ActionRow(title="Internet Ping (Cloudflare 1.1.1.1)")
        self.val_ping_inet = Gtk.Label(label="-- ms", halign=Gtk.Align.END)
        self.val_ping_inet.add_css_class("info-val")
        self.row_ping_inet.add_suffix(self.val_ping_inet)
        diag_group.add(self.row_ping_inet)

        self.row_local_ip = Adw.ActionRow(title="Local IP Address")
        self.val_local_ip = Gtk.Label(label="127.0.0.1", halign=Gtk.Align.END)
        self.val_local_ip.add_css_class("info-val")
        self.row_local_ip.add_suffix(self.val_local_ip)
        diag_group.add(self.row_local_ip)

        self.row_public_ip = Adw.ActionRow(title="Public Egress IP")
        self.val_public_ip = Gtk.Label(label="Checking...", halign=Gtk.Align.END)
        self.val_public_ip.add_css_class("info-val")
        self.row_public_ip.add_suffix(self.val_public_ip)
        diag_group.add(self.row_public_ip)

        box.append(diag_group)

        clamp.set_child(box)
        scroller.set_child(clamp)
        return scroller

    # --- Page 3: Throne & Apps ---
    def _build_throne_page(self) -> Gtk.Widget:
        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        scroller.set_hexpand(True)

        clamp = Adw.Clamp(maximum_size=780)
        clamp.set_vexpand(True)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        box.set_margin_start(16)
        box.set_margin_end(16)
        box.set_margin_top(12)
        box.set_margin_bottom(24)

        throne_group = Adw.PreferencesGroup(title="Throne VPN Status")

        self.row_throne_state = Adw.ActionRow(title="Connection State")
        self.val_throne_state = Gtk.Label(label="Checking...", halign=Gtk.Align.END)
        self.val_throne_state.add_css_class("info-val")
        self.row_throne_state.add_suffix(self.val_throne_state)
        throne_group.add(self.row_throne_state)

        self.row_throne_prof = Adw.ActionRow(title="Config Profile")
        self.val_throne_prof = Gtk.Label(label="None", halign=Gtk.Align.END)
        self.val_throne_prof.add_css_class("info-val")
        self.row_throne_prof.add_suffix(self.val_throne_prof)
        throne_group.add(self.row_throne_prof)

        self.row_throne_tun = Adw.ActionRow(title="Virtual TUN Interface")
        self.val_throne_tun = Gtk.Label(label="None", halign=Gtk.Align.END)
        self.val_throne_tun.add_css_class("info-val")
        self.row_throne_tun.add_suffix(self.val_throne_tun)
        throne_group.add(self.row_throne_tun)

        box.append(throne_group)

        self.app_group = Adw.PreferencesGroup(title="Top Apps Consuming VPN (Throne Database)")
        self.app_rows_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.app_group.add(self.app_rows_container)
        box.append(self.app_group)

        clamp.set_child(box)
        scroller.set_child(clamp)
        return scroller

    # --- Page 4: History ---
    def _build_history_page(self) -> Gtk.Widget:
        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        scroller.set_hexpand(True)

        clamp = Adw.Clamp(maximum_size=780)
        clamp.set_vexpand(True)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        box.set_margin_start(16)
        box.set_margin_end(16)
        box.set_margin_top(12)
        box.set_margin_bottom(24)

        self.hist_group = Adw.PreferencesGroup(title="Daily Bandwidth History (Last 7 Days)")
        self.hist_rows_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.hist_group.add(self.hist_rows_container)
        box.append(self.hist_group)

        clamp.set_child(box)
        scroller.set_child(clamp)
        return scroller

    def _on_tick(self) -> bool:
        snapshot = self.collector.get_snapshot()

        speeds = snapshot["speeds"]
        session = snapshot["session_usage"]
        today = snapshot["today_usage"]
        wifi = snapshot["wifi"]
        ping = snapshot["ping"]
        throne = snapshot["throne"]

        # 1. Update Header & Badge
        if throne["tun_active"]:
            self.vpn_badge.set_label("VPN ACTIVE")
            self.vpn_badge.remove_css_class("badge-vpn-inactive")
            self.vpn_badge.add_css_class("badge-vpn-active")
        else:
            self.vpn_badge.set_label("DIRECT ONLY")
            self.vpn_badge.remove_css_class("badge-vpn-active")
            self.vpn_badge.add_css_class("badge-vpn-inactive")

        # 2. Update Live Cards
        self.norm_down_lbl.set_label(speeds["normal_down_str"])
        self.norm_sub_lbl.set_label(f"↓ {speeds['normal_down_str']}   ↑ {speeds['normal_up_str']}")

        self.vpn_down_lbl.set_label(speeds["vpn_down_str"])
        self.vpn_sub_lbl.set_label(f"↓ {speeds['vpn_down_str']}   ↑ {speeds['vpn_up_str']}")

        self.tot_down_lbl.set_label(speeds["total_down_str"])
        self.tot_sub_lbl.set_label(f"↓ {speeds['total_down_str']}   ↑ {speeds['total_up_str']}")

        # Progress bar
        tot_bps = speeds["total_down_bps"] + speeds["total_up_bps"]
        vpn_bps = speeds["vpn_down_bps"] + speeds["vpn_up_bps"]
        ratio = (vpn_bps / tot_bps) if tot_bps > 0 else (1.0 if throne["tun_active"] else 0.0)
        self.vpn_prog_bar.set_fraction(min(1.0, max(0.0, ratio)))
        self.split_pct_lbl.set_label(f"{int(ratio * 100)}% VPN")

        # Usage Breakdown
        self.val_today_normal.set_label(today["normal_total_str"])
        self.val_today_vpn.set_label(today["vpn_total_str"])
        self.val_today_tot.set_label(today["grand_total_str"])
        self.val_sess_tot.set_label(
            f"{session['grand_total_str']} (Direct: {session['normal_total_str']} | VPN: {session['vpn_total_str']})"
        )

        # 3. Wi-Fi & Diagnostics
        self.val_ssid.set_label(wifi.get("ssid", "Disconnected"))
        self.val_signal.set_label(f"{wifi.get('signal', 0)}%  ({wifi.get('bars', '____')})")
        self.val_bitrate.set_label(wifi.get("bitrate", "N/A"))
        self.val_band.set_label(f"{wifi.get('band', 'N/A')} (Ch {wifi.get('channel', 'N/A')})")
        self.val_security.set_label(wifi.get("security", "N/A"))

        gw_lat = f"{ping.get('gateway_ping_ms'):.2f} ms" if ping.get("gateway_ping_ms") is not None else "--"
        inet_lat = f"{ping.get('internet_ping_ms'):.2f} ms" if ping.get("internet_ping_ms") is not None else "--"
        self.val_ping_gw.set_label(gw_lat)
        self.val_ping_inet.set_label(inet_lat)
        self.val_local_ip.set_label(wifi.get("local_ip") or "N/A")
        self.val_public_ip.set_label(ping.get("public_ip") or "Checking...")

        # 4. Throne Status & Apps
        self.val_throne_state.set_label(throne.get("status_text", "N/A"))
        self.val_throne_prof.set_label(f"{throne.get('active_profile', 'None')} ({throne.get('profile_type', '')})")
        self.val_throne_tun.set_label(throne.get("tun_interface") or "Inactive")

        # Populate top apps
        top_apps = throne.get("top_apps", [])
        child = self.app_rows_container.get_first_child()
        while child:
            next_child = child.get_next_sibling()
            self.app_rows_container.remove(child)
            child = next_child

        if not top_apps:
            row = Adw.ActionRow(title="No app traffic recorded yet in Throne database")
            self.app_rows_container.append(row)
        else:
            for app in top_apps:
                row = Adw.ActionRow(title=app["process"])
                total_formatted = format_bytes(app["total_bytes"])
                sub_formatted = f"↓ {format_bytes(app['down_bytes'])}   ↑ {format_bytes(app['up_bytes'])}"
                row.set_subtitle(sub_formatted)
                lbl = Gtk.Label(label=total_formatted, halign=Gtk.Align.END)
                lbl.add_css_class("info-val")
                row.add_suffix(lbl)
                self.app_rows_container.append(row)

        # 5. Daily History
        history = self.collector.db.get_daily_history(days=7)
        child = self.hist_rows_container.get_first_child()
        while child:
            next_child = child.get_next_sibling()
            self.hist_rows_container.remove(child)
            child = next_child

        for day in reversed(history):
            row = Adw.ActionRow(title=day["date"])
            norm_str = format_bytes(day["normal_rx"] + day["normal_tx"])
            vpn_str = format_bytes(day["vpn_rx"] + day["vpn_tx"])
            tot_str = format_bytes(day["total_rx"] + day["total_tx"])
            row.set_subtitle(f"Direct: {norm_str}  |  VPN: {vpn_str}")
            lbl = Gtk.Label(label=tot_str, halign=Gtk.Align.END)
            lbl.add_css_class("info-val")
            row.add_suffix(lbl)
            self.hist_rows_container.append(row)

        return True


class NetworkMonitorApp(Adw.Application):
    def __init__(self, collector: NetworkCollector):
        super().__init__(application_id="io.github.networkmonitor.app")
        self.collector = collector

    def do_activate(self):
        win = self.props.active_window
        if not win:
            win = MainWindow(self, self.collector)
        win.present()


def run_gui(collector: NetworkCollector):
    app = NetworkMonitorApp(collector)
    return app.run(sys.argv)

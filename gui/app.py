"""
NetSplit - Modern Native GNOME Desktop Application.
Features real-time speed meters, live Cairo waveform graph, Direct vs Throne VPN traffic split,
Wi-Fi signal diagnostics, Throne per-app statistics, and full Settings customization (Dark/Light/System theme).
"""

import sys
import os
import math
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Gio
import cairo

from core.collector import NetworkCollector, format_bytes, format_speed


CSS_STYLES = """
.metric-card {
    background-color: alpha(@window_fg_color, 0.05);
    border: 1px solid alpha(@borders, 0.5);
    border-radius: 16px;
    padding: 18px 20px;
    margin: 4px;
}

.card-title {
    font-size: 10pt;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: alpha(@window_fg_color, 0.65);
}

.speed-value-normal {
    font-size: 26pt;
    font-weight: 800;
    color: #38bdf8; /* Sky Blue */
    font-family: 'JetBrains Mono', monospace;
    letter-spacing: -0.02em;
}

.speed-value-vpn {
    font-size: 26pt;
    font-weight: 800;
    color: #c084fc; /* Bright Purple */
    font-family: 'JetBrains Mono', monospace;
    letter-spacing: -0.02em;
}

.speed-value-total {
    font-size: 26pt;
    font-weight: 800;
    color: #34d399; /* Emerald Green */
    font-family: 'JetBrains Mono', monospace;
    letter-spacing: -0.02em;
}

.speed-sub {
    font-size: 9.5pt;
    color: alpha(@window_fg_color, 0.6);
    font-family: 'JetBrains Mono', monospace;
}

.badge-vpn-active {
    background: rgba(38, 162, 105, 0.22);
    color: #34d399;
    border: 1px solid rgba(52, 211, 153, 0.4);
    border-radius: 9999px;
    padding: 4px 14px;
    font-size: 9pt;
    font-weight: 800;
}

.badge-vpn-inactive {
    background: alpha(@window_fg_color, 0.08);
    color: alpha(@window_fg_color, 0.7);
    border: 1px solid alpha(@borders, 0.4);
    border-radius: 9999px;
    padding: 4px 14px;
    font-size: 9pt;
    font-weight: 600;
}

.status-pill {
    background: alpha(@window_fg_color, 0.04);
    border: 1px solid alpha(@borders, 0.4);
    border-radius: 12px;
    padding: 8px 14px;
    font-size: 9.5pt;
}

.status-pill-val {
    font-weight: 700;
    font-family: 'JetBrains Mono', monospace;
}

.info-label {
    font-size: 10pt;
    color: alpha(@window_fg_color, 0.65);
}

.info-val {
    font-size: 10pt;
    font-weight: 700;
    font-family: 'JetBrains Mono', monospace;
}

.graph-card {
    background-color: alpha(@window_fg_color, 0.04);
    border: 1px solid alpha(@borders, 0.5);
    border-radius: 16px;
    padding: 14px 16px;
}
"""


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app, collector: NetworkCollector):
        super().__init__(application=app, title="NetSplit")
        self.collector = collector
        self.set_default_size(880, 720)
        self.set_icon_name("netsplit")

        # Apply CSS
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(CSS_STYLES.encode('utf-8'))
        Gtk.StyleContext.add_provider_for_display(
            self.get_display(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        self._build_ui()

        # Apply persisted theme
        self._load_saved_theme()

        # Immediate first update
        self._on_tick()

        # Refresh timer every 1000ms
        GLib.timeout_add(1000, self._on_tick)

    def _load_saved_theme(self):
        saved_theme = self.collector.db.get_setting("theme", "0")
        try:
            idx = int(saved_theme)
        except ValueError:
            idx = 0

        self.theme_row.set_selected(idx)
        self._apply_theme(idx)

    def _apply_theme(self, idx: int):
        sm = Adw.StyleManager.get_default()
        if idx == 1:
            sm.set_color_scheme(Adw.ColorScheme.FORCE_DARK)
        elif idx == 2:
            sm.set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)
        else:
            sm.set_color_scheme(Adw.ColorScheme.DEFAULT)

    def _on_theme_changed(self, row, param):
        selected = row.get_selected()
        self._apply_theme(selected)
        self.collector.db.set_setting("theme", str(selected))
        self.graph_area.queue_draw()

    def _build_ui(self):
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(main_box)

        # Header bar
        header = Adw.HeaderBar()
        title_widget = Adw.WindowTitle(title="NetSplit", subtitle="Direct Wi-Fi and VPN / Proxy Split")
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

        # 3. VPN & Proxy Page (Universal for Throne, NetMod, Netch, Xray, etc.)
        self.vpn_page = self._build_vpn_page()
        self.view_stack.add_titled_with_icon(self.vpn_page, "vpn", "VPN & Proxy", "network-vpn-symbolic")

        # 4. History Page
        self.history_page = self._build_history_page()
        self.view_stack.add_titled_with_icon(self.history_page, "history", "History", "document-open-recent-symbolic")

        # 5. Settings Page
        self.settings_page = self._build_settings_page()
        self.view_stack.add_titled_with_icon(self.settings_page, "settings", "Settings", "preferences-system-symbolic")

        main_box.append(self.view_stack)

    # --- Page 1: Overview ---
    def _build_overview_page(self) -> Gtk.Widget:
        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        scroller.set_hexpand(True)

        clamp = Adw.Clamp(maximum_size=820)
        clamp.set_vexpand(True)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        box.set_margin_start(16)
        box.set_margin_end(16)
        box.set_margin_top(6)
        box.set_margin_bottom(24)

        # Quick Status Strip
        strip = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10, homogeneous=True)

        # Pill 1: Wi-Fi Quick
        p1 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        p1.add_css_class("status-pill")
        dot1 = Gtk.Label(label="●")
        dot1.set_markup('<span foreground="#34d399">●</span>')
        self.pill_wifi_lbl = Gtk.Label(label="Wi-Fi: Checking...", halign=Gtk.Align.START)
        self.pill_wifi_lbl.add_css_class("status-pill-val")
        p1.append(dot1)
        p1.append(self.pill_wifi_lbl)
        strip.append(p1)

        # Pill 2: Latency Quick
        p2 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        p2.add_css_class("status-pill")
        dot2 = Gtk.Label(label="●")
        dot2.set_markup('<span foreground="#38bdf8">●</span>')
        self.pill_ping_lbl = Gtk.Label(label="Ping: -- ms", halign=Gtk.Align.START)
        self.pill_ping_lbl.add_css_class("status-pill-val")
        p2.append(dot2)
        p2.append(self.pill_ping_lbl)
        strip.append(p2)

        # Pill 3: Egress IP Quick
        p3 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        p3.add_css_class("status-pill")
        dot3 = Gtk.Label(label="●")
        dot3.set_markup('<span foreground="#c084fc">●</span>')
        self.pill_ip_lbl = Gtk.Label(label="IP: Checking...", halign=Gtk.Align.START)
        self.pill_ip_lbl.add_css_class("status-pill-val")
        p3.append(dot3)
        p3.append(self.pill_ip_lbl)
        strip.append(p3)

        box.append(strip)

        # 3 Main Speed Cards
        cards_grid = Gtk.Grid(column_spacing=12, row_spacing=12, column_homogeneous=True)

        # Card 1: Direct Wi-Fi
        c1 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        c1.add_css_class("metric-card")
        h1 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        t1 = Gtk.Label(label="Direct Wi-Fi", halign=Gtk.Align.START)
        t1.add_css_class("card-title")
        ico1 = Gtk.Label(label="📶", halign=Gtk.Align.END, hexpand=True)
        h1.append(t1)
        h1.append(ico1)
        self.norm_down_lbl = Gtk.Label(label="0.0 KB/s", halign=Gtk.Align.START)
        self.norm_down_lbl.add_css_class("speed-value-normal")
        self.norm_sub_lbl = Gtk.Label(label="↓ 0.0 KB/s   ↑ 0.0 KB/s", halign=Gtk.Align.START)
        self.norm_sub_lbl.add_css_class("speed-sub")
        self.norm_today_lbl = Gtk.Label(label="Today: 0 B", halign=Gtk.Align.START)
        self.norm_today_lbl.add_css_class("info-label")
        c1.append(h1)
        c1.append(self.norm_down_lbl)
        c1.append(self.norm_sub_lbl)
        c1.append(self.norm_today_lbl)
        cards_grid.attach(c1, 0, 0, 1, 1)

        # Card 2: VPN / Proxy
        c2 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        c2.add_css_class("metric-card")
        h2 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.card_vpn_title = Gtk.Label(label="VPN / Proxy", halign=Gtk.Align.START)
        self.card_vpn_title.add_css_class("card-title")
        ico2 = Gtk.Label(label="🛡️", halign=Gtk.Align.END, hexpand=True)
        h2.append(self.card_vpn_title)
        h2.append(ico2)
        self.vpn_down_lbl = Gtk.Label(label="0.0 KB/s", halign=Gtk.Align.START)
        self.vpn_down_lbl.add_css_class("speed-value-vpn")
        self.vpn_sub_lbl = Gtk.Label(label="↓ 0.0 KB/s   ↑ 0.0 KB/s", halign=Gtk.Align.START)
        self.vpn_sub_lbl.add_css_class("speed-sub")
        self.vpn_today_lbl = Gtk.Label(label="Today: 0 B", halign=Gtk.Align.START)
        self.vpn_today_lbl.add_css_class("info-label")
        c2.append(h2)
        c2.append(self.vpn_down_lbl)
        c2.append(self.vpn_sub_lbl)
        c2.append(self.vpn_today_lbl)
        cards_grid.attach(c2, 1, 0, 1, 1)

        # Card 3: Total Wi-Fi
        c3 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        c3.add_css_class("metric-card")
        h3 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        t3 = Gtk.Label(label="Total Physical", halign=Gtk.Align.START)
        t3.add_css_class("card-title")
        ico3 = Gtk.Label(label="⚡", halign=Gtk.Align.END, hexpand=True)
        h3.append(t3)
        h3.append(ico3)
        self.tot_down_lbl = Gtk.Label(label="0.0 KB/s", halign=Gtk.Align.START)
        self.tot_down_lbl.add_css_class("speed-value-total")
        self.tot_sub_lbl = Gtk.Label(label="↓ 0.0 KB/s   ↑ 0.0 KB/s", halign=Gtk.Align.START)
        self.tot_sub_lbl.add_css_class("speed-sub")
        self.tot_today_lbl = Gtk.Label(label="Today: 0 B", halign=Gtk.Align.START)
        self.tot_today_lbl.add_css_class("info-label")
        c3.append(h3)
        c3.append(self.tot_down_lbl)
        c3.append(self.tot_sub_lbl)
        c3.append(self.tot_today_lbl)
        cards_grid.attach(c3, 2, 0, 1, 1)

        box.append(cards_grid)

        # Cairo Live Waveform Graph
        graph_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        graph_box.add_css_class("graph-card")

        g_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        g_title = Gtk.Label(label="REAL-TIME SPEED WAVEFORM (LAST 30s)", halign=Gtk.Align.START)
        g_title.add_css_class("card-title")

        g_legend = Gtk.Label(halign=Gtk.Align.END, hexpand=True)
        g_legend.set_markup(
            '<span foreground="#38bdf8">● Direct</span>   '
            '<span foreground="#c084fc">● VPN / Proxy</span>'
        )
        g_header.append(g_title)
        g_header.append(g_legend)
        graph_box.append(g_header)

        # DrawingArea for Cairo
        self.graph_area = Gtk.DrawingArea()
        self.graph_area.set_content_height(115)
        self.graph_area.set_vexpand(False)
        self.graph_area.set_hexpand(True)
        self.graph_area.set_draw_func(self._draw_speed_graph)
        graph_box.append(self.graph_area)

        box.append(graph_box)

        # Split Meter
        split_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        split_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        split_title = Gtk.Label(label="TRAFFIC SPLIT RATIO", halign=Gtk.Align.START)
        split_title.add_css_class("card-title")
        self.split_pct_lbl = Gtk.Label(label="100% Direct   |   0% VPN", halign=Gtk.Align.END, hexpand=True)
        self.split_pct_lbl.add_css_class("info-label")
        split_header.append(split_title)
        split_header.append(self.split_pct_lbl)
        split_box.append(split_header)

        self.vpn_prog_bar = Gtk.ProgressBar()
        self.vpn_prog_bar.set_fraction(0.0)
        split_box.append(self.vpn_prog_bar)
        box.append(split_box)

        # Usage Statistics Group (Today & Session)
        usage_group = Adw.PreferencesGroup(title="Usage Summary")

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

        self.row_sess_tot = Adw.ActionRow(title="Session Total")
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

        clamp = Adw.Clamp(maximum_size=820)
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

        self.row_bitrate = Adw.ActionRow(title="Link Bitrate (Capability)")
        self.val_bitrate = Gtk.Label(label="N/A", halign=Gtk.Align.END)
        self.val_bitrate.add_css_class("info-val")
        self.row_bitrate.add_suffix(self.val_bitrate)
        wifi_group.add(self.row_bitrate)

        self.row_band = Adw.ActionRow(title="Frequency Band and Channel")
        self.val_band = Gtk.Label(label="N/A", halign=Gtk.Align.END)
        self.val_band.add_css_class("info-val")
        self.row_band.add_suffix(self.val_band)
        wifi_group.add(self.row_band)

        self.row_security = Adw.ActionRow(title="Security / Encryption")
        self.val_security = Gtk.Label(label="N/A", halign=Gtk.Align.END)
        self.val_security.add_css_class("info-val")
        self.row_security.add_suffix(self.val_security)
        wifi_group.add(self.row_security)

        box.append(wifi_group)

        diag_group = Adw.PreferencesGroup(title="Diagnostics and Latency")

        self.row_ping_gw = Adw.ActionRow(title="Router Latency (Local Gateway)")
        self.val_ping_gw = Gtk.Label(label="-- ms", halign=Gtk.Align.END)
        self.val_ping_gw.add_css_class("info-val")
        self.row_ping_gw.add_suffix(self.val_ping_gw)
        diag_group.add(self.row_ping_gw)

        self.row_ping_inet = Adw.ActionRow(title="Internet Latency (Cloudflare 1.1.1.1)")
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

    # --- Page 3: VPN & Proxy (Universal) ---
    def _build_vpn_page(self) -> Gtk.Widget:
        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        scroller.set_hexpand(True)

        clamp = Adw.Clamp(maximum_size=820)
        clamp.set_vexpand(True)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        box.set_margin_start(16)
        box.set_margin_end(16)
        box.set_margin_top(12)
        box.set_margin_bottom(24)

        vpn_group = Adw.PreferencesGroup(title="VPN and Proxy Status")

        self.row_vpn_state = Adw.ActionRow(title="Connection State")
        self.val_vpn_state = Gtk.Label(label="Checking...", halign=Gtk.Align.END)
        self.val_vpn_state.add_css_class("info-val")
        self.row_vpn_state.add_suffix(self.val_vpn_state)
        vpn_group.add(self.row_vpn_state)

        self.row_vpn_client = Adw.ActionRow(title="Detected Client / Tool")
        self.val_vpn_client = Gtk.Label(label="None", halign=Gtk.Align.END)
        self.val_vpn_client.add_css_class("info-val")
        self.row_vpn_client.add_suffix(self.val_vpn_client)
        vpn_group.add(self.row_vpn_client)

        self.row_vpn_prof = Adw.ActionRow(title="Active Profile / Protocol")
        self.val_vpn_prof = Gtk.Label(label="None", halign=Gtk.Align.END)
        self.val_vpn_prof.add_css_class("info-val")
        self.row_vpn_prof.add_suffix(self.val_vpn_prof)
        vpn_group.add(self.row_vpn_prof)

        self.row_vpn_tun = Adw.ActionRow(title="Virtual TUN / Wintun Interface")
        self.val_vpn_tun = Gtk.Label(label="None", halign=Gtk.Align.END)
        self.val_vpn_tun.add_css_class("info-val")
        self.row_vpn_tun.add_suffix(self.val_vpn_tun)
        vpn_group.add(self.row_vpn_tun)

        self.row_vpn_procs = Adw.ActionRow(title="Running Proxy Processes")
        self.val_vpn_procs = Gtk.Label(label="None", halign=Gtk.Align.END)
        self.val_vpn_procs.add_css_class("info-val")
        self.row_vpn_procs.add_suffix(self.val_vpn_procs)
        vpn_group.add(self.row_vpn_procs)

        box.append(vpn_group)

        self.app_group = Adw.PreferencesGroup(title="Applications Routed via Proxy / VPN")
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

        clamp = Adw.Clamp(maximum_size=820)
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

    # --- Page 5: Settings ---
    def _build_settings_page(self) -> Gtk.Widget:
        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        scroller.set_hexpand(True)

        clamp = Adw.Clamp(maximum_size=820)
        clamp.set_vexpand(True)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        box.set_margin_start(16)
        box.set_margin_end(16)
        box.set_margin_top(12)
        box.set_margin_bottom(24)

        # Appearance Settings Group
        appearance_group = Adw.PreferencesGroup(title="Appearance and Theme")

        self.theme_row = Adw.ComboRow(title="Theme")
        self.theme_row.set_subtitle("Switch between dark, light, or follow system default")
        model = Gtk.StringList.new(["System Default", "Dark Theme", "Light Theme"])
        self.theme_row.set_model(model)
        self.theme_row.connect("notify::selected", self._on_theme_changed)
        appearance_group.add(self.theme_row)

        box.append(appearance_group)

        # Traffic Accounting & Proxy Settings Group
        proxy_settings_group = Adw.PreferencesGroup(title="VPN and Proxy Compatibility")

        support_row = Adw.ActionRow(title="Supported Clients")
        support_row.set_subtitle("Throne • NetMod • Netch • NekoRay • v2rayA • Clash • Sing-Box • Xray • WireGuard • OpenVPN")
        auto_badge = Gtk.Label(label="AUTO-DETECT")
        auto_badge.add_css_class("badge-vpn-active")
        support_row.add_suffix(auto_badge)
        proxy_settings_group.add(support_row)

        acct_row = Adw.ActionRow(title="Exclusive Mode")
        acct_row.set_subtitle("When VPN is active, Direct Wi-Fi reads 0 B/s and all traffic counts as VPN")
        active_badge = Gtk.Label(label="ENABLED")
        active_badge.add_css_class("badge-vpn-active")
        acct_row.add_suffix(active_badge)
        proxy_settings_group.add(acct_row)

        # Custom Interface Override Entry
        self.custom_iface_row = Adw.EntryRow(title="Custom Interface Override (Optional)")
        saved_iface = self.collector.db.get_setting("custom_vpn_iface", "")
        self.custom_iface_row.set_text(saved_iface)
        self.custom_iface_row.connect("changed", self._on_custom_iface_changed)
        proxy_settings_group.add(self.custom_iface_row)

        box.append(proxy_settings_group)

        # Data Management Group
        data_group = Adw.PreferencesGroup(title="Data and History Management")

        reset_today_row = Adw.ActionRow(title="Reset Today's Usage")
        reset_today_row.set_subtitle("Zero out accumulated bytes for today and current session")
        btn_reset_today = Gtk.Button(label="Reset Today", valign=Gtk.Align.CENTER)
        btn_reset_today.add_css_class("suggested-action")
        btn_reset_today.connect("clicked", self._on_reset_today_clicked)
        reset_today_row.add_suffix(btn_reset_today)
        data_group.add(reset_today_row)

        clear_all_row = Adw.ActionRow(title="Clear All History")
        clear_all_row.set_subtitle("Permanently erase all historical daily and hourly database records")
        btn_clear_all = Gtk.Button(label="Clear All", valign=Gtk.Align.CENTER)
        btn_clear_all.add_css_class("destructive-action")
        btn_clear_all.connect("clicked", self._on_clear_all_clicked)
        clear_all_row.add_suffix(btn_clear_all)
        data_group.add(clear_all_row)

        db_loc_row = Adw.ActionRow(title="Local Database Path")
        db_path = self.collector.db.db_path
        db_loc_row.set_subtitle(db_path)
        data_group.add(db_loc_row)

        box.append(data_group)

        # About NetSplit Group
        about_group = Adw.PreferencesGroup(title="About NetSplit")

        ver_row = Adw.ActionRow(title="NetSplit Version")
        ver_lbl = Gtk.Label(label="1.2.0 (Multi-Protocol Edition)", halign=Gtk.Align.END)
        ver_lbl.add_css_class("info-val")
        ver_row.add_suffix(ver_lbl)
        about_group.add(ver_row)

        repo_row = Adw.ActionRow(title="GitHub Repository")
        repo_row.set_subtitle("https://github.com/ChavinduJayakody/NetSplit")
        btn_open_repo = Gtk.Button(label="Open", valign=Gtk.Align.CENTER)
        btn_open_repo.connect("clicked", lambda _: Gio.AppInfo.launch_default_for_uri("https://github.com/ChavinduJayakody/NetSplit", None))
        repo_row.add_suffix(btn_open_repo)
        about_group.add(repo_row)

        box.append(about_group)

        clamp.set_child(box)
        scroller.set_child(clamp)
        return scroller

    def _on_custom_iface_changed(self, row):
        text = row.get_text().strip()
        self.collector.db.set_setting("custom_vpn_iface", text)
        self.collector.vpn.set_custom_interface(text)

    def _on_reset_today_clicked(self, _):
        self.collector.reset_today()
        self._on_tick()

    def _on_clear_all_clicked(self, _):
        self.collector.clear_all_history()
        self._on_tick()

    # --- Cairo Waveform Drawing ---
    def _draw_speed_graph(self, area, cr, width, height):
        history = list(self.collector.speed_history)

        is_dark = Adw.StyleManager.get_default().get_dark()
        bg_r, bg_g, bg_b, bg_a = (0.04, 0.06, 0.1, 0.85) if is_dark else (0.94, 0.95, 0.98, 0.95)
        grid_alpha = 0.06 if is_dark else 0.08

        # Background rounded rect
        radius = 8.0
        cr.new_sub_path()
        cr.arc(width - radius, radius, radius, -math.pi / 2, 0)
        cr.arc(width - radius, height - radius, radius, 0, math.pi / 2)
        cr.arc(radius, height - radius, radius, math.pi / 2, math.pi)
        cr.arc(radius, radius, radius, math.pi, 3 * math.pi / 2)
        cr.close_path()
        cr.set_source_rgba(bg_r, bg_g, bg_b, bg_a)
        cr.fill()

        # Subtle horizontal grid lines
        cr.set_line_width(0.7)
        cr.set_source_rgba(0.5, 0.5, 0.5, grid_alpha)
        for y_pct in [0.25, 0.5, 0.75]:
            y = height * y_pct
            cr.move_to(10, y)
            cr.line_to(width - 10, y)
            cr.stroke()

        if len(history) < 2:
            return

        # Calculate max scale
        max_speed = 1024.0 * 10.0  # minimum 10 KB/s scale
        for pt in history:
            max_speed = max(max_speed, pt["normal_down"], pt["vpn_down"], pt["total_down"])
        max_speed *= 1.15  # headroom

        n_pts = len(history)
        step_x = (width - 24) / max(1, n_pts - 1)
        start_x = 12
        bottom_y = height - 10

        # Helper to plot filled curve
        def draw_series(key: str, r: float, g: float, b: float, fill_alpha: float = 0.15):
            pts = []
            for i, item in enumerate(history):
                val = item.get(key, 0.0)
                x = start_x + (i * step_x)
                y = bottom_y - ((val / max_speed) * (height - 24))
                y = max(10, min(bottom_y, y))
                pts.append((x, y))

            # Filled area
            cr.move_to(pts[0][0], bottom_y)
            for x, y in pts:
                cr.line_to(x, y)
            cr.line_to(pts[-1][0], bottom_y)
            cr.close_path()
            cr.set_source_rgba(r, g, b, fill_alpha)
            cr.fill()

            # Stroke line
            cr.set_line_width(2.0)
            cr.set_source_rgba(r, g, b, 0.9)
            cr.move_to(pts[0][0], pts[0][1])
            for x, y in pts[1:]:
                cr.line_to(x, y)
            cr.stroke()

        # Draw Direct Speed (Cyan Blue)
        draw_series("normal_down", 0.22, 0.74, 0.97, fill_alpha=0.18)

        # Draw VPN Speed (Purple)
        draw_series("vpn_down", 0.75, 0.52, 0.99, fill_alpha=0.22)

    def _on_tick(self) -> bool:
        snapshot = self.collector.get_snapshot()

        speeds = snapshot["speeds"]
        session = snapshot["session_usage"]
        today = snapshot["today_usage"]
        wifi = snapshot["wifi"]
        ping = snapshot["ping"]
        vpn = snapshot.get("vpn", snapshot.get("throne", {}))
        throne = vpn

        # 1. Update Header & Badge
        if vpn["tun_active"]:
            proto = vpn.get('profile_type', 'ACTIVE')
            self.vpn_badge.set_label(f"VPN: {proto}")
            self.vpn_badge.remove_css_class("badge-vpn-inactive")
            self.vpn_badge.add_css_class("badge-vpn-active")
            self.card_vpn_title.set_label(f"VPN / Proxy ({proto})")
        else:
            self.vpn_badge.set_label("DIRECT ONLY")
            self.vpn_badge.remove_css_class("badge-vpn-active")
            self.vpn_badge.add_css_class("badge-vpn-inactive")
            self.card_vpn_title.set_label("VPN / Proxy")

        # 2. Update Quick Status Strip
        wifi_ssid = wifi.get("ssid", "Disconnected")
        wifi_sig = wifi.get("signal", 0)
        self.pill_wifi_lbl.set_label(f"Wi-Fi: {wifi_ssid} ({wifi_sig}%)")

        inet_p = f"{ping['internet_ping_ms']:.1f}ms" if ping.get('internet_ping_ms') is not None else "--"
        self.pill_ping_lbl.set_label(f"Ping: {inet_p}")

        pub_ip = ping.get("public_ip") or "Checking..."
        self.pill_ip_lbl.set_label(f"IP: {pub_ip}")

        # 3. Update Live Cards
        self.norm_down_lbl.set_label(speeds["normal_down_str"])
        self.norm_sub_lbl.set_label(f"↓ {speeds['normal_down_str']}   ↑ {speeds['normal_up_str']}")
        self.norm_today_lbl.set_label(f"Today: {today['normal_total_str']}")

        self.vpn_down_lbl.set_label(speeds["vpn_down_str"])
        self.vpn_sub_lbl.set_label(f"↓ {speeds['vpn_down_str']}   ↑ {speeds['vpn_up_str']}")
        self.vpn_today_lbl.set_label(f"Today: {today['vpn_total_str']}")

        self.tot_down_lbl.set_label(speeds["total_down_str"])
        self.tot_sub_lbl.set_label(f"↓ {speeds['total_down_str']}   ↑ {speeds['total_up_str']}")
        self.tot_today_lbl.set_label(f"Today: {today['grand_total_str']}")

        # Redraw Live Graph
        self.graph_area.queue_draw()

        # Progress bar
        tot_bps = speeds["total_down_bps"] + speeds["total_up_bps"]
        vpn_bps = speeds["vpn_down_bps"] + speeds["vpn_up_bps"]
        ratio = (vpn_bps / tot_bps) if tot_bps > 0 else (1.0 if vpn["tun_active"] else 0.0)
        self.vpn_prog_bar.set_fraction(min(1.0, max(0.0, ratio)))
        vpn_pct = int(ratio * 100)
        direct_pct = 100 - vpn_pct
        self.split_pct_lbl.set_label(f"{direct_pct}% Direct   |   {vpn_pct}% VPN")

        # Usage Breakdown
        self.val_today_normal.set_label(today["normal_total_str"])
        self.val_today_vpn.set_label(today["vpn_total_str"])
        self.val_today_tot.set_label(today["grand_total_str"])
        self.val_sess_tot.set_label(
            f"{session['grand_total_str']}  (Direct: {session['normal_total_str']}  |  VPN: {session['vpn_total_str']})"
        )

        # 4. Wi-Fi & Diagnostics
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

        # 5. VPN Status & Apps
        self.val_vpn_state.set_label(vpn.get("status_text", "N/A"))
        self.val_vpn_client.set_label(vpn.get("client_name", "None"))
        self.val_vpn_prof.set_label(f"{vpn.get('active_profile', 'None')} ({vpn.get('profile_type', '')})")
        self.val_vpn_tun.set_label(vpn.get("tun_interface") or "Inactive")

        running_procs = [t["name"] for t in vpn.get("running_tools", [])]
        self.val_vpn_procs.set_label(", ".join(running_procs) if running_procs else "None detected")

        # Populate top apps
        top_apps = vpn.get("top_apps", [])
        child = self.app_rows_container.get_first_child()
        while child:
            next_child = child.get_next_sibling()
            self.app_rows_container.remove(child)
            child = next_child

        if not top_apps:
            row = Adw.ActionRow(title="No per-app breakdown available for current client")
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

        # 6. Daily History
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

"""
NetSplit - Modern Native GNOME Desktop Application.
Features real-time speed meters, live Cairo waveform graph, Direct vs Throne VPN traffic split,
Wi-Fi signal diagnostics, Throne per-app statistics, and full Settings customization (Dark/Light/System theme).
"""

import sys
import os
import math
try:
    import gi
    gi.require_version('Gtk', '4.0')
    gi.require_version('Adw', '1')
    from gi.repository import Gtk, Gdk, Adw, GLib, Gio
    import cairo
    HAS_GTK = True
except (ImportError, ValueError):
    HAS_GTK = False
    class _Dummy:
        def __init__(self, *args, **kwargs):
            pass
        def __getattr__(self, name):
            return _Dummy
        def __call__(self, *args, **kwargs):
            return _Dummy()
    class _DummyModule:
        def __getattr__(self, name):
            return _Dummy
        def __call__(self, *args, **kwargs):
            return _Dummy()
    Gtk = Gdk = Adw = GLib = Gio = cairo = _DummyModule()



from core.collector import NetworkCollector, format_bytes, format_speed
from core.tray import create_tray_controller, DISPLAY_MODES
from core.autostart import is_autostart_supported, is_autostart_enabled, set_autostart
from core.security import mask_ip
from core.gnome_extension import (
    is_gnome_available,
    is_arch_linux,
    is_extension_enabled,
    is_extension_installed,
    install_and_enable_extension,
    disable_extension
)
from gui.hud import FloatingHudWindow


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
    background: rgba(38, 162, 105, 0.2);
    color: #34d399;
    border: 1px solid rgba(52, 211, 153, 0.35);
    border-radius: 9999px;
    padding: 3px 10px;
    font-size: 8.5pt;
    font-weight: 700;
}

.badge-vpn-inactive {
    background: alpha(@window_fg_color, 0.08);
    color: alpha(@window_fg_color, 0.7);
    border: 1px solid alpha(@borders, 0.4);
    border-radius: 9999px;
    padding: 3px 10px;
    font-size: 8.5pt;
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
        self.app = app
        self.collector = collector
        self.set_default_size(880, 720)

        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.assets_dir = os.path.join(project_root, "assets")
        display = Gdk.Display.get_default()
        if display:
            icon_theme = Gtk.IconTheme.get_for_display(display)
            icon_theme.add_search_path(self.assets_dir)
        self.set_icon_name("netsplit")

        # Apply CSS
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(CSS_STYLES.encode('utf-8'))
        Gtk.StyleContext.add_provider_for_display(
            self.get_display(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        # IP Privacy reveal states
        self.reveal_local_ip = False
        self.reveal_public_ip = False
        self.reveal_header_ip = False
        self.hud_window = None

        self._build_ui()

        # Apply persisted theme
        self._load_saved_theme()

        # Handle window close request (minimize to tray if enabled)
        self.connect("close-request", self._on_close_request)

        # Immediate first update
        self._on_tick()

        # Refresh timer every 1000ms
        GLib.timeout_add(1000, self._on_tick)

    def _on_close_request(self, window):
        min_to_tray = self.collector.db.get_minimize_to_tray()
        tray_enabled = self.collector.db.get_tray_enabled()
        hud_enabled = self.collector.db.get_hud_enabled()
        if (min_to_tray and tray_enabled) or hud_enabled:
            self.set_visible(False)
            return True  # Keep running in background!
        self.app.quit_application()
        return False

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
        self.vpn_badge.set_valign(Gtk.Align.CENTER)
        self.vpn_badge.add_css_class("badge-vpn-inactive")
        header.pack_end(self.vpn_badge)

        # Actions for primary menu on top
        action_toggle_hud = Gio.SimpleAction.new("toggle_hud", None)
        action_toggle_hud.connect("activate", self._on_menu_toggle_hud)
        self.add_action(action_toggle_hud)

        action_troubleshoot = Gio.SimpleAction.new("troubleshoot", None)
        action_troubleshoot.connect("activate", self._on_menu_troubleshoot)
        self.add_action(action_troubleshoot)

        action_settings = Gio.SimpleAction.new("preferences", None)
        action_settings.connect("activate", self._on_menu_settings)
        self.add_action(action_settings)

        # Primary Options Menu on top
        menu = Gio.Menu()
        menu.append("📊 Toggle Desktop HUD", "win.toggle_hud")
        menu.append("🛠️ Troubleshoot Network...", "win.troubleshoot")
        menu.append("⚙️ Preferences & Settings", "win.preferences")

        section_exit = Gio.Menu()
        section_exit.append("Quit NetSplit", "app.quit")
        menu.append_section(None, section_exit)

        menu_btn = Gtk.MenuButton()
        menu_btn.set_icon_name("open-menu-symbolic")
        menu_btn.set_menu_model(menu)
        menu_btn.set_tooltip_text("Options Menu")
        header.pack_end(menu_btn)

        # Quick Troubleshoot Header Button
        btn_quick_trouble = Gtk.Button()
        btn_quick_trouble.set_label("Troubleshoot")
        btn_quick_trouble.set_tooltip_text("Open Network Diagnostics & Repair")
        btn_quick_trouble.add_css_class("flat")
        btn_quick_trouble.set_valign(Gtk.Align.CENTER)
        btn_quick_trouble.connect("clicked", self._on_menu_troubleshoot)
        header.pack_end(btn_quick_trouble)

        # Quick Mini HUD Header Button
        btn_quick_hud = Gtk.Button()
        btn_quick_hud.set_label("Mini HUD")
        btn_quick_hud.set_tooltip_text("Toggle Floating Desktop HUD Pill")
        btn_quick_hud.add_css_class("flat")
        btn_quick_hud.set_valign(Gtk.Align.CENTER)
        btn_quick_hud.connect("clicked", lambda *args: self._on_menu_toggle_hud(None, None))
        header.pack_end(btn_quick_hud)

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

        # 2. Network & Diagnostics Page (Wi-Fi and LAN)
        self.wifi_page = self._build_wifi_page()
        self.view_stack.add_titled_with_icon(self.wifi_page, "wifi", "Network & Health", "network-wireless-symbolic")


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

        # Pill 3: Egress IP Quick (Clickable to reveal/mask)
        p3 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        p3.add_css_class("status-pill")
        dot3 = Gtk.Label(label="●")
        dot3.set_markup('<span foreground="#c084fc">●</span>')
        self.pill_ip_lbl = Gtk.Label(label="IP: Checking...", halign=Gtk.Align.START)
        self.pill_ip_lbl.add_css_class("status-pill-val")
        p3.append(dot3)
        p3.append(self.pill_ip_lbl)
        p3.set_tooltip_text("Click to toggle IP mask / reveal")
        click_pill = Gtk.GestureClick()
        click_pill.connect("released", self._on_toggle_header_ip)
        p3.add_controller(click_pill)
        strip.append(p3)

        box.append(strip)

        # 3 Main Speed Cards
        cards_grid = Gtk.Grid(column_spacing=12, row_spacing=12, column_homogeneous=True)

        # Card 1: Direct Network (LAN or Wi-Fi)
        c1 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        c1.add_css_class("metric-card")
        h1 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.card_direct_title = Gtk.Label(label="Direct Network", halign=Gtk.Align.START)
        self.card_direct_title.add_css_class("card-title")
        h1.append(self.card_direct_title)

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
        h2.append(self.card_vpn_title)
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
        h3.append(t3)
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

        self.row_today_vpn = Adw.ActionRow(title="Today: VPN / Proxy")
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

        self.group_network = Adw.PreferencesGroup(title="Connection Details")

        self.row_ssid = Adw.ActionRow(title="Network SSID")
        self.val_ssid = Gtk.Label(label="Loading...", halign=Gtk.Align.END)
        self.val_ssid.add_css_class("info-val")
        self.row_ssid.add_suffix(self.val_ssid)
        self.group_network.add(self.row_ssid)

        self.row_signal = Adw.ActionRow(title="Signal Strength")
        self.val_signal = Gtk.Label(label="0%", halign=Gtk.Align.END)
        self.val_signal.add_css_class("info-val")
        self.row_signal.add_suffix(self.val_signal)
        self.group_network.add(self.row_signal)

        self.row_bitrate = Adw.ActionRow(title="Link Bitrate (Capability)")
        self.val_bitrate = Gtk.Label(label="N/A", halign=Gtk.Align.END)
        self.val_bitrate.add_css_class("info-val")
        self.row_bitrate.add_suffix(self.val_bitrate)
        self.group_network.add(self.row_bitrate)

        self.row_band = Adw.ActionRow(title="Frequency Band and Channel")
        self.val_band = Gtk.Label(label="N/A", halign=Gtk.Align.END)
        self.val_band.add_css_class("info-val")
        self.row_band.add_suffix(self.val_band)
        self.group_network.add(self.row_band)

        self.row_security = Adw.ActionRow(title="Security / Encryption")
        self.val_security = Gtk.Label(label="N/A", halign=Gtk.Align.END)
        self.val_security.add_css_class("info-val")
        self.row_security.add_suffix(self.val_security)
        self.group_network.add(self.row_security)

        box.append(self.group_network)


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
        self.btn_reveal_local = Gtk.Button(valign=Gtk.Align.CENTER)
        self.btn_reveal_local.set_icon_name("view-reveal-symbolic")
        self.btn_reveal_local.add_css_class("flat")
        self.btn_reveal_local.set_tooltip_text("Reveal or mask local IP")
        self.btn_reveal_local.connect("clicked", self._on_toggle_reveal_local)
        self.row_local_ip.add_suffix(self.val_local_ip)
        self.row_local_ip.add_suffix(self.btn_reveal_local)
        diag_group.add(self.row_local_ip)

        self.row_public_ip = Adw.ActionRow(title="Public Egress IP")
        self.val_public_ip = Gtk.Label(label="Checking...", halign=Gtk.Align.END)
        self.val_public_ip.add_css_class("info-val")
        self.btn_reveal_public = Gtk.Button(valign=Gtk.Align.CENTER)
        self.btn_reveal_public.set_icon_name("view-reveal-symbolic")
        self.btn_reveal_public.add_css_class("flat")
        self.btn_reveal_public.set_tooltip_text("Reveal or mask public IP")
        self.btn_reveal_public.connect("clicked", self._on_toggle_reveal_public)
        self.row_public_ip.add_suffix(self.val_public_ip)
        self.row_public_ip.add_suffix(self.btn_reveal_public)
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
        self.app_rows = []
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
        self.hist_rows = []
        box.append(self.hist_group)

        clamp.set_child(box)
        scroller.set_child(clamp)
        return scroller

    # --- Page 5: Settings ---
    def _build_settings_page(self) -> Gtk.Widget:
        page = Adw.PreferencesPage()

        # 1. Privacy & Security Group
        privacy_group = Adw.PreferencesGroup(
            title="Privacy and Security",
            description="Control visibility of sensitive network identifiers"
        )
        self.mask_ip_row = Adw.SwitchRow(title="Mask IP Addresses (Privacy Mode)")
        self.mask_ip_row.set_subtitle("Hide sensitive local and public IP addresses across all dashboard views")
        self.mask_ip_row.set_active(self.collector.db.get_mask_ips())
        self.mask_ip_row.connect("notify::active", self._on_mask_ips_changed)
        privacy_group.add(self.mask_ip_row)
        page.add(privacy_group)

        # 2. Appearance & Theme Group
        appearance_group = Adw.PreferencesGroup(
            title="Appearance",
            description="Application styling and color scheme preference"
        )
        self.theme_row = Adw.ComboRow(title="Application Theme")
        self.theme_row.set_subtitle("Switch between dark, light, or follow system default")
        model = Gtk.StringList.new(["System Default", "Dark Theme", "Light Theme"])
        self.theme_row.set_model(model)
        self.theme_row.connect("notify::selected", self._on_theme_changed)
        appearance_group.add(self.theme_row)
        page.add(appearance_group)

        # 3. Background & System Tray Group
        tray_group = Adw.PreferencesGroup(
            title="Background and System Tray",
            description="Background monitoring and system panel integration"
        )

        self.tray_enable_row = Adw.SwitchRow(title="System Tray Integration")
        self.tray_enable_row.set_subtitle("Show status icon and live speeds in desktop notification area")
        self.tray_enable_row.set_active(self.collector.db.get_tray_enabled())
        self.tray_enable_row.connect("notify::active", self._on_tray_enabled_changed)
        tray_group.add(self.tray_enable_row)

        self.min_to_tray_row = Adw.SwitchRow(title="Minimize to Tray on Close")
        self.min_to_tray_row.set_subtitle("Closing window keeps NetSplit tracking 24/7 in the background")
        self.min_to_tray_row.set_active(self.collector.db.get_minimize_to_tray())
        self.min_to_tray_row.connect("notify::active", self._on_min_to_tray_changed)
        tray_group.add(self.min_to_tray_row)

        self.start_min_row = Adw.SwitchRow(title="Launch Minimized to Tray")
        self.start_min_row.set_subtitle("Start NetSplit silently in the background on launch")
        self.start_min_row.set_active(self.collector.db.get_start_minimized())
        self.start_min_row.connect("notify::active", self._on_start_min_changed)
        tray_group.add(self.start_min_row)

        if is_autostart_supported():
            self.autostart_row = Adw.SwitchRow(title="Launch on System Startup")
            self.autostart_row.set_subtitle("Automatically start NetSplit in background when logging in")
            self.autostart_row.set_active(is_autostart_enabled())
            self.autostart_row.connect("notify::active", self._on_autostart_changed)
            tray_group.add(self.autostart_row)

        self.tray_mode_row = Adw.ComboRow(title="Top Bar Telemetry Display")
        self.tray_mode_row.set_subtitle("Select metric displayed directly on GNOME Shell top panel")
        tray_model = Gtk.StringList.new([name for _, name in DISPLAY_MODES])
        self.tray_mode_row.set_model(tray_model)
        cur_tray_mode = self.collector.db.get_tray_display_mode()
        keys = [k for k, _ in DISPLAY_MODES]
        idx = keys.index(cur_tray_mode) if cur_tray_mode in keys else 0
        self.tray_mode_row.set_selected(idx)
        self.tray_mode_row.connect("notify::selected", self._on_tray_mode_changed)
        tray_group.add(self.tray_mode_row)

        page.add(tray_group)

        # 4. Mini Floating Desktop HUD Group
        hud_group = Adw.PreferencesGroup(
            title="Mini Floating Desktop HUD",
            description="Movable, translucent always-on-top desktop telemetry pill"
        )
        self.hud_enable_row = Adw.SwitchRow(title="Show Floating Desktop HUD")
        self.hud_enable_row.set_subtitle("Display live network speeds widget floating on your desktop")
        self.hud_enable_row.set_active(self.collector.db.get_hud_enabled())
        self.hud_enable_row.connect("notify::active", self._on_hud_enabled_changed)
        hud_group.add(self.hud_enable_row)

        self.hud_mode_row = Adw.ComboRow(title="HUD Display Metric")
        self.hud_mode_row.set_subtitle("Choose which telemetry statistic is featured in the HUD")
        hud_names = [name for k, name in DISPLAY_MODES if k != "icon_only"]
        self.hud_keys = [k for k, _ in DISPLAY_MODES if k != "icon_only"]
        hud_model = Gtk.StringList.new(hud_names)
        self.hud_mode_row.set_model(hud_model)
        cur_hud_mode = self.collector.db.get_hud_display_mode()
        idx_hud = self.hud_keys.index(cur_hud_mode) if cur_hud_mode in self.hud_keys else 0
        self.hud_mode_row.set_selected(idx_hud)
        self.hud_mode_row.connect("notify::selected", self._on_hud_mode_changed)
        hud_group.add(self.hud_mode_row)

        self.hud_opacity_row = Adw.ComboRow(title="HUD Window Opacity")
        self.hud_opacity_row.set_subtitle("Adjust glass transparency level")
        self.hud_opacity_options = [60, 75, 90, 100]
        opacity_model = Gtk.StringList.new([f"{op}%" for op in self.hud_opacity_options])
        self.hud_opacity_row.set_model(opacity_model)
        cur_op = self.collector.db.get_hud_opacity()
        idx_op = self.hud_opacity_options.index(cur_op) if cur_op in self.hud_opacity_options else 2  # default 90%
        self.hud_opacity_row.set_selected(idx_op)
        self.hud_opacity_row.connect("notify::selected", self._on_hud_opacity_changed)
        hud_group.add(self.hud_opacity_row)

        page.add(hud_group)

        # 4b. GNOME Shell Top Bar Extension HUD Group (Arch Linux / GNOME)
        if is_gnome_available():
            ext_installed = is_extension_installed()
            ext_enabled = is_extension_enabled()
            if ext_enabled and not self.collector.db.get_gnome_ext_enabled():
                self.collector.db.set_gnome_ext_enabled(True)

            arch_badge = " (Arch Linux Native)" if is_arch_linux() else ""
            gnome_ext_group = Adw.PreferencesGroup(
                title=f"GNOME Top Bar Extension HUD{arch_badge}",
                description="Live telemetry directly on the GNOME Shell top panel (e.g. Σ 2.59 GB)"
            )

            self.gnome_ext_enable_row = Adw.SwitchRow(title="Show Top Bar Extension HUD")
            sub_text = "Active on top panel" if ext_enabled else "Embed live network usage directly into GNOME top bar"
            self.gnome_ext_enable_row.set_subtitle(sub_text)
            self.gnome_ext_enable_row.set_active(ext_enabled)
            self.gnome_ext_enable_row.connect("notify::active", self._on_gnome_ext_enabled_changed)
            gnome_ext_group.add(self.gnome_ext_enable_row)

            self.gnome_ext_mode_row = Adw.ComboRow(title="Top Bar Display Metric")
            self.gnome_ext_mode_row.set_subtitle("Choose which statistic is featured on the top panel")
            gnome_ext_names = [name for k, name in DISPLAY_MODES if k != "icon_only"]
            self.gnome_ext_keys = [k for k, _ in DISPLAY_MODES if k != "icon_only"]
            gnome_ext_model = Gtk.StringList.new(gnome_ext_names)
            self.gnome_ext_mode_row.set_model(gnome_ext_model)
            cur_ext_mode = self.collector.db.get_gnome_ext_display_mode()
            idx_ext = self.gnome_ext_keys.index(cur_ext_mode) if cur_ext_mode in self.gnome_ext_keys else 0
            self.gnome_ext_mode_row.set_selected(idx_ext)
            self.gnome_ext_mode_row.connect("notify::selected", self._on_gnome_ext_mode_changed)
            gnome_ext_group.add(self.gnome_ext_mode_row)

            page.add(gnome_ext_group)

        # 5. VPN and Proxy Engine Group
        proxy_settings_group = Adw.PreferencesGroup(
            title="VPN and Proxy Compatibility",
            description="Multi-protocol client detection and exclusive accounting rules"
        )

        support_row = Adw.ActionRow(title="Universal VPN / Proxy Detection")
        support_row.set_subtitle("Auto-detects any VPN, Proxy, Tunnel, WireGuard, OpenVPN, Tailscale, Clash, Sing-Box, or Commercial VPN")
        proxy_settings_group.add(support_row)

        self.exclusive_row = Adw.SwitchRow(title="Exclusive Accounting Mode")
        self.exclusive_row.set_subtitle("When VPN is active, Direct Wi-Fi reads 0 B/s and all traffic counts as VPN")
        self.exclusive_row.set_active(self.collector.db.get_exclusive_mode())
        self.exclusive_row.connect("notify::active", self._on_exclusive_mode_changed)
        proxy_settings_group.add(self.exclusive_row)

        # Custom Interface Override Entry
        self.custom_iface_row = Adw.EntryRow(title="Custom Interface Override (Optional)")
        saved_iface = self.collector.db.get_setting("custom_vpn_iface", "")
        self.custom_iface_row.set_text(saved_iface)
        self.custom_iface_row.connect("changed", self._on_custom_iface_changed)
        proxy_settings_group.add(self.custom_iface_row)

        page.add(proxy_settings_group)

        # 5. Network Tools & Troubleshooting Group
        tools_group = Adw.PreferencesGroup(
            title="Network Tools & Troubleshooting",
            description="One-click diagnostic repair utilities for DNS, proxy, and connection stalls"
        )

        flush_dns_row = Adw.ActionRow(title="Flush DNS Resolver Cache")
        flush_dns_row.set_subtitle("Invalidates cached hostnames to resolve broken DNS after VPN/proxy use")
        self.btn_flush_dns = Gtk.Button(label="Flush DNS", valign=Gtk.Align.CENTER)
        self.btn_flush_dns.connect("clicked", self._on_flush_dns_clicked)
        flush_dns_row.add_suffix(self.btn_flush_dns)
        tools_group.add(flush_dns_row)

        reset_proxy_row = Adw.ActionRow(title="Reset Lingering System Proxy")
        reset_proxy_row.set_subtitle("Clears dead localhost proxy redirects left behind by crashed VPN/proxy clients")
        self.btn_reset_proxy = Gtk.Button(label="Reset Proxy", valign=Gtk.Align.CENTER)
        self.btn_reset_proxy.connect("clicked", self._on_reset_proxy_clicked)
        reset_proxy_row.add_suffix(self.btn_reset_proxy)
        tools_group.add(reset_proxy_row)

        renew_dhcp_row = Adw.ActionRow(title="Renew DHCP / Reconnect Network")
        renew_dhcp_row.set_subtitle("Refreshes IP address lease and re-synchronizes the network stack")
        self.btn_renew_dhcp = Gtk.Button(label="Renew Network", valign=Gtk.Align.CENTER)
        self.btn_renew_dhcp.connect("clicked", self._on_renew_dhcp_clicked)
        renew_dhcp_row.add_suffix(self.btn_renew_dhcp)
        tools_group.add(renew_dhcp_row)

        page.add(tools_group)

        # 6. Data & Storage Management Group
        data_group = Adw.PreferencesGroup(
            title="Data and History Management",
            description="Local SQLite statistics storage and database maintenance"
        )

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

        page.add(data_group)

        # 7. About NetSplit Group (Featuring netsplit.svg icon)
        about_group = Adw.PreferencesGroup(title="About NetSplit")

        banner_card = Adw.ActionRow(
            title="NetSplit",
            subtitle="Cross-Platform Network &amp; VPN Traffic Monitor • v1.4.0"
        )
        banner_card.set_activatable(False)
        svg_path = os.path.join(self.assets_dir, "netsplit.svg")
        if os.path.exists(svg_path):
            app_icon = Gtk.Image.new_from_file(svg_path)
            app_icon.set_pixel_size(44)
            app_icon.set_valign(Gtk.Align.CENTER)
            banner_card.add_prefix(app_icon)

        about_group.add(banner_card)

        repo_row = Adw.ActionRow(title="GitHub Repository")
        repo_row.set_subtitle("https://github.com/ChavinduJayakody/NetSplit")
        btn_open_repo = Gtk.Button(label="Open", valign=Gtk.Align.CENTER)
        btn_open_repo.connect("clicked", lambda _: Gio.AppInfo.launch_default_for_uri("https://github.com/ChavinduJayakody/NetSplit", None))
        repo_row.add_suffix(btn_open_repo)
        about_group.add(repo_row)

        page.add(about_group)

        return page

    def _on_exclusive_mode_changed(self, row, param):
        self.collector.db.set_exclusive_mode(row.get_active())
        self._on_tick()

    def _on_mask_ips_changed(self, row, param):
        enabled = row.get_active()
        self.collector.db.set_mask_ips(enabled)
        self._on_tick()

    def _on_toggle_header_ip(self, *args):
        self.reveal_header_ip = not self.reveal_header_ip
        self._on_tick()

    def _on_toggle_reveal_local(self, _):
        self.reveal_local_ip = not self.reveal_local_ip
        icon = "view-conceal-symbolic" if self.reveal_local_ip else "view-reveal-symbolic"
        self.btn_reveal_local.set_icon_name(icon)
        self._on_tick()

    def _on_toggle_reveal_public(self, _):
        self.reveal_public_ip = not self.reveal_public_ip
        icon = "view-conceal-symbolic" if self.reveal_public_ip else "view-reveal-symbolic"
        self.btn_reveal_public.set_icon_name(icon)
        self._on_tick()

    def _on_tray_enabled_changed(self, row, param):
        enabled = row.get_active()
        self.collector.db.set_tray_enabled(enabled)
        if enabled:
            self.app.start_tray()
        else:
            self.app.stop_tray()

    def _on_tray_mode_changed(self, row, param):
        idx = row.get_selected()
        keys = [k for k, _ in DISPLAY_MODES]
        if 0 <= idx < len(keys):
            self.collector.db.set_tray_display_mode(keys[idx])
            self._on_tick()

    def _on_hud_enabled_changed(self, row, param):
        enabled = row.get_active()
        self.collector.db.set_hud_enabled(enabled)
        self.sync_hud_visibility()

    def _on_hud_mode_changed(self, row, param):
        idx = row.get_selected()
        if hasattr(self, "hud_keys") and 0 <= idx < len(self.hud_keys):
            self.collector.db.set_hud_display_mode(self.hud_keys[idx])
            if self.hud_window and self.hud_window.get_visible():
                self.hud_window.update_snapshot(self.collector.get_snapshot())

    def _on_hud_opacity_changed(self, row, param):
        idx = row.get_selected()
        if hasattr(self, "hud_opacity_options") and 0 <= idx < len(self.hud_opacity_options):
            op = self.hud_opacity_options[idx]
            self.collector.db.set_hud_opacity(op)
            if self.hud_window:
                self.hud_window.set_opacity(op / 100.0)

    def _on_gnome_ext_enabled_changed(self, row, param):
        enabled = row.get_active()
        self.collector.db.set_gnome_ext_enabled(enabled)
        if enabled:
            ok, msg = install_and_enable_extension()
            if hasattr(self, "gnome_ext_enable_row"):
                self.gnome_ext_enable_row.set_subtitle("Active on top panel" if ok else f"Extension note: {msg}")
            if hasattr(self.app, "start_tray"):
                self.app.start_tray()
        else:
            disable_extension()
            if hasattr(self, "gnome_ext_enable_row"):
                self.gnome_ext_enable_row.set_subtitle("Extension disabled")

    def _on_gnome_ext_mode_changed(self, row, param):
        idx = row.get_selected()
        if hasattr(self, "gnome_ext_keys") and 0 <= idx < len(self.gnome_ext_keys):
            mode = self.gnome_ext_keys[idx]
            self.collector.db.set_gnome_ext_display_mode(mode)
            if hasattr(self.app, "tray") and self.app.tray and hasattr(self.app.tray, "app_props"):
                self.app.tray.current_display_mode = mode
                self.app.tray.app_props["DisplayMode"] = mode
                self._on_tick()

    def sync_hud_visibility(self):
        enabled = self.collector.db.get_hud_enabled()
        if enabled:
            if not self.hud_window:
                self.hud_window = FloatingHudWindow(
                    self.app,
                    self.collector,
                    on_present_main=self._present_from_hud,
                    on_toggle_hud=self._on_hud_toggled_from_widget,
                )
            self.hud_window.present()
            self.hud_window.update_snapshot(self.collector.get_snapshot())
        elif self.hud_window:
            self.hud_window.set_visible(False)

    def _present_from_hud(self):
        self.set_visible(True)
        self.present()

    def _on_hud_toggled_from_widget(self, enabled: bool):
        if hasattr(self, "hud_enable_row") and self.hud_enable_row:
            self.hud_enable_row.set_active(enabled)

    def _on_menu_toggle_hud(self, action, param):
        new_state = not self.collector.db.get_hud_enabled()
        self.collector.db.set_hud_enabled(new_state)
        if hasattr(self, "hud_enable_row") and self.hud_enable_row:
            self.hud_enable_row.set_active(new_state)
        self.sync_hud_visibility()

    def _on_min_to_tray_changed(self, row, param):
        self.collector.db.set_minimize_to_tray(row.get_active())

    def _on_start_min_changed(self, row, param):
        self.collector.db.set_start_minimized(row.get_active())

    def _on_autostart_changed(self, row, param):
        set_autostart(row.get_active())

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

    def _on_flush_dns_clicked(self, btn):
        from core.network_tools import flush_dns
        btn.set_sensitive(False)
        btn.set_label("Flushing...")
        res = flush_dns()
        btn.set_label("Flushed ✓" if res.get("success") else "Failed")
        GLib.timeout_add(2500, lambda: (btn.set_label("Flush DNS"), btn.set_sensitive(True)))

    def _on_reset_proxy_clicked(self, btn):
        from core.network_tools import reset_system_proxy
        btn.set_sensitive(False)
        btn.set_label("Resetting...")
        res = reset_system_proxy()
        btn.set_label("Reset ✓" if res.get("success") else "Failed")
        GLib.timeout_add(2500, lambda: (btn.set_label("Reset Proxy"), btn.set_sensitive(True)))

    def _on_renew_dhcp_clicked(self, btn):
        from core.network_tools import renew_dhcp
        btn.set_sensitive(False)
        btn.set_label("Renewing...")
        res = renew_dhcp()
        btn.set_label("Renewed ✓" if res.get("success") else "Failed")
        GLib.timeout_add(2500, lambda: (btn.set_label("Renew Network"), btn.set_sensitive(True)))

    def _on_menu_troubleshoot(self, *args):
        self.view_stack.set_visible_child_name("settings")
        if hasattr(self, "btn_flush_dns"):
            self.btn_flush_dns.grab_focus()

    def _on_menu_settings(self, *args):
        self.view_stack.set_visible_child_name("settings")

    # --- Cairo Waveform Drawing ---
    def _draw_speed_graph(self, area, cr, width, height):
        history = self.collector.speed_history

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

        def _set_lbl(widget, txt: str):
            if widget.get_label() != txt:
                widget.set_label(txt)

        conn_type = wifi.get("conn_type", "WLAN")
        is_lan = conn_type == "LAN"
        is_connected = wifi.get("connected", False)

        # 1. Update Header & Badge
        if vpn["tun_active"]:
            proto = vpn.get('profile_type', 'ACTIVE')
            _set_lbl(self.vpn_badge, f"VPN: {proto}")
            if not self.vpn_badge.has_css_class("badge-vpn-active"):
                self.vpn_badge.remove_css_class("badge-vpn-inactive")
                self.vpn_badge.add_css_class("badge-vpn-active")
            _set_lbl(self.card_vpn_title, f"VPN / Proxy ({proto})")
        else:
            _set_lbl(self.vpn_badge, "DIRECT ONLY")
            if not self.vpn_badge.has_css_class("badge-vpn-inactive"):
                self.vpn_badge.remove_css_class("badge-vpn-active")
                self.vpn_badge.add_css_class("badge-vpn-inactive")
            _set_lbl(self.card_vpn_title, "VPN / Proxy")

        # 2. Update Quick Status Strip
        if is_lan:
            lan_status = "Connected" if is_connected else "Disconnected"
            lan_speed = wifi.get("bitrate", "N/A")
            if is_connected:
                _set_lbl(self.pill_wifi_lbl, f"LAN: {lan_status} ({lan_speed})")
            else:
                _set_lbl(self.pill_wifi_lbl, "LAN: Disconnected")
            _set_lbl(self.card_direct_title, "Direct LAN")
        else:
            wifi_ssid = wifi.get("ssid", "Disconnected")
            wifi_sig = wifi.get("signal", 0)
            _set_lbl(self.pill_wifi_lbl, f"Wi-Fi: {wifi_ssid} ({wifi_sig}%)")
            _set_lbl(self.card_direct_title, "Direct Wi-Fi")

        inet_p = f"{ping['internet_ping_ms']:.1f}ms" if ping.get('internet_ping_ms') is not None else "--"
        _set_lbl(self.pill_ping_lbl, f"Ping: {inet_p}")

        raw_pub_ip = ping.get("public_ip") or "Checking..."
        mask_setting = self.collector.db.get_mask_ips()
        header_pub_ip = raw_pub_ip if (not mask_setting or self.reveal_header_ip) else mask_ip(raw_pub_ip)
        _set_lbl(self.pill_ip_lbl, f"IP: {header_pub_ip}")

        # 3. Update Live Cards
        _set_lbl(self.norm_down_lbl, speeds["normal_down_str"])
        _set_lbl(self.norm_sub_lbl, f"↓ {speeds['normal_down_str']}   ↑ {speeds['normal_up_str']}")
        _set_lbl(self.norm_today_lbl, f"Today: {today['normal_total_str']}")

        _set_lbl(self.vpn_down_lbl, speeds["vpn_down_str"])
        _set_lbl(self.vpn_sub_lbl, f"↓ {speeds['vpn_down_str']}   ↑ {speeds['vpn_up_str']}")
        _set_lbl(self.vpn_today_lbl, f"Today: {today['vpn_total_str']}")

        _set_lbl(self.tot_down_lbl, speeds["total_down_str"])
        _set_lbl(self.tot_sub_lbl, f"↓ {speeds['total_down_str']}   ↑ {speeds['total_up_str']}")
        _set_lbl(self.tot_today_lbl, f"Today: {today['grand_total_str']}")

        # Redraw Live Graph only if overview page is visible
        if getattr(self, "view_stack", None) and self.view_stack.get_visible_child_name() == "overview":
            self.graph_area.queue_draw()

        # Progress bar
        tot_bps = speeds["total_down_bps"] + speeds["total_up_bps"]
        vpn_bps = speeds["vpn_down_bps"] + speeds["vpn_up_bps"]
        ratio = (vpn_bps / tot_bps) if tot_bps > 0 else (1.0 if vpn["tun_active"] else 0.0)
        self.vpn_prog_bar.set_fraction(min(1.0, max(0.0, ratio)))
        vpn_pct = int(ratio * 100)
        direct_pct = 100 - vpn_pct
        direct_name = "LAN" if is_lan else "Direct"
        _set_lbl(self.split_pct_lbl, f"{direct_pct}% {direct_name}   |   {vpn_pct}% VPN")

        # Update system tray tooltip & stats
        if hasattr(self.app, "update_tray"):
            tray_mode = self.collector.db.get_tray_display_mode()
            self.app.update_tray(
                speeds["normal_down_str"],
                speeds["vpn_down_str"],
                bool(vpn.get("tun_active", False)),
                snapshot=snapshot,
                display_mode=tray_mode,
            )

        # Update floating desktop HUD if enabled
        if self.collector.db.get_hud_enabled():
            if not self.hud_window:
                self.hud_window = FloatingHudWindow(
                    self.app,
                    self.collector,
                    on_present_main=self._present_from_hud,
                    on_toggle_hud=self._on_hud_toggled_from_widget,
                )
                self.hud_window.present()
            self.hud_window.update_snapshot(snapshot)
        elif self.hud_window and self.hud_window.get_visible():
            self.hud_window.set_visible(False)

        # Usage Breakdown
        _set_lbl(self.val_today_normal, today["normal_total_str"])
        _set_lbl(self.val_today_vpn, today["vpn_total_str"])
        _set_lbl(self.val_today_tot, today["grand_total_str"])
        _set_lbl(self.val_sess_tot,
            f"{session['grand_total_str']}  ({direct_name}: {session['normal_total_str']}  |  VPN: {session['vpn_total_str']})"
        )

        # 4. Connection Details (LAN or Wi-Fi)
        if is_lan:
            if hasattr(self, "group_network"):
                self.group_network.set_title("Wired Ethernet (LAN) Details")
            self.row_ssid.set_title("Interface / Link")
            self.row_signal.set_title("Physical Connection State")
            self.row_bitrate.set_title("Link Speed / Capability")
            self.row_band.set_title("Duplex Mode / Standard")
            self.row_security.set_title("Port Security / Cable")
            _set_lbl(self.val_ssid, wifi.get("ssid", "Wired Connection"))
            _set_lbl(self.val_signal, "Connected (100%)" if is_connected else "Disconnected (0%)")
            _set_lbl(self.val_bitrate, wifi.get("bitrate", "N/A"))
            _set_lbl(self.val_band, wifi.get("band", "Ethernet"))
            _set_lbl(self.val_security, wifi.get("security", "Wired (Physical)"))
        else:
            if hasattr(self, "group_network"):
                self.group_network.set_title("Wi-Fi Connection Details")
            self.row_ssid.set_title("Network SSID")
            self.row_signal.set_title("Signal Strength")
            self.row_bitrate.set_title("Link Bitrate (Capability)")
            self.row_band.set_title("Frequency Band and Channel")
            self.row_security.set_title("Security / Encryption")
            _set_lbl(self.val_ssid, wifi.get("ssid", "Disconnected"))
            _set_lbl(self.val_signal, f"{wifi.get('signal', 0)}%  ({wifi.get('bars', '____')})")
            _set_lbl(self.val_bitrate, wifi.get("bitrate", "N/A"))
            _set_lbl(self.val_band, f"{wifi.get('band', 'N/A')} (Ch {wifi.get('channel', 'N/A')})")
            _set_lbl(self.val_security, wifi.get("security", "N/A"))

        gw_lat = f"{ping.get('gateway_ping_ms'):.2f} ms" if ping.get("gateway_ping_ms") is not None else "--"
        inet_lat = f"{ping.get('internet_ping_ms'):.2f} ms" if ping.get("internet_ping_ms") is not None else "--"
        _set_lbl(self.val_ping_gw, gw_lat)
        _set_lbl(self.val_ping_inet, inet_lat)
        raw_local_ip = wifi.get("local_ip") or "N/A"
        diag_local_ip = raw_local_ip if (not mask_setting or self.reveal_local_ip) else mask_ip(raw_local_ip)
        diag_pub_ip = raw_pub_ip if (not mask_setting or self.reveal_public_ip) else mask_ip(raw_pub_ip)
        _set_lbl(self.val_local_ip, diag_local_ip)
        _set_lbl(self.val_public_ip, diag_pub_ip)


        # 5. VPN Status & Apps
        _set_lbl(self.val_vpn_state, vpn.get("status_text", "N/A"))
        _set_lbl(self.val_vpn_client, vpn.get("client_name", "None"))
        _set_lbl(self.val_vpn_prof, f"{vpn.get('active_profile', 'None')} ({vpn.get('profile_type', '')})")
        _set_lbl(self.val_vpn_tun, vpn.get("tun_interface") or "Inactive")

        running_procs = [t["name"] for t in vpn.get("running_tools", [])]
        _set_lbl(self.val_vpn_procs, ", ".join(running_procs) if running_procs else "None detected")


        # Populate top apps
        top_apps = vpn.get("top_apps", [])
        if top_apps != getattr(self, "_last_top_apps", None):
            self._last_top_apps = list(top_apps)
            for r in self.app_rows:
                self.app_group.remove(r)
            self.app_rows.clear()

            if not top_apps:
                row = Adw.ActionRow(title="No per-app breakdown available for current client")
                self.app_group.add(row)
                self.app_rows.append(row)
            else:
                for app in top_apps:
                    row = Adw.ActionRow(title=app["process"])
                    if app.get("is_connections"):
                        conns = app["total_bytes"]
                        conn_text = f"{conns} active connection" if conns == 1 else f"{conns} active connections"
                        row.set_subtitle(conn_text)
                        lbl = Gtk.Label(label=f"{conns} conns", halign=Gtk.Align.END)
                    else:
                        total_formatted = format_bytes(app["total_bytes"])
                        sub_formatted = f"↓ {format_bytes(app['down_bytes'])}   ↑ {format_bytes(app['up_bytes'])}"
                        row.set_subtitle(sub_formatted)
                        lbl = Gtk.Label(label=total_formatted, halign=Gtk.Align.END)
                    lbl.add_css_class("info-val")
                    row.add_suffix(lbl)
                    self.app_group.add(row)
                    self.app_rows.append(row)

        # 6. Daily History
        now_ts = GLib.get_monotonic_time() / 1_000_000
        if not hasattr(self, "_last_hist_update") or (now_ts - self._last_hist_update > 5.0):
            self._last_hist_update = now_ts
            history = self.collector.db.get_daily_history(days=7)
            for r in self.hist_rows:
                self.hist_group.remove(r)
            self.hist_rows.clear()

            for day in reversed(history):
                row = Adw.ActionRow(title=day["date"])
                norm_str = format_bytes(day["normal_rx"] + day["normal_tx"])
                vpn_str = format_bytes(day["vpn_rx"] + day["vpn_tx"])
                tot_str = format_bytes(day["total_rx"] + day["total_tx"])
                row.set_subtitle(f"Direct: {norm_str}  |  VPN: {vpn_str}")
                lbl = Gtk.Label(label=tot_str, halign=Gtk.Align.END)
                lbl.add_css_class("info-val")
                row.add_suffix(lbl)
                self.hist_group.add(row)
                self.hist_rows.append(row)

        return True


class NetworkMonitorApp(Adw.Application):
    def __init__(self, collector: NetworkCollector, start_minimized: bool = False):
        super().__init__(application_id="io.github.networkmonitor.app")
        self.collector = collector
        self.start_minimized = start_minimized or self.collector.db.get_start_minimized()
        self.main_window = None
        self.tray = None
        self._is_holding = False

    def do_startup(self):
        Adw.Application.do_startup(self)

        # Register Quit action for app menu and shortcuts
        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda *_: self.quit_application())
        self.add_action(quit_action)

        # Initialize System Tray & D-Bus Telemetry Controller
        def _on_mode_dbus(new_mode):
            if self.collector and self.collector.db:
                self.collector.db.set_gnome_ext_display_mode(new_mode)
            if self.main_window and hasattr(self.main_window, "_on_tick"):
                self.main_window._on_tick()

        self.tray = create_tray_controller(
            on_activate=self._on_tray_activate,
            on_quit=self.quit_application,
            on_display_mode_changed=_on_mode_dbus
        )
        if self.collector.db.get_tray_enabled() or self.collector.db.get_gnome_ext_enabled():
            self.tray.start()

        # Hold the application so hiding the window keeps the process running
        if not self._is_holding:
            self.hold()
            self._is_holding = True

    def do_activate(self):
        if not self.main_window:
            self.main_window = MainWindow(self, self.collector)

        if self.start_minimized:
            # Only start minimized once on initial activation
            self.start_minimized = False
            self.main_window.set_visible(False)
        else:
            self.main_window.set_visible(True)
            self.main_window.present()

    def _on_tray_activate(self):
        if self.main_window:
            self.main_window.set_visible(True)
            self.main_window.present()

    def start_tray(self):
        if self.tray and not self.tray.is_running:
            self.tray.start()

    def stop_tray(self):
        if self.tray and self.tray.is_running:
            self.tray.stop()

    def update_tray(self, normal_str: str, vpn_str: str, is_vpn: bool, snapshot: Optional[dict] = None, display_mode: str = "speeds_total"):
        if self.tray and self.tray.is_running:
            self.tray.update_stats(normal_str, vpn_str, is_vpn, snapshot=snapshot, display_mode=display_mode)

    def quit_application(self):
        if self.tray:
            self.tray.stop()
        if self.collector:
            self.collector.stop()
        if self._is_holding:
            self.release()
            self._is_holding = False
        self.quit()


def run_gui(collector: NetworkCollector, start_minimized: bool = False):
    if not HAS_GTK:
        raise RuntimeError("GTK 4 / Libadwaita is not available on this platform. Please run with --desktop or in CLI mode.")
    app = NetworkMonitorApp(collector, start_minimized=start_minimized)
    # Strip custom CLI flags before passing to GTK argument parser
    gtk_args = [arg for arg in sys.argv if arg not in ("--minimized", "--gnome", "--desktop", "--cli", "--web")]
    return app.run(gtk_args)

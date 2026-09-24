"""
NetSplit - Mini Floating Desktop HUD / Widget.
A movable, translucent, always-on-top desktop pill displaying real-time
network speeds, VPN routing status, and daily telemetry.
"""

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gdk, GLib
from typing import Callable, Optional

from core.tray import DISPLAY_MODES, format_telemetry_label


HUD_CSS = """
window.hud-floating-window {
    background-color: transparent;
}

.hud-pill {
    background-color: rgba(18, 24, 38, 0.90);
    border: 1px solid rgba(255, 255, 255, 0.16);
    border-radius: 20px;
    padding: 6px 14px;
    box-shadow: 0 10px 32px rgba(0, 0, 0, 0.55);
    transition: all 180ms ease-in-out;
}

.hud-pill:hover {
    border-color: rgba(53, 132, 228, 0.6);
    box-shadow: 0 12px 36px rgba(0, 0, 0, 0.7);
    background-color: rgba(22, 30, 48, 0.94);
}

.hud-dot {
    min-width: 9px;
    min-height: 9px;
    border-radius: 9999px;
    background-color: #2ec27e;
    margin-right: 2px;
}

.hud-dot.vpn {
    background-color: #a855f7;
    box-shadow: 0 0 8px #a855f7;
}

.hud-dot.disconnected {
    background-color: #e01b24;
}

.hud-primary {
    font-size: 12.5px;
    font-weight: 700;
    font-family: monospace;
    color: #ffffff;
}

.hud-secondary {
    font-size: 9.5px;
    font-weight: 500;
    color: rgba(255, 255, 255, 0.65);
}

.hud-icon-btn {
    min-width: 22px;
    min-height: 22px;
    padding: 2px 4px;
    border-radius: 6px;
    background: transparent;
    border: none;
    color: rgba(255, 255, 255, 0.6);
}

.hud-icon-btn:hover {
    background: rgba(255, 255, 255, 0.15);
    color: #ffffff;
}
"""


class FloatingHudWindow(Gtk.Window):
    """
    Mini floating desktop HUD widget displaying live network telemetry.
    Can be moved anywhere on desktop using Wayland/X11 Gtk.WindowHandle.
    """

    def __init__(
        self,
        app: Gtk.Application,
        collector,
        on_present_main: Optional[Callable[[], None]] = None,
        on_toggle_hud: Optional[Callable[[bool], None]] = None,
    ):
        super().__init__(application=app, title="NetSplit HUD")
        self.collector = collector
        self.on_present_main = on_present_main
        self.on_toggle_hud = on_toggle_hud

        self.set_decorated(False)
        self.set_resizable(False)
        self.set_can_focus(False)
        self.set_focus_on_click(False)
        self.add_css_class("hud-floating-window")

        self._apply_css()
        self._build_ui()
        self.apply_saved_opacity()

    def _apply_css(self):
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(HUD_CSS.encode("utf-8"))
        display = Gdk.Display.get_default()
        if display:
            Gtk.StyleContext.add_provider_for_display(
                display, css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )

    def apply_saved_opacity(self):
        opacity_val = self.collector.db.get_hud_opacity()
        self.set_opacity(opacity_val / 100.0)

    def _build_ui(self):
        # WindowHandle enables native compositor dragging across Wayland & X11
        self.handle = Gtk.WindowHandle()

        # Pill Container
        self.pill_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.pill_box.add_css_class("hud-pill")

        # 1. Status Indicator Dot
        self.status_dot = Gtk.Box()
        self.status_dot.add_css_class("hud-dot")
        self.status_dot.set_valign(Gtk.Align.CENTER)
        self.pill_box.append(self.status_dot)

        # 2. Telemetry Text Labels
        labels_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        labels_box.set_valign(Gtk.Align.CENTER)

        self.primary_lbl = Gtk.Label(label="↓ 0 B/s   ↑ 0 B/s")
        self.primary_lbl.add_css_class("hud-primary")
        self.primary_lbl.set_xalign(0.0)
        labels_box.append(self.primary_lbl)

        self.sub_lbl = Gtk.Label(label="NetSplit • Direct")
        self.sub_lbl.add_css_class("hud-secondary")
        self.sub_lbl.set_xalign(0.0)
        labels_box.append(self.sub_lbl)

        self.pill_box.append(labels_box)

        # 3. Quick Action Buttons
        actions_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        actions_box.set_valign(Gtk.Align.CENTER)

        # Options Menu Button
        self.menu_btn = Gtk.MenuButton()
        self.menu_btn.set_icon_name("view-more-symbolic")
        self.menu_btn.add_css_class("hud-icon-btn")
        self.menu_btn.set_tooltip_text("HUD Options & Display Mode")
        self._build_popover()
        actions_box.append(self.menu_btn)

        # Close / Hide HUD Button
        close_btn = Gtk.Button.new_from_icon_name("window-close-symbolic")
        close_btn.add_css_class("hud-icon-btn")
        close_btn.set_tooltip_text("Hide Floating HUD")
        close_btn.connect("clicked", self._on_hide_clicked)
        actions_box.append(close_btn)

        self.pill_box.append(actions_box)
        self.handle.set_child(self.pill_box)
        self.set_child(self.handle)

        # Gestures: Double-click to present main window; right-click for quick menu
        click_gesture = Gtk.GestureClick.new()
        click_gesture.set_button(0)
        click_gesture.connect("pressed", self._on_gesture_pressed)
        self.handle.add_controller(click_gesture)


    def _make_menu_btn(self, label: str, cb) -> Gtk.Button:
        btn = Gtk.Button(label=label)
        btn.set_has_frame(False)
        child = btn.get_child()
        if child and hasattr(child, "set_xalign"):
            child.set_xalign(0.0)
        btn.connect("clicked", cb)
        return btn

    def _build_popover(self):
        self.popover = Gtk.Popover()
        pop_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        pop_box.set_margin_top(6)
        pop_box.set_margin_bottom(6)
        pop_box.set_margin_start(6)
        pop_box.set_margin_end(6)

        # Title: Display Metric
        header_lbl = Gtk.Label(label="Display Metric")
        header_lbl.add_css_class("heading")
        header_lbl.set_xalign(0.0)
        pop_box.append(header_lbl)

        cur_mode = self.collector.db.get_hud_display_mode()
        for key, name in DISPLAY_MODES:
            if key == "icon_only":
                continue
            lbl = f"✔  {name}" if key == cur_mode else f"    {name}"
            btn = self._make_menu_btn(lbl, self._create_mode_cb(key))
            pop_box.append(btn)

        pop_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # Title: Opacity
        opacity_lbl = Gtk.Label(label="HUD Opacity")
        opacity_lbl.add_css_class("heading")
        opacity_lbl.set_xalign(0.0)
        pop_box.append(opacity_lbl)

        cur_op = self.collector.db.get_hud_opacity()
        op_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        for op in (60, 75, 90, 100):
            op_btn = Gtk.Button(label=f"{op}%")
            if op == cur_op:
                op_btn.add_css_class("suggested-action")
            op_btn.connect("clicked", self._create_opacity_cb(op))
            op_box.append(op_btn)
        pop_box.append(op_box)

        pop_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # Open Main App Window
        pop_box.append(self._make_menu_btn("Open NetSplit Dashboard", self._on_open_dashboard_clicked))

        # Hide HUD
        pop_box.append(self._make_menu_btn("Hide Floating HUD", self._on_hide_clicked))

        self.popover.set_child(pop_box)
        self.menu_btn.set_popover(self.popover)

    def _create_mode_cb(self, mode_key: str):
        def cb(button):
            self.collector.db.set_hud_display_mode(mode_key)
            self._build_popover()
            self.popover.popdown()
            # Force immediate visual update
            self.update_snapshot(self.collector.get_snapshot())
        return cb

    def _create_opacity_cb(self, op: int):
        def cb(button):
            self.collector.db.set_hud_opacity(op)
            self.set_opacity(op / 100.0)
            self._build_popover()
            self.popover.popdown()
        return cb

    def _on_gesture_pressed(self, gesture, n_press: int, x: float, y: float):
        button = gesture.get_current_button()
        if button == Gdk.BUTTON_PRIMARY and n_press == 2:
            # Double-click brings main NetSplit window
            if self.on_present_main:
                self.on_present_main()
        elif button == Gdk.BUTTON_SECONDARY:
            # Right-click pops open options
            self.popover.popup()

    def _on_open_dashboard_clicked(self, button):
        self.popover.popdown()
        if self.on_present_main:
            self.on_present_main()

    def _on_hide_clicked(self, button):
        self.collector.db.set_hud_enabled(False)
        self.set_visible(False)
        if self.on_toggle_hud:
            self.on_toggle_hud(False)

    def update_snapshot(self, snapshot: dict):
        """Update live telemetry shown in the floating HUD."""
        if not self.get_visible():
            return

        speeds = snapshot.get("speeds", {})
        today = snapshot.get("today_usage", {})
        wifi = snapshot.get("wifi", {})
        vpn = snapshot.get("vpn", snapshot.get("throne", {}))

        is_vpn = bool(vpn.get("tun_active", False))
        is_connected = bool(wifi.get("connected", False))
        conn_type = wifi.get("conn_type", "WLAN")

        # Update dot status
        self.status_dot.remove_css_class("vpn")
        self.status_dot.remove_css_class("disconnected")
        if not is_connected:
            self.status_dot.add_css_class("disconnected")
        elif is_vpn:
            self.status_dot.add_css_class("vpn")

        # Primary metric based on user setting
        mode = self.collector.db.get_hud_display_mode()
        primary_text = format_telemetry_label(mode, snapshot)
        if not primary_text:
            primary_text = f"↓ {speeds.get('total_down_str', '0 B/s')}   ↑ {speeds.get('total_up_str', '0 B/s')}"
        if self.primary_lbl.get_label() != primary_text:
            self.primary_lbl.set_label(primary_text)

        # Secondary label with quick context
        if is_vpn:
            vpn_name = vpn.get("profile_type") or vpn.get("client_name") or "VPN"
            sub_text = f"Today: {today.get('grand_total_str', '0 B')} • 🔒 {vpn_name}"
        else:
            net_desc = "LAN" if conn_type == "LAN" else wifi.get("ssid", "Direct")
            sub_text = f"Today: {today.get('grand_total_str', '0 B')} • {net_desc}"

        if self.sub_lbl.get_label() != sub_text:
            self.sub_lbl.set_label(sub_text)

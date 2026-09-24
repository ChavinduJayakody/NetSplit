"""
NetSplit - Cross-Platform System Tray & Background Resident Controller.
Native StatusNotifierItem (D-Bus) on Linux and Win32 Shell_NotifyIcon on Windows.
"""

import os
import sys
import platform
import threading
import warnings
from typing import Callable, Optional

warnings.filterwarnings("ignore", category=DeprecationWarning)


DISPLAY_MODES = [
    ("speeds_total", "Total Speeds (↓ / ↑)"),
    ("speeds_split", "Split Speeds (Direct vs VPN)"),
    ("today_total", "Today Total Usage"),
    ("today_split", "Today Split Usage (Direct vs VPN)"),
    ("down_only", "Download Speed Only"),
    ("up_only", "Upload Speed Only"),
    ("full_compact", "Full Compact (Speeds + Today)"),
    ("icon_only", "Icon Only (No Text)"),
]


def format_telemetry_label(
    mode: str,
    snapshot: Optional[dict] = None,
    normal_str: str = "0 B/s",
    vpn_str: str = "0 B/s",
    is_vpn: bool = False
) -> str:
    """Format live telemetry text according to the selected display mode."""
    if mode == "icon_only":
        return ""

    if not snapshot:
        vpn_icon = "🔒 " if is_vpn else ""
        if mode == "down_only":
            return f"{vpn_icon}↓ {normal_str}"
        elif mode == "up_only":
            return f"↑ {normal_str}"
        elif mode == "speeds_split":
            return f"DIR: {normal_str} | VPN: {vpn_str}"
        return f"{vpn_icon}↓ {normal_str}  ↑ {vpn_str}"

    speeds = snapshot.get("speeds", {})
    today = snapshot.get("today_usage", {})
    vpn = snapshot.get("vpn", snapshot.get("throne", {}))
    is_vpn = bool(vpn.get("tun_active", False)) if "tun_active" in vpn else is_vpn
    vpn_icon = "🔒 " if is_vpn else ""

    if mode == "speeds_total":
        down = speeds.get("total_down_str", "0 B/s")
        up = speeds.get("total_up_str", "0 B/s")
        return f"{vpn_icon}↓ {down}  ↑ {up}"
    elif mode == "speeds_split":
        nd = speeds.get("normal_down_str", "0 B/s")
        vd = speeds.get("vpn_down_str", "0 B/s")
        return f"DIR: {nd} | VPN: {vd}"
    elif mode == "today_total":
        tot = today.get("grand_total_str", "0 B")
        vpn_tot = today.get("vpn_total_str", "0 B")
        if is_vpn or (today.get("vpn_rx", 0) + today.get("vpn_tx", 0) > 0):
            return f"Today: {tot} (VPN: {vpn_tot})"
        return f"Today: {tot}"
    elif mode == "today_split":
        nd = today.get("normal_total_str", "0 B")
        vd = today.get("vpn_total_str", "0 B")
        return f"Direct: {nd} | VPN: {vd}"
    elif mode == "down_only":
        down = speeds.get("total_down_str", "0 B/s")
        return f"{vpn_icon}↓ {down}"
    elif mode == "up_only":
        up = speeds.get("total_up_str", "0 B/s")
        return f"↑ {up}"
    elif mode == "full_compact":
        down = speeds.get("total_down_str", "0 B/s")
        up = speeds.get("total_up_str", "0 B/s")
        tot = today.get("grand_total_str", "0 B")
        return f"{vpn_icon}↓{down} ↑{up} | {tot}"
    else:
        down = speeds.get("total_down_str", "0 B/s")
        up = speeds.get("total_up_str", "0 B/s")
        return f"{vpn_icon}↓ {down}  ↑ {up}"


class TrayController:
    """
    Abstract controller for system tray integration and background persistence.
    """
    def __init__(self, on_activate: Optional[Callable[[], None]] = None, on_quit: Optional[Callable[[], None]] = None):
        self.on_activate = on_activate
        self.on_quit = on_quit
        self.is_running = False

    def start(self):
        """Start the system tray icon."""
        pass

    def stop(self):
        """Remove the system tray icon."""
        pass

    def update_tooltip(self, text: str):
        """Update the tooltip text shown on hover."""
        pass

    def update_stats(self, normal_str: str, vpn_str: str, is_vpn: bool, snapshot: Optional[dict] = None, display_mode: str = "speeds_total"):
        """Update live network statistics for the tray."""
        pass


class LinuxDBusTray(TrayController):
    """
    Freedesktop StatusNotifierItem (SNI) implementation using Gio.DBus.
    Native to GTK 4, Wayland, and X11 without pulling in GTK 3 dependencies.
    """
    SNI_XML = """
    <node>
      <interface name='org.kde.StatusNotifierItem'>
        <property name='Category' type='s' access='read'/>
        <property name='Id' type='s' access='read'/>
        <property name='Title' type='s' access='read'/>
        <property name='Status' type='s' access='read'/>
        <property name='IconName' type='s' access='read'/>
        <property name='OverlayIconName' type='s' access='read'/>
        <property name='AttentionIconName' type='s' access='read'/>
        <property name='ItemIsMenu' type='b' access='read'/>
        <property name='ToolTip' type='(sa(iiay)ss)' access='read'/>
        <property name='XAyatanaLabel' type='s' access='read'/>
        <property name='XAyatanaLabelGuide' type='s' access='read'/>
        <method name='ContextMenu'>
          <arg type='i' name='x' direction='in'/>
          <arg type='i' name='y' direction='in'/>
        </method>
        <method name='Activate'>
          <arg type='i' name='x' direction='in'/>
          <arg type='i' name='y' direction='in'/>
        </method>
        <method name='SecondaryActivate'>
          <arg type='i' name='x' direction='in'/>
          <arg type='i' name='y' direction='in'/>
        </method>
        <method name='Scroll'>
          <arg type='i' name='delta' direction='in'/>
          <arg type='s' name='orientation' direction='in'/>
        </method>
        <signal name='NewTitle'/>
        <signal name='NewIcon'/>
        <signal name='NewAttentionIcon'/>
        <signal name='NewOverlayIcon'/>
        <signal name='NewToolTip'/>
        <signal name='NewStatus'>
          <arg type='s' name='status'/>
        </signal>
        <signal name='XAyatanaNewLabel'>
          <arg type='s' name='label'/>
          <arg type='s' name='guide'/>
        </signal>
      </interface>
    </node>
    """

    def __init__(self, on_activate: Optional[Callable[[], None]] = None, on_quit: Optional[Callable[[], None]] = None):
        super().__init__(on_activate, on_quit)
        self.bus = None
        self.reg_id = None
        self.owner_id = None
        self.tooltip_text = "NetSplit - Network Monitor"
        self.current_label = ""
        self._init_sni()

    def _init_sni(self):
        try:
            import gi
            gi.require_version('Gio', '2.0')
            from gi.repository import Gio, GLib

            self.GLib = GLib
            self.Gio = Gio
            self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        except Exception as e:
            print(f"[Tray] Gio D-Bus initialization error: {e}")

    def start(self):
        if not self.bus or self.is_running:
            return

        try:
            node_info = self.Gio.DBusNodeInfo.new_for_xml(self.SNI_XML)
            interface_info = node_info.interfaces[0]

            def method_call_cb(conn, sender, object_path, iface_name, method_name, params, invocation):
                if method_name in ("Activate", "SecondaryActivate"):
                    if self.on_activate:
                        self.GLib.idle_add(self.on_activate)
                    invocation.return_value(None)
                elif method_name == "ContextMenu":
                    if self.on_activate:
                        self.GLib.idle_add(self.on_activate)
                    invocation.return_value(None)
                else:
                    invocation.return_value(None)

            def get_prop_cb(conn, sender, object_path, iface_name, prop_name):
                if prop_name == "Category":
                    return self.GLib.Variant('s', "ApplicationStatus")
                elif prop_name == "Id":
                    return self.GLib.Variant('s', "NetSplit")
                elif prop_name == "Title":
                    return self.GLib.Variant('s', self.current_label if self.current_label else "NetSplit")
                elif prop_name == "Status":
                    return self.GLib.Variant('s', "Active")
                elif prop_name in ("IconName", "OverlayIconName", "AttentionIconName"):
                    return self.GLib.Variant('s', "netsplit")
                elif prop_name == "ItemIsMenu":
                    return self.GLib.Variant('b', False)
                elif prop_name == "ToolTip":
                    return self.GLib.Variant('(sa(iiay)ss)', ("netsplit", [], "NetSplit", self.tooltip_text))
                elif prop_name == "XAyatanaLabel":
                    return self.GLib.Variant('s', self.current_label)
                elif prop_name == "XAyatanaLabelGuide":
                    return self.GLib.Variant('s', "000.0 MB/s  000.0 MB/s")
                return None

            self.reg_id = self.bus.register_object(
                "/StatusNotifierItem",
                interface_info,
                method_call_cb,
                get_prop_cb,
                None
            )

            # Register with StatusNotifierWatcher if available
            pid = os.getpid()
            service_name = f"org.kde.StatusNotifierItem-{pid}-1"

            def on_bus_acquired(conn, name):
                try:
                    conn.call(
                        "org.kde.StatusNotifierWatcher",
                        "/StatusNotifierWatcher",
                        "org.kde.StatusNotifierWatcher",
                        "RegisterStatusNotifierItem",
                        self.GLib.Variant("(s)", ("/StatusNotifierItem",)),
                        None,
                        self.Gio.DBusCallFlags.NONE,
                        -1,
                        None,
                        None
                    )
                except Exception:
                    pass

            self.owner_id = self.Gio.bus_own_name_on_connection(
                self.bus,
                service_name,
                self.Gio.BusNameOwnerFlags.NONE,
                on_bus_acquired,
                None
            )

            self.is_running = True
        except Exception as e:
            print(f"[Tray] Failed to start StatusNotifierItem: {e}")

    def update_tooltip(self, text: str):
        self.tooltip_text = text
        if self.is_running and self.bus:
            try:
                # Emit NewToolTip signal
                self.bus.emit_signal(
                    None,
                    "/StatusNotifierItem",
                    "org.kde.StatusNotifierItem",
                    "NewToolTip",
                    None
                )
            except Exception:
                pass

    def update_label(self, label: str):
        """Publish updated telemetry text to GNOME top panel / Ayatana AppIndicator."""
        if self.current_label == label:
            return
        self.current_label = label
        if self.is_running and self.bus:
            try:
                # 1. NewTitle signal (KDE / general SNI)
                self.bus.emit_signal(
                    None,
                    "/StatusNotifierItem",
                    "org.kde.StatusNotifierItem",
                    "NewTitle",
                    None
                )
                # 2. XAyatanaNewLabel signal (Ubuntu / GNOME AppIndicator extension)
                self.bus.emit_signal(
                    None,
                    "/StatusNotifierItem",
                    "org.kde.StatusNotifierItem",
                    "XAyatanaNewLabel",
                    self.GLib.Variant("(ss)", (self.current_label, "000.0 MB/s  000.0 MB/s"))
                )
                # 3. Standard DBus PropertiesChanged signal
                changed_props = {
                    "Title": self.GLib.Variant('s', self.current_label if self.current_label else "NetSplit"),
                    "XAyatanaLabel": self.GLib.Variant('s', self.current_label)
                }
                self.bus.emit_signal(
                    None,
                    "/StatusNotifierItem",
                    "org.freedesktop.DBus.Properties",
                    "PropertiesChanged",
                    self.GLib.Variant("(sa{sv}as)", ("org.kde.StatusNotifierItem", changed_props, []))
                )
            except Exception:
                pass

    def update_stats(self, normal_str: str, vpn_str: str, is_vpn: bool, snapshot: Optional[dict] = None, display_mode: str = "speeds_total"):
        vpn_status = "Active" if is_vpn else "Direct"
        self.update_tooltip(f"NetSplit [{vpn_status}]\nDirect: {normal_str}\nVPN: {vpn_str}")
        new_label = format_telemetry_label(display_mode, snapshot=snapshot, normal_str=normal_str, vpn_str=vpn_str, is_vpn=is_vpn)
        self.update_label(new_label)

    def stop(self):
        if not self.is_running:
            return
        try:
            if self.reg_id and self.bus:
                self.bus.unregister_object(self.reg_id)
                self.reg_id = None
            if self.owner_id:
                self.Gio.bus_unown_name(self.owner_id)
                self.owner_id = None
            self.is_running = False
        except Exception as e:
            print(f"[Tray] Error stopping tray: {e}")


class WindowsTray(TrayController):
    """
    Native Win32 System Tray implementation using Python standard library ctypes.
    Requires no third-party pip dependencies.
    """
    def __init__(self, on_activate: Optional[Callable[[], None]] = None, on_quit: Optional[Callable[[], None]] = None):
        super().__init__(on_activate, on_quit)
        self._thread = None
        self._hwnd = None
        self._nid = None
        self._tooltip = "NetSplit - Network Monitor"

    def start(self):
        if platform.system() != "Windows" or self.is_running:
            return

        def _run_win32_tray():
            try:
                import ctypes
                from ctypes import wintypes

                # Win32 definitions
                WM_USER = 0x0400
                WM_TRAY = WM_USER + 20
                NIM_ADD = 0x00000000
                NIM_MODIFY = 0x00000001
                NIM_DELETE = 0x00000002
                NIF_MESSAGE = 0x00000001
                NIF_ICON = 0x00000002
                NIF_TIP = 0x00000004
                WM_LBUTTONUP = 0x0202
                WM_LBUTTONDBLCLK = 0x0203
                WM_RBUTTONUP = 0x0205
                MF_STRING = 0x0000
                MF_SEPARATOR = 0x0800
                TPM_BOTTOMALIGN = 0x0020
                TPM_RIGHTALIGN = 0x0008

                user32 = ctypes.windll.user32
                kernel32 = ctypes.windll.kernel32
                shell32 = ctypes.windll.shell32

                class NOTIFYICONDATA(ctypes.Structure):
                    _fields_ = [
                        ('cbSize', wintypes.DWORD),
                        ('hWnd', wintypes.HWND),
                        ('uID', wintypes.UINT),
                        ('uFlags', wintypes.UINT),
                        ('uCallbackMessage', wintypes.UINT),
                        ('hIcon', wintypes.HICON),
                        ('szTip', wintypes.WCHAR * 128),
                        ('dwState', wintypes.DWORD),
                        ('dwStateMask', wintypes.DWORD),
                        ('szInfo', wintypes.WCHAR * 256),
                        ('uTimeoutOrVersion', wintypes.UINT),
                        ('szInfoTitle', wintypes.WCHAR * 64),
                        ('dwInfoFlags', wintypes.DWORD),
                    ]

                # Window procedure callback
                WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_long, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

                def wnd_proc(hwnd, msg, wparam, lparam):
                    if msg == WM_TRAY:
                        if lparam in (WM_LBUTTONUP, WM_LBUTTONDBLCLK):
                            if self.on_activate:
                                self.on_activate()
                        elif lparam == WM_RBUTTONUP:
                            # Show popup menu
                            hmenu = user32.CreatePopupMenu()
                            user32.AppendMenuW(hmenu, MF_STRING, 1001, "Show NetSplit")
                            user32.AppendMenuW(hmenu, MF_SEPARATOR, 0, "")
                            user32.AppendMenuW(hmenu, MF_STRING, 1002, "Exit NetSplit")

                            pos = wintypes.POINT()
                            user32.GetCursorPos(ctypes.byref(pos))
                            user32.SetForegroundWindow(hwnd)
                            cmd = user32.TrackPopupMenu(
                                hmenu,
                                TPM_BOTTOMALIGN | TPM_RIGHTALIGN | 0x0100,  # TPM_RETURNCMD
                                pos.x, pos.y, 0, hwnd, None
                            )
                            user32.DestroyMenu(hmenu)

                            if cmd == 1001 and self.on_activate:
                                self.on_activate()
                            elif cmd == 1002 and self.on_quit:
                                self.on_quit()
                        return 0
                    return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

                self._wnd_proc = WNDPROC(wnd_proc)

                wc = wintypes.WNDCLASS()
                wc.lpfnWndProc = self._wnd_proc
                wc.hInstance = kernel32.GetModuleHandleW(None)
                wc.lpszClassName = "NetSplitTrayWnd"
                user32.RegisterClassW(ctypes.byref(wc))

                hwnd = user32.CreateWindowExW(
                    0, wc.lpszClassName, "NetSplitTray",
                    0, 0, 0, 0, 0, None, None, wc.hInstance, None
                )
                self._hwnd = hwnd

                # Load application icon or default system info icon
                hicon = user32.LoadIconW(None, ctypes.c_void_p(32516))  # IDI_INFORMATION

                nid = NOTIFYICONDATA()
                nid.cbSize = ctypes.sizeof(NOTIFYICONDATA)
                nid.hWnd = hwnd
                nid.uID = 1
                nid.uFlags = NIF_ICON | NIF_MESSAGE | NIF_TIP
                nid.uCallbackMessage = WM_TRAY
                nid.hIcon = hicon
                nid.szTip = self._tooltip[:127]
                self._nid = nid

                shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))
                self.is_running = True

                # Message pump
                msg = wintypes.MSG()
                while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                    user32.TranslateMessage(ctypes.byref(msg))
                    user32.DispatchMessageW(ctypes.byref(msg))

            except Exception as e:
                print(f"[Tray] Windows tray error: {e}")

        self._thread = threading.Thread(target=_run_win32_tray, daemon=True)
        self._thread.start()

    def update_tooltip(self, text: str):
        self._tooltip = text
        if platform.system() == "Windows" and self._hwnd and self._nid:
            try:
                import ctypes
                shell32 = ctypes.windll.shell32
                self._nid.szTip = text[:127]
                shell32.Shell_NotifyIconW(0x00000001, ctypes.byref(self._nid))  # NIM_MODIFY
            except Exception:
                pass

    def update_stats(self, normal_str: str, vpn_str: str, is_vpn: bool, snapshot: Optional[dict] = None, display_mode: str = "speeds_total"):
        vpn_status = "VPN ON" if is_vpn else "Direct"
        lbl = format_telemetry_label(display_mode, snapshot=snapshot, normal_str=normal_str, vpn_str=vpn_str, is_vpn=is_vpn)
        if lbl:
            self.update_tooltip(f"NetSplit ({vpn_status}) - {lbl}\nDirect: {normal_str}\nVPN: {vpn_str}")
        else:
            self.update_tooltip(f"NetSplit ({vpn_status})\nDirect: {normal_str}\nVPN: {vpn_str}")

    def stop(self):
        if not self.is_running:
            return
        if platform.system() == "Windows" and self._nid:
            try:
                import ctypes
                shell32 = ctypes.windll.shell32
                shell32.Shell_NotifyIconW(0x00000002, ctypes.byref(self._nid))  # NIM_DELETE
            except Exception:
                pass
        self.is_running = False


def create_tray_controller(on_activate: Optional[Callable[[], None]] = None, on_quit: Optional[Callable[[], None]] = None) -> TrayController:
    """Factory creating the appropriate native tray controller for the current OS."""
    if platform.system() == "Linux":
        return LinuxDBusTray(on_activate=on_activate, on_quit=on_quit)
    elif platform.system() == "Windows":
        return WindowsTray(on_activate=on_activate, on_quit=on_quit)
    return TrayController(on_activate=on_activate, on_quit=on_quit)

/* NetSplit GNOME Shell Top Bar Telemetry Extension (GNOME 45-50+) */
import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import { Extension } from 'resource:///org/gnome/shell/extensions/extension.js';

const NETSPLIT_DBUS_NAME = 'io.github.networkmonitor.App';
const NETSPLIT_DBUS_PATH = '/io/github/networkmonitor/App';
const NETSPLIT_DBUS_IFACE = 'io.github.networkmonitor.App';

const DISPLAY_MODES = [
    { key: 'sigma_today', label: 'Σ Today Usage (e.g. Σ 2.59 GB)' },
    { key: 'speeds_total', label: 'Total Speeds (↓ / ↑)' },
    { key: 'speeds_split', label: 'Split Speeds (Direct vs VPN)' },
    { key: 'today_total', label: 'Today Total Usage' },
    { key: 'today_split', label: 'Today Split Usage' },
    { key: 'down_only', label: 'Download Speed Only' },
    { key: 'up_only', label: 'Upload Speed Only' },
    { key: 'full_compact', label: 'Full Compact (Speeds + Σ Today)' },
];

const Indicator = GObject.registerClass(
class NetSplitIndicator extends PanelMenu.Button {
    _init(extension) {
        super._init(0.0, 'NetSplit Indicator', false);
        this._extension = extension;
        this._displayMode = 'sigma_today';
        this._proxy = null;
        this._timeoutId = null;
        this._prevRx = 0;
        this._prevTx = 0;
        this._prevTime = 0;

        // Container & Top Bar Label
        const box = new St.BoxLayout({
            style_class: 'panel-status-indicators-box',
            y_align: Clutter.ActorAlign.CENTER,
        });

        this._label = new St.Label({
            text: 'Σ --',
            y_align: Clutter.ActorAlign.CENTER,
            style_class: 'netsplit-panel-label',
        });
        box.add_child(this._label);
        this.add_child(box);

        this._buildMenu();
        this._initDBus();
        this._startPolling();
    }

    _buildMenu() {
        this.menu.removeAll();

        // 1. Header State
        this._headerItem = new PopupMenu.PopupMenuItem('NetSplit: Initializing...', { reactive: false });
        this.menu.addMenuItem(this._headerItem);

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        // 2. Real-Time Speeds Section
        this._speedsSection = new PopupMenu.PopupMenuSection();
        this._speedDirectItem = new PopupMenu.PopupMenuItem('Direct:  ↓ 0 B/s   ↑ 0 B/s', { reactive: false });
        this._speedVpnItem = new PopupMenu.PopupMenuItem('VPN:     ↓ 0 B/s   ↑ 0 B/s', { reactive: false });
        this._speedTotalItem = new PopupMenu.PopupMenuItem('Total:   ↓ 0 B/s   ↑ 0 B/s', { reactive: false });
        this._speedsSection.addMenuItem(this._speedDirectItem);
        this._speedsSection.addMenuItem(this._speedVpnItem);
        this._speedsSection.addMenuItem(this._speedTotalItem);
        this.menu.addMenuItem(this._speedsSection);

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        // 3. Today's Cumulative Usage Section
        this._usageSection = new PopupMenu.PopupMenuSection();
        this._usageDirectItem = new PopupMenu.PopupMenuItem('Today Direct:  0 B', { reactive: false });
        this._usageVpnItem = new PopupMenu.PopupMenuItem('Today VPN:     0 B', { reactive: false });
        this._usageTotalItem = new PopupMenu.PopupMenuItem('Today Total:   Σ 0 B', { reactive: false });
        this._usageSection.addMenuItem(this._usageDirectItem);
        this._usageSection.addMenuItem(this._usageVpnItem);
        this._usageSection.addMenuItem(this._usageTotalItem);
        this.menu.addMenuItem(this._usageSection);

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        // 4. Latency / Ping
        this._pingItem = new PopupMenu.PopupMenuItem('Ping: --', { reactive: false });
        this.menu.addMenuItem(this._pingItem);

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        // 5. Display Metric Submenu
        this._modesSubMenu = new PopupMenu.PopupSubMenuMenuItem('Display Metric');
        DISPLAY_MODES.forEach(mode => {
            const mItem = new PopupMenu.PopupMenuItem(mode.label);
            mItem.connect('activate', () => {
                this._setMode(mode.key);
            });
            this._modesSubMenu.menu.addMenuItem(mItem);
        });
        this.menu.addMenuItem(this._modesSubMenu);

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        // 6. Launch / Focus NetSplit Application
        const openAppItem = new PopupMenu.PopupMenuItem('🚀 Open NetSplit Dashboard');
        openAppItem.connect('activate', () => {
            this._openDashboard();
        });
        this.menu.addMenuItem(openAppItem);
    }

    _initDBus() {
        try {
            this._proxy = new Gio.DBusProxy({
                g_connection: Gio.DBus.session,
                g_interface_name: NETSPLIT_DBUS_IFACE,
                g_name: NETSPLIT_DBUS_NAME,
                g_object_path: NETSPLIT_DBUS_PATH,
                g_flags: Gio.DBusProxyFlags.NONE,
            });

            this._proxy.connect('g-properties-changed', () => {
                this._updateFromDBus();
            });

            this._proxy.init_async(GLib.PRIORITY_DEFAULT, null, (proxy, res) => {
                try {
                    this._proxy.init_finish(res);
                    this._updateFromDBus();
                } catch (e) {
                    // NetSplit daemon not running yet, will retry on timer
                }
            });
        } catch (e) {
            console.warn('[NetSplit-HUD] D-Bus proxy init error:', e);
        }
    }

    _setMode(modeKey) {
        this._displayMode = modeKey;
        if (this._proxy) {
            try {
                this._proxy.call(
                    'SetDisplayMode',
                    new GLib.Variant('(s)', [modeKey]),
                    Gio.DBusCallFlags.NONE,
                    -1,
                    null,
                    null
                );
            } catch (e) {}
        }
        this._updateFromDBus();
    }

    _openDashboard() {
        if (this._proxy) {
            try {
                this._proxy.call(
                    'OpenMainWindow',
                    null,
                    Gio.DBusCallFlags.NONE,
                    -1,
                    null,
                    null
                );
                return;
            } catch (e) {}
        }
        // Fallback: spawn command
        try {
            const proc = new Gio.Subprocess({
                argv: ['netsplit'],
                flags: Gio.SubprocessFlags.NONE,
            });
            proc.init(null);
        } catch (e) {
            try {
                const proc = new Gio.Subprocess({
                    argv: ['python3', GLib.build_filenamev([GLib.get_home_dir(), 'Projects/NetworkMonitor/main.py'])],
                    flags: Gio.SubprocessFlags.NONE,
                });
                proc.init(null);
            } catch (err) {}
        }
    }

    _updateFromDBus() {
        if (!this._proxy) return false;
        try {
            const cachedProps = this._proxy.get_cached_property_names();
            if (!cachedProps || cachedProps.length === 0) return false;

            const getProp = (name, def = '') => {
                const val = this._proxy.get_cached_property(name);
                return val ? val.unpack() : def;
            };

            const isVpn = getProp('IsVpnActive', false);
            const vpnName = getProp('VpnName', 'VPN');
            const netName = getProp('NetworkName', 'Direct');
            const normDown = getProp('NormalDownStr', '0 B/s');
            const normUp = getProp('NormalUpStr', '0 B/s');
            const vpnDown = getProp('VpnDownStr', '0 B/s');
            const vpnUp = getProp('VpnUpStr', '0 B/s');
            const totDown = getProp('TotalDownStr', '0 B/s');
            const totUp = getProp('TotalUpStr', '0 B/s');
            const todayTot = getProp('TodayTotalStr', '0 B');
            const todayNorm = getProp('TodayNormalStr', '0 B');
            const todayVpn = getProp('TodayVpnStr', '0 B');
            const pingStr = getProp('PingStr', '--');
            const serverMode = getProp('DisplayMode', this._displayMode);

            if (serverMode) this._displayMode = serverMode;

            // Format top panel label
            let labelText = '';
            const vpnIcon = isVpn ? '🔒 ' : '';

            switch (this._displayMode) {
                case 'sigma_today':
                    labelText = `${vpnIcon}Σ ${todayTot}`;
                    break;
                case 'speeds_total':
                    labelText = `${vpnIcon}↓ ${totDown}  ↑ ${totUp}`;
                    break;
                case 'speeds_split':
                    labelText = `DIR: ${normDown} | VPN: ${vpnDown}`;
                    break;
                case 'today_total':
                    labelText = isVpn ? `Today: ${todayTot} (VPN: ${todayVpn})` : `Today: ${todayTot}`;
                    break;
                case 'today_split':
                    labelText = `Dir: ${todayNorm} | VPN: ${todayVpn}`;
                    break;
                case 'down_only':
                    labelText = `${vpnIcon}↓ ${totDown}`;
                    break;
                case 'up_only':
                    labelText = `↑ ${totUp}`;
                    break;
                case 'full_compact':
                    labelText = `${vpnIcon}↓${totDown} ↑${totUp} | Σ ${todayTot}`;
                    break;
                default:
                    labelText = `${vpnIcon}Σ ${todayTot}`;
                    break;
            }

            this._label.set_text(labelText);

            // Update dropdown menu items
            const statusTxt = isVpn ? `NetSplit • 🔒 ${vpnName}` : `NetSplit • ${netName}`;
            this._headerItem.label.set_text(statusTxt);

            this._speedDirectItem.label.set_text(`Direct:  ↓ ${normDown}   ↑ ${normUp}`);
            this._speedVpnItem.label.set_text(`VPN:     ↓ ${vpnDown}   ↑ ${vpnUp}`);
            this._speedTotalItem.label.set_text(`Total:   ↓ ${totDown}   ↑ ${totUp}`);

            this._usageDirectItem.label.set_text(`Today Direct:  ${todayNorm}`);
            this._usageVpnItem.label.set_text(`Today VPN:     ${todayVpn}`);
            this._usageTotalItem.label.set_text(`Today Total:   Σ ${todayTot}`);

            this._pingItem.label.set_text(`Network: ${netName}  •  Ping: ${pingStr}`);

            return true;
        } catch (e) {
            return false;
        }
    }

    _startPolling() {
        this._timeoutId = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 1, () => {
            const handled = this._updateFromDBus();
            if (!handled) {
                // If D-Bus is not connected or NetSplit is not active yet, fallback
                this._readProcNetFallback();
            }
            return GLib.SOURCE_CONTINUE;
        });
    }

    _readProcNetFallback() {
        try {
            const [ok, contents] = GLib.file_get_contents('/proc/net/dev');
            if (!ok) return;
            const text = new TextDecoder().decode(contents);
            const lines = text.split('\n');
            let totalRx = 0, totalTx = 0;
            for (let i = 2; i < lines.length; i++) {
                const line = lines[i].trim();
                if (!line) continue;
                const parts = line.split(/[:\s]+/);
                if (parts.length >= 10) {
                    const iface = parts[0];
                    if (iface === 'lo') continue;
                    totalRx += parseInt(parts[1], 10) || 0;
                    totalTx += parseInt(parts[9], 10) || 0;
                }
            }
            const now = GLib.get_monotonic_time() / 1000000;
            const formatBytes = (bytes) => {
                if (bytes < 1024) return bytes + ' B';
                if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
                if (bytes < 1024 * 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(2) + ' MB';
                return (bytes / (1024 * 1024 * 1024)).toFixed(2) + ' GB';
            };

            const totUsageStr = formatBytes(totalRx + totalTx);
            if (this._displayMode === 'sigma_today') {
                this._label.set_text(`Σ ${totUsageStr}`);
            } else {
                let downRate = 0, upRate = 0;
                if (this._prevTime > 0) {
                    const dt = Math.max(0.1, now - this._prevTime);
                    downRate = Math.max(0, (totalRx - this._prevRx) / dt);
                    upRate = Math.max(0, (totalTx - this._prevTx) / dt);
                }
                this._prevRx = totalRx;
                this._prevTx = totalTx;
                this._prevTime = now;
                this._label.set_text(`↓ ${formatBytes(downRate)}/s  ↑ ${formatBytes(upRate)}/s`);
            }
            this._headerItem.label.set_text('NetSplit: Background Fallback (Click to Open)');
        } catch (e) {}
    }

    destroy() {
        if (this._timeoutId) {
            GLib.source_remove(this._timeoutId);
            this._timeoutId = null;
        }
        super.destroy();
    }
});

export default class NetSplitExtension extends Extension {
    enable() {
        this._indicator = new Indicator(this);
        Main.panel.addToStatusArea(this.uuid, this._indicator);
    }

    disable() {
        if (this._indicator) {
            this._indicator.destroy();
            this._indicator = null;
        }
    }
}

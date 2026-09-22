# -*- mode: python ; coding: utf-8 -*-
import os
import sys
import platform

block_cipher = None
spec_dir = SPECPATH if 'SPECPATH' in globals() else (os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else os.path.abspath("packaging"))
project_root = os.path.abspath(os.path.join(spec_dir, ".."))

is_windows = platform.system() == "Windows"
icon_path = os.path.join(project_root, "assets", "netsplit.ico" if is_windows else "netsplit.png")

datas = [
    (os.path.join(project_root, "assets"), "assets"),
    (os.path.join(project_root, "web", "static"), "web/static"),
    (os.path.join(project_root, "netsplit.desktop"), "."),
]

hidden_imports = [
    "psutil",
    "sqlite3",
    "urllib.request",
    "http.server",
    "threading",
    "socket",
    "subprocess",
    "json",
    "datetime",
    "platform",
    "ctypes",
    "contextlib",
]

# On Windows pywebview is the native engine
if is_windows:
    hidden_imports += [
        "webview",
        "webview.platforms.winforms",
        "webview.platforms.edgechromium",
    ]
else:
    hidden_imports += [
        "gi",
        "gi.repository.Gtk",
        "gi.repository.Gdk",
        "gi.repository.Gsk",
        "gi.repository.Adw",
        "gi.repository.GLib",
        "gi.repository.Gio",
        "cairo",
        "webview",
    ]

a = Analysis(
    [os.path.join(project_root, "main.py")],
    pathex=[project_root],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["gi", "gi.repository", "cairo"] if is_windows else [],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="NetSplit",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_path if os.path.exists(icon_path) else None,
)

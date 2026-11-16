# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

block_cipher = None
root = Path(SPECPATH)
vendor_sb = root / "vendor" / "sing-box.exe"

ctk_datas, ctk_binaries, ctk_hiddenimports = collect_all("customtkinter")
qr_datas, qr_binaries, qr_hiddenimports = collect_all("qrcode")

bundle = ctk_datas + qr_datas + [(str(root / "obhod.ico"), ".")]
if (root / "server.json").is_file():
    bundle.append((str(root / "server.json"), "."))
else:
    print("server.json не найден: сборка без встроенного сервера (см. server.example.json)")

a = Analysis(
    ["obhod_app.py"],
    pathex=[str(root)],
    binaries=[(str(vendor_sb), ".")] + ctk_binaries + qr_binaries,
    datas=bundle,
    hiddenimports=ctk_hiddenimports + qr_hiddenimports + [
        "obhod_core", "obhod_win", "obhod_gui", "obhod_provision", "obhod_icons", "paramiko", "PIL.ImageTk",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["obhod_linux"],
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
    name="OBHOD-VPS-v2.6.1",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    uac_admin=True,
    uac_uiaccess=False,
    icon=str(root / "obhod.ico"),
)

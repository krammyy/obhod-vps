# -*- coding: utf-8 -*-
"""
OBHOD-VPS — portable GUI: TUN (sing-box) -> personal VPS (Hysteria2 / Shadowsocks).
Tunnel starts only when the user flips the toggle ON.

Entry point for Windows (PyInstaller EXE) and Linux (/usr/bin/obhod-vps).
"""
from __future__ import annotations

import sys

import obhod_core as core

if sys.platform == "win32":
    import obhod_win as platform_layer
else:
    import obhod_linux as platform_layer

core.set_platform(platform_layer)

APP_VERSION = core.APP_VERSION


def main() -> None:
    if "--version" in sys.argv:
        print(f"{core.APP_NAME} {core.APP_VERSION}")
        return
    if "--extract-only" in sys.argv:
        print(platform_layer.ensure_singbox())
        print(core.write_config())
        return
    if "--stop" in sys.argv:
        core.stop_obhod()
        return
    if not platform_layer.prepare_privileges():
        return
    if not platform_layer.acquire_single_instance():
        platform_layer.fatal_box("Приложение уже запущено.")
        return
    import obhod_gui

    obhod_gui.run_gui()


if __name__ == "__main__":
    main()

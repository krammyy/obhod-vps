# -*- coding: utf-8 -*-
"""
Linux (Debian) layer.

The .deb installs sing-box to /opt/obhod-vps/sing-box with
cap_net_admin,cap_net_raw,cap_net_bind_service, so the GUI and the tunnel run
as the desktop user — no root, no pkexec. Browser policies are not touched on
Linux; Privacy mode still enforces strict routing, DoH and an IPv6 block.
"""
from __future__ import annotations

import fcntl
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import obhod_core as core

FONT = "DejaVu Sans"
FONT_MONO = "DejaVu Sans Mono"
PRIVACY_EXTRA = ""
SYSTEM_SINGBOX = Path("/opt/obhod-vps/sing-box")
_LOCK_HANDLE = None


def app_dir() -> Path:
    base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "obhod-vps"
    base.mkdir(parents=True, exist_ok=True)
    try:
        base.chmod(0o700)
    except OSError:
        pass
    return base


def protect_file(path: Path) -> None:
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _candidates() -> list[Path]:
    here = Path(__file__).resolve().parent
    return [SYSTEM_SINGBOX, here / "sing-box", here / "vendor" / "linux" / "sing-box",
            core.resource_dir() / "sing-box"]


def ensure_singbox() -> Path:
    for path in _candidates():
        if path.is_file() and os.access(path, os.X_OK):
            return path
    found = shutil.which("sing-box")
    if found:
        return Path(found)
    raise FileNotFoundError("sing-box не найден: переустановите пакет obhod-vps")


def has_net_admin(path: Path) -> bool:
    if os.geteuid() == 0:
        return True
    getcap = shutil.which("getcap") or "/usr/sbin/getcap"
    try:
        out = subprocess.run([getcap, str(path)], capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return False
    return "cap_net_admin" in out


def pid_path() -> Path:
    return app_dir() / "obhod.pid"


def log_path() -> Path:
    return app_dir() / "obhod.log"


def core_log_tail() -> str:
    if not log_path().is_file():
        return ""
    return re.sub(r"\x1b\[[0-9;]*m", "", log_path().read_text(encoding="utf-8", errors="replace")[-800:])


def prepare_privileges() -> bool:
    return True


def acquire_single_instance() -> bool:
    global _LOCK_HANDLE
    _LOCK_HANDLE = open(app_dir() / "gui.lock", "w")
    try:
        fcntl.flock(_LOCK_HANDLE, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def fatal_box(text: str) -> None:
    try:
        import tkinter
        from tkinter import messagebox
        root = tkinter.Tk()
        root.withdraw()
        messagebox.showerror(core.APP_NAME, text[:800])
        root.destroy()
    except Exception:
        print(text, file=sys.stderr)


def run_hidden(args: list[str], timeout: float | None = 30) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)


def _cmdline_of(pid: int) -> list[str]:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return []
    return [part.decode("utf-8", "replace") for part in raw.split(b"\0") if part]


def is_our_process(pid: int) -> bool:
    # /proc/<pid>/exe is unreadable here: a binary started with file capabilities
    # is non-dumpable, so its /proc entry belongs to root. cmdline stays readable.
    args = _cmdline_of(pid)
    if len(args) < 4 or args[1] != "run":
        return False
    try:
        return Path(args[0]).resolve() == ensure_singbox().resolve() and Path(args[3]) == core.config_file()
    except Exception:
        return False


def find_running_pid() -> int | None:
    p = pid_path()
    if p.is_file():
        raw = p.read_text(encoding="ascii", errors="ignore").strip()
        if raw.isdigit() and is_our_process(int(raw)):
            return int(raw)
    try:
        p.unlink(missing_ok=True)
    except Exception:
        pass
    return None


def tun_up() -> bool:
    ip = shutil.which("ip") or "/usr/sbin/ip"
    try:
        out = run_hidden([ip, "-o", "-4", "addr", "show"], timeout=5).stdout
    except Exception:
        return False
    return core.TUN_ADDR in out


def stop_singbox() -> None:
    pid = find_running_pid()
    if pid:
        core.emit_log(f"Остановка sing-box · PID {pid}", "CMD")
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline and is_our_process(pid):
            time.sleep(0.2)
        if is_our_process(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    try:
        pid_path().unlink(missing_ok=True)
    except Exception:
        pass


def clear_leftovers() -> None:
    # sing-box removes its own nftables/ip rules on SIGTERM.
    pass


def launch_singbox(cfg: Path) -> bool:
    sb = ensure_singbox()
    if not has_net_admin(sb):
        core.emit_log(f"У {sb} нет cap_net_admin · выполните: sudo setcap "
                      f"cap_net_admin,cap_net_raw,cap_net_bind_service+ep {sb}", "ERROR")
    err = open(log_path(), "w", encoding="utf-8", errors="replace")
    try:
        proc = subprocess.Popen([str(sb), "run", "-c", str(cfg)], stdout=subprocess.DEVNULL, stderr=err,
                                start_new_session=True)
    finally:
        err.close()
    pid_path().write_text(str(proc.pid), encoding="ascii")
    core.emit_log(f"sing-box запущен · PID {proc.pid}", "INFO")
    for _ in range(50):
        time.sleep(0.5)
        if proc.poll() is not None:
            return False
        if tun_up():
            core.emit_log(f"TUN готов · {core.TUN_ADDR}", "OK")
            return True
    return proc.poll() is None and tun_up()


def apply_privacy_policies() -> None:
    pass


def restore_privacy_policies() -> None:
    pass


def privacy_policies_ok() -> bool:
    return True


def legacy_config_present() -> bool:
    return False


def set_window_icon(root) -> None:
    for path in (Path("/usr/share/icons/hicolor/256x256/apps/obhod-vps.png"),
                 Path(__file__).resolve().parent / "obhod-icon.png"):
        if path.is_file():
            try:
                import tkinter
                img = tkinter.PhotoImage(file=str(path))
                root.iconphoto(True, img)
                root._obhod_icon = img
            except Exception:
                pass
            return


def ssh_key_dir() -> Path:
    path = app_dir() / "keys"
    path.mkdir(exist_ok=True)
    path.chmod(0o700)
    return path

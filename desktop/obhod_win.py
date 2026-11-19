# -*- coding: utf-8 -*-
"""Windows layer: sing-box process, Wintun cleanup, browser privacy policies."""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import winreg
from ctypes import wintypes
from pathlib import Path

import obhod_core as core

SINGBOX_EXE = "sing-box.exe"
SINGBOX_SHA256 = "DB0D779948214CF761011D154C3A5DA36DF20394FA01A9FC798F1DC39FE9D183"
APP_MUTEX_NAME = "Local\\OBHOD-VPS-GUI"
FONT = "Segoe UI"
FONT_MONO = "Consolas"
PRIVACY_EXTRA = " · WebRTC ограничен"
_APP_MUTEX_HANDLE = None

# Browser policies are enabled only while Privacy mode is active and are restored
# to their exact previous values when the tunnel is stopped or the mode changes.
PRIVACY_POLICY_SPECS = (
    (r"SOFTWARE\Policies\Google\Chrome", "DefaultGeolocationSetting", winreg.REG_DWORD, 2),
    (r"SOFTWARE\Policies\Google\Chrome", "WebRtcIPHandling", winreg.REG_SZ, "disable_non_proxied_udp"),
    (r"SOFTWARE\Policies\Microsoft\Edge", "DefaultGeolocationSetting", winreg.REG_DWORD, 2),
    (r"SOFTWARE\Policies\Microsoft\Edge", "WebRtcIPHandlingUrl", winreg.REG_SZ,
     '[{"handling":"disable_non_proxied_udp","url":"*"}]'),
    (r"SOFTWARE\Policies\YandexBrowser", "DefaultGeolocationSetting", winreg.REG_SZ, "2"),
    (r"SOFTWARE\Policies\YandexBrowser", "WebRtcIPHandling", winreg.REG_SZ, "disable_non_proxied_udp"),
)


def app_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "OBHOD-VPS"
    base.mkdir(parents=True, exist_ok=True)
    return base


def protect_file(path: Path) -> None:
    # %LOCALAPPDATA% is already private to the user.
    pass


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False)) and hasattr(sys, "_MEIPASS")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def bundled_singbox() -> Path | None:
    here = Path(__file__).resolve().parent
    cands = [core.resource_dir() / SINGBOX_EXE, here / "vendor" / SINGBOX_EXE, here / SINGBOX_EXE]
    for p in cands:
        if p.is_file() and p.stat().st_size > 1_000_000 and sha256_file(p) == SINGBOX_SHA256:
            return p
    return None


def ensure_singbox() -> Path:
    dest = app_dir() / SINGBOX_EXE
    if dest.is_file() and sha256_file(dest) == SINGBOX_SHA256:
        return dest
    src = bundled_singbox()
    if src is None:
        raise FileNotFoundError("sing-box.exe не найден в сборке")
    shutil.copy2(src, dest)
    if sha256_file(dest) != SINGBOX_SHA256:
        raise RuntimeError("Проверка целостности sing-box.exe не пройдена")
    return dest


def pid_path() -> Path:
    return app_dir() / "_obhod.pid"


def log_path() -> Path:
    return app_dir() / "_obhod.log"


def core_log_tail() -> str:
    if not log_path().is_file():
        return ""
    tail = log_path().read_text(encoding="utf-8", errors="replace")[-800:]
    return re.sub(r"\x1b\[[0-9;]*m", "", tail)


# ─── elevation / single instance ──────────────────────────────


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin() -> None:
    exe = sys.executable
    if is_frozen():
        params = subprocess.list2cmdline(sys.argv[1:])
    else:
        params = subprocess.list2cmdline([str(Path(sys.argv[0]).resolve()), *sys.argv[1:]])
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
    if rc <= 32:
        ctypes.windll.user32.MessageBoxW(0, f"Нужны права администратора (UAC).\nКод: {rc}", core.APP_NAME, 0x10)
        sys.exit(1)
    sys.exit(0)


def prepare_privileges() -> bool:
    """Returns False if the process was handed over to an elevated copy."""
    if not is_admin():
        relaunch_as_admin()
        return False
    return True


def acquire_single_instance() -> bool:
    global _APP_MUTEX_HANDLE
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    _APP_MUTEX_HANDLE = kernel32.CreateMutexW(None, False, APP_MUTEX_NAME)
    return kernel32.GetLastError() != 183


def fatal_box(text: str) -> None:
    ctypes.windll.user32.MessageBoxW(0, text[:800], core.APP_NAME, 0x10)


# ─── processes ────────────────────────────────────────────────


def _hidden_kwargs() -> dict:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0
    return {"startupinfo": si, "creationflags": flags}


def run_hidden(args: list[str], timeout: float | None = 30) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout, **_hidden_kwargs())


def system_exe(name: str) -> str:
    path = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / name
    if not path.is_file():
        raise FileNotFoundError(path)
    return str(path)


def process_path(pid: int) -> Path | None:
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                    ctypes.POINTER(wintypes.DWORD)]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return None
        return Path(buffer.value).resolve()
    finally:
        kernel32.CloseHandle(handle)


def pid_alive(pid: int) -> bool:
    return process_path(pid) is not None


def is_our_process(pid: int) -> bool:
    try:
        expected = (app_dir() / SINGBOX_EXE).resolve()
        actual = process_path(pid)
        return bool(actual and actual == expected and sha256_file(actual) == SINGBOX_SHA256)
    except Exception:
        return False


def terminate_process(pid: int) -> bool:
    if not is_our_process(pid):
        return False
    run_hidden([system_exe("taskkill.exe"), "/PID", str(pid)], timeout=8)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if not pid_alive(pid):
            return True
        time.sleep(0.2)
    PROCESS_TERMINATE = 0x0001
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.TerminateProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
    if not handle:
        return False
    try:
        return bool(kernel32.TerminateProcess(handle, 0))
    finally:
        kernel32.CloseHandle(handle)


class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.c_ulong),
        ("cntUsage", ctypes.c_ulong),
        ("th32ProcessID", ctypes.c_ulong),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", ctypes.c_ulong),
        ("cntThreads", ctypes.c_ulong),
        ("th32ParentProcessID", ctypes.c_ulong),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", ctypes.c_ulong),
        ("szExeFile", ctypes.c_char * 260),
    ]


def find_pids_by_name(exe_name: str) -> list[int]:
    """Find PIDs without spawning tasklist/cmd."""
    TH32CS_SNAPPROCESS = 0x00000002
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32)]
    kernel32.Process32First.restype = wintypes.BOOL
    kernel32.Process32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32)]
    kernel32.Process32Next.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap in (None, wintypes.HANDLE(-1).value):
        return []
    pe = PROCESSENTRY32()
    pe.dwSize = ctypes.sizeof(PROCESSENTRY32)
    pids: list[int] = []
    target = exe_name.lower().encode("ascii", "ignore")
    try:
        more = kernel32.Process32First(snap, ctypes.byref(pe))
        while more:
            if pe.szExeFile.split(b"\0", 1)[0].lower() == target:
                pids.append(int(pe.th32ProcessID))
            more = kernel32.Process32Next(snap, ctypes.byref(pe))
    finally:
        kernel32.CloseHandle(snap)
    return pids


def clear_leftovers() -> None:
    for name in (core.TUN_NAME, "obhod-tun"):
        run_hidden([system_exe("netsh.exe"), "interface", "set", "interface", f"name={name}", "admin=disabled"],
                   timeout=8)
        run_hidden([system_exe("netsh.exe"), "interface", "delete", "interface", f"name={name}"], timeout=8)


def find_running_pid() -> int | None:
    p = pid_path()
    if p.is_file():
        raw = p.read_text(encoding="ascii", errors="ignore").strip()
        if raw.isdigit():
            pid = int(raw)
            if pid_alive(pid) and is_our_process(pid):
                return pid
    try:
        p.unlink(missing_ok=True)
    except Exception:
        pass
    return None


def tun_up() -> bool:
    r = run_hidden([system_exe("netsh.exe"), "interface", "ip", "show", "address"])
    return core.TUN_ADDR in (r.stdout or "") + (r.stderr or "")


def stop_singbox() -> None:
    candidates = set(find_pids_by_name(SINGBOX_EXE))
    pid = find_running_pid()
    if pid:
        candidates.add(pid)
    if candidates:
        core.emit_log(f"Остановка sing-box · PID {', '.join(map(str, sorted(candidates)))}", "CMD")
    for candidate in candidates:
        terminate_process(candidate)
    deadline = time.monotonic() + 6
    while time.monotonic() < deadline:
        if not [c for c in find_pids_by_name(SINGBOX_EXE) if is_our_process(c)]:
            break
        time.sleep(0.2)
    try:
        pid_path().unlink(missing_ok=True)
    except Exception:
        pass


def launch_singbox(cfg: Path) -> bool:
    sb = ensure_singbox()
    try:
        log_path().unlink(missing_ok=True)
    except Exception:
        pass
    err = open(log_path(), "w", encoding="utf-8", errors="replace")
    try:
        proc = subprocess.Popen([str(sb), "run", "-c", str(cfg)], stdout=subprocess.DEVNULL, stderr=err,
                                **_hidden_kwargs())
    finally:
        err.close()
    pid_path().write_text(str(proc.pid), encoding="ascii")
    core.emit_log(f"sing-box запущен · PID {proc.pid}", "INFO")
    for _ in range(50):
        time.sleep(0.5)
        if proc.poll() is not None:
            return False
        if is_our_process(proc.pid) and tun_up():
            core.emit_log(f"TUN {core.TUN_NAME} готов · {core.TUN_ADDR}", "OK")
            return True
    return proc.poll() is None and is_our_process(proc.pid) and tun_up()


# ─── privacy policies ─────────────────────────────────────────


def _policy_id(path: str, name: str) -> str:
    return f"{path}|{name}"


def _read_policy(path: str, name: str) -> dict:
    access = winreg.KEY_QUERY_VALUE | getattr(winreg, "KEY_WOW64_64KEY", 0)
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0, access) as key:
            value, value_type = winreg.QueryValueEx(key, name)
        return {"exists": True, "value": value, "type": value_type}
    except FileNotFoundError:
        return {"exists": False}


def _write_policy(path: str, name: str, value_type: int, value: object) -> None:
    access = winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE | getattr(winreg, "KEY_WOW64_64KEY", 0)
    with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, path, 0, access) as key:
        winreg.SetValueEx(key, name, 0, value_type, value)


def apply_privacy_policies() -> None:
    settings = core.load_settings()
    if settings.get("privacy_policies_active"):
        for path, name, value_type, value in PRIVACY_POLICY_SPECS:
            _write_policy(path, name, value_type, value)
        return
    backup = {_policy_id(path, name): _read_policy(path, name) for path, name, _t, _v in PRIVACY_POLICY_SPECS}
    # Persist the rollback data before touching the registry so even an
    # interrupted start can be recovered on the next launch.
    settings["privacy_policy_backup"] = backup
    settings["privacy_policies_active"] = True
    core.save_settings(settings)
    try:
        for path, name, value_type, value in PRIVACY_POLICY_SPECS:
            _write_policy(path, name, value_type, value)
    except Exception:
        restore_privacy_policies()
        raise


def restore_privacy_policies() -> None:
    settings = core.load_settings()
    if not settings.get("privacy_policies_active"):
        return
    backup = settings.get("privacy_policy_backup") or {}
    errors: list[str] = []
    for path, name, value_type, applied_value in PRIVACY_POLICY_SPECS:
        previous = backup.get(_policy_id(path, name), {"exists": False})
        try:
            current = _read_policy(path, name)
            # Do not overwrite a policy changed by an administrator while the
            # privacy mode was running.
            if current.get("exists") and (current.get("value") != applied_value or current.get("type") != value_type):
                continue
            access = winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE | getattr(winreg, "KEY_WOW64_64KEY", 0)
            with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, path, 0, access) as key:
                if previous.get("exists"):
                    winreg.SetValueEx(key, name, 0, int(previous["type"]), previous.get("value"))
                else:
                    try:
                        winreg.DeleteValue(key, name)
                    except FileNotFoundError:
                        pass
        except Exception as exc:
            errors.append(f"{name}: {exc}")
    if errors:
        raise RuntimeError("Не удалось восстановить политики браузера: " + "; ".join(errors))
    settings["privacy_policies_active"] = False
    settings.pop("privacy_policy_backup", None)
    core.save_settings(settings)


def privacy_policies_ok() -> bool:
    return all(
        (current := _read_policy(path, name)).get("exists")
        and current.get("type") == value_type
        and current.get("value") == value
        for path, name, value_type, value in PRIVACY_POLICY_SPECS
    )


# ─── misc ─────────────────────────────────────────────────────


def legacy_config_present() -> bool:
    """True when a pre-2.x config (direct-detour DNS, system stack, …) is on disk."""
    p = core.config_file()
    if not p.is_file():
        return False
    try:
        old = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return True
    if "gstatic.com/generate_204" in json.dumps(old):
        return True
    servers = (old.get("dns") or {}).get("servers") or []
    has_doh = any(item.get("tag") == "doh" for item in servers)
    resolver = (old.get("route") or {}).get("default_domain_resolver")
    tun = next((i for i in (old.get("inbounds") or []) if i.get("type") == "tun"), {})
    return (not has_doh or resolver != "doh" or not str(tun.get("interface_name") or "").startswith("obh")
            or tun.get("stack") == "system" or core.TUN_ADDR not in json.dumps(tun))


def ensure_icon_file() -> Path | None:
    dest = app_dir() / "obhod.ico"
    here = Path(__file__).resolve().parent
    for src in (core.resource_dir() / "obhod.ico", here / "obhod.ico"):
        if src.is_file() and src.stat().st_size > 1000:
            if not dest.is_file() or dest.stat().st_size != src.stat().st_size:
                shutil.copy2(src, dest)
            return dest
    return dest if dest.is_file() else None


def set_window_icon(root) -> None:
    ico = ensure_icon_file()
    if not ico:
        return
    try:
        root.iconbitmap(default=str(ico))
    except Exception:
        try:
            root.iconbitmap(str(ico))
        except Exception:
            pass


def ssh_key_dir() -> Path:
    path = app_dir() / "keys"
    path.mkdir(exist_ok=True)
    return path

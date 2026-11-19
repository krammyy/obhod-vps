# -*- coding: utf-8 -*-
"""
OBHOD-VPS core: servers, lists, sing-box config and tunnel orchestration.

Nothing here knows about Tk or about a particular OS; the OS layer is
``obhod_win`` or ``obhod_linux`` and is bound through ``set_platform``.
"""
from __future__ import annotations

import base64
import copy
import ipaddress
import json
import re
import secrets
import socket
import sys
import time
import urllib.request
from pathlib import Path

APP_NAME = "OBHOD"
APP_VERSION = "2.6.1"
DEVELOPER = "krammy"
BUNDLED_SERVER_FILE = "server.json"
TUN_NAME = "obh"
TUN_ADDR = "198.18.0.1"
TUN_IPV6_ADDR = "fdfe:dcba:9876::1/126"
LINK_SCHEME = "obhod://add?d="

VALID_MODES = ("work", "home", "privacy")
MODE_NAMES = {"work": "Работа", "home": "Дом", "privacy": "Приватность"}
MODE_HINTS = {
    "work": "Офис и мессенджеры — локально · сайты — через VPS",
    "home": "Интернет через VPS · домашняя сеть остаётся локальной",
    "privacy": "Личный VPS · DNS/WebRTC/геолокация защищены · IPv6 закрыт",
}
TRANSPORTS = {
    "auto": "Авто (Hysteria2 + Shadowsocks)",
    "hy2": "Только Hysteria2 (UDP)",
    "ss": "Только Shadowsocks (TCP)",
}

# VK blocks accounts that come from datacenter exit IPs, so its traffic has to
# stay on the local connection in every mode, Privacy included.
DEFAULT_LISTS: dict[str, list[str]] = {
    # Every mode · resolved by the local DNS so the nearest CDN nodes are used.
    "always_direct_domains": [
        "vk.com", "vk.ru", "vkontakte.ru", "vk.me", "vk.cc", "vk.link",
        "userapi.com", "vk-cdn.net", "vkuseraudio.net", "vkuservideo.net",
        "vkuserlive.net", "vkvideo.ru", "vkmessenger.com", "vk-apps.com",
        "vkforms.ru", "mvk.com",
    ],
    # Safety net for connections whose hostname the sniffer cannot read in time.
    "always_direct_cidr": ["87.240.128.0/18", "95.213.0.0/18"],
    # Work mode only.
    "work_direct_domains": [
        "discord.com", "discord.gg", "discord.media", "discordapp.com",
        "discordapp.net", "discordcdn.com", "discord.gift", "telegram.org",
        "t.me", "telegram.me", "cdn-telegram.org",
    ],
    # Always through the VPS, even when a direct list above matches.
    "proxy_domains": [],
    # Applications (process names) that always go through the VPS, whatever the
    # domain lists say. Windows: chrome.exe, Linux: chrome.
    "proxy_apps": [],
    # Applications that always go through the provider, e.g. a bank client.
    "direct_apps": [],
    # Never captured by the TUN at all (LAN, Radmin VPN, …).
    "route_exclude": ["192.168.0.0/16", "10.0.0.0/8", "172.16.0.0/12", "26.0.0.0/8"],
}

LIST_TITLES = {
    "always_direct_domains": "Напрямую всегда",
    "work_direct_domains": "Напрямую в «Работе»",
    "proxy_domains": "Всегда через VPS",
    "proxy_apps": "Приложения через VPS",
    "direct_apps": "Приложения напрямую",
    "always_direct_cidr": "Подсети напрямую",
    "route_exclude": "Мимо туннеля",
}
LIST_TABS = {
    "always_direct_domains": "Напрямую",
    "work_direct_domains": "Работа",
    "proxy_domains": "Через VPS",
    "proxy_apps": "Приложения",
    "direct_apps": "Прил. мимо",
    "always_direct_cidr": "Подсети",
    "route_exclude": "Мимо TUN",
}
LIST_HINTS = {
    "always_direct_domains": "Домены (с поддоменами), которые во всех режимах идут через ваш провайдер, "
                             "а DNS для них спрашивается у локального резолвера. По умолчанию — VK.",
    "work_direct_domains": "Домены, которые идут напрямую только в режиме «Работа». "
                           "По умолчанию — Discord и Telegram.",
    "proxy_domains": "Домены, которые всегда идут через VPS. Приоритет выше, чем у списков «напрямую».",
    "proxy_apps": "Приложения, которые всегда идут через VPS, даже если их домен есть в списках «напрямую». "
                  "Пишите имя процесса: chrome.exe в Windows, chrome в Linux. Полный путь можно вставить — "
                  "останется только имя файла.",
    "direct_apps": "Приложения, которые всегда идут через вашего провайдера, например банковский клиент. "
                   "Список сильнее «Приложений через VPS»: если процесс указан в обоих, он пойдёт напрямую.",
    "always_direct_cidr": "IP-подсети (CIDR), которые во всех режимах идут напрямую, "
                          "например 87.240.128.0/18.",
    "route_exclude": "Подсети, которые туннель вообще не перехватывает: локальная сеть, "
                     "корпоративный VPN, Radmin (26.0.0.0/8).",
}
DOMAIN_LISTS = ("always_direct_domains", "work_direct_domains", "proxy_domains")
CIDR_LISTS = ("always_direct_cidr", "route_exclude")
APP_LISTS = ("proxy_apps", "direct_apps")

DEFAULT_OPTIONS = {"transport": "auto", "doh_server": "1.1.1.1", "mtu": 1400}

_DOMAIN_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9_](?:[a-z0-9_-]{0,61}[a-z0-9_])?\.)*[a-z0-9-]{1,63}$")
_PROCESS_RE = re.compile(r"^[A-Za-z0-9._+-]{1,64}$")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9._~+/=-]{1,256}$")

_LOG_SINK = None
plat = None  # bound OS layer module


def set_platform(module) -> None:
    global plat
    plat = module


def set_log_sink(sink) -> None:
    global _LOG_SINK
    _LOG_SINK = sink


def emit_log(message: object, level: str = "INFO") -> None:
    """Send a status line to the GUI without coupling core code to Tk."""
    sink = _LOG_SINK
    if sink is None:
        return
    try:
        sink(str(level).upper(), str(message).replace("\r", " ").strip())
    except Exception:
        pass


def resource_dir() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


# ─── settings ─────────────────────────────────────────────────


def _read_json(path: Path, default):
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return default


def _write_json(path: Path, data) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    plat.protect_file(path)


def settings_path() -> Path:
    return plat.app_dir() / "settings.json"


def load_settings() -> dict:
    data = _read_json(settings_path(), {})
    if not isinstance(data, dict):
        data = {}
    data.setdefault("mode", "work")
    return data


def save_settings(data: dict) -> None:
    _write_json(settings_path(), data)


def get_mode() -> str:
    mode = load_settings().get("mode", "work")
    return mode if mode in VALID_MODES else "work"


def set_mode(mode: str) -> None:
    data = load_settings()
    data["mode"] = mode if mode in VALID_MODES else "work"
    save_settings(data)


def get_lists() -> dict[str, list[str]]:
    stored = load_settings().get("lists") or {}
    result = {}
    for key, default in DEFAULT_LISTS.items():
        value = stored.get(key)
        result[key] = list(value) if isinstance(value, list) else list(default)
    return result


def get_options() -> dict:
    stored = load_settings().get("options") or {}
    result = dict(DEFAULT_OPTIONS)
    for key in DEFAULT_OPTIONS:
        if key in stored:
            result[key] = stored[key]
    if result["transport"] not in TRANSPORTS:
        result["transport"] = "auto"
    return result


def normalize_domain(raw: str) -> str:
    value = raw.strip().lower()
    value = re.sub(r"^[a-z]+://", "", value)
    value = value.split("/", 1)[0].split(":", 1)[0]
    value = value.lstrip("*.").lstrip(".").rstrip(".")
    return value


def normalize_process(raw: str) -> str:
    """Application name for a sing-box process_name rule: last path part, no spaces."""
    value = raw.strip().strip('"').strip("'")
    value = value.replace("\\", "/").rsplit("/", 1)[-1]
    return value.strip()


def parse_list(key: str, text: str) -> list[str]:
    """Parse a textbox (one item per line, # comments allowed); raises ValueError."""
    items: list[str] = []
    errors: list[str] = []
    for raw in re.split(r"[\n,;]+", text):
        raw = raw.split("#", 1)[0].strip()
        if not raw:
            continue
        if key in CIDR_LISTS:
            try:
                value = str(ipaddress.ip_network(raw, strict=False))
            except ValueError:
                errors.append(raw)
                continue
        elif key in APP_LISTS:
            value = normalize_process(raw)
            if not _PROCESS_RE.match(value):
                errors.append(raw)
                continue
        else:
            value = normalize_domain(raw)
            if not _DOMAIN_RE.match(value):
                errors.append(raw)
                continue
        if value not in items:
            items.append(value)
    if errors:
        raise ValueError(f"{LIST_TITLES[key]}: не распознано — " + ", ".join(errors[:6]))
    return items


def get_app_paths() -> dict[str, str]:
    """Process name -> exe path, remembered for icons. Config uses names only."""
    stored = load_settings().get("app_paths") or {}
    if not isinstance(stored, dict):
        return {}
    return {str(k): str(v) for k, v in stored.items() if isinstance(k, str) and isinstance(v, str)}


def save_lists_and_options(lists: dict[str, list[str]], options: dict,
                           app_paths: dict[str, str] | None = None) -> None:
    data = load_settings()
    data["lists"] = {key: list(lists.get(key, DEFAULT_LISTS[key])) for key in DEFAULT_LISTS}
    if app_paths is not None:
        allowed = set()
        for key in APP_LISTS:
            allowed.update(lists.get(key) or [])
        data["app_paths"] = {name: path for name, path in app_paths.items()
                             if name in allowed and path}
    merged = dict(DEFAULT_OPTIONS)
    merged.update({k: v for k, v in options.items() if k in DEFAULT_OPTIONS})
    data["options"] = merged
    save_settings(data)


def validate_options(transport: str, doh: str, mtu: str) -> dict:
    if transport not in TRANSPORTS:
        raise ValueError("Неизвестный транспорт")
    doh = doh.strip()
    try:
        ipaddress.ip_address(doh)
    except ValueError:
        if not _DOMAIN_RE.match(doh.lower()):
            raise ValueError("DNS-сервер: нужен IP или домен DoH, например 1.1.1.1")
    try:
        mtu_value = int(mtu)
    except ValueError:
        raise ValueError("MTU должен быть числом")
    if not 1200 <= mtu_value <= 1500:
        raise ValueError("MTU должен быть в диапазоне 1200–1500")
    return {"transport": transport, "doh_server": doh, "mtu": mtu_value}


# ─── servers ──────────────────────────────────────────────────


def servers_path() -> Path:
    return plat.app_dir() / "servers.json"


def new_server_id() -> str:
    return "s" + secrets.token_hex(4)


def server_from_outbounds(outbounds: list[dict], name: str) -> dict:
    """Convert a sing-box outbound set (legacy server.json) into a server record."""
    hy2 = next((o for o in outbounds if o.get("type") == "hysteria2"), None)
    ss = next((o for o in outbounds if o.get("type") == "shadowsocks"), None)
    if not hy2 and not ss:
        raise ValueError("В конфигурации нет ни Hysteria2, ни Shadowsocks")
    host = str((hy2 or ss).get("server") or "")
    server = {"id": new_server_id(), "name": name, "host": host, "added": time.strftime("%Y-%m-%d")}
    if hy2:
        tls = hy2.get("tls") or {}
        server["hy2"] = {
            "port": int(hy2.get("server_port") or 2080),
            "password": str(hy2.get("password") or ""),
            "obfs": str((hy2.get("obfs") or {}).get("password") or ""),
            "sni": str(tls.get("server_name") or "obhod.fast"),
            "cert": str(tls.get("certificate") or ""),
        }
    if ss:
        server["ss"] = {
            "port": int(ss.get("server_port") or 8388),
            "method": str(ss.get("method") or "aes-256-gcm"),
            "password": str(ss.get("password") or ""),
        }
    return validate_server(server)


def validate_server(server: dict) -> dict:
    host = str(server.get("host") or "").strip()
    if not host or not (_is_ip(host) or _DOMAIN_RE.match(host.lower())):
        raise ValueError(f"Некорректный адрес сервера: {host!r}")
    if not server.get("hy2") and not server.get("ss"):
        raise ValueError("У сервера нет ни одного транспорта")
    for key in ("hy2", "ss"):
        block = server.get(key)
        if not block:
            continue
        port = int(block.get("port") or 0)
        if not 1 <= port <= 65535:
            raise ValueError(f"{key}: некорректный порт")
        for field in ("password", "obfs", "sni", "method"):
            value = block.get(field)
            if value and not _TOKEN_RE.match(str(value)):
                raise ValueError(f"{key}.{field}: недопустимые символы")
        if not block.get("password"):
            raise ValueError(f"{key}: пустой пароль")
    server["name"] = (str(server.get("name") or host).strip() or host)[:40]
    server["host"] = host
    return server


def _bundled_server() -> dict | None:
    path = resource_dir() / BUNDLED_SERVER_FILE
    if not path.is_file():
        return None
    try:
        profile = json.loads(path.read_text(encoding="utf-8"))
        return server_from_outbounds(profile.get("outbounds") or [], "FastVPS")
    except Exception as exc:
        emit_log(f"Встроенный профиль не прочитан: {exc}", "WARN")
        return None


def load_servers() -> dict:
    data = _read_json(servers_path(), None)
    if not isinstance(data, dict) or not isinstance(data.get("servers"), list):
        data = {"active": "", "servers": []}
        bundled = _bundled_server()
        if bundled:
            bundled["id"] = "bundled"
            data["servers"].append(bundled)
            data["active"] = bundled["id"]
        _write_json(servers_path(), data)
    ids = [s.get("id") for s in data["servers"]]
    if data.get("active") not in ids:
        data["active"] = ids[0] if ids else ""
    return data


def save_servers(data: dict) -> None:
    _write_json(servers_path(), data)


def list_servers() -> list[dict]:
    return load_servers()["servers"]


def active_server() -> dict:
    data = load_servers()
    for server in data["servers"]:
        if server.get("id") == data.get("active"):
            return server
    raise RuntimeError("Нет ни одного сервера. Добавьте VM в окне «Серверы».")


def active_server_or_none() -> dict | None:
    try:
        return active_server()
    except Exception:
        return None


def set_active_server(server_id: str) -> None:
    data = load_servers()
    if not any(s.get("id") == server_id for s in data["servers"]):
        raise KeyError(server_id)
    data["active"] = server_id
    save_servers(data)


def add_server(server: dict, make_active: bool = False) -> dict:
    server = validate_server(dict(server))
    data = load_servers()
    server.setdefault("id", new_server_id())
    if any(s.get("id") == server["id"] for s in data["servers"]):
        server["id"] = new_server_id()
    names = {s.get("name") for s in data["servers"]}
    base, n = server["name"], 2
    while server["name"] in names:
        server["name"] = f"{base} ({n})"
        n += 1
    data["servers"].append(server)
    if make_active or not data.get("active"):
        data["active"] = server["id"]
    save_servers(data)
    return server


def update_server(server_id: str, **fields) -> None:
    data = load_servers()
    for server in data["servers"]:
        if server.get("id") == server_id:
            server.update(fields)
            validate_server(server)
    save_servers(data)


def remove_server(server_id: str) -> None:
    data = load_servers()
    data["servers"] = [s for s in data["servers"] if s.get("id") != server_id]
    if data.get("active") == server_id:
        data["active"] = data["servers"][0]["id"] if data["servers"] else ""
    save_servers(data)


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def server_ip(server: dict) -> str:
    host = server["host"]
    if _is_ip(host):
        return host
    return socket.gethostbyname(host)


def server_label(server: dict | None) -> str:
    if not server:
        return "нет сервера"
    return f"{server['name']}  ·  {server['host']}"


def probe_server(server: dict, timeout: float = 5) -> tuple[bool, str]:
    """TCP probe of the Shadowsocks port (the one transport a plain socket can test)."""
    ss = server.get("ss")
    if not ss:
        return True, "SS не настроен · проверка TCP пропущена"
    started = time.monotonic()
    try:
        with socket.create_connection((server["host"], int(ss["port"])), timeout=timeout):
            pass
    except Exception as exc:
        return False, f"TCP {ss['port']} недоступен: {exc}"
    return True, f"TCP {ss['port']} отвечает · {int((time.monotonic() - started) * 1000)} мс"


# ─── share links ──────────────────────────────────────────────


def export_link(server: dict) -> str:
    """Compact obhod:// link (fits a small QR); the certificate is left out."""
    payload = {"v": 1, "n": server["name"], "h": server["host"]}
    hy2 = server.get("hy2")
    if hy2:
        payload.update(hp=hy2["port"], hw=hy2["password"], ho=hy2.get("obfs", ""), hs=hy2.get("sni", "obhod.fast"))
    ss = server.get("ss")
    if ss:
        payload.update(sp=ss["port"], sw=ss["password"], sm=ss.get("method", "aes-256-gcm"))
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return LINK_SCHEME + base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def import_link(text: str) -> dict:
    text = text.strip()
    if not text.startswith(LINK_SCHEME):
        raise ValueError("Ожидается ссылка вида obhod://add?d=…")
    blob = text[len(LINK_SCHEME):].split("&", 1)[0]
    blob += "=" * (-len(blob) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(blob.encode("ascii")).decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"Ссылка повреждена: {exc}")
    if payload.get("v") != 1:
        raise ValueError("Неподдерживаемая версия ссылки")
    server = {"id": new_server_id(), "name": payload.get("n") or payload.get("h"), "host": payload.get("h"),
              "added": time.strftime("%Y-%m-%d")}
    if payload.get("hw"):
        server["hy2"] = {"port": int(payload.get("hp") or 2080), "password": payload["hw"],
                         "obfs": payload.get("ho") or "", "sni": payload.get("hs") or "obhod.fast", "cert": ""}
    if payload.get("sw"):
        server["ss"] = {"port": int(payload.get("sp") or 8388), "password": payload["sw"],
                        "method": payload.get("sm") or "aes-256-gcm"}
    return validate_server(server)


def import_file(path: Path) -> dict:
    """Accept either an OBHOD link in a text file or a sing-box client config."""
    text = Path(path).read_text(encoding="utf-8").strip()
    if text.startswith(LINK_SCHEME):
        return import_link(text)
    data = json.loads(text)
    if isinstance(data, dict) and "host" in data and ("hy2" in data or "ss" in data):
        return validate_server(dict(data, id=new_server_id()))
    return server_from_outbounds(data.get("outbounds") or [], Path(path).stem)


# ─── sing-box config ──────────────────────────────────────────


def build_outbounds(server: dict, transport: str) -> tuple[list[dict], str]:
    """Return (outbounds, final tag)."""
    outbounds: list[dict] = []
    hy2 = server.get("hy2")
    ss = server.get("ss")
    if transport == "hy2" and not hy2:
        transport = "ss"
    if transport == "ss" and not ss:
        transport = "hy2"
    if hy2 and transport in ("auto", "hy2"):
        tls = {"enabled": True, "server_name": hy2.get("sni") or "obhod.fast", "alpn": ["h3"], "insecure": True}
        if hy2.get("cert"):
            tls["certificate"] = hy2["cert"]
        item = {
            "type": "hysteria2", "tag": "hy2", "server": server["host"], "server_port": int(hy2["port"]),
            "password": hy2["password"], "up_mbps": 500, "down_mbps": 500, "tls": tls,
        }
        if hy2.get("obfs"):
            item["obfs"] = {"type": "salamander", "password": hy2["obfs"]}
        outbounds.append(item)
    if ss and transport in ("auto", "ss"):
        outbounds.append({
            "type": "shadowsocks", "tag": "ss", "server": server["host"], "server_port": int(ss["port"]),
            "method": ss.get("method") or "aes-256-gcm", "password": ss["password"],
            "udp_over_tcp": {"enabled": True},
        })
    tags = [o["tag"] for o in outbounds]
    if len(tags) > 1:
        outbounds.append({
            "type": "urltest", "tag": "auto", "outbounds": tags,
            "url": "https://1.1.1.1/cdn-cgi/trace", "interval": "3m", "tolerance": 80,
            "idle_timeout": "5m", "interrupt_exist_connections": False,
        })
        final = "auto"
    else:
        final = tags[0]
    outbounds.append({"type": "direct", "tag": "direct"})
    return outbounds, final


def build_config(mode: str = "work", server: dict | None = None, target: str = "desktop") -> dict:
    """target: 'desktop' (Windows/Linux) or 'android'."""
    mode = mode if mode in VALID_MODES else "work"
    server = server or active_server()
    lists = get_lists()
    options = get_options()
    host_ip = server_ip(server)
    privacy = mode == "privacy"
    android = target == "android"
    outbounds, final = build_outbounds(server, options["transport"])
    tags = {o["tag"] for o in outbounds}
    dns_detour = "ss" if "ss" in tags else "hy2"

    route_rules: list[dict] = [
        {"action": "sniff", "timeout": "150ms"},
        {"protocol": "dns", "action": "hijack-dns"},
        {"ip_cidr": [f"{host_ip}/32"], "outbound": "direct"},
        {"ip_is_private": True, "outbound": "direct"},
    ]
    if not android and lists.get("direct_apps"):
        route_rules.append({"process_name": lists["direct_apps"], "outbound": "direct"})
    if not android and lists.get("proxy_apps"):
        route_rules.append({"process_name": lists["proxy_apps"], "outbound": final})
    if lists["proxy_domains"]:
        route_rules.append({"domain_suffix": lists["proxy_domains"], "outbound": final})
    if lists["always_direct_domains"]:
        route_rules.append({"domain_suffix": lists["always_direct_domains"], "outbound": "direct"})
    if lists["always_direct_cidr"]:
        route_rules.append({"ip_cidr": lists["always_direct_cidr"], "outbound": "direct"})
    if privacy:
        # The TUN owns an IPv6 route in this mode, then rejects public IPv6 so a
        # native ISP IPv6 path cannot bypass the VPS.
        route_rules.append({"ip_version": 6, "action": "reject"})
    if mode == "work" and lists["work_direct_domains"]:
        route_rules.append({"domain_suffix": lists["work_direct_domains"], "outbound": "direct"})

    dns_rules = []
    if lists["proxy_domains"]:
        dns_rules.append({"domain_suffix": lists["proxy_domains"], "server": "doh"})
    if lists["always_direct_domains"]:
        dns_rules.append({"domain_suffix": lists["always_direct_domains"], "server": "dns-local"})

    tun = {
        "type": "tun",
        "tag": "tun-in",
        "interface_name": f"obh{int(time.time()) % 1000000}",
        "address": [f"{TUN_ADDR}/30", TUN_IPV6_ADDR] if privacy else [f"{TUN_ADDR}/30"],
        "mtu": 1280 if android else int(options["mtu"]),
        "auto_route": True,
        "strict_route": privacy,
        "stack": "system" if android else "mixed",
        "route_exclude_address": list(lists["route_exclude"]) + [f"{host_ip}/32"],
    }
    return {
        "log": {"level": "info", "timestamp": True},
        "dns": {
            "servers": [
                {"type": "https", "tag": "doh", "server": options["doh_server"], "path": "/dns-query",
                 "detour": dns_detour},
                {"type": "local", "tag": "dns-local"},
            ],
            "rules": dns_rules,
            "final": "doh",
            "strategy": "ipv4_only",
            "independent_cache": True,
        },
        "inbounds": [tun],
        "outbounds": outbounds,
        "route": {
            "auto_detect_interface": not android,
            "default_domain_resolver": "doh",
            "rules": route_rules,
            "final": final,
        },
    }


def config_file() -> Path:
    return plat.app_dir() / "obhod-singbox.json"


def write_config(mode: str | None = None) -> Path:
    path = config_file()
    _write_json(path, build_config(mode or get_mode()))
    return path


def check_config(path: Path) -> tuple[bool, str]:
    sb = plat.ensure_singbox()
    result = plat.run_hidden([str(sb), "check", "-c", str(path)], timeout=20)
    if result.returncode != 0:
        return False, re.sub(r"\x1b\[[0-9;]*m", "", (result.stderr or result.stdout or "Некорректный конфиг"))[-800:]
    return True, ""


# ─── tunnel ───────────────────────────────────────────────────


def is_obhod_on() -> bool:
    return plat.find_running_pid() is not None and plat.tun_up()


def stop_obhod() -> None:
    emit_log("Отключение туннеля…", "CMD")
    plat.stop_singbox()
    time.sleep(1)
    plat.clear_leftovers()
    plat.restore_privacy_policies()
    emit_log("Туннель выключен · маршруты и политики восстановлены", "OK")


def start_obhod() -> tuple[bool, str]:
    server = active_server()
    mode = get_mode()
    expected_ip = server_ip(server)
    emit_log(f"Запуск туннеля · {server['name']} ({server['host']}) · режим {mode}", "CMD")
    if is_obhod_on():
        if mode == "privacy":
            try:
                plat.apply_privacy_policies()
            except Exception as exc:
                emit_log(f"Ошибка политик браузеров: {exc}", "ERROR")
                return False, str(exc)
        emit_log("Туннель уже работает", "OK")
        return True, "Уже включено"
    try:
        cfg = write_config(mode)
        ok, detail = check_config(cfg)
        if not ok:
            emit_log("Конфигурация sing-box не прошла проверку", "ERROR")
            return False, detail
        emit_log("Конфигурация sing-box проверена", "OK")
    except Exception as exc:
        emit_log(f"Подготовка не удалась: {exc}", "ERROR")
        return False, str(exc)

    plat.stop_singbox()
    plat.clear_leftovers()
    time.sleep(1)

    ok = plat.launch_singbox(cfg)
    if not ok:
        emit_log("Первая попытка запуска не удалась · повтор", "WARN")
        plat.stop_singbox()
        plat.clear_leftovers()
        time.sleep(2)
        ok = plat.launch_singbox(cfg)
    if not ok:
        tail = plat.core_log_tail()
        plat.clear_leftovers()
        emit_log("sing-box не запустился", "ERROR")
        return False, f"Не запустился.\n{tail}"

    public_ip, ok_ip = "", False
    for _ in range(3):
        ok_ip, public_ip = tunnel_ip()
        if ok_ip and public_ip == expected_ip:
            break
        time.sleep(2)
    if not ok_ip or public_ip != expected_ip:
        stop_obhod()
        detail = public_ip or "нет ответа"
        emit_log(f"Проверка IP не пройдена · {detail}", "ERROR")
        return False, f"Туннель не прошёл проверку внешнего IP: {detail}"
    emit_log(f"Внешний IP подтверждён · {public_ip}", "OK")
    if mode == "privacy":
        try:
            plat.apply_privacy_policies()
        except Exception as exc:
            stop_obhod()
            emit_log(f"Защита браузеров не включена: {exc}", "ERROR")
            return False, f"Не удалось включить защиту браузеров: {exc}"
        emit_log("DNS · IPv6 · WebRTC · геолокация защищены", "OK")
    else:
        plat.restore_privacy_policies()
    return True, f"Включено · {server['name']} · IP {public_ip}"


def restart_if_running() -> tuple[bool, str] | None:
    """Apply new settings/server to a live tunnel. Returns None if the tunnel was off."""
    if not is_obhod_on():
        write_config()
        return None
    stop_obhod()
    time.sleep(1)
    return start_obhod()


def tunnel_ip() -> tuple[bool, str]:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    last_error = ""
    for url, timeout in (("https://1.1.1.1/cdn-cgi/trace", 5), ("https://api.ipify.org", 4)):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": f"{APP_NAME}/{APP_VERSION}"})
            with opener.open(request, timeout=timeout) as response:
                value = response.read(256).decode("ascii", "replace").strip()
            if "ip=" in value:
                value = next(line.split("=", 1)[1] for line in value.splitlines() if line.startswith("ip="))
            socket.inet_aton(value)
            return True, value
        except Exception as exc:
            last_error = str(exc)
    emit_log(f"Сервис проверки IP недоступен: {last_error}", "WARN")
    return False, last_error


def privacy_status() -> tuple[bool, str]:
    ok_ip, public_ip = tunnel_ip()
    if not ok_ip or public_ip != server_ip(active_server()):
        return False, f"IP не защищён: {public_ip or 'нет ответа'}"
    if not plat.privacy_policies_ok():
        return False, "Политики браузеров не применены"
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        request = urllib.request.Request("https://api6.ipify.org", headers={"User-Agent": f"{APP_NAME}/{APP_VERSION}"})
        with opener.open(request, timeout=4) as response:
            value = response.read(128).decode("ascii", "replace").strip()
        socket.inet_pton(socket.AF_INET6, value)
        return False, f"Обнаружен публичный IPv6: {value}"
    except Exception:
        return True, f"{public_ip} · DNS защищён · IPv6 закрыт" + plat.PRIVACY_EXTRA


def export_android_profile(server: dict) -> dict:
    """A full sing-box profile for the Android app with the user's current lists."""
    cfg = build_config("work", server, target="android")
    return copy.deepcopy(cfg)

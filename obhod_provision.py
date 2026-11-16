# -*- coding: utf-8 -*-
"""
Turn a freshly bought VM (Debian/Ubuntu, root or passwordless sudo) into an
OBHOD server over SSH: sing-box + Hysteria2/Shadowsocks + systemd + BBR.

If the VM already runs an OBHOD sing-box, its credentials are read back instead,
so the same dialog also "adds an existing server".
"""
from __future__ import annotations

import io
import ipaddress
import json
import secrets
import shlex
import socket
import tarfile
import time
import urllib.request
from pathlib import Path

import obhod_core as core

SERVER_SINGBOX_VERSION = "1.13.21"
SINGBOX_URL = "https://github.com/SagerNet/sing-box/releases/download/v{v}/sing-box-{v}-linux-{arch}.tar.gz"
CERT_SNI = "obhod.fast"
REMOTE_DIR = "/etc/sing-box"

SYSTEMD_UNIT = """[Unit]
Description=sing-box (OBHOD personal server)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/sing-box run -c /etc/sing-box/config.json
Restart=on-failure
RestartSec=5s
LimitNOFILE=1048576
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
ProtectKernelTunables=true
ProtectControlGroups=true
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX AF_NETLINK

[Install]
WantedBy=multi-user.target
"""

SYSCTL_CONF = """net.core.default_qdisc=fq
net.ipv4.tcp_congestion_control=bbr
net.core.rmem_max=16777216
net.core.wmem_max=16777216
"""


class ProvisionError(RuntimeError):
    pass


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def generate_ssh_key(path: Path) -> str:
    """Create an ed25519 key pair (OpenSSH format); returns the public line."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519

    key = ed25519.Ed25519PrivateKey.generate()
    private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH,
                                serialization.NoEncryption())
    public = key.public_key().public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH)
    path.write_bytes(private)
    core.plat.protect_file(path)
    line = public.decode("ascii") + f" obhod-vps@{socket.gethostname()}"
    path.with_suffix(".pub").write_text(line + "\n", encoding="ascii")
    return line


class Provisioner:
    def __init__(self, host: str, port: int = 22, user: str = "root", password: str = "",
                 key_path: str = "", log=None):
        self.host = host.strip()
        self.port = int(port or 22)
        self.user = (user or "root").strip()
        self.password = password or ""
        self.key_path = key_path.strip() if key_path else ""
        self.log = log or (lambda msg, level="INFO": None)
        self.client = None
        self.sudo = ""

    # ── ssh plumbing ──

    def connect(self) -> None:
        import paramiko

        if not self.host:
            raise ProvisionError("Не указан адрес VM")
        self.log(f"SSH {self.user}@{self.host}:{self.port} …", "CMD")
        client = paramiko.SSHClient()
        known = core.plat.app_dir() / "known_hosts"
        if known.is_file():
            client.load_host_keys(str(known))
        # Trust on first use: a new VM has never been seen before; the key is
        # pinned afterwards and a change is refused by paramiko.
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(self.host, port=self.port, username=self.user,
                           password=self.password or None, key_filename=self.key_path or None,
                           look_for_keys=False, allow_agent=False, timeout=20, banner_timeout=30,
                           auth_timeout=30)
        except paramiko.AuthenticationException:
            raise ProvisionError("SSH: неверный логин, пароль или ключ")
        except paramiko.BadHostKeyException:
            raise ProvisionError("SSH: ключ хоста изменился с прошлого подключения — возможна подмена. "
                                 f"Если VM переустановлена, удалите строку {self.host} из {known}")
        except Exception as exc:
            raise ProvisionError(f"SSH: не удалось подключиться — {exc}")
        client.save_host_keys(str(known))
        self.client = client
        self.log("SSH подключён", "OK")
        rc, out, _ = self.run("id -u", check=False, sudo=False)
        if out.strip() != "0":
            rc, _, _ = self.run("sudo -n true", check=False, sudo=False)
            if rc != 0:
                raise ProvisionError("Нужен root или sudo без пароля")
            self.sudo = "sudo -n "

    def close(self) -> None:
        if self.client:
            self.client.close()
            self.client = None

    def run(self, cmd: str, check: bool = True, timeout: float = 300, sudo: bool = True) -> tuple[int, str, str]:
        full = f"{self.sudo}sh -c {shlex.quote(cmd)}" if (sudo and self.sudo) else cmd
        _stdin, stdout, stderr = self.client.exec_command(full, timeout=timeout)
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
        rc = stdout.channel.recv_exit_status()
        if check and rc != 0:
            raise ProvisionError(f"Команда не выполнилась ({rc}): {cmd.split(chr(10))[0][:80]}\n{(err or out)[-600:]}")
        return rc, out, err

    def put(self, remote: str, content: bytes, mode: str = "600") -> None:
        tmp = f"/tmp/obhod-{secrets.token_hex(6)}"
        sftp = self.client.open_sftp()
        try:
            with sftp.open(tmp, "wb") as fh:
                fh.write(content)
        finally:
            sftp.close()
        self.run(f"install -D -m {mode} -o root -g root {shlex.quote(tmp)} {shlex.quote(remote)} && rm -f {shlex.quote(tmp)}")

    # ── steps ──

    def read_existing(self) -> dict | None:
        rc, out, _ = self.run(f"cat {REMOTE_DIR}/config.json", check=False)
        if rc != 0 or not out.strip():
            return None
        try:
            cfg = json.loads(out)
        except ValueError:
            raise ProvisionError(f"На VM есть {REMOTE_DIR}/config.json, но это не JSON — разберитесь вручную")
        server: dict = {"host": self.host}
        for inbound in cfg.get("inbounds") or []:
            kind = inbound.get("type")
            if kind == "hysteria2" and "hy2" not in server:
                users = inbound.get("users") or [{}]
                tls = inbound.get("tls") or {}
                cert = ""
                if tls.get("certificate_path"):
                    _rc, cert, _ = self.run(f"cat {shlex.quote(tls['certificate_path'])}", check=False)
                server["hy2"] = {
                    "port": int(inbound.get("listen_port") or 0),
                    "password": users[0].get("password", ""),
                    "obfs": (inbound.get("obfs") or {}).get("password", ""),
                    "sni": tls.get("server_name") or CERT_SNI,
                    "cert": cert.strip() + "\n" if cert.strip() else "",
                }
            elif kind == "shadowsocks" and "ss" not in server:
                server["ss"] = {
                    "port": int(inbound.get("listen_port") or 0),
                    "method": inbound.get("method") or "aes-256-gcm",
                    "password": inbound.get("password") or "",
                }
        if "hy2" not in server and "ss" not in server:
            raise ProvisionError(f"В {REMOTE_DIR}/config.json нет Hysteria2/Shadowsocks — это не сервер OBHOD. "
                                 "Снимите галочку «подключить существующий», чтобы переустановить.")
        return server

    def detect(self) -> str:
        _rc, osr, _ = self.run("cat /etc/os-release", check=False)
        pretty = next((l.split("=", 1)[1].strip('"') for l in osr.splitlines() if l.startswith("PRETTY_NAME=")), "?")
        self.log(f"ОС: {pretty}", "INFO")
        if self.run("command -v apt-get", check=False)[0] != 0:
            raise ProvisionError("Поддерживаются Debian/Ubuntu (нужен apt-get)")
        if self.run("command -v systemctl", check=False)[0] != 0:
            raise ProvisionError("На VM нет systemd")
        _rc, machine, _ = self.run("uname -m")
        arch = {"x86_64": "amd64", "aarch64": "arm64", "armv7l": "armv7"}.get(machine.strip())
        if not arch:
            raise ProvisionError(f"Неподдерживаемая архитектура: {machine.strip()}")
        return arch

    def check_ports(self, hy2_port: int, ss_port: int) -> None:
        _rc, out, _ = self.run("ss -Hlnup; echo ---; ss -Hlntp", check=False)
        udp, _, tcp = out.partition("---")
        for proto, text, port in (("UDP", udp, hy2_port), ("TCP", tcp, ss_port)):
            for line in text.splitlines():
                cols = line.split()
                if len(cols) > 3 and cols[3].rsplit(":", 1)[-1] == str(port) and "sing-box" not in line:
                    raise ProvisionError(f"{proto} {port} уже занят на VM: {line.strip()[:120]}")

    def install_packages(self) -> None:
        missing = [tool for tool in ("curl", "openssl", "tar")
                   if self.run(f"command -v {tool}", check=False)[0] != 0]
        if not missing:
            return
        self.log(f"apt: {', '.join(missing)}…", "CMD")
        rc, out, err = self.run("export DEBIAN_FRONTEND=noninteractive; (apt-get update -qq || true) && "
                                "apt-get install -y -qq curl ca-certificates openssl tar >/dev/null",
                                check=False, timeout=900)
        if rc == 0:
            return
        still = [tool for tool in ("openssl", "tar") if self.run(f"command -v {tool}", check=False)[0] != 0]
        if still:
            raise ProvisionError(f"apt не смог установить {', '.join(still)}:\n{(err or out)[-400:]}")
        # curl is only a convenience: sing-box is uploaded from this computer instead.
        self.log("apt недоступен · curl не установлен, sing-box загружу сам", "WARN")

    def install_singbox(self, arch: str) -> None:
        _rc, ver, _ = self.run("/usr/local/bin/sing-box version 2>/dev/null | head -1", check=False)
        if SERVER_SINGBOX_VERSION in ver:
            self.log(f"sing-box {SERVER_SINGBOX_VERSION} уже установлен", "OK")
            return
        url = SINGBOX_URL.format(v=SERVER_SINGBOX_VERSION, arch=arch)
        self.log(f"Загрузка sing-box {SERVER_SINGBOX_VERSION} ({arch}) на VM…", "CMD")
        rc, _, err = self.run(f"curl -fsSL --retry 3 -m 180 -o /tmp/obhod-sb.tgz {shlex.quote(url)}",
                              check=False, timeout=240)
        if rc != 0:
            self.log(f"VM не скачала релиз ({err.strip()[:80]}) · загружаю через этот компьютер", "WARN")
            with urllib.request.urlopen(url, timeout=180) as resp:
                blob = resp.read()
            tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz").getmembers()  # integrity check
            self.put("/tmp/obhod-sb.tgz", blob, mode="644")
        self.run("set -e; d=$(mktemp -d); tar -xzf /tmp/obhod-sb.tgz -C $d; "
                 "install -m 755 $d/sing-box-*/sing-box /usr/local/bin/sing-box; rm -rf $d /tmp/obhod-sb.tgz")
        _rc, ver, _ = self.run("/usr/local/bin/sing-box version | head -1")
        self.log(ver.strip(), "OK")

    def make_cert(self) -> str:
        san = f"DNS:{CERT_SNI}" + (f",IP:{self.host}" if _is_ip(self.host) else f",DNS:{self.host}")
        self.run(f"mkdir -p {REMOTE_DIR} && chmod 700 {REMOTE_DIR} && "
                 f"openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -days 3650 -nodes "
                 f"-keyout {REMOTE_DIR}/key.pem -out {REMOTE_DIR}/cert.pem -subj /CN={CERT_SNI} "
                 f"-addext {shlex.quote('subjectAltName=' + san)} 2>/dev/null && chmod 600 {REMOTE_DIR}/key.pem")
        _rc, cert, _ = self.run(f"cat {REMOTE_DIR}/cert.pem")
        self.log("Самоподписанный сертификат создан (10 лет)", "OK")
        return cert.strip() + "\n"

    def open_firewall(self, hy2_port: int, ss_port: int) -> None:
        if self.run("command -v ufw >/dev/null && ufw status | grep -q 'Status: active'", check=False)[0] == 0:
            self.run(f"ufw allow {hy2_port}/udp && ufw allow {ss_port}/tcp && ufw allow {ss_port}/udp")
            self.log("ufw: порты открыты", "OK")
        if self.run("command -v firewall-cmd >/dev/null && firewall-cmd --state", check=False)[0] == 0:
            self.run(f"firewall-cmd --permanent --add-port={hy2_port}/udp --add-port={ss_port}/tcp "
                     f"--add-port={ss_port}/udp && firewall-cmd --reload")
            self.log("firewalld: порты открыты", "OK")
        _rc, pol, _ = self.run("command -v iptables >/dev/null && iptables -S INPUT 2>/dev/null | head -1", check=False)
        if "-P INPUT DROP" in pol:
            self.run(f"iptables -I INPUT -p udp --dport {hy2_port} -j ACCEPT; "
                     f"iptables -I INPUT -p tcp --dport {ss_port} -j ACCEPT; "
                     f"iptables -I INPUT -p udp --dport {ss_port} -j ACCEPT; "
                     "command -v netfilter-persistent >/dev/null && netfilter-persistent save || true")
            self.log("iptables: порты открыты", "OK")

    def install_client_key(self) -> str:
        key_path = core.plat.ssh_key_dir() / f"obhod_{self.host.replace(':', '_')}"
        line = generate_ssh_key(key_path)
        home_ssh = "~/.ssh"  # runs as the SSH user itself, not through sudo
        self.run(f"mkdir -p {home_ssh} && chmod 700 {home_ssh} && touch {home_ssh}/authorized_keys && "
                 f"chmod 600 {home_ssh}/authorized_keys && "
                 f"(grep -qxF {shlex.quote(line)} {home_ssh}/authorized_keys || "
                 f"echo {shlex.quote(line)} >> {home_ssh}/authorized_keys)", sudo=False)
        self.log(f"Ключ доступа установлен · {key_path.name}", "OK")
        return str(key_path)

    # ── entry point ──

    def provision(self, name: str, hy2_port: int = 2080, ss_port: int = 8388,
                  reuse_existing: bool = True, install_key: bool = True) -> dict:
        self.connect()
        try:
            if reuse_existing:
                existing = self.read_existing()
                if existing:
                    self.log("На VM уже настроен OBHOD · забираю параметры без переустановки", "OK")
                    existing["name"] = name or self.host
                    return self._finish(existing, install_key)
            arch = self.detect()
            self.check_ports(hy2_port, ss_port)
            self.install_packages()
            self.install_singbox(arch)
            cert = self.make_cert()
            hy2_pass, obfs_pass, ss_pass = (secrets.token_urlsafe(32) for _ in range(3))
            config = {
                "log": {"level": "warn", "timestamp": True},
                "inbounds": [
                    {
                        "type": "hysteria2", "tag": "hy2-in", "listen": "0.0.0.0", "listen_port": hy2_port,
                        "users": [{"name": "obhod", "password": hy2_pass}],
                        "obfs": {"type": "salamander", "password": obfs_pass},
                        "tls": {"enabled": True, "server_name": CERT_SNI,
                                "certificate_path": f"{REMOTE_DIR}/cert.pem", "key_path": f"{REMOTE_DIR}/key.pem"},
                    },
                    {
                        "type": "shadowsocks", "tag": "ss-in", "listen": "0.0.0.0", "listen_port": ss_port,
                        "method": "aes-256-gcm", "password": ss_pass,
                    },
                ],
                "outbounds": [{"type": "direct", "tag": "direct"}],
            }
            self.put(f"{REMOTE_DIR}/config.json", json.dumps(config, indent=1).encode("utf-8"))
            self.run(f"/usr/local/bin/sing-box check -c {REMOTE_DIR}/config.json")
            self.put("/etc/systemd/system/sing-box.service", SYSTEMD_UNIT.encode("ascii"), mode="644")
            self.put("/etc/sysctl.d/90-obhod.conf", SYSCTL_CONF.encode("ascii"), mode="644")
            self.run("modprobe tcp_bbr 2>/dev/null; sysctl --system >/dev/null 2>&1 || true", check=False)
            self.log("systemd-юнит и BBR настроены", "OK")
            self.open_firewall(hy2_port, ss_port)
            self.run("systemctl daemon-reload && systemctl enable sing-box >/dev/null 2>&1 && systemctl restart sing-box")
            time.sleep(2)
            rc, state, _ = self.run("systemctl is-active sing-box", check=False)
            if state.strip() != "active":
                _rc, journal, _ = self.run("journalctl -u sing-box -n 20 --no-pager", check=False)
                raise ProvisionError(f"sing-box не запустился на VM:\n{journal[-600:]}")
            self.log("sing-box работает на VM", "OK")
            server = {
                "name": name or self.host, "host": self.host,
                "hy2": {"port": hy2_port, "password": hy2_pass, "obfs": obfs_pass, "sni": CERT_SNI, "cert": cert},
                "ss": {"port": ss_port, "method": "aes-256-gcm", "password": ss_pass},
            }
            return self._finish(server, install_key)
        finally:
            self.close()

    def _finish(self, server: dict, install_key: bool) -> dict:
        ssh = {"port": self.port, "user": self.user, "key": self.key_path}
        if install_key and not self.key_path:
            ssh["key"] = self.install_client_key()
        server["ssh"] = ssh
        server["added"] = time.strftime("%Y-%m-%d")
        return core.validate_server(server)


def verify_reachable(server: dict, log) -> None:
    ok, text = core.probe_server(server, timeout=8)
    log(("Проверка с этого компьютера · " + text), "OK" if ok else "WARN")

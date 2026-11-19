# -*- coding: utf-8 -*-
"""OBHOD-VPS GUI (customtkinter) shared by Windows and Linux."""
from __future__ import annotations

import json
import re
import sys
import threading
import time
from pathlib import Path
from tkinter import filedialog, messagebox
from types import SimpleNamespace

import obhod_core as core
import obhod_icons as app_icons

BG = "#0d1017"
PANEL = "#151b26"
PANEL2 = "#1c2433"
LINE = "#2a3548"
TEXT = "#eef2f8"
MUTED = "#7d8aa3"
ACCENT = "#3dd68c"
ACCENT_DIM = "#1a3d2e"
HOME_CLR = "#5b9cff"
HOME_DIM = "#1a2d4a"
PRIVACY_CLR = "#b48cff"
PRIVACY_DIM = "#302147"
OFF = "#4a5568"
DANGER = "#f07070"
WARN = "#f2c94c"


def run_gui() -> None:
    import customtkinter as ctk

    P = core.plat
    F, FM = P.FONT, P.FONT_MONO
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")

    def font(size: int, bold: bool = False, mono: bool = False):
        return ctk.CTkFont(family=FM if mono else F, size=size, weight="bold" if bold else "normal")

    current_mode = {"v": core.get_mode()}

    root = ctk.CTk()
    root.title(f"{core.APP_NAME}  ·  v{core.APP_VERSION}")
    height = max(760, min(960, root.winfo_screenheight() - 90))
    root.geometry(f"520x{height}+{max(0, root.winfo_screenwidth() // 2 - 260)}+20")
    root.minsize(480, 740)
    root.configure(fg_color=BG)
    P.set_window_icon(root)

    busy = {"v": False}
    suppress_toggle = {"v": False}
    wanted_on = {"v": False}
    reconnect = {"n": 0, "last": 0.0}
    mode_btns: dict = {}
    busy_widgets: list = []

    def error_box(text: str, parent=None) -> None:
        messagebox.showerror(core.APP_NAME, str(text)[:900], parent=parent or root)

    def info_box(text: str, parent=None) -> None:
        messagebox.showinfo(core.APP_NAME, str(text)[:900], parent=parent or root)

    def ui(fn, *args) -> None:
        """Run fn on the Tk thread."""
        try:
            root.after(0, lambda: fn(*args))
        except Exception:
            pass

    # ── header ──
    header = ctk.CTkFrame(root, fg_color=BG, corner_radius=0)
    header.pack(fill="x", padx=24, pady=(20, 0))
    top_row = ctk.CTkFrame(header, fg_color="transparent")
    top_row.pack(fill="x")
    ctk.CTkLabel(top_row, text="OBHOD", font=font(30, True), text_color=TEXT, anchor="w").pack(side="left")
    ctk.CTkLabel(top_row, text=f"v{core.APP_VERSION}", font=font(11, mono=True), text_color=ACCENT,
                 fg_color=ACCENT_DIM, corner_radius=6, padx=8, pady=2).pack(side="right", padx=(8, 0))
    ctk.CTkFrame(header, fg_color=ACCENT, height=2, corner_radius=1).pack(fill="x", pady=(10, 10))
    ctk.CTkLabel(header, text=f"Быстрый обход через VPS   ·   by {core.DEVELOPER}", font=font(13),
                 text_color=ACCENT, anchor="w").pack(anchor="w")

    # ── server selector ──
    srv_frame = ctk.CTkFrame(root, fg_color=PANEL2, corner_radius=14, border_width=1, border_color=LINE)
    srv_frame.pack(fill="x", padx=24, pady=(12, 0))
    ctk.CTkLabel(srv_frame, text="СЕРВЕР", font=font(10, True), text_color=MUTED, anchor="w").pack(
        anchor="w", padx=16, pady=(10, 4))
    srv_row = ctk.CTkFrame(srv_frame, fg_color="transparent")
    srv_row.pack(fill="x", padx=12, pady=(0, 12))
    server_menu = ctk.CTkOptionMenu(srv_row, values=["—"], height=34, corner_radius=10, font=font(13, True),
                                    fg_color=LINE, button_color="#343c4d", button_hover_color="#434d61",
                                    dropdown_font=font(12), text_color=TEXT)
    server_menu.pack(side="left", fill="x", expand=True, padx=(4, 6))
    servers_btn = ctk.CTkButton(srv_row, text="Серверы", width=86, height=34, corner_radius=10, fg_color=LINE,
                                hover_color="#343c4d", font=font(12))
    servers_btn.pack(side="left", padx=(0, 6))
    lists_btn = ctk.CTkButton(srv_row, text="Списки", width=76, height=34, corner_radius=10, fg_color=LINE,
                              hover_color="#343c4d", font=font(12))
    lists_btn.pack(side="left", padx=(0, 4))
    busy_widgets += [server_menu, servers_btn, lists_btn]
    menu_ids: dict[str, str] = {}

    def refresh_server_menu() -> None:
        data = core.load_servers()
        menu_ids.clear()
        labels = []
        for s in data["servers"]:
            label = f"{s['name']}  ·  {s['host']}"
            menu_ids[label] = s["id"]
            labels.append(label)
        server_menu.configure(values=labels or ["нет серверов — нажмите «Серверы»"])
        active = next((l for l, i in menu_ids.items() if i == data.get("active")), None)
        server_menu.set(active or (labels[0] if labels else "нет серверов — нажмите «Серверы»"))
        srv = core.active_server_or_none()
        ip_lbl.configure(text=core.server_label(srv), text_color=MUTED)

    def switch_server(server_id: str) -> None:
        """Make server_id active; reconnect if the tunnel is up."""
        data = core.load_servers()
        if data.get("active") == server_id:
            return

        def work() -> None:
            ui(set_busy, True)
            try:
                core.set_active_server(server_id)
                ui(refresh_server_menu)
                srv = core.active_server()
                core.emit_log(f"Активный сервер · {srv['name']} ({srv['host']})", "CMD")
                if core.is_obhod_on():
                    ui(set_connecting_ui, f"Переключение на {srv['name']}…")
                    result = core.restart_if_running()
                    ok, msg = result if result else (False, "")
                    ui(set_ui, ok, msg if ok else "Ошибка переключения")
                    if not ok:
                        wanted_on["v"] = False
                        ui(error_box, msg)
                else:
                    core.write_config()
            except Exception as exc:
                ui(error_box, exc)
            finally:
                ui(set_busy, False)

        threading.Thread(target=work, daemon=True).start()

    def on_server_pick(label: str) -> None:
        if busy["v"] or label not in menu_ids:
            refresh_server_menu()
            return
        switch_server(menu_ids[label])

    server_menu.configure(command=on_server_pick)

    # ── mode selector ──
    mode_frame = ctk.CTkFrame(root, fg_color=PANEL2, corner_radius=14, border_width=1, border_color=LINE)
    mode_frame.pack(fill="x", padx=24, pady=(12, 0))
    ctk.CTkLabel(mode_frame, text="РЕЖИМ", font=font(10, True), text_color=MUTED, anchor="w").pack(
        anchor="w", padx=16, pady=(10, 6))
    mode_row = ctk.CTkFrame(mode_frame, fg_color="transparent")
    mode_row.pack(fill="x", padx=12, pady=(0, 6))
    mode_hint = ctk.CTkLabel(mode_frame, text=core.MODE_HINTS[current_mode["v"]], font=font(11), text_color=MUTED,
                             anchor="w", wraplength=380, justify="left")
    mode_hint.pack(anchor="w", padx=16, pady=(0, 10))

    def style_mode_btn(key: str, active: bool) -> None:
        colors = {"work": (ACCENT, "#35c07e"), "home": (HOME_CLR, "#4a8ee6"), "privacy": (PRIVACY_CLR, "#9b74e8")}
        active_color, hover_color = colors[key]
        mode_btns[key].configure(fg_color=active_color if active else LINE,
                                 hover_color=hover_color if active else "#343c4d",
                                 text_color=BG if active else TEXT)

    def apply_mode_ui() -> None:
        m = current_mode["v"]
        for key in core.VALID_MODES:
            style_mode_btn(key, m == key)
        mode_hint.configure(text=core.MODE_HINTS[m])
        check_btn.configure(text="Проверить защиту" if m == "privacy" else "Проверить внешний IP")
        card.configure(border_color={"work": LINE, "home": HOME_DIM, "privacy": PRIVACY_DIM}[m])

    def on_mode_pick(mode: str) -> None:
        if busy["v"] or mode == current_mode["v"]:
            return
        was_on = core.is_obhod_on()
        previous_mode = current_mode["v"]
        core.emit_log(f"Смена режима · {previous_mode} → {mode}", "CMD")

        def work() -> None:
            ui(set_busy, True)
            try:
                if was_on:
                    ui(set_disconnecting_ui, "Остановка текущего режима…")
                    core.stop_obhod()
                    time.sleep(1)
                elif previous_mode == "privacy":
                    P.restore_privacy_policies()
                current_mode["v"] = mode
                core.set_mode(mode)
                core.write_config(mode)
                ui(apply_mode_ui)
                if was_on:
                    ui(set_connecting_ui, "Подключение нового режима…")
                    ok, msg = core.start_obhod()
                    ui(set_ui, ok, msg if ok else f"Режим «{core.MODE_NAMES[mode]}» · ошибка")
                else:
                    ui(lambda: detail_lbl.configure(text=f"Режим: {core.MODE_NAMES[mode]}", text_color=TEXT))
            except Exception as exc:
                ui(error_box, exc)
            finally:
                ui(set_busy, False)

        threading.Thread(target=work, daemon=True).start()

    for key, label, icon in [("work", "Работа", "🏢"), ("home", "Дом", "🏠"), ("privacy", "Приватность", "🛡")]:
        mode_btns[key] = ctk.CTkButton(mode_row, text=f"{icon}  {label}", height=38, corner_radius=10,
                                       font=font(13, True), command=lambda k=key: on_mode_pick(k))
        mode_btns[key].pack(side="left", expand=True, fill="x", padx=4)
        busy_widgets.append(mode_btns[key])

    # ── main card ──
    card = ctk.CTkFrame(root, fg_color=PANEL, corner_radius=18, border_width=1, border_color=LINE)
    card.pack(fill="both", expand=True, padx=24, pady=12)
    status_dot = ctk.CTkLabel(card, text="●", font=ctk.CTkFont(size=16), text_color=OFF)
    status_dot.pack(pady=(22, 0))
    status_lbl = ctk.CTkLabel(card, text="ВЫКЛЮЧЕН", font=font(22, True), text_color=MUTED)
    status_lbl.pack(pady=(4, 0))
    detail_lbl = ctk.CTkLabel(card, text="Трафик идёт как обычно", font=font(12), text_color=MUTED, wraplength=360)
    detail_lbl.pack(pady=(4, 14))
    switch = ctk.CTkSwitch(card, text="", width=76, height=38, switch_width=76, switch_height=38, corner_radius=19,
                           border_width=0, fg_color=OFF, progress_color=ACCENT, button_color="#f2f5f8",
                           button_hover_color="#ffffff")
    switch.pack(pady=(4, 4))
    busy_widgets.append(switch)
    switch_caption = ctk.CTkLabel(card, text="включить обход", font=font(11), text_color=MUTED)
    switch_caption.pack(pady=(0, 12))
    ip_lbl = ctk.CTkLabel(card, text="", font=font(11, mono=True), text_color=MUTED, wraplength=380)
    ip_lbl.pack(pady=(0, 16))

    def mode_colors():
        m = current_mode["v"]
        return ({"work": ACCENT, "home": HOME_CLR, "privacy": PRIVACY_CLR}[m],
                {"work": ACCENT_DIM, "home": HOME_DIM, "privacy": PRIVACY_DIM}[m])

    def set_ui(on: bool, detail: str = "") -> None:
        suppress_toggle["v"] = True
        m = current_mode["v"]
        on_color, on_dim = mode_colors()
        try:
            if on:
                switch.select()
                switch.configure(progress_color=on_color)
                switch_caption.configure(text="обход включён", text_color=on_color)
                status_dot.configure(text_color=on_color)
                status_lbl.configure(text="ВКЛЮЧЕН", text_color=on_color)
                srv = core.active_server_or_none()
                detail_lbl.configure(text=detail or f"{srv['name'] if srv else ''} · {core.MODE_NAMES[m]}",
                                     text_color=TEXT)
                card.configure(border_color=on_dim)
            else:
                switch.deselect()
                switch.configure(progress_color=ACCENT)
                switch_caption.configure(text="включить обход", text_color=MUTED)
                status_dot.configure(text_color=OFF)
                status_lbl.configure(text="ВЫКЛЮЧЕН", text_color=MUTED)
                detail_lbl.configure(text=detail or "Трафик идёт как обычно", text_color=MUTED)
                card.configure(border_color={"work": LINE, "home": HOME_DIM, "privacy": PRIVACY_DIM}[m])
        finally:
            suppress_toggle["v"] = False

    def set_connecting_ui(detail: str = "Установка защищённого туннеля…") -> None:
        suppress_toggle["v"] = True
        try:
            switch.select()
            switch.configure(progress_color=WARN)
            switch_caption.configure(text="установка соединения", text_color=WARN)
            status_dot.configure(text_color=WARN)
            status_lbl.configure(text="ПОДКЛЮЧЕНИЕ…", text_color=WARN)
            detail_lbl.configure(text=detail, text_color=TEXT)
            card.configure(border_color="#5a4b1b")
        finally:
            suppress_toggle["v"] = False

    def set_disconnecting_ui(detail: str = "Безопасная остановка туннеля…") -> None:
        suppress_toggle["v"] = True
        try:
            switch.deselect()
            switch.configure(progress_color="#f08a5d")
            switch_caption.configure(text="завершение соединения", text_color="#f08a5d")
            status_dot.configure(text_color="#f08a5d")
            status_lbl.configure(text="ОТКЛЮЧЕНИЕ…", text_color="#f08a5d")
            detail_lbl.configure(text=detail, text_color=TEXT)
            card.configure(border_color="#5b3024")
        finally:
            suppress_toggle["v"] = False

    def set_busy(v: bool) -> None:
        busy["v"] = v
        state = "disabled" if v else "normal"
        for widget in busy_widgets:
            try:
                widget.configure(state=state)
            except Exception:
                pass

    def on_toggle() -> None:
        if suppress_toggle["v"] or busy["v"]:
            return
        want_on = bool(switch.get())
        wanted_on["v"] = want_on
        reconnect["n"] = 0

        def work() -> None:
            ui(set_busy, True)
            try:
                if want_on:
                    ui(set_connecting_ui)
                    ok, msg = core.start_obhod()
                    ui(set_ui, ok, msg if ok else "Ошибка запуска")
                    if not ok:
                        wanted_on["v"] = False
                        ui(error_box, msg)
                else:
                    ui(set_disconnecting_ui)
                    core.stop_obhod()
                    ui(set_ui, False, "Выключено")
            except Exception as exc:
                wanted_on["v"] = False
                ui(set_ui, False, "Ошибка")
                ui(error_box, exc)
            finally:
                ui(set_busy, False)

        threading.Thread(target=work, daemon=True).start()

    switch.configure(command=on_toggle)

    # ── live terminal ──
    terminal_frame = ctk.CTkFrame(root, fg_color="#070b10", corner_radius=14, border_width=1, border_color="#1e3a2d")
    terminal_frame.pack(fill="x", padx=24, pady=(0, 12))
    terminal_bar = ctk.CTkFrame(terminal_frame, fg_color="transparent", height=30)
    terminal_bar.pack(fill="x", padx=12, pady=(8, 4))
    ctk.CTkLabel(terminal_bar, text="●  ●  ●", font=font(11, True, True), text_color="#5fe292").pack(side="left")
    ctk.CTkLabel(terminal_bar, text=">_  OBHOD LIVE LOG", font=font(11, True, True), text_color="#98a6b8").pack(
        side="left", padx=(12, 0))
    terminal_box = ctk.CTkTextbox(terminal_frame, height=130, corner_radius=8, border_width=0, fg_color="#030706",
                                  text_color="#70e89b", scrollbar_button_color="#1b3c2d",
                                  scrollbar_button_hover_color="#28563f", font=font(11, mono=True), wrap="word",
                                  activate_scrollbars=True)
    terminal_box.pack(fill="x", padx=10, pady=(0, 10))
    for tag, color in (("INFO", "#70e89b"), ("CMD", "#79b8ff"), ("OK", "#49f2a0"), ("WARN", WARN),
                       ("ERROR", "#ff7272"), ("CORE", "#a8b7c8")):
        terminal_box.tag_config(tag, foreground=color)
    terminal_box.configure(state="disabled")
    log_listeners: list = []

    def append_console(line: str, level: str = "INFO") -> None:
        clean = re.sub(r"\x1b\[[0-9;]*m", "", str(line)).replace("\r", "").rstrip()
        if not clean:
            return
        terminal_box.configure(state="normal")
        terminal_box.insert("end", clean + "\n", level if level in {"INFO", "CMD", "OK", "WARN", "ERROR", "CORE"} else "INFO")
        try:
            total_lines = int(terminal_box.index("end-1c").split(".", 1)[0])
            if total_lines > 700:
                terminal_box.delete("1.0", f"{total_lines - 600}.0")
        except Exception:
            pass
        terminal_box.see("end")
        terminal_box.configure(state="disabled")
        for listener in list(log_listeners):
            try:
                listener(clean, level)
            except Exception:
                log_listeners.remove(listener)

    def queue_console(level: str, message: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        marker = {"CMD": "$", "OK": "+", "WARN": "!", "ERROR": "x", "INFO": ">"}.get(level, ">")
        ui(append_console, f"[{stamp}] {marker} {message}", level)

    def clear_console() -> None:
        terminal_box.configure(state="normal")
        terminal_box.delete("1.0", "end")
        terminal_box.configure(state="disabled")
        append_console(f"[{time.strftime('%H:%M:%S')}] $ console --clear", "CMD")

    ctk.CTkButton(terminal_bar, text="очистить", width=62, height=22, corner_radius=6, fg_color="#11231b",
                  hover_color="#1b3c2d", text_color="#7f9d8d", font=font(10, mono=True),
                  command=clear_console).pack(side="right")
    core.set_log_sink(queue_console)
    append_console(f"[{time.strftime('%H:%M:%S')}] $ obhod --live-log", "CMD")
    append_console(f"[{time.strftime('%H:%M:%S')}] + монитор готов · v{core.APP_VERSION}", "OK")

    core_log = P.log_path()
    tail_state = {"offset": core_log.stat().st_size if core_log.is_file() else 0, "buffer": b""}

    def poll_core_log() -> None:
        try:
            path = P.log_path()
            if path.is_file():
                size = path.stat().st_size
                if size < tail_state["offset"]:
                    tail_state["offset"] = 0
                    tail_state["buffer"] = b""
                if size > tail_state["offset"]:
                    with open(path, "rb") as stream:
                        stream.seek(tail_state["offset"])
                        chunk = stream.read(65536)
                        tail_state["offset"] = stream.tell()
                    data = tail_state["buffer"] + chunk
                    tail_state["buffer"] = b""
                    for raw in data.splitlines(keepends=True):
                        if raw.endswith((b"\n", b"\r")):
                            append_console("sing-box > " + raw.decode("utf-8", "replace").strip(), "CORE")
                        else:
                            tail_state["buffer"] = raw
                    if len(tail_state["buffer"]) > 8192:
                        append_console("sing-box > " + tail_state["buffer"].decode("utf-8", "replace"), "CORE")
                        tail_state["buffer"] = b""
        except Exception as exc:
            append_console(f"[{time.strftime('%H:%M:%S')}] ! чтение логов: {exc}", "WARN")
        finally:
            root.after(350, poll_core_log)

    root.after(350, poll_core_log)

    # ── footer ──
    footer = ctk.CTkFrame(root, fg_color=BG, corner_radius=0)
    footer.pack(fill="x", padx=24, pady=(0, 16))

    def do_check() -> None:
        if busy["v"]:
            return
        core.emit_log("Проверка внешнего IP и защиты…", "CMD")

        def work() -> None:
            ui(set_busy, True)
            ui(lambda: ip_lbl.configure(text="Проверка VPS…", text_color=MUTED))
            try:
                privacy = current_mode["v"] == "privacy" and core.is_obhod_on()
                ok, val = core.privacy_status() if privacy else core.tunnel_ip()
                srv = core.active_server_or_none()
                if ok:
                    core.emit_log(f"Проверка завершена · {val}", "OK")
                    match = srv is not None and val == core.server_ip(srv)
                    color = PRIVACY_CLR if privacy else (ACCENT if match else DANGER)
                    text = f"Защита  {val}" if privacy else f"Внешний IP  {val}" + ("" if match else "  (не VPS)")
                    ui(lambda: ip_lbl.configure(text=text, text_color=color))
                else:
                    core.emit_log(f"Проверка не пройдена · {val}", "ERROR")
                    ui(lambda: ip_lbl.configure(text=f"Ошибка: {val[:40]}", text_color=DANGER))
            except Exception as exc:
                ui(lambda: ip_lbl.configure(text=f"Ошибка: {str(exc)[:40]}", text_color=DANGER))
            finally:
                ui(set_busy, False)

        threading.Thread(target=work, daemon=True).start()

    check_btn = ctk.CTkButton(footer, text="Проверить внешний IP", height=40, corner_radius=12, fg_color=LINE,
                              hover_color="#343c4d", text_color=TEXT, font=font(13), command=do_check)
    check_btn.pack(fill="x")
    busy_widgets.append(check_btn)
    dev_row = ctk.CTkFrame(footer, fg_color="transparent")
    dev_row.pack(fill="x", pady=(12, 0))
    ctk.CTkLabel(dev_row, text="Разработчик", font=font(10), text_color=MUTED).pack(side="left")
    ctk.CTkLabel(dev_row, text=f"by {core.DEVELOPER}", font=font(11, True), text_color=ACCENT).pack(side="right")

    # ════════════════════ dialogs ════════════════════

    def make_toplevel(title: str, geometry: str):
        win = ctk.CTkToplevel(root)
        win.title(f"{core.APP_NAME} · {title}")
        win.geometry(geometry)
        win.configure(fg_color=BG)
        win.transient(root)
        win.after(200, lambda: P.set_window_icon(win))
        win.after(50, win.lift)
        win.after(60, win.focus_force)
        return win

    def small_btn(parent, text, command, color=LINE, hover="#343c4d", text_color=TEXT, width=0):
        kwargs = {"width": width} if width else {}
        return ctk.CTkButton(parent, text=text, command=command, height=30, corner_radius=8, fg_color=color,
                             hover_color=hover, text_color=text_color, font=font(12), **kwargs)

    # ── QR / share ──

    def show_share(server: dict, parent) -> None:
        link = core.export_link(server)
        win = make_toplevel(f"Телефон · {server['name']}", "460x640")
        ctk.CTkLabel(win, text=f"Подключить телефон к «{server['name']}»", font=font(15, True),
                     text_color=TEXT).pack(pady=(16, 4), padx=16, anchor="w")
        ctk.CTkLabel(win, text="Откройте OBHOD на Android → «+» → «Сканировать QR», либо просто наведите "
                               "камеру телефона на код. Сервер добавится и станет выбранным.",
                     font=font(11), text_color=MUTED, wraplength=420, justify="left").pack(padx=16, anchor="w")
        try:
            import qrcode
            from PIL import Image

            qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=8, border=3)
            qr.add_data(link)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
            img = img.resize((340, 340), Image.NEAREST)
            photo = ctk.CTkImage(light_image=img, dark_image=img, size=(340, 340))
            ctk.CTkLabel(win, text="", image=photo).pack(pady=12)
        except Exception as exc:
            ctk.CTkLabel(win, text=f"QR недоступен: {exc}", text_color=DANGER, font=font(11)).pack(pady=12)
        box = ctk.CTkTextbox(win, height=70, font=font(10, mono=True), fg_color=PANEL, wrap="char")
        box.pack(fill="x", padx=16)
        box.insert("1.0", link)
        box.configure(state="disabled")
        row = ctk.CTkFrame(win, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=10)

        def copy() -> None:
            win.clipboard_clear()
            win.clipboard_append(link)
            copy_btn.configure(text="Скопировано ✓")

        def save_android() -> None:
            path = filedialog.asksaveasfilename(parent=win, title="Профиль для Android",
                                                initialfile=f"OBHOD-{server['name']}.json",
                                                defaultextension=".json", filetypes=[("sing-box JSON", "*.json")])
            if not path:
                return
            try:
                Path(path).write_text(json.dumps(core.export_android_profile(server), ensure_ascii=False, indent=2),
                                      encoding="utf-8")
                info_box("Профиль сохранён. Он содержит ваши текущие белые списки.\n"
                         "На телефоне: OBHOD → «+» → «Импорт из файла».", parent=win)
            except Exception as exc:
                error_box(exc, parent=win)

        copy_btn = small_btn(row, "Копировать ссылку", copy)
        copy_btn.pack(side="left", expand=True, fill="x", padx=(0, 4))
        small_btn(row, "Файл для Android…", save_android).pack(side="left", expand=True, fill="x", padx=(4, 0))
        ctk.CTkLabel(win, text="Ссылка — это ключи доступа к серверу. Не публикуйте её.", font=font(10),
                     text_color=WARN).pack(padx=16, anchor="w")

    # ── add VM ──

    def open_add_vm(parent, on_done) -> None:
        win = make_toplevel("Новая VM", "540x700")
        ctk.CTkLabel(win, text="Добавить новую VM", font=font(16, True), text_color=TEXT).pack(
            padx=18, pady=(16, 2), anchor="w")
        ctk.CTkLabel(win, text="Свежая VM на Debian/Ubuntu. Приложение само зайдёт по SSH, установит sing-box, "
                               "сгенерирует ключи и добавит сервер в список. Если OBHOD на VM уже стоит — "
                               "просто заберёт его параметры.", font=font(11), text_color=MUTED, wraplength=500,
                     justify="left").pack(padx=18, anchor="w")
        form = ctk.CTkFrame(win, fg_color=PANEL, corner_radius=12)
        form.pack(fill="x", padx=18, pady=12)
        form.grid_columnconfigure(1, weight=1)
        entries: dict = {}

        def field(row: int, label: str, key: str, default: str = "", show: str = "", width: int = 0):
            ctk.CTkLabel(form, text=label, font=font(12), text_color=MUTED).grid(row=row, column=0, sticky="w",
                                                                                  padx=(12, 8), pady=5)
            entry = ctk.CTkEntry(form, font=font(12), show=show, fg_color=PANEL2, border_color=LINE)
            entry.insert(0, default)
            entry.grid(row=row, column=1, sticky="ew", padx=(0, 12), pady=5)
            entries[key] = entry
            return entry

        field(0, "Название", "name", "")
        field(1, "IP / хост VM", "host", "")
        field(2, "SSH-порт", "port", "22")
        field(3, "Пользователь", "user", "root")
        field(4, "Пароль", "password", "", show="•")
        key_entry = field(5, "…или ключ SSH", "key", "")

        def browse_key() -> None:
            path = filedialog.askopenfilename(parent=win, title="Приватный ключ SSH",
                                              initialdir=str(Path.home() / ".ssh"))
            if path:
                key_entry.delete(0, "end")
                key_entry.insert(0, path)

        small_btn(form, "…", browse_key, width=34).grid(row=5, column=2, padx=(0, 12))
        field(6, "Порт Hysteria2 (UDP)", "hy2", "2080")
        field(7, "Порт Shadowsocks (TCP)", "ss", "8388")
        opts = ctk.CTkFrame(win, fg_color="transparent")
        opts.pack(fill="x", padx=18)
        reuse_var = ctk.BooleanVar(value=True)
        key_var = ctk.BooleanVar(value=True)
        activate_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(opts, text="Если OBHOD уже стоит — подключить без переустановки", variable=reuse_var,
                        font=font(12)).pack(anchor="w", pady=2)
        ctk.CTkCheckBox(opts, text="Установить ключ доступа (дальше — вход без пароля)", variable=key_var,
                        font=font(12)).pack(anchor="w", pady=2)
        ctk.CTkCheckBox(opts, text="Сразу сделать сервер активным", variable=activate_var,
                        font=font(12)).pack(anchor="w", pady=2)
        log_box = ctk.CTkTextbox(win, height=110, font=font(10, mono=True), fg_color="#030706",
                                 text_color="#70e89b", wrap="word")
        log_box.configure(state="disabled")
        go_btn = ctk.CTkButton(win, text="Установить и добавить", height=40, corner_radius=12, fg_color=ACCENT,
                               hover_color="#35c07e", text_color=BG, font=font(13, True))
        # Packed before the log so a short screen clips the log, never the button.
        go_btn.pack(side="bottom", fill="x", padx=18, pady=(0, 16))
        log_box.pack(fill="both", expand=True, padx=18, pady=(10, 6))
        running = {"v": False}

        def dlog(msg: str, level: str = "INFO") -> None:
            core.emit_log(f"[VM] {msg}", level)

            def put() -> None:
                if not log_box.winfo_exists():
                    return
                log_box.configure(state="normal")
                log_box.insert("end", f"{time.strftime('%H:%M:%S')}  {msg}\n")
                log_box.see("end")
                log_box.configure(state="disabled")

            ui(put)

        def start() -> None:
            if running["v"]:
                return
            host = entries["host"].get().strip()
            try:
                port = int(entries["port"].get() or 22)
                hy2_port = int(entries["hy2"].get() or 2080)
                ss_port = int(entries["ss"].get() or 8388)
            except ValueError:
                error_box("Порты должны быть числами", parent=win)
                return
            if not host:
                error_box("Укажите IP или хост VM", parent=win)
                return
            if not entries["password"].get() and not entries["key"].get().strip():
                error_box("Нужен пароль root или путь к SSH-ключу", parent=win)
                return
            if hy2_port == ss_port:
                pass  # different protocols (UDP vs TCP) may share a number
            name = entries["name"].get().strip() or host
            import obhod_provision as prov

            running["v"] = True
            go_btn.configure(state="disabled", text="Установка…")
            prov_obj = prov.Provisioner(host, port, entries["user"].get(), entries["password"].get(),
                                        entries["key"].get(), log=dlog)

            def work() -> None:
                try:
                    server = prov_obj.provision(name, hy2_port, ss_port, reuse_existing=reuse_var.get(),
                                                install_key=key_var.get())
                    prov.verify_reachable(server, dlog)
                    added = core.add_server(server, make_active=False)
                    dlog(f"Сервер «{added['name']}» добавлен", "OK")

                    def done() -> None:
                        running["v"] = False
                        if win.winfo_exists():
                            go_btn.configure(text="Готово ✓", fg_color=LINE)
                        refresh_server_menu()
                        on_done()
                        if activate_var.get():
                            switch_server(added["id"])
                        info_box(f"Сервер «{added['name']}» готов.\n\nЧтобы добавить его на телефон, откройте "
                                 "«Серверы» → «Телефон».", parent=win if win.winfo_exists() else root)

                    ui(done)
                except Exception as exc:
                    dlog(f"Ошибка: {exc}", "ERROR")

                    def failed(err=str(exc)) -> None:
                        running["v"] = False
                        if win.winfo_exists():
                            go_btn.configure(state="normal", text="Повторить")
                            error_box(err, parent=win)

                    ui(failed)

            threading.Thread(target=work, daemon=True).start()

        go_btn.configure(command=start)

    # ── import ──

    def open_import(parent, on_done) -> None:
        win = make_toplevel("Импорт сервера", "520x360")
        ctk.CTkLabel(win, text="Импорт сервера", font=font(16, True), text_color=TEXT).pack(
            padx=18, pady=(16, 2), anchor="w")
        ctk.CTkLabel(win, text="Вставьте ссылку obhod://… (например, с другого компьютера) или выберите файл: "
                               "ссылку, профиль sing-box или старый server.json.", font=font(11), text_color=MUTED,
                     wraplength=480, justify="left").pack(padx=18, anchor="w")
        box = ctk.CTkTextbox(win, height=130, font=font(10, mono=True), fg_color=PANEL, wrap="char")
        box.pack(fill="x", padx=18, pady=10)
        row = ctk.CTkFrame(win, fg_color="transparent")
        row.pack(fill="x", padx=18)

        def finish(server: dict) -> None:
            added = core.add_server(server)
            refresh_server_menu()
            on_done()
            core.emit_log(f"Импортирован сервер «{added['name']}» ({added['host']})", "OK")
            win.destroy()

        def from_text() -> None:
            try:
                finish(core.import_link(box.get("1.0", "end")))
            except Exception as exc:
                error_box(exc, parent=win)

        def from_file() -> None:
            path = filedialog.askopenfilename(parent=win, title="Файл сервера",
                                              filetypes=[("JSON / текст", "*.json *.txt"), ("Все файлы", "*.*")])
            if not path:
                return
            try:
                finish(core.import_file(Path(path)))
            except Exception as exc:
                error_box(exc, parent=win)

        small_btn(row, "Добавить по ссылке", from_text, color=ACCENT, hover="#35c07e", text_color=BG).pack(
            side="left", expand=True, fill="x", padx=(0, 4))
        small_btn(row, "Выбрать файл…", from_file).pack(side="left", expand=True, fill="x", padx=(4, 0))

    # ── servers window ──

    servers_win = {"w": None}

    def open_servers() -> None:
        if servers_win["w"] is not None and servers_win["w"].winfo_exists():
            servers_win["w"].lift()
            return
        win = make_toplevel("Серверы", "640x600")
        servers_win["w"] = win
        top = ctk.CTkFrame(win, fg_color="transparent")
        top.pack(fill="x", padx=16, pady=(16, 8))
        ctk.CTkLabel(top, text="Серверы", font=font(18, True), text_color=TEXT).pack(side="left")
        lst = ctk.CTkScrollableFrame(win, fg_color=BG)

        def render() -> None:
            for child in lst.winfo_children():
                child.destroy()
            data = core.load_servers()
            if not data["servers"]:
                ctk.CTkLabel(lst, text="Серверов нет. Добавьте новую VM или импортируйте ссылку.",
                             font=font(12), text_color=MUTED).pack(pady=30)
            for server in data["servers"]:
                active = server["id"] == data.get("active")
                box = ctk.CTkFrame(lst, fg_color=PANEL, corner_radius=12, border_width=1,
                                   border_color=ACCENT if active else LINE)
                box.pack(fill="x", pady=5, padx=2)
                head = ctk.CTkFrame(box, fg_color="transparent")
                head.pack(fill="x", padx=12, pady=(10, 0))
                ctk.CTkLabel(head, text=server["name"], font=font(14, True), text_color=TEXT).pack(side="left")
                if active:
                    ctk.CTkLabel(head, text="активный", font=font(10, True), text_color=BG, fg_color=ACCENT,
                                 corner_radius=6, padx=6).pack(side="left", padx=8)
                transports = []
                if server.get("hy2"):
                    transports.append(f"Hy2 UDP/{server['hy2']['port']}")
                if server.get("ss"):
                    transports.append(f"SS TCP/{server['ss']['port']}")
                status = ctk.CTkLabel(box, text=f"{server['host']}   ·   {'  +  '.join(transports)}   ·   "
                                                f"добавлен {server.get('added', '—')}",
                                      font=font(11, mono=True), text_color=MUTED, anchor="w")
                status.pack(fill="x", padx=12, pady=(2, 6))
                btns = ctk.CTkFrame(box, fg_color="transparent")
                btns.pack(fill="x", padx=10, pady=(0, 10))

                def use(s=server) -> None:
                    if busy["v"]:
                        return
                    switch_server(s["id"])
                    win.after(400, render)

                def probe(s=server, label=status) -> None:
                    label.configure(text="проверка…", text_color=MUTED)

                    def work() -> None:
                        ok, text = core.probe_server(s)
                        ui(lambda: label.winfo_exists() and label.configure(
                            text=f"{s['host']}   ·   {text}", text_color=ACCENT if ok else DANGER))

                    threading.Thread(target=work, daemon=True).start()

                def rename(s=server) -> None:
                    dialog = ctk.CTkInputDialog(text="Новое название:", title="Переименовать")
                    value = (dialog.get_input() or "").strip()
                    if value:
                        core.update_server(s["id"], name=value[:40])
                        refresh_server_menu()
                        render()

                def delete(s=server) -> None:
                    if active and core.is_obhod_on():
                        error_box("Это активный сервер, и туннель включён. Сначала выключите обход или "
                                  "переключитесь на другой сервер.", parent=win)
                        return
                    if messagebox.askyesno(core.APP_NAME, f"Удалить «{s['name']}» из списка?\n\n"
                                                          "Сама VM не изменится.", parent=win):
                        core.remove_server(s["id"])
                        refresh_server_menu()
                        render()

                if not active:
                    small_btn(btns, "Выбрать", use, color=ACCENT, hover="#35c07e", text_color=BG, width=80).pack(
                        side="left", padx=2)
                small_btn(btns, "Телефон / QR", lambda s=server: show_share(s, win), width=110).pack(
                    side="left", padx=2)
                small_btn(btns, "Проверить", probe, width=86).pack(side="left", padx=2)
                small_btn(btns, "Имя", rename, width=54).pack(side="left", padx=2)
                small_btn(btns, "Удалить", delete, color="#3a2226", hover="#55303a", text_color=DANGER,
                          width=76).pack(side="right", padx=2)

        small_btn(top, "Импорт…", lambda: open_import(win, render), width=90).pack(side="right", padx=(6, 0))
        small_btn(top, "＋ Новая VM", lambda: open_add_vm(win, render), color=ACCENT, hover="#35c07e",
                  text_color=BG, width=120).pack(side="right")
        lst.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        render()

    servers_btn.configure(command=open_servers)

    # ── lists / settings window ──

    lists_win = {"w": None}

    def app_picker(parent, key: str, names: list[str], paths: dict[str, str]):
        """Icon list of applications: pick an exe, or type a process name."""
        state: list[list[str]] = [[name, paths.get(name, "")] for name in names]
        icon_cache: dict[str, object] = {}

        holder = ctk.CTkFrame(parent, fg_color="transparent")
        holder.pack(fill="both", expand=True, pady=(4, 0))

        top = ctk.CTkFrame(holder, fg_color="transparent")
        top.pack(fill="x", pady=(0, 6))

        scroll = ctk.CTkScrollableFrame(holder, fg_color=PANEL2, corner_radius=8)
        scroll.pack(fill="both", expand=True)

        def icon_for(path: str):
            if not path:
                return None
            if path not in icon_cache:
                image = app_icons.load_icon(path, 20)
                icon_cache[path] = ctk.CTkImage(light_image=image, dark_image=image, size=(20, 20)) if image else None
            return icon_cache[path]

        def redraw() -> None:
            for widget in scroll.winfo_children():
                widget.destroy()
            if not state:
                ctk.CTkLabel(scroll, text="Пока пусто. Нажмите «Выбрать .exe…» или впишите имя процесса.",
                             font=font(11), text_color=MUTED).pack(pady=18)
                return
            for index, (name, path) in enumerate(list(state)):
                row = ctk.CTkFrame(scroll, fg_color="transparent")
                row.pack(fill="x", pady=2, padx=2)
                icon = icon_for(path)
                if icon is not None:
                    ctk.CTkLabel(row, text="", image=icon, width=26).pack(side="left", padx=(4, 6))
                else:
                    ctk.CTkLabel(row, text=(name[:1] or "?").upper(), width=26, height=26, fg_color=PANEL,
                                 corner_radius=6, font=font(11, True), text_color=ACCENT).pack(side="left", padx=(4, 6))
                column = ctk.CTkFrame(row, fg_color="transparent")
                column.pack(side="left", fill="x", expand=True)
                ctk.CTkLabel(column, text=name, anchor="w", font=font(12, True), text_color=TEXT).pack(anchor="w")
                if path:
                    ctk.CTkLabel(column, text=path, anchor="w", font=font(10), text_color=MUTED).pack(anchor="w")
                ctk.CTkButton(row, text="✕", width=28, height=26, fg_color="transparent", hover_color=DANGER,
                              text_color=MUTED, font=font(12), command=lambda i=index: remove(i)).pack(side="right", padx=4)

        def add(value: str, path: str = "") -> None:
            raw = value.strip()
            if not raw:
                return
            if not path and ("\\" in raw or "/" in raw) and Path(raw).is_file():
                path = raw
            try:
                parsed = core.parse_list(key, Path(path).name if path else raw)
            except ValueError as exc:
                error_box(exc, parent=holder.winfo_toplevel())
                return
            for name in parsed:
                existing = next((item for item in state if item[0].lower() == name.lower()), None)
                if existing is not None:
                    if path:
                        existing[1] = path
                    continue
                state.append([name, path])
            redraw()

        def remove(index: int) -> None:
            state.pop(index)
            redraw()

        def choose() -> None:
            types = [("Программы", "*.exe"), ("Все файлы", "*.*")] if sys.platform == "win32" \
                else [("Все файлы", "*.*")]
            path = filedialog.askopenfilename(parent=holder.winfo_toplevel(), title="Выберите программу",
                                              filetypes=types)
            if path:
                add(Path(path).name, path)

        ctk.CTkButton(top, text="Выбрать .exe…", height=32, corner_radius=8, fg_color=ACCENT,
                      hover_color="#35c07e", text_color=BG, font=font(12, True), command=choose).pack(side="left")
        entry = ctk.CTkEntry(top, placeholder_text="или имя процесса: chrome.exe, telegram-desktop",
                             height=32, font=font(12), fg_color=PANEL2, border_color=LINE)
        entry.pack(side="left", fill="x", expand=True, padx=8)
        entry.bind("<Return>", lambda _event: (add(entry.get()), entry.delete(0, "end")))
        ctk.CTkButton(top, text="Добавить", height=32, width=96, corner_radius=8, fg_color=LINE,
                      hover_color="#343c4d", font=font(12), command=lambda: (add(entry.get()), entry.delete(0, "end"))
                      ).pack(side="left")

        def reset() -> None:
            state.clear()
            redraw()

        redraw()

        def names_now() -> list[str]:
            return [name for name, _path in state]

        def paths_now() -> dict[str, str]:
            return {name: path for name, path in state if path}

        return SimpleNamespace(names=names_now, paths=paths_now, reset=reset)


    def open_lists() -> None:
        if lists_win["w"] is not None and lists_win["w"].winfo_exists():
            lists_win["w"].lift()
            return
        win = make_toplevel("Белые списки и настройки", "760x680")
        lists_win["w"] = win
        ctk.CTkLabel(win, text="Белые списки и настройки", font=font(17, True), text_color=TEXT).pack(
            padx=16, pady=(14, 4), anchor="w")
        tabs = ctk.CTkTabview(win, fg_color=PANEL, segmented_button_selected_color=ACCENT,
                              segmented_button_selected_hover_color="#35c07e", text_color=TEXT)
        tabs.pack(fill="both", expand=True, padx=14, pady=(0, 6))
        lists = core.get_lists()
        options = core.get_options()
        boxes: dict = {}
        pickers: dict = {}
        stored_paths = core.get_app_paths()
        for key in ("always_direct_domains", "work_direct_domains", "proxy_domains", "proxy_apps", "direct_apps",
                    "always_direct_cidr", "route_exclude"):
            tab = tabs.add(core.LIST_TABS[key])
            ctk.CTkLabel(tab, text=core.LIST_HINTS[key], font=font(11), text_color=MUTED, wraplength=560,
                         justify="left").pack(anchor="w", pady=(2, 6))
            if key in core.APP_LISTS:
                pickers[key] = app_picker(tab, key, lists[key], stored_paths)
                continue
            box = ctk.CTkTextbox(tab, font=font(12, mono=True), fg_color=PANEL2, wrap="none")
            box.pack(fill="both", expand=True)
            box.insert("1.0", "\n".join(lists[key]))
            boxes[key] = box
        tab = tabs.add("Параметры")
        grid = ctk.CTkFrame(tab, fg_color="transparent")
        grid.pack(fill="x", pady=8)
        grid.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(grid, text="Транспорт", font=font(12), text_color=MUTED).grid(row=0, column=0, sticky="w",
                                                                                pady=6, padx=(0, 10))
        transport_labels = {v: k for k, v in core.TRANSPORTS.items()}
        transport_menu = ctk.CTkOptionMenu(grid, values=list(core.TRANSPORTS.values()), font=font(12),
                                           fg_color=LINE, button_color="#343c4d")
        transport_menu.set(core.TRANSPORTS[options["transport"]])
        transport_menu.grid(row=0, column=1, sticky="ew", pady=6)
        ctk.CTkLabel(grid, text="DNS (DoH через VPS)", font=font(12), text_color=MUTED).grid(
            row=1, column=0, sticky="w", pady=6, padx=(0, 10))
        doh_entry = ctk.CTkEntry(grid, font=font(12), fg_color=PANEL2, border_color=LINE)
        doh_entry.insert(0, str(options["doh_server"]))
        doh_entry.grid(row=1, column=1, sticky="ew", pady=6)
        ctk.CTkLabel(grid, text="MTU туннеля", font=font(12), text_color=MUTED).grid(
            row=2, column=0, sticky="w", pady=6, padx=(0, 10))
        mtu_entry = ctk.CTkEntry(grid, font=font(12), fg_color=PANEL2, border_color=LINE)
        mtu_entry.insert(0, str(options["mtu"]))
        mtu_entry.grid(row=2, column=1, sticky="ew", pady=6)
        ctk.CTkLabel(tab, text="«Авто» проверяет оба транспорта каждые 3 минуты и берёт быстрейший. Если провайдер "
                               "режет UDP, выберите «Только Shadowsocks».", font=font(11), text_color=MUTED,
                     wraplength=560, justify="left").pack(anchor="w", pady=(10, 0))

        row = ctk.CTkFrame(win, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(4, 14))

        def save() -> None:
            try:
                new_lists = {key: core.parse_list(key, box.get("1.0", "end")) for key, box in boxes.items()}
                new_lists.update({key: picker.names() for key, picker in pickers.items()})
                new_options = core.validate_options(transport_labels[transport_menu.get()], doh_entry.get(),
                                                    mtu_entry.get())
            except ValueError as exc:
                error_box(exc, parent=win)
                return
            app_paths: dict[str, str] = {}
            for picker in pickers.values():
                app_paths.update(picker.paths())
            old_lists, old_options = core.get_lists(), core.get_options()
            old_paths = core.get_app_paths()
            core.save_lists_and_options(new_lists, new_options, app_paths)
            try:
                path = core.write_config()
                ok, detail = core.check_config(path)
            except Exception as exc:
                ok, detail = False, str(exc)
            if not ok:
                core.save_lists_and_options(old_lists, old_options, old_paths)
                core.write_config()
                error_box(f"sing-box отклонил конфигурацию, изменения отменены:\n{detail}", parent=win)
                return
            core.emit_log("Списки и параметры сохранены", "OK")
            win.destroy()
            if core.is_obhod_on() and not busy["v"]:
                def work() -> None:
                    ui(set_busy, True)
                    ui(set_connecting_ui, "Применение новых списков…")
                    try:
                        ok2, msg = core.restart_if_running() or (True, "")
                        ui(set_ui, ok2, msg if ok2 else "Ошибка применения")
                        if not ok2:
                            wanted_on["v"] = False
                            ui(error_box, msg)
                    finally:
                        ui(set_busy, False)

                threading.Thread(target=work, daemon=True).start()

        def reset() -> None:
            if not messagebox.askyesno(core.APP_NAME, "Вернуть все списки и параметры к значениям по умолчанию?",
                                       parent=win):
                return
            for key, box in boxes.items():
                box.delete("1.0", "end")
                box.insert("1.0", "\n".join(core.DEFAULT_LISTS[key]))
            for picker in pickers.values():
                picker.reset()
            transport_menu.set(core.TRANSPORTS[core.DEFAULT_OPTIONS["transport"]])
            doh_entry.delete(0, "end")
            doh_entry.insert(0, core.DEFAULT_OPTIONS["doh_server"])
            mtu_entry.delete(0, "end")
            mtu_entry.insert(0, str(core.DEFAULT_OPTIONS["mtu"]))

        ctk.CTkButton(row, text="Сохранить и применить", height=38, corner_radius=10, fg_color=ACCENT,
                      hover_color="#35c07e", text_color=BG, font=font(13, True), command=save).pack(
            side="left", expand=True, fill="x", padx=(0, 4))
        small_btn(row, "По умолчанию", reset, width=130).pack(side="left", padx=4)
        small_btn(row, "Отмена", win.destroy, width=90).pack(side="left", padx=(4, 0))

    lists_btn.configure(command=open_lists)

    # ════════════════════ startup ════════════════════

    try:
        if P.legacy_config_present():
            core.emit_log("Обнаружена старая конфигурация · безопасная миграция", "WARN")
            core.stop_obhod()
        P.ensure_singbox()
        refresh_server_menu()
        if core.active_server_or_none():
            core.write_config(current_mode["v"])
        if current_mode["v"] == "privacy" and core.is_obhod_on():
            P.apply_privacy_policies()
        elif current_mode["v"] != "privacy" or not core.is_obhod_on():
            P.restore_privacy_policies()
    except Exception as exc:
        root.after(300, lambda e=exc: error_box(e))

    apply_mode_ui()
    set_ui(core.is_obhod_on())
    wanted_on["v"] = core.is_obhod_on()
    srv = core.active_server_or_none()
    core.emit_log(f"Состояние · {'туннель включён' if wanted_on['v'] else 'туннель выключен'} · "
                  f"{srv['name'] if srv else 'нет сервера'} · режим {current_mode['v']}", "INFO")

    def poll() -> None:
        if busy["v"]:
            root.after(5000, poll)
            return
        on = core.is_obhod_on()
        if wanted_on["v"] and not on:
            now = time.monotonic()
            if now - reconnect["last"] >= 8:
                reconnect["last"] = now
                reconnect["n"] += 1
                if reconnect["n"] <= 5:
                    busy["v"] = True
                    core.emit_log(f"Автопереподключение · попытка {reconnect['n']}/5", "WARN")

                    def work() -> None:
                        ui(set_busy, True)
                        ui(set_connecting_ui, f"Переподключение · попытка {reconnect['n']}/5…")
                        try:
                            ok, msg = core.start_obhod()
                            if ok:
                                reconnect["n"] = 0
                                ui(set_ui, True, msg)
                            elif reconnect["n"] >= 5:
                                wanted_on["v"] = False
                                ui(set_ui, False, "Туннель упал")
                        except Exception:
                            core.emit_log("Ошибка автопереподключения", "ERROR")
                            if reconnect["n"] >= 5:
                                wanted_on["v"] = False
                                ui(set_ui, False, "Туннель упал")
                        finally:
                            ui(set_busy, False)

                    threading.Thread(target=work, daemon=True).start()
                else:
                    wanted_on["v"] = False
                    set_ui(False, "Туннель упал")
        elif on != bool(switch.get()):
            set_ui(on)
            if on:
                reconnect["n"] = 0
        elif on:
            reconnect["n"] = 0
        root.after(5000, poll)

    root.after(5000, poll)

    def on_close() -> None:
        if busy["v"]:
            messagebox.showwarning(core.APP_NAME, "Дождитесь завершения текущей операции.", parent=root)
            return
        if not core.is_obhod_on():
            core.set_log_sink(None)
            root.destroy()
            return
        answer = messagebox.askyesnocancel(
            core.APP_NAME,
            "Обход сейчас включён.\n\nДа — выключить VPN и закрыть.\n"
            "Нет — оставить VPN включённым и закрыть окно.\nОтмена — вернуться в приложение.",
            parent=root,
        )
        if answer is True:
            wanted_on["v"] = False
            set_busy(True)
            set_disconnecting_ui("Отключение перед закрытием…")

            def stop_then_close() -> None:
                core.stop_obhod()
                ui(root.destroy)

            threading.Thread(target=stop_then_close, daemon=True).start()
        elif answer is False:
            core.set_log_sink(None)
            root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()

# OBHOD-VPS

Клиент обхода блокировок для Windows и Linux: интерфейс на customtkinter, туннель — встроенный sing-box (Hysteria2 + Shadowsocks), TUN-режим, режимы «Работа», «Дом», «Приватность».

## Скачать

Готовый `.exe` — [Releases](https://github.com/krammyy/obhod-vps/releases).

## Возможности

- несколько серверов с переключением, развёртывание новой VM по SSH;
- списки доменов, подсетей и приложений (`process_name`): что идёт через VPS, что напрямую;
- QR и ссылка `obhod://` для телефона;
- сборка `.deb` для Linux.

## Сборка

Windows:

```powershell
pyinstaller --noconfirm --clean OBHOD-VPS.spec
```

Перед сборкой положите рядом (в git этого нет):

- `server.json` — ваш сервер; без файла клиент соберётся без встроенного сервера;
- `vendor/sing-box.exe` — sing-box 1.13.14, SHA-256 в `obhod_win.SINGBOX_SHA256`;
- `vendor/linux/sing-box` — sing-box 1.13.21 для `.deb`.

Linux `.deb`: `packaging/linux/build_deb.sh` в WSL Debian; скрипты должны быть с LF.

## Секреты

`server.json`, `servers.json`, `settings.json`, `keys/`, `vendor/` — в `.gitignore` и в репозиторий не попадают.

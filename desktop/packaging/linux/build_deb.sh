#!/bin/sh
# Build obhod-vps_<ver>_amd64.deb. Run on Debian (WSL is fine) from the project root:
#   SITE_PACKAGES=<dir with customtkinter and darkdetect> sh packaging/linux/build_deb.sh <out_dir>
set -eu
ROOT=$(pwd)
OUT=${1:-$ROOT/dist}
VER=$(sed -n 's/^APP_VERSION = "\(.*\)"/\1/p' obhod_core.py | tr -d '\r')
SITE=${SITE_PACKAGES:?set SITE_PACKAGES to a dir with customtkinter and darkdetect}
STAGE=$(mktemp -d)
PKG=$STAGE/obhod-vps_${VER}_amd64
mkdir -p "$PKG/DEBIAN" "$PKG/opt/obhod-vps/lib" "$PKG/usr/bin" "$PKG/usr/share/applications" \
         "$PKG/usr/share/icons/hicolor/256x256/apps"

install -m 644 obhod_app.py obhod_core.py obhod_linux.py obhod_gui.py obhod_provision.py obhod-icon.png \
    "$PKG/opt/obhod-vps/"
install -m 644 server.json "$PKG/opt/obhod-vps/server.json"
install -m 755 vendor/linux/sing-box "$PKG/opt/obhod-vps/sing-box"
cp -r "$SITE/customtkinter" "$SITE/darkdetect" "$PKG/opt/obhod-vps/lib/"
find "$PKG/opt/obhod-vps" -name __pycache__ -prune -exec rm -rf {} +
install -m 644 packaging/linux/obhod-vps.png "$PKG/usr/share/icons/hicolor/256x256/apps/obhod-vps.png"

cat > "$PKG/usr/bin/obhod-vps" <<'SH'
#!/bin/sh
export PYTHONPATH=/opt/obhod-vps/lib${PYTHONPATH:+:$PYTHONPATH}
exec /usr/bin/python3 /opt/obhod-vps/obhod_app.py "$@"
SH
chmod 755 "$PKG/usr/bin/obhod-vps"

cat > "$PKG/usr/share/applications/obhod-vps.desktop" <<'DESK'
[Desktop Entry]
Type=Application
Name=OBHOD VPS
Comment=Быстрый обход через личный VPS
Exec=obhod-vps
Icon=obhod-vps
Terminal=false
Categories=Network;
DESK

SIZE=$(du -sk "$PKG" | cut -f1)
cat > "$PKG/DEBIAN/control" <<CTRL
Package: obhod-vps
Version: $VER
Architecture: amd64
Maintainer: krammy <noreply@obhod.local>
Installed-Size: $SIZE
Depends: python3 (>= 3.11), python3-tk, python3-paramiko, python3-cryptography, python3-pil, python3-pil.imagetk, python3-qrcode, python3-packaging, libcap2-bin, iproute2
Section: net
Priority: optional
Description: OBHOD VPS client (sing-box TUN, Hysteria2/Shadowsocks)
 GUI client for personal VPS servers: Work/Home/Privacy modes, several
 servers with switching, one-click provisioning of a new VM over SSH,
 editable direct/proxy lists, QR export for the Android app.
CTRL

cat > "$PKG/DEBIAN/postinst" <<'POST'
#!/bin/sh
set -e
# TUN and routing without running the GUI as root.
setcap cap_net_admin,cap_net_raw,cap_net_bind_service+ep /opt/obhod-vps/sing-box
command -v update-desktop-database >/dev/null && update-desktop-database -q /usr/share/applications || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q /usr/share/icons/hicolor || true
exit 0
POST
cat > "$PKG/DEBIAN/prerm" <<'PRERM'
#!/bin/sh
pkill -TERM -f '^/opt/obhod-vps/sing-box run' 2>/dev/null || true
exit 0
PRERM
chmod 755 "$PKG/DEBIAN/postinst" "$PKG/DEBIAN/prerm"

mkdir -p "$OUT"
dpkg-deb --root-owner-group --build "$PKG" "$OUT/obhod-vps_${VER}_amd64.deb"
rm -rf "$STAGE"

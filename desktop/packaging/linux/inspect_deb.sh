#!/bin/sh
# Print metadata and non-vendored contents of the built package.
D=${1:-dist/obhod-vps_2.6.0_amd64.deb}
dpkg-deb -f "$D" Package Version Depends Installed-Size
dpkg-deb -c "$D" | grep -v -e 'lib/customtkinter/.' -e 'lib/darkdetect/.' | awk '{print $1, $6}'

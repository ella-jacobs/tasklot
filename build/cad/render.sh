#!/bin/sh
# Render every TaskLot part (or just one) to PNG, an iso and a top view each, in
# renders/ for visual review. audit.py renders iso and underside views instead.
#
# Usage: ./render.sh [part]    (runs from any directory; renders/ is git-ignored)
# OpenSCAD is found through OPENSCAD_BIN, then PATH, then the usual macOS app locations.
set -u

find_openscad() {
  if [ -n "${OPENSCAD_BIN:-}" ]; then echo "$OPENSCAD_BIN"; return; fi
  if command -v openscad >/dev/null 2>&1; then command -v openscad; return; fi
  for app in /Applications/OpenSCAD.app /Applications/OpenSCAD-2021.01.app; do
    if [ -x "$app/Contents/MacOS/OpenSCAD" ]; then echo "$app/Contents/MacOS/OpenSCAD"; return; fi
  done
  echo openscad
}
openscad_bin="$(find_openscad)"

cd "$(dirname "$0")" || exit 1
mkdir -p renders
for p in ${1:-assembly base lcd_frame reader_coupon restaurant restaurant_body restaurant_roof restaurant_sign bottom_panel}; do
  "$openscad_bin" -o "renders/$p-iso.png" -D "part=\"$p\"" --camera=0,0,0,60,0,35,0 --viewall --autocenter \
    --imgsize=1400,1000 --projection=ortho tasklot_base.scad 2>&1 | grep -iE "^ERROR|^WARNING"
  "$openscad_bin" -o "renders/$p-top.png" -D "part=\"$p\"" --camera=0,0,0,0,0,0,0 --viewall --autocenter \
    --imgsize=1400,1000 --projection=ortho tasklot_base.scad 2>&1 | grep -iE "^ERROR|^WARNING"
done
echo "-> renders/"

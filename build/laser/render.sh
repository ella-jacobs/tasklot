#!/bin/sh
# Export the original per-sheet laser parts (sheet_*) from tasklot_laser.scad to SVG and
# DXF in exports/. The VLS run files come from make_uls_files.py instead.
#
# Usage: ./render.sh    (runs from any directory)
# OpenSCAD is found through OPENSCAD_BIN, then PATH, then the usual macOS app locations.
set -eu

find_openscad() {
  if [ -n "${OPENSCAD_BIN:-}" ]; then echo "$OPENSCAD_BIN"; return; fi
  if command -v openscad >/dev/null 2>&1; then command -v openscad; return; fi
  for app in /Applications/OpenSCAD.app /Applications/OpenSCAD-2021.01.app; do
    if [ -x "$app/Contents/MacOS/OpenSCAD" ]; then echo "$app/Contents/MacOS/OpenSCAD"; return; fi
  done
  echo openscad
}
openscad_bin="$(find_openscad)"

cd "$(dirname "$0")"
mkdir -p exports

for tasklot_part in sheet_1_cut sheet_1_score sheet_1_underside_score sheet_2_cut sheet_3_cut sheet_3_score sheet_4_reader_holders; do
  "$openscad_bin" -o "exports/${tasklot_part}.svg" -D "part=\"${tasklot_part}\"" tasklot_laser.scad
  "$openscad_bin" -o "exports/${tasklot_part}.dxf" -D "part=\"${tasklot_part}\"" tasklot_laser.scad
done

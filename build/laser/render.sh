#!/bin/sh
set -eu

OPENSCAD_BIN="${OPENSCAD_BIN:-/opt/homebrew/bin/openscad}"
mkdir -p exports

for tasklot_part in sheet_1_cut sheet_1_score sheet_1_underside_score sheet_2_cut sheet_3_cut sheet_3_score sheet_4_reader_holders; do
  "$OPENSCAD_BIN" -o "exports/${tasklot_part}.svg" -D "part=\"${tasklot_part}\"" tasklot_laser.scad
  "$OPENSCAD_BIN" -o "exports/${tasklot_part}.dxf" -D "part=\"${tasklot_part}\"" tasklot_laser.scad
done

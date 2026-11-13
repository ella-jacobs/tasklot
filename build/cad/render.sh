#!/bin/bash
# Render TaskLot parts to PNG (an iso and a top view each) in renders/ for visual review.
# Usage: ./render.sh [part]    (default: every part; renders/ is git-ignored)
SC=$(command -v openscad || echo /Applications/OpenSCAD-2021.01.app/Contents/MacOS/OpenSCAD)
cd "$(dirname "$0")"; mkdir -p renders
for p in ${1:-assembly base lcd_frame reader_coupon restaurant restaurant_body restaurant_roof restaurant_sign bottom_panel}; do
  "$SC" -o renders/$p-iso.png -D "part=\"$p\"" --camera=0,0,0,60,0,35,0 --viewall --autocenter \
    --imgsize=1400,1000 --projection=ortho tasklot_base.scad 2>&1 | grep -iE "^ERROR|^WARNING"
  "$SC" -o renders/$p-top.png -D "part=\"$p\"" --camera=0,0,0,0,0,0,0 --viewall --autocenter \
    --imgsize=1400,1000 --projection=ortho tasklot_base.scad 2>&1 | grep -iE "^ERROR|^WARNING"
done
echo "-> renders/"

# build/laser — the plywood deck and walls

The base of the lot is laser-cut from 1/8 in birch plywood on a Universal VLS 3.60
(24 x 12 in bed). All geometry is parametric OpenSCAD in `tasklot_laser.scad`; nothing is
hand-drawn.

| File | What it is |
|---|---|
| `tasklot_laser.scad` | Every laser part, selected with `-D part="<name>"`. |
| `make_uls_files.py` | Builds the VLS run files: one multi-page PDF per sheet (each page is the bed), plus SVG fallbacks. The driver separates operations by colour: red hairline = cut, blue hairline = etch, black fill = raster engrave. |
| `render.sh` | Exports the original `sheet_*` parts to SVG and DXF. |
| `exports/uls/` | The generated VLS files (deck sheet, walls sheet, recovery and final-recut sheets, optional parts). |
| `exports/sheet_*` | The earlier per-sheet SVG/DXF exports. |

```bash
cd build/laser
python3 make_uls_files.py     # needs OpenSCAD; set OPENSCAD_BIN if it is not on the default path
./render.sh                   # run from build/laser
```

Text parts (the lot numerals and the sign lettering) take OpenSCAD several minutes each
to export.

The laser conversion was a shared effort with a teammate (see the credits in the root
README), and was AI-assisted (Claude, Anthropic). Verify dimensions and laser settings
with shop staff before cutting.

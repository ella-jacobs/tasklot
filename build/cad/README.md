# build/cad — the 3D-printed parts

Parametric OpenSCAD for the 3D-printed parts: the reader holders that hold each RC522
under the deck, the LCD frame, the drive-through restaurant (body, roof, sign), the
bottom panel, and the original one-piece printed base.

| File | What it is |
|---|---|
| `tasklot_parameters.scad` | Every dimension, in one place. Edit this first. |
| `tasklot_base.scad` | The geometry. Select a part with `-D part="<name>"`. |
| `view/*.scad` | One-line wrappers for opening a single part in the OpenSCAD GUI. |
| `exports/*.stl` | The exported parts. |
| `audit.py` | Pre-print checks: export freshness, mesh validity, bed fit per printer, bed-contact area, and a ray-cast of the RC522 channel against measured hardware. Writes PNG renders to `renders/`. |
| `render.sh` | Renders every part to `renders/` for visual review. |

```bash
cd build/cad
python3 audit.py              # all parts (needs OpenSCAD)
python3 audit.py restaurant   # one part
./render.sh
```

`audit.py` prints its checks; it does not judge the renders. Look at the `-under` views,
because the channels, lips, and pockets are all on undersides.

The `HARDWARE` table at the top of `audit.py` is the ground-truth component list. Any
entry marked `verified=False` is still a guess.

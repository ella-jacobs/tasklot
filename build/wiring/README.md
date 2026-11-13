# build/wiring — wire lengths and the under-deck wiring plan

| File | What it is |
|---|---|
| `wiring-lengths.html` | The wiring pack: bus topology, the deck plan to scale, cut lists in mm, gauge and quantity, and the 3.3 V rail caveat. Open it in a browser. |
| `deck-wiring-plan-1to1.svg` | The plan alone, 330 x 270 mm on a 10 mm grid. Print at 100 % with no scaling, and mirror in X to lay it against the flipped deck. |
| `gen_plan.py` | Generates the SVG and prints the computed segment lengths. Edit this, not the SVG. |

```bash
python3 build/wiring/gen_plan.py
```

## Where the numbers come from

Everything is derived from the CAD, nothing is measured:

- Reader centres: `build/cad/tasklot_parameters.scad`.
- Holder footprint (67 x 51 mm) and its open end, where the wires leave: `build/cad/tasklot_base.scad`.
- Deck, LCD cable hole, and restaurant footprint: `build/laser/tasklot_laser.scad`.
- Pins: `firmware/tasklot_full_v2` (SS 44 / 45 / 40 / 41 / 36 / 37, RST A0).

Cut length = (straight route + 25 mm vertical drop) x 1.15 + 60 mm service loop, rounded
up to 25 mm. The service loop lets the deck lift off without unsoldering anything.

Two inputs are not measured: the Mega's position on the deck (good to about +/- 25 mm,
absorbed by the service loop) and the RC522 header height (`reader_header_underside`).

Note: `gen_plan.py` still labels the two lane readers with their earlier names (RECORD on
SS 36, DRIVE-THROUGH on SS 37). The firmware now calls them the speaker and the pickup
lane; see `DESIGN.md` for the pin question.

Page, diagrams, and calculations were AI-assisted (Claude, Anthropic).

#!/usr/bin/env python3
"""Generate the 1:1 under-deck wiring plan for TaskLot (deck-wiring-plan-1to1.svg).

    python3 build/wiring/gen_plan.py

Draws the deck, the six reader holders, the Mega, the shared 6-conductor SPI bus
and one chip-select (SS) run per reader, to scale on a 10 mm grid, and prints the
computed exit points and Manhattan segment lengths so they can be checked against
the cut list in wiring-lengths.html.

All coordinates are OpenSCAD deck coordinates (mm, origin bottom-left, +Y toward
the back), taken from build/cad and build/laser. The SVG flips Y so the drawing
reads the same way up as the laser score sheets. The output file is written next
to this script; edit this script, not the SVG.

This is a one-shot drawing script, so the drawing coordinates stay inline where
they are used.
"""
import os

W, H = 330.0, 270.0       # deck outline, mm (build/laser/tasklot_laser.scad `deck`)


def fy(y):
    """Deck Y (up) -> SVG Y (down)."""
    return H - y


READERS = [
    # id, label, ss pin, center, open_end_dir (+1 = open toward +X, -1 = open toward -X)
    ("R1", "SPACE 1",       "44", (286, 55),  -1),
    ("R2", "SPACE 2",       "45", (286, 110), -1),
    ("R3", "SPACE 3",       "40", (286, 165), -1),
    ("R4", "SPACE 4",       "41", (286, 220), -1),
    ("R5", "RECORD",        "36", (80,  36),  +1),
    ("R6", "DRIVE-THROUGH", "37", (103, 150), +1),
]
HOLDER = (67.0, 51.0)     # printed glue-on holder footprint

MEGA = (212.0, 55.0)      # header field anchor -- +/- 25mm, measure the real board


def exit_pt(center, d):
    """Where a reader's wires leave its holder.

    Wires leave at the OPEN end of the U-channel, on the reader's centre-line.

    Args:
        center: (x, y) of the reader.
        d: +1 if the holder opens toward +X, -1 toward -X.
    """
    return (center[0] + d * (HOLDER[0] / 2.0), center[1])

def L(a, b, first="x"):
    """Manhattan polyline a->b."""
    if first == "x":
        mid = (b[0], a[1])
    else:
        mid = (a[0], b[1])
    return [a, mid, b]


def plen(pts):
    """Manhattan length of a polyline, in mm."""
    return sum(abs(pts[i+1][0]-pts[i][0]) + abs(pts[i+1][1]-pts[i][1]) for i in range(len(pts)-1))


def path(pts):
    """SVG path data for a polyline given in deck coordinates."""
    return "M " + " L ".join("%.1f,%.1f" % (p[0], fy(p[1])) for p in pts)


def rect(x, y, w, h, **kw):
    """An SVG <rect> from its deck-coordinate bottom-left corner.

    Keyword arguments become attributes, with "_" written as "-" (stroke_width).
    """
    at = " ".join('%s="%s"' % (k.replace("_","-"), v) for k, v in kw.items())
    return '<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" %s/>' % (x, fy(y+h), w, h, at)


def txt(x, y, s, size=5, anchor="middle", fill="#142850", weight="700", family="monospace", rot=0):
    """An SVG <text> at deck coordinates (x, y), optionally rotated by `rot` degrees."""
    tr = ' transform="rotate(%d %.2f %.2f)"' % (rot, x, fy(y)) if rot else ""
    return ('<text x="%.2f" y="%.2f" font-family="%s" font-size="%.1f" font-weight="%s" '
            'text-anchor="%s" fill="%s"%s>%s</text>') % (x, fy(y), family, size, weight, anchor, fill, tr, s)

def main():
    """Compute the routes, write the SVG next to this script, and print the lengths."""
    # ---------------------------------------------------------------- routes
    exits = {}
    for rid, lab, ss, c, d in READERS:
        exits[rid] = exit_pt(c, d)

    # shared 6-conductor bus: trunk to R1, daisy-chain up the parking column,
    # second branch out to the drive-through then the record reader
    BUS = [
        ("B0", "MEGA -> R1",  L(MEGA, exits["R1"], "x")),
        ("B1", "R1 -> R2",    [exits["R1"], exits["R2"]]),
        ("B2", "R2 -> R3",    [exits["R2"], exits["R3"]]),
        ("B3", "R3 -> R4",    [exits["R3"], exits["R4"]]),
        ("B4", "MEGA -> R6",  [MEGA, (MEGA[0], 150.0), exits["R6"]]),
        ("B5", "R6 -> R5",    [exits["R6"], (exits["R6"][0], 36.0), exits["R5"]]),
    ]

    SS = []
    for rid, lab, ss, c, d in READERS:
        e = exits[rid]
        if rid in ("R1",):
            pts = [e, MEGA]
        elif rid in ("R2", "R3", "R4"):
            pts = [e, (240.0, e[1]), (240.0, MEGA[1]), MEGA]
        else:
            pts = [e, (e[0], MEGA[1]), MEGA]
        SS.append((rid, ss, pts))

    # ---------------------------------------------------------------- draw
    MT, MB, MX = 34.0, 62.0, 8.0          # title strip, legend strip, side margin
    CW, CH = W + 2*MX, H + MT + MB
    o = []
    o.append('<svg xmlns="http://www.w3.org/2000/svg" width="%.1fmm" height="%.1fmm" '
             'viewBox="0 0 %.1f %.1f">' % (CW, CH, CW, CH))
    o.append('<rect width="%.1f" height="%.1f" fill="#ffffff"/>' % (CW, CH))

    # ---- title strip (canvas coords, not deck coords)
    o.append('<text x="%.1f" y="13" font-family="monospace" font-size="8" font-weight="700" fill="#142850">TASKLOT - UNDERSIDE WIRING PLAN</text>' % MX)
    o.append('<text x="%.1f" y="21.5" font-family="monospace" font-size="4.6" fill="#5a5346">deck 330 x 270 mm, viewed from ABOVE. Print at 100%% and MIRROR IN X before tracing on the flipped deck.</text>' % MX)
    o.append('<text x="%.1f" y="28.5" font-family="monospace" font-size="4.6" fill="#5a5346">Lengths shown are straight-line routes. Cut list on the wiring page adds vertical drop, routing and a service loop.</text>' % MX)
    o.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#d8d2bf" stroke-width="0.5"/>' % (MX, MT-4, CW-MX, MT-4))

    o.append('<g transform="translate(%.1f,%.1f)">' % (MX, MT))

    # deck outline
    o.append('<rect x="0.4" y="0.4" width="%.1f" height="%.1f" rx="5" fill="none" '
             'stroke="#1a1a1a" stroke-width="0.8"/>' % (W-0.8, H-0.8))

    # 10 mm grid
    g = ['<g stroke="#dfe3e6" stroke-width="0.2">']
    for x in range(0, int(W)+1, 10):
        g.append('<line x1="%d" y1="0" x2="%d" y2="%.0f"/>' % (x, x, H))
    for y in range(0, int(H)+1, 10):
        g.append('<line x1="0" y1="%d" x2="%.0f" y2="%d"/>' % (y, W, y))
    g.append('</g>')
    o.append("".join(g))
    # 50 mm grid
    g = ['<g stroke="#c3cbd1" stroke-width="0.35">']
    for x in range(0, int(W)+1, 50):
        g.append('<line x1="%d" y1="0" x2="%d" y2="%.0f"/>' % (x, x, H))
    for y in range(0, int(H)+1, 50):
        g.append('<line x1="0" y1="%d" x2="%.0f" y2="%d"/>' % (y, W, y))
    g.append('</g>')
    o.append("".join(g))

    # keepouts / above-deck footprints
    o.append(rect(18, 112, 112, 76, fill="#f6f1e6", stroke="#d8d2bf", stroke_width="0.5", stroke_dasharray="3 2"))
    o.append(txt(74, 116, "RESTAURANT (above deck)", 4.2, fill="#8a8375"))
    o.append(rect(10, 182, 155, 78, fill="#faf6ee", stroke="#d8d2bf", stroke_width="0.5", stroke_dasharray="3 2"))
    o.append(txt(87.5, 254, "POWER BANK keepout", 4.2, fill="#8a8375"))
    o.append(rect(111.4, 228, 107.2, 34, fill="#eef7f8", stroke="#1F8A9E", stroke_width="0.5", stroke_dasharray="3 2"))
    o.append(txt(165, 258, "LCD FRAME glue footprint", 4.2, fill="#1F8A9E"))
    o.append(rect(115, 231, 34, 18, fill="#ffffff", stroke="#1F8A9E", stroke_width="0.7"))
    o.append(txt(132, 238, "CABLE", 3.6, fill="#1F8A9E"))
    o.append(txt(132, 233.5, "HOLE", 3.6, fill="#1F8A9E"))

    # Mega
    o.append(rect(120, 10, 112, 68, fill="none", stroke="#9A3DBF", stroke_width="0.4", stroke_dasharray="2 2"))
    o.append(rect(125.2, 17.3, 101.5, 53.3, fill="#f5eaf9", stroke="#9A3DBF", stroke_width="0.7"))
    o.append(txt(176, 36, "ELEGOO MEGA 2560", 5.2, fill="#9A3DBF"))
    o.append(txt(176, 66, "101.5 x 53.3 board", 3.8, fill="#9A3DBF", weight="400"))
    o.append(txt(176, 29, "orientation not fixed - measure it", 3.6, fill="#9A3DBF", weight="400"))

    # holders
    for rid, lab, ss, c, d in READERS:
        x0 = c[0] - HOLDER[0]/2.0
        y0 = c[1] - HOLDER[1]/2.0
        o.append(rect(x0, y0, HOLDER[0], HOLDER[1], fill="#e8f7f8", stroke="#1F8A9E", stroke_width="0.7"))
        # RC522 board 60 x 39 seated against the backstop
        bx = x0 + (2.5 if d < 0 else HOLDER[0]-2.5-60)
        o.append(rect(bx, c[1]-19.5, 60, 39, fill="none", stroke="#3EC1C7", stroke_width="0.5", stroke_dasharray="2 1.5"))
        # open end marker
        ex, ey = exits[rid]
        o.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#E3001B" stroke-width="1.4"/>'
                 % (ex, fy(c[1]-HOLDER[1]/2.0+2), ex, fy(c[1]+HOLDER[1]/2.0-2)))
        o.append(txt(c[0], c[1]+4, rid, 7.5, fill="#1F8A9E"))
        o.append(txt(c[0], c[1]-3, lab, 4.0, fill="#5a5346", weight="400"))
        o.append(txt(c[0], c[1]-10, "SS " + ss, 4.4, fill="#142850"))
        o.append(txt(c[0], c[1]-HOLDER[1]/2.0+3.0, "centre (%d, %d)" % c, 3.4, fill="#8a8375", weight="400"))

    # routes: SS first (thin), bus on top (thick)
    o.append('<g fill="none" stroke="#142850" stroke-width="0.9" stroke-dasharray="4 2.5" stroke-linejoin="round">')
    for rid, ss, pts in SS:
        o.append('<path d="%s"/>' % path(pts))
    o.append('</g>')
    o.append('<g fill="none" stroke="#1F8A9E" stroke-width="2.6" stroke-linejoin="round" stroke-linecap="round" opacity="0.85">')
    for bid, lab, pts in BUS:
        o.append('<path d="%s"/>' % path(pts))
    o.append('</g>')

    # exit dots + segment length labels
    for bid, lab, pts in BUS:
        mx = (pts[0][0] + pts[-1][0]) / 2.0
        my = (pts[0][1] + pts[-1][1]) / 2.0
        off = -30.0 if bid == "B0" else (3.0 if bid in ("B1","B2","B3") else -16.0)
        o.append('<rect x="%.1f" y="%.1f" width="28" height="7" rx="1.5" fill="#ffffff" opacity="0.92"/>'
                 % (mx+off, fy(my)-3.5))
        o.append(txt(mx+off+2, my-2.4, "%s %.0fmm" % (bid, plen(pts)), 4.6, anchor="start", fill="#1F8A9E"))
    for rid, lab, ss, c, d in READERS:
        ex, ey = exits[rid]
        o.append('<circle cx="%.1f" cy="%.1f" r="1.8" fill="#E3001B"/>' % (ex, fy(ey)))
    o.append('<circle cx="%.1f" cy="%.1f" r="2.4" fill="#9A3DBF"/>' % (MEGA[0], fy(MEGA[1])))

    o.append('</g>')   # end deck group

    # legend strip (canvas coords)
    LY = MT + H + 10
    o.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#d8d2bf" stroke-width="0.5"/>' % (MX, LY-6, CW-MX, LY-6))
    def leg(x, swatch, label):
        """One legend row: a line swatch at x and its label, on the current legend line LY."""
        o.append(swatch % (x, LY-1.6, x+16, LY-1.6))
        o.append('<text x="%.1f" y="%.1f" font-family="monospace" font-size="4.6" fill="#5a5346">%s</text>' % (x+20, LY, label))
    leg(MX, '<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#1F8A9E" stroke-width="2.6"/>', 'shared bus, 6 conductors: 3V3 / GND / SCK 52 / MOSI 51 / MISO 50 / RST A0')
    LY += 8
    leg(MX, '<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#142850" stroke-width="0.9" stroke-dasharray="4 2.5"/>', 'SS (chip select), one per reader, its own wire all the way to the Mega')
    LY += 8
    o.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#E3001B" stroke-width="1.8"/>' % (MX+7, LY-5, MX+7, LY+2))
    o.append('<text x="%.1f" y="%.1f" font-family="monospace" font-size="4.6" fill="#5a5346">red bar = OPEN end of the U-channel. The board slides in here and the wires leave here.</text>' % (MX+20, LY))
    LY += 8
    o.append('<text x="%.1f" y="%.1f" font-family="monospace" font-size="4.2" fill="#8a8375">grid 10 mm, heavy line 50 mm. Purple dot = Mega header field, +/- 25 mm: measure the real board once it is mounted.</text>' % (MX, LY))
    LY += 7
    o.append('<text x="%.1f" y="%.1f" font-family="monospace" font-size="4.0" fill="#8a8375">AI-assisted (Claude, Anthropic). Verify every fit against a real RC522 before soldering.</text>' % (MX, LY))

    o.append('</svg>')

    svg = "\n".join(o)
    # Written next to this script, so it works from any checkout and any working directory.
    OUT_SVG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "deck-wiring-plan-1to1.svg")
    with open(OUT_SVG, "w") as f:
        f.write(svg)

    # ---- print the computed numbers so they can be checked
    print("exit points:")
    for rid, lab, ss, c, d in READERS:
        print("  %s %-14s SS %-3s centre %-10s exit %s" % (rid, lab, ss, str(c), str(exits[rid])))
    print("\nbus segments (manhattan):")
    for bid, lab, pts in BUS:
        print("  %s %-12s %6.1f mm" % (bid, lab, plen(pts)))
    print("\nSS runs (manhattan):")
    for rid, ss, pts in SS:
        print("  %s SS%-3s %6.1f mm" % (rid, ss, plen(pts)))


if __name__ == "__main__":
    main()

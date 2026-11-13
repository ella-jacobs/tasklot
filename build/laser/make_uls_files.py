#!/usr/bin/env python3
"""
Build the Universal VLS 3.60 run file for TaskLot.

Primary output is ONE multi-page PDF -- one page per laser job, in run order,
each page exactly 24 x 12 in so the page IS the bed. Open it once, print page 1,
swap stock, print page 2. Individual SVGs are written alongside as a fallback.

The VLS driver separates operations by COLOR, not by file:
    pure red   (255,0,0) hairline stroke -> vector CUT
    pure blue  (0,0,255) hairline stroke -> vector ETCH
    black fill (0,0,0)   no stroke       -> raster ENGRAVE
UCP runs raster before vector, which is the order we want: burn the lot
markings while the deck is still held by the sheet, then cut it free.

Geometry is exported from tasklot_laser.scad, never hand-drawn. OpenSCAD emits
only M/L/z, so the PDF paths below are exact, not approximated.

Usage:  python3 build/laser/make_uls_files.py     (from any directory)
        OPENSCAD_BIN=/path/to/openscad python3 make_uls_files.py

Writes exports/uls/*.pdf and *.svg next to this script; scratch layers go in
exports/uls/.layers/ (git-ignored). Raises CalledProcessError if OpenSCAD fails.
"""
import os
import re
import subprocess
import zlib

OPENSCAD = os.environ.get("OPENSCAD_BIN", "/opt/homebrew/bin/openscad")
HERE = os.path.dirname(os.path.abspath(__file__))
# Relative to HERE; main() changes into it so the script runs from any directory.
SCAD, OUT, TMP = "tasklot_laser.scad", "exports/uls", "exports/uls/.layers"

BED_W, BED_H = 609.6, 304.8      # 24 x 12 in engraving field, origin top-left
HAIR_MM = 0.0254                 # 0.001 in; VLS treats <0.007 in as vector
MM2PT = 72.0 / 25.4
PX, PY = 10.0, 10.0              # every sheet parks against the same corner

RED, BLUE, BLACK = (1, 0, 0), (0, 0, 1), (0, 0, 0)
_cache = {}


def scad_layer(part):
    """Export one tasklot_laser.scad part to SVG and return its path data.

    Results are cached, because several sheets reuse the same part.

    Returns:
        list[str]: the `d` attribute of every <path> OpenSCAD wrote.

    Raises:
        subprocess.CalledProcessError: OpenSCAD failed.
        SystemExit: the part exported no geometry.
    """
    if part not in _cache:
        os.makedirs(TMP, exist_ok=True)
        dst = f"{TMP}/{part}.svg"
        subprocess.run([OPENSCAD, "-o", dst, "-D", f'part="{part}"', SCAD],
                       check=True, capture_output=True)
        with open(dst) as f:
            paths = re.findall(r'<path\s+d="(.*?)"', f.read(), re.S)
        if not paths:
            raise SystemExit(f"{part}: OpenSCAD returned no geometry")
        _cache[part] = paths
    return _cache[part]


def subpaths(d):
    """Parse OpenSCAD's M/L/z path into lists of (x, y) in scad-emitted space."""
    out, cur = [], []
    for tok in re.finditer(r'([MLz])\s*(-?[\d.]+)?[, ]*(-?[\d.]+)?', d):
        c = tok.group(1)
        if c == "z":
            if cur:
                out.append(cur); cur = []
        else:
            if c == "M" and cur:
                out.append(cur); cur = []
            cur.append((float(tok.group(2)), float(tok.group(3))))
    if cur:
        out.append(cur)
    return out


# ---------------------------------------------------------------- run defs
# href = height of the coordinate frame being placed. OpenSCAD emits scad point
# (x,y) as (x,-y) in absolute coords regardless of how it cropped the viewBox,
# so placement is one translate by (PX, PY+href) -- crop-proof.
DECK_H, WALLS_H, BOTTOM_H, RECOVERY_H, RECUT_H = 270.0, 170.0, 266.0, 216.0, 241.0

# The deck sheet. One shot, so it holds ONLY the deck: the parking surface, the
# engraved lot markings, the six reader guides, the LCD cable hole. Both pages are
# the same physical sheet -- page 2 is the flip.
#
# The empty right-hand third of the sheet could take the two 264 mm side walls stood
# on end (38 x 264 fits in the 259 mm x 300 mm that survives even undersized 12x24
# stock, which is often really 11.8 x 23.6 in). Deliberately left out: one shot, one
# sheet, nothing competing with the deck. The walls live on the walls sheet instead.
DECK_SHEET = [
    ("DECK SHEET - everything, one job",
     "Raster the lot markings, etch the two hidden guides, then cut: the deck, both "
     "side walls, the LCD bezel and back, and 20 corner squares. One 12 x 24 sheet.",
     [("deck_raster",      "raster", DECK_H),
      ("deck_etch",        "etch",   DECK_H),
      ("sheet_1_cut",      "cut",    DECK_H),
      ("uls_deck_sheet_extras", "cut", DECK_H)]),
]

# The walls sheet. All four walls in one 330 x 170 mm block -- a fraction of a sheet,
# so there is room to spare if anything else needs adding later.
WALLS_SHEET = [
    ("WALLS SHEET - front and back walls",
     "Front (Mega USB/power opening + three holes) and back (power-cord pass-through). "
     "330 x 82 mm. The side walls moved to the deck sheet. Cut only.",
     [("uls_walls_sheet", "cut", 82.0)]),
]

# Dropped from the main file 8/24. Two reasons: the deck outline is symmetric on BOTH
# axes, so it seats back in its hole four ways and only one is correct -- there is no
# feature to register orientation against, only position. And the six guides are the
# 67 x 51 footprint of the PRINTED holders, which were never printed and are now being
# made another way, so they would locate a part that does not exist. Kept as a
# standalone optional file rather than deleted.
UNDERSIDE = ("OPTIONAL - deck underside guides (requires flipping the deck)",
             "Only useful if the reader holders end up 67 x 51. Already mirrored.",
             [("deck_underside_score_mirrored", "etch", DECK_H)])

# Fallback for the deck sheet's page 1 if laser time turns out to be short. Same deck,
# markings etched as thin outlines instead of burned solid: much faster, but hollow
# numerals and thin double-line stalls, which are much harder to see from a distance.
ALT = ("DECK SHEET ALT - deck top, all vector, no raster pass",
       "Use INSTEAD of page 1 only if you are out of time.",
       [("deck_score_text",  "etch", DECK_H),
        ("deck_score_lines", "etch", DECK_H),
        ("sheet_1_cut",      "cut",  DECK_H)])

# Neither sheet needs this. It is a screwed-on service cover with a 220 x 105 mm hole
# already in it, and it is the only part that would demand a third sheet.
BOTTOM = ("OPTIONAL - bottom service panel",
          "Third sheet. Skippable; nothing else depends on it.",
          [("uls_bottom_cut", "cut", BOTTOM_H)])

# Recovery sheet after the printer failed on the LCD frame, restaurant roof/sign,
# and six RFID holders. One 12 x 24 sheet, with sign lettering etched before cuts.
RECOVERY = ("RECOVERY SHEET - LCD, roof, sign, and six RFID holders",
            "Etch the IN-N-OUT lettering first, then cut all parts.",
            [("uls_recovery_parts_etch", "etch", RECOVERY_H),
             ("uls_recovery_parts_cut",  "cut",  RECOVERY_H)])

# Final recut: the combined deck sheet deliberately shortened the two 330 mm
# feature-bearing walls to 281 mm. The physical build needs their full length.
RECUT = ("FINAL RECUT - walls, roof, sign, and eight RFID spacers",
         "Etch sign lettering first, then cut all parts.",
         [("uls_final_recut_etch", "etch", RECUT_H),
          ("uls_final_recut_cut",  "cut",  RECUT_H)])

# ---------------------------------------------------------------- PDF
def page_stream(groups):
    """One PDF content stream. Page origin is bottom-left, so y is flipped."""
    ops = [f"{HAIR_MM * MM2PT:.4f} w", "1 J", "1 j"]
    for part, mode, href in groups:
        r, g, b = BLACK if mode == "raster" else (RED if mode == "cut" else BLUE)
        ops.append(f"{r} {g} {b} rg" if mode == "raster" else f"{r} {g} {b} RG")
        for d in scad_layer(part):
            for sp in subpaths(d):
                for i, (x, y) in enumerate(sp):
                    # scad-emitted -> page (top-left, y down) -> PDF (y up)
                    px = (PX + x) * MM2PT
                    py = (BED_H - (PY + href + y)) * MM2PT
                    ops.append(f"{px:.4f} {py:.4f} {'m' if i == 0 else 'l'}")
                ops.append("h")
            ops.append("f*" if mode == "raster" else "S")
    return "\n".join(ops).encode("latin-1")


def write_pdf(path, pages):
    """Write a minimal PDF 1.4 file with one bed-sized page per run.

    Args:
        path: output file.
        pages: list of (title, note, groups); groups as in page_stream().

    Side effects:
        Writes `path`; exports every part it needs through OpenSCAD (cached).
    """
    W, H = BED_W * MM2PT, BED_H * MM2PT
    objs, kids = {}, []
    n = 3
    for _title, _note, groups in pages:
        # Flate-compressed: the uncompressed stream is ~10x larger, and its long runs of
        # plain-text coordinates are noise in diffs and text searches of the repo.
        content = zlib.compress(page_stream(groups), 9)
        objs[n] = (b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(content)
                   + content + b"\nendstream")
        objs[n + 1] = ("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %g %g] "
                       "/Contents %d 0 R /Resources << >> >>" % (W, H, n)).encode()
        kids.append(n + 1); n += 2
    objs[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objs[2] = ("<< /Type /Pages /Count %d /Kids [%s] >>"
               % (len(kids), " ".join("%d 0 R" % k for k in kids))).encode()

    buf, offsets = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"), {}
    for i in sorted(objs):
        offsets[i] = len(buf)
        buf += b"%d 0 obj\n" % i + objs[i] + b"\nendobj\n"
    xref = len(buf)
    buf += b"xref\n0 %d\n0000000000 65535 f\n" % (max(objs) + 1)
    for i in range(1, max(objs) + 1):
        buf += b"%010d 00000 n\n" % offsets.get(i, 0)
    buf += (b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
            % (max(objs) + 1, xref))
    with open(path, "wb") as f:
        f.write(bytes(buf))


# ---------------------------------------------------------------- SVG fallback
def write_svg(name, title, groups, flatten=False, canvas=(BED_W, BED_H), offset=(PX, PY)):
    """Write one run as an SVG fallback, colour-coded the same way as the PDF.

    Args:
        name: file name under OUT, without .svg.
        title: shown in the SVG comment and <title>.
        groups: list of (part, mode, href); mode is "cut", "etch" or "raster".
        flatten: write every contour as its own closed path in page coordinates,
            instead of OpenSCAD's compound paths under a translate.
        canvas: (width, height) of the page in mm.
        offset: (x, y) where the frame's origin is placed on the page, in mm.
    """
    canvas_w, canvas_h = canvas
    ox, oy = offset
    gs = []
    for part, mode, href in groups:
        if mode == "raster":
            style = 'fill="#000000" fill-rule="evenodd" stroke="none"'
        else:
            style = ('fill="none" stroke="%s" stroke-width="%s"'
                     % ("#FF0000" if mode == "cut" else "#0000FF", HAIR_MM))
        if flatten:
            # Write every contour as an independent, explicitly closed path. OpenSCAD's
            # compound path is valid, but some laser/viewer software makes its lowercase
            # `z` closures look like missing sides at hairline width.
            contours = []
            for d in scad_layer(part):
                for contour in subpaths(d):
                    # Flatten OpenSCAD's negative-Y coordinates into the positive
                    # top-left page coordinate system. Avoid group transforms because
                    # some SVG preview/import tools crop transformed negative geometry.
                    page = [(ox + x, oy + href + y) for x, y in contour]
                    commands = ["M %.6g,%.6g" % page[0]]
                    commands += ["L %.6g,%.6g" % point for point in page[1:]]
                    contours.append(" ".join(commands) + " Z")
            body = "\n".join('    <path d="%s"/>' % d for d in contours)
            gs.append('  <g %s>\n%s\n  </g>' % (style, body))
        else:
            body = "\n".join('    <path d="%s"/>' % d for d in scad_layer(part))
            gs.append('  <g transform="translate(%s,%s)" %s>\n%s\n  </g>'
                      % (ox, oy + href, style, body))
    svg = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!-- TaskLot %s. VLS 3.60, %s x %s mm bed, origin top-left.\n'
        '     red=vector cut  blue=vector etch  black=raster engrave.\n'
        '     Generated from tasklot_laser.scad by make_uls_files.py. -->\n'
        '<svg xmlns="http://www.w3.org/2000/svg" version="1.1"\n'
        '     width="%smm" height="%smm" viewBox="0 0 %s %s">\n'
        '  <title>TaskLot %s</title>\n%s\n</svg>\n'
        % (title, canvas_w, canvas_h, canvas_w, canvas_h, canvas_w, canvas_h,
           title, "\n".join(gs)))
    with open("%s/%s.svg" % (OUT, name), "w") as f:
        f.write(svg)


def main():
    """Write every run file and print what each one is for."""
    os.chdir(HERE)
    os.makedirs(OUT, exist_ok=True)

    write_pdf(f"{OUT}/TASKLOT-deck-sheet.pdf", DECK_SHEET)
    print(f"  {OUT}/TASKLOT-deck-sheet.pdf             {len(DECK_SHEET)} pages  <- ESSENTIAL, all on ONE 12x24 sheet")
    for i, (title, _n, groups) in enumerate(DECK_SHEET, 1):
        write_svg("deck_sheet_page%d" % i, title, groups)

    write_pdf(f"{OUT}/TASKLOT-walls-sheet.pdf", WALLS_SHEET)
    print(f"  {OUT}/TASKLOT-walls-sheet.pdf            1 page   <- front+back walls only")
    write_svg("walls_sheet_page1", WALLS_SHEET[0][0], WALLS_SHEET[0][2])

    write_pdf(f"{OUT}/TASKLOT-OPTIONAL-bottom-panel.pdf", [BOTTOM])
    write_svg("optional_bottom_panel", BOTTOM[0], BOTTOM[2])
    print(f"  {OUT}/TASKLOT-OPTIONAL-bottom-panel.pdf  1 page   <- only if a 3rd sheet appears")

    write_pdf(f"{OUT}/TASKLOT-RECOVERY-small-parts.pdf", [RECOVERY])
    write_svg("TASKLOT-RECOVERY-small-parts", RECOVERY[0], RECOVERY[2], flatten=True)
    print(f"  {OUT}/TASKLOT-RECOVERY-small-parts.pdf   1 page   <- LCD, roof, sign, 6 holders")

    write_svg("TASKLOT-FINAL-RECUT-roof-sign-full-walls", RECUT[0], RECUT[2], flatten=True,
              canvas=(336, 247), offset=(3, 3))
    print(f"  {OUT}/TASKLOT-FINAL-RECUT-roof-sign-full-walls.svg   <- walls, roof, sign, 8 RFID spacers")

    write_pdf(f"{OUT}/TASKLOT-OPTIONAL-deck-underside.pdf", [UNDERSIDE])
    write_svg("optional_deck_underside", UNDERSIDE[0], UNDERSIDE[2])
    print(f"  {OUT}/TASKLOT-OPTIONAL-deck-underside.pdf   1 page   <- dropped from the main file")
    write_pdf(f"{OUT}/TASKLOT-deck-sheet-ALT-all-vector.pdf", [ALT])
    write_svg("deck_sheet_ALT_all_vector", ALT[0], ALT[2])
    print(f"  {OUT}/TASKLOT-deck-sheet-ALT-all-vector.pdf        <- fallback for page 1 if the slot is short")


if __name__ == "__main__":
    main()

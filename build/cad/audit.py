#!/usr/bin/env python3
"""TaskLot CAD pre-print audit: deterministic checks on the exported STL parts.

    python3 audit.py              # all parts
    python3 audit.py restaurant   # one part (affects which parts are rendered)

Checks, in order:
  freshness    every STL is newer than the .scad it came from (and any copies in
               print-package/ match exports/)
  mesh + bed   watertight mesh, no solid islands floating free of the main body,
               the part sits on the bed, enough bed contact in its print pose,
               and which known printers it fits
  RC522 fit    ray-casts the exported reader coupon and compares the channel with
               the measured RC522 board
  renders      PNG renders to renders/ for a person to look at (needs OpenSCAD)

The script only reports; it does not judge the renders. Exit status is 1 if any
check is a blocker (FAIL), else 0.
"""
import hashlib
import math
import os
import struct
import subprocess
import sys
from collections import defaultdict

CAD = os.path.dirname(os.path.abspath(__file__))
SCAD = os.path.join(CAD, "tasklot_base.scad")
PARAMS = os.path.join(CAD, "tasklot_parameters.scad")
EXPORTS = os.path.join(CAD, "exports")
PKG = os.path.join(CAD, "print-package")   # optional copy of exports/ sent to a printer
OPENSCAD = next((p for p in [
    "/opt/homebrew/bin/openscad",
    "/Applications/OpenSCAD.app/Contents/MacOS/OpenSCAD",
    "/Applications/OpenSCAD-2021.01.app/Contents/MacOS/OpenSCAD",
] if os.path.exists(p)), None)

# ---- GROUND TRUTH -----------------------------------------------------------
# Real measured/datasheet component dimensions. UPDATE WITH CALIPERS.
# Anything marked verified=False is a guess and the audit will say so.
HARDWARE = {
    "rc522":      dict(dims=(39.0, 60.0, 1.6),  verified=True,
                       note="standard MFRC522 module; header on a 39mm short edge"),
    "lcd2004a":   dict(dims=(98.0, 60.0, 13.5), verified=True,
                       note="Raystar RC2004A datasheet: outline 98.0 x 60.0 x 13.6 max, "
                            "viewing area 77.0 x 25.2, active area 70.4 x 20.8, "
                            "mounting holes 93.0 x 55.0. Thickness w/ I2C backpack still unmeasured"),
    "mega2560":   dict(dims=(101.52, 53.3, 13.0), verified=True,
                       note="ELEGOO Mega; USB-B + barrel on one short edge, +4mm proud"),
    "car":        dict(dims=(20.0, 40.0, 18.0), verified=False,
                       note="UNVERIFIED -- measure the LARGEST car incl. ride height"),
}
PRINTERS = {           # name: (X, Y, Z)  -- UPDATE once the bed is measured
    "MK3S (self-serve)": (250, 210, 210),
    "Prusa XL (form, 1-5 days)": (360, 360, 360),
    "Bambu X1/P1": (256, 256, 256),
}
SELF_SERVE_PRINTER = "MK3S (self-serve)"
PARTS = ["reader_coupon", "lcd_frame", "restaurant", "restaurant_body",
         "restaurant_roof", "restaurant_sign", "base", "bottom_panel"]
# restaurant_body/roof/sign are the parts the print package actually sends to the printer.
# They were absent from this list, so the two printed parts were the only two never checked.
STL_OF = {p: os.path.join(EXPORTS, "tasklot-" + p.replace("_", "-") + ".stl") for p in PARTS}

# Exports that are intentionally a PLATE of several loose objects (the sign and its two
# posts): part -> number of separate solids expected. Every other part is one body.
PLATES = {"restaurant_sign": 3}

# ---- thresholds -------------------------------------------------------------
VERTEX_ROUND_DP = 4          # vertices this close (1e-4 mm) are the same point
DEGENERATE_AREA = 1e-9       # a triangle with less cross-product magnitude has no area
BED_TOLERANCE_MM = 0.05      # a triangle within this of the lowest Z lies on the bed
ON_BED_TOLERANCE_MM = 0.01   # a part whose lowest point is further off Z=0 is floating
MIN_BED_CONTACT_SHARE = 0.10  # less contact than this share of the footprint is a balance act
STALE_SLACK_S = 1            # filesystem mtime granularity when comparing STL vs .scad

# RC522 coupon ray-cast. The channel is probed part-way up the slot, from just outside
# the part, and the per-side clearance must land in a window that a real board slides
# into without rattling.
SLOT_PROBE_HEIGHT = 0.38     # fraction of the coupon height: mid-slot
RAY_START_OFFSET_MM = 5      # rays start this far outside the bounding box
RAY_EPS = 1e-9               # Moller-Trumbore parallel / edge tolerance
RAY_MIN_T = 1e-7             # ignore hits at the ray origin
CHANNEL_CLEARANCE_MM = (0.2, 1.2)    # per side, across the 39 mm board width
INSERTION_CLEARANCE_MM = (0.2, 1.5)  # per side, along the 60 mm board length

R, Y, G, DIM, B0 = "\033[31m", "\033[33m", "\033[32m", "\033[2m", "\033[0m"
fails, warns = [], []


def bad(m):
    """Report a blocker and remember it for the summary."""
    fails.append(m)
    print(f"  {R}FAIL{B0}  {m}")


def warn(m):
    """Report a warning and remember it for the summary."""
    warns.append(m)
    print(f"  {Y}WARN{B0}  {m}")


def ok(m):
    """Report a passing check."""
    print(f"  {G}ok{B0}    {m}")


def note(m):
    """Report context that is neither a pass nor a problem."""
    print(f"  {DIM}note{B0}  {m}")


def load(path):
    """Parse an ASCII or binary STL file.

    Returns:
        list of triangles, each a tuple of three (x, y, z) vertices.
    """
    with open(path, "rb") as f:
        head = f.read(512)
    if head.lstrip()[:5] == b"solid" and b"facet" in head:
        tris, v = [], []
        with open(path, errors="ignore") as f:
            for ln in f:
                ln = ln.strip()
                if ln.startswith("vertex"):
                    v.append(tuple(float(x) for x in ln.split()[1:4]))
                    if len(v) == 3:
                        tris.append(tuple(v))
                        v = []
        return tris
    with open(path, "rb") as f:
        f.seek(80)                      # binary STL: 80-byte header, then a count
        (n,) = struct.unpack("<I", f.read(4))
        tris = []
        for _ in range(n):
            d = struct.unpack("<12fH", f.read(50))   # normal, 3 vertices, attribute
            tris.append((d[3:6], d[6:9], d[9:12]))
        return tris


def bbox(T):
    """Axis-aligned bounds of triangles T as (xmin, xmax, ymin, ymax, zmin, zmax)."""
    xs = [p[0] for t in T for p in t]
    ys = [p[1] for t in T for p in t]
    zs = [p[2] for t in T for p in t]
    return (min(xs), max(xs), min(ys), max(ys), min(zs), max(zs))


def _vertex_key(p):
    """A hashable vertex, rounded so coincident vertices from two triangles match."""
    return tuple(round(c, VERTEX_ROUND_DP) for c in p)


def _signed_volume(a, b, c):
    """Signed volume of the tetrahedron (origin, a, b, c); sums to a closed mesh's volume."""
    return (a[0]*(b[1]*c[2]-b[2]*c[1]) + b[0]*(c[1]*a[2]-c[2]*a[1])
            + c[0]*(a[1]*b[2]-a[2]*b[1])) / 6.0


def _shell_roots(T):
    """Group vertices into connected shells with union-find.

    Returns:
        find: callable(vertex key) -> the shell's root key.
        parent: the union-find table (its keys are every vertex in T).
    """
    parent = {}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]   # path halving
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for (a, b, c) in T:
        ka, kb, kc = _vertex_key(a), _vertex_key(b), _vertex_key(c)
        for k in (ka, kb, kc):
            parent.setdefault(k, k)
        union(ka, kb)
        union(kb, kc)
    return find, parent


def mesh_report(T):
    """Mesh health of triangles T.

    Returns:
        dict: shells (connected surfaces), nonmanifold (edges not shared by exactly
        two triangles), degenerate (zero-area triangles), volume (cm^3).
    """
    edges = defaultdict(int)
    degen = 0
    vol = 0.0
    find, parent = _shell_roots(T)
    for (a, b, c) in T:
        ka, kb, kc = _vertex_key(a), _vertex_key(b), _vertex_key(c)
        u = [b[i] - a[i] for i in range(3)]
        v = [c[i] - a[i] for i in range(3)]
        cr = (u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0])
        if math.sqrt(sum(x*x for x in cr)) < DEGENERATE_AREA:
            degen += 1
        vol += _signed_volume(a, b, c)
        for e in ((ka, kb), (kb, kc), (kc, ka)):
            edges[tuple(sorted(e))] += 1
    shells = len({find(k) for k in parent})
    nonman = sum(1 for c in edges.values() if c != 2)
    return dict(shells=shells, nonmanifold=nonman, degenerate=degen, volume=vol/1000.0)


# The orientation each part is printed in, per the print package instructions. Bed contact measured
# in the as-exported pose is meaningless for parts that are flipped or stood up in the slicer --
# that is why the base read 4.2% when its real printed contact is ~98%.
PRINT_POSE = {
    "base":            ("flip_x", "flip 180 about X, deck on the bed"),
    "reader_coupon":   ("flip_x", "flip 180 about X, deck on the bed"),
    "lcd_frame":       ("tip_x",  "rotate +90 about X, bezel face down"),
}


def reorient(T, how):
    """Rotate triangles T into a print pose and drop them onto Z = 0.

    Args:
        T: triangles.
        how: "flip_x" (180 degrees about X) or "tip_x" (+90 degrees about X); anything
            else returns T unchanged.
    """
    if how == "flip_x":
        def f(p):
            return (p[0], -p[1], -p[2])
    # +90 about X. -90 was recorded here and is wrong: it stands the frame on its hollow
    # back for 1037mm2 of contact on a 73mm-tall part. Bezel face down is 4584mm2, same time.
    elif how == "tip_x":
        def f(p):
            return (p[0], -p[2], p[1])
    else:
        return T
    T2 = [tuple(f(v) for v in t) for t in T]
    zmin = min(v[2] for t in T2 for v in t)
    return [tuple((v[0], v[1], v[2] - zmin) for v in t) for t in T2]


def islands(T):
    """Solid shells floating free of the main body.

    Returns:
        list of (triangle count, bbox) for every positive-volume shell except the
        largest one.
    """
    find, _ = _shell_roots(T)
    groups = defaultdict(list)
    for t in T:
        groups[find(_vertex_key(t[0]))].append(t)
    out = []
    for tris in groups.values():
        pts = [v for t in tris for v in t]
        # Signed volume: outward-oriented shells are solid bodies, inward-oriented ones are
        # enclosed cavities (a hollow interior is legitimately its own connected surface).
        sv = sum(_signed_volume(a, b, c) for (a, b, c) in tris)
        out.append((len(tris), (min(q[0] for q in pts), max(q[0] for q in pts),
                                min(q[1] for q in pts), max(q[1] for q in pts),
                                min(q[2] for q in pts), max(q[2] for q in pts)), sv))
    out.sort(key=lambda r: abs(r[2]), reverse=True)
    # Drop the main body, then keep only positive-volume (solid) shells -- those are the
    # ones the slicer would try to print floating in mid-air.
    return [(n, bb) for (n, bb, sv) in out[1:] if sv > 0]


def bed_contact(T, tol=BED_TOLERANCE_MM):
    """Area of the triangles lying in the lowest Z plane.

    Returns:
        (area in mm^2, the lowest Z).
    """
    zmin = min(p[2] for t in T for p in t)
    area = 0.0
    for (a, b, c) in T:
        if all(abs(p[2] - zmin) < tol for p in (a, b, c)):
            area += abs((b[0]-a[0])*(c[1]-a[1]) - (c[0]-a[0])*(b[1]-a[1])) / 2
    return area, zmin


def _md5(path):
    """MD5 of a file's bytes (identity check only, not security)."""
    with open(path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


def stale():
    """Report STL exports older than their source, and print-package copies that drifted."""
    print(f"\n{DIM}-- freshness --{B0}")
    if not os.path.exists(SCAD):
        return bad("tasklot_base.scad missing")
    src = max(os.path.getmtime(SCAD), os.path.getmtime(PARAMS))
    for p in PARTS:
        s = STL_OF[p]
        if not os.path.exists(s):
            warn(f"{p}: no export")
            continue
        if os.path.getmtime(s) < src - STALE_SLACK_S:
            bad(f"{p}: STL is OLDER than the .scad -- re-export before printing")
        else:
            ok(f"{p}: export current")
    for root, _, files in os.walk(PKG):
        for f in files:
            if not f.endswith(".stl"):
                continue
            a = os.path.join(root, f)
            b = os.path.join(EXPORTS, f)
            if not os.path.exists(b):
                warn(f"{f}: in print-package/ but not exports/")
                continue
            same = _md5(a) == _md5(b)
            (ok if same else bad)(
                f"print-package/{f}: " + ("matches exports/" if same else "STALE vs exports/ -- recopy"))


def _ray_hits(T, o, d):
    """Distances along ray o + t*d at which it crosses triangles T (Moller-Trumbore).

    Returns:
        sorted list of t > RAY_MIN_T.
    """
    hits = []
    for (a, b, c) in T:
        e1 = [b[i]-a[i] for i in range(3)]
        e2 = [c[i]-a[i] for i in range(3)]
        pv = [d[1]*e2[2]-d[2]*e2[1], d[2]*e2[0]-d[0]*e2[2], d[0]*e2[1]-d[1]*e2[0]]
        det = sum(e1[i]*pv[i] for i in range(3))
        if abs(det) < RAY_EPS:
            continue
        inv = 1/det
        tv = [o[i]-a[i] for i in range(3)]
        u = sum(tv[i]*pv[i] for i in range(3))*inv
        if u < -RAY_EPS or u > 1+RAY_EPS:
            continue
        qv = [tv[1]*e1[2]-tv[2]*e1[1], tv[2]*e1[0]-tv[0]*e1[2], tv[0]*e1[1]-tv[1]*e1[0]]
        vv = sum(d[i]*qv[i] for i in range(3))*inv
        if vv < -RAY_EPS or u+vv > 1+RAY_EPS:
            continue
        t = sum(e2[i]*qv[i] for i in range(3))*inv
        if t > RAY_MIN_T:
            hits.append(t)
    return sorted(hits)


def clearances():
    """Ray-cast the exported reader coupon and check the RC522 channel width and depth."""
    print(f"\n{DIM}-- RC522 fit (ray-cast on the exported coupon) --{B0}")
    s = STL_OF["reader_coupon"]
    if not os.path.exists(s):
        return warn("no coupon export")
    T = load(s)
    x0, x1, y0, y1, z0, z1 = bbox(T)
    bw, bl, _bt = HARDWARE["rc522"]["dims"]
    zp = z0 + (z1 - z0) * SLOT_PROBE_HEIGHT
    cx, cy = (x0+x1)/2, (y0+y1)/2
    off = RAY_START_OFFSET_MM
    # Hit positions in part coordinates: across the channel (Y), and into it (X).
    hy = [v + y0 - off for v in _ray_hits(T, [cx, y0-off, zp], [0, 1, 0])]
    hx = [v + x0 - off for v in _ray_hits(T, [x0-off, cy, zp], [1, 0, 0])]

    lo, hi = CHANNEL_CLEARANCE_MM
    if len(hy) >= 4:
        # Outer wall, channel wall, channel wall, outer wall: the channel is hits 1..2.
        chan = hy[2] - hy[1]
        per = (chan - bw) / 2
        (ok if lo <= per <= hi else bad)(
            f"channel {chan:.2f}mm vs {bw}mm board = {per:+.2f}mm/side "
            f"({'good' if lo <= per <= hi else f'BAD -- needs {lo}-{hi}mm/side'})")
    else:
        warn(f"channel: unexpected ray pattern {[f'{v:.1f}' for v in hy]}")

    # Insertion depth = open end -> backstop face.
    lo, hi = INSERTION_CLEARANCE_MM
    if hx:
        start = hy[1] if len(hy) > 1 else x0
        ins = hx[0] - start
        per = (ins - bl) / 2
        (ok if lo <= per <= hi else bad)(
            f"insertion {ins:.2f}mm vs {bl}mm board = {per:+.2f}mm/side "
            f"({'good' if lo <= per <= hi else 'BAD'})")
    for k, h in HARDWARE.items():
        if not h["verified"]:
            warn(f"{k}: dimensions UNVERIFIED -- {h['note']}")


def geometry():
    """Check every exported part's mesh, islands, bed placement, contact, and printer fit."""
    print(f"\n{DIM}-- mesh + bed --{B0}")
    for p in PARTS:
        s = STL_OF[p]
        if not os.path.exists(s):
            continue
        T = load(s)
        x0, x1, y0, y1, z0, z1 = bbox(T)
        w, d, h = x1-x0, y1-y0, z1-z0
        m = mesh_report(T)
        how, how_txt = PRINT_POSE.get(p, (None, None))
        area, zmin = bed_contact(reorient(T, how) if how else T)
        print(f"\n  {p}  {w:.1f} x {d:.1f} x {h:.1f} mm   {m['volume']:.1f} cm3")
        if m["nonmanifold"] or m["degenerate"]:
            bad(f"{p}: {m['nonmanifold']} non-manifold edges, {m['degenerate']} degenerate tris")
        else:
            ok(f"{p}: watertight")
        # A multi-shell export is almost always loose geometry floating in mid-air, which the
        # slicer will try to print on nothing. v2 shipped 7 such cubes in the base and a sign
        # island in the restaurant body, and this check reported "watertight (8 shells)" as OK.
        plate = PLATES.get(p, 1)
        isl = islands(T)
        if len(isl) > plate - 1:
            bad(f"{p}: {len(isl)} solid island(s) floating free of the main body "
                f"({m['shells']} shells total)")
            for (n, bb) in isl[:6]:
                bad(f"    island {n} tris  x[{bb[0]:.1f},{bb[1]:.1f}] "
                    f"y[{bb[2]:.1f},{bb[3]:.1f}] z[{bb[4]:.1f},{bb[5]:.1f}]")
        elif plate > 1:
            ok(f"{p}: plate of {plate} separate objects, as intended")
        else:
            ok(f"{p}: single connected body")
        if how:
            note(f"{p}: measured as printed -- {how_txt}")
        elif abs(zmin) > ON_BED_TOLERANCE_MM:
            warn(f"{p}: sits at Z={zmin:.2f}, not on the bed -- sink/drop it in the slicer")
        foot = w * d
        if area < foot * MIN_BED_CONTACT_SHARE:
            bad(f"{p}: bed contact only {area:.0f}mm2 of a {foot:.0f}mm2 footprint "
                f"({area/foot*100:.1f}%) -- REORIENT, it is balancing on a feature")
        else:
            ok(f"{p}: bed contact {area:.0f}mm2 ({area/foot*100:.0f}% of footprint)")
        fits = [n for n, (bx, by, bz) in PRINTERS.items() if w <= bx and d <= by and h <= bz]
        if not fits:
            bad(f"{p}: FITS NO KNOWN PRINTER")
        elif SELF_SERVE_PRINTER not in fits:
            warn(f"{p}: needs {', '.join(fits)} -- not printable self-serve today")
        else:
            ok(f"{p}: fits {len(fits)} printer(s) incl. self-serve MK3S")


def renders(todo):
    """Render each part in `todo` from above and below to renders/ (needs OpenSCAD)."""
    print(f"\n{DIM}-- renders --{B0}")
    if not OPENSCAD:
        return warn("OpenSCAD not installed -- brew install --cask openscad")
    out = os.path.join(CAD, "renders")
    os.makedirs(out, exist_ok=True)
    for p in todo:
        # The channels, lips and pockets are all on undersides, hence the "under" view.
        for tag, cam in (("iso", "0,0,0,60,0,35,0"), ("under", "0,0,0,235,0,35,0")):
            subprocess.run([OPENSCAD, "-o", f"{out}/{p}-{tag}.png", "-D", f'part="{p}"',
                            f"--camera={cam}", "--viewall", "--autocenter",
                            "--imgsize=1200,900", "--projection=ortho", SCAD],
                           capture_output=True)
    ok(f"rendered {len(todo)} part(s) x2 views -> renders/  ** NOW LOOK AT THEM **")


def main(argv):
    """Run every check and print a summary.

    Args:
        argv: part names to render (all parts plus the assembly when empty).

    Returns:
        int: 1 if any check failed, else 0.
    """
    print(f"\n{DIM}TaskLot pre-print audit{B0}")
    stale()
    geometry()
    clearances()
    renders(argv or PARTS + ["assembly"])
    print(f"\n{'='*58}")
    if fails:
        print(f"{R}{len(fails)} BLOCKER(S) -- do not print{B0}")
        for f in fails:
            print(f"  - {f}")
    elif warns:
        print(f"{Y}no blockers, {len(warns)} warning(s){B0}")
    else:
        print(f"{G}clean{B0}")
    print(f"{DIM}Renders are NOT checked by this script. Open renders/ and look.{B0}\n")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

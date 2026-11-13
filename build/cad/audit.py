#!/usr/bin/env python3
"""
TaskLot CAD pre-print audit. Deterministic checks only -- judgment lives in /audit.

    python3 audit.py            # all parts
    python3 audit.py coupon     # one part

Checks: mesh validity, bed fit, bed-contact area, floating/disconnected shells, staleness,
and real-component clearances against MEASURED hardware dimensions.
"""
import os, sys, math, subprocess, hashlib
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
# Anything marked UNVERIFIED is a guess and the audit will say so.
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
PARTS = ["reader_coupon", "lcd_frame", "restaurant", "restaurant_body",
         "restaurant_roof", "restaurant_sign", "base", "bottom_panel"]
# restaurant_body/roof/sign are the parts the print package actually sends to the printer.
# They were absent from this list, so the two printed parts were the only two never checked.
STL_OF = {p: os.path.join(EXPORTS, "tasklot-" + p.replace("_", "-") + ".stl") for p in PARTS}

R, Y, G, DIM, B0 = "\033[31m", "\033[33m", "\033[32m", "\033[2m", "\033[0m"
fails, warns = [], []
def bad(m):  fails.append(m); print(f"  {R}FAIL{B0}  {m}")
def warn(m): warns.append(m); print(f"  {Y}WARN{B0}  {m}")
def ok(m):   print(f"  {G}ok{B0}    {m}")
def note(m): print(f"  {DIM}note{B0}  {m}")


def load(path):
    """Parse ASCII or binary STL -> list of triangles."""
    with open(path, "rb") as f:
        head = f.read(512)
    if head.lstrip()[:5] == b"solid" and b"facet" in head:
        tris, v = [], []
        for ln in open(path, errors="ignore"):
            ln = ln.strip()
            if ln.startswith("vertex"):
                v.append(tuple(float(x) for x in ln.split()[1:4]))
                if len(v) == 3:
                    tris.append(tuple(v)); v = []
        return tris
    import struct
    with open(path, "rb") as f:
        f.seek(80); (n,) = struct.unpack("<I", f.read(4)); tris = []
        for _ in range(n):
            d = struct.unpack("<12fH", f.read(50))
            tris.append((d[3:6], d[6:9], d[9:12]))
        return tris


def bbox(T):
    xs = [p[0] for t in T for p in t]; ys = [p[1] for t in T for p in t]; zs = [p[2] for t in T for p in t]
    return (min(xs), max(xs), min(ys), max(ys), min(zs), max(zs))


def mesh_report(T):
    """manifold / degenerate / shells / volume"""
    edges = defaultdict(int); degen = 0; vol = 0.0
    key = lambda p: (round(p[0], 4), round(p[1], 4), round(p[2], 4))
    parent = {}
    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]; a = parent[a]
        return a
    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb: parent[ra] = rb
    for (a, b, c) in T:
        ka, kb, kc = key(a), key(b), key(c)
        for k in (ka, kb, kc): parent.setdefault(k, k)
        union(ka, kb); union(kb, kc)
        u = [b[i] - a[i] for i in range(3)]; v = [c[i] - a[i] for i in range(3)]
        cr = (u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0])
        if math.sqrt(sum(x*x for x in cr)) < 1e-9: degen += 1
        vol += (a[0]*(b[1]*c[2]-b[2]*c[1]) + b[0]*(c[1]*a[2]-c[2]*a[1]) + c[0]*(a[1]*b[2]-a[2]*b[1])) / 6.0
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
    if how == "flip_x":   f = lambda p: (p[0], -p[1], -p[2])
    # +90 about X. -90 was recorded here and is wrong: it stands the frame on its hollow
    # back for 1037mm2 of contact on a 73mm-tall part. Bezel face down is 4584mm2, same time.
    elif how == "tip_x":  f = lambda p: (p[0], -p[2],  p[1])
    else:                 return T
    T2 = [tuple(f(v) for v in t) for t in T]
    zmin = min(v[2] for t in T2 for v in t)
    return [tuple((v[0], v[1], v[2] - zmin) for v in t) for t in T2]


def islands(T):
    """Every connected shell except the largest, as (triangle count, bbox)."""
    key = lambda p: (round(p[0], 4), round(p[1], 4), round(p[2], 4))
    parent = {}
    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]; a = parent[a]
        return a
    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb: parent[ra] = rb
    for (a, b, c) in T:
        ka, kb, kc = key(a), key(b), key(c)
        for k in (ka, kb, kc): parent.setdefault(k, k)
        union(ka, kb); union(kb, kc)
    groups = defaultdict(list)
    for t in T: groups[find(key(t[0]))].append(t)
    out = []
    for tris in groups.values():
        pts = [v for t in tris for v in t]
        # Signed volume: outward-oriented shells are solid bodies, inward-oriented ones are
        # enclosed cavities (a hollow interior is legitimately its own connected surface).
        sv = 0.0
        for (a, b, c) in tris:
            sv += (a[0]*(b[1]*c[2]-b[2]*c[1]) + b[0]*(c[1]*a[2]-c[2]*a[1])
                   + c[0]*(a[1]*b[2]-a[2]*b[1])) / 6.0
        out.append((len(tris), (min(q[0] for q in pts), max(q[0] for q in pts),
                                min(q[1] for q in pts), max(q[1] for q in pts),
                                min(q[2] for q in pts), max(q[2] for q in pts)), sv))
    out.sort(key=lambda r: abs(r[2]), reverse=True)
    # Drop the main body, then keep only positive-volume (solid) shells -- those are the
    # ones the slicer would try to print floating in mid-air.
    return [(n, bb) for (n, bb, sv) in out[1:] if sv > 0]


def bed_contact(T, tol=0.05):
    """Area of triangles lying in the lowest Z plane."""
    zmin = min(p[2] for t in T for p in t); area = 0.0
    for (a, b, c) in T:
        if all(abs(p[2] - zmin) < tol for p in (a, b, c)):
            area += abs((b[0]-a[0])*(c[1]-a[1]) - (c[0]-a[0])*(b[1]-a[1])) / 2
    return area, zmin


def stale():
    print(f"\n{DIM}-- freshness --{B0}")
    if not os.path.exists(SCAD): return bad("tasklot_base.scad missing")
    src = max(os.path.getmtime(SCAD), os.path.getmtime(PARAMS))
    for p in PARTS:
        s = STL_OF[p]
        if not os.path.exists(s): warn(f"{p}: no export"); continue
        if os.path.getmtime(s) < src - 1:
            bad(f"{p}: STL is OLDER than the .scad -- re-export before printing")
        else:
            ok(f"{p}: export current")
    for root, _, files in os.walk(PKG):
        for f in files:
            if not f.endswith(".stl"): continue
            a = os.path.join(root, f); b = os.path.join(EXPORTS, f)
            if not os.path.exists(b): warn(f"{f}: in print-package/ but not exports/"); continue
            ha = hashlib.md5(open(a, 'rb').read()).hexdigest()
            hb = hashlib.md5(open(b, 'rb').read()).hexdigest()
            (ok if ha == hb else bad)(
                f"print-package/{f}: " + ("matches exports/" if ha == hb else "STALE vs exports/ -- recopy"))


def clearances():
    """Ray-cast the coupon to measure the real PCB channel."""
    print(f"\n{DIM}-- RC522 fit (ray-cast on the exported coupon) --{B0}")
    s = STL_OF["reader_coupon"]
    if not os.path.exists(s): return warn("no coupon export")
    T = load(s); x0, x1, y0, y1, z0, z1 = bbox(T)
    bw, bl, bt = HARDWARE["rc522"]["dims"]
    zp = z0 + (z1 - z0) * 0.38                       # mid-slot
    def cross(o, d):
        hits = []
        for (a, b, c) in T:
            e1 = [b[i]-a[i] for i in range(3)]; e2 = [c[i]-a[i] for i in range(3)]
            pv = [d[1]*e2[2]-d[2]*e2[1], d[2]*e2[0]-d[0]*e2[2], d[0]*e2[1]-d[1]*e2[0]]
            det = sum(e1[i]*pv[i] for i in range(3))
            if abs(det) < 1e-9: continue
            inv = 1/det; tv = [o[i]-a[i] for i in range(3)]
            u = sum(tv[i]*pv[i] for i in range(3))*inv
            if u < -1e-9 or u > 1+1e-9: continue
            qv = [tv[1]*e1[2]-tv[2]*e1[1], tv[2]*e1[0]-tv[0]*e1[2], tv[0]*e1[1]-tv[1]*e1[0]]
            vv = sum(d[i]*qv[i] for i in range(3))*inv
            if vv < -1e-9 or u+vv > 1+1e-9: continue
            t = sum(e2[i]*qv[i] for i in range(3))*inv
            if t > 1e-7: hits.append(t)
        return sorted(hits)
    cx, cy = (x0+x1)/2, (y0+y1)/2
    hy = [v + y0 - 5 for v in cross([cx, y0-5, zp], [0, 1, 0])]
    hx = [v + x0 - 5 for v in cross([x0-5, cy, zp], [1, 0, 0])]
    if len(hy) >= 4:
        chan = hy[2] - hy[1]
        per = (chan - bw) / 2
        (ok if 0.2 <= per <= 1.2 else bad)(
            f"channel {chan:.2f}mm vs {bw}mm board = {per:+.2f}mm/side "
            f"({'good' if 0.2 <= per <= 1.2 else 'BAD -- needs 0.2-1.2mm/side'})")
    else:
        warn(f"channel: unexpected ray pattern {[f'{v:.1f}' for v in hy]}")
    if hx:
        depth = hx[0] - (y0 and x0 + (hy[1]-y0 if len(hy) > 1 else 0)) if False else None
    if len(hx) >= 1 and len(hy) >= 2:
        depth = hx[0] - hy[1] if False else None
    # insertion depth = open end -> backstop face
    if hx:
        ins = hx[0] - (x0 + 8.5 - x0) - x0 if False else hx[0] - (hy[1] if len(hy) > 1 else x0)
    if len(hx) >= 1:
        start = hy[1] if len(hy) > 1 else x0
        ins = hx[0] - start
        per = (ins - bl) / 2
        (ok if 0.2 <= per <= 1.5 else bad)(
            f"insertion {ins:.2f}mm vs {bl}mm board = {per:+.2f}mm/side "
            f"({'good' if 0.2 <= per <= 1.5 else 'BAD'})")
    for k, h in HARDWARE.items():
        if not h["verified"]:
            warn(f"{k}: dimensions UNVERIFIED -- {h['note']}")


def geometry():
    print(f"\n{DIM}-- mesh + bed --{B0}")
    for p in PARTS:
        s = STL_OF[p]
        if not os.path.exists(s): continue
        T = load(s); x0, x1, y0, y1, z0, z1 = bbox(T)
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
        # Some exports are intentionally a PLATE of several loose objects (the sign and its
        # two posts). Those are fine; anything else with a floating solid is not.
        plate = {"restaurant_sign": 3}.get(p, 1)
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
        elif abs(zmin) > 0.01:
            warn(f"{p}: sits at Z={zmin:.2f}, not on the bed -- sink/drop it in the slicer")
        foot = w * d
        if area < foot * 0.10:
            bad(f"{p}: bed contact only {area:.0f}mm2 of a {foot:.0f}mm2 footprint "
                f"({area/foot*100:.1f}%) -- REORIENT, it is balancing on a feature")
        else:
            ok(f"{p}: bed contact {area:.0f}mm2 ({area/foot*100:.0f}% of footprint)")
        fits = [n for n, (bx, by, bz) in PRINTERS.items() if w <= bx and d <= by and h <= bz]
        if not fits:
            bad(f"{p}: FITS NO KNOWN PRINTER")
        elif "MK3S (self-serve)" not in fits:
            warn(f"{p}: needs {', '.join(fits)} -- not printable self-serve today")
        else:
            ok(f"{p}: fits {len(fits)} printer(s) incl. self-serve MK3S")


def renders():
    print(f"\n{DIM}-- renders --{B0}")
    if not OPENSCAD: return warn("OpenSCAD not installed -- brew install --cask openscad")
    out = os.path.join(CAD, "renders"); os.makedirs(out, exist_ok=True)
    todo = sys.argv[1:] or PARTS + ["assembly"]
    for p in todo:
        for tag, cam in (("iso", "0,0,0,60,0,35,0"), ("under", "0,0,0,235,0,35,0")):
            subprocess.run([OPENSCAD, "-o", f"{out}/{p}-{tag}.png", "-D", f'part="{p}"',
                            f"--camera={cam}", "--viewall", "--autocenter",
                            "--imgsize=1200,900", "--projection=ortho", SCAD],
                           capture_output=True)
    ok(f"rendered {len(todo)} part(s) x2 views -> renders/  ** NOW LOOK AT THEM **")


if __name__ == "__main__":
    print(f"\n{DIM}TaskLot pre-print audit{B0}")
    stale(); geometry(); clearances(); renders()
    print(f"\n{'='*58}")
    if fails:
        print(f"{R}{len(fails)} BLOCKER(S) -- do not print{B0}")
        for f in fails: print(f"  - {f}")
    elif warns:
        print(f"{Y}no blockers, {len(warns)} warning(s){B0}")
    else:
        print(f"{G}clean{B0}")
    print(f"{DIM}Renders are NOT checked by this script. Open renders/ and look.{B0}\n")
    sys.exit(1 if fails else 0)

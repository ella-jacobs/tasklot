#!/usr/bin/env python3
"""Draw the README's LCD storyboard from the firmware's golden transcripts.

    python3 docs/make_lcd_frames.py

firmware/tests/golden/*.txt record everything the real sketch printed and showed
on the LCD at each step of a scripted session; the firmware host tests replay the
sketch against fake hardware and diff its output against them. This script picks
one LCD frame per gesture from those files and writes them as an SVG storyboard
to docs/images/lcd-frames.svg, so the picture in the README is the firmware's own
output rather than a mock-up. Run it again after re-recording the golden files.

Standard library only. Exits with a message if a chosen step is missing.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from xml.sax.saxutils import escape

REPO = Path(__file__).resolve().parent.parent
GOLDEN = REPO / "firmware" / "tests" / "golden"
OUT = REPO / "docs" / "images" / "lcd-frames.svg"

# (golden file, step title in that file, caption, sub-caption). One frame per gesture,
# in the order a task lives through them.
FRAMES = [
    ("order_flow", "blank car 1 at the speaker", "1. Blank car at the speaker", "the laptop starts recording"),
    ("order_flow", "park car 1 on space 1: order closes", "2. Park it", "parking is the stop gesture"),
    ("order_flow", "laptop sends the label", "3. The label arrives", "space 1 is the top priority"),
    # From another recorded session, so the task differs from frames 1-3.
    ("readback", "laptop sends the full text", "4. Loaded car at the speaker", "another car's task, 3 rows a page"),
    ("pickup", "carry car 1 from space 1 to pickup", "5. Through the pickup lane", "done; the car is blank again"),
]
FRAMES_PER_ROW = 3

LCD_COLS, LCD_ROWS = 20, 4
STEP = re.compile(r"^-- (.*) \(t=\d+\)$")      # "-- park car 1 on space 1 (t=3960)"
LCD_ROW = re.compile(r"^  \|(.{%d})\|$" % LCD_COLS)  # "  |1>Email the Prof    |"

# Geometry, in SVG user units (px).
CHAR_W, ROW_H, FONT_SIZE = 9.6, 22, 15   # one 15 px monospace cell, slightly letter-spaced
BASELINE_RAISE = 6                       # baseline sits this far above the row's bottom
GLASS_PAD, BEZEL = 12, 10
GLASS_W = LCD_COLS * CHAR_W + 2 * GLASS_PAD
GLASS_H = LCD_ROWS * ROW_H + 2 * GLASS_PAD
FRAME_W, FRAME_H = GLASS_W + 2 * BEZEL, GLASS_H + 2 * BEZEL
GAP_X, CAPTION_H, GAP_Y, MARGIN = 28, 46, 22, 24

# The simulator's LCD colours (tools/sim), on a light card so the strip reads in
# GitHub's light and dark themes alike.
CARD, BEZEL_FILL, GLASS_FILL, PIXEL = "#F3F4F6", "#22242A", "#0B2E6B", "#EAF4FF"
INK, MUTED = "#1A1A1A", "#5A5346"
MONO = "'Space Mono', Menlo, Consolas, 'DejaVu Sans Mono', monospace"
SANS = "Inter, -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif"


def lcd_frames(path: Path) -> dict[str, list[str]]:
    """The LCD as it stood at the end of each step of one golden transcript.

    Args:
        path: a firmware/tests/golden/*.txt file.

    Returns:
        dict: step title -> four 20-character rows, for every step that redrew the LCD.
    """
    frames: dict[str, list[str]] = {}
    title, rows = None, []
    for line in path.read_text(encoding="ascii").splitlines():
        step = STEP.match(line)
        if step:
            title, rows = step.group(1), []
            continue
        row = LCD_ROW.match(line)
        if row and title is not None:
            rows.append(row.group(1))
            if len(rows) == LCD_ROWS:   # a step may redraw more than once; keep the last
                frames[title], rows = rows, []
    return frames


def frame_svg(x: float, y: float, rows: list[str], caption: str, sub: str) -> str:
    """One LCD frame with its caption, as SVG elements, top-left corner at (x, y)."""
    gx, gy = x + BEZEL, y + BEZEL
    parts = [
        f'<rect x="{x:g}" y="{y:g}" width="{FRAME_W:g}" height="{FRAME_H:g}" rx="8" fill="{BEZEL_FILL}"/>',
        f'<rect x="{gx:g}" y="{gy:g}" width="{GLASS_W:g}" height="{GLASS_H:g}" rx="3" fill="{GLASS_FILL}"/>',
    ]
    for i, row in enumerate(rows):
        baseline = gy + GLASS_PAD + (i + 1) * ROW_H - BASELINE_RAISE
        # textLength pins the row to exactly 20 character cells whatever monospace
        # font the viewer has, so the columns line up as they do on the glass.
        parts.append(f'<text x="{gx + GLASS_PAD:g}" y="{baseline:g}" textLength="{LCD_COLS * CHAR_W:g}" '
                     f'lengthAdjust="spacing" xml:space="preserve">{escape(row)}</text>')
    cx = x + FRAME_W / 2
    parts.append(f'<text x="{cx:g}" y="{y + FRAME_H + 20:g}" class="cap">{escape(caption)}</text>')
    parts.append(f'<text x="{cx:g}" y="{y + FRAME_H + 38:g}" class="sub">{escape(sub)}</text>')
    return "\n  ".join(parts)


def storyboard(frames: list[tuple[list[str], str, str]]) -> str:
    """The whole SVG: frames in rows of FRAMES_PER_ROW, the last row centred."""
    rows = [frames[i:i + FRAMES_PER_ROW] for i in range(0, len(frames), FRAMES_PER_ROW)]
    width = 2 * MARGIN + FRAMES_PER_ROW * FRAME_W + (FRAMES_PER_ROW - 1) * GAP_X
    height = 2 * MARGIN + len(rows) * (FRAME_H + CAPTION_H) + (len(rows) - 1) * GAP_Y
    body = []
    for r, row in enumerate(rows):
        row_w = len(row) * FRAME_W + (len(row) - 1) * GAP_X
        x0 = (width - row_w) / 2
        y = MARGIN + r * (FRAME_H + CAPTION_H + GAP_Y)
        for c, (lcd, caption, sub) in enumerate(row):
            body.append(frame_svg(x0 + c * (FRAME_W + GAP_X), y, lcd, caption, sub))
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" height="{height:.0f}" viewBox="0 0 {width:.0f} {height:.0f}">
  <title>TaskLot LCD, one frame per gesture, from the firmware golden transcripts</title>
  <style>
    text {{ font-family: {MONO}; font-size: {FONT_SIZE}px; fill: {PIXEL}; }}
    text.cap {{ font-family: {SANS}; font-size: 14px; font-weight: 700; fill: {INK}; text-anchor: middle; }}
    text.sub {{ font-family: {SANS}; font-size: 12.5px; fill: {MUTED}; text-anchor: middle; }}
  </style>
  <rect width="100%" height="100%" rx="12" fill="{CARD}"/>
  {(chr(10) + "  ").join(body)}
</svg>
"""


def main() -> int:
    """Read the golden files, write docs/images/lcd-frames.svg, return the exit status."""
    cache: dict[str, dict[str, list[str]]] = {}
    chosen = []
    for name, step, caption, sub in FRAMES:
        if name not in cache:
            cache[name] = lcd_frames(GOLDEN / f"{name}.txt")
        rows = cache[name].get(step)
        if rows is None:
            print(f"golden/{name}.txt has no LCD frame for step {step!r}", file=sys.stderr)
            return 1
        chosen.append((rows, caption, sub))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(storyboard(chosen), encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO)} ({len(chosen)} frames)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

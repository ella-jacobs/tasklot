# tools/sim — TaskLot in a browser, with no hardware

`tasklot-sim.html` is a single self-contained page that simulates the parking lot:
drag cars onto the four spaces, the speaker, and the pickup lane, and watch the LCD panel
update. It follows the board's interaction rules (order at the speaker, park to finish,
read back, collect at the pickup lane), and its task text comes from an inlined copy of
`tools/voice/condense.js`. Its serial log uses the event lines of
`firmware/history/tasklot_full`; the differences from the v2 protocol are listed in
`DESIGN.md` (section 3 and edge case E-30).

Open it in Chrome or Edge:

```bash
open tools/sim/tasklot-sim.html
```

Typing a task works everywhere. Dictation uses the browser's speech recognition, which
needs an `https` origin, so it does not work from `file://`.

With a board attached over USB, the page can also connect over Web Serial and follow the
real readers (Chrome or Edge only; close the Arduino Serial Monitor first, because only
one program can hold the port).

The inlined condenser is regenerated from `tools/voice/condense.js` with:

```bash
python3 tools/voice/sync_page.py
```

`tools/voice/tests/test_condenser.py` fails if the inlined copy is stale, so `make test` catches it.

What the simulator cannot prove: that the RC522s read through the deck, that six readers
hold up on the shared SPI bus and the 3.3 V rail, or that the LCD contrast is set. Those
are bench checks (see `DESIGN.md`).

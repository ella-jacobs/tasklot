# tools/voice — a spoken task becomes an 18-character LCD label

The laptop half of TaskLot. The Arduino never handles audio: the laptop records,
transcribes, and shortens the task, and only ASCII text travels down the serial line.

```
  mic  ->  ffmpeg  ->  whisper.cpp  ->  clean_transcript()  ->  condense()  ->  CAR n <label>
                                                               (optional LLM label upgrade)
```

| File | What it is |
|---|---|
| `tasklot_ears.py` | The daemon. Holds the serial port, starts/stops recording on board events, transcribes, condenses, and sends the label back. |
| `condense.js` | The canonical rule-based condenser: memo -> `{full, lcd, due, raw}`. Runs in node and in the browser. |
| `condense.py` | A Python port of `condense.js`, checked against the same fixtures. |
| `cases.json` | Shared fixtures for both condensers. |
| `tasklot_voice.py` | Offline CLI: an audio file or typed text -> `tasks.json`, with an optional push to the board. |
| `sync_page.py` | Re-inlines `condense.js` into `tools/sim/tasklot-sim.html`; `--check` reports a stale copy. |
| `test_condense.js`, `test_condense.py` | Run `cases.json` against each condenser. |
| `test_ears_mock.py` | Runs the daemon against a fake board on a pseudo-terminal and checks what it sends. |

## Running

```bash
python3 tools/voice/tasklot_ears.py           # needs pyserial, ffmpeg, whisper-cli
python3 tools/voice/tasklot_voice.py --text "remind me to charge the battery pack tonight" --car 1
```

Environment variables: `TASKLOT_PORT` (serial device), `TASKLOT_WHISPER_MODEL`
(whisper.cpp model path), `TASKLOT_LLM=0` (turn off the LLM label upgrade),
`TASKLOT_LLM_TIMEOUT` (seconds), `TASKLOT_WHISPER_SCRIPT` (transcriber used by
`tasklot_voice.py`).

## Tests

```bash
node tools/voice/test_condense.js
python3 tools/voice/test_condense.py
TASKLOT_LLM=0 python3 tools/voice/test_ears_mock.py    # needs pyserial
```

The full design, the serial protocol, and the edge cases are in `DESIGN.md` at the
repo root.

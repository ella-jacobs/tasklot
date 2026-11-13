# tools/voice: a spoken task becomes an 18-character LCD label

The laptop half of TaskLot. The Arduino never handles audio: the laptop records,
transcribes, and shortens the task, and only ASCII text travels down the serial line.

```
board events ──> SerialLink ──> Ears ──> Recorder (ffmpeg, one WAV per order)
                                  │
                                  └─ Job queue ─> worker thread:
                                       Transcriber (whisper.cpp)
                                       -> TranscriptCleaner (drop "um", [BLANK_AUDIO], greetings)
                                       -> Condenser  ──> "CAR n <18-char label>"  (sent at once)
                                       -> Labeler    ──> "CAR n <better label>"   (optional LLM, guarded)
```

`Lot` is the laptop's model of the cars: each car's full task and the label the board
shows, which car is in which space, and a per-car order id. Every new order and every
pickup bumps the order id, and a transcription or LLM result whose id is no longer
current is dropped, so a car that was collected while its label was being computed is
never re-labelled.

## Running

```bash
cd tools/voice
python3 -m pip install -r requirements.txt   # pyserial, the only dependency
python3 tasklot_ears.py                  # live daemon (needs pyserial, ffmpeg, whisper-cli)
python3 tasklot_voice.py --text "remind me to charge the battery pack tonight" --car 1
python3 condense.py "I need to email the professor by Friday"     # prints the JSON
```

The same commands are available as `python3 -m tasklot ears` and `python3 -m tasklot voice`.
`tasklot_voice.py` keeps its original flags: audio files, `--text`, `--latest-memo`,
`--watch DIR`, `--car N`, `--push --port PORT`, `--clear`.

While the daemon holds the port, two files act as side channels (paths configurable):

```bash
echo "Drive up when you are ready" > /tmp/tasklot_say.txt   # spoken with macOS say
echo CLEAR > /tmp/tasklot_cmd.txt                            # sent to the board
echo RESET > /tmp/tasklot_cmd.txt                            # forget every task, laptop and board
```

Configuration is by environment variable; the full table is at the top of
[`tasklot/config.py`](tasklot/config.py). The common ones: `TASKLOT_PORT`,
`TASKLOT_WHISPER_MODEL`, `TASKLOT_LLM=0` (never call the LLM), `TASKLOT_LLM_TIMEOUT`,
`TASKLOT_WHISPER_SCRIPT` (transcriber for `tasklot_voice.py` audio files),
`TASKLOT_FAKE_TRANSCRIPT` (skip the mic and whisper, for demos and tests).

The optional LLM label upgrade shells out to the `claude` CLI, as the project did. Its
output is checked before use: it is rejected if it shares no word with what was said, or
if it adds a time, day, or number that was never said, and the rule-based label stays.

## Files

| File | What it is |
|---|---|
| `tasklot/config.py` | `Settings` from environment variables; every tunable and why it has its value. |
| `tasklot/protocol.py` | Board events (`parse_line`, anchored patterns) and the exact command strings. |
| `tasklot/serial_link.py` | `SerialLink`: paced writes (the board's RX buffer is 64 bytes), reconnect with backoff. |
| `tasklot/recorder.py` | `Recorder` (ffmpeg, graceful stop escalation) and `NullRecorder`. |
| `tasklot/transcriber.py` | `Transcriber` (whisper.cpp), `ScriptTranscriber` (offline CLI), `FakeTranscriber`. |
| `tasklot/cleaner.py` | `TranscriptCleaner`: whisper noise and filler out. |
| `tasklot/condenser.py` | `Condenser`: memo -> `{full, lcd, due, raw}`, the LCD rows, the read-back line. |
| `tasklot/labeler.py` | `Labeler`: the optional LLM label and its hallucination guards. |
| `tasklot/task.py`, `tasklot/lot.py` | `Task` and `Lot`: the laptop's state, and `tasks.json`. |
| `tasklot/ears.py` | `Ears`: the live daemon that wires it all together. |
| `tasklot/offline.py` | `OfflineTool`: audio or text -> `tasks.json` -> optional push. |
| `tasklot/side_channels.py` | `FileInbox` (the say/command files) and `Speaker` (macOS `say`). |
| `tasklot/cli.py` | Argument parsing for `ears` and `voice`. |
| `condense.js` | The `Condenser` for the browser, rule for rule the same as the Python one. |
| `cases.json` | Shared fixtures both condensers must pass. |
| `sync_page.py` | Re-inlines `condense.js` into `tools/sim/tasklot-sim.html`; `--check` reports a stale copy. |
| `tasklot_ears.py`, `tasklot_voice.py`, `condense.py` | The original commands, now thin entry points. |
| `requirements.txt` | `pyserial`, pinned: needed only to open the serial port. |
| `tests/` | `unittest` and `node --test` suites (below). |

## Tests

From the repo root, `make test`. Or directly:

```bash
cd tools/voice && python3 -m unittest discover -s tests -t .
node --test tools/voice/tests/*.test.js
```

| Test file | Covers |
|---|---|
| `test_condenser.py`, `condense.test.js` | `cases.json`, width never exceeded (seeded random memos), empty and non-ASCII input, lot rows, read-back. |
| `test_cross_language.py` | Python and JS condensers give identical output on fixtures, edge inputs, and 5,000 random memos (skipped without node). |
| `test_cleaner.py`, `test_labeler.py` | Filler-only transcripts; LLM guards against the real hallucinations seen on the bench; timeouts and junk output. |
| `test_lot.py`, `test_config.py` | Spaces and priority order, moves and swaps, full lot, order ids, `tasks.json` round trip. |
| `test_protocol.py`, `test_serial_link.py` | Every board event, garbage lines, look-alike text inside labels, byte-exact commands, read-back chunking, pacing, reconnect. |
| `test_recorder.py` | ffmpeg stop escalation, minimum hold, failed start, with the process mocked. |
| `test_transcriber.py` | whisper-cli failures (missing binary, timeout, non-zero exit, tiny file), the offline script transcriber, the fake. |
| `test_ears.py` | The daemon end to end with fakes: order flow, two cars at the speaker, pickup during an order or during labelling, the 60 s cap, RESET, reconnect. |
| `test_cli.py` | The offline tool's output and `tasks.json` match the original script; `--push` pacing; `--watch`; clear errors. |
| `test_ears_mock.py` | The real daemon process against a fake board on a pseudo-terminal, checking every byte written (needs pyserial). |

The design, the serial protocol, and the edge-case list (E-01 to E-43) are in
[`DESIGN.md`](../../DESIGN.md) at the repo root.

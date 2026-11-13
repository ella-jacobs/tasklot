# TaskLot

A physical to-do list: a toy parking lot where each car is one voice-recorded task, and
where you park it is its priority.

<!-- TODO(Ella): one or two sentences on why you built this -->

![CAD render of the TaskLot deck, LCD frame and drive-through](docs/images/cad-assembly-iso.png)

<!-- TODO(Ella): add a photo or short GIF of the real build in use -->

## How it works

1. **Order.** Drive a blank car past the speaker reader and say the task. The laptop
   records it.
2. **Park.** Put the car in one of four spaces. Parking ends the recording. The laptop
   transcribes it locally with whisper.cpp, shortens it to 18 characters, and sends it to
   the board. The LCD shows the four spaces top to bottom, so space 1 is the top priority.
3. **Reorder** by moving cars between spaces.
4. **Read back** a task by driving its car past the speaker again: the LCD shows the full
   text.
5. **Finish** a task by driving the car through the pickup lane. The label is cleared and
   the car is ready for a new task.

```
 RFID sticker on each car
        |
 6 x RC522 readers --SPI--> Arduino Mega 2560 --I2C--> 20x4 LCD
                                 |  ^
                       events    |  |   commands  (USB serial, 9600 baud)
                                 v  |
                     laptop: tools/voice/tasklot_ears.py  (the Ears daemon)
                     mic -> ffmpeg -> whisper.cpp -> Condenser -> "CAR n <label>"
```

The sticker stores nothing; it is a key. The board maps each sticker to a car number and
each car to its label, and the laptop holds the full text. The board never handles audio.

The full design, the serial protocol, and the edge cases are in [`DESIGN.md`](DESIGN.md).

## What is in the repo

| Path | What |
|---|---|
| `firmware/tasklot_full_v2/` | Arduino Mega sketch: six readers, presence detection, the LCD, and the serial command set. |
| `firmware/history/` | The earlier sketches that built up to v2, with a README explaining each step. |
| `tools/voice/` | The laptop side: the `tasklot` Python package (the `Ears` daemon, `Recorder`, `Transcriber`, `Condenser`, `Labeler`, `SerialLink`, `Lot`), `condense.js` for the browser, the original `tasklot_ears.py` / `tasklot_voice.py` commands, and tests. See [`tools/voice/README.md`](tools/voice/README.md). |
| `tools/sim/` | A browser simulator of the whole lot. It can also drive a real board over Web Serial. |
| `build/cad/` | Parametric OpenSCAD for the 3D-printed parts, STL exports, and a pre-print audit script. |
| `build/laser/` | Parametric OpenSCAD for the laser-cut plywood deck and walls, and the run-file generator. |
| `build/wiring/` | Wire-length calculations and a 1:1 under-deck wiring plan. |

## Setup

**Board.** Arduino Mega 2560 with the
[MFRC522](https://github.com/miguelbalboa/rfid) (v1.4.12) and LiquidCrystal I2C
(v1.1.2, Frank de Brabander) libraries. Pin map and wiring are in the header of
`firmware/tasklot_full_v2/tasklot_full_v2.ino` and in `DESIGN.md`.

```bash
arduino-cli compile --fqbn arduino:avr:mega:cpu=atmega2560 firmware/tasklot_full_v2
arduino-cli upload  --fqbn arduino:avr:mega:cpu=atmega2560 -p <port> firmware/tasklot_full_v2
```

**Laptop (macOS).** Python 3.9 or later, `pyserial`, `ffmpeg`, and whisper.cpp
(`whisper-cli`) with an English model. The package itself uses only the standard library.

```bash
python3 -m pip install pyserial
brew install ffmpeg whisper-cpp
TASKLOT_PORT=/dev/cu.usbmodem101 python3 tools/voice/tasklot_ears.py
```

Optional settings: `TASKLOT_WHISPER_MODEL` (model path), `TASKLOT_LLM=0` (turn off the
LLM label upgrade, which calls the `claude` CLI), `TASKLOT_LLM_TIMEOUT`. Every setting is
listed in [`tools/voice/tasklot/config.py`](tools/voice/tasklot/config.py).

**Simulator.** Open `tools/sim/tasklot-sim.html` in Chrome or Edge. No install.

## Tests

```bash
make test
```

This needs only `python3` and `node`. It runs the voice pipeline's unit tests
(`python3 -m unittest`, about 150 tests: every edge case in `DESIGN.md` section 5 that
can be checked on a laptop), the `node --test` suite for `condense.js`, a cross-language
test that requires the Python and JavaScript condensers to agree on thousands of inputs,
and a check that the simulator's inlined copy of the condenser is current. It also runs
the ears daemon against a fake board on a pseudo-terminal and checks every byte it
writes; that test is reported as skipped if `pyserial` is not installed (run
`make test PYTHON=/path/to/python3` with an interpreter that has it). No test calls an
LLM or needs a microphone, a model, or a board. `make firmware` compiles every sketch if
`arduino-cli` is installed.

Hardware checks that cannot be automated are listed in `DESIGN.md`, section 7.

## Credits

Built as the final project for Digital Tangible User Interfaces at Dartmouth by Ella
Jacobs, Colleen, and Riccardo.
<!-- TODO(Ella): confirm with Colleen and Riccardo how they want to be credited (full names, GitHub links) before this goes public. -->

Ella owned the RFID firmware and the physical build; Colleen owned the presentation deck,
the system spec, and the laser-cut fabrication model.
<!-- TODO(Ella): confirm this split and add Riccardo's part. -->

Written with Claude (Anthropic) as a coding assistant, as the course required to be
disclosed. Libraries: MFRC522 by miguelbalboa (public domain), LiquidCrystal I2C by Frank
de Brabander. Transcription uses whisper.cpp with OpenAI's Whisper models.

## License

[MIT](LICENSE)

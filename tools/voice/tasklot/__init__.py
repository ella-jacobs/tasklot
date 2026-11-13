"""TaskLot voice pipeline: the laptop half of a toy parking lot where each car is a task.

The Arduino board never handles audio. This package records the microphone when a
blank car passes the speaker reader, transcribes it locally with whisper.cpp,
shortens it to an 18-character label, and sends that label to the board over USB
serial. See DESIGN.md at the repo root for the protocol and the edge cases.

Modules, in pipeline order:

    config        Settings from environment variables
    protocol      board events (parse_line) and command formatters
    serial_link   SerialLink: paced writes, reconnect
    recorder      Recorder: ffmpeg microphone capture
    transcriber   Transcriber (whisper.cpp), ScriptTranscriber, FakeTranscriber
    cleaner       TranscriptCleaner: drop filler and greetings
    condenser     Condenser: memo -> 18-character label (mirrors condense.js)
    labeler       Labeler: optional LLM label with hallucination guards
    task, lot     Task and Lot: the laptop's model of the cars
    ears          Ears: the live daemon that wires everything together
    cli           `python3 -m tasklot ears|voice`

Run from tools/voice:  python3 -m tasklot --help
"""

"""Command-line entry points. Argument parsing and wiring only; no logic.

    python3 -m tasklot ears [--port PORT] [--no-llm]
    python3 -m tasklot voice [AUDIO ...] [--text T] [--latest-memo] [--watch DIR]
                             [--car N] [--push --port PORT] [--clear]

Run from tools/voice. The original scripts still work and call into this module:
`python3 tasklot_ears.py` is `ears`, `python3 tasklot_voice.py ...` is `voice`.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

from .config import ConfigError, Settings
from .ears import Ears
from .labeler import Labeler
from .logs import log
from .offline import OfflineError, OfflineTool
from .recorder import NullRecorder, Recorder
from .serial_link import SerialLink, SerialLinkError
from .side_channels import FileInbox, Speaker
from .transcriber import FakeTranscriber, ScriptTranscriber, Transcriber, TranscriptionError

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_PORT = 2   # the serial port could not be opened (E-35, E-39)
EXIT_INTERRUPTED = 130  # shell convention for Ctrl-C


def build_parser() -> argparse.ArgumentParser:
    """The top-level parser with the `ears` and `voice` subcommands."""
    parser = argparse.ArgumentParser(prog="python3 -m tasklot",
                                     description="TaskLot voice pipeline (the laptop side).")
    sub = parser.add_subparsers(dest="command", required=True)

    ears = sub.add_parser("ears", help="live daemon: board events -> mic -> whisper -> LCD")
    ears.add_argument("--port", help="serial port (default: $TASKLOT_PORT)")
    ears.add_argument("--no-llm", action="store_true", help="never call the LLM (same as TASKLOT_LLM=0)")

    voice = sub.add_parser("voice", aliases=["add"], help="offline: audio file or text -> tasks.json")
    add_voice_arguments(voice)
    # An empty `voice` run prints this subcommand's help, as the original did.
    voice.set_defaults(help_parser=voice)
    return parser


def add_voice_arguments(parser: argparse.ArgumentParser) -> None:
    """The flags of the original tasklot_voice.py, unchanged."""
    parser.add_argument("audio", nargs="*", help="audio file(s) to transcribe")
    parser.add_argument("--text", help="skip transcription, condense this text")
    parser.add_argument("--latest-memo", action="store_true", help="use the newest Apple Voice Memo")
    parser.add_argument("--watch", metavar="DIR", help="watch DIR for new recordings")
    parser.add_argument("--car", type=int, help="assign to car N (default: next free)")
    parser.add_argument("--push", action="store_true", help="send tasks.json to the Mega")
    parser.add_argument("--port", help="serial port, e.g. /dev/cu.usbmodem14101")
    parser.add_argument("--clear", action="store_true", help="empty tasks.json")


def run_ears(args: argparse.Namespace, settings: Settings) -> int:
    """Wire and run the live daemon until Ctrl-C.

    Returns:
        int: exit status (EXIT_PORT if the port will not open).
    """
    if args.port:
        settings.port = args.port
    if args.no_llm:
        settings.llm_enabled = False
    link = SerialLink(settings.port, settings.baud, pacing=settings.pacing,
                      reset_delay=settings.reset_delay)
    if settings.fake_transcript:
        # Mock mode for tests and demos without a mic: no ffmpeg, no whisper.
        recorder = NullRecorder(settings.rec_dir)
        transcriber = FakeTranscriber(settings.fake_transcript)
    else:
        recorder = Recorder(settings.rec_dir, settings.mic, min_hold=settings.min_hold)
        transcriber = Transcriber(settings.whisper_bin, settings.whisper_model,
                                  timeout=settings.whisper_timeout)
    ears = Ears(link.send, recorder, transcriber,
                labeler=Labeler(enabled=settings.llm_enabled, timeout=settings.llm_timeout),
                speaker=Speaker(settings.voice, settings.say_rate),
                say_inbox=FileInbox(settings.say_file), cmd_inbox=FileInbox(settings.cmd_file),
                max_recording=settings.max_recording)
    link.on_reconnect = ears.on_reconnect
    try:
        link.open()
    except SerialLinkError as exc:
        print(f"[ears] !! {exc}", file=sys.stderr, flush=True)
        return EXIT_PORT
    ears.startup_report()
    ears.start_background_threads()
    log(f"[ears] attached to {settings.port}. Drive a car past the speaker to order.")
    try:
        ears.run(link.readline)
    except KeyboardInterrupt:
        ears.shutdown()
        log("\n[ears] stopped.")
    finally:
        link.close()
    return EXIT_OK


def run_voice(args: argparse.Namespace, settings: Settings,
              parser: Optional[argparse.ArgumentParser] = None) -> int:
    """The offline tool, with the original tasklot_voice.py behaviour.

    Returns:
        int: exit status.
    """
    tool = OfflineTool(settings, ScriptTranscriber(settings.whisper_script))
    try:
        if args.clear:
            print(f"  cleared {tool.clear()}")
            return EXIT_OK
        car = args.car
        if args.text:
            tool.add(args.text, car, "typed")
        for audio in args.audio:
            tool.add_audio(Path(audio), car)
            car = None          # only the first file honours --car
        if args.latest_memo:
            tool.add_audio(tool.latest_memo(), car)
        if args.watch:
            tool.watch(Path(args.watch), push_port=args.port if args.push else None)
            return EXIT_OK
        if tool.has_tasks:
            tool.preview()
            print(f"  saved {settings.tasks_file}")
        if args.push:
            if not args.port:
                print("--push needs --port. List them:  ls /dev/cu.usbmodem*", file=sys.stderr)
                return EXIT_ERROR
            tool.push(args.port)
        elif not tool.has_tasks and parser is not None:
            parser.print_help()
    except (OfflineError, TranscriptionError) as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_ERROR
    except SerialLinkError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_PORT
    return EXIT_OK


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Parse arguments and run a subcommand.

    Returns:
        int: process exit status.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        settings = Settings.from_env()
    except ConfigError as exc:
        print(f"config: {exc}", file=sys.stderr)
        return EXIT_ERROR
    try:
        if args.command == "ears":
            return run_ears(args, settings)
        return run_voice(args, settings, args.help_parser)
    except KeyboardInterrupt:
        # Ctrl-C outside the daemon's read loop (e.g. while the board resets).
        return EXIT_INTERRUPTED

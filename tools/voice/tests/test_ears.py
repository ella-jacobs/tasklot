"""Tests for the Ears orchestrator, driven synchronously with fakes.

No threads, serial port, ffmpeg, whisper, or LLM: board lines go in through
handle_line(), queued recordings are processed with drain_jobs(), and every
command sent to the board is recorded. Covers DESIGN.md E-01, E-02, E-08, E-09,
E-10, E-11, E-12, E-13, E-32, E-33, E-37, E-38, and the RESET command.
"""
import tempfile
import unittest
from pathlib import Path

from tasklot.ears import Ears, Job
from tasklot.labeler import Labeler
from tasklot.logs import LogCapture
from tasklot.recorder import NullRecorder, Recorder
from tasklot.side_channels import FileInbox
from tasklot.transcriber import FakeTranscriber
from tests.fakes import FakeClock, FakeProcess, RecordingSender

TRANSCRIPT = "email the professor about the final project"


class ScriptedTranscriber:
    """Returns queued transcripts in order, then ""; can run a hook mid-call to
    simulate an event arriving while transcription is in progress."""

    def __init__(self, *texts, during=None):
        self.texts = list(texts)
        self.during = during

    def transcribe(self, path):
        if self.during:
            self.during()
        return self.texts.pop(0) if self.texts else ""


class EarsTestCase(unittest.TestCase):
    """Builds an Ears with a NullRecorder, a fake clock, and a recording sender."""

    def make(self, transcriber=None, labeler=None, **kwargs):
        self.clock = FakeClock()
        self.sent = RecordingSender()
        self.log = LogCapture()
        self.recorder = NullRecorder(Path("/nowhere"), log=self.log, clock=self.clock)
        self.ears = Ears(self.sent, self.recorder, transcriber or FakeTranscriber(TRANSCRIPT, log=self.log),
                         labeler=labeler, log=self.log, delete_recordings=False, **kwargs)
        return self.ears

    def board(self, *lines):
        for line in lines:
            self.ears.handle_line(line)


class OrderFlowTest(EarsTestCase):
    """Order -> park -> label, read-back, and pickup."""

    def test_order_park_label(self):
        self.make()
        self.board("SPEAKER  CAR 3 ordering", "SPACE 2  <- CAR 3 parked")
        self.assertEqual(self.ears.drain_jobs(), 1)
        self.assertEqual(self.sent.sent, ["CAR 3 Email the Prof"])
        self.assertEqual(self.ears.lot.full_text(3), "Email the professor about the final project")
        self.assertEqual(self.ears.lot.space_of(3), 2)

    def test_read_back_uses_full_text(self):
        self.make()
        self.board("SPEAKER  CAR 3 ordering", "SPACE 2  <- CAR 3 parked")
        self.ears.drain_jobs()
        self.board("PLAYBACK CAR 3 reading back")
        self.assertEqual(self.sent.sent[1:], ["FULLCLR", "FULL Email the professor about the final",
                                              "FULL project", "FULLSHOW 3"])

    def test_read_back_of_unknown_car_sends_nothing(self):
        # E-38: a restarted daemon has no text for this car.
        self.make()
        self.board("PLAYBACK CAR 5 reading back")
        self.assertEqual(self.sent.sent, [])
        self.assertIn("nothing to show", self.log.text())

    def test_read_back_falls_back_to_echoed_label(self):
        # E-38: labels learned from TASK echoes still allow a read-back.
        self.make()
        self.board("TASK 4 Call mom", "PLAYBACK CAR 4 reading back")
        self.assertEqual(self.sent.sent, ["FULLCLR", "FULL Call mom", "FULLSHOW 4"])

    def test_echo_with_empty_label_forgets(self):
        self.make()
        self.board("TASK 4 Call mom", "TASK 4 ", "PLAYBACK CAR 4 reading back")
        self.assertEqual(self.sent.sent, [])

    def test_empty_echo_after_done_forgets_full_text(self):
        # DONE sent through the command file blanks the car on the board.
        self.make()
        self.board("SPEAKER  CAR 3 ordering", "SPACE 2  <- CAR 3 parked")
        self.ears.drain_jobs()
        self.board("TASK 3 Email the Prof", "TASK 3 ")
        self.assertEqual(self.ears.lot.full_text(3), "")

    def test_bad_space_still_closes_the_order(self):
        self.make()
        self.board("SPEAKER  CAR 3 ordering", "SPACE 9  <- CAR 3 parked")
        self.assertIsNone(self.ears.lot.recording)
        self.assertEqual(self.ears.drain_jobs(), 1)

    def test_pickup_forgets(self):
        self.make()
        self.board("SPEAKER  CAR 3 ordering", "SPACE 2  <- CAR 3 parked")
        self.ears.drain_jobs()
        self.board("PICKUP   CAR 3 collected", "PLAYBACK CAR 3 reading back")
        self.assertEqual(self.sent.sent, ["CAR 3 Email the Prof"])

    def test_park_without_order_sends_nothing(self):
        self.make()
        self.board("SPACE 4  <- CAR 1 parked")
        self.assertEqual(self.ears.drain_jobs(), 0)
        self.assertEqual(self.sent.sent, [])


class EmptyTranscriptTest(EarsTestCase):
    """E-01, E-02: nothing said means nothing sent; the row keeps "CAR n"."""

    def test_silent_recording(self):
        self.make(transcriber=ScriptedTranscriber(""))
        self.board("SPEAKER  CAR 2 ordering", "SPACE 1  <- CAR 2 parked")
        self.ears.drain_jobs()
        self.assertEqual(self.sent.sent, [])
        self.assertIn("nothing transcribed", self.log.text())

    def test_filler_only_transcript(self):
        self.make(transcriber=ScriptedTranscriber("Hello? Um. Okay."))
        self.board("SPEAKER  CAR 2 ordering", "SPACE 1  <- CAR 2 parked")
        self.ears.drain_jobs()
        self.assertEqual(self.sent.sent, [])
        self.assertIn("nothing left after cleanup", self.log.text())


class SpeakerLaneEdgeCasesTest(EarsTestCase):
    """The ordering lane's reader (the "speaker"): E-09, E-10, E-11, E-12."""

    def test_same_car_re_read_keeps_recording(self):
        # E-09
        self.make()
        self.board("SPEAKER  CAR 3 ordering")
        first = self.ears.lot.order_id(3)
        self.board("SPEAKER  CAR 3 ordering")
        self.assertEqual(self.ears.lot.order_id(3), first)
        self.assertIn("keeping the recording", self.log.text())

    def test_second_car_takes_the_speaker(self):
        # E-10: car 3's order is abandoned and logged; car 5's is recorded.
        self.make()
        self.board("SPEAKER  CAR 3 ordering", "SPEAKER  CAR 5 ordering", "SPACE 1  <- CAR 5 parked")
        self.ears.drain_jobs()
        self.assertIn("CAR 3's order abandoned", self.log.text())
        self.assertEqual(self.sent.sent, ["CAR 5 Email the Prof"])

    def test_other_car_parking_closes_the_order(self):
        # E-11: the firmware closes the order on any park; the recording is car 3's.
        self.make()
        self.board("SPEAKER  CAR 3 ordering", "SPACE 4  <- CAR 1 parked")
        self.assertIsNone(self.ears.lot.recording)
        self.ears.drain_jobs()
        self.assertEqual(self.sent.sent, ["CAR 3 Email the Prof"])

    def test_collected_while_ordering_discards(self):
        # E-12: no transcription, nothing sent, even after the cap would have fired.
        self.make()
        self.board("SPEAKER  CAR 3 ordering", "PICKUP   CAR 3 collected")
        self.assertFalse(self.recorder.is_running())
        self.clock.advance(120)
        self.assertFalse(self.ears.check_cap())
        self.assertEqual(self.ears.drain_jobs(), 0)
        self.assertEqual(self.sent.sent, [])


class StaleResultTest(EarsTestCase):
    """E-13: a car collected (or re-ordered) while its label is computed is not re-labelled."""

    def test_collected_during_transcription(self):
        transcriber = ScriptedTranscriber(TRANSCRIPT,
                                          during=lambda: self.board("PICKUP   CAR 3 collected"))
        self.make(transcriber=transcriber)
        self.board("SPEAKER  CAR 3 ordering", "SPACE 2  <- CAR 3 parked")
        self.ears.drain_jobs()
        self.assertEqual(self.sent.sent, [])
        self.assertIn("dropped stale label", self.log.text())

    def test_collected_during_llm_upgrade(self):
        def runner(prompt, timeout):
            self.board("PICKUP   CAR 3 collected")
            return "EMAIL PROF RE PROJ"
        self.make(labeler=Labeler(runner=runner, log=LogCapture()))
        self.board("SPEAKER  CAR 3 ordering", "SPACE 2  <- CAR 3 parked")
        self.ears.drain_jobs()
        self.assertEqual(self.sent.sent, ["CAR 3 Email the Prof"])
        self.assertIn("dropped stale upgrade", self.log.text())

    def test_llm_upgrade_is_sent_when_current(self):
        self.make(labeler=Labeler(runner=lambda p, t: "EMAIL PROF RE PROJ", log=LogCapture()))
        self.board("SPEAKER  CAR 3 ordering", "SPACE 2  <- CAR 3 parked")
        self.ears.drain_jobs()
        self.assertEqual(self.sent.sent, ["CAR 3 Email the Prof", "CAR 3 EMAIL PROF RE PROJ"])
        self.assertEqual(self.ears.lot.label(3), "EMAIL PROF RE PROJ")

    def test_stale_job_for_reordered_car(self):
        self.make()
        lot = self.ears.lot
        old = lot.begin_order(3)
        lot.close_order()
        lot.begin_order(3)
        self.ears.work_once(Job(3, old, Path("/nowhere/x.wav")))
        self.assertEqual(self.sent.sent, [])


class CapTest(EarsTestCase):
    """E-08, E-14: an order nobody parks is closed at the cap and still labelled."""

    def test_cap(self):
        self.make(max_recording=60)
        self.board("SPEAKER  CAR 6 ordering")
        self.clock.advance(59)
        self.assertFalse(self.ears.check_cap())
        self.clock.advance(2)
        self.assertTrue(self.ears.check_cap())
        self.ears.drain_jobs()
        self.assertEqual(self.sent.sent, ["CAR 6 Email the Prof"])
        self.assertIn("never parked", self.log.text())


class RobustnessTest(EarsTestCase):
    """E-32, E-33: garbage and look-alike text never break or trigger anything."""

    def test_garbage_lines(self):
        self.make()
        self.board("3>Charge baCAR 4 Glu", "", "\x00\x01", "--------------------")
        self.board("SPEAKER  CAR 2 ordering", "SPACE 1  <- CAR 2 parked")
        self.ears.drain_jobs()
        self.assertEqual(self.sent.sent, ["CAR 2 Email the Prof"])

    def test_event_text_inside_a_label(self):
        self.make()
        self.board("TASK 9 Call mom", "TASK 3 CAR 9 reading back", "1>CAR 9 reading back")
        self.assertEqual(self.sent.sent, [])

    def test_collaborator_error_is_logged_not_raised(self):
        self.make()
        self.ears.lot.park = None  # sabotage: calling it raises TypeError
        self.board("SPACE 1  <- CAR 2 parked")
        self.assertIn("[handle] !! TypeError", self.log.text())


class FailingRecorder(NullRecorder):
    """A recorder whose ffmpeg never starts (E-05)."""

    def start(self, car, order_id):
        return None

    def is_running(self):
        return False


class StartupAndFailureTest(EarsTestCase):
    """E-05 at the daemon level, and E-06's one-time startup report."""

    def test_failed_recording_sends_nothing(self):
        self.make()
        self.ears.recorder = FailingRecorder(Path("/nowhere"), log=self.log)
        self.board("SPEAKER  CAR 2 ordering", "SPACE 1  <- CAR 2 parked")
        self.assertEqual(self.ears.drain_jobs(), 0)
        self.assertEqual(self.sent.sent, [])
        self.assertIn("nothing was recorded", self.log.text())

    def test_startup_report_lists_problems_once(self):
        class Broken:
            def problems(self):
                return ["whisper-cli not found on PATH"]

        self.make(transcriber=Broken())
        self.ears.startup_report()
        self.assertEqual(self.log.lines, ["[whisper] !! whisper-cli not found on PATH"])


class ShutdownTest(unittest.TestCase):
    """Ctrl-C or SIGTERM never leaves a recording on disk (privacy default)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        clock = FakeClock()

        def ffmpeg(cmd, **kwargs):
            # The fake "ffmpeg" writes its WAV (the last argument) when it stops.
            return FakeProcess(writes_file=Path(cmd[-1]))

        self.log = LogCapture()
        self.recorder = Recorder(self.dir, process_factory=ffmpeg, clock=clock,
                                 sleep=clock.sleep, log=self.log)
        self.transcriber = ScriptedTranscriber(TRANSCRIPT)
        self.sent = RecordingSender()

    def tearDown(self):
        self.tmp.cleanup()

    def make(self, delete_recordings=True):
        return Ears(self.sent, self.recorder, self.transcriber, log=self.log,
                    delete_recordings=delete_recordings)

    def test_shutdown_mid_order_deletes_the_recording(self):
        ears = self.make()
        ears.handle_line("SPEAKER  CAR 3 ordering")
        ears.shutdown()
        self.assertFalse(self.recorder.is_running())
        self.assertEqual(list(self.dir.iterdir()), [])

    def test_shutdown_deletes_queued_recordings_without_transcribing(self):
        ears = self.make()
        ears.handle_line("SPEAKER  CAR 3 ordering")
        ears.handle_line("SPACE 2  <- CAR 3 parked")
        self.assertEqual(len(list(self.dir.iterdir())), 1)
        ears.shutdown()
        self.assertEqual(list(self.dir.iterdir()), [])
        self.assertEqual(ears.jobs.qsize(), 0)
        self.assertEqual(self.transcriber.texts, [TRANSCRIPT])  # never transcribed
        self.assertEqual(self.sent.sent, [])

    def test_shutdown_keeps_recordings_when_asked(self):
        ears = self.make(delete_recordings=False)
        ears.handle_line("SPEAKER  CAR 3 ordering")
        ears.shutdown()
        self.assertEqual([p.name for p in self.dir.iterdir()], ["tasklot_order_car3_1.wav"])


class SideChannelTest(EarsTestCase):
    """The command file, RESET, and re-sending labels after a reconnect."""

    def test_reset_wipes_laptop_and_board(self):
        self.make()
        self.board("TASK 4 Call mom")
        self.ears.handle_command("reset")
        self.assertEqual(self.sent.sent, ["CLEAR"])
        self.assertEqual(self.ears.lot.labels, {})

    def test_other_commands_pass_through(self):
        self.make()
        self.ears.handle_command("  LOT \n")
        self.ears.handle_command("   ")
        self.assertEqual(self.sent.sent, ["LOT"])

    def test_inbox_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            inbox = FileInbox(Path(tmp) / "cmd.txt")
            self.make(cmd_inbox=inbox)
            inbox.reset()
            self.ears.poll_inboxes()
            self.assertEqual(self.sent.sent, [])
            (Path(tmp) / "cmd.txt").write_text("PING\n")
            # Make sure the mtime moves past the reset even on coarse filesystems.
            inbox._last_mtime -= 10
            self.ears.poll_inboxes()
            self.ears.poll_inboxes()
            self.assertEqual(self.sent.sent, ["PING"])

    def test_reconnect_resends_labels(self):
        # E-37
        self.make()
        self.board("TASK 2 Call mom", "TASK 1 Email the Prof", "SPACE 1  <- CAR 1 parked")
        self.ears.on_reconnect()
        self.assertEqual(self.sent.sent, ["CAR 1 Email the Prof", "CAR 2 Call mom"])
        self.assertEqual(self.ears.lot.spaces, [None, None, None, None])

    def test_reconnect_drops_the_open_order(self):
        # A reset board has forgotten the order, so the mic must not stay open
        # until the cap and then label the car.
        self.make()
        self.board("SPEAKER  CAR 3 ordering")
        self.ears.on_reconnect()
        self.assertIsNone(self.ears.lot.recording)
        self.assertFalse(self.recorder.is_running())
        self.clock.advance(120)
        self.assertFalse(self.ears.check_cap())
        self.assertEqual(self.ears.drain_jobs(), 0)
        self.assertEqual(self.sent.sent, [])
        self.assertIn("CAR 3's order dropped", self.log.text())


if __name__ == "__main__":
    unittest.main()

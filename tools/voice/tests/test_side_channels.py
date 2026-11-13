"""Tests for the side channels: SayVoice (macOS `say`) and FileInbox.

`say` is never run: every test injects fake run/popen callables.
"""
import subprocess
import unittest

from tasklot.logs import LogCapture
from tasklot.side_channels import VOICE_PREFERENCES, SayVoice

# What `say -v ?` prints: one voice per line, name first.
INSTALLED = """Albert              en_US    # Hello! My name is Albert.
Samantha            en_US    # Hello! My name is Samantha.
Zoe (Premium)       en_US    # Hello! My name is Zoe.
"""


def fake_run(stdout="", exc=None):
    """A subprocess.run stand-in that returns `stdout` or raises `exc`; records calls."""
    def run(cmd, **kwargs):
        run.calls.append(cmd)
        if exc is not None:
            raise exc
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")
    run.calls = []
    return run


class Popen:
    """A subprocess.Popen stand-in that records each command, or raises."""

    def __init__(self, exc=None):
        self.exc = exc
        self.commands = []

    def __call__(self, cmd):
        if self.exc is not None:
            raise self.exc
        self.commands.append(cmd)


class PickVoiceTest(unittest.TestCase):
    """The requested voice if installed, else the best installed preference."""

    def test_requested_voice_installed(self):
        run = fake_run(INSTALLED)
        voice = SayVoice("Albert", run=run, log=LogCapture())
        self.assertEqual(voice.pick_voice(), "Albert")
        self.assertEqual(run.calls, [["say", "-v", "?"]])

    def test_falls_back_to_first_installed_preference(self):
        # Zoe (Premium) comes before Samantha in VOICE_PREFERENCES.
        self.assertLess(VOICE_PREFERENCES.index("Zoe (Premium)"), VOICE_PREFERENCES.index("Samantha"))
        voice = SayVoice("Nobody", run=fake_run(INSTALLED), log=LogCapture())
        self.assertEqual(voice.pick_voice(), "Zoe (Premium)")

    def test_no_preference_installed_is_system_default(self):
        voice = SayVoice(run=fake_run("Albert   en_US  # hi\n"), log=LogCapture())
        self.assertIsNone(voice.pick_voice())

    def test_say_missing_keeps_what_was_asked_for(self):
        voice = SayVoice("Albert", run=fake_run(exc=FileNotFoundError("say")), log=LogCapture())
        self.assertEqual(voice.pick_voice(), "Albert")


class SpeakTest(unittest.TestCase):
    """speak() builds the `say` command and never raises."""

    def test_command_ends_options_before_the_text(self):
        # Text from the say file starting with "-" must be spoken, not parsed
        # as a `say` option such as -o (write a file) or -f (read one).
        popen = Popen()
        voice = SayVoice(rate="200", popen=popen, run=fake_run(INSTALLED), log=LogCapture())
        voice.pick_voice()
        voice.speak("-o stolen.aiff")
        self.assertEqual(popen.commands, [["say", "-r", "200", "-v", "Zoe (Premium)",
                                           "--", "-o stolen.aiff"]])

    def test_without_a_voice_uses_the_system_default(self):
        popen = Popen()
        SayVoice(rate="180", popen=popen, log=LogCapture()).speak("Drive up")
        self.assertEqual(popen.commands, [["say", "-r", "180", "--", "Drive up"]])

    def test_failure_is_logged(self):
        log = LogCapture()
        SayVoice(popen=Popen(exc=FileNotFoundError("say")), log=log).speak("hello")
        self.assertIn("[say] failed", log.text())


if __name__ == "__main__":
    unittest.main()

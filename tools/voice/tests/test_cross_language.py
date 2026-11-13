"""Cross-language test: condense.js and tasklot.condenser must agree exactly.

The simulator page runs condense.js and the daemon runs the Python Condenser. If
they disagree, the page and the LCD show different words for the same memo. This
feeds one batch of inputs (every cases.json fixture, the DESIGN.md edge cases,
non-ASCII text, and thousands of seeded random memos) through both and compares
condense(), playback(), and the rendered lot line field by field.

Skipped when node is not on PATH.
"""
import json
import os
import shutil
import subprocess
import unittest

from tasklot.condenser import LCD_TEXT, Condenser
from tests.test_condenser import load_cases, random_memos

VOICE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NODE_HELPER = os.path.join(VOICE_DIR, "tests", "condense_cli.js")
NODE = shutil.which("node")
NODE_TIMEOUT_S = 60

# Inputs chosen to hit places where the two regex engines or string APIs could
# differ: punctuation at index 0, a repeated due phrase, smart punctuation,
# accents, emoji, other scripts, tabs, very long words, exactly 18/19 characters.
EDGE_INPUTS = [
    "? Hello there. Next thing",
    "! email the professor. Then call mom",
    "by friday email Bob by friday",
    # The due text also appears inside an earlier word; JS String.replace
    # removes the first occurrence, not the match, and Python mirrors that.
    "call standby friday crew by friday",
    "on monday, on monday call the dentist",
    "Don\u2019t forget to \u201cprint\u201d the poster \u2014 today\u2026",
    "caf\u00e9 meeting with Jos\u00e9 about the r\u00e9sum\u00e9",
    "\U0001F600 buy groceries \U0001F6D2",
    "\u4f60\u597d\u4e16\u754c",
    "call\tmom\nnow",
    "Supercalifragilisticexpialidociousness homework",
    "Charge battery now",
    "Print reader coupon",
    "I need to I need to remember to call her",
    "um um um um um um okay so so so well email",
    "by 4:30 pm finish the lab",
    "on jan 3rd submit the application and the registration",
    "",
    "   ",
    ". . .",
]


def run_node(width, inputs):
    """Run inputs through condense.js via the batch helper.

    Args:
        width: label width for the JS Condenser.
        inputs: list of memo strings.

    Returns:
        list[dict]: one {"condensed", "playback", "lotLine"} per input.

    Raises:
        subprocess.CalledProcessError: if node exits non-zero.
    """
    payload = json.dumps({"width": width, "inputs": inputs})
    result = subprocess.run([NODE, NODE_HELPER], input=payload, capture_output=True,
                            text=True, check=True, timeout=NODE_TIMEOUT_S)
    return json.loads(result.stdout)


def run_python(width, inputs):
    """The same batch through the Python Condenser, in the helper's output shape."""
    condenser = Condenser(width)
    out = []
    for text in inputs:
        condensed = condenser.condense(text)
        out.append({"condensed": condensed.to_dict(),
                    "playback": condenser.playback(condensed),
                    "lotLine": Condenser.lot_lines([text])[0]})
    return out


@unittest.skipUnless(NODE, "node not on PATH")
class CrossLanguageTest(unittest.TestCase):
    """Python and JS produce identical output for the same inputs."""

    def assert_agree(self, width, inputs):
        js = run_node(width, inputs)
        py = run_python(width, inputs)
        self.assertEqual(len(js), len(inputs))
        for text, j, p in zip(inputs, js, py):
            with self.subTest(text=text[:60]):
                self.assertEqual(p, j)

    def test_cases_json(self):
        spec = load_cases()
        self.assert_agree(spec["width"], [c["in"] for c in spec["cases"]])

    def test_edge_inputs(self):
        self.assert_agree(LCD_TEXT, EDGE_INPUTS)

    def test_random_memos(self):
        self.assert_agree(LCD_TEXT, random_memos(count=3000))
        self.assert_agree(LCD_TEXT, random_memos(seed=99, count=2000))

    def test_other_width(self):
        self.assert_agree(12, random_memos(seed=5, count=500))


if __name__ == "__main__":
    unittest.main()

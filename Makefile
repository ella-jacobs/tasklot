# TaskLot — one command runs every automated check.
#
#   make test        Python unit tests (stdlib unittest) and node tests (node --test)
#                    for the voice pipeline. The end-to-end ears test against a fake
#                    board runs only if pyserial is importable by $(PYTHON); otherwise
#                    unittest reports it as skipped.
#   make firmware    compile every sketch for the Mega 2560 (needs arduino-cli + libraries)
#
# Zero install: python3 and node are the only requirements for `make test`. No test
# ever calls an LLM or needs a microphone, a whisper model, or a board.
#
# Use a different interpreter (for example one that has pyserial) with:
#   make test PYTHON=/path/to/python3

PYTHON ?= python3
NODE   ?= node
VOICE  := tools/voice
FQBN   := arduino:avr:mega:cpu=atmega2560

.PHONY: test test-python test-node firmware

test: test-python test-node

test-python:
	cd $(VOICE) && $(PYTHON) -m unittest discover -s tests -t .

test-node:
	$(NODE) --test $(VOICE)/tests/*.test.js

firmware:
	@command -v arduino-cli >/dev/null || { echo "SKIP  arduino-cli not installed"; exit 0; }; \
	for sketch in firmware/tasklot_full_v2 firmware/history/*/; do \
		echo "== $$sketch"; \
		arduino-cli compile --fqbn $(FQBN) $$sketch | grep -E "Sketch uses|rror" || exit 1; \
	done

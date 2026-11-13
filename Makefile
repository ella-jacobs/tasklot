# TaskLot — one command runs every automated check.
#
#   make test        everything below that needs no extra install:
#     test-python      voice pipeline unit tests (stdlib unittest). The end-to-end ears
#                      test against a fake board runs only if pyserial is importable by
#                      $(PYTHON); otherwise unittest reports it as skipped.
#     test-node        condense.js tests (node --test)
#     test-firmware    firmware host tests: the sketch built with the system C++
#                      compiler against fake Arduino libraries (firmware/tests)
#   make firmware    compile every sketch for the Mega 2560 (needs arduino-cli + libraries)
#
# Zero install: python3, node and a C++17 compiler (Xcode command line tools on macOS)
# are the only requirements for `make test`. No test ever calls an LLM or needs a
# microphone, a whisper model, or a board.
#
# Use a different interpreter (for example one that has pyserial) with:
#   make test PYTHON=/path/to/python3

# pipefail, so a failed compile fails `make firmware` even though its output goes through grep.
SHELL       := /bin/bash
.SHELLFLAGS := -o pipefail -c

PYTHON ?= python3
NODE   ?= node
VOICE  := tools/voice
FQBN   := arduino:avr:mega:cpu=atmega2560

.PHONY: test test-python test-node test-firmware firmware

test: test-python test-node test-firmware

test-python:
	cd $(VOICE) && $(PYTHON) -m unittest discover -s tests -t .

test-node:
	$(NODE) --test $(VOICE)/tests/*.test.js

test-firmware:
	firmware/tests/run_tests.sh

firmware:
	@command -v arduino-cli >/dev/null || { echo "SKIP  arduino-cli not installed"; exit 0; }; \
	for sketch in firmware/tasklot_full_v2 firmware/history/*/; do \
		echo "== $$sketch"; \
		arduino-cli compile --fqbn $(FQBN) $$sketch 2>&1 | grep -E "Sketch uses|rror" || exit 1; \
	done

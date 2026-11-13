# TaskLot — one command runs every automated check.
#
#   make test        condenser fixtures (node + python), simulator copy check,
#                    and the ears daemon against a fake board (if pyserial is installed)
#   make firmware    compile every sketch for the Mega 2560 (needs arduino-cli + libraries)
#
# Everything here is zero-install except the two optional pieces, which say SKIP
# instead of failing when their tool is missing. TASKLOT_LLM=0 keeps the tests from
# ever calling an LLM.

VOICE := tools/voice
FQBN  := arduino:avr:mega:cpu=atmega2560

.PHONY: test test-condense test-ears firmware

test: test-condense test-ears

test-condense:
	node $(VOICE)/test_condense.js
	python3 $(VOICE)/test_condense.py

test-ears:
	@if python3 -c "import serial" 2>/dev/null; then \
		TASKLOT_LLM=0 python3 $(VOICE)/test_ears_mock.py; \
	else \
		echo "SKIP  test_ears_mock.py (pyserial not installed: python3 -m pip install pyserial)"; \
	fi

firmware:
	@command -v arduino-cli >/dev/null || { echo "SKIP  arduino-cli not installed"; exit 0; }; \
	for sketch in firmware/tasklot_full_v2 firmware/history/*/; do \
		echo "== $$sketch"; \
		arduino-cli compile --fqbn $(FQBN) $$sketch | grep -E "Sketch uses|rror" || exit 1; \
	done

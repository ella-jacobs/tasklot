# TaskLot firmware checks.
#
#   make -C firmware test      host tests (unit tests + golden scenarios); needs only c++
#   make -C firmware compile   compile the sketch for the Mega 2560 in all three switch
#                              settings and print flash / RAM use (needs arduino-cli,
#                              core arduino:avr, MFRC522 1.4.12, LiquidCrystal I2C 1.1.2)
#   make -C firmware check     both
#
# The repo-root Makefile's `make firmware` also compiles the history sketches.

# pipefail, so a failed compile fails the target even though its output goes through grep.
SHELL       := /bin/bash
.SHELLFLAGS := -o pipefail -c

FQBN   := arduino:avr:mega:cpu=atmega2560
SKETCH := tasklot_full_v2
CLI    := arduino-cli compile --fqbn $(FQBN) --warnings all

.PHONY: check test compile

check: test compile

test:
	tests/run_tests.sh

# Each build must succeed. Library warnings are noise, so only the size lines and any
# error or sketch warning are shown.
SHOW := grep -E "Sketch uses|Global variables|rror|$(SKETCH)/.*warning"
compile:
	@echo "== default (REMEMBER 0, USE_PRESENCE 1)"
	@$(CLI) $(SKETCH) 2>&1 | $(SHOW)
	@echo "== REMEMBER 1"
	@$(CLI) --build-property "compiler.cpp.extra_flags=-DREMEMBER=1" $(SKETCH) 2>&1 | $(SHOW)
	@echo "== USE_PRESENCE 0"
	@$(CLI) --build-property "compiler.cpp.extra_flags=-DUSE_PRESENCE=0" $(SKETCH) 2>&1 | $(SHOW)

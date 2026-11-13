#!/usr/bin/env bash
# run_tests.sh - host-side tests for the TaskLot firmware.
#
# Builds the sketch in firmware/tasklot_full_v2 with the system C++ compiler against
# the fake Arduino libraries in fakes/, then:
#
#   1. runs the unit tests (unit_tests.cpp), which exercise each class directly, and
#   2. runs every scripted scenario (scenarios.cpp) and diffs its transcript against
#      golden/<scenario>.txt. The golden files were recorded from the monolithic
#      sketch before the refactor, so a diff means the refactor changed what the
#      board prints or shows.
#
# Usage:
#   firmware/tests/run_tests.sh                    run everything (exit 1 on any failure)
#   firmware/tests/run_tests.sh --regen <sketch>   rewrite golden/ from another sketch
#                                                  folder (needs arduino-cli, which adds
#                                                  the function prototypes a monolithic
#                                                  .ino relies on)
#
# Needs only a C++17 compiler (c++ / clang++ / g++). Nothing is installed.

set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
sketch="$here/../tasklot_full_v2"
golden="$here/golden"
cxx="${CXX:-c++}"
work="$(mktemp -d "${TMPDIR:-/tmp}/tasklot-fw-tests.XXXXXX")"
trap 'rm -rf "$work"' EXIT

mode="check"
if [[ "${1:-}" == "--regen" ]]; then
  mode="regen"
  sketch="$(cd "${2:?usage: run_tests.sh --regen <sketch-folder>}" && pwd)"
fi

# Scenario -> build variant. The REMEMBER scenarios share one EEPROM image across
# three processes, in order, to model power cycles.
default_scenarios=(boot boot_degraded boot_lcd_3f park_and_leave move_and_swap
                   order_flow readback pickup commands slots_full)
presence_off_scenarios=(presence_off)
remember_scenarios=(remember_1 remember_2 remember_3)

cxxflags=(-std=c++17 -O1 -I "$here/fakes")
if [[ "$mode" == "check" ]]; then
  cxxflags+=(-Wall -Wextra -Werror)
fi

# build_variant <name> <REMEMBER 0|1> <USE_PRESENCE 0|1>
# Copies the sketch, flips the two compile-time switches the same way a person would
# (by editing the #define), and links it with the fakes and the scenario driver.
build_variant() {
  local name="$1" remember="$2" presence="$3"
  # arduino-cli insists the folder is named after the .ino.
  local dir="$work/$name/$(basename "$sketch")"
  mkdir -p "$dir"
  cp "$sketch"/*.ino "$dir"/
  cp "$sketch"/*.h "$sketch"/*.cpp "$dir"/ 2>/dev/null || true
  # The switches are '#define NAME <value>' lines (inside an #ifndef guard in config.h).
  sed -i.bak -E \
    -e "s/^([[:space:]]*#define[[:space:]]+REMEMBER[[:space:]]+)[01]/\1$remember/" \
    -e "s/^([[:space:]]*#define[[:space:]]+USE_PRESENCE[[:space:]]+)[01]/\1$presence/" \
    "$dir"/*.ino "$dir"/*.h 2>/dev/null || true
  rm -f "$dir"/*.bak

  local ino
  ino="$(ls "$dir"/*.ino)"
  local main_cpp="$work/$name/sketch_main.cpp"
  if [[ "$mode" == "regen" ]]; then
    # arduino-cli's preprocessor inserts the prototypes the .ino relies on.
    arduino-cli compile --fqbn arduino:avr:mega:cpu=atmega2560 --preprocess "$dir" > "$main_cpp"
  else
    { echo '#include <Arduino.h>'; echo "#line 1 \"$(basename "$ino")\""; cat "$ino"; } > "$main_cpp"
  fi

  local sources=("$main_cpp" "$here/scenarios.cpp" "$here/fakes/fakes.cpp")
  for f in "$dir"/*.cpp; do [[ -e "$f" ]] && sources+=("$f"); done
  "$cxx" "${cxxflags[@]}" -I "$dir" "${sources[@]}" -o "$work/$name/scenarios"
}

fails=0

# compare <scenario> <transcript-file>
compare() {
  local name="$1" got="$2"
  if [[ "$mode" == "regen" ]]; then
    cp "$got" "$golden/$name.txt"
    echo "  wrote golden/$name.txt"
  elif diff -u "$golden/$name.txt" "$got" > "$work/$name.diff"; then
    echo "  PASS  scenario $name"
  else
    echo "  FAIL  scenario $name (diff against golden/$name.txt):"
    sed 's/^/        /' "$work/$name.diff" | head -60
    fails=$((fails + 1))
  fi
}

echo "firmware host tests ($mode)"

if [[ "$mode" == "check" ]]; then
  echo "== unit tests"
  unit_sources=("$here/unit_tests.cpp" "$here/fakes/fakes.cpp")
  for f in "$sketch"/*.cpp; do unit_sources+=("$f"); done
  "$cxx" "${cxxflags[@]}" -I "$sketch" "${unit_sources[@]}" -o "$work/unit_tests"
  if ! "$work/unit_tests"; then fails=$((fails + 1)); fi
fi

echo "== scenarios"
build_variant default 0 1
build_variant presence_off 0 0
build_variant remember 1 1

for s in "${default_scenarios[@]}"; do
  "$work/default/scenarios" "$s" > "$work/$s.txt"
  compare "$s" "$work/$s.txt"
done
for s in "${presence_off_scenarios[@]}"; do
  "$work/presence_off/scenarios" "$s" > "$work/$s.txt"
  compare "$s" "$work/$s.txt"
done
eeprom="$work/eeprom.bin"
for s in "${remember_scenarios[@]}"; do
  "$work/remember/scenarios" "$s" "$eeprom" > "$work/$s.txt"
  compare "$s" "$work/$s.txt"
done

if [[ "$fails" -ne 0 ]]; then
  echo "FAILED: $fails"
  exit 1
fi
echo "all firmware host tests passed"

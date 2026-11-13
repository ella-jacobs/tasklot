// Tests for condense.js, run with the node built-in test runner:
//
//   node --test tools/voice/tests/*.test.js
//
// Pins the behaviour from before the refactor (every case in cases.json), checks
// the Condenser class and the function-style API the simulator uses agree, and
// covers the DESIGN.md width and character-set edge cases. Agreement with the
// Python Condenser is checked from the Python side (test_cross_language.py).
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const C = require('../condense.js');

const spec = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'cases.json'), 'utf8'));

test('every case in cases.json matches', () => {
  const condenser = new C.Condenser({ width: spec.width });
  for (const c of spec.cases) {
    const got = condenser.condense(c.in);
    for (const k of ['full', 'lcd', 'due']) {
      assert.equal(got[k], c[k], `${k} for ${JSON.stringify(c.in).slice(0, 50)}`);
    }
  }
});

test('function API matches the class (the simulator calls the functions)', () => {
  const condenser = new C.Condenser();
  for (const c of spec.cases) {
    assert.deepEqual(C.condense(c.in), condenser.condense(c.in));
    assert.deepEqual(C.condense(c.in, { width: 12 }), new C.Condenser({ width: 12 }).condense(c.in));
  }
  assert.equal(C.playback({ full: 'Call mom' }), condenser.playback({ full: 'Call mom' }));
});

test('E-15: label never exceeds the width', () => {
  const words = 'um so I need to email the professor about whether we still need the poster by friday library meeting homework extraordinarily-long-word and with'.split(' ');
  // Deterministic linear congruential generator so a failure is reproducible.
  let seed = 7;
  const next = (n) => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed % n; };
  const condenser = new C.Condenser();
  for (let i = 0; i < 500; i++) {
    const memo = Array.from({ length: 1 + next(30) }, () => words[next(words.length)]).join(' ');
    assert.ok(condenser.condense(memo).lcd.length <= C.LCD_TEXT, memo);
  }
});

test('E-18: empty-like input gives empty fields', () => {
  for (const text of ['', '   ', '   ...   ', null, undefined]) {
    const got = new C.Condenser().condense(text);
    assert.deepEqual([got.full, got.lcd, got.due], ['', '', '']);
  }
});

test('E-19: exactly 18 untouched, 19 is devowelled', () => {
  assert.equal(C.condense('Charge battery now').lcd, 'Charge battery now');
  assert.equal(C.condense('Print reader coupon').lcd, 'Print reader coupn');
});

test('E-17: smart punctuation maps to ASCII, other non-ASCII drops', () => {
  assert.equal(C.ascii('don\u2019t \u201cforget\u201d \u2013 now\u2026'), 'don\'t "forget" - now...');
  assert.equal(C.ascii('caf\u00e9 \u{1F600} run'), 'caf run');
  assert.equal(C.condense('\u4f60\u597d\u4e16\u754c').lcd, '');
});

test('lotLines returns four lines of exactly LCD_WIDTH', () => {
  // A short write leaves the previous line's tail on the LCD, so every line is padded.
  const lines = C.lotLines([{ lcd: 'Email the Prof' }, 'Call mom', null, null]);
  assert.equal(lines.length, 4);
  for (const l of lines) assert.equal(l.length, C.LCD_WIDTH);
  assert.equal(lines[2].trim(), '3>-');
  assert.deepEqual(C.lotLines(null).map((l) => l.trim()), ['1>-', '2>-', '3>-', '4>-']);
});

test('playback reads the task, the due hint, then the nudge', () => {
  const task = C.condense('remind me to charge the battery pack tonight');
  assert.equal(C.playback(task),
    'Charge the battery pack. Due tonight. Go plug it in. That is the whole task.');
  assert.equal(C.playback(null), '');
});

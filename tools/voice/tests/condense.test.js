// Tests for condense.js, run with the node built-in test runner:
//
//   node --test tools/voice/tests/*.test.js
//
// Pins the current behaviour: every case in cases.json gives the same
// full/lcd/due output, and the four lot lines are always 20 characters.
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const C = require('../condense.js');

const spec = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'cases.json'), 'utf8'));

test('every case in cases.json matches', () => {
  for (const c of spec.cases) {
    const got = C.condense(c.in, { width: spec.width });
    for (const k of ['full', 'lcd', 'due']) {
      assert.equal(got[k], c[k], `${k} for ${JSON.stringify(c.in).slice(0, 50)}`);
    }
    assert.ok(got.lcd.length <= spec.width, `lcd too wide: ${got.lcd}`);
  }
});

test('lotLines returns four lines of exactly LCD_WIDTH', () => {
  // A short write leaves the previous line's tail on the LCD, so every line is padded.
  const lines = C.lotLines([{ lcd: 'Email the Prof' }, 'Call mom', null, null]);
  assert.equal(lines.length, 4);
  for (const l of lines) assert.equal(l.length, C.LCD_WIDTH);
  assert.equal(lines[2].trim(), '3>-');
});

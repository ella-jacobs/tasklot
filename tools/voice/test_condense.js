#!/usr/bin/env node
// Runs cases.json against condense.js. Its twin, test_condense.py, runs the same
// file against condense.py. If one passes and the other doesn't, the port drifted.
const fs = require('fs');
const path = require('path');
const C = require('./condense.js');

const spec = JSON.parse(fs.readFileSync(path.join(__dirname, 'cases.json'), 'utf8'));
let fail = 0;

for (const c of spec.cases) {
  const got = C.condense(c.in, { width: spec.width });
  for (const k of ['full', 'lcd', 'due']) {
    if (got[k] !== c[k]) {
      fail++;
      console.log(`FAIL  ${JSON.stringify(c.in).slice(0, 50)}\n      ${k}: want ${JSON.stringify(c[k])}\n           got  ${JSON.stringify(got[k])}`);
    }
  }
  if (got.lcd.length > spec.width) { fail++; console.log(`FAIL  lcd too wide (${got.lcd.length}): ${got.lcd}`); }
}

// The four lines must always be exactly 20 chars, or the LCD keeps stale text
// from the previous write hanging off the end of a shorter one.
const lines = C.lotLines([{ lcd: 'Email the Prof' }, 'Call mom', null, null]);
if (lines.length !== 4) { fail++; console.log('FAIL  lotLines did not return 4 lines'); }
lines.forEach((l, i) => {
  if (l.length !== C.LCD_WIDTH) { fail++; console.log(`FAIL  line ${i + 1} is ${l.length} chars, want ${C.LCD_WIDTH}`); }
});
if (lines[2].trim() !== '3>-') { fail++; console.log('FAIL  empty space should render "3>-", got ' + JSON.stringify(lines[2])); }

console.log(fail ? `\n${fail} failure(s)` : `js: ${spec.cases.length} cases ok`);
process.exit(fail ? 1 : 0);

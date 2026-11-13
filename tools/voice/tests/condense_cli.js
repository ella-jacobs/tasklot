#!/usr/bin/env node
// Batch front end to condense.js for the cross-language test
// (tests/test_cross_language.py). Not a user-facing tool.
//
// Reads JSON from stdin:   { "width": 18, "inputs": ["memo", ...] }
// Writes JSON to stdout:   [ { "condensed": {full, lcd, due, raw},
//                              "playback": "...", "lotLine": "1>..." }, ... ]
//
// The Python test runs the same inputs through tasklot.condenser and requires
// identical output, so the browser simulator and the LCD always agree.
'use strict';

const C = require('../condense.js');

let input = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', (chunk) => { input += chunk; });
process.stdin.on('end', () => {
  const req = JSON.parse(input);
  const condenser = new C.Condenser({ width: req.width });
  const out = req.inputs.map((text) => {
    const condensed = condenser.condense(text);
    return {
      condensed: condensed,
      playback: condenser.playback(condensed),
      lotLine: condenser.lotLines([text])[0]
    };
  });
  process.stdout.write(JSON.stringify(out));
});

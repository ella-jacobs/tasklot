/* TaskLot — condense.js
 *
 * One spoken memo -> { full, lcd, due, raw }: the judgment half of the voice
 * pipeline, for the browser. Whisper (or the browser's dictation) turns audio
 * into text; this decides what the text means and fits it on one row of a 20x4
 * character LCD, where "1>" takes two characters and leaves 18 for the task.
 *
 *   full -> the whole task, however long (read-back, simulator page)
 *   lcd  -> what fits on one LCD row
 *   due  -> a due hint pulled out of the text ("friday", "4pm"), or ""
 *   raw  -> the ASCII-flattened input
 *
 * The Condenser class here mirrors tasklot/condenser.py rule for rule. Both are
 * checked against tools/voice/cases.json, and a cross-language test feeds the
 * same inputs to both, so the simulator and the LCD cannot drift apart.
 *
 * Runs unchanged in the browser (<script src>, exposes window.TaskLotCondense)
 * and in node (require). The simulator page carries an inlined copy; after any
 * change run `python3 tools/voice/sync_page.py` to refresh it.
 *
 * Written with Claude (Anthropic) as a coding assistant.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.TaskLotCondense = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var LCD_WIDTH = 20;  // characters per physical LCD row
  var LCD_TEXT = 18;   // what is left after the "1>" priority marker
  var LCD_ROWS = 4;    // one row per parking space; row order is priority order

  // clip() only honours a word boundary if it keeps at least this share of the
  // width; otherwise a hard cut keeps more of the task.
  var WORD_BOUNDARY_MIN_SHARE = 0.55;

  // devowel() only fires when the line misses by at most this many characters;
  // past that, squeezed words become unreadable and truncation is better.
  var DEVOWEL_MAX_OVER = 3;
  var DEVOWEL_MIN_WORD = 5;

  // Loop caps: the leading-filler rule is anchored and fires once per pass, and
  // intent prefixes stack. Well above real transcripts; guarantees termination.
  var FILLER_PASSES = 4;
  var INTENT_PASSES = 3;

  // ---------------------------------------------------------------------------
  // Rule tables. Order matters in every list; keep them identical to condenser.py.
  // ---------------------------------------------------------------------------

  // 1. Disfluency. Whisper transcribes every "um" faithfully.
  var FILLER = [
    /\b(um+|uh+|er+|ah+|hmm+|mm+)\b/gi,
    /\b(you know|i mean|like i said|sort of|kind of|kinda|sorta)\b/gi,
    /^\s*(ok(ay)?|so|alright|right|well|anyway|and)\b[,\s]*/i,
    /\b(basically|literally|honestly|actually|really|just)\b/gi
  ];

  // 2. Intent prefixes. "I need to email the professor" is the task "Email the
  //    professor". Longest alternatives first, so "I have got to" beats "I have".
  var INTENT = new RegExp(
    '^\\s*(?:' + [
      'note to self(?:,)?',
      'reminder(?:,)?', 'remind me (?:to|that i (?:need|have) to)',
      "don'?t forget (?:to|about)",
      'i (?:really )?(?:need|have|ought|want|meant|forgot|gotta|got)\\s*(?:to|ta)?',
      "i'?ve (?:got|gotta) to", "i'?m (?:going to|gonna)", "i'?ll",
      'i should', 'we (?:need|have) to', 'we should',
      'make sure (?:that )?(?:i|we) ?(?:need to)?',
      'remember to', 'todo(?::)?', 'task(?::)?', 'new task(?::)?'
    ].join('|') + ')\\b[,:\\s]*', 'i');

  // 3. When it is due. Pulled out of the text: the LCD has no room for it.
  var DUE = [
    /\b(?:by|before|due|on)\s+(tomorrow morning|tomorrow night|tomorrow|tonight|today|this (?:morning|afternoon|evening|week|weekend)|next week|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b/i,
    /\b(?:by|at|before)\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm))\b/i,
    /\b(?:by|before|on)\s+((?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2}(?:st|nd|rd|th)?|\d{1,2}\/\d{1,2})\b/i,
    /\b(tomorrow (?:morning|afternoon|night)|tomorrow|tonight|today|this (?:morning|afternoon|evening|weekend)|next week)\b/i
  ];

  // 4. Where a sentence stops being the task and starts being the reason.
  //    "Email the professor about whether we still need the poster" -> cut at "about".
  var CLAUSE = /\s+\b(?:about|because|since|so that|so|which|whether|that i|if i|but|and then|before i|after i|in order to|to see|to ask|to find out|for the (?:sake|reason))\b\s+/i;

  // 5. LCD-only abbreviations. Conservative on purpose: a bad abbreviation reads
  //    worse than an honest truncation.
  var ABBREV = [
    [/\bprofessors?\b/gi, 'Prof'], [/\bappointments?\b/gi, 'appt'],
    [/\bmeetings?\b/gi, 'mtg'], [/\bhomework\b/gi, 'HW'],
    [/\bassignments?\b/gi, 'asgmt'], [/\bpresentations?\b/gi, 'pres'],
    [/\bprojects?\b/gi, 'proj'], [/\bapplications?\b/gi, 'app'],
    [/\blaboratory\b/gi, 'lab'], [/\blibrary\b/gi, 'lib'],
    [/\bmessages?\b/gi, 'msg'], [/\bschedule\b/gi, 'sched'],
    [/\bquestions?\b/gi, 'Q'], [/\bminutes?\b/gi, 'min'],
    [/\btomorrow\b/gi, 'tmrw'], [/\bdeadline\b/gi, 'due'],
    [/\breservations?\b/gi, 'resv'], [/\bregistration\b/gi, 'reg'],
    [/\band\b/gi, '&'], [/\bwith\b/gi, 'w/'],
    [/\bwithout\b/gi, 'w/o'], [/\bnumber\b/gi, '#'],
    [/\bversus\b/gi, 'vs']
  ];

  var ARTICLES = /\b(?:the|a|an|my|our)\s+/gi;

  // Trailing detail lives in prepositional phrases: "Print the reader coupon
  // before class" -> "Print the reader coupon".
  var PREPS = ['about', 'before', 'after', 'during', 'against', 'onto', 'into',
               'for', 'from', 'with', 'under', 'over', 'at', 'in', 'on', 'to', 'by', 're'];

  // A sentence end followed by a capital: where the second sentence starts.
  var SENTENCE_BREAK = /[.!?]\s+[A-Z]/;

  var VOWELS = 'aeiouAEIOU';

  // The nudge: the last line of a read-back names the first physical move.
  // Rule-based so it runs offline and gives the same answer every time, which
  // makes a demo rehearsable. Specific patterns come before general ones.
  var NUDGE = [
    [/\b(gmail|email|e-mail|inbox|reply|write back)\b/i, 'Just open Gmail and get started.'],
    [/\b(call|phone|ring|voicemail)\b/i, 'Just pick up the phone. It is a two-minute call.'],
    [/\b(text|message|dm|slack)\b/i, 'Open the thread and send one line.'],
    [/\b(print|printer|coupon)\b/i, 'The printer is right there. Go hit print.'],
    [/\b(charge|battery|plug|outlet)\b/i, 'Go plug it in. That is the whole task.'],
    [/\b(pay|bill|invoice|venmo|rent)\b/i, 'Open the app and pay it now.'],
    [/\b(book|schedule|appointment|reserve|rsvp)\b/i, 'Open the calendar and pick a time.'],
    [/\b(submit|turn in|upload|hand in|send)\b/i, 'Attach it and hit send.'],
    [/\b(report|essay|draft|paper|write|writing)\b/i, 'Open the doc and write one bad sentence.'],
    [/\b(study|review|revise|practice|problem set|pset)\b/i, 'Open it and do one problem.'],
    [/\b(read|chapter|article|paper)\b/i, 'Open it and read one page.'],
    [/\b(buy|order|cart|groceries|pick up)\b/i, 'Pull it up and add it to the cart.'],
    [/\b(clean|tidy|laundry|dishes|trash|organize)\b/i, 'Set a timer for five minutes and start.'],
    [/\b(glue|cut|solder|wire|assemble|build|sand|paint)\b/i, 'Get the parts out on the table.'],
    [/\b(pack|laundry|bag)\b/i, 'Put one thing in the bag.']
  ];
  var DEFAULT_NUDGE = 'Start with the first small piece. That is all you have to do.';

  var EMPTY_SPACE = '-';  // what an empty parking space shows on its LCD row

  // ---------------------------------------------------------------------------
  // Text helpers (stateless).
  // ---------------------------------------------------------------------------

  /**
   * Flatten text to printable ASCII on one line. The HD44780 ROM is ASCII, so
   * smart quotes and dashes map to plain ones and everything else is dropped.
   * @param {*} s  anything; falsy becomes ''
   * @returns {string}
   */
  function ascii(s) {
    return String(s || '')
      .replace(/[\u2018\u2019\u02bc]/g, "'")
      .replace(/[\u201c\u201d]/g, '"')
      .replace(/[\u2013\u2014]/g, '-')
      .replace(/\u2026/g, '...')
      .replace(/[^\x20-\x7E]/g, '')
      .replace(/\s+/g, ' ')
      .trim();
  }

  /** Collapse spaces and trim stray punctuation left behind by removals. */
  function tidy(s) {
    return s.replace(/\s+/g, ' ')
            .replace(/\s+([,.;:!?])/g, '$1')
            .replace(/^[\s,.;:-]+/, '')
            .replace(/[\s,;:]+$/, '')
            .trim();
  }

  /** Upper-case the first character only. */
  function sentenceCase(s) {
    if (!s) return s;
    return s.charAt(0).toUpperCase() + s.slice(1);
  }

  /** Remove trailing periods and whitespace. */
  function stripTrailingStops(s) {
    return s.replace(/[.\s]+$/, '');
  }

  /**
   * Cut to n characters, preferring a word boundary. No ellipsis: the LCD has no
   * glyph for it and three dots would cost 3 of 18 characters.
   * @param {string} s
   * @param {number} n  maximum length
   * @returns {string}
   */
  function clip(s, n) {
    if (s.length <= n) return s;
    var cut = s.slice(0, n);
    var sp = cut.lastIndexOf(' ');
    // Only honour the word boundary if it does not throw away most of the line.
    if (sp >= Math.floor(n * WORD_BOUNDARY_MIN_SHARE)) cut = cut.slice(0, sp);
    return cut.replace(/[\s,.;:-]+$/, '');
  }

  /**
   * Drop trailing prepositional phrases, rightmost first, until it fits. Never
   * cuts at word 0 or 1, so a two-word verb phrase always survives.
   * @param {string} s
   * @param {number} width
   * @returns {string} possibly still longer than width
   */
  function trimPhrases(s, width) {
    while (s.length > width) {
      var words = s.split(' ');
      var cut = -1;
      for (var i = words.length - 2; i >= 2; i--) {
        if (PREPS.indexOf(words[i].toLowerCase()) >= 0) { cut = i; break; }
      }
      if (cut < 0) return s;
      s = words.slice(0, cut).join(' ');
    }
    return s;
  }

  /**
   * When a line misses by a hair, pull interior vowels out of its longest word:
   * "Print reader coupon" (19) -> "Print reader coupn" (18). Keeps the noun that
   * truncation would have thrown away whole.
   * @param {string} s
   * @param {number} width
   * @returns {string} unchanged if it fits, misses by too much, or the word is short
   */
  function devowel(s, width) {
    var over = s.length - width;
    if (over <= 0 || over > DEVOWEL_MAX_OVER) return s;
    var words = s.split(' ');
    // Longest word, latest one on a tie: trailing detail is safer to squash.
    var pick = 0;
    for (var i = 0; i < words.length; i++) if (words[i].length >= words[pick].length) pick = i;
    var w = words[pick];
    if (w.length < DEVOWEL_MIN_WORD) return s;
    while (over > 0) {
      // Rightmost interior vowel: never the first or last character.
      var cut = -1;
      for (var j = w.length - 2; j >= 1; j--) {
        if (VOWELS.indexOf(w.charAt(j)) >= 0) { cut = j; break; }
      }
      if (cut < 0) break;
      w = w.slice(0, cut) + w.slice(cut + 1);
      over--;
    }
    words[pick] = w;
    return words.join(' ');
  }

  // ---------------------------------------------------------------------------
  // The Condenser.
  // ---------------------------------------------------------------------------

  /** Remove disfluencies, looping because the anchored rule fires once a pass. */
  function stripFiller(t) {
    for (var pass = 0; pass < FILLER_PASSES; pass++) {
      var before = t;
      for (var i = 0; i < FILLER.length; i++) t = t.replace(FILLER[i], ' ');
      t = tidy(t);
      if (t === before) break;
    }
    return t;
  }

  /**
   * Pull the first due hint out before later stages can eat it.
   * @returns {{text:string, due:string}}
   */
  function extractDue(t) {
    for (var d = 0; d < DUE.length; d++) {
      var m = t.match(DUE[d]);
      if (m) return { text: tidy(t.replace(m[0], ' ')), due: m[1].toLowerCase() };
    }
    return { text: t, due: '' };
  }

  /** Drop intent prefixes ("I need to", "remind me to"); they stack. */
  function stripIntent(t) {
    for (var k = 0; k < INTENT_PASSES; k++) {
      var before = t;
      t = tidy(t.replace(INTENT, ''));
      if (t === before) break;
    }
    return t;
  }

  // ---------------------------------------------------------------------------
  // The Condenser.
  // ---------------------------------------------------------------------------

  /** Shortens transcripts to LCD labels and renders the lot. Stateless apart from the width. */
  class Condenser {
    /** @param {object} [opts]  { width: label width, default LCD_TEXT (18) } */
    constructor(opts) {
      this.width = (opts && opts.width) || LCD_TEXT;
    }

    /**
     * Turn one transcript into a task. Each squeeze stage runs only while the
     * text is still too wide, so a short task is never abbreviated.
     * @param {string} transcript  raw text; messy is expected
     * @returns {{full:string, lcd:string, due:string, raw:string}}
     */
    condense(transcript) {
      var width = this.width;
      var raw = ascii(transcript);
      if (!raw) return { full: '', lcd: '', due: '', raw: '' };

      var t = stripFiller(raw);
      var d = extractDue(t);
      t = stripIntent(d.text);

      // One task per memo: keep the first sentence. A break at index 0 is not a sentence.
      var firstStop = t.search(SENTENCE_BREAK);
      var full = tidy(firstStop > 0 ? t.slice(0, firstStop + 1) : t);
      full = sentenceCase(stripTrailingStops(full));

      var lcd = full;
      if (lcd.length > width) {                                      // (a) cut the reason off
        var c = lcd.search(CLAUSE);
        if (c > 0) lcd = tidy(lcd.slice(0, c));
      }
      if (lcd.length > width) lcd = tidy(trimPhrases(lcd, width));   // (b) trailing detail
      if (lcd.length > width) {                                      // (c) abbreviate
        for (var a = 0; a < ABBREV.length; a++) lcd = lcd.replace(ABBREV[a][0], ABBREV[a][1]);
        lcd = tidy(lcd);
      }
      if (lcd.length > width) lcd = tidy(lcd.replace(ARTICLES, ''));  // (d) drop articles
      if (lcd.length > width) lcd = devowel(lcd, width);             // (e) squeeze vowels
      lcd = clip(sentenceCase(lcd), width);                           // (f) truncate

      return { full: full, lcd: lcd, due: d.due, raw: raw };
    }

    /**
     * The nudge line for a task: the first physical move. Never empty.
     * @param {string} text  the full task
     * @returns {string}
     */
    firstStep(text) {
      var t = ascii(text || '');
      for (var i = 0; i < NUDGE.length; i++) {
        if (NUDGE[i][0].test(t)) return NUDGE[i][1];
      }
      return DEFAULT_NUDGE;
    }

    /**
     * What a read-back says: the task, its due hint if any, then the nudge.
     * @param {{full:string, due:string}} task
     * @returns {string} '' if there is nothing to read back
     */
    playback(task) {
      if (!task || !task.full) return '';
      var out = stripTrailingStops(task.full) + '.';
      if (task.due) out += ' Due ' + task.due + '.';
      return out + ' ' + this.firstStep(task.full);
    }

    /**
     * Render the four LCD rows from the lot, in priority (space) order. Every
     * row is padded to full width, because a short write leaves the old tail.
     * @param {Array} lot  up to 4 entries: null, a label string, or { lcd, full }
     * @param {number} [width]  physical row width, default LCD_WIDTH (20)
     * @returns {string[]} exactly LCD_ROWS strings of exactly width characters
     */
    lotLines(lot, width) {
      width = width || LCD_WIDTH;
      var out = [];
      for (var i = 0; i < LCD_ROWS; i++) {
        var item = lot && lot[i];
        var text = !item ? EMPTY_SPACE
          : (typeof item === 'string' ? item : (item.lcd || item.full || EMPTY_SPACE));
        var line = (i + 1) + '>' + clip(ascii(text), width - 2);
        while (line.length < width) line += ' ';
        out.push(line);
      }
      return out;
    }
  }

  // A shared default instance backs the function-style API the simulator uses.
  var standard = new Condenser();

  return {
    Condenser: Condenser,
    condense: function (transcript, opts) {
      return (opts && opts.width ? new Condenser(opts) : standard).condense(transcript);
    },
    firstStep: function (text) { return standard.firstStep(text); },
    playback: function (task) { return standard.playback(task); },
    lotLines: function (lot, width) { return standard.lotLines(lot, width); },
    clip: clip,
    devowel: devowel,
    trimPhrases: trimPhrases,
    ascii: ascii,
    LCD_WIDTH: LCD_WIDTH,
    LCD_TEXT: LCD_TEXT
  };
});

/* TaskLot — condense.js
 *
 * ONE spoken memo  ->  { full, lcd, due, car }
 *
 * This is the JUDGMENT half of the voice pipeline. The MECHANICAL half (audio ->
 * text) is whisper, and it lives in tasklot_voice.py. Same split as a
 * classic voice-memo pipeline: a dumb transcriber, then a layer that decides what the text
 * MEANS and where it goes.
 *
 * Two sinks, two shapes:
 *   full -> the browser page       the whole task, however long
 *   lcd  -> the LCD2004A, 18 chars  what fits on one of four lines
 *
 * ** THIS FILE IS CANONICAL. ** condense.py is a port of it. Both are checked
 * against tools/voice/cases.json so they cannot drift apart silently.
 *
 * Runs unchanged in the browser (<script src>) and in node (require).
 *
 * AI disclosure: written with Claude (Anthropic) to Ella's spec. Credit it.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.TaskLotCondense = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  // The LCD is 20 chars wide. Two of them go to the priority marker ("1>"),
  // which leaves this much for the task itself. Change it here, nowhere else.
  var LCD_WIDTH = 20;
  var LCD_TEXT  = 18;

  // ---------------------------------------------------------------------------
  // 1. Disfluency. Whisper transcribes every "um" faithfully.
  // ---------------------------------------------------------------------------
  var FILLER = [
    /\b(um+|uh+|er+|ah+|hmm+|mm+)\b/gi,
    /\b(you know|i mean|like i said|sort of|kind of|kinda|sorta)\b/gi,
    /^\s*(ok(ay)?|so|alright|right|well|anyway|and)\b[,\s]*/i,
    /\b(basically|literally|honestly|actually|really|just)\b/gi
  ];

  // ---------------------------------------------------------------------------
  // 2. Intent prefixes. "I need to email the professor" is the task "Email the professor".
  //    Order matters — longest first, so "I have got to" beats "I have".
  // ---------------------------------------------------------------------------
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

  // ---------------------------------------------------------------------------
  // 3. When it's due. Pulled OUT of the text — the LCD has no room for it and
  //    the page shows it as its own field.
  // ---------------------------------------------------------------------------
  var DUE = [
    /\b(?:by|before|due|on)\s+(tomorrow morning|tomorrow night|tomorrow|tonight|today|this (?:morning|afternoon|evening|week|weekend)|next week|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b/i,
    /\b(?:by|at|before)\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm))\b/i,
    /\b(?:by|before|on)\s+((?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2}(?:st|nd|rd|th)?|\d{1,2}\/\d{1,2})\b/i,
    /\b(tomorrow (?:morning|afternoon|night)|tomorrow|tonight|today|this (?:morning|afternoon|evening|weekend)|next week)\b/i
  ];

  // ---------------------------------------------------------------------------
  // 4. Where a sentence stops being the task and starts being the reason.
  //    "Email the professor about whether we still need the poster" -> cut at "about".
  //    This is what makes the LCD line read like a task and not like a fragment.
  // ---------------------------------------------------------------------------
  var CLAUSE = /\s+\b(?:about|because|since|so that|so|which|whether|that i|if i|but|and then|before i|after i|in order to|to see|to ask|to find out|for the (?:sake|reason))\b\s+/i;

  // ---------------------------------------------------------------------------
  // 5. LCD-only abbreviations. Conservative on purpose: a bad abbreviation
  //    reads worse than an honest truncation.
  // ---------------------------------------------------------------------------
  var ABBREV = [
    [/\bprofessors?\b/gi, 'Prof'], [/\bappointments?\b/gi, 'appt'],
    [/\bmeetings?\b/gi, 'mtg'],    [/\bhomework\b/gi, 'HW'],
    [/\bassignments?\b/gi, 'asgmt'], [/\bpresentations?\b/gi, 'pres'],
    [/\bprojects?\b/gi, 'proj'],   [/\bapplications?\b/gi, 'app'],
    [/\blaboratory\b/gi, 'lab'],   [/\blibrary\b/gi, 'lib'],
    [/\bmessages?\b/gi, 'msg'],    [/\bschedule\b/gi, 'sched'],
    [/\bquestions?\b/gi, 'Q'],     [/\bminutes?\b/gi, 'min'],
    [/\btomorrow\b/gi, 'tmrw'],    [/\bdeadline\b/gi, 'due'],
    [/\breservations?\b/gi, 'resv'],[/\bregistration\b/gi, 'reg'],
    [/\band\b/gi, '&'],            [/\bwith\b/gi, 'w/'],
    [/\bwithout\b/gi, 'w/o'],      [/\bnumber\b/gi, '#'],
    [/\bversus\b/gi, 'vs']
  ];

  var ARTICLES = /\b(?:the|a|an|my|our)\s+/gi;

  // Trailing detail lives in prepositional phrases. "Print the reader coupon
  // before class" -> "Print the reader coupon". Trimmed from the right, one
  // phrase at a time, and never below a two-word verb phrase.
  var PREPS = ['about','before','after','during','against','onto','into',
               'for','from','with','under','over','at','in','on','to','by','re'];

  // ---------------------------------------------------------------------------

  // HD44780 ROM is ASCII. Smart quotes and dashes come out as garbage blocks,
  // so they get flattened before anything else.
  function ascii(s) {
    return String(s || '')
      .replace(/[‘’ʼ]/g, "'")
      .replace(/[“”]/g, '"')
      .replace(/[–—]/g, '-')
      .replace(/…/g, '...')
      .replace(/[^\x20-\x7E]/g, '')
      .replace(/\s+/g, ' ')
      .trim();
  }

  function tidy(s) {
    return s.replace(/\s+/g, ' ')
            .replace(/\s+([,.;:!?])/g, '$1')
            .replace(/^[\s,.;:-]+/, '')
            .replace(/[\s,;:]+$/, '')
            .trim();
  }

  function sentenceCase(s) {
    if (!s) return s;
    return s.charAt(0).toUpperCase() + s.slice(1);
  }

  // Cut to n chars, preferring a word boundary. No ellipsis — the LCD has no
  // "…" glyph and spending 3 of 18 chars on dots is a bad trade.
  function clip(s, n) {
    if (s.length <= n) return s;
    var cut = s.slice(0, n);
    var sp = cut.lastIndexOf(' ');
    // Only honour the word boundary if it doesn't throw away most of the line.
    if (sp >= Math.floor(n * 0.55)) cut = cut.slice(0, sp);
    return cut.replace(/[\s,.;:-]+$/, '');
  }

  // Drop trailing prepositional phrases, rightmost first, until it fits or
  // there's nothing left to drop. Stops while a real verb phrase remains.
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

  // Last resort before truncation: when a line misses by only a character or
  // three, pull interior vowels out of its longest word. "Print reader coupon"
  // (19) -> "Print reader coupn" (18). Classic LCD trick, and it keeps the noun
  // that truncation would have thrown away whole.
  function devowel(s, width) {
    var over = s.length - width;
    if (over <= 0 || over > 3) return s;
    var words = s.split(' ');
    // longest word, latest one on a tie - trailing detail is the safer thing to squash
    var pick = 0;
    for (var i = 0; i < words.length; i++) if (words[i].length >= words[pick].length) pick = i;
    var w = words[pick];
    if (w.length < 5) return s;
    while (over > 0) {
      // rightmost interior vowel: never the first or last character of the word
      var cut = -1;
      for (var j = w.length - 2; j >= 1; j--) {
        if ('aeiouAEIOU'.indexOf(w.charAt(j)) >= 0) { cut = j; break; }
      }
      if (cut < 0) break;
      w = w.slice(0, cut) + w.slice(cut + 1);
      over--;
    }
    words[pick] = w;
    return words.join(' ');
  }

  /**
   * The whole job.
   * @param {string} transcript  raw whisper text (messy is expected)
   * @param {object} [opts]      { width: LCD text width, default 18 }
   * @returns {{full:string, lcd:string, due:string, raw:string}}
   */
  function condense(transcript, opts) {
    opts = opts || {};
    var width = opts.width || LCD_TEXT;

    var raw = ascii(transcript);
    if (!raw) return { full: '', lcd: '', due: '', raw: '' };

    // -- strip disfluency ----------------------------------------------------
    // Looped, because the leading-filler rule is anchored and only fires once
    // per pass. Real whisper output stacks them: "Um okay so I really need to".
    var t = raw, before;
    for (var pass = 0; pass < 4; pass++) {
      before = t;
      for (var i = 0; i < FILLER.length; i++) t = t.replace(FILLER[i], ' ');
      t = tidy(t);
      if (t === before) break;
    }

    // -- pull the due hint out before anything eats it -----------------------
    var due = '';
    for (var d = 0; d < DUE.length; d++) {
      var m = t.match(DUE[d]);
      if (m) { due = m[1].toLowerCase(); t = tidy(t.replace(m[0], ' ')); break; }
    }

    // -- drop the intent prefix ("I need to ...") ----------------------------
    // Looped: "I need to remember to call her" stacks two of them.
    for (var k = 0; k < 3; k++) {
      before = t;
      t = tidy(t.replace(INTENT, ''));
      if (t === before) break;
    }

    // -- one task per memo: keep the first sentence ---------------------------
    var firstStop = t.search(/[.!?]\s+[A-Z]/);
    var full = tidy(firstStop > 0 ? t.slice(0, firstStop + 1) : t);
    full = sentenceCase(full.replace(/[.\s]+$/, ''));

    // -- now squeeze, in stages, until it fits --------------------------------
    var lcd = full;

    // (a) cut the explanation off the task
    if (lcd.length > width) {
      var c = lcd.search(CLAUSE);
      if (c > 0) lcd = tidy(lcd.slice(0, c));
    }
    // (b) drop trailing prepositional detail
    if (lcd.length > width) lcd = tidy(trimPhrases(lcd, width));
    // (c) abbreviate
    if (lcd.length > width) {
      for (var a = 0; a < ABBREV.length; a++) lcd = lcd.replace(ABBREV[a][0], ABBREV[a][1]);
      lcd = tidy(lcd);
    }
    // (d) drop articles
    if (lcd.length > width) lcd = tidy(lcd.replace(ARTICLES, ''));
    // (e) squeeze vowels if it misses by a hair
    if (lcd.length > width) lcd = devowel(lcd, width);
    // (f) truncate
    lcd = clip(sentenceCase(lcd), width);

    return { full: full, lcd: lcd, due: due, raw: raw };
  }

  /**
   * THE NUDGE — the line the speaker adds when it reads a task back.
   *
   * Playing the task back verbatim is just a recording. The point of driving up
   * to the speaker is that you are about to DO the thing, so the last line names
   * the first physical move: "just open Gmail and get started." Small, concrete,
   * and impossible to argue with — which is the whole reason it works on a brain
   * that is avoiding the task.
   *
   * Rule-based on purpose. It has to run offline, in a browser, with no network
   * and no model, and give the same answer every time so a demo is rehearsable.
   * Order matters: the specific patterns are tested before the general ones.
   *
   * @param {string} text  the full task
   * @returns {string} one sentence, always non-empty
   */
  var NUDGE = [
    [/\b(gmail|email|e-mail|inbox|reply|write back)\b/i, 'Just open Gmail and get started.'],
    [/\b(call|phone|ring|voicemail)\b/i,                 'Just pick up the phone. It is a two-minute call.'],
    [/\b(text|message|dm|slack)\b/i,                     'Open the thread and send one line.'],
    [/\b(print|printer|coupon)\b/i,                      'The printer is right there. Go hit print.'],
    [/\b(charge|battery|plug|outlet)\b/i,                'Go plug it in. That is the whole task.'],
    [/\b(pay|bill|invoice|venmo|rent)\b/i,               'Open the app and pay it now.'],
    [/\b(book|schedule|appointment|reserve|rsvp)\b/i,    'Open the calendar and pick a time.'],
    [/\b(submit|turn in|upload|hand in|send)\b/i,        'Attach it and hit send.'],
    [/\b(report|essay|draft|paper|write|writing)\b/i,    'Open the doc and write one bad sentence.'],
    [/\b(study|review|revise|practice|problem set|pset)\b/i, 'Open it and do one problem.'],
    [/\b(read|chapter|article|paper)\b/i,                'Open it and read one page.'],
    [/\b(buy|order|cart|groceries|pick up)\b/i,          'Pull it up and add it to the cart.'],
    [/\b(clean|tidy|laundry|dishes|trash|organize)\b/i,  'Set a timer for five minutes and start.'],
    [/\b(glue|cut|solder|wire|assemble|build|sand|paint)\b/i, 'Get the parts out on the table.'],
    [/\b(pack|laundry|bag)\b/i,                          'Put one thing in the bag.']
  ];

  function firstStep(text) {
    var t = ascii(text || '');
    for (var i = 0; i < NUDGE.length; i++) {
      if (NUDGE[i][0].test(t)) return NUDGE[i][1];
    }
    return 'Start with the first small piece. That is all you have to do.';
  }

  /**
   * What the speaker SAYS when a loaded car pulls up — the whole read-back.
   * Task, then when it is due if a due date was heard, then the nudge.
   * @param {{full:string, due:string}} task
   * @returns {string} one spoken string, or '' if there is nothing to read back
   */
  function playback(task) {
    if (!task || !task.full) return '';
    var out = task.full.replace(/[.\s]+$/, '') + '.';
    if (task.due) out += ' Due ' + task.due + '.';
    return out + ' ' + firstStep(task.full);
  }

  /**
   * Render the four LCD lines from the lot state. Space order IS priority order:
   * space 1 is the top of the list, and moving a car moves the task.
   * @param {Array} lot  4 entries, each null or { lcd } / a string
   * @returns {string[]} exactly 4 lines of exactly LCD_WIDTH chars
   */
  function lotLines(lot, width) {
    width = width || LCD_WIDTH;
    var out = [];
    for (var i = 0; i < 4; i++) {
      var item = lot && lot[i];
      var text = !item ? '-' : (typeof item === 'string' ? item : (item.lcd || item.full || '-'));
      var line = (i + 1) + '>' + clip(ascii(text), width - 2);
      while (line.length < width) line += ' ';
      out.push(line);
    }
    return out;
  }

  return {
    condense: condense,
    firstStep: firstStep,
    playback: playback,
    lotLines: lotLines,
    clip: clip,
    devowel: devowel,
    trimPhrases: trimPhrases,
    ascii: ascii,
    LCD_WIDTH: LCD_WIDTH,
    LCD_TEXT: LCD_TEXT
  };
});

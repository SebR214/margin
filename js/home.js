/* The home page, built from stored files only (SEB-240).
 *
 * Numbers, dates, currency codes and stored ids come from data/*.json.
 * Every word comes from copy.json "homeData". A key that is empty (or missing)
 * is not rendered. No word is written in this file.
 *
 * Reads: data/heatmap_daily.json, record_daily.json, cycle_log.json,
 * record_milestones.json, movers_week.json, findings.json, copy.json.
 */
(function () {

  var HEAT_STEPS = [2, 8, 25, 50]; // gap thresholds in percent; the legend shows these numbers
  var BIG_CCY = 'DZD';             // the page's one big number
  var LAST_N = 48;
  var SVGNS = 'http://www.w3.org/2000/svg';
  var C = {};
  var D = {};
  var S = { i: 0, playing: false };
  var timer = null;
  var updaters = [];

  /* ---------------------------------------------------------------- helpers */
  function fmt(s, vars) {
    return s.replace(/\{(\w+)\}/g, function (m, k) { return vars && vars[k] != null ? vars[k] : ''; });
  }
  function has(key) { return typeof C[key] === 'string' && C[key].length > 0; }
  function t(key, vars) { return has(key) ? fmt(C[key], vars) : ''; }
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) { [].concat(cls).forEach(function (c) { e.classList.add(c); }); }
    if (text != null) { e.textContent = text; }
    return e;
  }
  function sv(tag, attrs, cls) {
    var e = document.createElementNS(SVGNS, tag);
    Object.keys(attrs || {}).forEach(function (k) { e.setAttribute(k, attrs[k]); });
    if (cls) { e.setAttribute('class', cls); }
    return e;
  }
  /* A text element tied to a copy key; absent when the key is empty. */
  function word(parent, tag, cls, key, varsFn) {
    if (!has(key)) { return null; }
    var e = el(tag, cls);
    var run = function () { e.textContent = t(key, varsFn ? varsFn() : null); };
    run();
    if (varsFn) { updaters.push(run); }
    parent.appendChild(e);
    return e;
  }
  function num(n, d) {
    if (n == null || isNaN(n)) { return ''; }
    return Number(n).toLocaleString('en-US', { maximumFractionDigits: d || 0, minimumFractionDigits: d || 0 });
  }
  function dShort(day) {
    return new Date(day + 'T00:00:00Z').toLocaleDateString('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC' });
  }
  function dLong(day) {
    return new Date(day + 'T00:00:00Z').toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });
  }
  function hhmm(iso) { return iso ? iso.slice(11, 16) : ''; }
  function ccyLink(parent, ccy, cls) {
    var a = el('a', cls, ccy);
    a.href = 'country.html?ccy=' + encodeURIComponent(ccy);
    a.setAttribute('data-ccy', ccy);
    parent.appendChild(a);
    return a;
  }
  function getJSON(url) {
    return fetch(url).then(function (r) { if (!r.ok) { throw new Error(url); } return r.json(); });
  }
  function colourClass(g) {
    if (g == null) { return 'hn'; }
    for (var k = 0; k < HEAT_STEPS.length; k++) { if (g < HEAT_STEPS[k]) { return 'h' + k; } }
    return 'h' + HEAT_STEPS.length;
  }
  function lastIndex() { return D.days.length - 1; }
  function dayLabel(i) {
    return (i === lastIndex() && has('dayToday')) ? t('dayToday') : dShort(D.days[i]);
  }

  /* ---------------------------------------------------------------- header */
  function header(wrap) {
    var h = el('div', 'hp-head');
    var left = el('div', 'hp-headleft');
    var logo = word(left, 'a', ['hp-logo', 'mono'], 'brand');
    if (logo) { logo.href = './index.html'; }
    if (has('navCountries') || has('navRoutes') || has('navSources') || has('navFindings') || has('navHow')) {
      var nav = el('nav', 'hp-nav');
      [['navCountries', 'countries.html'], ['navRoutes', 'sending-money.html'], ['navSources', 'sources.html'],
       ['navFindings', 'findings.html'], ['navHow', 'how-it-works.html']].forEach(function (n) {
        var a = word(nav, 'a', 'hp-navlink', n[0]);
        if (a) { a.href = './' + n[1]; }
      });
      left.appendChild(nav);
    }
    h.appendChild(left);
    var CL = D.cycles;
    if (CL && CL.last_reading_utc && CL.next_reading_utc) {
      var right = el('div', ['mono', 'muted', 'hp-clock']);
      var dot = el('span', 'hp-dot');
      right.appendChild(dot);
      var a = word(right, 'span', null, 'headerLast', function () { return { time: CL.last_reading_utc.slice(11, 19) }; });
      var b = el('span');
      right.appendChild(b);
      var next = Date.parse(CL.next_reading_utc);
      var tick = function () {
        var diff = Math.round((next - Date.now()) / 1000);
        var over = diff < 0;
        var s = Math.abs(diff);
        var hh = Math.floor(s / 3600), mm = Math.floor((s % 3600) / 60), ss = s % 60;
        var pad = function (x) { return (x < 10 ? '0' : '') + x; };
        var cd = (hh > 0 ? hh + ':' : '') + pad(mm) + ':' + pad(ss);
        b.textContent = t(over ? 'headerOverdue' : 'headerNext', { countdown: cd });
        dot.classList.toggle('still', over);
      };
      tick();
      setInterval(tick, 1000);
      h.appendChild(right);
    }
    wrap.appendChild(h);
  }

  /* ---------------------------------------------------------------- hero + counters */
  function totalsVars() {
    var R = D.record, tt = R && R.totals ? R.totals : {};
    var big = D.big;
    return {
      readings: num(tt.readings), sources: num(tt.sources), currencies: num(tt.currencies),
      routes: num(tt.routes), hours: num(tt.hours_collected),
      gap: big ? num(big.value, 0) : '', country: big ? big.country : ''
    };
  }
  function hero(wrap) {
    if (!has('headline') && !has('headlineSub')) { return; }
    var s = el('section', 'hp-hero');
    word(s, 'h1', null, 'headline', totalsVars);
    word(s, 'p', ['soft', 'hp-lede'], 'headlineSub', totalsVars);
    wrap.appendChild(s);
  }
  function counters(wrap) {
    var R = D.record;
    if (!R) { return; }
    var box = el('div', 'hp-counterbox');
    var grid = el('div', 'hp-counters');
    var recAt = function () { return R.byDay[D.days[S.i]] || {}; };
    [['counterReadings', 'readings_cumulative'], ['counterSources', 'sources_cumulative'],
     ['counterCurrencies', 'currencies_cumulative'], ['counterRoutes', 'routes_cumulative'],
     ['counterHours', 'hours_cumulative']].forEach(function (c) {
      var cell = el('div');
      var v = el('span', ['mono', 'hp-count']);
      var run = function () { var d = recAt(); v.textContent = d[c[1]] == null ? '' : num(d[c[1]]); };
      run(); updaters.push(run);
      cell.appendChild(v);
      word(cell, 'span', ['muted', 'hp-small'], c[0]);
      grid.appendChild(cell);
    });
    box.appendChild(grid);
    word(box, 'span', ['mono', 'muted', 'hp-tiny'], 'countersNote', function () { return { date: dayLabel(S.i) }; });
    wrap.appendChild(box);
  }

  /* ---------------------------------------------------------------- this hour */
  function cycleSection(wrap) {
    var CL = D.cycles;
    if (!CL || !CL.steps) { return; }
    var st = CL.steps;
    var sec = el('section', 'hp-sec');
    var head = el('div', 'hp-sechead');
    word(head, 'h2', null, 'cycleTitle');
    word(head, 'span', ['muted', 'hp-small'], 'cycleLine');
    sec.appendChild(head);
    var row = el('div', 'hp-row');
    var list = el('div', ['hp-main', 'hp-list']);
    var hour = hhmm(st.hour_utc);
    var last = CL.cycles && CL.cycles.length ? CL.cycles[CL.cycles.length - 1] : null;
    var steps = [];
    if (st.currencies) { steps.push({ time: hour, key: 'stepCurrencies', vars: { collected: num(st.currencies.collected), of: num(st.currencies.of) } }); }
    if (st.routes) { steps.push({ time: hour, key: 'stepRoutes', vars: { priced: num(st.routes.priced), of: num(st.routes.of) } }); }
    if (st.auditor) {
      steps.push({ time: hhmm(st.auditor.sample_ts) || hour, key: 'stepAuditor', vars: { rebuilt: num(st.auditor.rebuilt) },
        vkey: 'stepAuditorResult', vvars: { matched: num(st.auditor.matched), rebuilt: num(st.auditor.rebuilt) } });
    }
    if (st.analyst != null && typeof st.analyst === 'object') { // null: the analyst has not run, so no row
      var av = {};
      Object.keys(st.analyst).forEach(function (k) { if (typeof st.analyst[k] !== 'object') { av[k] = st.analyst[k]; } });
      steps.push({ time: hour, key: 'stepAnalyst', vars: av });
    }
    if (last) {
      var rk = last.status === 'clean' ? 'resultClean' : last.status === 'source_missed' ? 'resultSourceMissed' : 'resultCheckFailed';
      steps.push({ time: hhmm(last.last_reading_utc) || hour, key: rk, vars: { sources: (last.reasons || []).join(', '), n: (last.reasons || []).length }, final: true });
    }
    steps.forEach(function (s) {
      if (!has(s.key)) { return; }
      var r = el('div', 'hp-step');
      r.appendChild(el('span', ['mono', 'muted', 'hp-time'], s.time));
      r.appendChild(el('span', s.final ? 'hp-sdot-amber' : 'hp-sdot'));
      var tx = el('span', s.final ? 'hp-steptext' : ['soft', 'hp-steptext'], t(s.key, s.vars));
      r.appendChild(tx);
      if (s.vkey && has(s.vkey)) { r.appendChild(el('span', 'mono', t(s.vkey, s.vvars))); }
      list.appendChild(r);
    });
    row.appendChild(list);

    var side = el('div', ['hp-side', 'hp-tight']);
    var cycles = (CL.cycles || []).slice(-LAST_N);
    word(side, 'span', ['muted', 'hp-small'], 'stripTitle', function () { return { n: cycles.length }; });
    var strip = el('div', 'hp-strip');
    cycles.forEach(function (c) {
      var s = el('span', c.status === 'check_failed' ? 'sf' : c.status === 'source_missed' ? 'sm' : 'sc');
      s.title = c.hour_utc.slice(0, 10) + ' ' + hhmm(c.hour_utc);
      strip.appendChild(s);
    });
    side.appendChild(strip);
    var leg = el('div', ['soft', 'hp-tiny', 'hp-legend']);
    [['stripClean', 'sc'], ['stripMissed', 'sm'], ['stripFailed', 'sf']].forEach(function (l) {
      if (!has(l[0])) { return; }
      var s = el('span');
      s.appendChild(el('i', ['hp-sw', 'k' + l[1]]));
      s.appendChild(document.createTextNode(' ' + t(l[0])));
      leg.appendChild(s);
    });
    side.appendChild(leg);
    row.appendChild(side);
    sec.appendChild(row);
    wrap.appendChild(sec);
  }

  /* ---------------------------------------------------------------- heatmap */
  function heatSection(wrap) {
    var H = D.heat;
    if (!H) { return; }
    var n = D.days.length;
    var sec = el('section', ['hp-sec', 'hp-gap24']);
    var head = el('div', 'hp-intro');
    word(head, 'h2', null, 'heatTitle');
    word(head, 'p', ['muted', 'hp-body'], 'heatLine');
    if (head.childNodes.length) { sec.appendChild(head); }
    var row = el('div', 'hp-row');
    var main = el('div', ['hp-main', 'hp-rel']);
    var grid = el('div', 'hp-heat');
    var cols = [];
    for (var d = 0; d < n; d++) { cols.push([]); }
    var tip = el('div', ['hp-tip', 'mono']);
    tip.hidden = true;
    var unranked = [];
    D.rows.forEach(function (cur) {
      var r = el('div', 'hp-hmrow');
      ccyLink(r, cur.ccy, ['hp-code', 'mono']);
      var cells = el('div', 'hp-cells');
      cells.setAttribute('data-ccy', cur.ccy);
      for (var k = 0; k < n; k++) {
        var s = el('span', cur.ranked ? colourClass(cur.cells[k]) : 'hu');
        if (cur.ranked && cur.cells[k] == null) { s.className = 'hn'; }
        cells.appendChild(s);
        cols[k].push(s);
      }
      r.appendChild(cells);
      grid.appendChild(r);
      if (!cur.ranked) { unranked.push(cur); }
      cells.addEventListener('mousemove', function (ev) {
        var b = cells.getBoundingClientRect();
        var k2 = Math.max(0, Math.min(n - 1, Math.floor((ev.clientX - b.left) / b.width * n)));
        var v = cur.cells[k2];
        var text = v == null ? t('tipNone') : num(v, 1) + '%';
        if (!text) { tip.hidden = true; return; }
        tip.textContent = cur.ccy + ' ' + dShort(D.days[k2]) + ' ' + text;
        tip.hidden = false;
        var mb = main.getBoundingClientRect();
        tip.style.top = (b.top - mb.top - 34) + 'px';
        tip.style.left = Math.max(0, Math.min(mb.width - 180, ev.clientX - mb.left - 40)) + 'px';
      });
      cells.addEventListener('mouseleave', function () { tip.hidden = true; });
    });
    D.cols = cols;
    main.appendChild(grid);
    main.appendChild(tip);
    unranked.forEach(function (cur) {
      var note = word(main, 'p', ['muted', 'hp-note'], 'unrankedNote', function () { return { ccy: cur.ccy, country: cur.country }; });
      return note;
    });

    var ctl = el('div', 'hp-controls');
    if (has('heatPlay')) {
      var btn = el('button', 'hp-btn');
      btn.type = 'button';
      var label = function () { btn.textContent = S.playing ? (t('heatPause') || t('heatPlay')) : t('heatPlay'); };
      label();
      btn.addEventListener('click', function () { toggle(label); });
      ctl.appendChild(btn);
    }
    var lab = el('label', ['muted', 'hp-slider']);
    var cap = el('span');
    var run = function () {
      cap.textContent = '';
      var pre = t('heatDay', { date: dayLabel(S.i) });
      if (pre) { cap.textContent = pre; }
    };
    run(); updaters.push(run);
    if (has('heatDay')) { lab.appendChild(cap); }
    var rg = el('input');
    rg.type = 'range'; rg.min = '0'; rg.max = String(n - 1); rg.value = String(S.i);
    if (has('heatSlider')) { rg.setAttribute('aria-label', t('heatSlider')); }
    rg.addEventListener('input', function () { stop(); set(+rg.value); });
    D.range = rg;
    lab.appendChild(rg);
    ctl.appendChild(lab);
    main.appendChild(ctl);
    row.appendChild(main);

    var side = el('aside', 'hp-side');
    // the one big number
    var bigBox = el('div', 'hp-bigbox');
    if (D.big) {
      var a = el('a', ['mono', 'hp-big']);
      a.href = 'country.html?ccy=' + encodeURIComponent(BIG_CCY);
      a.textContent = num(D.big.value, 0) + '%';
      bigBox.appendChild(a);
      var bv = function () { return { country: D.big.country, ccy: BIG_CCY, date: dShort(D.days[n - 1]), gap: num(D.big.value, 1) }; };
      word(bigBox, 'span', 'soft', 'bigLabel', bv);
      var ln = word(bigBox, 'a', 'hp-biglink', 'bigLink', bv);
      if (ln) { ln.href = 'country.html?ccy=' + encodeURIComponent(BIG_CCY); }
      side.appendChild(bigBox);
    }
    // widest gaps on the selected day
    var topBox = el('div', 'hp-topbox');
    word(topBox, 'span', ['muted', 'hp-small'], 'topTitle', function () { return { date: dayLabel(S.i) }; });
    var tops = [];
    for (var q = 0; q < 6; q++) {
      var tr = el('div', 'hp-toprow');
      var code = el('a', ['mono', 'hp-topcode']);
      var bar = el('span', 'hp-bar');
      var fill = el('i');
      bar.appendChild(fill);
      var val = el('span', ['mono', 'hp-topval']);
      tr.appendChild(code); tr.appendChild(bar); tr.appendChild(val);
      topBox.appendChild(tr);
      tops.push({ row: tr, code: code, fill: fill, val: val });
    }
    D.tops = tops;
    side.appendChild(topBox);
    // legend
    var lg = el('div', 'hp-legbox');
    word(lg, 'span', ['muted', 'hp-small'], 'legendTitle');
    var items = [];
    for (var s2 = 0; s2 <= HEAT_STEPS.length; s2++) {
      var lo = s2 === 0 ? null : HEAT_STEPS[s2 - 1], hi = s2 === HEAT_STEPS.length ? null : HEAT_STEPS[s2];
      var key = lo == null ? 'legendUnder' : hi == null ? 'legendOver' : 'legendBetween';
      items.push({ cls: 'k' + 'h' + s2, key: key, vars: { min: lo, max: hi } });
    }
    items.push({ cls: 'khn', key: 'legendNone', vars: {} });
    if (unranked.length) { items.push({ cls: 'khu', key: 'legendUnranked', vars: {} }); }
    items.forEach(function (it) {
      if (!has(it.key)) { return; }
      var r = el('span', ['soft', 'hp-legrow']);
      r.appendChild(el('i', ['hp-sw', 'hp-sw14', it.cls]));
      r.appendChild(document.createTextNode(t(it.key, it.vars)));
      lg.appendChild(r);
    });
    side.appendChild(lg);
    row.appendChild(side);
    sec.appendChild(row);
    wrap.appendChild(sec);
  }

  function paintHeat() {
    var i = S.i;
    if (D.cols) {
      D.cols.forEach(function (col, k) {
        col.forEach(function (s) { s.classList.toggle('sel', k === i); });
      });
    }
    if (D.tops) {
      var list = D.rows.filter(function (c) { return c.ranked && c.cells[i] != null && c.cells[i] > 0; })
        .sort(function (a, b) { return b.cells[i] - a.cells[i] || (a.ccy < b.ccy ? -1 : 1); }).slice(0, 6);
      var max = list.length ? list[0].cells[i] : 1;
      D.tops.forEach(function (tp, q) {
        var c = list[q];
        tp.row.hidden = !c;
        if (!c) { return; }
        tp.code.textContent = c.ccy;
        tp.code.href = 'country.html?ccy=' + encodeURIComponent(c.ccy);
        tp.code.setAttribute('data-ccy', c.ccy);
        tp.fill.style.width = Math.max(4, c.cells[i] / max * 100).toFixed(1) + '%';
        tp.val.textContent = num(c.cells[i], 0) + '%';
      });
    }
    if (D.range) { D.range.value = String(i); }
  }

  /* ---------------------------------------------------------------- replay */
  function set(i) {
    S.i = i;
    paintHeat();
    updaters.forEach(function (u) { u(); });
    if (D.moveLine) { D.moveLine(); }
  }
  function stop() { if (timer) { clearInterval(timer); timer = null; } S.playing = false; }
  function toggle(relabel) {
    if (timer) { stop(); relabel(); return; }
    if (S.i >= lastIndex()) { set(0); }
    S.playing = true; relabel();
    timer = setInterval(function () {
      if (S.i >= lastIndex()) { stop(); relabel(); return; }
      set(S.i + 1);
      if (S.i >= lastIndex()) { stop(); relabel(); }
    }, 160);
  }

  /* ---------------------------------------------------------------- record timeline */
  function recordSection(wrap) {
    var R = D.record;
    if (!R || !R.days || R.days.length < 2) { return; }
    var rd = R.days;
    var n = rd.length;
    var sec = el('section', 'hp-sec');
    var head = el('div', 'hp-sechead');
    word(head, 'h2', null, 'recordTitle');
    word(head, 'span', ['mono', 'muted', 'hp-small'], 'recordCount', function () {
      var d = R.byDay[D.days[S.i]] || rd[rd.length - 1];
      return { n: num(d.readings_cumulative) };
    });
    sec.appendChild(head);
    var box = el('div', 'hp-record');
    var max = rd[n - 1].readings_cumulative || 1;
    var X = function (k) { return (k * 560 / (n - 1)).toFixed(1); };
    var pts = rd.map(function (d, k) { return X(k) + ',' + (118 - d.readings_cumulative / max * 108).toFixed(1); });
    var line = 'M' + pts.join(' L');
    var svg = sv('svg', { viewBox: '0 0 560 120', preserveAspectRatio: 'none' }, 'hp-recsvg');
    svg.appendChild(sv('path', { d: line + ' L560,120 L0,120 Z' }, 'hp-area'));
    svg.appendChild(sv('path', { d: line, 'vector-effect': 'non-scaling-stroke' }, 'hp-line'));
    var cur = sv('line', { y1: '0', y2: '120', 'vector-effect': 'non-scaling-stroke' }, 'hp-cursor');
    svg.appendChild(cur);
    var moveCursor = function () {
      var k = Math.max(0, rd.findIndex(function (d) { return d.day === D.days[S.i]; }));
      cur.setAttribute('x1', X(k)); cur.setAttribute('x2', X(k));
    };
    moveCursor(); D.moveLine = moveCursor;
    box.appendChild(svg);

    // markers: backfill and route days first, then source days by how many sources began
    var cands = [];
    var byDay = {};
    var back = [];
    (D.milestones || []).forEach(function (m) {
      if (m.kind === 'backfill') { back.push(m); return; }
      var o = byDay[m.first_day] || (byDay[m.first_day] = { route: [], source: [] });
      (o[m.kind] || o.source).push(m.id);
    });
    if (back.length) {
      back.sort(function (a, b) { return a.first_day < b.first_day ? -1 : 1; });
      cands.push({ prio: 0, k: 0, ids: back.map(function (m) { return m.id; }),
        parts: [t('markBackfill', { n: back.length, date: dLong(back[0].first_day), id: back[0].id })] });
    }
    var dayKeys = Object.keys(byDay).sort();
    var idx = {};
    rd.forEach(function (d, k) { idx[d.day] = k; });
    dayKeys.forEach(function (day) {
      if (idx[day] == null) { return; }
      var o = byDay[day], parts = [], ids = o.route.concat(o.source);
      if (o.route.length) { parts.push(t('markRoute', { date: dShort(day), n: o.route.length, ids: o.route.join(', ') })); }
      if (o.source.length) {
        parts.push(o.source.length === 1
          ? t('markSource', { date: dShort(day), id: o.source[0] })
          : t('markSources', { date: dShort(day), n: o.source.length }));
      }
      cands.push({ prio: o.route.length ? 1 : 2 + (1 - Math.min(o.source.length, 1000) / 1000), k: idx[day], ids: ids, parts: parts, day: day });
    });
    cands.sort(function (a, b) { return a.prio - b.prio || a.k - b.k; });
    var marks = cands.filter(function (c) { return c.parts.some(Boolean); }).map(function (c) {
      var m = el('div', 'hp-mark');
      m.title = c.ids.join(', ');
      var lab = el('span', ['soft', 'hp-marklabel']);
      c.parts.filter(Boolean).forEach(function (p, q) { lab.appendChild(el('span', 'hp-markpart', p)); });
      m.appendChild(lab);
      m.appendChild(el('span', 'hp-markline'));
      m.style.visibility = 'hidden';
      box.appendChild(m);
      return { c: c, m: m, lab: lab };
    });
    var place = function () {
      var W = box.clientWidth;
      var placed = [];
      marks.forEach(function (o) { o.m.style.display = ''; o.m.style.visibility = 'hidden'; });
      marks.forEach(function (o) {
        var p = o.c.k / (n - 1);
        var right = p > 0.6;
        var w = o.lab.offsetWidth;
        var x = p * W;
        var fits = function (r) { return r ? x - w >= -1 : x + w <= W + 1; };
        if (!fits(right)) { right = !right; }
        if (!fits(right)) { o.m.style.display = 'none'; return; }
        var a = right ? x - w : x, b = right ? x : x + w;
        var ok = -1;
        for (var lane = 0; lane < 3 && ok < 0; lane++) {
          var clash = placed.some(function (q) {
            if (q.lane === lane) { return a < q.b + 10 && b > q.a - 10; }                // same row
            if (q.lane < lane) { return q.x > a - 6 && q.x < b + 6; }                    // its line crosses this row
            return x > q.a - 6 && x < q.b + 6;                                           // our line crosses its row
          });
          if (!clash) { ok = lane; }
        }
        if (ok < 0) { o.m.style.display = 'none'; return; }
        o.m.style.display = '';
        o.m.style.visibility = 'visible';
        o.m.style.top = (ok * 22) + 'px';
        o.m.style.left = right ? 'auto' : (p * 100).toFixed(2) + '%';
        o.m.style.right = right ? ((1 - p) * 100).toFixed(2) + '%' : 'auto';
        o.m.classList.toggle('end', right);
        o.m.lastChild.style.height = (176 - ok * 22) + 'px';
        placed.push({ lane: ok, a: a, b: b, x: x });
      });
    };
    D.placeMarks = place;
    sec.appendChild(box);
    var foot = el('div', ['mono', 'muted', 'hp-axis']);
    foot.appendChild(el('span', null, dShort(rd[0].day)));
    word(foot, 'span', null, 'axisToday');
    sec.appendChild(foot);
    wrap.appendChild(sec);
  }

  /* ---------------------------------------------------------------- what moved + findings */
  function spark(values) {
    var svg = sv('svg', { viewBox: '0 0 70 20', width: '70', height: '20' }, 'hp-spark');
    var nums = values.filter(function (v) { return v != null; });
    if (!nums.length) { return svg; }
    var lo = Math.min.apply(null, nums), hi = Math.max.apply(null, nums);
    var Y = function (v) { return hi === lo ? 10 : 18 - (v - lo) / (hi - lo) * 16; };
    var seg = [];
    var flush = function () {
      if (seg.length > 1) { svg.appendChild(sv('polyline', { points: seg.join(' ') }, 'hp-sline')); }
      else if (seg.length === 1) {
        var p = seg[0].split(',');
        svg.appendChild(sv('circle', { cx: p[0], cy: p[1], r: '1' }, 'hp-sdotc'));
      }
      seg = [];
    };
    values.forEach(function (v, k) {
      if (v == null) { flush(); return; }
      seg.push((k * 70 / (values.length - 1)).toFixed(1) + ',' + Y(v).toFixed(1));
    });
    flush();
    return svg;
  }
  function lowerSections(wrap) {
    var both = el('div', 'hp-two');
    var M = D.movers;
    if (M && M.top && M.top.length) {
      var sec = el('section', 'hp-half');
      word(sec, 'h2', null, 'moversTitle');
      var list = el('div', 'hp-listbox');
      M.top.slice(0, 4).forEach(function (m) {
        var a = el('a', 'hp-mover');
        a.href = 'country.html?ccy=' + encodeURIComponent(m.ccy);
        a.appendChild(el('span', ['mono', 'hp-movercode'], m.ccy));
        var line = t('moverLine', { country: m.country, ccy: m.ccy, from: num(m.earlier_median_pct, 1), to: num(m.recent_median_pct, 1), change: (m.change_pp > 0 ? '+' : '\u2212') + num(Math.abs(m.change_pp), 1), abs: num(Math.abs(m.change_pp), 1) });
        if (line) { a.appendChild(el('span', ['soft', 'hp-moverline'], line)); } else { a.appendChild(el('span', 'hp-moverline')); }
        a.appendChild(spark(m.spark || []));
        list.appendChild(a);
      });
      sec.appendChild(list);
      both.appendChild(sec);
    }
    var F = D.findings;
    if (F) {
      var pub = F.filter(function (f) { return f.published; });
      var fs = el('section', 'hp-half');
      fs.id = 'findings';
      word(fs, 'h2', null, 'findingsTitle');
      var n = 0;
      pub.forEach(function (f) {
        var key = 'finding_' + f.id;
        if (!has(key)) { return; }
        n++;
        var a = el('a', 'hp-card');
        a.href = 'finding.html?id=' + encodeURIComponent(f.id);
        a.appendChild(el('span', ['mono', 'hp-cardnum'], (n < 10 ? '0' : '') + n));
        var hv = f.headline ? f.headline.value : null;
        a.appendChild(el('span', null, t(key, { value: num(hv, hv != null && Math.abs(hv) < 100 && hv % 1 ? 1 : 0), n: n })));
        fs.appendChild(a);
      });
      if (n) { both.appendChild(fs); }
    }
    if (both.childNodes.length) { wrap.appendChild(both); }
  }

  /* ---------------------------------------------------------------- start */
  function prepare() {
    var H = D.heat;
    if (H && H.days && H.currencies) {
      D.days = H.days;
      var rows = H.currencies.map(function (c) {
        var lastv = null;
        for (var k = c.cells.length - 1; k >= 0; k--) { if (c.cells[k] != null) { lastv = c.cells[k]; break; } }
        return { ccy: c.ccy, country: c.country, ranked: c.ranked !== false, cells: c.cells, last: lastv };
      });
      var rank = function (r) { return r.last == null ? 2 : r.ranked ? 0 : 1; };
      rows.sort(function (a, b) {
        return rank(a) - rank(b) || (b.last || 0) - (a.last || 0) || (a.ccy < b.ccy ? -1 : 1);
      });
      D.rows = rows;
      var big = rows.filter(function (r) { return r.ccy === BIG_CCY; })[0];
      var v = big ? big.cells[big.cells.length - 1] : null;
      D.big = v == null ? null : { value: v, country: big.country };
      S.i = D.days.length - 1;
    } else {
      D.heat = null;
    }
    var R = D.record;
    if (R && R.days) {
      R.byDay = {};
      R.days.forEach(function (d) { R.byDay[d.day] = d; });
      if (!D.days) { D.days = R.days.map(function (d) { return d.day; }); S.i = D.days.length - 1; }
    }
    if (D.milestones) { D.milestones = D.milestones.milestones || []; }
    if (D.findings) { D.findings = D.findings.findings || []; }
  }

  function build() {
    var app = document.getElementById('app');
    app.textContent = '';
    var wrap = el('div', 'hp-wrap');
    header(wrap);
    hero(wrap);
    if (D.days) { counters(wrap); }
    cycleSection(wrap);
    if (D.days) { heatSection(wrap); }
    if (D.days) { recordSection(wrap); }
    lowerSections(wrap);
    if (D.failed.length && has('loadError')) {
      wrap.appendChild(el('p', ['muted', 'hp-note'], t('loadError', { n: D.failed.length })));
    }
    app.appendChild(wrap);
    if (D.days) { set(S.i); }
    if (D.placeMarks) {
      D.placeMarks();
      var rt = null;
      window.addEventListener('resize', function () { clearTimeout(rt); rt = setTimeout(D.placeMarks, 120); });
      if (document.fonts && document.fonts.ready) { document.fonts.ready.then(D.placeMarks); }
    }
  }

  var jobs = {
    heat: 'data/heatmap_daily.json', record: 'data/record_daily.json', cycles: 'data/cycle_log.json',
    milestones: 'data/record_milestones.json', movers: 'data/movers_week.json', findings: 'data/findings.json'
  };
  D.failed = [];
  Promise.all([getJSON('copy.json').catch(function () { return {}; })].concat(Object.keys(jobs).map(function (k) {
    return getJSON(jobs[k]).catch(function () { D.failed.push(k); return null; });
  }))).then(function (res) {
    C = (res[0] && res[0].homeData) || {};
    Object.keys(jobs).forEach(function (k, q) { D[k] = res[q + 1]; });
    if (has('metaDescription')) {
      var m = document.querySelector('meta[name="description"]');
      if (m) { m.setAttribute('content', C.metaDescription); }
    }
    prepare();
    build();
  });
})();

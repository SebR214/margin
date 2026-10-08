/* The home page, built from stored files only (SEB-240).
 *
 * Numbers, dates, currency codes and stored ids come from data/*.json.
 * Every word comes from copy.json "homeData". A key that is empty (or missing)
 * is not rendered. No word is written in this file.
 *
 * Reads: data/heatmap_daily.json, record_daily.json, cycle_log.json,
 * movers_week.json, routes_summary.json, copy.json.
 * The "This hour" and "The record grew" blocks live in js/cycle_block.js and
 * js/record_block.js.
 */
(function () {

  var HEAT_STEPS = [2, 8, 25, 50]; // gap thresholds in percent; the legend shows these numbers
  var BIG_CCY = 'DZD';             // the page's one big number
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
    return new Date(day + 'T00:00:00Z').toLocaleDateString('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC' }).replace('Sept', 'Sep');
  }
  function dLong(day) {
    return new Date(day + 'T00:00:00Z').toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' }).replace('Sept', 'Sep');
  }
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
    if (g < 0 && has('legendBelowOfficial')) { return 'hb'; }
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
      var a = word(right, 'span', null, 'headerLast', function () { return { time: dShort(CL.last_reading_utc.slice(0, 10)) + ', ' + CL.last_reading_utc.slice(11, 16) }; });
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
        var late = Math.max(1, Math.round(s / 60));
        b.textContent = over ? t(late === 1 ? 'headerOverdueOne' : 'headerOverdue', { minutes: late }) : t('headerNext', { countdown: cd });
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
  function currencyCount() {
    var R = D.record, st = D.cycles && D.cycles.steps;
    if (R && R.totals && R.totals.currencies != null) { return R.totals.currencies; }
    return st && st.currencies ? st.currencies.of : null;
  }
  /* headline, what the site is, the one big number, subhead, updated line */
  function hero(wrap) {
    var s = el('section', ['hp-hero', 'hero', 'bleed']);
    word(s, 'h1', null, 'headline', totalsVars);
    var cc = currencyCount();
    if (cc != null) { word(s, 'p', ['soft', 'hp-lede'], 'whatLine', function () { return { currencies: num(cc) }; }); }
    if (D.big) {
      var bigBox = el('div', 'hp-bigbox');
      var href = 'country.html?ccy=' + encodeURIComponent(BIG_CCY);
      var a = el('a', ['mono', 'hp-big']);
      a.href = href;
      a.textContent = num(D.big.value, 0) + '%';
      bigBox.appendChild(a);
      var bv = function () { return { country: D.big.country, ccy: BIG_CCY, date: dShort(D.days[D.days.length - 1]), gap: num(D.big.value, 1) }; };
      word(bigBox, 'span', 'soft', 'bigCaption', bv);
      var ln = word(bigBox, 'a', 'hp-biglink', 'bigLink', bv);
      if (ln) { ln.href = href; }
      s.appendChild(bigBox);
    }
    word(s, 'p', ['soft', 'hp-lede'], 'headlineSub', totalsVars);
    var cs = D.cycles && D.cycles.steps && D.cycles.steps.currencies;
    if (cs && claimOk('homeData.updatedLine')) { word(s, 'p', ['muted', 'hp-body'], 'updatedLine', function () { return { collected: num(cs.collected), of: num(cs.of) }; }); }
    if (s.childNodes.length) { wrap.appendChild(s); }
  }
  /* ---------------------------------------------------------------- heatmap */
  function heatSection(wrap) {
    var H = D.heat;
    if (!H) { return; }
    var n = D.days.length;
    var sec = el('section', ['hp-sec', 'hp-gap24']);
    var head = el('div', 'hp-intro');
    // Only render heatTitle if claims are loaded and it's not blocked
    if (claimOk('homeData.heatTitle')) {
      word(head, 'h2', null, 'heatTitle');
    }
    word(head, 'p', ['muted', 'hp-body'], 'heatLine');
    if (head.childNodes.length) { sec.appendChild(head); }

    var row = el('div', 'hp-row');
    var main = el('div', ['hp-main', 'hp-rel']);
    var tip = el('div', ['hp-tip', 'mono']);
    tip.hidden = true;
    var unranked = [];
    var LIMIT = has('heatShowAll') ? 20 : D.rows.length;
    var hidden = [];
    var cols = [];
    for (var d = 0; d < n; d++) { cols.push([]); }
    D.cols = cols;

    /* The grid starts at the first day most currencies have a price; earlier days sit behind a toggle
       (only when the toggle has words, otherwise every day shows). */
    var FIRST = 0;
    if (has('heatEarlier')) {
      for (var dd = 0; dd < n; dd++) {
        var cnt = D.rows.filter(function (r) { return r.cells[dd] != null; }).length;
        if (cnt * 2 >= D.rows.length) { FIRST = dd; break; }
      }
    }
    D.first = FIRST;
    D.view = FIRST;

    /* controls: Play and slider above the map */
    var ctlAbove = el('div', 'hp-controls-above');
    if (has('heatPlay')) {
      var btn = el('button', 'hp-btn');
      btn.type = 'button';
      var label = function () { btn.textContent = S.playing ? (t('heatPause') || t('heatPlay')) : t('heatPlay'); };
      label();
      btn.addEventListener('click', function () { toggle(label); });
      ctlAbove.appendChild(btn);
    }
    var lab = el('label', ['muted', 'hp-slider']);
    var cap = el('span');
    var run = function () { cap.textContent = t('heatDay', { date: dayLabel(S.i) }); };
    run(); updaters.push(run);
    if (has('heatDay')) { lab.appendChild(cap); }
    var rg = el('input');
    rg.type = 'range'; rg.min = String(FIRST); rg.max = String(n - 1); rg.value = String(S.i);
    if (has('heatSlider')) { rg.setAttribute('aria-label', t('heatSlider')); }
    rg.addEventListener('input', function () { stop(); set(+rg.value); });
    D.range = rg;
    lab.appendChild(rg);
    ctlAbove.appendChild(lab);
    if (FIRST > 0) {
      var earlier = el('button', 'hp-btn', t('heatEarlier', { n: num(FIRST) }));
      earlier.type = 'button';
      earlier.addEventListener('click', function () {
        D.view = D.view === 0 ? FIRST : 0;
        applyView();
      });
      ctlAbove.appendChild(earlier);
    }
    main.appendChild(ctlAbove);

    var scroller = el('div', 'hp-scroll');
    var gridwrap = el('div', 'hp-gridwrap');
    var grid = el('div', 'hp-heat');
    var marker = el('div', 'hp-marker');
    D.marker = marker;
    D.scroller = scroller;
    D.gridwrap = gridwrap;

    D.rows.forEach(function (cur, ri) {
      var r = el('div', 'hp-hmrow');
      if (ri >= LIMIT) { r.hidden = true; hidden.push(r); }
      ccyLink(r, cur.ccy, ['hp-code', 'mono']);
      var cells = el('div', 'hp-cells');
      cells.setAttribute('data-ccy', cur.ccy);
      for (var k = 0; k < n; k++) {
        var s = el('span', cur.ranked ? colourClass(cur.cells[k]) : 'hu');
        cells.appendChild(s);
        cols[k].push(s);
      }
      r.appendChild(cells);
      grid.appendChild(r);
      if (!cur.ranked) { unranked.push(cur); }
      cells.addEventListener('mousemove', function (ev) {
        var b = cells.getBoundingClientRect();
        var vis = n - D.view;
        var k2 = D.view + Math.max(0, Math.min(vis - 1, Math.floor((ev.clientX - b.left) / b.width * vis)));
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
    gridwrap.appendChild(marker);
    gridwrap.appendChild(grid);
    scroller.appendChild(gridwrap);
    main.appendChild(scroller);
    if (hidden.length) {
      var more = el('button', ['hp-btn', 'hp-more'], t('heatShowAll', { n: num(D.rows.length) }));
      more.type = 'button';
      more.addEventListener('click', function () { hidden.forEach(function (h) { h.hidden = false; }); more.hidden = true; placeMarker(); });
      main.appendChild(more);
    }
    main.appendChild(tip);
    unranked.forEach(function (cur) {
      word(main, 'p', ['muted', 'hp-note'], 'unrankedNote', function () { return { ccy: cur.ccy, country: cur.country }; });
    });
    window.addEventListener('resize', placeMarker);

    row.appendChild(main);

    var side = el('aside', 'hp-side');
    // widest gaps on the selected day
    var topBox = el('div', 'hp-topbox');
    word(topBox, 'span', ['muted', 'hp-small'], 'topTitle', function () { return { date: dayLabel(S.i) }; });
    var tops = [];
    for (var q = 0; q < 6; q++) {
      var tr = el('div', 'hp-toprow');
      var code = el('a', ['mono', 'hp-topcode']);
      var val = el('span', ['mono', 'hp-topval']);
      var pl = el('span', ['soft', 'hp-small', 'hp-topprice']);
      var track = el('span', 'hp-bar');
      var fill = el('i');
      track.appendChild(fill);
      tr.appendChild(code); tr.appendChild(track); tr.appendChild(val); tr.appendChild(pl);
      topBox.appendChild(tr);
      tops.push({ row: tr, code: code, val: val, price: pl, fill: fill });
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
    items.unshift({ cls: 'khb', key: 'legendBelowOfficial', vars: {} });
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

  // The price line under a ranking row needs the country's own file; fetched once, then the rows repaint.
  function loadCountry(ccy) {
    D.cfile = D.cfile || {};
    if (D.cfile[ccy] !== undefined) { return; }
    D.cfile[ccy] = null;
    getJSON('data/countries/' + encodeURIComponent(ccy) + '.json').then(function (d) { D.cfile[ccy] = d; paintHeat(); }).catch(function () {});
  }

  /* Shows the days from D.view on; the slider and the marker follow. */
  function applyView() {
    D.cols.forEach(function (col, k) { col.forEach(function (c) { c.hidden = k < D.view; }); });
    if (D.range) { D.range.min = String(D.view); }
    set(Math.max(S.i, D.view));
  }
  /* One thin vertical line across the grid at the selected day, with a short tick above the first row. */
  function placeMarker() {
    var m = D.marker, first = D.cols && D.cols[S.i] && D.cols[S.i][0];
    if (!m || !first || first.hidden) { if (m) { m.hidden = true; } return; }
    var w = D.gridwrap.getBoundingClientRect(), c = first.getBoundingClientRect();
    if (!c.width) { return; }
    m.hidden = false;
    m.style.left = (c.left - w.left + c.width / 2 - 0.5) + 'px';
    var sc = D.scroller;
    if (sc && sc.scrollWidth > sc.clientWidth) {
      var x = c.left - sc.getBoundingClientRect().left + sc.scrollLeft;
      if (x < sc.scrollLeft + 60 || x > sc.scrollLeft + sc.clientWidth - 20) { sc.scrollLeft = Math.max(0, x - sc.clientWidth / 2); }
    }
  }

  function paintHeat() {
    var i = S.i;
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
        tp.val.textContent = num(c.cells[i], 0) + '%';
        // square-root scale: one very wide gap no longer flattens the other five into stubs
        tp.fill.style.width = Math.max(4, Math.sqrt(c.cells[i] / max) * 100).toFixed(1) + '%';
        var pr = D.cfile && D.cfile[c.ccy];
        if (has('topPriceLine') && !pr && i === lastIndex()) { loadCountry(c.ccy); }
        tp.price.textContent = (pr && pr.buy_price != null && pr.fx_mid_per_usd != null && has('topPriceLine') && i === lastIndex()) ? t('topPriceLine', { price: num(pr.buy_price, pr.buy_price >= 100 ? 0 : 2), ccy: c.ccy, rate: num(pr.fx_mid_per_usd, pr.fx_mid_per_usd >= 100 ? 0 : 2) }) : '';
      });
    }
    if (D.range) { D.range.value = String(i); }
    placeMarker();
  }

  /* ---------------------------------------------------------------- replay */
  function set(i) {
    S.i = i;
    paintHeat();
    updaters.forEach(function (u) { u(); });
  }
  function stop() { if (timer) { clearInterval(timer); timer = null; } S.playing = false; }
  function toggle(relabel) {
    if (timer) { stop(); relabel(); return; }
    if (S.i >= lastIndex()) { set(D.view || 0); }
    S.playing = true; relabel();
    timer = setInterval(function () {
      if (S.i >= lastIndex()) { stop(); relabel(); return; }
      set(S.i + 1);
      if (S.i >= lastIndex()) { stop(); relabel(); }
    }, 160);
  }

  /* ---------------------------------------------------------------- findings strip + Singapore to the Philippines */
  // A claim-guarded line renders only when the claims gate loaded and says the claim holds.
  function claimOk(key) { return !!(window.Claims && window.Claims.blocked && !window.Claims.blocked(key)); }

  // Each published finding's number is read from data/findings.json (headline.value); a finding whose copy slot is empty is not shown.
  function findingValue(f) {
    var v = f.headline && f.headline.value;
    if (v == null) { return ''; }
    return v >= 1e6 ? num(v / 1e6, 1) + 'M' : num(v, 0);
  }
  function findingsStrip(wrap) {
    var F = D.findings;
    var lines = [];
    if (F && F.findings) {
      F.findings.forEach(function (f) {
        if (f.published === false) { return; }
        var text = t('finding_' + f.id, { value: findingValue(f) });
        if (text) { lines.push(text); }
      });
    }
    var sg = sgPhLines();
    if (!lines.length && !sg) { return; }
    var sec = el('section', ['hp-sec', 'hp-findings-sec']);
    word(sec, 'h2', null, 'findingsTitle');
    if (lines.length) {
      var box = el('div', 'hp-findings');
      lines.forEach(function (x) { box.appendChild(el('p', 'hp-finding', x)); });
      sec.appendChild(box);
    }
    if (sg) {
      var sub = el('div', 'hp-sgph');
      word(sub, 'h3', 'hp-subhead', 'sgPhTitle');
      sub.appendChild(sg);
      sec.appendChild(sub);
    }
    wrap.appendChild(sec);
  }

  /* One stablecoin statement, for SGD->PHP only, and only while the stored claim is true:
     total_hours_stable_cheapest must be 0. Any other value renders nothing. */
  function sgPhLines() {
    var RS = D.routes;
    if (!RS || !RS.routes) { return null; }
    var r = RS.routes.filter(function (x) { return x.id === 'SGD->PHP'; })[0];
    if (!r || r.total_hours_stable_cheapest !== 0 || typeof r.hours_priced_any_amount !== 'number' || !RS.start) { return null; }
    var box = el('div', 'hp-sgline');
    var vars = function () { return { hours: num(r.hours_priced_any_amount), since: dLong(RS.start) }; };
    if (claimOk('homeData.stableLine')) { word(box, 'p', ['soft', 'hp-body'], 'stableLine', vars); }
    if (claimOk('homeData.stableLink')) {
      var a = word(box, 'a', 'hp-biglink', 'stableLink', vars);
      if (a) { a.href = './sending-money.html'; }
    }
    return box.childNodes.length ? box : null;
  }

  /* ---------------------------------------------------------------- what moved */
  function moversSection(wrap) {
    var M = D.movers;
    if (!M || !M.top || !M.top.length) { return; }
    var sec = el('section', 'hp-sec');
    word(sec, 'h2', null, 'moversTitle');
    var list = el('div', 'hp-listbox');
    M.top.slice(0, 4).forEach(function (m) {
      var a = el('a', 'hp-mover');
      a.href = 'country.html?ccy=' + encodeURIComponent(m.ccy);
      a.appendChild(el('span', ['mono', 'hp-movercode'], m.ccy));
      // baseline window: every day before the last 7 (movers_week.json "definition")
      var n = D.days ? D.days.length : 0;
      var li = D.days ? D.days.indexOf(M.last_day) : -1;
      if (li < 0) { li = n - 1; }
      var hrow = (D.rows || []).filter(function (r) { return r.ccy === m.ccy; })[0];
      var since = '', until = '';
      if (hrow && li - 7 >= 0) {
        for (var q = 0; q <= li - 7; q++) { if (hrow.cells[q] != null) { since = dShort(D.days[q]); break; } }
        until = dShort(D.days[li - 7]);
      }
      var dir = function (v) { return t(v < 0 ? 'dirBelow' : 'dirAbove'); };
      var line = t('moverLine', {
        country: m.country, baseline: num(Math.abs(m.earlier_median_pct), 1) + '%', baselineDir: dir(m.earlier_median_pct),
        recent: num(Math.abs(m.recent_median_pct), 1) + '%', recentDir: dir(m.recent_median_pct), since: since, until: until
      });
      a.appendChild(el('span', ['soft', 'hp-moverline'], line));
      var diff = Math.round(m.recent_median_pct * 10) / 10 - Math.round(m.earlier_median_pct * 10) / 10;
      a.appendChild(el('span', ['mono', 'hp-moverdiff'], (diff < 0 ? '-' : '+') + num(Math.abs(diff), 1)));
      list.appendChild(a);
    });
    sec.appendChild(list);
    wrap.appendChild(sec);
  }

  /* ---------------------------------------------------------------- the record so far */
  function recordSection(wrap) {
    if (!D.record || !D.record.days || typeof window.renderRecordBlock !== 'function') { return; }
    var box = el('div', 'hp-recordwrap');
    wrap.appendChild(box);
    window.renderRecordBlock(box, D.record, D.milestones, C);
    if (!box.childNodes.length) { box.remove(); }
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

      // Filter out currencies with no readings on any day (AFN, AOA, BWP, ETB, GHS, NPR, XOF)
      rows = rows.filter(function (r) {
        // Check if currency has any non-null values
        var hasReading = r.cells.some(function (cell) { return cell != null; });
        return hasReading;
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
  }

  function build() {
    var app = document.getElementById('app');
    app.textContent = '';
    var wrap = el('div', 'hp-wrap');
    header(wrap);
    hero(wrap);
    if (D.days) { heatSection(wrap); }
    moversSection(wrap);
    findingsStrip(wrap);
    recordSection(wrap);
    if (D.failed.length && has('loadError')) {
      wrap.appendChild(el('p', ['muted', 'hp-note'], t('loadError', { n: D.failed.length })));
    }
    app.appendChild(wrap);
    if (D.days) { if (D.view > 0) { applyView(); } else { set(S.i); } }
    if (D.heat && D.scroller) { D.scroller.scrollLeft = D.scroller.scrollWidth; placeMarker(); }
  }

  var jobs = {
    heat: 'data/heatmap_daily.json', record: 'data/record_daily.json', cycles: 'data/cycle_log.json',
    movers: 'data/movers_week.json', routes: 'data/routes_summary.json', findings: 'data/findings.json',
    milestones: 'data/record_milestones.json'
  };
  D.failed = [];
  // Load claims and data in parallel
  Promise.all([
    getJSON('copy.json').catch(function () { return {}; }),
    window.Claims && typeof window.Claims.load === 'function' ? window.Claims.load().catch(function () { return null; }) : Promise.resolve(null)
  ].concat(Object.keys(jobs).map(function (k) {
    return getJSON(jobs[k]).catch(function () { D.failed.push(k); return null; });
  }))).then(function (res) {
    C = (res[0] && res[0].homeData) || {};
    var claimsData = res[1]; // claims data is the second item
    var dataOffset = 2; // data files start at index 2
    Object.keys(jobs).forEach(function (k, q) { D[k] = res[q + dataOffset]; });
    if (has('metaDescription')) {
      var m = document.querySelector('meta[name="description"]');
      if (m) { m.setAttribute('content', C.metaDescription); }
    }
    prepare();
    // Pass whether claims loaded successfully to build function
    build();
  });
})();

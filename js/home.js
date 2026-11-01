/* Home (SEB-268), built to the approved reference.
 * Reads data/heatmap_daily.json, data/index_latest.json, data/findings.json,
 * data/record_daily.json (the totals line), data/sources_daily.json and copy.json (homeData). The time control is js/home_timeline.js's (SEB-384). The header clock is js/site_head.js's.
 * Every figure is read from those files at render time; every word is a homeData key. Dates, numbers and names are formatted here. */
(function () {
  var MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  var MINUS = '−';
  var C = {}, D = {};
  var showAll = false, early = false;
  var NAV = [['navCountries', 'countries.html'], ['navRoutes', 'sending-money.html'], ['navSources', 'sources.html'], ['navResearch', 'research.html'], ['navEvents', 'events.html'], ['navHow', 'how-it-works.html']];
  var BUCKETS = [
    [-Infinity, 0, 'b-neg', 'legendBelowOfficial'],
    [0, 2, 'b0', 'legendUnder', { max: 2 }],
    [2, 8, 'b1', 'legendBetween', { min: 2, max: 8 }],
    [8, 25, 'b2', 'legendBetween', { min: 8, max: 25 }],
    [25, 50, 'b3', 'legendBetween', { min: 25, max: 50 }],
    [50, Infinity, 'b4', 'legendOver', { min: 50 }]
  ];

  function $(id) { return document.getElementById(id); }
  function T(k, v) { var s = C[k]; return typeof s === 'string' && s ? s.replace(/\{(\w+)\}/g, function (m, x) { return v && v[x] != null ? v[x] : ''; }) : ''; }
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function approx(v) { return v >= 1e6 ? (v / 1e6).toFixed(1) + 'M' : g(v); }   // the template carries the S$
  function g(n) { return Math.round(n).toLocaleString('en-US'); }
  function dd(s) { return (+s.slice(8, 10)) + ' ' + MON[+s.slice(5, 7) - 1]; }
  function pct1(v) { return (Math.abs(v) >= 100 ? g(Math.abs(v)) : Math.abs(v).toFixed(1)) + '%'; }
  function sgn(v) { return (v > 0 ? '+' : v < 0 ? MINUS : '') + pct1(v); }
  function bucket(v) { if (v == null) { return 'b-none'; } for (var i = 0; i < BUCKETS.length; i++) { if (v >= BUCKETS[i][0] && v < BUCKETS[i][1]) { return BUCKETS[i][2]; } } return 'b-none'; }
  function plain(name) { return String(name || '').replace(/^the /i, '').replace(/^./, function (c) { return c.toUpperCase(); }); }
  function getJSON(u) { return fetch(u, { cache: 'no-store' }).then(function (r) { if (!r.ok) { throw new Error(u); } return r.json(); }); }
  function ctry(ccy) { return './country/' + encodeURIComponent(String(ccy).toLowerCase()) + '/'; }
  // Same words as whatLine, just split into two lines (SEB-301, 21 Oct): "We track... had a price." then "We also price...".
  function leadSpans(s) {
    var at = s.indexOf('every hour. ');
    if (at < 0) { return esc(s); }
    at += 'every hour. '.length;
    return '<span class="s">' + esc(s.slice(0, at).trim()) + '</span> <span class="s">' + esc(s.slice(at).trim()) + '</span>';
  }
  function lastValue(c) { for (var i = c.cells.length - 1; i >= 0; i--) { if (c.cells[i] != null) { return c.cells[i]; } } return null; }
  // Fast lane (SEB-301, 21 Oct): a country with no price on any of the last 30 days comes off the map and out of every count.
  function pricedInLast30(cells) { return cells.slice(Math.max(0, cells.length - 30)).some(function (v) { return v != null; }); }

  /* ---------------------------------------------------------------- header nav, words
     (the header status is js/site_head.js's) */
  function nav() {
    var n = $('nav');
    // built once: load() runs again every new hour in an open tab, and appending each time repeated the links (25 Oct)
    if (n.querySelector('a')) { return; }
    NAV.forEach(function (x) {
      var t = T(x[0]); if (!t) { return; }
      var a = document.createElement('a'); a.textContent = t; a.href = './' + x[1]; n.appendChild(a);
    });
  }

  /* ---------------------------------------------------------------- the computed headline and the week's changes (SEB-423)
     data/home_facts.json is built by tools/emit_home_facts.py; each sentence shows only while data/claims_status.json says the facts
     match their source files (Claims). With no facts, a failed claim or a move of 1 point or less, the fixed headline stays. */
  function blocked(k) { return !window.Claims || window.Claims.blocked('homeData.' + k); }
  function longDate(s) { return (+s.slice(8, 10)) + ' ' + MON[+s.slice(5, 7) - 1]; }
  function nameOf(ccy) {
    var c = ((D.heat && D.heat.currencies) || []).filter(function (x) { return x.ccy === ccy; })[0];
    return c ? plain(c.country) : ccy;
  }
  function moveFacts() {
    var m = D.facts && D.facts.largest_move;
    return m && !blocked('headlineMove') ? m : null;
  }
  // The move leads the page only when it takes the gap away from its usual level, by a point or more (1 Nov, Seb: a move back
  // to normal is not news). Said as the level now and yesterday, so the reader sees what a dollar costs, not a change in points.
  function awayMove() {
    var m = moveFacts(); if (!m || m.now_pct == null || m.typical_pct == null) { return null; }
    var from = m.direction === 'dearer' ? m.now_pct - m.points : m.now_pct + m.points;
    var away = m.direction === 'dearer' ? m.now_pct > m.typical_pct : m.now_pct < m.typical_pct;
    if (!away || Math.abs(m.now_pct - m.typical_pct) < 1 || m.now_pct < 0 || from < 0 || m.typical_pct < 0) { return null; }
    return { m: m, from: from };
  }
  function moveHeadline() {
    if (T('headlineAwayUp')) {
      var a = awayMove(); if (!a) { return ''; }
      var hk = a.m.direction === 'dearer' ? 'headlineAwayUp' : 'headlineAwayDown';
      return blocked('headlineMove') ? '' : T(hk, { country: plain(a.m.country), now: a.m.now_pct.toFixed(1) + '%', from: a.from.toFixed(1) + '%' });
    }
    var m = moveFacts(); if (!m) { return ''; }
    var k = m.direction === 'dearer' ? 'headlineMoveUp' : 'headlineMoveDown';
    return blocked(k) ? '' : T(k, { country: plain(m.country), points: m.points.toFixed(1) });
  }
  function moveSince() {
    if (T('moveUsual')) {
      var a = awayMove(); if (!a || !moveHeadline()) { return ''; }
      return '<p class="lead sub">' + esc(T('moveUsual', { typical: Math.round(a.m.typical_pct) + '%' })) + '</p>';
    }
    var m = moveFacts(); if (!m || !moveHeadline() || m.side === 'at') { return ''; }
    var k = m.since_whole_window ? (m.side === 'above' ? 'moveSinceWholeAbove' : 'moveSinceWholeBelow') : (m.side === 'above' ? 'moveSinceAbove' : 'moveSinceBelow');
    var t = blocked(k) ? '' : T(k, { date: m.since ? longDate(m.since) : '' });
    return t ? '<p class="lead sub">' + esc(t) + '</p>' : '';
  }
  // The writer's daily sentences (SEB-423 step 4), from data/home_prose.json: shown under the headline, in place of the
  // "since" line, only when the number audit passed, any voice check passed, and the file is under 30 hours old.
  // Otherwise the page shows what it showed before.
  function dailyProse() {
    var p = D.prose;
    if (!p || !p.audit || p.audit.passed !== true || (p.voice && p.voice.passed !== true) || !Array.isArray(p.sentences)) { return ''; }
    var a = awayMove();
    if (!a || !p.about_ccy || p.about_ccy !== a.m.ccy) { return ''; }   // written for the headline on the page now, or not shown
    var t = Date.parse(p.written_utc || '');
    if (!(t > 0) || Date.now() - t > 30 * 3600e3) { return ''; }
    var lines = p.sentences.filter(function (x) { return typeof x === 'string' && x.trim(); }).slice(0, 2);
    return lines.length ? '<p class="lead sub today">' + esc(lines.join(' ')) + '</p>' : '';
  }
  function changeLine(it) {
    var v = { date: longDate(it.date) }, k = '', FD = (D.copy && D.copy.findingData) || {}, RN = (D.copy && D.copy.routeNames) || {};
    if (it.kind === 'crossed_up') { k = 'wcCrossedUp'; v.country = it.country; }
    else if (it.kind === 'crossed_down') { k = 'wcCrossedDown'; v.country = it.country; }
    else if (it.kind === 'event') { k = it.event_kind === 'street_slide' ? 'wcEventStreet' : 'wcEventOfficial'; v.country = nameOf(it.ccy); v.pct = Math.round(it.pct) + '%'; }
    else if (it.kind === 'source_added') { k = it.status === 'quarantine' ? 'wcSourceQuarantine' : 'wcSourceAdded'; v.source = it.source; }
    else if (it.kind === 'finding_changed') { k = { holds: 'wcFindingHolds', weaker: 'wcFindingWeaker', no_longer_true: 'wcFindingNoLonger' }[it.to]; v.title = String(FD['title_' + it.id] || '').replace(/\{\w+\}/g, '').trim(); if (!v.title) { return null; } }
    else if (it.kind === 'route_flip') { k = it.now === 'cheaper' ? 'wcRouteCheaper' : 'wcRouteDearer'; v.route = (RN[it.route] || {}).fromTo; if (!v.route) { return null; } }
    if (!k || blocked(k) || !T(k)) { return null; }
    return '<a class="r f" href="./' + esc(it.link) + '"><span class="m">' + esc(T(k, v)) + '</span><span class="v">' + esc(v.date) + '</span></a>';
  }
  function whatChanged() {
    var el = $('wc'); if (!el) { return; }
    var f = D.facts;
    if (!f || !T('whatChangedTitle') || blocked('whatChangedTitle')) { el.innerHTML = ''; return; }
    var lines = (f.what_changed || []).map(changeLine).filter(Boolean);
    el.innerHTML = '<h2>' + esc(T('whatChangedTitle')) + '</h2>' +
      (lines.length ? '<div class="rows">' + lines.join('') + '</div>' : '<p class="note">' + esc(T('whatChangedEmpty')) + '</p>');
  }

  /* ---------------------------------------------------------------- hero: what the site is, with the totals from record_daily.json */
  function hero() {
    var tt = D.rec.totals || {};
    // same counts as the Countries page, from index_latest.json: priced = this hour's count. tracked = countries with a
    // price on at least one of the last 30 days (SEB-301, 21 Oct), the same count the "Countries tracked" counter uses.
    var ix = D.idx || {}, nPriced = (ix.countries || []).length;
    var nTracked = D.heat.countries_tracked;
    var idxCount = { priced: g(nPriced), tracked: g(nTracked) };
    // one per row, as the Sources page lists them: the CriptoYa feeds count once
    // the sources behind the stored-prices count, and every source read each hour (the Sources page's own count, CriptoYa's
    // feeds as one), so the line says plainly that the count covers some of them (1 Nov: home said 41, Sources said 49)
    var grp = function (list) { return list ? list.filter(function (s) { return s.live && !/^CriptoYa/.test(s.id); }).length + (list.some(function (s) { return s.live && /^CriptoYa/.test(s.id); }) ? 1 : 0) : null; };
    var all = (D.src && D.src.sources) || null;
    var sr = all ? all.filter(function (s) { return (s.files || []).every(function (f) { return f !== 'cash_rates/' && f !== 'p2p_basis_boards.csv'; }); }) : null;
    var nSources = grp(sr), nAll = grp(all);
    var h = '<h1>' + esc(moveHeadline() || T('headline')) + '</h1>' + (dailyProse() || moveSince()) +
      (T('heroWhy') ? '<p class="lead sub">' + esc(T('heroWhy')) + '</p>' : '') +
      '<p class="lead what">' + esc(T('whatLine', { tracked: idxCount.tracked, priced: idxCount.priced, routes: tt.routes })) + '</p>' +
      // who built it and what is stored so far, as one line (21 Oct, Seb's wording); the numbers come from the files
      // the line links to How it was built (1 Nov)
      '<p class="body agents"><a href="./how-it-was-built.html">' + esc(T('agentsLine')) + (T('agentsStored') && nSources != null && tt.readings != null && tt.hours_collected != null ? ' ' +
        esc(T('agentsStored', { readings: '\u0001', sources: '\u0002', hours: '\u0003', all: '\u0004' })).replace('\u0001', g(tt.readings)).replace('\u0002', String(nSources)).replace('\u0004', String(nAll)).replace('\u0003', g(tt.hours_collected)) : '') + '</a></p>';
    $('hero').innerHTML = h;
    $('hero').style.display = 'flex'; $('hero').style.flexDirection = 'column';
  }

  /* ---------------------------------------------------------------- the map: one row per country, one square per day, sorted by this hour's figure */
  function build() {
    var days = D.heat.days || [];
    var byCcy = {};
    ((D.idx && D.idx.countries) || []).forEach(function (c) { byCcy[c.ccy] = c; });
    D.days = days;
    var all = (D.heat.currencies || []).map(function (c) {
      var i = byCcy[c.ccy];
      return { ccy: c.ccy, country: plain(c.country), ranked: c.ranked !== false, cells: c.cells || [],
        now: i && i.index_pct != null ? Math.round(i.index_pct * 10) / 10 : null,
        buy: i ? i.buy_price : null, rate: i ? i.fx_mid_per_usd : null };
    });
    // a country with no price on any of the last 30 days comes off the map and out of every count (SEB-301, 21 Oct)
    D.cur = all.filter(function (c) { return pricedInLast30(c.cells); });
    D.never30 = all.filter(function (c) { return !pricedInLast30(c.cells); });
    // priced countries first, by this hour's figure; countries with no price this hour sit below them (SEB-268, 11 Oct),
    // ordered by their last stored day so the order does not jump
    D.ranked = D.cur.filter(function (c) { return c.ranked; }).sort(function (a, b) {
      if ((a.now != null) !== (b.now != null)) { return a.now != null ? -1 : 1; }
      var av = a.now != null ? a.now : (lastValue(a) != null ? lastValue(a) : -1e9), bv = b.now != null ? b.now : (lastValue(b) != null ? lastValue(b) : -1e9);
      return bv - av;
    });
    D.unranked = D.cur.filter(function (c) { return !c.ranked; });
  }

  // a mark on rows where a stablecoin is the cheaper dollar than cash at a money changer (SEB-424 item 1, 1 Nov). Same two numbers
  // and the same rules as the country page: a cash reading within 6 hours of the hour, and a difference of at least 0.5%.
  function cashMark(ccy) {
    var cash = D.cash && D.cash.rows && D.cash.rows[ccy], c = ((D.idx && D.idx.countries) || []).filter(function (x) { return x.ccy === ccy; })[0];
    if (!cash || !c || !c.buy_price || !cash.mid || !T('cashMarkTip')) { return ''; }
    if (Date.parse(c.hour_utc) - Date.parse(cash.ts_utc) > 6 * 3600 * 1000) { return ''; }
    var cs = (c.buy_price / cash.mid - 1) * 100;
    if (cs > -0.5) { return ''; }
    return '<b class="cmark" data-tip="' + esc(T('cashMarkTip', { pct: ((cash.mid / c.buy_price - 1) * 100).toFixed(1) + '%' })) + '" aria-label="' + esc(T('cashMarkTip', { pct: ((cash.mid / c.buy_price - 1) * 100).toFixed(1) + '%' })) + '"></b>';
  }

  function heat() {
    var vw = tlView();
    if (vw) { heatTl(vw); return; }
    var rows = showAll ? D.ranked : D.ranked.slice(0, 20);
    var s0 = early ? 0 : Math.max(0, D.days.length - 30), days = D.days.slice(s0), n = days.length;
    var X = function (i) { return (i + 0.5) / n * 100; };
    var ax = '<span class="l" style="left:0">' + dd(days[0]) + '</span>';
    days.forEach(function (d, i) { if ((d.slice(8) === '01' || d.slice(8) === '15') && i > 3 && i < n - 4) { ax += '<span style="left:' + X(i) + '%">' + dd(d) + '</span>'; } });
    var row = function (c, extra) {
      return '<a class="hrow' + (extra || '') + '" href="' + ctry(c.ccy) + '" data-ccy="' + esc(c.ccy) + '"><span class="nm">' + esc(c.country) + cashMark(c.ccy) + '</span><span class="cells">' +
        c.cells.slice(s0).map(function (v, i) { return '<i class="' + (c.ranked ? bucket(v) : (v == null ? 'b-none' : 'b-frozen')) + '" data-i="' + (i + s0) + '"></i>'; }).join('') +
        '</span><span class="v num">' + (c.now != null ? sgn(c.now) : '<small>' + esc(T('noPrice')) + '</small>') + '</span></a>';
    };
    $('heat').innerHTML =
      '<p class="key">' + BUCKETS.map(function (b) { return '<span><i class="' + b[2] + '"></i>' + esc(T(b[3], b[4])) + '</span>'; }).join('') + '<span><i class="b-none"></i>' + esc(T('legendNone')) + '</span>' +
        (rows.some(function (c) { return cashMark(c.ccy); }) && T('cashMarkKey') ? '<span><b class="cmark"></b>' + esc(T('cashMarkKey')) + '</span>' : '') + '</p>' +
      '<div class="hax"><span></span><div class="ax num">' + ax + '</div><span class="axh">' + esc(T('dayToday')) + '</span></div>' +
      rows.map(function (c) { return row(c); }).join('') +
      // the unranked country closes the full list as a grey row, so "Show all" counts every country tracked
      (showAll ? D.unranked.map(function (c) { return row(c, ' frozen'); }).join('') : '') +
      '<div class="pills hb">' + (showAll ? '' : '<button class="pill" type="button" id="all">' + esc(T('heatShowAll', { n: D.cur.length })) + '</button>') +
      (early ? '' : '<button class="pill" type="button" id="early">' + esc(T('heatEarlier')) + '</button>') + '</div>' +
      D.unranked.map(function (c) { return '<p class="note sm">' + esc(T('unrankedNote', { country: c.country, ccy: c.ccy })) + '</p>'; }).join('') +
      // countries with no price on any of the last 30 days: one grey line naming them, under the map (SEB-301, 21 Oct)
      (D.never30.length && T('neverPricedNote') ? '<p class="note sm">' + esc(T('neverPricedNote', { list: D.never30.map(function (c) { return c.country; }).join(', ') })) + '</p>' : '');
  }

  /* ---------------------------------------------------------------- the time control (js/home_timeline.js): the same grid at a chosen day or hour.
     Every value and class comes from data/map_timeline/; this only draws them. */
  function tlView() { return window.homeTimeline ? window.homeTimeline.view() : null; }
  function tlBucket(c) { if (c.v == null || c.k === '-') { return 'b-none'; } if (c.k === '2') { return c.v >= 100 ? 'b-offstep' : 'b-off'; } return bucket(c.v / 10); }
  // axis labels stay short (the year and the full hour are in the line above the grid): the right-hand column is 58px wide on a phone
  function tlShort(vw, j, end) { var l = vw.labels[j]; return vw.hourly ? (end ? '' : dd(l.slice(0, 10)) + ' ') + l.slice(11, 13) + ':00' : dd(l); }
  function tlValue(c) {
    if (c.v == null || c.k === '-') { return '<small>' + esc(T('tlNoData')) + '</small>'; }
    return sgn(c.v / 10) + (c.k === '2' ? '<small class="tag">' + esc(T('tlOfficialTag')) + '</small>' : '');
  }
  function heatTl(vw) {
    var rows = showAll ? vw.rows : vw.rows.slice(0, 20), n = vw.labels.length;
    var anyOff = vw.rows.some(function (r) { return r.cells.some(function (c) { return c.k === '2'; }); });
    var ax = '<span class="l" style="left:0">' + esc(tlShort(vw, 0)) + '</span>';
    var line = function (r) {
      return '<a class="hrow" href="' + ctry(r.ccy) + '" data-ccy="' + esc(r.ccy) + '"><span class="nm">' + esc(plain(r.country)) + '</span><span class="cells">' +
        r.cells.map(function (c, j) { return '<i class="' + tlBucket(c) + '" data-i="' + j + '"></i>'; }).join('') +
        '</span><span class="v num">' + tlValue(r.end) + '</span></a>';
    };
    $('heat').innerHTML =
      (vw.reported && T('tlReported') ? '<p class="note tlnote">' + esc(T('tlReported', { since: window.homeTimeline.fmt(window.homeTimeline.meta().own_start, false) })) + '</p>' : '') +
      '<p class="key">' + BUCKETS.map(function (b) { return '<span><i class="' + b[2] + '"></i>' + esc(T(b[3], b[4])) + '</span>'; }).join('') +
      (anyOff ? '<span><i class="b-off"></i>' + esc(T('tlLegendOfficial')) + '</span><span><i class="b-offstep"></i>' + esc(T('tlLegendOfficialStep')) + '</span>' : '') +
      '<span><i class="b-none"></i>' + esc(T('legendNone')) + '</span></p>' +
      '<div class="hax"><span></span><div class="ax num">' + ax + '</div><span class="axh">' + esc(tlShort(vw, n - 1, true)) + '</span></div>' +
      rows.map(line).join('') +
      '<div class="pills hb">' + (showAll || vw.rows.length <= 20 ? '' : '<button class="pill" type="button" id="all">' + esc(T('heatShowAll', { n: vw.rows.length })) + '</button>') + '</div>';
  }
  function heatHead() {
    var vw = tlView();
    if (vw) {
      $('heatT').textContent = vw.counts.N ? T('tlHeatTitle', { n: g(vw.counts.n), N: g(vw.counts.N), when: vw.when }) : T(vw.counts.off ? 'tlHeatTitleOfficial' : 'tlHeatTitleNone', { when: vw.when });
      $('heatL').textContent = T('tlHeatLine');
      return;
    }
    var rk = D.rk || [];
    // the lead line (SEB-391): the biggest premium this hour, how many countries are at 8% or more (the legend's cut), and how many are within 2%.
    // Until its words are set the older "In n of N countries" title stands.
    var r1 = function (c) { return Math.round(c.index_pct * 10) / 10; };
    var top = rk.reduce(function (a, c) { return !a || c.index_pct > a.index_pct ? c : a; }, null);
    $('heatT').textContent = !rk.length ? '' : T('heatLead') ? T('heatLead', { top_pct: top.index_pct.toFixed(1), top_country: plain(top.country), n_over_8: g(rk.filter(function (c) { return r1(c) >= 8; }).length),
      n_within_2: g(rk.filter(function (c) { var v = r1(c); return v >= -2 && v <= 2; }).length), n_priced: g(rk.length) }) :
      T('heatTitle', { n: g(rk.filter(function (c) { var v = r1(c); return v >= -2 && v <= 2; }).length), N: g(rk.length) });
    $('heatL').textContent = T('heatLine') + (T('heatTapNote') ? ' ' + T('heatTapNote') : '');
  }
  function tlTip(vw, cells, j) {
    var r = vw.rows.filter(function (x) { return x.ccy === cells.closest('.hrow').dataset.ccy; })[0], c = r.cells[j];
    var v = { country: plain(r.country), when: window.homeTimeline.fmt(vw.labels[j], vw.hourly), value: c.v == null ? '' : sgn(c.v / 10) };
    return T(c.k === '-' || c.v == null ? 'tlTipNone' : c.k === '0' ? 'tlTipOurs' : c.k === '1' ? 'tlTipReported' : 'tlTipOfficial', v);
  }

  /* ---------------------------------------------------------------- where the official rate landed after past breaks (SEB-384, from the backtest)
     data/map_timeline/landing.json: each break of 10% or more that has a street price before it. Reported, not seen by us. */
  // Rework (25 Oct, Seb: "repetitive and not clear"). Only moves where a real gap existed before (a dollar cost at least LAND_MIN_GAP%
  // more on exchanges) are shown: without a gap there is nothing for the official rate to land on. Each row says how big the gap was
  // and how much of it the move closed, both from the row's two figures in landing.json:
  //   street before = official before x (1 + gap), new official = landing_ratio x street before,
  //   share closed = (new official - official before) / (street before - official before) = (ratio x (1 + gap) - 1) / gap.
  var LAND_MIN_GAP = 10;
  var MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
  function closed(r) { var p = r.premium_before_pct / 100; return Math.max(0, Math.min(1, (r.landing_ratio * (1 + p) - 1) / p)); }
  function month(d, short) { var m = MONTHS[+d.slice(5, 7) - 1]; return (short ? m.slice(0, 3) : m) + ' ' + d.slice(0, 4); }
  // the worked example is the latest move in the list
  function example(rows) {
    var r = rows[0];
    return r && T('landExample') ? '<p class="note">' + esc(T('landExample', { country: plain(r.country), month: month(r.date),
      premium: pct1(r.premium_before_pct), closed: Math.round(closed(r) * 100) + '%' })) + '</p>' : '';
  }
  function land(j) {
    var box = $('land'), rows = ((j && j.rows) || []).filter(function (r) { return r.premium_before_pct >= LAND_MIN_GAP; });
    if (!box || !rows.length || !T('landTitle') || !T('landGap') || !T('landClosed')) { if (box) { box.innerHTML = ''; } return; }
    box.innerHTML = '<h2>' + esc(T('landTitle')) + '</h2><p class="note">' + esc(T('landLine', { n: rows.length, gap: LAND_MIN_GAP + '%' })) + '</p>' + example(rows) +
      '<div class="rows lrows">' + rows.map(function (r) {
        var c = Math.round(closed(r) * 100);
        return '<a class="r lr" href="' + ctry(r.ccy) + '"><b>' + esc(plain(r.country)) + '<small class="d">' + esc(month(r.date, true)) + '</small></b>' +
          // the gap before and after on one line (1 Nov, Claude Design review): the jump closing the gap, not a progress bar.
          // After = the part of the gap still open, on the same base as "of the gap closed", so the two numbers agree.
          '<span class="m lba num">' + esc(T('landBeforeAfter', { before: pct1(r.premium_before_pct), after: pct1(r.premium_before_pct * (1 - closed(r))) })) + '</span>' +
          '<span class="v num">' + c + '%<small>' + esc(T('landClosed')) + '</small></span></a>';
      }).join('') + '</div><p class="note sm">' + esc(T('landNote')) + '</p>';
  }

  /* ---------------------------------------------------------------- findings: each line links to its page */
  function findings() {
    // the same published findings, in the same order and with the same titles as the Research list (copy.json findingData.title_<id>)
    var FD = (D.copy && D.copy.findingData) || {};
    var title = function (f) {
      var t = FD['title_' + f.id], v = (f.headline || {}).value;
      if (typeof t !== 'string' || !t) { return ''; }
      return t.replace(/\{approx\}/g, typeof v === 'number' ? 'S$' + (v / 1e6).toFixed(1) + 'M' : '')
              .replace(/\{n\}/g, typeof v === 'number' ? v.toLocaleString('en-US', { maximumFractionDigits: 2 }) : '');
    };
    var pub = ((D.fin && D.fin.findings) || []).filter(function (f) { return f.published === true; });
    // a finding keeps its number and its page; 01 and 02 (apps change prices, Saturday pricing) are off the home list, their pages stay (SEB-384)
    var OFF = ['price_changes', 'weekend_penalty', 'volume_crossover'];   // volume_crossover (the S$13.5M line) is off the home list too (SEB-391); the Research list keeps it
    var ord = pub.map(function (f, i) { return { f: f, no: i + 1 }; }).filter(function (o) { return OFF.indexOf(o.f.id) < 0; });
    var lines = ord.map(function (o) { return [o.f.id, title(o.f), o.no]; }).filter(function (l) { return l[1]; });
    if (!lines.length || !T('findingsTitle')) { $('finds').innerHTML = ''; return; }
    var routesLink = T('findingsRoutesLink') ? '<a class="r f" href="./sending-money.html"><span class="m">' + esc(T('findingsRoutesLink')) + '</span><span class="v">→</span></a>' : '';
    $('finds').innerHTML = '<h2>' + esc(T('findingsTitle')) + '</h2><div class="rows">' + routesLink + lines.map(function (f, i) {
      // no number here: this list is in Seb's order (21 Oct), so the Findings page numbers would read out of order (24 Oct)
      return '<a class="r f" href="./finding.html?id=' + encodeURIComponent(f[0]) + '"><span class="m">' + esc(f[1]) + '</span><span class="v">→</span></a>';
    }).join('') + '</div>';
  }

  /* ---------------------------------------------------------------- squares answer hover and tap: the day comes from where the pointer is along the row */
  function readSquare(e) {
    var cells = e.target.closest && e.target.closest('.cells');
    if (!cells) { if (!e.target.closest || !e.target.closest('.chart,[data-tip]')) { /* the shared tooltip hides itself elsewhere */ } return; }
    var r = cells.getBoundingClientRect(), k = cells.children.length;
    var j = Math.max(0, Math.min(k - 1, Math.floor((e.clientX - r.left) / r.width * k))), i = +cells.children[j].dataset.i, n = D.days.length;
    var vw = tlView();
    if (vw) {
      [].forEach.call(document.querySelectorAll('.cells i.on'), function (x) { x.classList.remove('on'); });
      cells.children[j].classList.add('on');
      if (window.siteTip) { window.siteTip.show(tlTip(vw, cells, j), e.clientX, e.clientY); }
      return;
    }
    var c = D.cur.filter(function (x) { return x.ccy === cells.closest('.hrow').dataset.ccy; })[0], v = c.cells[i];
    [].forEach.call(document.querySelectorAll('.cells i.on'), function (x) { x.classList.remove('on'); });
    cells.children[j].classList.add('on');
    var text = c.country + ', ' + dd(D.days[i]) + ': ' + (v == null ? T('tipNone') : T('tipAgainst', { value: sgn(v) }));
    if (i === n - 1 && c.buy && c.rate && T('topPriceLine')) { text += '. ' + T('topPriceLine', { price: g(c.buy), ccy: c.ccy, rate: g(c.rate) }); }
    if (window.siteTip) { window.siteTip.show(text, e.clientX, e.clientY); }
  }

  function wire() {
    document.addEventListener('pointermove', function (e) { if (e.pointerType !== 'touch' || e.buttons) { readSquare(e); } });
    document.addEventListener('pointerdown', readSquare);
    document.addEventListener('pointerleave', function (e) { if (e.pointerType !== 'touch' && window.siteTip) { window.siteTip.hide(); } });   // a finger lifting is a pointerleave too: the tap's tooltip stays until the next tap
    document.addEventListener('click', function (e) {
      if (e.target.closest('#all')) { showAll = true; heat(); return; }
      if (e.target.closest('#early')) { early = true; heat(); return; }
      if (e.target.closest('.cmark')) { e.preventDefault(); return; }   // the mark shows its tooltip; it does not open the country
      var sq = e.target.closest('.cells');
      if (sq && window.matchMedia('(hover: none)').matches) { e.preventDefault(); }   // on a phone the first tap reads the square; the name opens the country
    });
  }

  var jobs = { copy: 'copy.json', heat: 'data/heatmap_daily.json', idx: 'data/index_latest.json', fin: 'data/findings.json', rec: 'data/record_daily.json', src: 'data/sources_daily.json' };
  // loading is a function so a tab left open can load again when a newer hour is published (siteLive, js/site_head.js)
  var wired = false, tlWired = false;
  function load() {
  var failed = [], y0 = window.scrollY;
  // the computed sentences (SEB-423): not counted as a failed file when absent, the page then keeps its fixed headline and shows no block
  var extra = [getJSON('data/home_facts.json').catch(function () { return null; }), window.Claims ? window.Claims.load() : Promise.resolve(null),
    getJSON('data/home_prose.json').catch(function () { return null; }), getJSON('data/cash_latest.json').catch(function () { return null; })];
  return Promise.all(Object.keys(jobs).map(function (k) { return getJSON(jobs[k]).catch(function () { failed.push(k); return null; }); }).concat(extra)).then(function (r) {
    var keys = Object.keys(jobs), got = {};
    keys.forEach(function (k, i) { got[k] = r[i]; });
    got.facts = r[keys.length];
    got.prose = r[keys.length + 2];
    got.cash = r[keys.length + 3];
    C = (got.copy && got.copy.homeData) || {};
    D = got;
    nav();
    if (!got.heat || !got.rec) { var e = $('loaderr'); e.textContent = T('loadError', { n: failed.length }); e.hidden = !e.textContent; return; }
    build();   // before hero(): the "tracked" count and the "Countries tracked" counter both read D.cur, built here
    hero();
    // counted like the Countries page title: ranked countries with a price this hour, and how many sit within 2% (SEB-268, 12 Oct)
    D.rk = ((got.idx && got.idx.countries) || []).filter(function (c) { return c.index_pct != null && c.denominator_class !== 'unmaintained'; });
    heatHead();
    heat();
    whatChanged();
    findings();
    getJSON('data/map_timeline/landing.json').then(land).catch(function () { land(null); });
    if (window.homeTimeline) {
      window.homeTimeline.init({ T: T, esc: esc, mount: $('tl') });
      if (!tlWired) { tlWired = true; window.homeTimeline.onChange(function () { heatHead(); heat(); }); }
    }
    if (wired) { window.scrollTo(0, y0); }
    if (!wired) { wired = true; wire(); }
    if (failed.length) { var er = $('loaderr'); er.textContent = T('loadError', { n: failed.length }); er.hidden = !er.textContent; }
  });
  }
  load();
  (window.siteLive = window.siteLive || { handlers: [], onNewHour: function (fn) { this.handlers.push(fn); } }).onNewHour(load);
})();

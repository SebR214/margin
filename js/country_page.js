/* One country (SEB-268), built to the approved reference. ?ccy= picks the country. Reads
 *   data/countries/<CCY>.json            this hour's price, the daily history, the venues
 *   data/index_latest.json               the list of countries with no price this hour
 *   data/country_history_segment/<CCY>   who reported the older prices, where they exist
 *   data/street_depth_latest.json        how much can be bought before the price moves
 * Every figure is worked out here from those files; every word is a countryData key in copy.json.
 * The chart answers hover and tap through js/tooltip.js. */
(function () {
  var MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  var MINUS = '−';
  var C = {}, qs = new URLSearchParams(location.search), ccy = qs.get('ccy') || document.body.getAttribute('data-ccy') || '', period = 'ours';   // the chart range: 'ours' (our own record, the default), '1y', '5y', 'all' (24 Oct)
  var S = {};

  function $(k) { return document.getElementById(k); }
  function T(k, v) { var s = C[k]; return typeof s === 'string' && s ? s.replace(/\{(\w+)\}/g, function (m, x) { return v && v[x] != null ? v[x] : ''; }) : ''; }
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function dd(s) { return (+s.slice(8, 10)) + ' ' + MON[+s.slice(5, 7) - 1]; }
  function ddY(s) { return dd(s) + ' ' + s.slice(0, 4); }
  function pct1(v) { return (Math.abs(v) >= 100 ? Math.round(Math.abs(v)).toLocaleString('en-US') : Math.abs(v).toFixed(1)) + '%'; }
  // a rounded figure never prints as -0.0: anything that rounds to zero is 0.0
  function z1(v) { var x = v.toFixed(1); return parseFloat(x) === 0 ? '0.0' : x.replace('-', MINUS); }
  function sgn(v) { var z = Math.abs(v) < 0.05; return (z ? '' : v > 0 ? '+' : MINUS) + pct1(v); }
  function money(v, c) { return (v >= 1000 ? Math.round(v).toLocaleString('en-US') : v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })) + ' ' + c; }
  function getJSON(u) { return fetch(u, { cache: 'no-store' }).then(function (r) { if (!r.ok) { throw new Error(u); } return r.json(); }); }
  function maybe(u) { return getJSON(u).catch(function () { return null; }); }
  function isBack(h) { return /backfill/.test(h.source); }
  function tip(text, x, y) { if (window.siteTip) { window.siteTip.show(text, x, y); } }
  function untip() { if (window.siteTip) { window.siteTip.hide(); } }
  function niceTicks(lo, hi, n) {
    var span = hi - lo || 1, step = Math.pow(10, Math.floor(Math.log10(span / n)));
    var err = span / n / step; step *= err >= 5 ? 5 : err >= 2 ? 2 : 1;
    var out = [], v = Math.floor(lo / step) * step;
    for (; v < hi + step * 1e-6 || out.length < 2; v += step) { out.push(Math.abs(v) < step * 1e-6 ? 0 : +v.toFixed(6)); }
    if (out[out.length - 1] < hi) { out.push(+(out[out.length - 1] + step).toFixed(6)); }
    return out;
  }
  // a stored venue id, in words a reader knows
  function vname(v) {
    if (/p2p/i.test(v)) {
      var n = String(v).replace(/[ _]?p2p/i, '');
      return T('venuePerson', { venue: /^okx$/i.test(n) ? 'OKX' : n.replace(/^./, function (c) { return c.toUpperCase(); }) });
    }
    return String(v).replace(/^CriptoYa:(.)/, function (m, c) { return 'CriptoYa · ' + c.toUpperCase(); });
  }

  function nav() {
    $('nav').innerHTML = '';   // the page can arrive with its nav already in the HTML (SEB-426)
    [['navCountries', 'countries.html'], ['navRoutes', 'sending-money.html'], ['navSources', 'sources.html'], ['navFindings', 'findings.html'], ['navResearch', 'research.html'], ['navEvents', 'events.html'], ['navHow', 'how-it-works.html']].forEach(function (x) {
      var t = C[x[0]]; if (!t) { return; }
      var a = document.createElement('a'); a.textContent = t; a.href = './' + x[1]; $('nav').appendChild(a);
    });
  }

  function hero() {
    var c = S.c, held = !!S.withheld, own = S.own, h = '';
    if (held) {
      var last = own.filter(function (x) { return x.source !== 'current_hour'; }).pop() || own[own.length - 1];
      h += '<h1>' + esc(T('withheldTitle', { country: c.country })) + '</h1><p class="lead">' + esc(/^held back:/.test(S.withheld.reason_raw || '') && T('heldBackBody') ? T('heldBackBody') : T('withheldBody', { reason: S.withheld.reason })) + '</p>' +
        (last ? '<p class="money num">' + esc(T('lastPublished', { gap: sgn(last.index_pct), date: dd(last.date) })) + '</p>' : '');
    } else {
      var key = c.index_pct > 0.05 ? 'headlineMore' : c.index_pct < -0.05 ? 'headlineLess' : 'headlineSame';
      var rate = c.fx_mid_per_usd;
      // a number taken from exchanges: say what the person-to-person boards read for the same hour (the published number does not change)
      var pb = c.p2p_beside, pbLine = '';
      if (pb && c.source_class !== 'p2p_buy_median') {
        var names = pb.boards.map(function (b) { return b === 'okx_p2p' ? 'OKX' : 'Binance'; });
        pbLine = '<p class="money num">' + esc(T(pb.index_pct < 0 ? 'p2pBesideUnder' : 'p2pBeside', { boards: names.length > 1 ? T('boardsAnd', { a: names[0], b: names[1] }) : names[0], price: money(pb.buy_price, c.ccy).replace(/ [A-Z]{3}$/, ''), ccy: c.ccy, pct: pct1(pb.index_pct) })) + '</p>';
      }
      // v1.5: priced although a board is crossed, because both boards' sellers agree: one grey line says so
      var crossedLine = c.crossed_boards_agree && T('crossedBoardsAgree') ? '<p class="stamp">' + esc(T('crossedBoardsAgree')) + '</p>' : '';
      h += '<h1>' + esc(T(key, { country: c.country, gap: pct1(c.index_pct) })) + '</h1>' +
        '<p class="lead">' + esc(T(c.source_class === 'p2p_buy_median' ? (c.n_boards === 2 ? 'leadP2pTwo' : 'leadP2p') : 'leadBook', { rate: rate.toLocaleString('en-US', { maximumFractionDigits: 2 }), ccy: c.ccy, country: c.country, street: money(c.buy_price, c.ccy) })) + '</p>' + crossedLine + pbLine +
        '<p class="money num">' + T('usd100Line', { street: esc(money(c.buy_price * 100, c.ccy)), rate: esc(money(rate * 100, c.ccy)) }) + '</p>';
      // the cash dollar (SEB-422): shown only when a money changer's reading is within 6 hours of this hour; older than that it is a gap, not a line
      var cash = S.cash;
      if (cash && T('threeDollarsLine') && Date.parse(c.hour_utc) - Date.parse(cash.ts_utc) <= 6 * 3600 * 1000) {
        h += '<p class="money num">' + esc(T('threeDollarsLine', { official: money(rate, c.ccy), cash: money(cash.mid, c.ccy), stable: money(c.buy_price, c.ccy) })) + '</p>';
      }
      // the price rests on one source only: say so (SEB-302)
      if ((c.venues || []).length === 1 && T('oneSource')) { h += '<p class="stamp num">' + esc(T('oneSource')) + '</p>'; }
      if (c.denominator && c.denominator.class === 'unmaintained') { h += '<p class="flag">' + esc(T('unrankedNote', { country: c.country })) + '</p>'; }
    }
    h += '<p class="stamp num">' + esc(T('pricesFrom', { time: c.hour_utc.slice(11, 16), date: dd(c.hour_utc) })) + '</p>';
    $('hero').innerHTML = h;
    $('hero').style.display = 'flex'; $('hero').style.flexDirection = 'column';
    var d = S.depth;
    $('depth').innerHTML = d && !held ? '<p class="body">' + esc(T(d.is_floor ? 'depthNowFloor' : 'depthNowMoved', { amount: 'US$' + d.depth_usd.toLocaleString('en-US'), pct: d.threshold_pct })) + '</p>' : '';
  }

  function chart() {
    // Our own record is the default view. The older prices (the reported layer: data/country_history_segment and the
    // daily backfill in the country file) only show when a longer range is picked, and a range is offered only when it
    // adds older prices the shorter one did not show (24 Oct, Seb in chat).
    var hist = S.c.history;
    // a country that has never had a price has nothing to draw
    if (!hist.length) { $('chart').innerHTML = ''; return; }
    var mine0 = S.own.length ? S.own : hist;
    var older = ((S.seg && S.seg.points) || []).map(function (p) { return { date: p.date, index_pct: p.index_pct, source: 'segment_backfill' }; })
      .concat(hist.filter(isBack)).filter(function (h) { return h.date < mine0[0].date; })
      .sort(function (a, b) { return a.date < b.date ? -1 : 1; });
    var last = Date.parse(hist[hist.length - 1].date), ownStart = Date.parse(mine0[0].date);
    var RANGES = [['ours', ownStart], ['1y', last - 365 * 864e5], ['5y', last - 1826 * 864e5], ['all', older.length ? Date.parse(older[0].date) : ownStart]];
    var offered = [RANGES[0]];
    var first = RANGES[3][1];
    RANGES.slice(1).forEach(function (r) {
      var prev = offered[offered.length - 1][1];
      if (prev <= first) { return; }                              // everything is already shown
      if (r[1] <= first) { r = ['all', first]; }                   // a range reaching past the oldest price is All
      if (r[1] < prev && older.some(function (h) { var t = Date.parse(h.date); return t >= r[1] && t < prev; })) { offered.push(r); }
    });
    if (!offered.some(function (r) { return r[0] === period; })) { period = 'ours'; }
    var from = offered.filter(function (r) { return r[0] === period; })[0][1];
    var back = older.filter(function (h) { return Date.parse(h.date) >= from; }), mine = mine0;
    var all = back.concat(mine);
    var venue = S.seg && S.seg.venue || T('venueOther');
    var label = function (k) { return k === 'ours' ? T('rangeSince', { month: MON[+mine0[0].date.slice(5, 7) - 1] }) : T('range_' + k); };
    var bar = offered.length > 1 ? '<div class="rbar" role="group">' + offered.map(function (r) {
      return '<button type="button" data-p="' + r[0] + '" aria-pressed="' + (period === r[0]) + '">' + esc(label(r[0])) + '</button>'; }).join('') + '</div>' : '';
    var head = '<h2>' + esc(T('chartHeading')) + '</h2><p class="note">' + esc(T('chartNote')) + '</p>' +
      (back.length ? '<p class="key"><span><i class="ln"></i>' + esc(T('layerDaily')) + '</span><span><i class="ln dash"></i>' + esc(T('layerReported', { venue: venue })) + '</span></p>' : '');
    $('chart').innerHTML = head + '<div class="chart" id="cv"><svg id="svg"></svg></div>' + bar + '<p class="note" id="rec"></p><p class="note" id="swl"></p>';
    switchLine();
    var box = $('cv'), W = Math.max(320, box.clientWidth), H = W < 560 ? 240 : 300, L = 56, Tp = 10, B = 26, R = 8, pw = W - L - R, ph = H - Tp - B;
    var t = all.map(function (h) { return Date.parse(h.date); }), t0 = t[0], t1 = t[t.length - 1];
    function X(v) { return L + (t1 > t0 ? (v - t0) / (t1 - t0) : 0.5) * pw; }
    var vals = all.map(function (h) { return h.index_pct; }), lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals);
    if (lo > 0 && lo < 6) { lo = 0; } if (hi < 0 && hi > -6) { hi = 0; }
    var pad = (hi - lo) * 0.08 || 1, ys = niceTicks(lo - (lo ? pad : 0), hi + pad, 4), y0 = ys[0], y1 = ys[ys.length - 1];
    function Y(v) { return Tp + ph - (v - y0) / (y1 - y0) * ph; }
    var s = '';
    // the older prices sit on a shaded band, labelled, so they never read as our own
    if (back.length) { s += '<rect class="band" x="' + L + '" y="' + Tp + '" width="' + Math.max(0, X(ownStart) - L) + '" height="' + ph + '"/>' + (T('bandLabel') ? '<text class="ax" x="' + (L + 8) + '" y="' + (Tp + 16) + '">' + esc(T('bandLabel')) + '</text>' : ''); }
    ys.forEach(function (v) { s += '<line class="gl' + (v === 0 ? ' z' : '') + '" x1="' + L + '" x2="' + (W - R) + '" y1="' + Y(v) + '" y2="' + Y(v) + '"/><text class="ax' + (v === 0 ? ' z' : '') + '" x="' + (L - 8) + '" y="' + (Y(v) + 4) + '" text-anchor="end">' + (v === 0 ? '0%' : sgn(v)) + '</text>'; });
    function path(arr) { var d = '', p = null; arr.forEach(function (h) { var x = Date.parse(h.date); d += (p && x - p <= 3 * 864e5 ? 'L' : 'M') + X(x).toFixed(1) + ' ' + Y(h.index_pct).toFixed(1); p = x; }); return d; }
    if (back.length) { s += '<path class="ln-back" d="' + path(back) + '"/>'; }
    // our record: the line over a light fill down to 0% (or the bottom of the scale), as on the Routes chart
    var base = Y(Math.min(Math.max(0, y0), y1)), own = path(mine);
    own.split('M').filter(Boolean).forEach(function (seg) {
      var pts = seg.split('L'), x0 = pts[0].split(' ')[0], x1 = pts[pts.length - 1].split(' ')[0];
      s += '<path class="ar-own" d="M' + seg + 'L' + x1 + ' ' + base + 'L' + x0 + ' ' + base + 'Z"/>';
    });
    s += '<path class="ln-own" d="' + own + '"/>';
    var lp = mine[mine.length - 1]; s += '<circle class="pt" cx="' + X(Date.parse(lp.date)) + '" cy="' + Y(lp.index_pct) + '" r="3.5"/>';
    var yearly = t1 - t0 > 400 * 864e5, gapPx = W < 560 ? 64 : 80, lastLX = -1e9;
    // date labels spaced by position, not by point count, so days bunched together never print on top of each other (27 Oct)
    all.forEach(function (h, i) { var lx = X(t[i]); if (lx - lastLX >= gapPx && X(t1) - lx > gapPx) { lastLX = lx; s += '<text class="ax" x="' + lx + '" y="' + (H - 6) + '" text-anchor="' + (i === 0 ? 'start' : 'middle') + '">' + (yearly ? MON[+h.date.slice(5, 7) - 1] + ' ' + h.date.slice(0, 4) : dd(h.date)) + '</text>'; } });
    s += '<text class="ax" x="' + (W - R) + '" y="' + (H - 6) + '" text-anchor="end">' + dd(all[all.length - 1].date) + '</text>';
    s += '<line class="cr" id="cr" y1="' + Tp + '" y2="' + (Tp + ph) + '" visibility="hidden"/><circle class="cd" id="cd" r="4.5" visibility="hidden"/>';
    var svg = box.querySelector('svg'); svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H); svg.innerHTML = s;
    function mark(on, i) {
      var cr = svg.querySelector('#cr'), cd = svg.querySelector('#cd');
      cr.setAttribute('visibility', on ? 'visible' : 'hidden'); cd.setAttribute('visibility', on ? 'visible' : 'hidden');
      if (on) { cr.setAttribute('x1', X(t[i])); cr.setAttribute('x2', X(t[i])); cd.setAttribute('cx', X(t[i])); cd.setAttribute('cy', Y(all[i].index_pct)); }
    }
    function move(e) {
      var r = svg.getBoundingClientRect(), x = (e.clientX - r.left) / r.width * W, tt = t0 + (x - L) / pw * (t1 - t0), best = 0;
      t.forEach(function (v, i) { if (Math.abs(v - tt) < Math.abs(t[best] - tt)) { best = i; } });
      var h = all[best];
      var what = isBack(h) ? T('tipReported') : h.source === 'current_hour' ? T('tipThisHour') : (h.n ? T('tipPrices', { n: h.n }) : '');
      mark(true, best);
      tip(ddY(h.date) + ': ' + T('tipAgainst', { gap: sgn(h.index_pct) }) + (what ? '\n' + what : ''), e.clientX, e.clientY);
    }
    box.onpointermove = move; box.onpointerdown = move;
    box.onpointerleave = function (e) { if (e.pointerType !== 'touch') { untip(); mark(false); } };
    // the record sentence: our own days only, not the reported older prices
    var own = S.own, past = own.map(function (h) { return h.index_pct; }).slice(0, -1), today = S.c.index_pct;
    if (past.length > 5 && today != null && !S.withheld) {
      var sorted = past.slice().sort(function (a, b) { return a - b; });
      var q = function (p) { return sorted[Math.round(p * (sorted.length - 1))]; };
      var mn = sorted[0], mx = sorted[sorted.length - 1], band = (mx - mn) * 0.1;
      var key = today > mx ? 'recordWidest' : today < mn ? 'recordNarrowest' : today > mx - band ? 'recordNearWidest' : today < mn + band ? 'recordNearNarrowest' : 'recordNormal';
      $('rec').textContent = T(key, { first: ddY(own[0].date), scope: T('recordScopeOwn') }) + ' ' + T('recordRange', { lo: z1(q(0.1)), hi: z1(q(0.9)) });
    }
  }

  // the kind of source behind a published number: order books, broker quotes, person-to-person ads, a stand-in
  function family(cls) { return String(cls).replace(/_(median|single)$/, ''); }
  // one grey line when the number started coming from a different kind of source in the last 30 days (data/source_switches.csv)
  function switchLine() {
    var el = $('swl'), rows = S.switches || [];
    if (!el) { return; }
    var now = Date.parse(S.c.hour_utc), hit = null;
    rows.forEach(function (r) {
      if (r.ccy === S.c.ccy && family(r.old_class) !== family(r.new_class) && now - Date.parse(r.hour_utc) <= 30 * 864e5 && now >= Date.parse(r.hour_utc)) { hit = r; }
    });
    el.textContent = hit && T('classNoun_' + hit.new_class) && T('classNoun_' + hit.old_class)
      ? T('sourceSwitched', { date: dd(hit.hour_utc.slice(0, 10)), now: T('classNoun_' + hit.new_class), was: T('classNoun_' + hit.old_class) }) : '';
  }

  function source() {
    if (S.withheld) { $('src').innerHTML = ''; return; }
    var vs = S.c.venues.slice().sort(function (a, b) { return a.index_pct - b.index_pct; });
    $('src').innerHTML = '<h2>' + esc(T('sourceHeading')) + '</h2><p class="note">' + esc(T('sourceLinePlain') && T('classNoun_' + S.c.source_class) ? T('sourceRule') + ' ' + T('sourceLinePlain', { source: T('classNoun_' + S.c.source_class) }) : T('sourceLine', { sourceWords: S.c.source_words }) + ' ' + T('sourceRule')) + '</p><div class="rows">' +
      vs.map(function (v) { return '<div class="r"><b>' + esc(vname(v.venue)) + '</b><span></span><span class="v num">' + esc(money(v.buy_price, S.c.ccy)) + '<small>' + sgn(v.index_pct) + '</small></span></div>'; }).join('') + '</div>';
  }

  function fail(key, v) {
    $('hero').innerHTML = '<p class="lead">' + esc(T(key, v)) + '</p>';
    $('nf').hidden = true;
  }

  var started = false;
  function start(res) {
    C = (res[0] && res[0].countryData) || {};
    if (!started) { nav(); }
    $('cnav').innerHTML = '<a class="back" href="./countries.html">' + esc(T('navCountries')) + '</a>';
    if (!res[1] || !res[2]) { if (started) { return; } return fail(ccy && !res[1] ? 'notFound' : 'loadFailed', { code: ccy }); }
    S.c = res[1]; S.withheld = (res[2].withheld || []).filter(function (w) { return w.ccy === ccy; })[0] || null;
    S.idx = res[3]; S.seg = res[4]; S.depth = res[5] && res[5].countries && res[5].countries[ccy] || null;
    S.cash = res[6] && res[6].rows && res[6].rows[ccy] || null;
    S.switches = res[7] || [];
    S.own = S.c.history.filter(function (h) { return !isBack(h); });
    var again = started, y = window.scrollY;
    started = true;
    if (window.PageHead) { window.PageHead.copy().then(function (H) { window.PageHead.set({ title: window.PageHead.fill(H.countryTitle, { country: S.c.country }), description: window.PageHead.fill(H.countryDescription, { country: S.c.country }), path: 'country/' + encodeURIComponent(ccy.toLowerCase()) + '/', twin: 'country/' + encodeURIComponent(ccy) + '.md' }); }); }
    hero(); chart(); source();
    if (again) { window.scrollTo(0, y); }
  }

  document.addEventListener('click', function (e) {
    var p = e.target.closest('[data-p]');
    if (p) { period = p.getAttribute('data-p'); chart(); return; }
  });
  var rt; window.addEventListener('resize', function () { clearTimeout(rt); rt = setTimeout(function () { if (S.c) { chart(); } }, 150); });

  // the file naming who reported the older prices exists only for the currencies the manifest lists; asking for any other is a 404
  var seg = ccy ? maybe('data/country_history_segment/manifest.json').then(function (m) {
    return m && m.ccys && m.ccys.indexOf(ccy) >= 0 ? maybe('data/country_history_segment/' + ccy + '.json') : null;
  }) : Promise.resolve(null);
  // loading is a function so a tab left open can load again when a newer hour is published (siteLive, js/site_head.js);
  // the picked period and how many readings are shown stay
  function load(again) {
    return Promise.all([
      maybe('copy.json'),
      ccy ? maybe('data/countries/' + ccy + '.json') : Promise.resolve(null),
      maybe('data/index_latest.json'),
      Promise.resolve(null),   // the hour by hour price list was cut on 27 Oct (Seb): nothing reads data/country_readings here now
      seg, maybe('data/street_depth_latest.json'),
      maybe('data/cash_latest.json'),
      fetch('data/source_switches.csv', { cache: 'no-store' }).then(function (r) { return r.ok ? r.text() : ''; }).then(function (t) {
        var l = t.trim().split(/\r?\n/), h = (l[0] || '').split(',');
        return l.slice(1).map(function (x) { var p = x.split(','), o = {}; h.forEach(function (k, i) { o[k] = p[i]; }); return o; });
      }).catch(function () { return []; })
    ]).then(start).catch(function () { if (!again) { fail('loadFailed'); } });
  }
  // country.html?ccy=ARS still works: it goes to the country's own page (SEB-426) when that page exists, and draws in place when not
  var own = ccy && /^[A-Z]{3}$/.test(ccy) && !document.body.getAttribute('data-ccy') && !qs.get('noredirect') ? 'country/' + ccy.toLowerCase() + '/' : '';
  if (own) {
    fetch('/' + own, { method: 'HEAD' }).then(function (r) { if (r.ok) { location.replace('/' + own + location.hash); } }).catch(function () {});
  }
  load(false);
  (window.siteLive = window.siteLive || { handlers: [], onNewHour: function (fn) { this.handlers.push(fn); } }).onNewHour(function () { return load(true); });
})();

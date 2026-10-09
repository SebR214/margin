/* One country (SEB-268), built to the approved reference. ?ccy= picks the country. Reads
 *   data/countries/<CCY>.json            this hour's price, the daily history, the venues
 *   data/index_latest.json               the list of countries with no price this hour
 *   data/country_readings/<CCY>/...      every stored reading, by month (the receipts)
 *   data/country_history_segment/<CCY>   who reported the older prices, where they exist
 *   data/street_depth_latest.json        how much can be bought before the price moves
 * Every figure is worked out here from those files; every word is a countryData key in copy.json.
 * The chart answers hover and tap through js/tooltip.js. */
(function () {
  var MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  var MINUS = '−';
  var C = {}, ccy = new URLSearchParams(location.search).get('ccy') || '', period = 'all', shown = 12;
  var S = {};

  function $(k) { return document.getElementById(k); }
  function T(k, v) { var s = C[k]; return typeof s === 'string' && s ? s.replace(/\{(\w+)\}/g, function (m, x) { return v && v[x] != null ? v[x] : ''; }) : ''; }
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function dd(s) { return (+s.slice(8, 10)) + ' ' + MON[+s.slice(5, 7) - 1]; }
  function ddY(s) { return dd(s) + ' ' + s.slice(0, 4); }
  function pct1(v) { return (Math.abs(v) >= 100 ? Math.round(Math.abs(v)).toLocaleString('en-US') : Math.abs(v).toFixed(1)) + '%'; }
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
    [['navCountries', 'countries.html'], ['navRoutes', 'sending-money.html'], ['navSources', 'sources.html'], ['navFindings', 'findings.html'], ['navHow', 'how-it-works.html']].forEach(function (x) {
      var t = C[x[0]]; if (!t) { return; }
      var a = document.createElement('a'); a.textContent = t; a.href = './' + x[1]; $('nav').appendChild(a);
    });
  }

  function hero() {
    var c = S.c, held = !!S.withheld, own = S.own, h = '';
    if (held) {
      var last = own.filter(function (x) { return x.source !== 'current_hour'; }).pop() || own[own.length - 1];
      h += '<h1>' + esc(T('withheldTitle', { country: c.country })) + '</h1><p class="lead">' + esc(T('withheldBody', { reason: S.withheld.reason })) + '</p>' +
        (last ? '<p class="money num">' + esc(T('lastPublished', { gap: sgn(last.index_pct), date: dd(last.date) })) + '</p>' : '');
    } else {
      var key = c.index_pct > 0.05 ? 'headlineMore' : c.index_pct < -0.05 ? 'headlineLess' : 'headlineSame';
      var rate = c.fx_mid_per_usd;
      h += '<h1>' + esc(T(key, { country: c.country, gap: pct1(c.index_pct) })) + '</h1>' +
        '<p class="lead">' + esc(T(c.source_class === 'p2p_buy_median' ? (c.n_boards === 2 ? 'leadP2pTwo' : 'leadP2p') : 'leadBook', { rate: rate.toLocaleString('en-US', { maximumFractionDigits: 2 }), ccy: c.ccy, country: c.country, street: money(c.buy_price, c.ccy) })) + '</p>' +
        '<p class="money num">' + T('usd100Line', { street: esc(money(c.buy_price * 100, c.ccy)), rate: esc(money(rate * 100, c.ccy)) }) + '</p>';
      if (c.denominator && c.denominator.class === 'unmaintained') { h += '<p class="flag">' + esc(T('unrankedNote', { country: c.country })) + '</p>'; }
    }
    h += '<p class="stamp num">' + esc(T('pricesFrom', { time: c.hour_utc.slice(11, 16), date: dd(c.hour_utc) })) + '</p>';
    $('hero').innerHTML = h;
    $('hero').style.display = 'flex'; $('hero').style.flexDirection = 'column';
    var d = S.depth;
    $('depth').innerHTML = d && !held ? '<p class="body">' + esc(T(d.is_floor ? 'depthNowFloor' : 'depthNowMoved', { amount: 'US$' + d.depth_usd.toLocaleString('en-US'), pct: d.threshold_pct })) + '</p>' : '';
  }

  function chart() {
    var hist = S.c.history, all = period === 'all' ? hist : hist.slice(-30);
    var back = all.filter(isBack), mine = all.filter(function (h) { return !isBack(h); });
    var hasBack = hist.length !== S.own.length;
    var venue = S.seg && S.seg.venue || T('venueOther');
    var head = '<h2>' + esc(T('chartHeading')) + '</h2><p class="note">' + esc(T('chartNote')) + '</p><div class="pills">' +
      [['30', 'period30'], ['all', 'periodAll']].map(function (p) { return '<button class="pill" type="button" data-p="' + p[0] + '" aria-pressed="' + (period === p[0]) + '">' + esc(T(p[1])) + '</button>'; }).join('') + '</div>' +
      (hasBack && period === 'all' ? '<p class="key"><span><i class="ln"></i>' + esc(T('layerDaily')) + '</span><span><i class="ln dash"></i>' + esc(T('layerReported', { venue: venue })) + '</span></p>' : '');
    $('chart').innerHTML = head + '<div class="chart" id="cv"><svg id="svg"></svg></div><p class="note" id="rec"></p>';
    var box = $('cv'), W = Math.max(320, box.clientWidth), H = W < 560 ? 240 : 300, L = 56, Tp = 10, B = 26, R = 8, pw = W - L - R, ph = H - Tp - B;
    var t = all.map(function (h) { return Date.parse(h.date); }), t0 = t[0], t1 = t[t.length - 1];
    function X(v) { return L + (t1 > t0 ? (v - t0) / (t1 - t0) : 0.5) * pw; }
    var vals = all.map(function (h) { return h.index_pct; }), lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals);
    if (lo > 0 && lo < 6) { lo = 0; } if (hi < 0 && hi > -6) { hi = 0; }
    var pad = (hi - lo) * 0.08 || 1, ys = niceTicks(lo - (lo ? pad : 0), hi + pad, 4), y0 = ys[0], y1 = ys[ys.length - 1];
    function Y(v) { return Tp + ph - (v - y0) / (y1 - y0) * ph; }
    var s = '';
    ys.forEach(function (v) { s += '<line class="gl' + (v === 0 ? ' z' : '') + '" x1="' + L + '" x2="' + (W - R) + '" y1="' + Y(v) + '" y2="' + Y(v) + '"/><text class="ax' + (v === 0 ? ' z' : '') + '" x="' + (L - 8) + '" y="' + (Y(v) + 4) + '" text-anchor="end">' + (v === 0 ? '0%' : sgn(v)) + '</text>'; });
    function path(arr) { var d = '', p = null; arr.forEach(function (h) { var x = Date.parse(h.date); d += (p && x - p <= 3 * 864e5 ? 'L' : 'M') + X(x).toFixed(1) + ' ' + Y(h.index_pct).toFixed(1); p = x; }); return d; }
    if (back.length) { s += '<path class="ln-back" d="' + path(back) + '"/>'; }
    s += '<path class="ln-own" d="' + path(mine) + '"/>';
    if (mine.length < 60) { mine.forEach(function (h) { s += '<circle class="pt" cx="' + X(Date.parse(h.date)) + '" cy="' + Y(h.index_pct) + '" r="2.5"/>'; }); }
    var step = Math.max(1, Math.round(all.length / 5)), yearly = period === 'all' && t1 - t0 > 400 * 864e5;
    all.forEach(function (h, i) { if (i % step === 0 && X(t1) - X(t[i]) > (W < 560 ? 56 : 70)) { s += '<text class="ax" x="' + X(t[i]) + '" y="' + (H - 6) + '" text-anchor="middle">' + (yearly ? MON[+h.date.slice(5, 7) - 1] + ' ' + h.date.slice(2, 4) : dd(h.date)) + '</text>'; } });
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
      $('rec').textContent = T(key, { first: ddY(own[0].date), scope: T('recordScopeOwn') }) + ' ' + T('recordRange', { lo: q(0.1).toFixed(1).replace('-', MINUS), hi: q(0.9).toFixed(1).replace('-', MINUS) });
    }
  }

  function source() {
    if (S.withheld) { $('src').innerHTML = ''; return; }
    var vs = S.c.venues.slice().sort(function (a, b) { return a.index_pct - b.index_pct; });
    $('src').innerHTML = '<h2>' + esc(T('sourceHeading')) + '</h2><p class="note">' + esc(T('sourceLine', { sourceWords: S.c.source_words }) + ' ' + T('sourceRule')) + '</p><div class="rows">' +
      vs.map(function (v) { return '<div class="r"><b>' + esc(vname(v.venue)) + '</b><span></span><span class="v num">' + esc(money(v.buy_price, S.c.ccy)) + '<small>' + sgn(v.index_pct) + '</small></span></div>'; }).join('') + '</div>';
  }

  function receipts() {
    var rows = S.rows, name = S.c.country;
    var h = '<h2>' + esc(T('receiptsHeading', { country: name })) + '</h2><p class="note">' + esc(T('receiptsLead')) + '</p>';
    if (!rows.length) { $('rcp').innerHTML = h + '<p class="note">' + esc(T('receiptsEmpty')) + '</p>'; return; }
    h += '<div class="tbl num"><div class="th"><span>' + esc(T('rcolTime')) + '</span><span>' + esc(T('rcolSource')) + '</span><span>' + esc(T('rcolPrice')) + '</span><span>' + esc(T('rcolGap')) + '</span><span>' + esc(T('rcolDepth')) + '</span><span>' + esc(T('rcolRaw')) + '</span></div>' +
      rows.slice(0, shown).map(function (r) {
        var d = new Date(r[0] * 1000).toISOString(), src = S.idx.sources[r[1]];
        return '<div class="tr"><span>' + dd(d) + ', ' + d.slice(11, 16) + ' UTC</span><span>' + esc(vname(src.id)) + '</span><span>' + esc(money(r[2], S.c.ccy)) + '</span><span>' + sgn(r[4]) + '</span><span>' +
          (r[5] != null ? esc(T('depthAds', { n: r[5], total: r[6] != null ? Math.round(r[6]) : '' })) : '') + '</span><span><a href="https://github.com/SebR214/margin/blob/main/' + esc(src.raw_file) + '">' + esc(src.raw_file.replace('data/', '')) + '</a></span></div>';
      }).join('') + '</div>' + (rows.length > shown ? '<button class="pill more" type="button" id="more">' + esc(T('showMore', { n: Math.min(12, rows.length - shown) })) + '</button>' : '');
    $('rcp').innerHTML = h;
  }

  // the newest readings, walking back through the months until there are enough
  function loadRows(need) {
    var months = S.idx.months.slice().reverse(), got = [], i = 0;
    function next() {
      if (got.length >= need || i >= months.length) { return Promise.resolve(got); }
      return getJSON('data/country_readings/' + ccy + '/' + months[i++] + '.json').then(function (d) { got = got.concat(d.readings.slice().reverse()); return next(); });
    }
    return next();
  }

  function fail(key, v) {
    $('hero').innerHTML = '<p class="lead">' + esc(T(key, v)) + '</p>';
    $('nf').hidden = true;
  }

  function start(res) {
    C = (res[0] && res[0].countryData) || {};
    nav();
    $('cnav').innerHTML = '<a class="back" href="./countries.html">' + esc(T('navCountries')) + '</a>';
    if (!res[1] || !res[2]) { return fail(ccy && !res[1] ? 'notFound' : 'loadFailed', { code: ccy }); }
    S.c = res[1]; S.withheld = (res[2].withheld || []).filter(function (w) { return w.ccy === ccy; })[0] || null;
    S.idx = res[3]; S.seg = res[4]; S.depth = res[5] && res[5].countries && res[5].countries[ccy] || null;
    S.own = S.c.history.filter(function (h) { return !isBack(h); });
    document.title = 'margin.wiki: ' + S.c.country;
    hero(); chart(); source();
    if (S.idx && S.idx.months && S.idx.months.length) {
      loadRows(shown).then(function (rows) { S.rows = rows; receipts(); }).catch(function () { $('rcp').innerHTML = '<p class="note">' + esc(T('receiptsFailed')) + '</p>'; });
    } else { S.rows = []; receipts(); }
  }

  document.addEventListener('click', function (e) {
    var p = e.target.closest('[data-p]');
    if (p) { period = p.getAttribute('data-p'); chart(); return; }
    if (e.target.closest('#more')) { shown += 12; loadRows(shown).then(function (rows) { S.rows = rows; receipts(); }); }
  });
  var rt; window.addEventListener('resize', function () { clearTimeout(rt); rt = setTimeout(function () { if (S.c) { chart(); } }, 150); });

  // the file naming who reported the older prices exists only for the currencies the manifest lists; asking for any other is a 404
  var seg = ccy ? maybe('data/country_history_segment/manifest.json').then(function (m) {
    return m && m.ccys && m.ccys.indexOf(ccy) >= 0 ? maybe('data/country_history_segment/' + ccy + '.json') : null;
  }) : Promise.resolve(null);
  Promise.all([
    maybe('copy.json'),
    ccy ? maybe('data/countries/' + ccy + '.json') : Promise.resolve(null),
    maybe('data/index_latest.json'),
    ccy ? maybe('data/country_readings/' + ccy + '/index.json') : Promise.resolve(null),
    seg, maybe('data/street_depth_latest.json')
  ]).then(start).catch(function () { fail('loadFailed'); });
})();

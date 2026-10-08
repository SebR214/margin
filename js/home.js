/* Home (SEB-268), built to the approved reference.
 * Reads data/heatmap_daily.json, data/index_latest.json, data/movers_week.json, data/findings.json,
 * data/record_daily.json, data/record_milestones.json and copy.json (homeData). The header clock is js/site_head.js's.
 * Every figure is read from those files at render time; every word is a homeData key. Dates, numbers and names are formatted here. */
(function () {
  var MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  var MINUS = '−';
  var C = {}, D = {};
  var showAll = false, early = false;
  var NAV = [['navCountries', 'countries.html'], ['navRoutes', 'sending-money.html'], ['navSources', 'sources.html'], ['navFindings', 'findings.html'], ['navHow', 'how-it-works.html']];
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
  function g(n) { return Math.round(n).toLocaleString('en-US'); }
  function dd(s) { return (+s.slice(8, 10)) + ' ' + MON[+s.slice(5, 7) - 1]; }
  function pct1(v) { return (Math.abs(v) >= 100 ? g(Math.abs(v)) : Math.abs(v).toFixed(1)) + '%'; }
  function sgn(v) { return (v > 0 ? '+' : v < 0 ? MINUS : '') + pct1(v); }
  function bucket(v) { if (v == null) { return 'b-none'; } for (var i = 0; i < BUCKETS.length; i++) { if (v >= BUCKETS[i][0] && v < BUCKETS[i][1]) { return BUCKETS[i][2]; } } return 'b-none'; }
  function plain(name) { return String(name || '').replace(/^the /i, '').replace(/^./, function (c) { return c.toUpperCase(); }); }
  function getJSON(u) { return fetch(u, { cache: 'no-store' }).then(function (r) { if (!r.ok) { throw new Error(u); } return r.json(); }); }
  function ctry(ccy) { return './country.html?ccy=' + encodeURIComponent(ccy); }
  function lastValue(c) { for (var i = c.cells.length - 1; i >= 0; i--) { if (c.cells[i] != null) { return c.cells[i]; } } return null; }

  /* ---------------------------------------------------------------- header nav, words
     (the header status is js/site_head.js's) */
  function nav() {
    var n = $('nav');
    NAV.forEach(function (x) {
      var t = T(x[0]); if (!t) { return; }
      var a = document.createElement('a'); a.textContent = t; a.href = './' + x[1]; n.appendChild(a);
    });
  }

  /* ---------------------------------------------------------------- hero: what the site is, with the totals from record_daily.json */
  function hero() {
    var tt = D.rec.totals || {};
    var h = '<h1>' + esc(T('headline')) + '</h1>' +
      '<p class="lead">' + esc(T('whatLine', { currencies: tt.currencies })) + ' ' + esc(T('routesLine', { routes: tt.routes })) + '</p>' +
      '<p class="body">' + esc(T('agentsLine')) + ' <a href="./how-it-was-built.html">' + esc(T('agentsLink')) + '</a></p>' +
      '<p class="counts num">' + [['counterReadings', g(tt.readings)], ['counterSources', tt.sources], ['counterCurrencies', tt.currencies], ['counterRoutes', tt.routes], ['counterHours', g(tt.hours_collected)]].map(function (c) {
        return T(c[0]) ? '<span><b>' + c[1] + '</b> ' + esc(T(c[0]).toLowerCase()) + '</span>' : '';
      }).join('') + '</p>';
    $('hero').innerHTML = h;
    $('hero').style.display = 'flex'; $('hero').style.flexDirection = 'column';
    if (T('headline')) { document.title = 'margin.wiki'; }
  }

  /* ---------------------------------------------------------------- the map: one row per country, one square per day, sorted by this hour's figure */
  function build() {
    var days = D.heat.days || [];
    var byCcy = {};
    ((D.idx && D.idx.countries) || []).forEach(function (c) { byCcy[c.ccy] = c; });
    D.days = days;
    D.cur = (D.heat.currencies || []).map(function (c) {
      var i = byCcy[c.ccy];
      return { ccy: c.ccy, country: plain(c.country), ranked: c.ranked !== false, cells: c.cells || [],
        now: i && i.index_pct != null ? Math.round(i.index_pct * 10) / 10 : null,
        buy: i ? i.buy_price : null, rate: i ? i.fx_mid_per_usd : null };
    });
    D.ranked = D.cur.filter(function (c) { return c.ranked; }).sort(function (a, b) {
      var av = a.now != null ? a.now : (lastValue(a) != null ? lastValue(a) : -1e9), bv = b.now != null ? b.now : (lastValue(b) != null ? lastValue(b) : -1e9);
      return bv - av;
    });
    D.unranked = D.cur.filter(function (c) { return !c.ranked; });
  }

  function heat() {
    var rows = showAll ? D.ranked : D.ranked.slice(0, 20);
    var s0 = early ? 0 : Math.max(0, D.days.length - 30), days = D.days.slice(s0), n = days.length;
    var X = function (i) { return (i + 0.5) / n * 100; };
    var ax = '<span class="l" style="left:0">' + dd(days[0]) + '</span>';
    days.forEach(function (d, i) { if ((d.slice(8) === '01' || d.slice(8) === '15') && i > 3 && i < n - 4) { ax += '<span style="left:' + X(i) + '%">' + dd(d) + '</span>'; } });
    var row = function (c, extra) {
      return '<a class="hrow' + (extra || '') + '" href="' + ctry(c.ccy) + '" data-ccy="' + esc(c.ccy) + '"><span class="nm">' + esc(c.country) + '</span><span class="cells">' +
        c.cells.slice(s0).map(function (v, i) { return '<i class="' + (c.ranked ? bucket(v) : (v == null ? 'b-none' : 'b-frozen')) + '" data-i="' + (i + s0) + '"></i>'; }).join('') +
        '</span><span class="v num">' + (c.now != null ? sgn(c.now) : '<small>' + esc(T('noPrice')) + '</small>') + '</span></a>';
    };
    $('heat').innerHTML =
      '<p class="key">' + BUCKETS.map(function (b) { return '<span><i class="' + b[2] + '"></i>' + esc(T(b[3], b[4])) + '</span>'; }).join('') + '<span><i class="b-none"></i>' + esc(T('legendNone')) + '</span></p>' +
      '<div class="hax"><span></span><div class="ax num">' + ax + '</div><span class="axh">' + esc(T('dayToday')) + '</span></div>' +
      rows.map(function (c) { return row(c); }).join('') +
      '<div class="pills hb">' + (showAll ? '' : '<button class="pill" type="button" id="all">' + esc(T('heatShowAll', { n: D.ranked.length })) + '</button>') +
      (early ? '' : '<button class="pill" type="button" id="early">' + esc(T('heatEarlier')) + '</button>') + '</div>' +
      (showAll ? D.unranked.map(function (c) { return row(c, ' frozen'); }).join('') : '') +
      D.unranked.map(function (c) { return '<p class="note sm">' + esc(T('unrankedNote', { country: c.country, ccy: c.ccy })) + '</p>'; }).join('');
  }

  /* ---------------------------------------------------------------- this week's movers */
  function movers() {
    var M = (D.mov && D.mov.days) ? null : null;   // movers_week.json lists them under "top" or "movers"
    var list = (D.mov && (D.mov.top || D.mov.movers)) || [];
    if (!list.length || !T('moversTitle')) { $('movers').innerHTML = ''; return; }
    var days = D.days, L = days.length;
    $('movers').innerHTML = '<h2>' + esc(T('moversTitle')) + '</h2><div class="rows">' + list.slice(0, 5).map(function (m) {
      var bd = m.earlier_median_pct >= 0 ? T('dirAbove') : T('dirBelow'), rd = m.recent_median_pct >= 0 ? T('dirAbove') : T('dirBelow');
      var since = days[L - 1 - 6 - m.earlier_days] || days[0], until = days[L - 8] || days[L - 1];
      return '<a class="r" href="' + ctry(m.ccy) + '"><b>' + esc(plain(m.country)) + '</b><span class="m">' +
        esc(T('moverLine', { country: plain(m.country), baseline: pct1(m.earlier_median_pct), baselineDir: bd, since: dd(since), until: dd(until), recent: pct1(m.recent_median_pct), recentDir: rd })) +
        '</span><span class="v num">' + (m.change_pp > 0 ? '+' : MINUS) + Math.abs(m.change_pp).toFixed(1) + '<small>' + esc(T('moverUnit')) + '</small></span></a>';
    }).join('') + '</div>';
  }

  /* ---------------------------------------------------------------- findings: each line links to its page */
  function findings() {
    var F = {};
    ((D.fin && D.fin.findings) || []).forEach(function (f) { F[f.id] = f; });
    var val = function (id) { return F[id] && F[id].headline ? F[id].headline.value : null; };
    var lines = [];
    if (val('price_changes') != null) { lines.push(['price_changes', T('finding_price_changes', { value: g(val('price_changes')) })]); }
    if (val('weekend_penalty') != null) { lines.push(['weekend_penalty', T('finding_weekend_penalty', { value: g(val('weekend_penalty')) })]); }
    if (val('volume_crossover') != null) { lines.push(['volume_crossover', T('finding_volume_crossover', { value: g(val('volume_crossover')) })]); }
    var sg = F.sgd_php_never_cheapest;
    if (sg && sg.headline && sg.hours_rows != null) { lines.push(['sgd_php_never_cheapest', T('finding_sgd_php', { n: g(sg.headline.value), hours: g(sg.hours_rows) })]); }
    lines = lines.filter(function (l) { return l[1]; });
    if (!lines.length || !T('findingsTitle')) { $('finds').innerHTML = ''; return; }
    $('finds').innerHTML = '<h2>' + esc(T('findingsTitle')) + '</h2><div class="rows">' + lines.map(function (f, i) {
      return '<a class="r f" href="./finding.html?id=' + encodeURIComponent(f[0]) + '"><span class="no num">0' + (i + 1) + '</span><span class="m">' + esc(f[1]) + '</span><span class="v">→</span></a>';
    }).join('') + '</div>';
  }

  /* ---------------------------------------------------------------- the record: the SEB-278 chart (hover any day) */
  function record() {
    var box = $('rec');
    box.innerHTML = '';
    if (!D.rec || !D.mil) { return; }
    var P = { SGD: 'Singapore', AUD: 'Australia', NZD: 'New Zealand', USD: 'United States' }, Q = { PHP: 'the Philippines', MXN: 'Mexico', INR: 'India', NGN: 'Nigeria' };
    var names = {};
    (D.mil.milestones || []).forEach(function (m) { if (m.kind === 'route') { var ab = m.id.split('->'); names[m.id] = (P[ab[0]] || ab[0]) + ' to ' + (Q[ab[1]] || ab[1]); } });
    if (typeof window.renderRecordBlock === 'function') { window.renderRecordBlock(box, D.rec, D.mil, C, names); }
  }

  /* ---------------------------------------------------------------- squares answer hover and tap: the day comes from where the pointer is along the row */
  function readSquare(e) {
    var cells = e.target.closest && e.target.closest('.cells');
    if (!cells) { if (!e.target.closest || !e.target.closest('.chart,[data-tip]')) { /* the shared tooltip hides itself elsewhere */ } return; }
    var r = cells.getBoundingClientRect(), k = cells.children.length;
    var j = Math.max(0, Math.min(k - 1, Math.floor((e.clientX - r.left) / r.width * k))), i = +cells.children[j].dataset.i, n = D.days.length;
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
    document.addEventListener('pointerleave', function () { if (window.siteTip) { window.siteTip.hide(); } });
    document.addEventListener('click', function (e) {
      if (e.target.closest('#all')) { showAll = true; heat(); return; }
      if (e.target.closest('#early')) { early = true; heat(); return; }
      var sq = e.target.closest('.cells');
      if (sq && window.matchMedia('(hover: none)').matches) { e.preventDefault(); }   // on a phone the first tap reads the square; the name opens the country
    });
  }

  var jobs = { copy: 'copy.json', heat: 'data/heatmap_daily.json', idx: 'data/index_latest.json', mov: 'data/movers_week.json', fin: 'data/findings.json', rec: 'data/record_daily.json', mil: 'data/record_milestones.json' };
  var failed = [];
  Promise.all(Object.keys(jobs).map(function (k) { return getJSON(jobs[k]).catch(function () { failed.push(k); return null; }); })).then(function (r) {
    var keys = Object.keys(jobs), got = {};
    keys.forEach(function (k, i) { got[k] = r[i]; });
    C = (got.copy && got.copy.homeData) || {};
    D = got;
    nav();
    if (!got.heat || !got.rec) { var e = $('loaderr'); e.textContent = T('loadError', { n: failed.length }); e.hidden = !e.textContent; return; }
    hero();
    $('heatT').textContent = T('heatTitle');
    $('heatL').textContent = T('heatLine') + (T('heatTapNote') ? ' ' + T('heatTapNote') : '');
    build();
    heat();
    movers();
    findings();
    record();
    wire();
    if (failed.length) { var er = $('loaderr'); er.textContent = T('loadError', { n: failed.length }); er.hidden = !er.textContent; }
  });
})();

/* The countries page (SEB-270), built from stored files only.
 *
 * Numbers come from data/*.json: today's figure from index_latest.json, the 30-day
 * range and the money columns from data/countries/{ccy}.json, the weekly change from
 * movers_week.json, the region of each currency from country_regions.json.
 * Every word comes from copy.json ("countries" for this page, "homeData" for the
 * brand and the nav). No word is written in this file, and every count is computed.
 */
(function () {
  var C = {}, H = {};
  var app = document.getElementById('app');
  var MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  var MINUS = '−';

  function fmt(s, vars) { return String(s || '').replace(/\{(\w+)\}/g, function (m, k) { return vars && vars[k] != null ? vars[k] : ''; }); }
  function t(key, vars) { return typeof C[key] === 'string' && C[key] ? fmt(C[key], vars) : ''; }
  function getJSON(url) { return fetch(url).then(function (r) { if (!r.ok) { throw new Error(url); } return r.json(); }); }
  function esc(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }
  function plainName(n) { return String(n).replace(/^the /i, ''); }
  function r1(v) { return Math.round(v * 10) / 10; }
  function pct(v) { var x = r1(v); return (x > 0 ? '+' : x < 0 ? MINUS : '') + Math.abs(x).toFixed(1) + '%'; }
  function signed(v) { return (v > 0 ? '+' : MINUS) + Math.abs(v).toFixed(1); }
  /* 100 dollars in local money: whole numbers at 100 or more per dollar, else two decimals. */
  function money(v, official) {
    return official >= 100
      ? Math.round(v).toLocaleString('en-US')
      : v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  /* The group a country sits in is chosen from the figure the reader sees (one decimal). */
  function band(v) { var p = r1(v); return p > 8 ? 'far' : p > 2 ? 'above' : p >= -2 ? 'near' : 'below'; }

  var GROUPS = [['far', 'rbGroupFar'], ['above', 'rbGroupAbove'], ['near', 'rbGroupNear'], ['below', 'rbGroupBelow']];

  /* Each group gets its own scale because the groups sit far apart. The official-rate line (0) is always drawn. */
  function scaleFor(k, list) {
    if (k === 'far') {
      var top = Math.max.apply(null, list.map(function (c) { return Math.max(c.hi, c.p); }));
      var hi = Math.max(25, Math.ceil(top / 25) * 25), ticks = [];
      for (var v = 0; v <= hi; v += 25) { ticks.push(v); }
      return { lo: 0, hi: hi, ticks: ticks };
    }
    if (k === 'above') { return { lo: 0, hi: 10, ticks: [0, 2, 4, 6, 8, 10] }; }
    if (k === 'near') { return { lo: -4, hi: 4, ticks: [-4, -2, 0, 2, 4] }; }
    return { lo: -6, hi: 2, ticks: [-6, -4, -2, 0, 2] };
  }
  function mkX(S) { return function (v) { return (Math.max(S.lo, Math.min(S.hi, v)) - S.lo) / (S.hi - S.lo) * 100; }; }
  function lines(S, X) {
    return S.ticks.map(function (k) { return '<i class="grid-l' + (k === 0 ? ' zero' : '') + '" style="left:' + X(k) + '%"></i>'; }).join('');
  }
  function axisRow(S, X, withMoney) {
    var ticks = S.ticks.map(function (k) {
      return '<span class="tk num' + (k === 0 ? ' z' : '') + '" style="left:' + X(k) + '%">' + (k === 0 ? '0%' : (k > 0 ? '+' : MINUS) + Math.abs(k) + '%') + '</span>';
    }).join('');
    return '<div class="axisrow"><span></span><div class="track">' + lines(S, X) + ticks + '</div>' +
      (withMoney ? '<span class="sup">' + esc(t('rbColMoney')) + '</span><span class="mh pay">' + esc(t('rbColPay')) + '</span><span class="mh off">' + esc(t('rbColOfficial')) + '</span>' : '') +
      '<span></span></div>';
  }

  function render(d) {
    var ranked = d.rows.filter(function (c) { return !c.frozen; });
    var frozen = d.rows.filter(function (c) { return c.frozen; });
    var count = function (k) { return ranked.filter(function (c) { return band(c.p) === k; }).length; };
    var topC = ranked.reduce(function (a, b) { return b.p > a.p ? b : a; });
    var asof = new Date(d.asof);
    var when = String(asof.getUTCHours()).padStart(2, '0') + ':00 UTC, ' + asof.getUTCDate() + ' ' + MON[asof.getUTCMonth()];
    var total = d.rows.length + d.withheld.length;

    var h = '';
    h += '<header class="hd"><a class="logo" href="./index.html">' + esc(H.brand || '') + '</a><nav class="nv" aria-label="Main">' +
      [['navCountries', 'countries.html'], ['navRoutes', 'sending-money.html'], ['navSources', 'sources.html'], ['navFindings', 'findings.html'], ['navHow', 'how-it-works.html']]
        .map(function (n) { return '<a href="./' + n[1] + '"' + (n[1] === 'countries.html' ? ' aria-current="page"' : '') + '>' + esc(H[n[0]] || '') + '</a>'; }).join('') +
      '</nav></header>';
    h += '<div class="hero"><h1>' + esc(t('rbHeadline', { n: count('near'), N: ranked.length })) + '</h1>' +
      '<p class="lead">' + esc(t('rbLead', { n: count('far'), country: topC.n, x: r1(topC.p).toFixed(1) })) + '</p>' +
      '<p class="meta num"><span class="live" aria-hidden="true"></span>' + esc(t('rbChecked', { when: when, n: d.rows.length, total: total })) + '</p></div>';

    h += '<div class="tools"><label for="q" class="vh">' + esc(t('searchLabel')) + '</label>' +
      '<input id="q" class="search" type="search" placeholder="' + esc(t('searchLabel')) + '" autocomplete="off">' +
      '<div class="pills" id="regions" role="group" aria-label="' + esc(t('rbRegionAll')) + '"></div></div>';

    var sample = d.sampleWeek != null ? '<i class="kw">' + signed(d.sampleWeek) + '</i>' : '';
    h += '<p class="key"><span><i class="kd"></i>' + esc(t('rbKeyToday')) + '</span><span><i class="kr"></i>' + esc(t('rbKeyRange')) +
      '</span><span><i class="kl"></i>' + esc(t('rbKeyOfficial')) + '</span><span>' + sample + esc(t('rbKeyWeek')) + '</span></p>';

    h += '<div id="bands"></div>';
    h += '<div class="np"><h2>' + esc(t('rbNoPrice', { n: d.withheld.length })) + '</h2>' +
      '<p class="names">' + esc(d.withheld.map(function (w) { return plainName(w.country); }).join(', ')) + '.</p>' +
      '<details><summary>' + esc(t('rbShowWhy')) + '</summary><ul class="why">' +
      d.withheld.map(function (w) { var r = String(w.reason || ''); return '<li>' + esc(plainName(w.country)) + '<span>' + esc(r.charAt(0).toUpperCase() + r.slice(1)) + '.</span></li>'; }).join('') +
      '</ul></details>' +
      frozen.map(function (f) { return '<p class="aside">' + esc(t('rbSudan', { country: f.n })) + '</p>'; }).join('') + '</div>';
    h += '<footer class="ft"><p><a href="https://github.com/SebR214/margin">' + esc(t('rbSource')) + '</a></p></footer>';
    app.innerHTML = h;

    var bandsEl = document.getElementById('bands');
    GROUPS.forEach(function (g) {
      var list = ranked.filter(function (c) { return band(c.p) === g[0]; }).sort(function (a, b) { return b.p - a.p; });
      if (!list.length) { return; }
      var S = scaleFor(g[0], list), X = mkX(S), withMoney = g[0] !== 'near';
      var sec = document.createElement('section');
      if (withMoney) { sec.className = 'money'; }
      var s = '<h2>' + esc(t(g[1])) + ' <span class="n num">(' + list.length + ')</span></h2>' + axisRow(S, X, withMoney);
      s += list.map(function (c) {
        var a = Math.min(c.lo, c.p), z = Math.max(c.hi, c.p);
        var wk = c.w != null ? '<small class="wk">' + signed(c.w) + '</small>' : '';
        var cells = withMoney ? '<span class="m pay num">' + money(c.b * 100, c.f) + '</span><span class="m off num">' + money(c.f * 100, c.f) + '</span>' : '';
        var tip = t('rbTip', { country: c.n, today: pct(c.p), lo: pct(c.lo), hi: pct(c.hi) });
        return '<a class="row" data-c="' + esc(c.c) + '" href="./country.html?ccy=' + encodeURIComponent(c.c) + '" title="' + esc(tip) + '">' +
          '<span class="nm">' + esc(c.n) + (withMoney ? ' <span class="cc">' + esc(c.c) + '</span>' : '') + '</span>' +
          '<span class="track">' + lines(S, X) + '<i class="rng' + (a < S.lo ? ' cl' : '') + (z > S.hi ? ' cr' : '') + '" style="left:' + X(a) + '%;width:' + Math.max(0.6, X(z) - X(a)) + '%"></i><i class="dot" style="left:' + X(c.p) + '%"></i></span>' +
          cells + '<span class="v num">' + pct(c.p) + wk + '</span></a>';
      }).join('');
      s += '<p class="empty" hidden>' + esc(t('rbNoMatch')) + '</p>';
      sec.innerHTML = s;
      bandsEl.appendChild(sec);
    });

    /* region buttons and search */
    var ids = Object.keys(C.rbRegions || {}).filter(function (k) { return ranked.some(function (c) { return d.region[c.c] === k; }); });
    var pillsEl = document.getElementById('regions');
    var reg = '', q = '';
    pillsEl.innerHTML = [['', t('rbRegionAll')]].concat(ids.map(function (k) { return [k, C.rbRegions[k]]; })).map(function (r) {
      return '<button class="pill" type="button" data-r="' + esc(r[0]) + '" aria-pressed="' + (r[0] === '') + '">' + esc(r[1]) + '</button>';
    }).join('');
    function apply() {
      bandsEl.querySelectorAll('section').forEach(function (sec) {
        var shown = 0;
        sec.querySelectorAll('.row').forEach(function (el) {
          var c = ranked.filter(function (x) { return x.c === el.getAttribute('data-c'); })[0];
          var m = (!reg || d.region[c.c] === reg) && (!q || c.n.toLowerCase().indexOf(q) >= 0 || c.c.toLowerCase().indexOf(q) >= 0);
          el.classList.toggle('hide', !m);
          if (m) { shown++; }
        });
        sec.hidden = shown === 0;
      });
    }
    pillsEl.addEventListener('click', function (e) {
      var b = e.target.closest('.pill'); if (!b) { return; }
      reg = b.getAttribute('data-r');
      pillsEl.querySelectorAll('.pill').forEach(function (p) { p.setAttribute('aria-pressed', p === b ? 'true' : 'false'); });
      apply();
    });
    document.getElementById('q').addEventListener('input', function (e) { q = e.target.value.trim().toLowerCase(); apply(); });
  }

  Promise.all([getJSON('copy.json'), getJSON('data/index_latest.json'), getJSON('data/movers_week.json'), getJSON('data/country_regions.json')]).then(function (r) {
    C = r[0].countries || {};
    H = r[0].homeData || {};
    var idx = r[1], weekly = {}, first = null;
    (r[2].top || []).forEach(function (m, i) { weekly[m.ccy] = m.change_pp; if (i === 0) { first = m.change_pp; } });
    return Promise.all(idx.countries.map(function (c) {
      return getJSON('data/countries/' + encodeURIComponent(c.ccy) + '.json').then(function (f) {
        var days = (f.history || []).slice(-30).map(function (x) { return x.index_pct; }).filter(function (v) { return v != null; });
        var p = c.index_pct;
        return {
          c: c.ccy, n: plainName(c.country), p: p,
          b: f.buy_price, f: f.denominator && f.denominator.rate_per_usd,
          lo: days.length ? Math.min.apply(null, days.concat([p])) : p, hi: days.length ? Math.max.apply(null, days.concat([p])) : p,
          w: weekly[c.ccy] != null ? weekly[c.ccy] : null,
          frozen: c.denominator_class === 'unmaintained'
        };
      });
    })).then(function (rows) {
      return { rows: rows, withheld: idx.withheld || [], asof: idx.as_of_utc, region: r[3], sampleWeek: first };
    });
  }).then(render).catch(function () {
    getJSON('copy.json').then(function (c) {
      var p = document.createElement('p');
      p.textContent = (c.countries && c.countries.loadFailed) || '';
      app.innerHTML = '';
      app.appendChild(p);
    }).catch(function () { /* nothing to say without copy */ });
  });
})();

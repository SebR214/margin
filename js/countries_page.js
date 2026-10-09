/* The countries page, rebuilt to match the approved reference exactly
 * (SEB-270, https://claude.ai/artifact/A7iDWVRm1NRjKLHqvfwmFE).
 *
 * Numbers, dates, currency codes, country names and regions come from
 * data/index_latest.json and data/movers_week.json. Every word comes from
 * copy.json: "countries" for this page, "homeData" for the nav and brand.
 * A key that is empty (or missing) is not rendered, so a slot the writer
 * has not filled yet stays hidden instead of showing placeholder text.
 * No word is written in this file.
 *
 * Reads: data/index_latest.json, data/movers_week.json, copy.json.
 */
(function () {
  var C = {}, H = {}, D = {}, Mv = null;
  var S = { q: '', region: '__ALL__' };
  var app = document.getElementById('app');
  var MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

  // Each group's own fixed scale, per the reference -- "far" is the one
  // exception, computed from the real data below, because the far group
  // can run from 0% to wherever the dearest real country lands.
  var SCALES = {
    above: { lo: 0, hi: 10, ticks: [0, 2, 4, 6, 8, 10] },
    near: { lo: -4, hi: 4, ticks: [-4, -2, 0, 2, 4] },
    below: { lo: -6, hi: 2, ticks: [-6, -4, -2, 0, 2] }
  };
  var BANDS = [
    { k: 'far', capKey: 'groupFar' },
    { k: 'above', capKey: 'groupAbove' },
    { k: 'near', capKey: 'groupNear' },
    { k: 'below', capKey: 'groupBelow' }
  ];

  /* ---------------------------------------------------------------- helpers */
  function fmt(s, vars) {
    return s.replace(/\{(\w+)\}/g, function (m, k) { return vars && vars[k] != null ? vars[k] : ''; });
  }
  function has(o, key) { return typeof o[key] === 'string' && o[key].length > 0; }
  function t(key, vars) { return has(C, key) ? fmt(C[key], vars) : ''; }
  function th(key, vars) { return has(H, key) ? fmt(H[key], vars) : ''; }
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) { [].concat(cls).forEach(function (c) { e.classList.add(c); }); }
    if (text != null) { e.textContent = text; }
    return e;
  }
  function put(parent, tag, cls, text) {
    if (!text) { return null; }
    var e = el(tag, cls, text);
    parent.appendChild(e);
    return e;
  }
  function num(n, d) {
    if (n == null || isNaN(n)) { return ''; }
    return Number(n).toLocaleString('en-US', { maximumFractionDigits: d || 0, minimumFractionDigits: d || 0 });
  }
  function r1(v) { return Math.round(v * 10) / 10; }
  function sign(x) { return x > 0 ? '+' : x < 0 ? '−' : ''; }
  function fmtPct(v) { var x = r1(v); return sign(x) + Math.abs(x).toFixed(1) + '%'; }
  function fmtPts(v) { var x = r1(v); return sign(x) + Math.abs(x).toFixed(1); }
  function fmtMoney(v, ref) {
    if (v == null || ref == null) { return ''; }
    return ref >= 100 ? num(v, 0) : num(v, 2);
  }
  function bandOf(v) {
    var p = r1(v);
    return p > 8 ? 'far' : p > 2 ? 'above' : p >= -2 ? 'near' : 'below';
  }
  // Stored names keep a leading "the" for use in sentences; a list shows the bare name.
  function plainName(n) { return String(n).replace(/^the /i, ''); }
  function getJSON(url) {
    return fetch(url).then(function (r) { if (!r.ok) { throw new Error(url); } return r.json(); });
  }
  function countryHref(ccy) { return 'country.html?ccy=' + encodeURIComponent(ccy); }
  function mkX(Sc) { return function (v) { return (Math.max(Sc.lo, Math.min(Sc.hi, v)) - Sc.lo) / (Sc.hi - Sc.lo) * 100; }; }
  function farScale(rows) {
    var mx = 0;
    rows.forEach(function (r) { mx = Math.max(mx, r.hi, r.p); });
    return { lo: 0, hi: Math.ceil((mx || 25) / 25) * 25, ticks: [0, 25, 50, 75, 100] };
  }
  function visibleTicks(Sc) { return Sc.ticks.filter(function (tk) { return tk >= Sc.lo && tk <= Sc.hi; }); }
  function gridlinesHTML(Sc, X) {
    return visibleTicks(Sc).map(function (tk) {
      return '<i class="ci-gridl' + (tk === 0 ? ' zero' : '') + '" style="left:' + X(tk) + '%"></i>';
    }).join('');
  }

  /* ---------------------------------------------------------------- header */
  function header(wrap) {
    var h = el('div', 'ci-head');
    var logo = put(h, 'a', 'ci-logo', th('brand'));
    if (logo) { logo.href = './index.html'; }
    var nav = el('nav', 'ci-nav');
    [['navCountries', 'countries.html'], ['navRoutes', 'sending-money.html'], ['navSources', 'sources.html'],
     ['navFindings', 'findings.html'], ['navHow', 'how-it-works.html']].forEach(function (n) {
      var a = put(nav, 'a', null, th(n[0]));
      if (a) {
        a.href = './' + n[1];
        if (n[1] === 'countries.html') { a.setAttribute('aria-current', 'page'); }
      }
    });
    if (nav.childNodes.length) { h.appendChild(nav); }
    wrap.appendChild(h);
  }

  /* ---------------------------------------------------------------- hero */
  function hero(wrap, ctx) {
    var s = el('div', 'ci-hero');
    put(s, 'h1', null, t('h1Template', { n: num(ctx.nearCount), N: num(ctx.rankedLen) }));
    put(s, 'p', 'ci-lead', t('leadTemplate', { n: num(ctx.farCount), country: ctx.topName, x: ctx.topX }));
    var metaTxt = t('metaLine', { time: ctx.time, n: num(ctx.pricedCount), total: num(ctx.total) });
    if (metaTxt) {
      var m = el('p', ['ci-meta', 'ci-num']);
      m.appendChild(document.createTextNode(metaTxt));
      s.appendChild(m);
    }
    if (s.childNodes.length) { wrap.appendChild(s); }
  }

  /* ---------------------------------------------------------------- tools */
  function makePill(pillsWrap, label, val) {
    var b = el('button', 'ci-pill', label);
    b.type = 'button';
    b.setAttribute('aria-pressed', val === S.region ? 'true' : 'false');
    b.addEventListener('click', function () {
      S.region = val;
      [].forEach.call(pillsWrap.children, function (x) { x.setAttribute('aria-pressed', x === b ? 'true' : 'false'); });
      apply();
    });
    pillsWrap.appendChild(b);
  }

  function tools(wrap, ctx) {
    var box = el('div', 'ci-tools');
    if (has(C, 'searchLabel')) {
      var lbl = el('label', null, t('searchLabel'));
      lbl.style.position = 'absolute';
      lbl.style.left = '-9999px';
      lbl.setAttribute('for', 'ciSearch');
      box.appendChild(lbl);
      var inp = el('input', 'ci-search');
      inp.type = 'search';
      inp.id = 'ciSearch';
      inp.autocomplete = 'off';
      inp.placeholder = t('searchLabel');
      inp.addEventListener('input', function () { S.q = inp.value.trim().toLowerCase(); apply(); });
      box.appendChild(inp);
    }
    var pillsWrap = el('div', 'ci-pills');
    pillsWrap.setAttribute('role', 'group');
    pillsWrap.setAttribute('aria-label', 'Region');
    var allLabel = t('filterAll');
    if (allLabel) { makePill(pillsWrap, allLabel, '__ALL__'); }
    (ctx.regionOrder || []).forEach(function (rg) {
      if (ctx.rankedRegions[rg]) { makePill(pillsWrap, rg, rg); }
    });
    if (pillsWrap.childNodes.length) { box.appendChild(pillsWrap); }
    if (box.childNodes.length) { wrap.appendChild(box); }
  }

  /* ---------------------------------------------------------------- key */
  function keyRow(wrap, ctx) {
    if (!(has(C, 'keyToday') && has(C, 'keyRange') && has(C, 'keyOfficial') && has(C, 'keyWeekly'))) { return; }
    var p = el('p', 'ci-key');
    var i1 = el('span'); i1.appendChild(el('i', 'ci-kd')); i1.appendChild(document.createTextNode(t('keyToday')));
    var i2 = el('span'); i2.appendChild(el('i', 'ci-kr')); i2.appendChild(document.createTextNode(t('keyRange')));
    var i3 = el('span'); i3.appendChild(el('i', 'ci-kl')); i3.appendChild(document.createTextNode(t('keyOfficial')));
    var i4 = el('span');
    i4.appendChild(el('i', 'ci-kw', ctx.weeklySample));
    i4.appendChild(document.createTextNode(t('keyWeekly')));
    [i1, i2, i3, i4].forEach(function (i) { p.appendChild(i); });
    wrap.appendChild(p);
  }

  /* ---------------------------------------------------------------- bands */
  function axisRowEl(Sc, X, money) {
    var row = el('div', 'ci-axisrow');
    row.appendChild(el('span'));
    var track = el('div', 'ci-track');
    track.innerHTML = gridlinesHTML(Sc, X) + visibleTicks(Sc).map(function (tk) {
      var label = tk === 0 ? '0%' : (tk > 0 ? '+' : '−') + Math.abs(tk) + '%';
      return '<span class="ci-tk ci-num' + (tk === 0 ? ' z' : '') + '" style="left:' + X(tk) + '%">' + label + '</span>';
    }).join('');
    row.appendChild(track);
    if (money) {
      put(row, 'span', 'ci-sup', t('colMoney'));
      put(row, 'span', ['ci-mh', 'pay'], t('colPay'));
      put(row, 'span', ['ci-mh', 'off'], t('colOfficialHead'));
    }
    row.appendChild(el('span'));
    return row;
  }

  var ROW_TPL = document.getElementById('ciRowTpl');

  function rowEl(row, Sc, X, money) {
    // Cloned from the <template> in countries.html rather than built from
    // scratch, so the row's shape (one <a class="ci-row">) is real, static
    // markup -- the same "trow" template convention the old page used,
    // which tools/check_inventory.py's regression guard looks for.
    var a = ROW_TPL.content.firstElementChild.cloneNode(true);
    a.href = countryHref(row.ccy);
    a.setAttribute('data-ccy', row.ccy);
    a.setAttribute('data-region', row.region || '');
    a.setAttribute('data-name', (row.country + ' ' + row.ccy).toLowerCase());

    var nm = a.querySelector('.ci-nm');
    nm.textContent = row.country;
    if (money) {
      nm.appendChild(document.createTextNode(' '));
      nm.appendChild(el('span', 'ci-cc', row.ccy));
    }

    var lo = Math.min(row.lo, row.p), hi = Math.max(row.hi, row.p);
    var cutL = lo < Sc.lo, cutR = hi > Sc.hi;
    var rngClass = 'ci-rng' + (cutL ? ' cl' : '') + (cutR ? ' cr' : '');
    var left = X(lo), width = Math.max(0.6, X(hi) - X(lo));
    var track = a.querySelector('.ci-track');
    // on a phone a tap on the bar shows its figures; the row's link is the name
    track.addEventListener('click', function (e) { if (e.pointerType === 'touch' || window.matchMedia('(pointer: coarse)').matches) { e.preventDefault(); } });
    if (t('tipRange')) { track.setAttribute('data-tip', t('tipRange', { country: row.country, now: fmtPct(row.p), lo: fmtPct(lo), hi: fmtPct(hi) })); }
    track.innerHTML = gridlinesHTML(Sc, X) +
      '<i class="' + rngClass + '" style="left:' + left + '%;width:' + width + '%"></i>' +
      '<i class="ci-dot" style="left:' + X(row.p) + '%"></i>';

    var v = a.querySelector('.ci-v');
    if (money) {
      var pay = fmtMoney(row.buy * 100, row.fx), off = fmtMoney(row.fx * 100, row.fx);
      if (pay) { a.insertBefore(el('span', ['ci-m', 'pay', 'ci-num'], pay), v); }
      if (off) { a.insertBefore(el('span', ['ci-m', 'off', 'ci-num'], off), v); }
    }
    v.textContent = fmtPct(row.p);
    if (row.w != null) { v.appendChild(el('span', 'ci-wk', fmtPts(row.w))); }
    return a;
  }

  function bandSection(def, rows) {
    if (!rows.length || !has(C, def.capKey)) { return null; }
    var money = def.k !== 'near';
    var Sc = def.k === 'far' ? farScale(rows) : SCALES[def.k];
    var X = mkX(Sc);
    var sec = el('section', money ? ['ci-band', 'ci-money'] : 'ci-band');
    var h2 = el('h2');
    h2.appendChild(document.createTextNode(t(def.capKey) + ' '));
    h2.appendChild(el('span', ['ci-n', 'ci-num'], '(' + rows.length + ')'));
    sec.appendChild(h2);
    sec.appendChild(axisRowEl(Sc, X, money));
    rows.forEach(function (r) { sec.appendChild(rowEl(r, Sc, X, money)); });
    return sec;
  }

  function bandsSection(wrap, ctx) {
    BANDS.forEach(function (b) {
      var sec = bandSection(b, ctx.grouped[b.k] || []);
      if (sec) { wrap.appendChild(sec); }
    });
  }

  /* ---------------------------------------------------------------- no-price */
  function noPriceSection(wrap, ctx) {
    var showWithheld = ctx.withheld.length && has(C, 'noPriceTemplate');
    var showFrozen = !!(ctx.frozenRow && has(C, 'frozenTemplate'));
    if (!showWithheld && !showFrozen) { return; }
    var np = el('div', 'ci-np');
    if (showWithheld) {
      put(np, 'h2', null, t('noPriceTemplate', { n: num(ctx.withheld.length) }));
      var names = ctx.withheld.map(function (w) { return plainName(w.country || w.ccy); }).join(', ') + '.';
      put(np, 'p', 'ci-note', names);
      if (has(C, 'showWhy')) {
        var det = el('details');
        det.appendChild(el('summary', null, t('showWhy')));
        var ul = el('ul', 'ci-why');
        ctx.withheld.forEach(function (w) {
          var li = el('li', null, plainName(w.country || w.ccy));
          var reason = w.reason ? w.reason.charAt(0).toUpperCase() + w.reason.slice(1) + '.' : '';
          if (reason) { li.appendChild(el('span', null, reason)); }
          ul.appendChild(li);
        });
        det.appendChild(ul);
        np.appendChild(det);
      }
    }
    if (showFrozen) {
      put(np, 'p', 'ci-aside', t('frozenTemplate', { country: plainName(ctx.frozenRow.country) }));
    }
    if (np.childNodes.length) { wrap.appendChild(np); }
  }

  /* ---------------------------------------------------------------- footer */
  function footer(wrap) {
    if (!has(C, 'footerLink')) { return; }
    var f = el('div', 'ci-foot');
    var a = put(f, 'a', null, t('footerLink'));
    if (a) { a.href = 'https://github.com/SebR214/margin'; }
    if (f.childNodes.length) { wrap.appendChild(f); }
  }

  /* ---------------------------------------------------------------- filter */
  function apply() {
    [].forEach.call(document.querySelectorAll('.ci-row'), function (r) {
      var okQ = !S.q || r.getAttribute('data-name').indexOf(S.q) >= 0;
      var okR = S.region === '__ALL__' || r.getAttribute('data-region') === S.region;
      r.classList.toggle('hide', !(okQ && okR));
    });
    [].forEach.call(document.querySelectorAll('.ci-band'), function (sec) {
      sec.hidden = sec.querySelectorAll('.ci-row:not(.hide)').length === 0;
    });
  }

  /* ---------------------------------------------------------------- page */
  function buildCtx() {
    var countries = D.countries || [];
    var withheld = D.withheld || [];
    var unverified = D.unverified || [];
    var total = countries.length + withheld.length + unverified.length;
    var moversByCcy = {};
    ((Mv && Mv.top) || []).forEach(function (m) { moversByCcy[m.ccy] = m.change_pp; });

    var allRows = countries.map(function (c) {
      var spark = c.spark || [];
      var lo = spark.length ? Math.min.apply(null, spark) : c.index_pct;
      var hi = spark.length ? Math.max.apply(null, spark) : c.index_pct;
      return {
        ccy: c.ccy, country: plainName(c.country || c.ccy), p: c.index_pct,
        buy: c.buy_price, fx: c.fx_mid_per_usd, region: c.region,
        unranked: c.denominator_class === 'unmaintained',
        lo: lo, hi: hi,
        w: Object.prototype.hasOwnProperty.call(moversByCcy, c.ccy) ? moversByCcy[c.ccy] : null
      };
    });
    var ranked = allRows.filter(function (r) { return !r.unranked; });
    var frozenRow = allRows.filter(function (r) { return r.unranked; })[0] || null;

    var grouped = { far: [], above: [], near: [], below: [] };
    ranked.forEach(function (r) { grouped[bandOf(r.p)].push(r); });
    Object.keys(grouped).forEach(function (k) { grouped[k].sort(function (a, b) { return b.p - a.p; }); });

    var topRow = ranked.length ? ranked.reduce(function (a, b) { return b.p > a.p ? b : a; }) : null;

    var rankedRegions = {};
    ranked.forEach(function (r) { if (r.region) { rankedRegions[r.region] = true; } });

    var asof = D.as_of_utc ? new Date(D.as_of_utc) : null;
    var time = asof
      ? String(asof.getUTCHours()).padStart(2, '0') + ':00'
      : '';

    var topMover = Mv && Mv.top && Mv.top[0];
    var weeklySample = topMover && topMover.change_pp != null ? fmtPts(topMover.change_pp) : '';

    return {
      nearCount: grouped.near.length, farCount: grouped.far.length, rankedLen: ranked.length,
      topName: topRow ? topRow.country : '', topX: topRow ? Math.abs(r1(topRow.p)).toFixed(1) : '',
      time: time, pricedCount: countries.length, total: total,
      regionOrder: D.region_order || [], rankedRegions: rankedRegions,
      grouped: grouped, withheld: withheld, frozenRow: frozenRow, weeklySample: weeklySample
    };
  }

  function page() {
    var ctx = buildCtx();
    var wrap = el('div', 'ci-wrap');
    header(wrap);
    hero(wrap, ctx);
    tools(wrap, ctx);
    keyRow(wrap, ctx);
    bandsSection(wrap, ctx);
    noPriceSection(wrap, ctx);
    footer(wrap);
    app.innerHTML = '';
    app.appendChild(wrap);
    apply();
  }

  Promise.all([
    getJSON('copy.json'), getJSON('data/index_latest.json'),
    getJSON('data/movers_week.json').catch(function () { return null; })
  ]).then(function (r) {
    C = r[0].countries || {};
    H = r[0].homeData || {};
    D = r[1];
    Mv = r[2];
    page();
  }).catch(function () {
    var wrap = el('div', 'ci-wrap');
    app.innerHTML = '';
    fetch('copy.json').then(function (x) { return x.json(); }).then(function (c) {
      put(wrap, 'p', null, c.countries && c.countries.loadFailed);
      app.appendChild(wrap);
    }).catch(function () { /* nothing to say without copy */ });
  });
})();

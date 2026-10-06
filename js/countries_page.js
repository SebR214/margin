/* The countries page, built from stored files only (SEB-240).
 *
 * Numbers, dates, currency codes and country names come from data/*.json.
 * Every word comes from copy.json: "countries" for this page, "homeData" for the
 * nav, the brand and the big-number caption. A key that is empty (or missing) is
 * not rendered, so a control whose words are not written yet stays hidden.
 * No word is written in this file.
 *
 * Reads: data/heatmap_daily.json, data/index_latest.json, data/record_daily.json,
 * data/cycle_log.json, copy.json.
 */
(function () {
  var C = {}, H = {}, D = {};
  var S = { filter: 'all', q: '' };
  var app = document.getElementById('app');

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
  function pct(n) { return (n > 0 ? '+' : '') + num(n, 1) + '%'; }
  function dShort(day) {
    return new Date(day + 'T00:00:00Z').toLocaleDateString('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC' });
  }
  function getJSON(url) {
    return fetch(url).then(function (r) { if (!r.ok) { throw new Error(url); } return r.json(); });
  }
  function claimOk(key) { return !!(window.Claims && window.Claims.blocked && !window.Claims.blocked(key)); }
  function countryHref(ccy) { return 'country.html?ccy=' + encodeURIComponent(ccy); }

  /* ---------------------------------------------------------------- header */
  function header(wrap) {
    var h = el('div', 'hp-head');
    var left = el('div', 'hp-headleft');
    var logo = put(left, 'a', ['hp-logo', 'mono'], th('brand'));
    if (logo) { logo.href = './index.html'; }
    var nav = el('nav', 'hp-nav');
    [['navCountries', 'countries.html'], ['navRoutes', 'sending-money.html'], ['navSources', 'sources.html'],
     ['navFindings', 'findings.html'], ['navHow', 'how-it-works.html']].forEach(function (n) {
      var a = put(nav, 'a', 'hp-navlink', th(n[0]));
      if (a) { a.href = './' + n[1]; }
    });
    if (nav.childNodes.length) { left.appendChild(nav); }
    h.appendChild(left);
    wrap.appendChild(h);
  }

  /* ---------------------------------------------------------------- rows */
  // One row per currency. gap is the latest day's value from the daily heat file;
  // a currency with no value that day has gap == null and is listed as having no price.
  function buildRows() {
    var days = H2.days;
    var byCcy = {};
    H2.currencies.forEach(function (c) { byCcy[c.ccy] = c; });
    var withheld = {};
    (D.index.withheld || []).forEach(function (w) { withheld[w.ccy] = w; });
    (D.index.unverified || []).forEach(function (u) { var k = typeof u === 'string' ? u : u.ccy; if (k && !withheld[k]) { withheld[k] = { ccy: k, reason: null }; } });
    var names = {};
    (D.index.countries || []).concat(D.index.withheld || [], D.index.unverified || []).forEach(function (c) {
      if (c && c.ccy) { names[c.ccy] = c.country || names[c.ccy]; }
      else if (typeof c === 'string') { names[c] = names[c] || null; }
    });
    Object.keys(D.extraNames || {}).forEach(function (k) { if (D.extraNames[k]) { names[k] = D.extraNames[k]; } });
    var all = {};
    Object.keys(names).forEach(function (k) { all[k] = true; });
    Object.keys(byCcy).forEach(function (k) { all[k] = true; });
    return Object.keys(all).map(function (ccy) {
      var c = byCcy[ccy];
      var cells = c ? c.cells : [];
      var first = -1;
      for (var i = 0; i < cells.length; i++) { if (cells[i] != null) { first = i; break; } }
      var last = cells.length && !withheld[ccy] ? cells[cells.length - 1] : null;
      var series = first >= 0 ? cells.slice(first).filter(function (v) { return v != null; }) : [];
      return {
        ccy: ccy, country: plainName((c && c.country) || names[ccy] || ccy),
        gap: last, series: series, firstDay: first >= 0 ? days[first] : null,
        unranked: !!(c && c.ranked === false),
        reason: withheld[ccy] ? withheld[ccy].reason : null
      };
    });
  }
  var H2 = null;

  function lineSvg(series, neg) {
    var NS = 'http://www.w3.org/2000/svg';
    var svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('class', 'cr-line' + (neg ? ' neg' : ''));
    svg.setAttribute('viewBox', '0 0 100 28');
    svg.setAttribute('preserveAspectRatio', 'none');
    svg.setAttribute('aria-hidden', 'true');
    if (series.length < 2) { return svg; }
    var lo = Math.min.apply(null, series.concat([0])), hi = Math.max.apply(null, series.concat([0]));
    if (hi === lo) { hi = lo + 1; }
    var y = function (v) { return 26 - ((v - lo) / (hi - lo)) * 24; };
    var zero = document.createElementNS(NS, 'line');
    zero.setAttribute('x1', 0); zero.setAttribute('x2', 100); zero.setAttribute('y1', y(0)); zero.setAttribute('y2', y(0));
    svg.appendChild(zero);
    var pl = document.createElementNS(NS, 'polyline');
    pl.setAttribute('points', series.map(function (v, i) { return (i / (series.length - 1) * 100).toFixed(2) + ',' + y(v).toFixed(2); }).join(' '));
    svg.appendChild(pl);
    return svg;
  }

  // Stored names keep a leading "the" for use in sentences; a list shows the bare name.
  function plainName(n) { return String(n).replace(/^the /i, ''); }

  function rowEl(r, rank) {
    var a = el('a', ['cr-row', 'trow']);
    a.href = countryHref(r.ccy);
    a.setAttribute('data-ccy', r.ccy);
    a.setAttribute('data-name', (r.country + ' ' + r.ccy).toLowerCase());
    a.setAttribute('data-sign', r.gap == null ? 'none' : (r.gap >= 0 ? 'above' : 'below'));
    a.appendChild(el('span', ['mono', 'cr-rank'], rank != null ? String(rank) : ''));
    var nm = el('span', 'cr-name');
    nm.appendChild(el('span', null, r.country));
    nm.appendChild(el('span', ['mono', 'cr-code'], r.ccy));
    a.appendChild(nm);
    var showGap = r.gap != null && !r.unranked;
    a.appendChild(el('span', ['mono', 'cr-gap', showGap ? (r.gap < 0 ? 'neg' : 'pos') : 'none'], showGap ? pct(r.gap) : ''));
    var cell = el('span');
    cell.appendChild(lineSvg(r.series, r.gap != null && r.gap < 0));
    a.appendChild(cell);
    return a;
  }

  function listHead(parent) {
    var tpl = document.getElementById('crHeadTpl');
    if (!tpl) { return; }
    var h = tpl.content.firstElementChild.cloneNode(true);
    [].forEach.call(h.querySelectorAll('[data-k]'), function (n) { n.textContent = t(n.getAttribute('data-k')); });
    parent.appendChild(h);
  }

  /* ---------------------------------------------------------------- page */
  function hero(wrap, rows, ranked) {
    var s = el('section', ['hp-hero', 'hero', 'bleed']);
    var cc = D.record && D.record.totals ? D.record.totals.currencies : rows.length;
    put(s, 'h1', null, t('title', { count: num(cc) }));
    put(s, 'p', ['soft', 'hp-lede'], t('lede'));
    var top = ranked[0];
    if (top) {
      var bigBox = el('div', 'hp-bigbox');
      var a = el('a', ['mono', 'hp-big']);
      a.href = countryHref(top.ccy);
      a.textContent = num(top.gap, 0) + '%';
      bigBox.appendChild(a);
      put(bigBox, 'span', 'soft', th('bigCaption', { country: top.country, ccy: top.ccy, date: dShort(H2.last_day), gap: num(top.gap, 1) }));
      s.appendChild(bigBox);
    }
    var st = D.cycles && D.cycles.steps && D.cycles.steps.currencies;
    if (st && claimOk('homeData.updatedCount')) {
      put(s, 'p', ['muted', 'hp-body'], t('metaTemplate', {
        time: ((D.cycles && D.cycles.last_reading_utc) || D.index.as_of_utc || '').slice(11, 16), n: num(st.collected), total: num(cc)
      }));
    }
    if (s.childNodes.length) { wrap.appendChild(s); }
  }

  function tools(wrap) {
    var box = el('div', 'cr-tools');
    if (has(C, 'searchLabel')) {
      var inp = el('input', 'cr-search');
      inp.type = 'search';
      inp.setAttribute('aria-label', t('searchLabel'));
      inp.placeholder = t('searchLabel');
      inp.addEventListener('input', function () { S.q = inp.value.trim().toLowerCase(); apply(); });
      box.appendChild(inp);
    }
    var opts = [['all', 'filterAll'], ['above', 'filterAbove'], ['below', 'filterBelow']].filter(function (o) { return has(C, o[1]); });
    if (opts.length === 3) {
      var f = el('div', 'cr-filters');
      opts.forEach(function (o) {
        var b = el('button', 'cr-chip', t(o[1]));
        b.type = 'button';
        b.setAttribute('aria-pressed', o[0] === S.filter ? 'true' : 'false');
        b.addEventListener('click', function () {
          S.filter = o[0];
          [].forEach.call(f.children, function (x) { x.setAttribute('aria-pressed', x === b ? 'true' : 'false'); });
          apply();
        });
        f.appendChild(b);
      });
      box.appendChild(f);
    }
    if (box.childNodes.length) { wrap.appendChild(box); }
  }

  function apply() {
    [].forEach.call(document.querySelectorAll('.cr-row'), function (r) {
      var okQ = !S.q || r.getAttribute('data-name').indexOf(S.q) >= 0;
      var okF = S.filter === 'all' || r.getAttribute('data-sign') === S.filter;
      r.hidden = !(okQ && okF);
    });
  }

  function page() {
    var wrap = el('div', 'hp-wrap');
    header(wrap);
    var rows = buildRows();
    var ranked = rows.filter(function (r) { return r.gap != null && !r.unranked; })
      .sort(function (a, b) { return b.gap - a.gap; });
    var frozen = rows.filter(function (r) { return r.gap != null && r.unranked; });
    var none = rows.filter(function (r) { return r.gap == null; })
      .sort(function (a, b) { return a.country < b.country ? -1 : 1; });
    hero(wrap, rows, ranked);
    tools(wrap);

    var sec = el('section', ['hp-sec', 'hp-gap24']);
    var list = el('div', 'cr-list');
    listHead(list);
    ranked.forEach(function (r, i) { list.appendChild(rowEl(r, i + 1)); });
    frozen.forEach(function (r) { list.appendChild(rowEl(r, null)); });
    sec.appendChild(list);
    if (frozen.length) {
      var names = frozen.map(function (r) { return r.country; }).join(', ');
      put(sec, 'p', ['muted', 'hp-small', 'cr-note'], t(frozen.length === 1 ? 'frozenOneTemplate' : 'frozenManyTemplate', { names: names }));
    }
    wrap.appendChild(sec);

    if (none.length) {
      var s2 = el('section', ['hp-sec', 'hp-gap24']);
      put(s2, 'h2', null, t('withheldTitleTemplate', { n: num(none.length), countries: t(none.length === 1 ? 'countryOne' : 'countryMany') }));
      put(s2, 'p', ['muted', 'hp-small', 'cr-note'], t('withheldNoteTemplate', { min: num(D.index.min_buy_ads) }));
      var l2 = el('div', 'cr-list');
      none.forEach(function (r) {
        var row = rowEl(r, null);
        l2.appendChild(row);
      });
      s2.appendChild(l2);
      wrap.appendChild(s2);
    }

    var foot = el('section', ['hp-sec']);
    var how = put(foot, 'a', ['hp-biglink', 'hp-small'], t('howLink'));
    if (how) { how.href = 'how-it-works.html'; }
    put(foot, 'p', ['muted', 'hp-small'], t('footer'));
    var gh = put(foot, 'a', ['hp-biglink', 'hp-small'], t('footerLink'));
    if (gh) { gh.href = 'https://github.com/SebR214/margin'; }
    if (foot.childNodes.length) { wrap.appendChild(foot); }

    app.innerHTML = '';
    app.appendChild(wrap);
    apply();
  }

  Promise.all([
    getJSON('copy.json'), getJSON('data/heatmap_daily.json'), getJSON('data/index_latest.json'),
    getJSON('data/record_daily.json').catch(function () { return null; }),
    getJSON('data/cycle_log.json').catch(function () { return null; }),
    window.Claims ? window.Claims.load() : null
  ]).then(function (r) {
    var extra = (r[2].unverified || []).filter(function (x) { return typeof x === 'string'; });
    return Promise.all(extra.map(function (k) {
      return getJSON('data/countries/' + encodeURIComponent(k) + '.json').then(function (d) { return [k, d.country]; }).catch(function () { return [k, null]; });
    })).then(function (pairs) {
      var m = {};
      pairs.forEach(function (p) { m[p[0]] = p[1]; });
      r.push(m);
      return r;
    });
  }).then(function (r) {
    C = r[0].countries || {};
    H = r[0].homeData || {};
    H2 = r[1];
    D = { index: r[2], record: r[3], cycles: r[4], extraNames: r[6] };
    page();
  }).catch(function () {
    var wrap = el('div', 'hp-wrap');
    app.innerHTML = '';
    fetch('copy.json').then(function (x) { return x.json(); }).then(function (c) {
      put(wrap, 'p', 'soft', c.countries && c.countries.loadFailed);
      app.appendChild(wrap);
    }).catch(function () { /* nothing to say without copy */ });
  });
})();

/* Research (SEB-301): research.html lists the analyses, research-capital-controls.html is the first one, the dollar premium as a
   capital-controls meter. Every number comes from data/research/capital_controls.json (tools/research_capital_controls.py); every word
   from copy.json -> researchData (nav words from findingData), and an element whose key is empty is not drawn. Hand-written DOM. */
(function () {
  var app = document.getElementById('app');
  var mode = document.body.getAttribute('data-page');
  var C = {}, NAVC = {}, NAMES = {};
  var BANDS = [['b0', 2], ['b1', 8], ['b2', 25], ['b3', 50], ['b4', 1e9]];     // upper edges of a premium, in percent

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = Array.isArray(cls) ? cls.join(' ') : cls;
    if (text !== undefined && text !== null && text !== '') n.textContent = text;
    return n;
  }
  function kid(p, c) { if (c) p.appendChild(c); return c; }
  function T(k, v) {
    var s = C[k];
    if (typeof s !== 'string' || !s) return '';
    return s.replace(/\{(\w+)\}/g, function (m, x) { return v && v[x] != null ? v[x] : ''; });
  }
  function word(tag, cls, key) { var t = T(key); return t ? el(tag, cls, t) : null; }
  function nm_(ccy) { return String(NAMES[ccy] || ccy).replace(/^./, function (c) { return c.toUpperCase(); }); }
  function fmt(p) { var a = Math.abs(p), t = a >= 10 ? String(Math.round(a)) : a.toFixed(1); return (p < 0 && +t !== 0 ? '-' : '') + t; }   // no "-0.0"
  function band(p) {
    if (p < -2) return 'bl';
    for (var i = 0; i < BANDS.length; i++) { if (p < BANDS[i][1]) return BANDS[i][0]; }
    return 'b4';
  }

  function header() {
    var head = el('header', 'fp-head');
    var brand = kid(head, el('div', 'fp-brand'));
    var logo = kid(brand, el('a', ['fp-logo', 'mono'], typeof C.brand === 'string' ? C.brand : ''));
    logo.href = './index.html';
    var nav = el('nav', 'fp-nav');
    [[NAVC.navCountries, './countries.html'], [NAVC.navRoutes, './sending-money.html'], [NAVC.navSources, './sources.html'],
     [NAVC.navFindings, './findings.html'], [C.navResearch, './research.html'], [NAVC.navHowItWorks, './how-it-works.html']].forEach(function (l) {
      if (!l[0]) return;
      var a = el('a', '', l[0]);
      a.href = l[1];
      if (l[1] === './research.html') a.setAttribute('aria-current', 'page');
      nav.appendChild(a);
    });
    if (nav.firstChild) brand.appendChild(nav);
    return head;
  }

  function renderIndex(wrap, doc) {
    var hero = kid(wrap, el('div', 'fp-hero'));
    var text = kid(hero, el('div', 'fp-hero-text'));
    kid(text, word('h1', '', 'indexTitle'));
    kid(text, word('p', ['soft', 'fp-line'], 'indexLead'));
    if (!text.firstChild) wrap.removeChild(hero);
    // one row per piece of research, like the Findings list: title, one line, the dates, an arrow. No grey card (25 Oct, Seb).
    var list = el('div', 'rs-list');
    var a = el('a', 'rs-item');
    a.href = './research-capital-controls.html';
    var body = kid(a, el('span', 'rs-item-body'));
    kid(body, word('span', 'rs-item-title', 'cardTitle'));
    kid(body, word('span', 'rs-item-line', 'cardLine'));
    if (doc && T('cardMeta')) {
      kid(body, el('span', 'rs-item-meta', T('cardMeta', { n: doc.countries, from: doc.years[0], to: doc.years[doc.years.length - 1] })));
    }
    a.appendChild(el('span', 'rs-item-go', '\u2192'));
    if (body.firstChild) { list.appendChild(a); wrap.appendChild(list); }
  }

  function byCountry(doc) {
    var m = {};
    doc.rows.forEach(function (r) { (m[r.ccy] = m[r.ccy] || { ccy: r.ccy, type: r.type, years: {}, peak: -1e9 }); m[r.ccy].years[r.year] = r; m[r.ccy].peak = Math.max(m[r.ccy].peak, r.median_premium_pct); });
    return Object.keys(m).map(function (k) { return m[k]; }).sort(function (a, b) { return b.peak - a.peak; });
  }

  function chart(doc) {
    var sec = el('section', ['fp-sec', 'rs-chart']);
    var h = el('div', 'fp-sec-head');
    kid(h, word('h2', '', 'chartHeading'));
    kid(h, word('p', ['muted', 'fp-note'], 'chartLine'));
    if (h.firstChild) sec.appendChild(h);
    var legend = el('div', 'rs-legend');
    [['bl', 'bandBelow'], ['b0', 'bandUnder2'], ['b1', 'band2to8'], ['b2', 'band8to25'], ['b3', 'band25to50'], ['b4', 'bandOver50']].forEach(function (b) {
      var t = T(b[1]);
      if (!t) return;
      var s = el('span', 'rs-key');
      s.appendChild(el('i', ['rs-cell', 'rs-' + b[0]]));
      s.appendChild(document.createTextNode(t));
      legend.appendChild(s);
    });
    if (legend.firstChild) sec.appendChild(legend);
    var years = doc.years, rows = byCountry(doc), last = years[years.length - 1];
    var lastPartial = doc.rows.some(function (r) { return r.year === last && r.partial === 'yes'; });
    var box = el('div', 'rs-scroll');
    var grid = el('div', 'rs-grid');
    grid.style.setProperty('--cols', String(years.length));
    grid.setAttribute('role', 'table');
    var head = el('div', ['rs-row', 'rs-head']);
    head.setAttribute('role', 'row');
    head.appendChild(el('span', 'rs-name'));
    years.forEach(function (y) {
      head.appendChild(el('span', ['rs-y', 'mono'], y === last && lastPartial && T('partialYear') ? T('partialYear', { year: y }) : String(y)));
    });
    grid.appendChild(head);
    rows.forEach(function (c) {
      var r = el('div', 'rs-row');
      r.setAttribute('role', 'row');
      var nm = el('span', 'rs-name', nm_(c.ccy));
      var tag = T(c.type === 'managed' ? 'tagManaged' : 'tagFloating');
      if (tag) nm.appendChild(el('small', 'rs-tag', tag));
      r.appendChild(nm);
      years.forEach(function (y) {
        var d = c.years[y], cell;
        if (!d) {
          cell = el('span', ['rs-cell', 'rs-none']);
          if (T('noCell')) cell.title = T('noCell', { country: nm_(c.ccy), year: y });
        } else {
          var p = d.median_premium_pct;
          cell = el('span', ['rs-cell', 'rs-' + band(p), 'mono'], fmt(p));
          var tip = T(p < 0 ? 'cellTipBelow' : 'cellTip', { country: nm_(c.ccy), year: y, value: fmt(Math.abs(p)) + '%', days: d.days });
          if (tip) cell.title = tip;
        }
        cell.setAttribute('role', 'cell');
        r.appendChild(cell);
      });
      grid.appendChild(r);
    });
    box.appendChild(grid);
    sec.appendChild(box);
    return sec;
  }

  function result(doc) {
    var sec = el('section', 'fp-sec');
    var h = el('div', 'fp-sec-head');
    kid(h, word('h2', '', 'resultHeading'));
    if (h.firstChild) sec.appendChild(h);
    var top = doc.rows.reduce(function (a, r) { return !a || r.median_premium_pct > a.median_premium_pct ? r : a; }, null);
    var calm = doc.rows.filter(function (r) { return Math.abs(r.median_premium_pct) < 2; }).length;
    var big = doc.rows.filter(function (r) { return r.median_premium_pct >= 25; });
    var managedBig = big.filter(function (r) { return r.type === 'managed'; }).length;
    var lines = [
      top && T('resultTop', { country: NAMES[top.ccy] || top.ccy, year: top.year, value: fmt(top.median_premium_pct) + '%' }),
      T('resultCalm', { n: calm, N: doc.rows.length }),
      big.length && T('resultBig', { n: big.length, m: managedBig })
    ];
    lines.forEach(function (t) { if (t) sec.appendChild(el('p', ['fp-line', 'rs-result'], t)); });
    return sec.querySelector('p') ? sec : null;
  }

  function paras(heading, keys) {
    var sec = el('section', 'fp-sec');
    var h = el('div', 'fp-sec-head');
    kid(h, word('h2', '', heading));
    if (h.firstChild) sec.appendChild(h);
    keys.forEach(function (k) { kid(sec, word('p', ['soft', 'fp-line'], k)); });
    return sec.querySelector('p') ? sec : null;
  }

  function downloads(doc) {
    var sec = el('section', 'fp-sec');
    var h = el('div', 'fp-sec-head');
    kid(h, word('h2', '', 'downloadHeading'));
    if (h.firstChild) sec.appendChild(h);
    var list = el('div', 'rs-dl');
    [['downloadCsv', './data/research/capital_controls.csv'], ['downloadJson', './data/research/capital_controls.json']].forEach(function (d) {
      var t = T(d[0], { n: doc.rows.length });
      if (!t) return;
      var a = el('a', 'fp-back', t);
      a.href = d[1];
      a.setAttribute('download', '');
      list.appendChild(a);
    });
    if (list.firstChild) sec.appendChild(list);
    return sec.querySelector('a') ? sec : null;
  }

  function renderCapital(wrap, doc) {
    var back = word('a', 'fp-back', 'backLink');
    if (back) { back.href = './research.html'; wrap.appendChild(back); }
    var hero = el('div', 'fp-hero');
    var text = kid(hero, el('div', 'fp-hero-text'));
    kid(text, word('h1', '', 'pageTitle'));
    kid(text, word('p', ['soft', 'fp-line'], 'pageLead'));
    kid(text, word('p', ['muted', 'fp-note'], 'labelNote'));
    if (text.firstChild) wrap.appendChild(hero);
    if (!doc || !doc.rows || !doc.rows.length) return;
    [result(doc), chart(doc), paras('methodHeading', ['method1', 'method2', 'method3', 'method4']), paras('limitsHeading', ['limit1', 'limit2']), downloads(doc)]
      .forEach(function (s) { if (s) wrap.appendChild(s); });
    var t = T('pageTitle');
    if (t) document.title = 'margin.wiki: ' + t;
  }

  function load(u) { return fetch(u).then(function (r) { if (!r.ok) throw new Error(u); return r.json(); }); }
  Promise.all([load('./copy.json').catch(function () { return {}; }), load('./data/research/capital_controls.json').catch(function () { return null; }),
               load('./data/index_latest.json').catch(function () { return null; })]).then(function (res) {
    C = res[0].researchData || {};
    C.brand = typeof res[0].brand === 'string' ? res[0].brand : '';
    NAVC = res[0].findingData || {};
    ((res[2] && res[2].countries) || []).forEach(function (c) { NAMES[c.ccy] = c.country; });
    var wrap = el('div', 'wrap');
    wrap.appendChild(header());
    if (mode === 'index') { renderIndex(wrap, res[1]); } else { renderCapital(wrap, res[1]); }
    app.appendChild(wrap);
  });
})();

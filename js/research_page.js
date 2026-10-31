/* Research (SEB-301): research.html lists the analyses, research-capital-controls.html is the first one, the dollar premium as a
   capital-controls meter. Every number comes from data/research/capital_controls.json (tools/research_capital_controls.py); every word
   from copy.json -> researchData (nav words from findingData), and an element whose key is empty is not drawn. Hand-written DOM. */
(function () {
  var app = document.getElementById('app');
  var mode = document.body.getAttribute('data-page');
  var C = {}, NAVC = {}, NAMES = {};
  var MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  function monthName(m) { return MON[+m.slice(5, 7) - 1] + ' ' + m.slice(0, 4); }
  function dayName(d) { return (+d.slice(8, 10)) + ' ' + MON[+d.slice(5, 7) - 1] + ' ' + d.slice(0, 4); }
  function cname(r) { return String(r.country || NAMES[r.ccy] || r.ccy).replace(/^the /i, '').replace(/^./, function (c) { return c.toUpperCase(); }); }
  function srcName(id) { var n = C.srcNames && C.srcNames[id]; return n || String(id).replace(/_/g, ' '); }
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

  function renderIndex(wrap, doc, months, pairs) {
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
      kid(body, el('span', 'rs-item-meta', T('cardMeta', { n: doc.countries, from: doc.years[0], to: doc.years[doc.years.length - 1] }) +
        (months && T('cardAsOf') ? ' ' + T('cardAsOf', { date: dayName(months.as_of_day) }) : '')));
    }
    a.appendChild(el('span', 'rs-item-go', '\u2192'));
    if (body.firstChild) { list.appendChild(a); wrap.appendChild(list); }
    if (pairs && T('cardTitle2')) {
      var b = el('a', 'rs-item');
      b.href = './research-source-pairs.html';
      var bb = kid(b, el('span', 'rs-item-body'));
      kid(bb, word('span', 'rs-item-title', 'cardTitle2'));
      kid(bb, word('span', 'rs-item-line', 'cardLine2'));
      kid(bb, el('span', 'rs-item-meta', T('cardMeta2', { N: pairs.compared, days: pairs.window_days }) + ' ' + T('cardAsOf', { date: dayName(pairs.as_of_utc.slice(0, 10)) })));
      b.appendChild(el('span', 'rs-item-go', '\u2192'));
      list.appendChild(b);
      if (!list.parentNode) { wrap.appendChild(list); }
    }
  }

  function byCountry(doc) {
    var m = {};
    doc.rows.forEach(function (r) { (m[r.ccy] = m[r.ccy] || { ccy: r.ccy, type: r.type, years: {}, peak: -1e9 }); m[r.ccy].years[r.year] = r; m[r.ccy].peak = Math.max(m[r.ccy].peak, r.median_premium_pct); });
    return Object.keys(m).map(function (k) { return m[k]; }).sort(function (a, b) { return b.peak - a.peak; });
  }

  function chart(doc, k) {
    k = k || { h: 'chartHeading', l: 'chartLine' };
    var sec = el('section', ['fp-sec', 'rs-chart']);
    var h = el('div', 'fp-sec-head');
    kid(h, word('h2', '', k.h));
    kid(h, word('p', ['muted', 'fp-note'], k.l));
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

  // the months we saw ourselves, drawn with the yearly chart's own code: each month is a column, labelled like a year
  function monthsDoc(months, yearly) {
    var type = {};
    yearly.rows.forEach(function (r) { type[r.ccy] = r.type; });
    var keys = []; months.months.forEach(function (r) { if (keys.indexOf(r.month) < 0) keys.push(r.month); });
    keys.sort();
    var label = {}; keys.forEach(function (m) { label[m] = monthName(m); });
    return { years: keys.map(function (m) { return label[m]; }), rows: months.months.map(function (r) {
      return { ccy: r.ccy, type: type[r.ccy] || 'floating', year: label[r.month], median_premium_pct: r.median_premium_pct, days: r.days, partial: r.partial ? 'yes' : 'no' };
    }) };
  }
  function monthsSection(months, yearly) {
    if (!months || !months.months || !months.months.length || !T('monthsHeading')) return null;
    var sec = chart(monthsDoc(months, yearly), { h: 'monthsHeading', l: 'monthsLine' });
    if (T('monthsAsOf')) sec.insertBefore(el('p', ['muted', 'fp-note'], T('monthsAsOf', { date: dayName(months.as_of_day) })), sec.children[1] || null);
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

  function renderCapital(wrap, doc, months) {
    var back = word('a', 'fp-back', 'backLink');
    if (back) { back.href = './research.html'; wrap.appendChild(back); }
    var hero = el('div', 'fp-hero');
    var text = kid(hero, el('div', 'fp-hero-text'));
    kid(text, word('h1', '', 'pageTitle'));
    kid(text, word('p', ['soft', 'fp-line'], 'pageLead'));
    kid(text, word('p', ['muted', 'fp-note'], 'labelNote'));
    if (text.firstChild) wrap.appendChild(hero);
    if (!doc || !doc.rows || !doc.rows.length) return;
    [result(doc), chart(doc), monthsSection(months, doc), paras('methodHeading', ['method1', 'method2', 'method3', 'method4']), paras('limitsHeading', ['limit1', 'limit2']), downloads(doc)]
      .forEach(function (s) { if (s) wrap.appendChild(s); });
  }

  function renderPairs(wrap, doc) {
    var back = word('a', 'fp-back', 'backLink');
    if (back) { back.href = './research.html'; wrap.appendChild(back); }
    var hero = el('div', 'fp-hero');
    var text = kid(hero, el('div', 'fp-hero-text'));
    kid(text, word('h1', '', 'pairsTitle'));
    kid(text, word('p', ['soft', 'fp-line'], 'pairsLead'));
    kid(text, el('p', ['muted', 'fp-note'], [T('pairsLabel'), doc ? T('monthsAsOf', { date: dayName(doc.as_of_utc.slice(0, 10)) }) : ''].join(' ').trim()));
    if (text.firstChild) wrap.appendChild(hero);
    if (!doc || !doc.countries || !doc.countries.length) return;
    var wide = doc.countries.filter(function (r) { return r.gap_pct >= doc.wide_pct; });
    var sec = el('section', 'fp-sec');
    var h = el('div', 'fp-sec-head'); kid(h, word('h2', '', 'resultHeading')); sec.appendChild(h);
    sec.appendChild(el('p', ['fp-line', 'rs-result'], T('pairsTight', { n: doc.bands.tight, N: doc.compared, pct: doc.tight_pct })));
    if (wide.length) {
      sec.appendChild(el('p', ['fp-line', 'rs-result'], T('pairsWide', { n: wide.length, pct: doc.wide_pct,
        list: wide.slice(0, 8).map(cname).join(', ') })));
    }
    wrap.appendChild(sec);
    var lst = el('section', 'fp-sec');
    var lh = el('div', 'fp-sec-head'); kid(lh, word('h2', '', 'pairsListHeading')); lst.appendChild(lh);
    var rows = el('div', 'rs-list');
    doc.countries.slice(0, 12).forEach(function (r) {
      var a = el('a', 'rs-item'); a.href = './country/' + encodeURIComponent(String(r.ccy).toLowerCase()) + '/';
      var b = kid(a, el('span', 'rs-item-body'));
      kid(b, el('span', 'rs-item-title', cname(r)));
      kid(b, el('span', 'rs-item-line', T('pairsRow', { a: srcName(r.a), b: srcName(r.b), gap: fmt(r.gap_pct) + '%', hours: r.hours })));
      a.appendChild(el('span', 'rs-item-go', '\u2192'));
      rows.appendChild(a);
    });
    lst.appendChild(rows); wrap.appendChild(lst);
    var ms = el('section', 'fp-sec'); var mh = el('div', 'fp-sec-head'); kid(mh, word('h2', '', 'pairsMethodHeading')); ms.appendChild(mh);
    ['pairsMethod1', 'pairsMethod2', 'pairsLimits'].forEach(function (k) { var t = T(k, { days: doc.window_days, hours: doc.min_common_hours }); if (t) ms.appendChild(el('p', ['soft', 'fp-line'], t)); });
    wrap.appendChild(ms);
  }

  function load(u) { return fetch(u).then(function (r) { if (!r.ok) throw new Error(u); return r.json(); }); }
  Promise.all([load('./copy.json').catch(function () { return {}; }), load('./data/research/capital_controls.json').catch(function () { return null; }),
               load('./data/index_latest.json').catch(function () { return null; }),
               load('./data/research/capital_controls_months.json').catch(function () { return null; }),
               load('./data/research/source_pairs.json').catch(function () { return null; }),
               window.Claims ? window.Claims.load() : null]).then(function (res) {
    C = res[0].researchData || {};
    C.brand = typeof res[0].brand === 'string' ? res[0].brand : '';
    NAVC = res[0].findingData || {};
    ((res[2] && res[2].countries) || []).forEach(function (c) { NAMES[c.ccy] = c.country; });
    var wrap = el('div', 'wrap');
    wrap.appendChild(header());
    // the live months and the pairs page print numbers that the claims audit re-derives; blocked ones are not drawn
    var months = res[3] && !(window.Claims && window.Claims.blocked('researchData.monthsLine')) ? res[3] : null;
    var pairs = res[4] && !(window.Claims && window.Claims.blocked('researchData.pairsTight')) ? res[4] : null;
    if (mode === 'index') { renderIndex(wrap, res[1], months, pairs); } else if (mode === 'pairs') { renderPairs(wrap, pairs); } else { renderCapital(wrap, res[1], months); }
    app.appendChild(wrap);
  });
})();

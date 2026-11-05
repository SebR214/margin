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


  var MONS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  function dayY(s) { return s ? (+s.slice(8, 10)) + ' ' + MONS[+s.slice(5, 7) - 1] + ' ' + s.slice(0, 4) : ''; }
  // each row leads with its number, big, on the left (1 Nov, Claude Design review), and a short label under it
  function numCell(a, value, unit) {
    if (value == null || value === '') return;
    var n = el('span', 'rs-item-num');
    n.appendChild(el('b', '', String(value)));
    if (unit) n.appendChild(el('small', '', unit));
    a.insertBefore(n, a.firstChild);
  }

  function renderIndex(wrap, doc, months, pairs) {
    var hero = kid(wrap, el('div', 'fp-hero'));
    var text = kid(hero, el('div', 'fp-hero-text'));
    kid(text, word('h1', '', 'indexTitle'));
    kid(text, word('p', ['soft', 'fp-line'], 'indexLead'));
    if (!text.firstChild) wrap.removeChild(hero);
    // one row per piece of research, like the Findings list: title, one line, the dates, an arrow. No grey card (25 Oct, Seb).
    // how often things update is said once, above the list (1 Nov), not on every row
    var note = word('p', ['muted', 'rs-list-note'], 'listNote');
    if (note) { wrap.appendChild(note); }
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
    if (doc) { numCell(a, doc.countries, T('cardNumUnit')); }
    if (body.firstChild) { list.appendChild(a); wrap.appendChild(list); }
    if (pairs && T('cardTitle2')) {
      var b = el('a', 'rs-item');
      b.href = './research-source-pairs.html';
      var bb = kid(b, el('span', 'rs-item-body'));
      kid(bb, word('span', 'rs-item-title', 'cardTitle2'));
      kid(bb, word('span', 'rs-item-line', 'cardLine2'));
      kid(bb, el('span', 'rs-item-meta', T('cardMeta2', { N: pairs.compared, days: pairs.window_days }) + ' ' + T('cardAsOf', { date: dayName(pairs.as_of_utc.slice(0, 10)) })));
      b.appendChild(el('span', 'rs-item-go', '\u2192'));
      numCell(b, pairs.compared, T('cardNumUnit2'));
      list.appendChild(b);
      if (!list.parentNode) { wrap.appendChild(list); }
    }
    // the third row (SEB-437): the history table, reached from here so that no page is hidden
    if (T('cardTitle3') && brk && brk.length) {
      var c3 = el('a', 'rs-item');
      c3.href = './research-breaks.html';
      var cb = kid(c3, el('span', 'rs-item-body'));
      kid(cb, word('span', 'rs-item-title', 'cardTitle3'));
      kid(cb, word('span', 'rs-item-line', 'cardLine3'));
      kid(cb, word('span', 'rs-item-meta', 'cardMeta3'));
      c3.appendChild(el('span', 'rs-item-go', '\u2192'));
      numCell(c3, brk.length, T('cardNumUnit3'));
      list.appendChild(c3);
      if (!list.parentNode) { wrap.appendChild(list); }
    }
    if (list.firstChild && !list.parentNode) { wrap.appendChild(list); }
  }

  /* The history table (SEB-437): breaks in the official rate found later in a backtest of history, before our hourly record began.
     One table, no page per break. Rows: events_published.json "history" (the replay) and data/map_timeline/landing.json (the gap
     before and after, where a street price existed). A gap we have no price for is a blank, never filled in. */
  var brk = null;
  function pct1(v) { return v.toFixed(1) + '%'; }
  function buildBreaks(pub, land, ownStart) {
    var rows = {}, start = ownStart || (pub && pub.own_start) || '';   // the first day of our hourly record
    var add = function (ccy, date, move, country) {
      var k = ccy + '|' + date;
      rows[k] = rows[k] || { ccy: ccy, date: date, country: country };
      if (move != null) { rows[k].move = move; }
      return rows[k];
    };
    ((pub && (pub.history || pub.events)) || []).forEach(function (e) { if (!start || e.date < start) { add(e.ccy, e.date, e.change_pct); } });
    ((land && land.rows) || []).forEach(function (r) {
      if (start && r.date >= start) { return; }
      var x = add(r.ccy, r.date, null, r.country);
      if (x.move == null) { x.move = r.move_pct; }
      var p = r.premium_before_pct / 100, closed = p > 0 ? Math.max(0, Math.min(1, (r.landing_ratio * (1 + p) - 1) / p)) : 1;
      x.before = r.premium_before_pct;
      x.after = r.premium_before_pct * (1 - closed);   // the part of the gap still open after the jump, as the home page worked it out
    });
    return Object.keys(rows).map(function (k) { return rows[k]; }).sort(function (a, b) { return a.date < b.date ? 1 : -1; });
  }
  function renderBreaks(wrap) {
    var back = word('a', 'fp-back', 'backLink');
    if (back) { back.href = './research.html'; wrap.appendChild(back); }
    var hero = el('div', 'fp-hero');
    var text = kid(hero, el('div', 'fp-hero-text'));
    kid(text, word('h1', '', 'breaksTitle'));
    kid(text, word('p', ['soft', 'fp-line'], 'breaksLead'));
    kid(text, word('p', ['muted', 'fp-note'], 'breaksLabel'));
    if (text.firstChild) wrap.appendChild(hero);
    if (!brk || !brk.length) return;
    var cols = [['colCountry', 'c'], ['colDate', 'd'], ['colMove', 'm'], ['colBefore', 'b'], ['colAfter', 'a']];
    if (cols.some(function (c) { return !T(c[0]); })) return;
    var tb = el('table', 'rs-brk');
    var hd = el('tr');
    cols.forEach(function (c) { var th = el('th', 'rs-brk-' + c[1], T(c[0])); th.setAttribute('scope', 'col'); hd.appendChild(th); });
    tb.appendChild(el('thead')).appendChild(hd);
    var body = el('tbody');
    brk.forEach(function (r) {
      var tr = el('tr');
      var cell = function (k, text) { var td = el('td', 'rs-brk-' + k, text); td.setAttribute('data-label', T(cols.filter(function (c) { return c[1] === k; })[0][0])); tr.appendChild(td); };
      cell('c', cname(r));
      cell('d', dayName(r.date));
      cell('m', r.move == null ? '' : (r.move > 0 ? '+' : '\u2212') + fmt(Math.abs(r.move)) + '%');
      cell('b', r.before == null ? T('noPrice') : pct1(r.before));
      cell('a', r.after == null ? T('noPrice') : pct1(r.after));
      body.appendChild(tr);
    });
    tb.appendChild(body);
    wrap.appendChild(tb);
    kid(wrap, word('p', ['muted', 'fp-note'], 'breaksNote'));
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
    exchangeSection(wrap);
    var ms = el('section', 'fp-sec'); var mh = el('div', 'fp-sec-head'); kid(mh, word('h2', '', 'pairsMethodHeading')); ms.appendChild(mh);
    ['pairsMethod1', 'pairsMethod2', 'pairsLimits'].forEach(function (k) { var t = T(k, { days: doc.window_days, hours: doc.min_common_hours }); if (t) ms.appendChild(el('p', ['soft', 'fp-line'], t)); });
    wrap.appendChild(ms);
  }

  // People against an exchange (4 Nov, Seb): the finding "In 2 countries people pay more from each other than on an exchange"
  // lives here now, as its own section of the pairs page, with its number and its rows. data/findings.json, exchange_vs_p2p.
  var EXCH = null;
  function exchangeSection(wrap) {
    var f = EXCH; if (!f || !(f.evidence || []).length || !NAVC.title_exchange_vs_p2p) return;
    var N = function (k) { return NAVC[k] || ''; };
    var g = function (n) { return Number(n).toLocaleString('en-US'); };
    var sec = el('section', 'fp-sec'); sec.id = 'exchange';
    var h = el('div', 'fp-sec-head');
    kid(h, el('h2', '', N('title_exchange_vs_p2p').replace('{n}', g(f.headline.value))));
    sec.appendChild(h);
    var top = f.evidence.filter(function (e) { return e.persists; })[0];
    var claim = top ? N('claim_exchange_vs_p2p').replace('{country}', top.country).replace('{gap}', top.median_gap_pts.toFixed(1)).replace('{share}', Math.round(top.share_gap_2pts * 100) + '%') : N('claimNone_exchange_vs_p2p');
    if (claim) sec.appendChild(el('p', ['soft', 'fp-line'], claim));
    if (N('evidenceBasis_exchange_vs_p2p')) sec.appendChild(el('p', ['soft', 'fp-line'], N('evidenceBasis_exchange_vs_p2p')));
    var rows = el('div', 'rs-list');
    f.evidence.forEach(function (e) {
      var a = el('a', 'rs-item'); a.href = './country/' + encodeURIComponent(String(e.ccy).toLowerCase()) + '/';
      var b = kid(a, el('span', 'rs-item-body'));
      kid(b, el('span', 'rs-item-title', e.country));
      var ex = (e.exchanges || []).map(function (x) { return x.replace(/^(.*) \(.*\)$/, '$1'); }).filter(function (x, i, l) { return l.indexOf(x) === i; });
      // feeds read through one service (CriptoYa:saldo) are said once with the count, as the old finding page said them
      var via = {}, plainEx = [];
      ex.forEach(function (x) { var m = /^([^:]+):(.*)$/.exec(x); if (m) { (via[m[1]] = via[m[1]] || []).push(m[2]); } else { plainEx.push(x); } });
      Object.keys(via).forEach(function (k) { plainEx.push(via[k].length > 1 && N('brokersVia') ? N('brokersVia').replace('{n}', via[k].length).replace('{name}', k) : k + ' ' + via[k][0].replace(/^./, function (c) { return c.toUpperCase(); })); });
      ex = plainEx;
      kid(b, el('span', 'rs-item-line', Math.round(e.share_gap_2pts * 100) + '% ' + N('field_share_gap_2pts') + ', ' + g(e.hours_checked) + ' ' +
        (e.hours_checked === 1 ? N('field_hour_checked') : N('field_hours_checked')) + ', ' + N('field_since') + ' ' + dayY(e.first_day) + ', ' +
        ex.join(' ' + N('and') + ' ') + ' ' + N('field_against') + ' ' + (e.boards || []).map(function (x) { return N('board_' + x); }).join(' ' + N('and') + ' ') +
        '. ' + (e.persists ? N('field_persists') : N('field_not_persist'))));
      a.appendChild(el('span', 'rs-item-go', '→'));
      numCell(a, (e.median_gap_pts > 0 ? '+' : e.median_gap_pts < 0 ? '−' : '') + Math.abs(e.median_gap_pts).toFixed(1) + '%', N('field_median_gap_pts'));
      rows.appendChild(a);
    });
    sec.appendChild(rows);
    ['method_exchange_vs_p2p', 'limits_exchange_vs_p2p'].forEach(function (k) { if (N(k)) sec.appendChild(el('p', ['soft', 'fp-line'], N(k))); });
    wrap.appendChild(sec);
  }

  function load(u) { return fetch(u, { cache: 'no-store' }).then(function (r) { if (!r.ok) throw new Error(u); return r.json(); }); }
  Promise.all([load('./copy.json').catch(function () { return {}; }), load('./data/research/capital_controls.json').catch(function () { return null; }),
               load('./data/index_latest.json').catch(function () { return null; }),
               load('./data/research/capital_controls_months.json').catch(function () { return null; }),
               load('./data/research/source_pairs.json').catch(function () { return null; }),
               window.Claims ? window.Claims.load() : null,
               mode === 'pairs' ? load('./data/findings.json').catch(function () { return null; }) : null,
               mode === 'breaks' || mode === 'index' ? load('./data/events_published.json').catch(function () { return null; }) : null,
               mode === 'breaks' || mode === 'index' ? load('./data/map_timeline/landing.json').catch(function () { return null; }) : null,
               mode === 'breaks' || mode === 'index' ? load('./data/map_timeline/index.json').catch(function () { return null; }) : null,
               mode === 'breaks' ? load('./data/heatmap_daily.json').catch(function () { return null; }) : null]).then(function (res) {
    C = res[0].researchData || {};
    C.brand = typeof res[0].brand === 'string' ? res[0].brand : '';
    NAVC = res[0].findingData || {};
    ((res[2] && res[2].countries) || []).forEach(function (c) { NAMES[c.ccy] = c.country; });
    var wrap = el('div', 'wrap');
    // the live months and the pairs page print numbers that the claims audit re-derives; blocked ones are not drawn
    var months = res[3] && !(window.Claims && window.Claims.blocked('researchData.monthsLine')) ? res[3] : null;
    var pairs = res[4] && !(window.Claims && window.Claims.blocked('researchData.pairsTight')) ? res[4] : null;
    ((res[10] && res[10].currencies) || []).forEach(function (c) { if (!NAMES[c.ccy]) { NAMES[c.ccy] = c.country; } });
    brk = mode === 'breaks' || mode === 'index' ? buildBreaks(res[7], res[8], res[9] && res[9].own_start) : null;
    EXCH = ((res[6] && res[6].findings) || []).filter(function (f) { return f.id === 'exchange_vs_p2p' && f.published === true; })[0] || null;
    // the page's own title once its words exist (siteHead.breaksTitle); until then the head holds the Research list's
    if (mode === 'breaks' && window.PageHead) {
      window.PageHead.copy().then(function (H) { if (H.breaksTitle) { window.PageHead.set({ title: H.breaksTitle, description: H.breaksDescription }); } });
    }
    if (mode === 'index') { renderIndex(wrap, res[1], months, pairs); } else if (mode === 'pairs') { renderPairs(wrap, pairs); } else if (mode === 'breaks') { renderBreaks(wrap); } else { renderCapital(wrap, res[1], months); }
    app.appendChild(wrap);
  });
})();

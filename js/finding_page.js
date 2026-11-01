/* Finding page (finding.html?id=<id>) and the findings index (findings.html).
   Every number, date, id and file path comes from data/findings.json; every
   word comes from copy.json -> findingData, and an element whose key is empty
   is not rendered. Hand-written DOM, no library. */
(function () {
  var GH = 'https://github.com/SebR214/margin/blob/main/';
  var NON_FIELDS = { route: 1, ccy: 1, side: 1, amount: 1 };
  var PRIMARY = { price_changes: 'changes', weekend_penalty: 'weekend_up', volume_crossover: 'monthly_volume_sgd', sgd_php_never_cheapest: 'hours_priced', exchange_vs_p2p: 'median_gap_pts' };
  var app = document.getElementById('app');
  var mode = document.body.getAttribute('data-page');
  var C = {};
  var BRAND = '';

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = Array.isArray(cls) ? cls.join(String.fromCharCode(32)) : cls;
    if (text !== undefined && text !== null && text !== '') n.textContent = text;
    return n;
  }
  function kid(parent, child) { if (child) parent.appendChild(child); return child; }
  function T(key) { var v = C[key]; return typeof v === 'string' ? v : ''; }
  // A node holding a copy key's text, or null when the key is empty.
  var CLAIMS = null;
  // a finding's claim line: the one that states a count shows only while claims_status.json says the count holds
  function claimLine(f) {
    if (f.id !== 'sgd_php_never_cheapest') { return word('p', ['soft', 'fp-line'], 'claim_' + f.id); }
    var cl = CLAIMS && CLAIMS.claims && CLAIMS.claims['findingData.claim_sgd_php_never_cheapest'];
    var t = cl && cl.ok === true ? T('claim_' + f.id).replace(/\{n\}/g, fmt(cl.value.n)).replace(/\{hours\}/g, fmt(cl.value.hours)) : '';
    return t ? el('p', ['soft', 'fp-line'], t) : null;
  }
  function word(tag, cls, key) { var t = T(key); return t ? el(tag, cls, t) : null; }
  // A finding's title with {approx} filled from its own headline number (4,444,700 -> "S$4.4M"): the figure
  // in a headline is always the stored number, never typed.
  function approxSgd(v) { return 'S$' + (v / 1e6).toFixed(1) + 'M'; }
  function titleOf(f) {
    var t = T('title_' + f.id);
    var v = (f.headline || {}).value;
    return t.replace(/\{approx\}/g, typeof v === 'number' ? approxSgd(v) : '').replace(/\{n\}/g, typeof v === 'number' ? fmt(v) : '');
  }
  // The headline as shown: a monthly volume in Singapore dollars reads "S$4.5M", everything else its stored number.
  function shownHeadline(h) { 
    if (h.unit === 'sgd_per_month') return approxSgd(h.value);
    return fmt(h.value); 
  }
  var MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  // The short label under a number so it reads on its own. 01: the earliest first day in its evidence; 04: the stablecoin's hours
  // are "of" the hours priced at S$5,000. Every value comes from findings.json.
  function shortUnit(f) {
    var ev = f.evidence || [], label = T('short_unit_' + f.id);
    if (!label) return '';
    if (f.id === 'price_changes') {
      var days = ev.map(function (e) { return e.first_day; }).filter(Boolean).sort();
      if (!days.length) return '';
      label = label.replace('{first}', (+days[0].slice(8, 10)) + ' ' + MON[+days[0].slice(5, 7) - 1]);
    }
    return label;
  }
  function shortValue(f, value) {
    if (f.id !== 'sgd_php_never_cheapest') return value;
    var row = (f.evidence || []).filter(function (e) { return e.amount === 5000; })[0];
    return row && typeof row.hours_priced === 'number' ? T('short_value_sgd_php_never_cheapest').replace('{value}', value).replace('{hours}', fmt(row.hours_priced)) || value : value;
  }
  function niceRoute(r) { return String(r || '').replace('->', ' \u2192 '); }

  function fmt(v) {
    if (typeof v !== 'number') return String(v);
    return v.toLocaleString('en-US', { maximumFractionDigits: 2 });
  }
  // "5 Oct, 00:00", then the word UTC once from copy.json (findingData.utc), so a time is never printed without its zone.
  var MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  function fmtTime(s) {
    var m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}:\d{2})/.exec(s || '');
    return m ? (+m[3]) + ' ' + MONTHS[+m[2] - 1] + ', ' + m[4] : (s || '');
  }
  function dayY(s) { return s ? (+s.slice(8, 10)) + ' ' + MON[+s.slice(5, 7) - 1] + ' ' + s.slice(0, 4) : ''; }
  // A finding's retest status ("Still holds", "Weaker", "No longer true") and when it was last rechecked. Only findings with 14 days
  // of retest rows carry f.retest (data/finding_status.json, tools/emit_finding_status.py); with no retest, or an empty word in copy.json, nothing is drawn.
  var STATUS_KEY = { holds: 'statusHolds', weaker: 'statusWeaker', no_longer_true: 'statusNoLonger' };
  function statusText(f) {
    var r = f.retest, w = r && T(STATUS_KEY[r.status] || '');
    if (!w) return '';
    var c = T('statusRechecked');
    return w + (c && r.last_rechecked ? '. ' + c.replace('{date}', dayY(r.last_rechecked)) : '');
  }
  function fmtWhen(s) { var z = T('utc'); return fmtTime(s) + (z && s ? ' ' + z : ''); }
  // The currency a route's amount is sent in: "SGD->PHP" -> "SGD".
  function fromCcy(route) { var m = /^([A-Z]{3})\s*(?:->|\u2192)/.exec(route || ''); return m ? m[1] : ''; }
  function fmtBytes(n) { return n < 1000 ? n + ' B' : (n / 1000).toFixed(1) + ' kB'; }
  function two(i) { return (i < 9 ? '0' : '') + (i + 1); }

  function header() {
    var head = el('header', 'fp-head');
    var brand = kid(head, el('div', 'fp-brand'));
    var logo = kid(brand, el('a', ['fp-logo', 'mono'], BRAND));
    logo.href = './index.html';
    var links = [['navCountries', './countries.html'], ['navRoutes', './sending-money.html'], ['navSources', './sources.html'],
                 ['navResearch', './research.html'], ['navEvents', './events.html'], ['navHowItWorks', './how-it-works.html']];
    var nav = el('nav', 'fp-nav');
    links.forEach(function (l) {
      var a = word('a', '', l[0]);
      if (!a) return;
      a.href = l[1];
      if (l[1] === './research.html') a.setAttribute('aria-current', 'page');
      nav.appendChild(a);
    });
    if (nav.firstChild) brand.appendChild(nav);
    return head;
  }

  function chips(published, currentId) {
    var box = el('div', 'fp-chips');
    published.forEach(function (f, i) {
      var a = el('a', ['fp-chip', 'mono'], two(i));
      a.href = './finding.html?id=' + encodeURIComponent(f.id);
      if (f.id === currentId) a.setAttribute('aria-current', 'page');
      box.appendChild(a);
    });
    return box;
  }

  function section(heading, note) {
    var s = el('section', 'fp-sec');
    var h = el('div', 'fp-sec-head');
    kid(h, heading ? word('h2', '', heading) : null);
    kid(h, note ? word('p', ['muted', 'fp-note'], note) : null);
    if (h.firstChild) s.appendChild(h);
    return s;
  }
  // Add a section only when something in it rendered.
  function keep(wrap, s) { if (s.querySelector('h2, p, a, div.fp-list, div.fp-cards')) wrap.appendChild(s); }

  function stat(labelKey, value) {
    if (value === null || value === undefined || value === '' || !T(labelKey)) return null;
    var d = el('div');
    d.appendChild(el('span', 'fp-k', T(labelKey)));
    d.appendChild(el('span', ['fp-v', 'mono'], String(value)));
    return d;
  }

  function evidenceSection(f) {
    var rows = f.evidence || [];
    if (!rows.length) return null;
    var pk = PRIMARY[f.id];
    if (!pk) {
      Object.keys(rows[0]).some(function (k) {
        if (!NON_FIELDS[k] && typeof rows[0][k] === 'number') { pk = k; return true; }
        return false;
      });
    }
    // A count of zero is drawn against what it could have been: the hours priced.
    if (f.id === 'sgd_php_never_cheapest') pk = 'hours_stablecoin_cheapest';
    var max = 0;
    rows.forEach(function (r) {
      var cap = f.id === 'sgd_php_never_cheapest' && typeof r.hours_priced === 'number' ? r.hours_priced : r[pk];
      if (typeof cap === 'number' && cap > max) max = cap;
    });
    var s = section('evidenceHeading', 'evidenceBasis_' + f.id);
    kid(s, T('field_' + pk) ? el('p', ['muted', 'fp-note'], T('field_' + pk)) : null);
    var list = kid(s, el('div', 'fp-list'));
    rows.forEach(function (r) {
      var leg = kid(list, el('div', 'fp-leg'));
      var lab = kid(leg, el('span', ['fp-lab', 'mono']));
      lab.appendChild(el('span', 'fp-labmain', (r.route ? niceRoute(r.route) : (r.ccy || '')) +
        (r.amount != null ? ' \u00b7 ' + fmt(r.amount) + (fromCcy(r.route) ? ' ' + fromCcy(r.route) : '') : '')));
      if (r.side) kid(lab, word('span', 'muted', 'side_' + r.side));
      var track = kid(leg, el('span', 'fp-track'));
      var bar = kid(track, document.createElement('i'));
      var pct = (max > 0 && typeof r[pk] === 'number') ? Math.max(r[pk] > 0 ? 2 : 0, r[pk] / max * 100) : 0;
      bar.style.width = pct.toFixed(1) + '%';
      if (r[pk] === 0) track.classList.add('zero');
      kid(leg, el('span', ['fp-num', 'mono'], typeof r[pk] === 'number' ? fmt(r[pk]) : ''));
      var extra = el('div', 'fp-extra');
      Object.keys(r).forEach(function (k) {
        if (NON_FIELDS[k] || k === pk || !T('field_' + k)) return;
        var sp = kid(extra, el('span'));
        sp.appendChild(el('span', 'mono', fmt(r[k])));
        sp.appendChild(el('span', 'muted', T('field_' + k)));
      });
      if (extra.firstChild) leg.appendChild(extra);
    });
    return s;
  }

  function methodSection(f) {
    var s = section('methodHeading');
    kid(s, word('p', 'fp-block', 'method_' + f.id));
    var files = f.method_files || [];
    if (files.length) {
      kid(s, word('p', ['muted', 'fp-note'], 'methodFilesLabel'));
      var list = kid(s, el('div', 'fp-list'));
      files.forEach(function (p) {
        var a = kid(list, el('a', 'fp-row'));
        a.href = GH + p;
        a.target = '_blank';
        a.rel = 'noopener';
        a.appendChild(el('span', ['fp-path', 'mono'], p));
      });
    }
    return s;
  }

  function limitsSection(f) {
    var s = section('limitsHeading');
    kid(s, word('p', 'fp-block', 'limits_' + f.id));
    return s;
  }

  function downloadSection(f) {
    var file = f.download_file;
    if (!file) return null;
    var s = section('downloadHeading', 'downloadNote');
    var list = kid(s, el('div', 'fp-list'));
    var a = kid(list, el('a', 'fp-row'));
    a.href = './' + file;
    a.setAttribute('download', '');
    a.appendChild(el('span', ['fp-path', 'mono'], file));
    if (f.hours_file === file && typeof f.hours_rows === 'number' && T('downloadRows')) {
      var r = kid(a, el('span', 'muted'));
      r.appendChild(el('span', 'mono', fmt(f.hours_rows)));
      r.appendChild(document.createTextNode(' '));
      r.appendChild(el('span', '', T('downloadRows')));
    }
    return s;
  }

  function card(f, i) {
    var a = el('a', 'fp-card');
    a.href = './finding.html?id=' + encodeURIComponent(f.id);
    a.appendChild(el('span', ['fp-no', 'mono'], two(i)));
    var body = kid(a, el('div', 'fp-card-body'));
    kid(body, titleOf(f) ? el('span', '', titleOf(f)) : null);
    var h = f.headline || {};
    if (typeof h.value === 'number') {
      body.appendChild(el('span', ['fp-card-val', 'mono'], fmt(h.value)));
      kid(body, word('span', ['soft', 'fp-note'], 'unit_' + h.unit));
    }
    if (f.first_published && T('firstPublished')) {
      kid(body, el('span', ['fp-card-meta', 'muted'], T('firstPublished').replace('{date}', dayY(f.first_published))));
    }
    if (statusText(f)) { kid(body, el('span', ['fp-card-meta', 'fp-status'], statusText(f))); }
    return a;
  }

  // One row per finding: its number, its title, the headline figure, and when it was last rechecked.
  function indexRow(f, i) {
    var a = el('a', 'f');
    a.href = './finding.html?id=' + encodeURIComponent(f.id);
    a.appendChild(el('span', 'id', f.n || two(i)));
    var txt = el('span', 'txt');
    txt.appendChild(el('h2', '', titleOf(f)));
    
    // Caption
    var cap = T('caption_' + f.id);
    if (cap) {
      txt.appendChild(el('p', 'cap', cap));
    }
    
    // Recheck time
    if (f.first_published && T('firstPublished')) {
      txt.appendChild(el('p', 'when', T('firstPublished').replace('{date}', dayY(f.first_published))));
    }
    if (statusText(f)) { txt.appendChild(el('p', ['when', 'fp-status'], statusText(f))); }
    
    a.appendChild(txt);
    
    // Big figure
    var h = f.headline || {};
    var bigValue = shownHeadline({ ...h, id: f.id }); // Pass ID for special handling
    var big = el('span', 'big', shortValue(f, bigValue));
    var unit = shortUnit(f);
    if (unit) { big.appendChild(el('small', '', unit)); }
    a.appendChild(big);
    
    return a;
  }

  function renderIndex(wrap, published) {
    wrap.appendChild(header());
    
    // Hero section
    var hero = el('div', 'hero');
    kid(hero, word('h1', '', 'indexHeading'));
    kid(hero, word('p', 'lead', 'indexLine'));
    if (hero.firstChild) wrap.appendChild(hero);
    
    // Findings list
    var list = el('div', ['list', 'num']);
    published.forEach(function (f, i) { 
      // Add finding number to the object for indexRow
      var findingWithNumber = { ...f, n: two(i) };
      list.appendChild(indexRow(findingWithNumber, i)); 
    });
    if (list.firstChild) wrap.appendChild(list);
    
    // Footer
    var footer = el('footer');
    var footerLink = word('a', '', 'footerGithub');
    if (footerLink) {
      footerLink.href = 'https://github.com/SebR214/margin';
      footer.appendChild(footerLink);
      wrap.appendChild(footer);
    }
  }

  function renderNotFound(wrap, published) {
    wrap.appendChild(header());
    wrap.appendChild(chips(published, null));
    var s = el('section', 'fp-sec');
    kid(s, word('p', ['soft', 'fp-line'], 'notFound'));
    var back = kid(s, word('a', 'fp-back', 'notFoundLink'));
    if (back) back.href = './research.html';
    if (s.firstChild) wrap.appendChild(s);
  }

  function renderFinding(wrap, published, f, size) {
    wrap.appendChild(header());
    wrap.appendChild(chips(published, f.id));

    var hero = el('section', ['fp-hero', 'hero', 'bleed']);
    var text = kid(hero, el('div', 'fp-hero-text'));
    kid(text, titleOf(f) ? el('h1', '', titleOf(f)) : null);
    kid(text, claimLine(f));
    if (!text.firstChild) hero.removeChild(text);
    var h = f.headline || {};
    if (typeof h.value === 'number') {
      var num = kid(hero, el('div', 'fp-hero-num'));
      var shown = shownHeadline(h);
      var big = kid(num, el('span', ['fp-big', 'mono'], shown));
      big.style.setProperty('--digits', String(shown.length));
      kid(num, word('span', ['soft', 'fp-unit'], 'unit_' + h.unit));
    }
    if (hero.firstChild) wrap.appendChild(hero);

    var stats = el('div', 'fp-stats');
    // What backs the number first, then when it was checked; the download's size and row count come last.
    if (f.first_published && T('firstPublished')) { kid(stats, el('p', ['fp-first', 'muted'], T('firstPublished').replace('{date}', dayY(f.first_published)))); }
    if (statusText(f)) { kid(stats, el('p', ['fp-first', 'fp-status'], statusText(f))); }
    kid(stats, stat('statEvidence', (f.evidence || []).length ? fmt(f.evidence.length) : ''));
    kid(stats, stat('statRows', typeof f.hours_rows === 'number' ? fmt(f.hours_rows) : ''));
    kid(stats, stat('statSize', size === null ? '' : fmtBytes(size)));
    if (stats.firstChild) wrap.appendChild(stats);

    var ev = evidenceSection(f);
    if (ev) keep(wrap, ev);
    keep(wrap, methodSection(f));
    keep(wrap, limitsSection(f));
    var dl = downloadSection(f);
    if (dl) keep(wrap, dl);

    var others = published.map(function (g, i) { return [g, i]; }).filter(function (p) { return p[0].id !== f.id; });
    if (others.length) {
      var rel = section('relatedHeading');
      var cards = kid(rel, el('div', 'fp-cards'));
      others.forEach(function (p) { cards.appendChild(card(p[0], p[1])); });
      keep(wrap, rel);
    }
    var t = titleOf(f);
    if (t && window.PageHead) { window.PageHead.copy().then(function (S) { window.PageHead.set({ title: t + ': margin.wiki', description: window.PageHead.fill(S.findingDescription, { title: t }), path: 'finding.html?id=' + encodeURIComponent(f.id), twin: 'finding/' + encodeURIComponent(f.id) + '.md' }); }); }
  }

  function load(url) {
    return fetch(url).then(function (r) { if (!r.ok) throw new Error(url); return r; });
  }

  Promise.all([
    load('./copy.json').then(function (r) { return r.json(); }).catch(function () { return {}; }),
    load('./data/findings.json').then(function (r) { return r.json(); }).catch(function () { return { findings: [] }; }),
    load('./data/claims_status.json').then(function (r) { return r.json(); }).catch(function () { return null; }),
    load('./data/findings_first_published.json').then(function (r) { return r.json(); }).catch(function () { return {}; }),
    load('./data/finding_status.json').then(function (r) { return r.json(); }).catch(function () { return null; })
  ]).then(function (res) {
    (res[1].findings || []).forEach(function (f) { f.first_published = res[3][f.id] || ''; f.retest = (res[4] && res[4].findings && res[4].findings[f.id]) || null; });
    C = res[0].findingData || {};
    CLAIMS = res[2];
    BRAND = typeof res[0].brand === 'string' ? res[0].brand : '';
    var published = (res[1].findings || []).filter(function (f) { return f.published === true; });
    var wrap = document.createElement('div');
    wrap.className = 'wrap';
    if (mode === 'index') {
      renderIndex(wrap, published);
      app.appendChild(wrap);
      return;
    }
    var id = new URLSearchParams(location.search).get('id');
    var f = published.filter(function (g) { return g.id === id; })[0];
    if (!f) { renderNotFound(wrap, published); app.appendChild(wrap); return; }
    renderFinding(wrap, published, f);
    app.appendChild(wrap);
  });
})();

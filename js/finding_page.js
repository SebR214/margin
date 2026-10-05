/* Finding page (finding.html?id=<id>) and the findings index (findings.html).
   Every number, date, id and file path comes from data/findings.json; every
   word comes from copy.json -> findingData, and an element whose key is empty
   is not rendered. Hand-written DOM, no library. */
(function () {
  var GH = 'https://github.com/SebR214/margin/blob/main/';
  var NON_FIELDS = { route: 1, ccy: 1, side: 1 };
  var PRIMARY = { price_changes: 'changes', weekend_penalty: 'weekend_up', volume_crossover: 'monthly_volume_sgd' };
  var app = document.getElementById('app');
  var mode = document.body.getAttribute('data-page');
  var C = {};
  var BRAND = '';

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null && text !== '') n.textContent = text;
    return n;
  }
  function kid(parent, child) { if (child) parent.appendChild(child); return child; }
  function T(key) { var v = C[key]; return typeof v === 'string' ? v : ''; }
  // A node holding a copy key's text, or null when the key is empty.
  function word(tag, cls, key) { var t = T(key); return t ? el(tag, cls, t) : null; }

  function fmt(v) {
    if (typeof v !== 'number') return String(v);
    return v.toLocaleString('en-US', { maximumFractionDigits: 2 });
  }
  function fmtTime(s) {
    var m = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/.exec(s || '');
    return m ? m[1] + ' ' + m[2] + ' UTC' : (s || '');
  }
  function fmtBytes(n) { return n < 1000 ? n + ' B' : (n / 1000).toFixed(1) + ' kB'; }
  function two(i) { return (i < 9 ? '0' : '') + (i + 1); }

  function header() {
    var head = el('header', 'fp-head');
    var brand = kid(head, el('div', 'fp-brand'));
    var logo = kid(brand, el('a', 'fp-logo mono', BRAND));
    logo.href = './index.html';
    var links = [['navCountries', './countries.html'], ['navRoutes', './sending-money.html'], ['navSources', './sources.html'],
                 ['navFindings', './findings.html'], ['navHowItWorks', './how-it-works.html']];
    var nav = el('nav', 'fp-nav');
    links.forEach(function (l) {
      var a = word('a', '', l[0]);
      if (!a) return;
      a.href = l[1];
      if (l[1] === './findings.html') a.setAttribute('aria-current', 'page');
      nav.appendChild(a);
    });
    if (nav.firstChild) brand.appendChild(nav);
    return head;
  }

  function chips(published, currentId) {
    var box = el('div', 'fp-chips');
    published.forEach(function (f, i) {
      var a = el('a', 'fp-chip mono', two(i));
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
    kid(h, note ? word('p', 'muted fp-note', note) : null);
    if (h.firstChild) s.appendChild(h);
    return s;
  }
  // Add a section only when something in it rendered.
  function keep(wrap, s) { if (s.querySelector('h2, p, a, div.fp-list, div.fp-cards')) wrap.appendChild(s); }

  function stat(labelKey, value) {
    if (value === null || value === undefined || value === '' || !T(labelKey)) return null;
    var d = el('div');
    d.appendChild(el('span', 'fp-k', T(labelKey)));
    d.appendChild(el('span', 'fp-v mono', String(value)));
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
    var max = 0;
    rows.forEach(function (r) { if (typeof r[pk] === 'number' && r[pk] > max) max = r[pk]; });
    var s = section('evidenceHeading', 'evidenceBasis_' + f.id);
    kid(s, T('field_' + pk) ? el('p', 'muted fp-note', T('field_' + pk)) : null);
    var list = kid(s, el('div', 'fp-list'));
    rows.forEach(function (r) {
      var leg = kid(list, el('div', 'fp-leg'));
      var lab = kid(leg, el('span', 'fp-lab mono', r.route || r.ccy || ''));
      if (r.side) kid(lab, word('span', 'muted', 'side_' + r.side));
      var track = kid(leg, el('span', 'fp-track'));
      var bar = kid(track, document.createElement('i'));
      var pct = (max > 0 && typeof r[pk] === 'number') ? Math.max(r[pk] > 0 ? 2 : 0, r[pk] / max * 100) : 0;
      bar.style.width = pct.toFixed(1) + '%';
      kid(leg, el('span', 'fp-num mono', typeof r[pk] === 'number' ? fmt(r[pk]) : ''));
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
      kid(s, word('p', 'muted fp-note', 'methodFilesLabel'));
      var list = kid(s, el('div', 'fp-list'));
      files.forEach(function (p) {
        var a = kid(list, el('a', 'fp-row'));
        a.href = GH + p;
        a.target = '_blank';
        a.rel = 'noopener';
        a.appendChild(el('span', 'fp-path mono', p));
      });
    }
    return s;
  }

  function limitsSection(f) {
    var s = section('limitsHeading');
    kid(s, word('p', 'fp-block', 'limits_' + f.id));
    return s;
  }

  function downloadSection(f, size) {
    var file = f.download_file;
    if (!file) return null;
    var s = section('downloadHeading', 'downloadNote');
    var list = kid(s, el('div', 'fp-list'));
    var a = kid(list, el('a', 'fp-row'));
    a.href = './' + file;
    a.setAttribute('download', '');
    a.appendChild(el('span', 'fp-path mono', file));
    if (f.hours_file === file && typeof f.hours_rows === 'number' && T('downloadRows')) {
      var r = kid(a, el('span', 'muted'));
      r.appendChild(el('span', 'mono', fmt(f.hours_rows)));
      r.appendChild(document.createTextNode(' '));
      r.appendChild(el('span', '', T('downloadRows')));
    }
    if (size !== null && T('downloadSize')) {
      var z = kid(a, el('span', 'muted'));
      z.appendChild(el('span', 'mono', fmtBytes(size)));
      z.appendChild(document.createTextNode(' '));
      z.appendChild(el('span', '', T('downloadSize')));
    }
    return s;
  }

  function card(f, i) {
    var a = el('a', 'fp-card');
    a.href = './finding.html?id=' + encodeURIComponent(f.id);
    a.appendChild(el('span', 'fp-no mono', two(i)));
    var body = kid(a, el('div', 'fp-card-body'));
    kid(body, word('span', '', 'title_' + f.id));
    var h = f.headline || {};
    if (typeof h.value === 'number') {
      body.appendChild(el('span', 'fp-card-val mono', fmt(h.value)));
      kid(body, word('span', 'soft fp-note', 'unit_' + h.unit));
    }
    if (f.last_recheck_utc && T('lastRecheck')) {
      var m = kid(body, el('span', 'fp-card-meta muted'));
      m.appendChild(el('span', '', T('lastRecheck')));
      m.appendChild(el('span', 'mono', fmtTime(f.last_recheck_utc)));
    }
    return a;
  }

  function renderIndex(wrap, published) {
    wrap.appendChild(header());
    var top = el('section', 'fp-sec');
    kid(top, word('h1', '', 'indexHeading'));
    kid(top, word('p', 'soft fp-line', 'indexLine'));
    if (top.firstChild) wrap.appendChild(top);
    var cards = el('div', 'fp-cards');
    published.forEach(function (f, i) { cards.appendChild(card(f, i)); });
    if (cards.firstChild) wrap.appendChild(cards);
    if (T('indexTitle')) document.title = 'margin.wiki — ' + T('indexTitle');
  }

  function renderNotFound(wrap, published) {
    wrap.appendChild(header());
    wrap.appendChild(chips(published, null));
    var s = el('section', 'fp-sec');
    kid(s, word('p', 'soft fp-line', 'notFound'));
    var back = kid(s, word('a', 'fp-back', 'notFoundLink'));
    if (back) back.href = './findings.html';
    if (s.firstChild) wrap.appendChild(s);
  }

  function renderFinding(wrap, published, f, size) {
    wrap.appendChild(header());
    wrap.appendChild(chips(published, f.id));

    var hero = el('section', 'fp-hero');
    var text = kid(hero, el('div', 'fp-hero-text'));
    kid(text, word('h1', '', 'title_' + f.id));
    kid(text, word('p', 'soft fp-line', 'claim_' + f.id));
    if (!text.firstChild) hero.removeChild(text);
    var h = f.headline || {};
    if (typeof h.value === 'number') {
      var num = kid(hero, el('div', 'fp-hero-num'));
      var shown = fmt(h.value);
      var big = kid(num, el('span', 'fp-big mono', shown));
      big.style.setProperty('--digits', String(shown.length));
      kid(num, word('span', 'soft fp-unit', 'unit_' + h.unit));
    }
    if (hero.firstChild) wrap.appendChild(hero);

    var stats = el('div', 'fp-stats');
    kid(stats, stat('lastRecheck', fmtTime(f.last_recheck_utc)));
    kid(stats, stat('statRows', typeof f.hours_rows === 'number' ? fmt(f.hours_rows) : ''));
    kid(stats, stat('statSize', size === null ? '' : fmtBytes(size)));
    kid(stats, stat('statEvidence', (f.evidence || []).length ? fmt(f.evidence.length) : ''));
    if (stats.firstChild) wrap.appendChild(stats);

    var ev = evidenceSection(f);
    if (ev) keep(wrap, ev);
    keep(wrap, methodSection(f));
    keep(wrap, limitsSection(f));
    var dl = downloadSection(f, size);
    if (dl) keep(wrap, dl);

    var others = published.map(function (g, i) { return [g, i]; }).filter(function (p) { return p[0].id !== f.id; });
    if (others.length) {
      var rel = section('relatedHeading');
      var cards = kid(rel, el('div', 'fp-cards'));
      others.forEach(function (p) { cards.appendChild(card(p[0], p[1])); });
      keep(wrap, rel);
    }
    var t = T('title_' + f.id);
    if (t) document.title = 'margin.wiki — ' + t;
  }

  function load(url) {
    return fetch(url).then(function (r) { if (!r.ok) throw new Error(url); return r; });
  }

  Promise.all([
    load('./copy.json').then(function (r) { return r.json(); }).catch(function () { return {}; }),
    load('./data/findings.json').then(function (r) { return r.json(); }).catch(function () { return { findings: [] }; })
  ]).then(function (res) {
    C = res[0].findingData || {};
    BRAND = typeof res[0].brand === 'string' ? res[0].brand : '';
    var published = (res[1].findings || []).filter(function (f) { return f.published === true; });
    var wrap = document.createElement('div');
    wrap.className = 'fp-wrap';
    if (mode === 'index') {
      renderIndex(wrap, published);
      app.appendChild(wrap);
      return;
    }
    var id = new URLSearchParams(location.search).get('id');
    var f = published.filter(function (g) { return g.id === id; })[0];
    if (!f) { renderNotFound(wrap, published); app.appendChild(wrap); return; }
    var sizeP = f.download_file
      ? load('./' + f.download_file).then(function (r) { return r.blob(); }).then(function (b) { return b.size; }).catch(function () { return null; })
      : Promise.resolve(null);
    sizeP.then(function (size) { renderFinding(wrap, published, f, size); app.appendChild(wrap); });
  });
})();

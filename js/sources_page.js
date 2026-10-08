/* The Sources page. Reads data/sources_daily.json (every source, a status per day, history),
   data/record_daily.json (totals) and data/record_milestones.json (first date each source
   appears), and builds the DOM by hand. No library, no network call beyond the stored files.
   Every word comes from copy.json -> sourcesData. An element whose key is empty is not
   rendered. Numbers, dates, source ids, currency codes, route ids, timestamps and the stored
   history_reason text are data and are shown as stored. Ages are measured against the data's
   own as_of_utc, never the browser clock. */
(function () {

  var COPY = {};
  var DATA = null, RECORD = null, FIRST_DAY = {};
  var state = { kind: 'all' };

  var KIND_KEYS = [
    ['p2p', 'kindP2p'], ['order_book', 'kindOrderBook'], ['broker', 'kindBroker'],
    ['fx', 'kindFx'], ['provider_quote', 'kindProviderQuote'], ['other', 'kindOther']
  ];
  var KIND_KEY = {};
  KIND_KEYS.forEach(function (k) { KIND_KEY[k[0]] = k[1]; });
  var STATUS = [
    ['answered_every_hour', 'statusAnsweredEveryHour', 's-ans'],
    ['missed_some', 'statusMissedSome', 's-some'],
    ['missed_all', 'statusMissedAll', 's-all'],
    ['not_yet_a_source', 'statusNotYetASource', 's-not']
  ];
  var STATUS_BY = {};
  STATUS.forEach(function (s) { STATUS_BY[s[0]] = s; });

  function $(id) { return document.getElementById(id); }

  function tpl(key, vars) {
    var s = COPY[key];
    if (!s) return '';
    return s.replace(/\{(\w+)\}/g, function (m, k) {
      return vars && vars[k] != null ? String(vars[k]) : '';
    });
  }

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = Array.isArray(cls) ? cls.join(String.fromCharCode(32)) : cls;
    if (text != null && text !== '') n.textContent = text;
    return n;
  }

  /* An element that carries words: null when its key is empty. */
  function word(tag, cls, key, vars) {
    var t = tpl(key, vars);
    return t ? el(tag, cls, t) : null;
  }

  /* A template whose stored-text placeholders (names in `raw`) go into a code element, so the
     text is shown exactly as stored. */
  function rich(tag, cls, key, vars, raw) {
    var t = COPY[key];
    if (!t) return null;
    var n = el(tag, cls);
    t.split(/(\{\w+\})/).forEach(function (part) {
      var m = /^\{(\w+)\}$/.exec(part);
      if (!m) { if (part) n.appendChild(document.createTextNode(part)); return; }
      var v = vars[m[1]];
      if (v == null || v === '') return;
      if (raw.indexOf(m[1]) >= 0) n.appendChild(el('code', '', String(v)));
      else n.appendChild(document.createTextNode(String(v)));
    });
    return n;
  }

  function add(parent, child) { if (child) parent.appendChild(child); return child; }

  function groupDigits(n) { return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ','); }
  function day(s) { return s ? String(s).slice(0, 10) : ''; }
  function clock(s) { return s ? String(s).slice(11, 19) : ''; }

  // "2026-10-08T06:10:31Z" -> "8 Oct, 06:10 UTC": no ISO timestamps in reader text.
  var MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  function friendly(iso) {
    var m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}:\d{2})/.exec(iso || '');
    return m ? (+m[3]) + ' ' + MON[+m[2] - 1] + ', ' + m[4] + ' UTC' : String(iso || '');
  }

  function friendlyDay(d) {
    var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(d || '');
    return m ? (+m[3]) + ' ' + MON[+m[2] - 1] : String(d || '');
  }

  function ageText(lastUtc) {
    var asOf = Date.parse(DATA.as_of_utc), last = Date.parse(lastUtc);
    if (isNaN(asOf) || isNaN(last)) return '';
    var mins = Math.max(0, Math.floor((asOf - last) / 60000));
    if (mins < 60) return tpl(mins === 1 ? 'ageMinuteOne' : 'ageMinutes', { n: mins });
    var hrs = Math.floor(mins / 60);
    if (hrs < 48) return tpl(hrs === 1 ? 'ageHourOne' : 'ageHours', { n: hrs });
    var days = Math.floor(hrs / 24);
    return tpl(days === 1 ? 'ageDayOne' : 'ageDays', { n: days });
  }

  /* ---------------------------------------------------------------- header, hero, stats */
  function buildHeader() {
    var logo = $('logo');
    var t = tpl('logo');
    if (t) { logo.textContent = t; logo.hidden = false; }
    var nav = $('nav');
    [['navCountries', './countries.html'], ['navRoutes', './sending-money.html'],
     ['navSources', './sources.html'], ['navFindings', './findings.html'],
     ['navHowItWorks', './how-it-works.html']].forEach(function (n) {
      var txt = tpl(n[0]);
      if (!txt) return;
      var a = el('a', '', txt);
      a.href = n[1];
      if (n[0] === 'navSources') a.setAttribute('aria-current', 'page');
      nav.appendChild(a);
    });
    var asof = tpl('headerAsOf', { time: friendly(DATA.as_of_utc), day: day(DATA.as_of_utc), clock: clock(DATA.as_of_utc) });
    if (asof) { var h = $('asof'); h.textContent = asof; h.hidden = false; }
    var title = tpl('pageTitle');
    if (title) document.title = title;
  }

  function buildHero(total, live, gone, withHist, noHist) {
    var h1 = tpl('headline');
    if (h1) { var h = $('headline'); h.textContent = h1; h.hidden = false; }
    var lede = tpl('headlineSub');
    if (lede) { var p = $('lede'); p.textContent = lede; p.hidden = false; }
    $('big').textContent = String(total);
    var bl = tpl('bigLabel', { n: total });
    if (bl) { var b = $('bigl'); b.textContent = bl; b.hidden = false; }

    var stats = $('stats');
    [['statLive', live], ['statHistoryOnly', gone], ['statWithHistory', withHist], ['statNoHistory', noHist]].forEach(function (s) {
      var cell = el('div', 's-stat');
      cell.appendChild(el('span', ['num', 'mono'], String(s[1])));
      add(cell, word('span', ['lab', 'muted'], s[0], { n: s[1] }));
      stats.appendChild(cell);
    });
  }

  /* ---------------------------------------------------------------- chips, legend */
  function buildChips(sources) {
    var box = $('chips');
    box.textContent = '';
    var label = tpl('filterLabel');
    if (label) box.setAttribute('aria-label', label);
    var present = {};
    sources.forEach(function (s) { present[s.kind] = true; });
    var items = [['all', 'kindAll']].concat(KIND_KEYS.filter(function (k) { return present[k[0]]; }));
    items.forEach(function (it) {
      var txt = tpl(it[1]);
      if (!txt) return;
      var b = el('button', 's-chip' + (state.kind === it[0] ? ' on' : ''), txt);
      b.type = 'button';
      b.setAttribute('aria-pressed', state.kind === it[0] ? 'true' : 'false');
      b.addEventListener('click', function () { state.kind = it[0]; buildChips(sources); buildLists(); });
      box.appendChild(b);
    });
  }

  function buildLegend() {
    var box = $('legend');
    add(box, word('span', ['head', 'muted'], 'legendHeading'));
    STATUS.forEach(function (s) {
      var txt = tpl(s[1]);
      if (!txt) return;
      var k = el('span', 's-key');
      k.appendChild(el('i', 'sw ' + s[2]));
      k.appendChild(el('span', '', txt));
      box.appendChild(k);
    });
  }

  /* ---------------------------------------------------------------- one row */
  function strip(s) {
    var wrap = el('div', 's-stripcol');
    var grid = el('div', 's-strip');
    grid.style.setProperty('--days', String(s.status.length));
    s.status.forEach(function (st, i) {
      var def = STATUS_BY[st] || STATUS_BY.not_yet_a_source;
      var sq = el('span', def[2]);
      var tip = tpl('stripDay', { day: DATA.days[i], status: tpl(def[1]) });
      if (tip) { sq.title = tip; sq.setAttribute('aria-label', tip); }
      grid.appendChild(sq);
    });
    wrap.appendChild(grid);
    return wrap;
  }

  function history(s) {
    var col = el('div', 's-histcol');
    if (s.history && s.history.length) {
      add(col, word('span', ['muted', 's-small'], 'historyHeading'));
      s.history.forEach(function (h) {
        add(col, word('span', ['mono', 'soft', 's-small'], h.ccy ? 'historyLine' : 'historyLineNoCcy', {
          series: seriesName(h.series), ccy: h.ccy || '', interval: h.interval,
          first: friendlyDay(day(h.first)), last: friendlyDay(day(h.last)), rows: groupDigits(h.rows)
        }));
      });
    }
    // Why there is no older history, in plain words by kind (tools/emit_sources_daily.py reason_kind).
    // The stored reason text, endpoint and HTTP code stay in the data file and are not shown.
    if (s.history_reason_kind) add(col, word('span', ['soft', 's-small'], 'reason_' + s.history_reason_kind));
    return col;
  }

  // A stored source id made readable: the names live in copy.json (sourceNames); CriptoYa sub-venues
  // read "CriptoYa · name". Anything else shows as stored.
  function displayName(id) {
    var m = (COPY.sourceNames || {})[id];
    if (m) return m;
    return String(id).replace(/^CriptoYa:/, 'CriptoYa · ');
  }

  // A stored series id made readable: names in copy.json (seriesNames), else the venue name without the
  // interval suffix (_1d, _1h), because the interval is printed on its own.
  function seriesName(id) {
    var m = (COPY.seriesNames || {})[id];
    return m || String(id).replace(/_(1d|1h)$/, '');
  }

  function coverage(s) {
    // How many currencies and routes the source covers, as plain counts: no internal codes.
    var box = el('div', 's-cur');
    [['coverageCurrencies', s.currencies || []], ['coverageRoutes', s.routes || []]].forEach(function (g) {
      if (!g[1].length) return;
      add(box, word('span', ['soft', 's-small'], g[1].length === 1 ? g[0] + 'One' : g[0], { n: g[1].length }));
    });
    return box.childNodes.length ? box : null;
  }

  function row(s) {
    var r = el('div', 's-row');
    r.id = 's-' + String(s.id).toLowerCase().replace(/[^a-z0-9]/g, '');
    var info = el('div', 's-info');
    info.appendChild(el('span', ['s-id', 'mono'], displayName(s.id)));
    if (s.feeds) add(info, word('span', ['mono', 'muted', 's-small'], 'feedsCount', { n: s.feeds }));
    add(info, word('span', ['s-kind', 'mono', 'soft'], KIND_KEY[s.kind] || 'kindOther'));
    if (s.last_answered_utc) {
      add(info, word('span', ['mono', 'soft', 's-small'], 'lastAnswered', {
        time: friendly(s.last_answered_utc), day: day(s.last_answered_utc), clock: clock(s.last_answered_utc)
      }));
      if (Date.parse(DATA.as_of_utc) - Date.parse(s.last_answered_utc) >= 3600000) add(info, el('span', ['mono', 'muted', 's-small'], ageText(s.last_answered_utc)));
    } else {
      add(info, word('span', ['muted', 's-small'], 'neverAnswered'));
    }
    var first = s.first_utc ? day(s.first_utc) : FIRST_DAY[s.id];
    if (first) add(info, word('span', ['mono', 'muted', 's-small'], 'firstSeen', { date: friendlyDay(first) }));
    if (s.live) add(info, word('span', ['mono', 'muted', 's-small'], 'hoursAnswered', { answered: groupDigits(s.hours_answered), expected: groupDigits(s.hours_expected) }));
    r.appendChild(info);
    r.appendChild(strip(s));
    r.appendChild(history(s));
    add(r, coverage(s));
    return r;
  }

  /* ---------------------------------------------------------------- lists */
  function buildLists() {
    var all = DATA.sources.filter(function (s) { return state.kind === 'all' || s.kind === state.kind; });
    var live = all.filter(function (s) { return s.live; }).sort(function (a, b) {
      if (a.last_answered_utc !== b.last_answered_utc) return a.last_answered_utc < b.last_answered_utc ? 1 : -1;
      return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
    });
    var gone = all.filter(function (s) { return !s.live; }).sort(function (a, b) {
      return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
    });
    live = collapseFeeds(live);
    fill('liveSec', 'liveHead', 'liveList', 'liveHeading', live);
    axis();
    fill('histSec', 'histHead', 'histList', 'historyOnlyHeading', gone);
    var c = $('count');
    var ct = tpl('shown', { n: all.length, total: DATA.sources.length });
    c.hidden = !ct;
    c.textContent = ct;
  }

  // CriptoYa feeds that report identical status are one row ("CriptoYa", n feeds), not a wall of copies.
  function collapseFeeds(rows) {
    var groups = {}, out = [];
    rows.forEach(function (s) {
      if (!/^CriptoYa:/.test(String(s.id))) { out.push(s); return; }
      var key = s.status.join('') + '|' + s.hours_answered + '|' + s.hours_expected;
      (groups[key] = groups[key] || []).push(s);
    });
    Object.keys(groups).forEach(function (k) {
      var g = groups[k];
      if (g.length === 1) { out.push(g[0]); return; }
      var m = {}; Object.keys(g[0]).forEach(function (f) { m[f] = g[0][f]; });
      m.id = 'CriptoYa'; m.feeds = g.length; m.history = []; m.history_reason_kind = null;
      m.last_answered_utc = g.map(function (x) { return x.last_answered_utc; }).sort().pop();
      var cur = {}, rt = {};
      g.forEach(function (x) { (x.currencies || []).forEach(function (c) { cur[c] = 1; }); (x.routes || []).forEach(function (c) { rt[c] = 1; }); });
      m.currencies = Object.keys(cur); m.routes = Object.keys(rt);
      out.push(m);
    });
    return out.sort(function (a, b) {
      if (a.last_answered_utc !== b.last_answered_utc) return a.last_answered_utc < b.last_answered_utc ? 1 : -1;
      return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
    });
  }

  // The date axis, once, above the list: first day on the left, last on the right.
  function axis() {
    var old = $('axis'); if (old) old.remove();
    var list = $('liveList'); if (!list || !DATA) return;
    var ax = el('div', ['s-axis', 'mono', 'muted']);
    ax.id = 'axis';
    var cap = tpl('stripCaption', { first: friendlyDay(DATA.first_day), last: friendlyDay(DATA.last_day), days: DATA.days.length });
    if (cap) ax.appendChild(el('span', '', cap));
    list.parentNode.insertBefore(ax, list);
  }

  function fill(secId, headId, listId, headKey, rows) {
    var sec = $(secId), head = $(headId), list = $(listId);
    list.textContent = '';
    sec.hidden = rows.length === 0;
    var t = tpl(headKey, { n: rows.reduce(function (a, r) { return a + (r.feeds || 1); }, 0) });
    head.hidden = !t;
    head.textContent = t;
    rows.forEach(function (s) { list.appendChild(row(s)); });
  }

  /* ---------------------------------------------------------------- start */
  function getJSON(url) {
    return fetch(url, { cache: 'no-store' }).then(function (r) {
      if (!r.ok) throw new Error(String(r.status));
      return r.json();
    });
  }

  // A link such as sources.html#s-bithumb opens the page at that source's row.
  function jumpToHash() {
    var h = (location.hash || '').replace(/^#/, '');
    if (!h) return;
    var target = document.getElementById(h);
    if (!target) {
      var rows = document.querySelectorAll('.s-row[id]');
      for (var i = 0; i < rows.length; i++) { if (rows[i].id.indexOf(h) === 0) { target = rows[i]; break; } }
    }
    if (target) { target.classList.add('s-target'); target.scrollIntoView(); }
  }

  function start(copy, sources, record, milestones) {
    COPY = (copy && copy.sourcesData) || {};
    if (!sources || !sources.sources) {
      var f = $('fail');
      var msg = tpl('loadFailed');
      f.textContent = msg;
      f.hidden = !msg;
      return;
    }
    DATA = sources;
    RECORD = record;
    ((milestones && milestones.milestones) || []).forEach(function (m) {
      if (m.kind === 'source') FIRST_DAY[m.id] = m.first_day;
    });
    var liveCount = DATA.sources.filter(function (s) { return s.live; }).length;
    var total = DATA.sources.length;
    var withHist = DATA.sources.filter(function (s) { return s.history && s.history.length; }).length;
    var noHist = DATA.sources.length - withHist;
    buildHeader();
    buildHero(total, liveCount, total - liveCount, withHist, noHist);
    buildLegend();
    buildChips(DATA.sources);
    buildLists();
    jumpToHash();
  }

  Promise.all([
    getJSON('./copy.json').catch(function () { return {}; }),
    getJSON('./data/sources_daily.json').catch(function () { return null; }),
    getJSON('./data/record_daily.json').catch(function () { return null; }),
    getJSON('./data/record_milestones.json').catch(function () { return null; })
  ]).then(function (r) { start(r[0], r[1], r[2], r[3]); });
})();

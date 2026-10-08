/* Sources page (SEB-266), built to the reference. Reads data/sources_daily.json and copy.json (sourcesData).
   The header status is js/site_head.js's. Every word is a copy.json key; numbers, dates and names are formatted here.
   A source is a row; CriptoYa's live feeds are one row. Clicking a strip picks a day across every row. */
(function () {
  var C = {}, D = null;
  var MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  var CODE = { answered_every_hour: 'a', missed_some: 's', missed_all: 'x', not_yet_a_source: 'n' };
  var STAT = { a: 'statusAnsweredEveryHour', s: 'statusMissedSome', x: 'statusMissedAll', n: 'statusNotYetASource' };
  var RANK = { n: 0, a: 1, s: 2, x: 3 };
  var KIND = { p2p: 'kindP2p', order_book: 'kindOrderBook', broker: 'kindBroker', fx: 'kindFx', provider_quote: 'kindProviderQuote', other: 'kindOther' };
  var KORDER = ['order_book', 'broker', 'fx', 'provider_quote', 'p2p', 'other'];
  var NAV = [['navCountries', 'countries.html'], ['navRoutes', 'sending-money.html'], ['navSources', 'sources.html'], ['navFindings', 'findings.html'], ['navHowItWorks', 'how-it-works.html']];

  var live = [], hist = [], days = [], kind = 'all', sel = null, collectorDays = [], gapText = '';

  function $(id) { return document.getElementById(id); }
  function T(k, v) { var s = C[k]; return typeof s === 'string' && s ? s.replace(/\{(\w+)\}/g, function (m, x) { return v && v[x] != null ? v[x] : ''; }) : ''; }
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function g(n) { return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ','); }
  function dd(s) { var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s || ''); return m ? (+m[3]) + ' ' + MON[+m[2] - 1] : ''; }
  function ddY(s) { var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s || ''); return m ? (+m[3]) + ' ' + MON[+m[2] - 1] + ' ' + m[1] : ''; }
  function clockT(s) { return s ? dd(s) + ', ' + s.slice(11, 16) + ' UTC' : ''; }
  function name(id) { var m = (C.sourceNames || {})[id]; return m || String(id).replace(/^CriptoYa:/, 'CriptoYa · '); }
  function seriesName(id) { var m = (C.seriesNames || {})[id]; return m || String(id).replace(/_(1d|1h)$/, ''); }
  function every(iv) { return iv === '1d' ? 'day' : iv === '1h' ? 'hour' : iv; }
  function slug(id) { return 's-' + String(id).toLowerCase().replace(/[^a-z0-9]/g, ''); }
  function share(s) { return s.he ? s.ha / s.he : 1; }
  function isCY(s) { return /^CriptoYa/.test(s.id); }
  // "1,175 of 1,176 hours priced" -> the figure up front, the rest on a second line
  function split(s) { var m = /^(.*?)(\s+\S+\s+\S+)$/.exec(s); return m ? [m[1], m[2].trim()] : [s, '']; }
  function getJSON(u) { return fetch(u, { cache: 'no-store' }).then(function (r) { if (!r.ok) { throw new Error(r.status); } return r.json(); }); }

  function model(raw) {
    days = raw.days || [];
    var all = (raw.sources || []).map(function (s) {
      return {
        id: s.id, k: s.kind, live: !!s.live, cur: (s.currencies || []).length, rt: (s.routes || []).length,
        first: s.first_utc || '', last: s.last_answered_utc || '', ha: s.hours_answered || 0, he: s.hours_expected || 0,
        st: (s.status || []).map(function (x) { return CODE[x] || 'n'; }).join(''),
        h: s.history || [], why: s.history_reason_kind || null
      };
    });
    var cy = all.filter(function (s) { return s.live && isCY(s); });
    var group = cy.length > 1 ? {
      id: 'CriptoYa', k: 'broker', live: true, feeds: cy,
      ha: cy.reduce(function (a, s) { return a + s.ha; }, 0), he: cy.reduce(function (a, s) { return a + s.he; }, 0),
      cur: 0, rt: 0, first: cy.map(function (s) { return s.first; }).filter(Boolean).sort()[0] || '',
      last: cy.map(function (s) { return s.last; }).sort().pop(),
      st: days.map(function (_, i) { return cy.map(function (s) { return s.st[i]; }).reduce(function (w, c) { return RANK[c] > RANK[w] ? c : w; }, 'n'); }).join(''),
      h: [], why: 'snapshot_only'
    } : null;
    live = all.filter(function (s) { return s.live && !(group && isCY(s)); }).concat(group ? [group] : []);
    hist = all.filter(function (s) { return !s.live; });
    live.sort(function (a, b) { return share(a) - share(b) || name(a.id).localeCompare(name(b.id)); });
    // a day on which every source live that day missed hours: that was the collector, not the sources
    collectorDays = days.filter(function (_, i) {
      var on = all.filter(function (s) { return s.live && s.st[i] !== 'n'; });
      return on.length > 5 && on.every(function (s) { return s.st[i] === 's' || s.st[i] === 'x'; });
    });
    gapText = collectorDays.length ? T('collectorGap', { days: collectorDays.map(dd).join(' and ') }) : '';
    return all;
  }

  function header() {
    var nav = $('nav');
    NAV.forEach(function (n) {
      var t = T(n[0]); if (!t) { return; }
      var a = document.createElement('a'); a.textContent = t; a.href = './' + n[1];
      if (n[1] === 'sources.html') { a.setAttribute('aria-current', 'page'); }
      nav.appendChild(a);
    });
    if (T('pageTitle')) { document.title = T('pageTitle'); }
    var h1 = $('h1'), lead = $('lead');
    if (T('headline')) { h1.textContent = T('headline'); h1.hidden = false; }
    if (T('headlineSub')) { lead.textContent = T('headlineSub'); lead.hidden = false; }
  }

  function counts(all) {
    var total = all.length, nLive = all.filter(function (s) { return s.live; }).length, withH = all.filter(function (s) { return s.h.length; }).length;
    var b = function (n) { return '<b>' + n + '</b> '; };
    $('counts').innerHTML = b(total) + esc(T('bigLabel')) + '. ' + b(nLive) + esc(T('statLive')) + '. ' + b(total - nLive) + esc(T('statHistoryOnly')) + '.<br>' +
      b(withH) + esc(T('statWithHistory')) + ', ' + b(total - withH) + esc(T('statNoHistory')) + '.';
    $('key').innerHTML = '<span>' + esc(T('legendHeading')) + '</span>' +
      ['a', 's', 'x', 'n'].map(function (k) { return '<span><i class="s-' + k + '"></i>' + esc(T(STAT[k])) + '</span>'; }).join('');
    $('gapnote').textContent = gapText;
  }

  function pills(all) {
    var present = KORDER.filter(function (k) { return all.some(function (s) { return s.k === k; }); });
    var box = $('kinds');
    box.setAttribute('aria-label', T('filterLabel'));
    box.innerHTML = ['all'].concat(present).map(function (k) {
      return '<button class="pill" type="button" data-k="' + k + '" aria-pressed="' + (k === kind) + '">' + esc(T(k === 'all' ? 'kindAll' : KIND[k])) + '</button>';
    }).join('');
  }

  function axis() {
    var n = days.length, X = function (i) { return (i + 0.5) / n * 100; };
    var h = '<span class="l" style="left:0">' + dd(D.first_day) + '</span><span class="r" style="left:100%">' + dd(D.last_day) + '</span>';
    days.forEach(function (d, i) { if (d.slice(8) === '01' && i > 5 && i < n - 5) { h += '<i style="left:' + X(i) + '%"></i><span style="left:' + X(i) + '%">' + dd(d) + '</span>'; } });
    if (sel != null) { h += '<span class="sel" style="left:' + X(sel) + '%">' + dd(days[sel]) + '</span>'; }
    return '<div class="axisrow"><span></span><div class="ax num">' + h + '</div><span></span></div>';
  }
  function cover(s) {
    var out = [];
    if (s.cur) { out.push(T(s.cur === 1 ? 'coverageCurrenciesOne' : 'coverageCurrencies', { n: s.cur })); }
    if (s.rt) { out.push(T(s.rt === 1 ? 'coverageRoutesOne' : 'coverageRoutes', { n: s.rt })); }
    return out;
  }
  function details(s) {
    var h = '';
    if (s.first) { h += '<p>' + esc(T('firstSeen', { date: ddY(s.first) })) + '</p>'; }
    if (s.last && Date.parse(D.as_of_utc) - Date.parse(s.last) >= 3600e3) { h += '<p>' + esc(T('lastAnswered', { time: clockT(s.last) })) + '</p>'; }
    if (s.h.length) {
      h += '<p class="h">' + esc(T('historyHeading')) + '</p>';
      s.h.forEach(function (x) {
        h += '<p class="num">' + esc(T(x.ccy && x.ccy.indexOf(',') < 0 ? 'historyLine' : 'historyLineNoCcy', {
          series: seriesName(x.series), ccy: x.ccy, interval: every(x.interval), rows: g(x.rows), first: ddY(x.first), last: ddY(x.last) })) + '</p>';
      });
    } else if (s.why && T('reason_' + s.why)) { h += '<p>' + esc(T('reason_' + s.why)) + '</p>'; }
    if (s.feeds) {
      h += '<ul class="feeds num">' + s.feeds.slice().sort(function (a, b) { return name(a.id).localeCompare(name(b.id)); }).map(function (f) {
        return '<li>' + esc(name(f.id).replace(/^CriptoYa · /, '')) + '<span>' + esc(split(T('hoursAnswered', { answered: g(f.ha), expected: g(f.he) }))[0]) + '</span></li>';
      }).join('') + '</ul>';
    }
    return h;
  }
  function row(s) {
    var sub = [T(KIND[s.k] || 'kindOther')].concat(s.feeds ? [T('feedsCount', { n: s.feeds.length })] : []).concat(cover(s)).filter(Boolean).join(' · ');
    var sp = split(T('hoursAnswered', { answered: g(s.ha), expected: g(s.he) }));
    var low = share(s) < 0.99;
    return '<div class="rowwrap" id="' + slug(s.id) + '" data-id="' + esc(s.id) + '"><div class="row">' +
      '<button class="nm" type="button" aria-expanded="false"><b>' + esc(name(s.id)) + '<span class="chev" aria-hidden="true">›</span></b><small>' + esc(sub) + '</small></button>' +
      '<div class="strip" tabindex="0" role="group" aria-label="' + esc(name(s.id)) + '">' +
      s.st.split('').map(function (c, i) { return '<span class="s-' + c + (i === sel ? ' on' : '') + '" data-i="' + i + '"></span>'; }).join('') + '</div>' +
      '<div class="v num"><b' + (low ? ' class="low"' : '') + '>' + esc(sp[0]) + '</b><small>' + esc(sp[1]) + '</small></div>' +
      '</div><div class="more">' + details(s) + '</div></div>';
  }
  function hrow(s) {
    return '<div class="hrow"><div><b>' + esc(name(s.id)) + '</b><small>' + esc(T(KIND[s.k] || 'kindOther')) + '</small></div><div>' +
      s.h.map(function (x) {
        return '<p class="num">' + esc(T('historyLineNoCcy', { series: seriesName(x.series), interval: every(x.interval), rows: g(x.rows), first: ddY(x.first), last: ddY(x.last) })) + '</p>';
      }).join('') + '</div></div>';
  }
  function render() {
    var L = live.filter(function (s) { return kind === 'all' || s.k === kind; });
    var H = hist.filter(function (s) { return kind === 'all' || s.k === kind; });
    var feeds = L.reduce(function (a, s) { return a + (s.feeds ? s.feeds.length : 1); }, 0);
    $('liveSec').hidden = !L.length;
    $('liveH').textContent = T('liveHeading', { n: feeds });
    $('liveList').innerHTML = axis() + L.map(row).join('');
    $('histSec').hidden = !H.length;
    $('histH').textContent = T('historyOnlyHeading', { n: H.length });
    $('histList').innerHTML = H.map(hrow).join('');
  }

  // a day in a strip: from where the pointer is along the strip, so a 5px square is still easy to hit
  function dayAt(strip, x) { var r = strip.getBoundingClientRect(); return Math.max(0, Math.min(days.length - 1, Math.floor((x - r.left) / r.width * days.length))); }
  function pick(i) {
    sel = i;
    [].forEach.call(document.querySelectorAll('.strip span.on'), function (x) { x.classList.remove('on'); });
    var day = $('day');
    var reAxis = function () { [].forEach.call(document.querySelectorAll('.axisrow'), function (a) { a.outerHTML = axis(); }); };
    if (i == null) { day.hidden = true; reAxis(); return; }
    [].forEach.call(document.querySelectorAll('.strip span[data-i="' + i + '"]'), function (x) { x.classList.add('on'); });
    reAxis();
    var cnt = { a: 0, s: 0, x: 0 };
    var feeds = live.reduce(function (a, s) { return a.concat(s.feeds || [s]); }, []);
    feeds.forEach(function (s) { if (s.st[i] !== 'n') { cnt[s.st[i]]++; } });
    var who = function (k) {
      return live.filter(function (s) { return s.st[i] === k; }).map(function (s) {
        return '<a href="#' + slug(s.id) + '" data-go="' + esc(s.id) + '">' + esc(name(s.id)) +
          (s.feeds ? ' (' + esc(T('feedsCount', { n: s.feeds.filter(function (f) { return f.st[i] === k; }).length })) + ')' : '') + '</a>';
      });
    };
    var w = '';
    if (collectorDays.indexOf(days[i]) >= 0) { w = '<p class="who">' + esc(gapText) + '</p>'; }
    else { ['x', 's'].forEach(function (k) { var l = who(k); if (l.length) { w += '<p class="who">' + esc(T(STAT[k])) + ': ' + l.join(', ') + '</p>'; } }); }
    day.innerHTML = '<div class="c"><span class="d">' + ddY(days[i]) + '</span>' +
      ['a', 's', 'x'].map(function (k) { return '<span><i class="s-' + k + '"></i>' + esc(T(STAT[k])) + '<b>' + cnt[k] + '</b></span>'; }).join('') + '</div>' +
      '<button class="x" type="button" aria-label="' + esc(T('clearDay')) + '">×</button>' + w;
    day.hidden = false;
  }
  function openRow(id) {
    var w = null;
    [].forEach.call(document.querySelectorAll('.rowwrap'), function (x) { if (x.dataset.id === id || x.id === id) { w = x; } });
    if (!w) { return; }
    w.classList.add('open'); w.querySelector('.nm').setAttribute('aria-expanded', 'true');
    window.scrollTo({ top: w.getBoundingClientRect().top + window.scrollY - $('day').offsetHeight - 8, behavior: 'smooth' });
  }

  function wire() {
    document.addEventListener('click', function (e) {
      var p = e.target.closest('[data-k]');
      if (p) { kind = p.dataset.k; pills(live.concat(hist)); render(); return; }
      var st = e.target.closest('.strip');
      if (st) { var i = dayAt(st, e.clientX); pick(i === sel ? null : i); return; }
      if (e.target.closest('.day .x')) { pick(null); return; }
      var go = e.target.closest('[data-go]');
      if (go) { e.preventDefault(); openRow(go.dataset.go); return; }
      var r = e.target.closest('button.nm');
      if (r) { var w = r.closest('.rowwrap'); w.classList.toggle('open'); r.setAttribute('aria-expanded', w.classList.contains('open')); }
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && sel != null) { pick(null); return; }
      if (!e.target.closest || !e.target.closest('.strip')) { return; }
      if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
        e.preventDefault();
        pick(Math.max(0, Math.min(days.length - 1, sel == null ? days.length - 1 : sel + (e.key === 'ArrowRight' ? 1 : -1))));
      }
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick(sel == null ? days.length - 1 : null); }
    });
    var tip = $('tip');
    document.addEventListener('pointermove', function (e) {
      var st = e.target.closest && e.target.closest('.strip');
      if (!st || e.pointerType === 'touch') { tip.hidden = true; return; }
      var i = dayAt(st, e.clientX), id = st.closest('.rowwrap').dataset.id;
      var s = live.filter(function (x) { return x.id === id; })[0];
      if (!s) { tip.hidden = true; return; }
      tip.textContent = T('stripDay', { day: dd(days[i]), status: T(STAT[s.st[i]]) });
      tip.hidden = false;
      var w = tip.offsetWidth, x = Math.min(window.innerWidth - w - 8, Math.max(8, e.clientX - w / 2));
      tip.style.left = x + 'px'; tip.style.top = (e.clientY - 40) + 'px';
    });
  }

  Promise.all([getJSON('./copy.json').catch(function () { return {}; }), getJSON('./data/sources_daily.json').catch(function () { return null; })]).then(function (r) {
    C = (r[0] && r[0].sourcesData) || {};
    D = r[1];
    if (!D || !D.sources) { var f = $('fail'); f.textContent = T('loadFailed'); f.hidden = !f.textContent; return; }
    header();
    var all = model(D);
    counts(all);
    pills(all);
    render();
    wire();
    var h = (location.hash || '').replace(/^#/, '');
    if (h) { openRow(h); }
  });
})();

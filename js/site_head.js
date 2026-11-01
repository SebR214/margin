/* Marks the current page in the nav (aria-current) and gives every page the home page's status on the right of
   the header: a dot, 'Last reading 8 Oct, 08:10 UTC', 'Next in 47:05'. The home page builds its own (js/home.js);
   on every other page this builds the same thing from data/cycle_log.json and the homeData words in copy.json. */
(function () {
  var here = (location.pathname.split('/').pop() || 'index.html').toLowerCase();
  var alias = { 'finding.html': 'findings.html', '': 'index.html' };
  here = alias[here] || here;
  function mark() {
    var links = document.querySelectorAll('.hp-nav a, .ci-nav a, .c-nav a, .sm-nav a, .s-nav a, .fp-nav a, .mwh nav a');
    [].forEach.call(links, function (a) {
      var target = (a.getAttribute('href') || '').split('?')[0].split('#')[0].split('/').pop().toLowerCase();
      if (target && target === here) { a.setAttribute('aria-current', 'page'); }
    });
  }
  // The one nav (DESIGN.md "Nav"): a page whose header still carries an old hand-written list, or an empty one, gets the
  // canonical seven links from homeData in copy.json, so every page shows the same menu.
  var CANON = [['navCountries', 'countries.html'], ['navRoutes', 'sending-money.html'], ['navSources', 'sources.html'],
    ['navFindings', 'findings.html'], ['navResearch', 'research.html'], ['navEvents', 'events.html'], ['navHow', 'how-it-works.html']];
  function canonNav() {
    var nav = document.querySelector('.mwh nav, [data-canon-nav]');
    if (!nav) { return; }
    fetch('./copy.json').then(function (r) { return r.json(); }).then(function (c) {
      var h = (c && c.homeData) || {};
      if (!CANON.every(function (l) { return h[l[0]]; })) { return; }
      nav.textContent = '';
      CANON.forEach(function (l) { var a = document.createElement('a'); a.href = './' + l[1]; a.textContent = h[l[0]]; nav.appendChild(a); });
      mark();
    }).catch(function () {});
  }
  canonNav();
  mark();
  document.addEventListener('DOMContentLoaded', mark);
  window.addEventListener('load', mark);
  var n = 0, t = setInterval(function () { mark(); if (++n > 20) { clearInterval(t); } }, 250);

  // ---- the phone menu (SEB-268): below 768px the nav is a list behind a Menu button (css/site_head.css) ----
  var NAVSEL = '.hp-nav, .ci-nav, .c-nav, .sm-nav, .s-nav, .fp-nav, .mwh nav';
  var menuLabel = null, closeLabel = '';
  function menu() {
    var nav = document.querySelector(NAVSEL);
    if (!nav || document.querySelector('.sh-menu')) { return; }
    if (menuLabel === null) {
      menuLabel = '';
      fetch('./copy.json').then(function (r) { return r.json(); }).then(function (c) {
        menuLabel = (c && c.homeData && c.homeData.menuLabel) || '';
        closeLabel = (c && c.homeData && c.homeData.menuClose) || '';
        var b = document.querySelector('.sh-menu'); if (b) { b.textContent = b.getAttribute('aria-expanded') === 'true' ? (closeLabel || menuLabel) : menuLabel; }
      }).catch(function () {});
    }
    if (!nav.id) { nav.id = 'sh-nav'; }
    var btn = document.createElement('button');
    btn.type = 'button'; btn.className = 'sh-menu'; btn.textContent = menuLabel;
    btn.setAttribute('aria-expanded', 'false'); btn.setAttribute('aria-controls', nav.id);
    nav.insertAdjacentElement('afterend', btn);
    // open: a full screen sheet over the page, big ink links, the button reads Close (27 Oct, Seb: "like Superpower").
    // The page goes back to where it was when the sheet closes.
    var keepY = 0;
    function set(open) {
      var was = nav.classList.contains('sh-open');
      if (open === was) { return; }
      if (open) { keepY = window.scrollY; window.scrollTo(0, 0); }
      nav.classList.toggle('sh-open', open); btn.setAttribute('aria-expanded', String(open));
      document.documentElement.classList.toggle('sh-menu-on', open);
      btn.textContent = open ? (closeLabel || menuLabel) : menuLabel;
      if (!open && keepY) { window.scrollTo(0, keepY); }
    }
    btn.addEventListener('click', function (e) { e.stopPropagation(); set(!nav.classList.contains('sh-open')); });
    nav.addEventListener('click', function (e) { if (e.target.closest('a')) { keepY = 0; set(false); } });
    document.addEventListener('click', function (e) { if (!nav.contains(e.target)) { set(false); } });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape') { set(false); } });
    window.addEventListener('resize', function () { if (window.innerWidth >= 768) { set(false); } });
  }
  menu();
  var mn = 0, mt = setInterval(function () { menu(); if (++mn > 40) { clearInterval(mt); } }, 250);

  var MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  function fill(tpl, v) { return String(tpl || '').replace(/\{(\w+)\}/g, function (m, k) { return v[k] != null ? v[k] : ''; }); }
  // ---- keeping an open tab current (SEB-268 item 9) ----
  // Pages register `siteLive.onNewHour(fn)`; fn refetches that page's own data and redraws, keeping the reader's
  // place, filters and picked route or amount. This file asks the small file the header already reads
  // (data/cycle_log.json) every 5 minutes, and when the tab comes back into view, never while it is hidden. When the
  // published last reading is newer than the one this page has, every registered fn runs. No page reload.
  var LIVE_EVERY = 5 * 60 * 1000, CHECK_FRESH = 90 * 1000;
  var live = window.siteLive = window.siteLive || { handlers: [], onNewHour: function (fn) { live.handlers.push(fn); } };
  var seen = null, checkedAt = 0, inflight = false, paint = null;
  function cycleUrl() { return './data/cycle_log.json?m=' + Math.floor(Date.now() / 60000); }   // a new URL each minute: a CDN copy cannot hide a new hour
  function poll() {
    if (document.hidden || inflight) { return Promise.resolve(); }
    inflight = true;
    return fetch(cycleUrl(), { cache: 'no-store' }).then(function (r) { return r.json(); }).then(function (CL) {
      checkedAt = Date.now();
      if (!CL || !CL.last_reading_utc) { return; }
      var newer = seen && CL.last_reading_utc > seen;
      if (seen === null) { seen = CL.last_reading_utc; }
      if (paint) { paint(CL); }
      if (newer) {
        seen = CL.last_reading_utc;
        return Promise.all(live.handlers.map(function (fn) { try { return fn(); } catch (e) { return null; } })).catch(function () {});
      }
    }).catch(function () { checkedAt = Date.now(); }).then(function () { inflight = false; });
  }
  setInterval(poll, LIVE_EVERY);
  document.addEventListener('visibilitychange', function () { if (!document.hidden) { poll(); } });
  poll();
  live.poll = poll;

  var clockStarted = false;
  function clock() {
    if (clockStarted || document.querySelector('.hp-clock')) { return; }
    var head = document.querySelector('.hp-head, .ci-head, .c-head, .sm-head, .s-head, .fp-head, .mwh');
    if (!head) { return; }     // pages that build their header from script: try again on the next tick
    clockStarted = true;
    Promise.all([
      fetch(cycleUrl(), { cache: 'no-store' }).then(function (r) { return r.json(); }),
      fetch('./copy.json', { cache: 'no-store' }).then(function (r) { return r.json(); })
    ]).then(function (r) {
      var CL = r[0], H = (r[1] && r[1].homeData) || {};
      if (document.querySelector('.hp-clock') || !CL || !CL.last_reading_utc || !CL.next_reading_utc || !H.headerLast) { return; }
      var box = document.createElement('div'); box.className = 'mono muted hp-clock';
      var dot = document.createElement('span'); dot.className = 'hp-dot'; box.appendChild(dot);
      var a = document.createElement('span'); box.appendChild(a);
      var b = document.createElement('span'); box.appendChild(b);
      var next = 0;
      var pad = function (x) { return (x < 10 ? '0' : '') + x; };
      // the last-reading text and the next-reading time come from the newest file we have read
      paint = function (C2) {
        var m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}:\d{2})/.exec(C2.last_reading_utc || '');
        if (!m || !C2.next_reading_utc) { return; }
        a.textContent = fill(H.headerLast, { time: (+m[3]) + ' ' + MON[+m[2] - 1] + ', ' + m[4] });
        next = Date.parse(C2.next_reading_utc);
        if (seen === null || C2.last_reading_utc >= seen) { seen = C2.last_reading_utc; }
        tick();
      };
      var tick = function () {
        if (!box.isConnected) {      // a page that redraws its whole header on a refresh: put the clock back in the new one
          var h2 = document.querySelector('.hp-head, .ci-head, .c-head, .sm-head, .s-head, .fp-head, .mwh');
          if (h2) { h2.appendChild(box); }
        }
        var diff = Math.round((next - Date.now()) / 1000), over = diff < 0, s = Math.abs(diff);
        var hh = Math.floor(s / 3600), mm = Math.floor((s % 3600) / 60), ss = s % 60;
        var late = Math.max(1, Math.round(s / 60));
        if (over && Date.now() - checkedAt > CHECK_FRESH) {
          // "late" is only said when the published file itself is late: look again before saying it, and say nothing meanwhile
          b.textContent = ''; dot.classList.remove('still'); poll(); return;
        }
        b.textContent = over ? fill(late === 1 ? H.headerOverdueOne : H.headerOverdue, { minutes: late }) : fill(H.headerNext, { countdown: (hh > 0 ? hh + ':' : '') + pad(mm) + ':' + pad(ss) });
        dot.classList.toggle('still', over);
      };
      paint(CL);
      if (!checkedAt) { checkedAt = Date.now(); }
      setInterval(tick, 1000);
      head.appendChild(box);
    }).catch(function () {});
  }
  clock();
  var cn = 0, ct = setInterval(function () { clock(); if (clockStarted || ++cn > 40) { clearInterval(ct); } }, 250);
})();

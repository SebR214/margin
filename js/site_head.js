/* Marks the current page in the nav (aria-current) and gives every page the home page's status on the right of
   the header: a dot, 'Last reading 8 Oct, 08:10 UTC', 'Next in 47:05'. The home page builds its own (js/home.js);
   on every other page this builds the same thing from data/cycle_log.json and the homeData words in copy.json. */
/* The one site header's behaviour (2 Nov 2026, DESIGN.md "Nav"). The header itself is plain HTML, the same on every page,
   written by tools/bake_nav.py; this script never draws or moves a link. It does three things:
   About opens and closes; below 768px the Menu button opens the links as a full screen sheet; and the time of the prices
   ("Prices from 13:15 UTC") goes on the right, from data/cycle_log.json and homeData "headerLast" in copy.json.
   It also keeps an open tab current (siteLive, below). */
(function () {
  var bar = function () { return document.querySelector('.site-head-bar'); };

  // ---- About: opens on click (and on hover where there is a mouse, css/site_head.css); a click elsewhere or Escape closes it
  function setAbout(box, open) {
    box.classList.toggle('sh-open-about', open);
    var b = box.querySelector('.sh-about-btn'); if (b) { b.setAttribute('aria-expanded', String(open)); }
  }
  function closeAbout(except) {
    [].forEach.call(document.querySelectorAll('.sh-about.sh-open-about'), function (x) { if (x !== except) { setAbout(x, false); } });
  }

  // ---- the phone menu: a full screen sheet over the page; the page goes back to where it was when the sheet closes
  var keepY = 0;
  function setMenu(open) {
    var nav = document.querySelector('.site-nav'), btn = document.querySelector('.sh-menu');
    if (!nav || !btn || nav.classList.contains('sh-open') === open) { return; }
    if (open) { keepY = window.scrollY; window.scrollTo(0, 0); }
    nav.classList.toggle('sh-open', open); btn.setAttribute('aria-expanded', String(open));
    document.documentElement.classList.toggle('sh-menu-on', open);
    btn.textContent = btn.getAttribute(open ? 'data-close' : 'data-open') || btn.textContent;
    if (!open && keepY) { window.scrollTo(0, keepY); }
  }

  document.addEventListener('click', function (e) {
    var t = e.target, about = t.closest && t.closest('.sh-about-btn'), menu = t.closest && t.closest('.sh-menu');
    closeAbout(about ? about.parentNode : null);
    if (about) { e.preventDefault(); setAbout(about.parentNode, !about.parentNode.classList.contains('sh-open-about')); return; }
    if (menu) { setMenu(!document.querySelector('.site-nav.sh-open')); return; }
    if (t.closest && t.closest('.site-nav a')) { keepY = 0; setMenu(false); return; }
    if (!(t.closest && t.closest('.site-nav'))) { setMenu(false); }
  });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') { closeAbout(null); setMenu(false); } });
  window.addEventListener('resize', function () { if (window.innerWidth >= 768) { setMenu(false); } });

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
    if (clockStarted || document.querySelector('.sh-clock')) { return; }
    var head = bar();
    if (!head) { return; }     // the page has not been parsed this far yet: try again on the next tick
    clockStarted = true;
    Promise.all([
      fetch(cycleUrl(), { cache: 'no-store' }).then(function (r) { return r.json(); }),
      fetch('./copy.json', { cache: 'no-store' }).then(function (r) { return r.json(); })
    ]).then(function (r) {
      var CL = r[0], H = (r[1] && r[1].homeData) || {};
      if (document.querySelector('.sh-clock') || !CL || !CL.last_reading_utc || !CL.next_reading_utc || !H.headerLast) { return; }
      var box = document.createElement('div'); box.className = 'mono muted sh-clock';
      var dot = document.createElement('span'); dot.className = 'sh-dot'; box.appendChild(dot);
      var a = document.createElement('span'); box.appendChild(a);
      var b = document.createElement('span'); box.appendChild(b);
      var next = 0;
      var pad = function (x) { return (x < 10 ? '0' : '') + x; };
      // the last-reading text and the next-reading time come from the newest file we have read
      paint = function (C2) {
        var m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}:\d{2})/.exec(C2.last_reading_utc || '');
        if (!m || !C2.next_reading_utc) { return; }
        a.textContent = fill(H.headerLast, { time: m[4] });
        next = Date.parse(C2.next_reading_utc);
        if (seen === null || C2.last_reading_utc >= seen) { seen = C2.last_reading_utc; }
        tick();
      };
      var tick = function () {
                var diff = Math.round((next - Date.now()) / 1000), over = diff < 0, s = Math.abs(diff);
        var hh = Math.floor(s / 3600), mm = Math.floor((s % 3600) / 60), ss = s % 60;
        var late = Math.max(1, Math.round(s / 60));
        if (over && Date.now() - checkedAt > CHECK_FRESH) {
          // "late" is only said when the published file itself is late: look again before saying it, and say nothing meanwhile
          b.textContent = ''; dot.classList.remove('still'); poll(); return;
        }
        b.textContent = '';   // the bar says only when the prices are from (2 Nov, Seb): no countdown, no late note
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

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
  mark();
  document.addEventListener('DOMContentLoaded', mark);
  window.addEventListener('load', mark);
  var n = 0, t = setInterval(function () { mark(); if (++n > 20) { clearInterval(t); } }, 250);

  var MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  function fill(tpl, v) { return String(tpl || '').replace(/\{(\w+)\}/g, function (m, k) { return v[k] != null ? v[k] : ''; }); }
  var clockStarted = false;
  function clock() {
    if (clockStarted || document.querySelector('.hp-clock')) { return; }
    var head = document.querySelector('.hp-head, .ci-head, .c-head, .sm-head, .s-head, .fp-head, .mwh');
    if (!head) { return; }     // pages that build their header from script: try again on the next tick
    clockStarted = true;
    Promise.all([
      fetch('./data/cycle_log.json', { cache: 'no-store' }).then(function (r) { return r.json(); }),
      fetch('./copy.json', { cache: 'no-store' }).then(function (r) { return r.json(); })
    ]).then(function (r) {
      var CL = r[0], H = (r[1] && r[1].homeData) || {};
      if (document.querySelector('.hp-clock') || !CL || !CL.last_reading_utc || !CL.next_reading_utc || !H.headerLast) { return; }
      var l = CL.last_reading_utc, m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}:\d{2})/.exec(l);
      if (!m) { return; }
      var box = document.createElement('div'); box.className = 'mono muted hp-clock';
      var dot = document.createElement('span'); dot.className = 'hp-dot'; box.appendChild(dot);
      var a = document.createElement('span'); a.textContent = fill(H.headerLast, { time: (+m[3]) + ' ' + MON[+m[2] - 1] + ', ' + m[4] }); box.appendChild(a);
      var b = document.createElement('span'); box.appendChild(b);
      var next = Date.parse(CL.next_reading_utc);
      var pad = function (x) { return (x < 10 ? '0' : '') + x; };
      var tick = function () {
        var diff = Math.round((next - Date.now()) / 1000), over = diff < 0, s = Math.abs(diff);
        var hh = Math.floor(s / 3600), mm = Math.floor((s % 3600) / 60), ss = s % 60;
        var late = Math.max(1, Math.round(s / 60));
        b.textContent = over ? fill(late === 1 ? H.headerOverdueOne : H.headerOverdue, { minutes: late }) : fill(H.headerNext, { countdown: (hh > 0 ? hh + ':' : '') + pad(mm) + ':' + pad(ss) });
        dot.classList.toggle('still', over);
      };
      tick(); setInterval(tick, 1000);
      head.appendChild(box);
    }).catch(function () {});
  }
  clock();
  var cn = 0, ct = setInterval(function () { clock(); if (clockStarted || ++cn > 40) { clearInterval(ct); } }, 250);
})();

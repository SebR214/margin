/* Home time control (SEB-384 step 4). Scrubs the home grid back to any day since 2000, or hour by hour over the last 90 days.
 * Reads data/map_timeline/ (tools/emit_map_timeline.py): index.json, one <year>.json per year, last90.json. Nothing is computed here
 * beyond picking the window: every value on the grid is a value in those files. Every word is a homeData key (copy.json); with
 * the keys empty the control does not draw and the grid stays as it was.
 * A point is {v: tenths of a percent or null, k: '0' ours, '1' reported exchange, '2' official only, '-' no data}. */
(function () {
  var MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  var WIN = 30;                                   // squares in the window: 30 days, or 30 hours in the hourly view
  var BASE = './data/map_timeline/';
  var IDX = null, YEARS = {}, HOURS = null, ctx = null, cur = null, token = 0, listeners = [];
  var S = { mode: 'now', year: null, i: 0 };      // mode: now (the home grid as it was), day, hour

  function getJSON(u) { return fetch(u, { cache: 'no-store' }).then(function (r) { if (!r.ok) { throw new Error(u); } return r.json(); }); }
  function pad(n) { return (n < 10 ? '0' : '') + n; }
  function isLeap(y) { return y % 4 === 0 && (y % 100 !== 0 || y % 400 === 0); }
  function fmtDay(s) { return (+s.slice(8, 10)) + ' ' + MON[+s.slice(5, 7) - 1] + ' ' + s.slice(0, 4); }
  function fmtHour(s) { return fmtDay(s.slice(0, 10)) + ' ' + s.slice(11, 13) + ':00 UTC'; }
  function dayOfYear(s) { return Math.round((Date.UTC(+s.slice(0, 4), +s.slice(5, 7) - 1, +s.slice(8, 10)) - Date.UTC(+s.slice(0, 4), 0, 1)) / 864e5) + 1; }
  function daysIn(y) { return +IDX.last_day.slice(0, 4) === y ? dayOfYear(IDX.last_day) : (isLeap(y) ? 366 : 365); }
  function T(k, v) { return ctx.T(k, v); }
  function ready() { return !!(ctx && IDX && T('tlNow') && T('tlYear') && T('tlHourly')); }

  function loadYear(y) { return YEARS[y] ? Promise.resolve(YEARS[y]) : getJSON(BASE + y + '.json').then(function (j) { YEARS[y] = j; return j; }); }
  function loadHours() { return HOURS ? Promise.resolve(HOURS) : getJSON(BASE + 'last90.json').then(function (j) { HOURS = j; return j; }); }

  function mkRows(labels, pick) {
    return IDX.countries.map(function (c) {
      return { ccy: c.ccy, country: c.country, cells: labels.map(function (_, j) { return pick(c.ccy, j); }) };
    });
  }
  function finish(labels, rows, hourly) {
    var last = labels.length - 1;
    rows.forEach(function (r) { r.end = r.cells[last]; });
    var prem = rows.filter(function (r) { return r.end.k === '0' || r.end.k === '1'; });
    var order = function (a, b) { return b.end.v - a.end.v; };
    var off = rows.filter(function (r) { return r.end.k === '2'; }), none = rows.filter(function (r) { return r.end.k === '-'; });
    var ranked = prem.sort(order).concat(off.sort(order), none);
    // before our own record begins everything on the grid is reported, not seen by us, whatever a given square holds
    var reported = (!hourly && labels[last] < IDX.own_start) || rows.some(function (r) { return r.cells.some(function (c) { return c.k === '1' || c.k === '2'; }); });
    return { hourly: hourly, labels: labels, when: hourly ? fmtHour(labels[last] + ':00') : fmtDay(labels[last]), rows: ranked, reported: reported,
      counts: { n: prem.filter(function (r) { return r.end.v >= -20 && r.end.v <= 20; }).length, N: prem.length, off: off.length } };
  }

  function buildDay() {
    var y = S.year, i = S.i;
    return loadYear(y).then(function (cur0) {
      var need = WIN - 1 - i, prevY = need > 0 && IDX.years.indexOf(y - 1) >= 0 ? y - 1 : null;
      return (prevY ? loadYear(prevY) : Promise.resolve(null)).then(function (prev) {
        var parts = [];
        if (prev && need > 0) { parts.push({ f: prev, a: prev.days.length - need, b: prev.days.length }); }
        parts.push({ f: cur0, a: Math.max(0, i - WIN + 1), b: i + 1 });
        var labels = [];
        parts.forEach(function (p) { labels = labels.concat(p.f.days.slice(p.a, p.b)); });
        var rows = mkRows(labels, function (ccy, j) {
          var q = 0;
          for (var s = 0; s < parts.length; s++) {
            var len = parts[s].b - parts[s].a;
            if (j < q + len) {
              var x = parts[s].f.ccy[ccy], at = parts[s].a + j - q;
              return x ? { v: x.v[at], k: x.k.charAt(at) } : { v: null, k: '-' };
            }
            q += len;
          }
          return { v: null, k: '-' };
        });
        return finish(labels, rows, false);
      });
    });
  }

  function buildHour() {
    return loadHours().then(function (h) {
      var end = Math.min(h.hours.length - 1, Math.max(0, S.i)), a = Math.max(0, end - WIN + 1);
      var labels = h.hours.slice(a, end + 1);
      var rows = mkRows(labels, function (ccy, j) {
        var x = h.ccy[ccy], at = a + j - (x ? x.o : 0), v = x && at >= 0 && at < x.v.length ? x.v[at] : null;
        return v == null ? { v: null, k: '-' } : { v: v, k: '0' };
      });
      return finish(labels, rows, true);
    });
  }

  function refresh() {
    var mine = ++token;
    if (S.mode === 'now') { cur = null; paint(); listeners.forEach(function (f) { f(); }); return; }
    (S.mode === 'hour' ? buildHour() : buildDay()).then(function (v) {
      if (mine !== token) { return; }
      cur = v; paint(); listeners.forEach(function (f) { f(); });
    }).catch(function () { if (mine === token) { S.mode = 'now'; cur = null; paint(); listeners.forEach(function (f) { f(); }); } });
  }

  function paint() {
    var box = ctx.mount, on = S.mode;
    if (!ready()) { box.innerHTML = ''; return; }
    var yrs = (IDX.menu_years || IDX.years).slice().reverse().map(function (y) {
      return '<option value="' + y + '"' + (on === 'day' && S.year === y ? ' selected' : '') + '>' + y + '</option>';
    }).join('');
    var max = 0;
    var html = '<div class="tl"><div class="tlbar">' +
      '<button class="pill" type="button" data-tl="now" aria-pressed="' + (on === 'now') + '">' + ctx.esc(T('tlNow')) + '</button>' +
      '<label class="tlyear"><span>' + ctx.esc(T('tlYear')) + '</span><select id="tlY" >' +
      (on === 'day' ? '' : '<option value="" selected></option>') + yrs + '</select></label>' +
      '<button class="pill" type="button" data-tl="hour" aria-pressed="' + (on === 'hour') + '">' + ctx.esc(T('tlHourly')) + '</button></div>';
    if (on !== 'now') {
      var n = on === 'hour' ? (HOURS ? HOURS.hours.length : 0) : daysIn(S.year);
      max = Math.max(0, n - 1);
      html += '<div class="tlslide"><input type="range" id="tlR" min="0" max="' + max + '" step="1" value="' + Math.min(S.i, max) +
        '" aria-label="' + ctx.esc(T(on === 'hour' ? 'tlSliderHour' : 'tlSliderDay')) + '"><span class="tlwhen num" id="tlW">' +
        (cur ? ctx.esc(T('tlShowing', { when: cur.when })) : '') + '</span></div>';
    }
    box.innerHTML = html + '</div>';
  }

  function setDay(y, i) { S.mode = 'day'; S.year = y; S.i = i == null ? daysIn(y) - 1 : i; }

  // ?day=YYYY-MM-DD (the Events page links here): open the time control on that day, if the record holds it
  function deepLink() {
    var m = /[?&]day=(\d{4})-(\d{2})-(\d{2})(?:&|$)/.exec(location.search || '');
    if (!m || !IDX) { return; }
    var d = m[1] + '-' + m[2] + '-' + m[3], y = +m[1];
    if (d < IDX.first_day || d > IDX.last_day || IDX.years.indexOf(y) < 0) { return; }
    setDay(y, dayOfYear(d) - 1);
    refresh();
  }

  function wire() {
    var box = ctx.mount;
    box.addEventListener('click', function (e) {
      var b = e.target.closest('[data-tl]');
      if (!b) { return; }
      if (b.dataset.tl === 'now') { S.mode = 'now'; refresh(); return; }
      if (b.dataset.tl === 'hour') { loadHours().then(function (h) { S.mode = 'hour'; S.i = h.hours.length - 1; refresh(); }); }
    });
    box.addEventListener('change', function (e) {
      if (e.target.id === 'tlY' && e.target.value) { setDay(+e.target.value, null); refresh(); }
    });
    box.addEventListener('input', function (e) {
      if (e.target.id !== 'tlR') { return; }
      S.i = +e.target.value;
      var mine = S.i;
      (S.mode === 'hour' ? buildHour() : buildDay()).then(function (v) {
        if (mine !== S.i) { return; }
        cur = v; listeners.forEach(function (f) { f(); });
        var w = document.getElementById('tlW'); if (w) { w.textContent = ctx.T('tlShowing', { when: v.when }); }
      });
    });
  }

  window.homeTimeline = {
    // ctx: { T, esc, mount }. Safe to call again on every reload of the page's data: the state stays.
    init: function (c) {
      var first = !ctx;
      ctx = c;
      var go = function () { if (first) { wire(); deepLink(); } paint(); };
      if (IDX) { go(); return Promise.resolve(); }
      return getJSON(BASE + 'index.json').then(function (j) { IDX = j; go(); }).catch(function () { IDX = null; });
    },
    view: function () { return S.mode === 'now' ? null : cur; },
    meta: function () { return IDX; },
    fmt: function (label, hourly) { return hourly ? fmtHour(label + ':00') : fmtDay(label); },
    onChange: function (f) { listeners.push(f); }
  };
})();

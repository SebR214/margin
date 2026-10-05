/* Record block ("The record grew"): cumulative readings since the record began, with
 * markers on the real dates each source, route and backfill went live. Moved off the home
 * page (SEB-240 home v2) so how-it-was-built.html can use it.
 *
 *   renderRecordBlock(containerEl, recordDaily, milestones, copyBlock)
 *     recordDaily = parsed data/record_daily.json
 *     milestones  = parsed data/record_milestones.json (the object, or its .milestones array)
 *     copyBlock   = an object holding these keys (same names and placeholders as
 *                   docs/copy-slots/home.md "Record timeline"): recordTitle, recordCount,
 *                   axisToday, markBackfill, markRoute, markSource, markSources.
 *   A key that is empty or missing is not rendered; a marker whose words are empty is dropped.
 *   Call it when containerEl is attached to the document (marker placement measures widths).
 *   Classes are the hp-* classes (hp-sec, hp-record, hp-mark, hp-axis, ...) from the home
 *   page's stylesheet; the caller's page must carry that CSS. No word is written here.
 */
(function (root) {
  var SVGNS = 'http://www.w3.org/2000/svg';
  function mk(C) {
    var o = {};
    o.has = function (key) { return typeof C[key] === 'string' && C[key].length > 0; };
    o.t = function (key, vars) {
      return o.has(key) ? C[key].replace(/\{(\w+)\}/g, function (m, k) { return vars && vars[k] != null ? vars[k] : ''; }) : '';
    };
    return o;
  }
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) { [].concat(cls).forEach(function (c) { e.classList.add(c); }); }
    if (text != null) { e.textContent = text; }
    return e;
  }
  function sv(tag, attrs, cls) {
    var e = document.createElementNS(SVGNS, tag);
    Object.keys(attrs || {}).forEach(function (k) { e.setAttribute(k, attrs[k]); });
    if (cls) { e.setAttribute('class', cls); }
    return e;
  }
  function num(n, d) {
    if (n == null || isNaN(n)) { return ''; }
    return Number(n).toLocaleString('en-US', { maximumFractionDigits: d || 0, minimumFractionDigits: d || 0 });
  }
  function dShort(day) {
    return new Date(day + 'T00:00:00Z').toLocaleDateString('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC' });
  }
  function dLong(day) {
    return new Date(day + 'T00:00:00Z').toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });
  }
  function hhmm(iso) { return iso ? iso.slice(11, 16) : ''; }

  function renderRecordBlock(containerEl, recordDaily, milestones, copyBlock) {
    var K = mk(copyBlock || {}), has = K.has, t = K.t;
    var R = recordDaily;
    if (!R || !R.days || R.days.length < 2) { return; }
    var D = {};
    D.milestones = Array.isArray(milestones) ? milestones : ((milestones && milestones.milestones) || []);
    var rd = R.days;
    var n = rd.length;
    var sec = el('section', 'hp-sec');
    var head = el('div', 'hp-sechead');
    if (has('recordTitle')) { head.appendChild(el('h2', null, t('recordTitle'))); }
    if (has('recordCount')) { head.appendChild(el('span', ['mono', 'muted', 'hp-small'], t('recordCount', { n: num(rd[n - 1].readings_cumulative) }))); }
    sec.appendChild(head);
    var box = el('div', 'hp-record');
    var max = rd[n - 1].readings_cumulative || 1;
    var X = function (k) { return (k * 560 / (n - 1)).toFixed(1); };
    var pts = rd.map(function (d, k) { return X(k) + ',' + (118 - d.readings_cumulative / max * 108).toFixed(1); });
    var line = 'M' + pts.join(' L');
    var svg = sv('svg', { viewBox: '0 0 560 120', preserveAspectRatio: 'none' }, 'hp-recsvg');
    svg.appendChild(sv('path', { d: line + ' L560,120 L0,120 Z' }, 'hp-area'));
    svg.appendChild(sv('path', { d: line, 'vector-effect': 'non-scaling-stroke' }, 'hp-line'));
    box.appendChild(svg);

    // markers: backfill and route days first, then source days by how many sources began
    var cands = [];
    var byDay = {};
    var back = [];
    (D.milestones || []).forEach(function (m) {
      if (m.kind === 'backfill') { back.push(m); return; }
      var o = byDay[m.first_day] || (byDay[m.first_day] = { route: [], source: [] });
      (o[m.kind] || o.source).push(m.id);
    });
    if (back.length) {
      back.sort(function (a, b) { return a.first_day < b.first_day ? -1 : 1; });
      cands.push({ prio: 0, k: 0, ids: back.map(function (m) { return m.id; }),
        parts: [t('markBackfill', { n: back.length, date: dLong(back[0].first_day), id: back[0].id })] });
    }
    var dayKeys = Object.keys(byDay).sort();
    var idx = {};
    rd.forEach(function (d, k) { idx[d.day] = k; });
    dayKeys.forEach(function (day) {
      if (idx[day] == null) { return; }
      var o = byDay[day], parts = [], ids = o.route.concat(o.source);
      if (o.route.length) { parts.push(t('markRoute', { date: dShort(day), n: o.route.length, ids: o.route.join(', ') })); }
      if (o.source.length) {
        parts.push(o.source.length === 1
          ? t('markSource', { date: dShort(day), id: o.source[0] })
          : t('markSources', { date: dShort(day), n: o.source.length }));
      }
      cands.push({ prio: o.route.length ? 1 : 2 + (1 - Math.min(o.source.length, 1000) / 1000), k: idx[day], ids: ids, parts: parts, day: day });
    });
    cands.sort(function (a, b) { return a.prio - b.prio || a.k - b.k; });
    var marks = cands.filter(function (c) { return c.parts.some(Boolean); }).map(function (c) {
      var m = el('div', 'hp-mark');
      m.title = c.ids.join(', ');
      var lab = el('span', ['soft', 'hp-marklabel']);
      c.parts.filter(Boolean).forEach(function (p, q) { lab.appendChild(el('span', 'hp-markpart', p)); });
      m.appendChild(lab);
      m.appendChild(el('span', 'hp-markline'));
      m.style.visibility = 'hidden';
      box.appendChild(m);
      return { c: c, m: m, lab: lab };
    });
    var place = function () {
      var W = box.clientWidth;
      var placed = [];
      marks.forEach(function (o) { o.m.style.display = ''; o.m.style.visibility = 'hidden'; });
      marks.forEach(function (o) {
        var p = o.c.k / (n - 1);
        var right = p > 0.6;
        var w = o.lab.offsetWidth;
        var x = p * W;
        var fits = function (r) { return r ? x - w >= -1 : x + w <= W + 1; };
        if (!fits(right)) { right = !right; }
        if (!fits(right)) { o.m.style.display = 'none'; return; }
        var a = right ? x - w : x, b = right ? x : x + w;
        var ok = -1;
        for (var lane = 0; lane < 3 && ok < 0; lane++) {
          var clash = placed.some(function (q) {
            if (q.lane === lane) { return a < q.b + 10 && b > q.a - 10; }                // same row
            if (q.lane < lane) { return q.x > a - 6 && q.x < b + 6; }                    // its line crosses this row
            return x > q.a - 6 && x < q.b + 6;                                           // our line crosses its row
          });
          if (!clash) { ok = lane; }
        }
        if (ok < 0) { o.m.style.display = 'none'; return; }
        o.m.style.display = '';
        o.m.style.visibility = 'visible';
        o.m.style.top = (ok * 22) + 'px';
        o.m.style.left = right ? 'auto' : (p * 100).toFixed(2) + '%';
        o.m.style.right = right ? ((1 - p) * 100).toFixed(2) + '%' : 'auto';
        o.m.classList.toggle('end', right);
        o.m.lastChild.style.height = (176 - ok * 22) + 'px';
        placed.push({ lane: ok, a: a, b: b, x: x });
      });
    };
    D.placeMarks = place;
    sec.appendChild(box);
    var foot = el('div', ['mono', 'muted', 'hp-axis']);
    foot.appendChild(el('span', null, dShort(rd[0].day)));
    if (has('axisToday')) { foot.appendChild(el('span', null, t('axisToday'))); }
    sec.appendChild(foot);
    containerEl.appendChild(sec);
    place();
    var rt = null;
    window.addEventListener('resize', function () { clearTimeout(rt); rt = setTimeout(place, 120); });
    if (document.fonts && document.fonts.ready) { document.fonts.ready.then(place); }
  }

  root.renderRecordBlock = renderRecordBlock;
  if (typeof module !== 'undefined' && module.exports) { module.exports = { renderRecordBlock: renderRecordBlock }; }
  if (typeof window !== 'undefined') { window.renderRecordBlock = renderRecordBlock; }
})(typeof window !== 'undefined' ? window : this);
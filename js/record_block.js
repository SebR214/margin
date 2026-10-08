/* Record block ("The record grew"): cumulative readings since the record began, with
 * markers on the real dates each source, route and backfill went live. Moved off the home
 * page (SEB-240 home v2) so how-it-was-built.html can use it.
 *
 *   renderRecordBlock(containerEl, recordDaily, milestones, copyBlock, routeNames)
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
    return new Date(day + 'T00:00:00Z').toLocaleDateString('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC' }).replace('Sept', 'Sep');
  }
  function dLong(day) {
    return new Date(day + 'T00:00:00Z').toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' }).replace('Sept', 'Sep');
  }
  function hhmm(iso) { return iso ? iso.slice(11, 16) : ''; }

  var CSS = [
    '.rb-plot{position:relative;height:210px;margin-left:44px;border-bottom:1px solid var(--color-neutral-300);touch-action:pan-y;outline-offset:2px}',
    '.rb-y{position:absolute;left:-44px;width:38px;text-align:right;font-size:11px;transform:translateY(50%)}',
    '.rb-grid{position:absolute;left:0;right:0;height:1px;background:var(--color-neutral-200)}',
    '.rb-dot{position:absolute;width:7px;height:7px;margin:-3px 0 0 -3px;border-radius:50%;background:var(--color-bg);border:1.5px solid var(--data-700);pointer-events:none}',
    '.rb-dot.route{width:9px;height:9px;margin:-4px 0 0 -4px;background:var(--color-neutral-900);border-color:var(--color-bg)}',
    '.rb-cross{position:absolute;top:0;bottom:0;width:0;border-left:1px dashed var(--color-neutral-600);pointer-events:none;display:none}',
    '.rb-card{position:absolute;top:6px;z-index:3;width:max-content;max-width:min(260px,calc(100vw - 32px));padding:10px 12px;background:var(--color-bg);border:1px solid var(--color-neutral-300);font-size:13px;line-height:1.4;pointer-events:none;display:none}',
    '.rb-card .d{font-weight:600;margin-bottom:4px}',
    '.rb-card div+div{margin-top:2px}',
    '.rb-note{font-size:13px;margin:0 0 12px}'
  ].join('');
  var cssDone = false;

  function renderRecordBlock(containerEl, recordDaily, milestones, copyBlock, routeNames) {
    var K = mk(copyBlock || {}), has = K.has, t = K.t;
    var R = recordDaily;
    if (!R || !R.days || R.days.length < 2) { return; }
    if (!cssDone) { var st = document.createElement('style'); st.textContent = CSS; document.head.appendChild(st); cssDone = true; }
    var names = routeNames || {};
    var rn = function (id) { return names[id] || id; };
    var ms = Array.isArray(milestones) ? milestones : ((milestones && milestones.milestones) || []);
    var rd = R.days, n = rd.length;
    var idx = {};
    rd.forEach(function (d, k) { idx[d.day] = k; });

    var sec = el('section', 'hp-sec');
    var head = el('div', 'hp-sechead');
    if (has('recordTitle')) { head.appendChild(el('h2', null, t('recordTitle'))); }
    var countEl = null;
    var today = rd[n - 1].readings_cumulative;
    if (has('recordCount')) { countEl = el('span', ['mono', 'muted', 'hp-small'], t('recordCount', { n: num(today) })); head.appendChild(countEl); }
    sec.appendChild(head);

    // The backfill note stays as one line under the heading.
    var back = ms.filter(function (m) { return m.kind === 'backfill'; }).sort(function (a, b) { return a.first_day < b.first_day ? -1 : 1; });
    if (back.length && has('markBackfill')) {
      sec.appendChild(el('p', ['soft', 'rb-note'], t('markBackfill', { n: back.length, date: dLong(back[0].first_day), id: back[0].id })));
    }

    if (has('recordDotNote')) { sec.appendChild(el('p', ['soft', 'rb-note'], t('recordDotNote'))); }
    var max = rd[n - 1].readings_cumulative || 1;
    var plot = el('div', 'rb-plot');
    plot.tabIndex = 0;
    var Hh = 210, PADT = 14;
    var xp = function (k) { return k / (n - 1) * 100; };
    var yp = function (v) { return PADT + (1 - v / max) * (Hh - PADT - 1); };   // px from the top

    // y axis: light labels outside the plot
    [0, 0.5, 1].forEach(function (f) {
      var v = Math.round(max * f);
      var top = yp(max * f);
      var lab = el('span', ['mono', 'muted', 'rb-y'], num(v));
      lab.style.top = top + 'px';
      lab.style.transform = 'translateY(-50%)';
      plot.appendChild(lab);
      if (f > 0) { var g = el('div', 'rb-grid'); g.style.top = top + 'px'; plot.appendChild(g); }
    });

    var pts = rd.map(function (d, k) { return (xp(k) * 5.6).toFixed(1) + ',' + yp(d.readings_cumulative).toFixed(1); });
    var line = 'M' + pts.join(' L');
    var svg = sv('svg', { viewBox: '0 0 560 ' + Hh, preserveAspectRatio: 'none' }, 'hp-recsvg');
    svg.style.cssText = 'position:absolute;left:0;top:0;width:100%;height:' + Hh + 'px;overflow:visible';
    svg.appendChild(sv('path', { d: line + ' L560,' + Hh + ' L0,' + Hh + ' Z' }, 'hp-area'));
    svg.appendChild(sv('path', { d: line, 'vector-effect': 'non-scaling-stroke' }, 'hp-line'));
    plot.appendChild(svg);

    // what started on each day, by name
    var byDay = {};
    ms.forEach(function (m) {
      if (m.kind === 'backfill') { return; }
      var o = byDay[m.first_day] || (byDay[m.first_day] = { route: [], source: [] });
      (m.kind === 'route' ? o.route : o.source).push(m.id);
    });
    var started = function (day) {
      var o = byDay[day], out = [];
      if (!o) { return out; }
      if (o.route.length) { out.push(t('markRoute', { date: dShort(day), n: o.route.length, ids: o.route.map(rn).join(', ') })); }
      if (o.source.length) {
        out.push(o.source.length === 1 ? t('markSource', { date: dShort(day), id: o.source[0] })
                                       : t('markSources', { date: dShort(day), n: o.source.length }) + (o.source.length <= 8 ? ' (' + o.source.join(', ') + ')' : ''));
      }
      return out.filter(Boolean);
    };

    // markers sit on the line: a dark dot for a day a route started, an open dot for a day sources started. No labels:
    // the day's card names everything that started.
    Object.keys(byDay).sort().forEach(function (day) {
      var k = idx[day]; if (k == null) { return; }
      var isRoute = byDay[day].route.length > 0;
      var dot = el('div', ['rb-dot'].concat(isRoute ? ['route'] : []));
      dot.style.left = xp(k).toFixed(2) + '%';
      dot.style.top = yp(rd[k].readings_cumulative) + 'px';
      plot.appendChild(dot);
    });

    // hover, touch and keyboard: a dashed line snaps to the nearest day; a card says what that day was
    var cross = el('div', 'rb-cross'), card = el('div', 'rb-card');
    plot.appendChild(cross); plot.appendChild(card);
    var cur = -1;
    var show = function (k) {
      k = Math.max(0, Math.min(n - 1, k)); cur = k;
      var d = rd[k], W = plot.clientWidth, x = xp(k) / 100 * W;
      cross.style.left = x + 'px'; cross.style.display = 'block';
      card.textContent = '';
      card.appendChild(el('div', 'd', dLong(d.day)));
      if (has('recordCount')) { card.appendChild(el('div', 'mono', t('recordCount', { n: num(d.readings_cumulative) }))); }
      if (has('recordCardSources') && d.sources_live != null) { card.appendChild(el('div', null, t('recordCardSources', { n: num(d.sources_live) }))); }
      if (has('recordCardRoutes') && d.routes_priced != null) { card.appendChild(el('div', null, t('recordCardRoutes', { n: num(d.routes_priced) }))); }
      started(d.day).forEach(function (line) { card.appendChild(el('div', 'soft', line)); });
      card.style.display = 'block';
      var cw = card.offsetWidth;
      var left = x + 12 + cw <= W + 44 ? x + 12 : x - 12 - cw;
      card.style.left = Math.max(-44, left) + 'px';
      if (countEl) { countEl.textContent = t('recordCount', { n: num(d.readings_cumulative) }); }
    };
    var hide = function () {
      cur = -1; cross.style.display = 'none'; card.style.display = 'none';
      if (countEl) { countEl.textContent = t('recordCount', { n: num(today) }); }
    };
    var kAt = function (ev) {
      var r = plot.getBoundingClientRect();
      var cx = (ev.touches && ev.touches[0] ? ev.touches[0].clientX : ev.clientX);
      return Math.round(Math.max(0, Math.min(1, (cx - r.left) / r.width)) * (n - 1));
    };
    plot.addEventListener('pointermove', function (ev) { show(kAt(ev)); });
    plot.addEventListener('pointerdown', function (ev) { show(kAt(ev)); });
    plot.addEventListener('pointerleave', function (ev) { if (ev.pointerType !== 'touch') { hide(); } });
    plot.addEventListener('keydown', function (ev) {
      if (ev.key === 'ArrowLeft') { show((cur < 0 ? n - 1 : cur) - 1); ev.preventDefault(); }
      else if (ev.key === 'ArrowRight') { show((cur < 0 ? n - 2 : cur) + 1); ev.preventDefault(); }
      else if (ev.key === 'Escape' || ev.key === 'Home' && false) { hide(); }
    });
    plot.addEventListener('blur', hide);
    document.addEventListener('pointerdown', function (ev) { if (!plot.contains(ev.target)) { hide(); } });

    sec.appendChild(plot);
    var foot = el('div', ['mono', 'muted', 'hp-axis']);
    foot.style.marginLeft = '44px';
    foot.appendChild(el('span', null, dShort(rd[0].day)));
    if (has('axisToday')) { foot.appendChild(el('span', null, t('axisToday'))); }
    sec.appendChild(foot);
    containerEl.appendChild(sec);
  }

  root.renderRecordBlock = renderRecordBlock;
  if (typeof module !== 'undefined' && module.exports) { module.exports = { renderRecordBlock: renderRecordBlock }; }
if (typeof window !== 'undefined') { window.renderRecordBlock = renderRecordBlock; }
})(typeof window !== 'undefined' ? window : this);

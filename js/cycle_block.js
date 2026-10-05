/* Cycle block ("This hour"): the last collection cycle's steps plus the last 48 cycles
 * as squares. Moved off the home page (SEB-240 home v2) so how-it-works.html can use it.
 *
 *   renderCycleBlock(containerEl, cycleLog, copyBlock)
 *     cycleLog  = parsed data/cycle_log.json
 *     copyBlock = an object holding these keys (same names and placeholders as
 *                 docs/copy-slots/home.md "This hour"): cycleTitle, cycleLine,
 *                 stepCurrencies, stepRoutes, stepAuditor, stepAuditorResult,
 *                 stepAnalyst, resultClean, resultSourceMissed, resultCheckFailed,
 *                 stripTitle, stripClean, stripMissed, stripFailed.
 *   A key that is empty or missing is not rendered. No word is written here.
 *   Classes are the hp-* classes (hp-sec, hp-row, hp-step, hp-strip, ...) from the home
 *   page's stylesheet; the caller's page must carry that CSS.
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

  function renderCycleBlock(containerEl, CL, copyBlock) {
    var K = mk(copyBlock || {}), has = K.has, t = K.t, LAST_N = 48;
    function wordT(parent, tag, cls, key, vars) {
      if (!has(key)) { return null; }
      var e = el(tag, cls, t(key, vars));
      parent.appendChild(e);
      return e;
    }
    if (!CL || !CL.steps) { return; }
    var st = CL.steps;
    var sec = el('section', 'hp-sec');
    var head = el('div', 'hp-sechead');
    wordT(head, 'h2', null, 'cycleTitle');
    wordT(head, 'span', ['muted', 'hp-small'], 'cycleLine');
    sec.appendChild(head);
    var row = el('div', 'hp-row');
    var list = el('div', ['hp-main', 'hp-list']);
    var hour = hhmm(st.hour_utc);
    var last = CL.cycles && CL.cycles.length ? CL.cycles[CL.cycles.length - 1] : null;
    var steps = [];
    if (st.currencies) { steps.push({ time: hour, key: 'stepCurrencies', vars: { collected: num(st.currencies.collected), of: num(st.currencies.of) } }); }
    if (st.routes) { steps.push({ time: hour, key: 'stepRoutes', vars: { priced: num(st.routes.priced), of: num(st.routes.of) } }); }
    if (st.auditor) {
      steps.push({ time: hhmm(st.auditor.sample_ts) || hour, key: 'stepAuditor', vars: { rebuilt: num(st.auditor.rebuilt) },
        vkey: 'stepAuditorResult', vvars: { matched: num(st.auditor.matched), rebuilt: num(st.auditor.rebuilt) } });
    }
    if (st.analyst != null && typeof st.analyst === 'object') { // null: the analyst has not run, so no row
      var av = {};
      Object.keys(st.analyst).forEach(function (k) { if (typeof st.analyst[k] !== 'object') { av[k] = st.analyst[k]; } });
      steps.push({ time: hour, key: 'stepAnalyst', vars: av });
    }
    if (last) {
      var rk = last.status === 'clean' ? 'resultClean' : last.status === 'source_missed' ? 'resultSourceMissed' : 'resultCheckFailed';
      steps.push({ time: hhmm(last.last_reading_utc) || hour, key: rk, vars: { sources: (last.reasons || []).join(', '), n: (last.reasons || []).length }, final: true });
    }
    steps.forEach(function (s) {
      if (!has(s.key)) { return; }
      var r = el('div', 'hp-step');
      r.appendChild(el('span', ['mono', 'muted', 'hp-time'], s.time));
      r.appendChild(el('span', s.final ? 'hp-sdot-amber' : 'hp-sdot'));
      var tx = el('span', s.final ? 'hp-steptext' : ['soft', 'hp-steptext'], t(s.key, s.vars));
      r.appendChild(tx);
      if (s.vkey && has(s.vkey)) { r.appendChild(el('span', 'mono', t(s.vkey, s.vvars))); }
      list.appendChild(r);
    });
    row.appendChild(list);

    var side = el('div', ['hp-side', 'hp-tight']);
    var cycles = (CL.cycles || []).slice(-LAST_N);
    wordT(side, 'span', ['muted', 'hp-small'], 'stripTitle', { n: cycles.length });
    var strip = el('div', 'hp-strip');
    cycles.forEach(function (c) {
      var s = el('span', c.status === 'check_failed' ? 'sf' : c.status === 'source_missed' ? 'sm' : 'sc');
      s.title = c.hour_utc.slice(0, 10) + ' ' + hhmm(c.hour_utc);
      strip.appendChild(s);
    });
    side.appendChild(strip);
    var leg = el('div', ['soft', 'hp-tiny', 'hp-legend']);
    [['stripClean', 'sc'], ['stripMissed', 'sm'], ['stripFailed', 'sf']].forEach(function (l) {
      if (!has(l[0])) { return; }
      var s = el('span');
      s.appendChild(el('i', ['hp-sw', 'k' + l[1]]));
      s.appendChild(document.createTextNode(' ' + t(l[0])));
      leg.appendChild(s);
    });
    side.appendChild(leg);
    row.appendChild(side);
    sec.appendChild(row);
    containerEl.appendChild(sec);
  }

  root.renderCycleBlock = renderCycleBlock;
  if (typeof module !== 'undefined' && module.exports) { module.exports = { renderCycleBlock: renderCycleBlock }; }
})(typeof window !== 'undefined' ? window : this);

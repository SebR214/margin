/* The machine room (SEB-427). Draws data/machine_room.json with the words of copy.json machineRoomPage. No numbers are typed here:
   every figure is read from the file, and a missing one shows as "none yet", never a guess. */
(function () {
  var $ = function (id) { return document.getElementById(id); };
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function fill(t, v) { return String(t || '').replace(/\{(\w+)\}/g, function (_, k) { return v && v[k] != null ? v[k] : ''; }); }
  var C, D;
  var money = function (n) { return n == null ? C.totals.noneYet : '$' + Number(n).toFixed(2); };
  function day(iso) { var d = new Date(iso + (iso.length === 10 ? 'T00:00:00Z' : '')); return d.getUTCDate() + ' ' + C.incidents.months[d.getUTCMonth()]; }
  function stamp(iso) { var d = new Date(iso); return day(iso) + ' ' + ('0' + d.getUTCHours()).slice(-2) + ':' + ('0' + d.getUTCMinutes()).slice(-2); }
  function table(el, cols, rows) {
    el.innerHTML = '<thead><tr>' + cols.map(function (c) { return '<th' + (c.n ? ' class="n"' : '') + '>' + esc(c.label) + '</th>'; }).join('') + '</tr></thead><tbody>' +
      rows.map(function (r) { return '<tr>' + cols.map(function (c, i) { return '<td' + (c.n ? ' class="n"' : '') + ' data-label="' + esc(c.label) + '">' + r[i] + '</td>'; }).join('') + '</tr>'; }).join('') + '</tbody>';
  }

  function totals() {
    var T = D.totals, L = C.totals;
    var since = T.days_since_last_merge == null ? L.sinceMergeNone : (T.days_since_last_merge === 0 ? L.sinceMergeToday : T.days_since_last_merge === 1 ? L.sinceMergeOne : fill(L.sinceMergeValue, { n: T.days_since_last_merge }));
    var tiles = [[money(T.spent_usd), L.spent], [T.merged, L.merged], [T.cost_per_merged_usd == null ? L.noneYet : money(T.cost_per_merged_usd), L.perMerged], [since, L.sinceMerge]];
    $('tiles').innerHTML = tiles.map(function (t) { return '<div class="tile"><div class="v">' + esc(t[0]) + '</div><div class="l">' + esc(t[1]) + '</div></div>'; }).join('');
    $('totalsNote').textContent = fill(L.note, { date: day(T.all_models_since), money: money(T.all_models_usd) });
  }

  function chart() {
    var W = D.weeks.slice().reverse(), S = C.scorecard;
    $('chartTitle').textContent = S.chartTitle;
    $('chartLegend').innerHTML = '<span><svg viewBox="0 0 10 10"><rect width="10" height="10" fill="#D3D0CB"/></svg>' + esc(S.chartTries) + '</span><span><svg viewBox="0 0 10 10"><rect width="10" height="10" fill="#817FCC"/></svg>' + esc(S.chartMerged) + '</span>';
    if (!W.length) { $('chartBox').textContent = S.none; return; }
    var max = Math.max.apply(null, W.map(function (w) { return w.attempts; }).concat([1]));
    var width = 720, h = 130, top = 16, base = h - 4, slot = Math.min(96, 680 / W.length), bw = Math.min(30, slot / 3);
    var x0 = 24;
    var y = function (v) { return base - (base - top) * v / max; };
    var out = '<svg viewBox="0 0 ' + width + ' ' + (h + 26) + '" role="img" aria-label="' + esc(S.chartLabel) + '">' +
      '<line x1="24" x2="704" y1="' + base + '" y2="' + base + '" stroke="#201E1D" stroke-width="1"/>' +
      '<text x="0" y="' + (top + 4) + '" font-size="12" fill="#7D7979">' + max + '</text>';
    W.forEach(function (w, i) {
      var cx = x0 + slot * i + slot / 2;
      [[w.attempts, '#D3D0CB', -bw - 1], [w.merged, '#817FCC', 1]].forEach(function (b) {
        var yy = y(b[0]);
        out += '<rect x="' + (cx + b[2]).toFixed(1) + '" y="' + yy.toFixed(1) + '" width="' + bw.toFixed(1) + '" height="' + Math.max(b[0] ? 1 : 0, base - yy).toFixed(1) + '" fill="' + b[1] + '"><title>' + esc(day(w.week_start) + ': ' + b[0]) + '</title></rect>';
        if (b[0]) out += '<text x="' + (cx + b[2] + bw / 2).toFixed(1) + '" y="' + (yy - 4).toFixed(1) + '" font-size="12" text-anchor="middle" fill="#201E1D">' + b[0] + '</text>';
      });
      out += '<text x="' + cx.toFixed(1) + '" y="' + (h + 14) + '" font-size="12" text-anchor="middle" fill="#7D7979">' + esc(day(w.week_start)) + '</text>';
    });
    $('chartBox').innerHTML = out + '</svg>';
  }

  function score() {
    var S = C.scorecard, K = S.cols;
    $('scoreHeading').textContent = S.heading; $('scoreIntro').textContent = S.intro;
    chart();
    table($('scoreTable'), [{ label: K.week }, { label: K.tries, n: 1 }, { label: K.opened, n: 1 }, { label: K.merged, n: 1 }, { label: K.share, n: 1 }, { label: K.cost, n: 1 }],
      D.weeks.map(function (w) { return [esc(day(w.week_start)), w.attempts, w.opened, w.merged, w.merged_share_pct == null ? esc(C.totals.noneYet) : w.merged_share_pct + '%', esc(money(w.cost_usd))]; }));
  }

  function when(s, over) {
    if (over) return over;
    var Sc = C.where.schedule, v = {};
    if (s.kind === 'every') v.minutes = s.minutes;
    if (s.kind === 'hourly') v.minutes = s.minutes.join(', ');
    if (s.times) v.times = s.times.join(', ');
    if (s.kind === 'weekly') v.day = C.where.days[s.day];
    if (s.kind === 'monthly') v.day = s.day;
    return fill(Sc[s.kind], v);
  }
  function where() {
    var K = C.where.cols, ST = C.where.status, anyRun = D.workflows.some(function (w) { return w.last_run; });
    $('whereHeading').textContent = C.where.heading; $('whereIntro').textContent = C.where.intro;
    var cols = [{ label: K.job }, { label: K.when }, { label: K.what }].concat(anyRun ? [{ label: K.last }] : []);
    table($('whereTable'), cols, D.workflows.map(function (w) {
      var j = C.where.jobs[w.file] || {}, r = w.last_run, row = [esc(j.name || w.name), esc(when(w.schedule, j.when)), esc(j.what || '')];
      if (anyRun) {
        var st = !r ? ST.none : (r.status !== 'completed' ? ST.running : (ST[r.conclusion] || r.conclusion));
        row.push(esc(st) + (r && r.run_utc ? ' (' + esc(stamp(r.run_utc)) + ' UTC)' : ''));
      }
      return row;
    }));
  }

  function incidents() {
    var I = C.incidents, L = I.labels;
    $('incHeading').textContent = I.heading; $('incIntro').textContent = I.intro;
    $('incList').innerHTML = I.items.map(function (it) {
      var g = (D.gaps || {})[it.id], v = g ? { hours: g.hours, from: stamp(g.last_before_utc), until: stamp(g.next_after_utc) } : {};
      var lasted = it.lasted == null ? I.notRecorded : (it.gapFromUtc && !g ? I.notRecorded : fill(it.lasted, v));
      var prs = (it.prs || []).map(function (n) { return '<a href="https://github.com/SebR214/margin/pull/' + n + '">' + n + '</a>'; }).join(', ');
      var rows = [[L.broke, esc(it.broke)], [L.lasted, esc(lasted)], [L.lost, esc(it.lost == null ? I.notRecorded : it.lost)], [L.fixed, esc(it.fixed)]];
      if (prs) rows.push([L.prs, prs]);
      return '<div class="inc"><div class="d">' + esc(it.date) + '</div><h3>' + esc(it.title) + '</h3><dl>' +
        rows.map(function (r) { return '<dt>' + esc(r[0]) + '</dt><dd>' + r[1] + '</dd>'; }).join('') + '</dl></div>';
    }).join('');
  }

  Promise.all([fetch('./copy.json').then(function (r) { return r.json(); }), fetch('./data/machine_room.json', { cache: 'no-store' }).then(function (r) { if (!r.ok) throw new Error('machine_room.json'); return r.json(); })])
    .then(function (a) {
      C = a[0].machineRoomPage; D = a[1];
      $('pageTitle').textContent = C.title; $('pageLede').textContent = C.lede;
      totals(); score(); where(); incidents();
      $('sources').innerHTML = D.files.map(function (f) { return '<a href="./' + esc(f) + '">' + esc(f) + '</a>'; }).join(' &middot; ');
    })
    .catch(function (e) { $('pageLede').textContent = String(e && e.message || e); });
})();

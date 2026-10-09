/* One finding (SEB-268), built to the approved reference. ?id= picks price_changes, weekend_penalty, volume_crossover or
 * sgd_php_never_cheapest. Reads data/findings.json and the finding's own file: data/findings_hours_<id>.csv (and
 * data/volume_crossover.json for the curve). Every figure is worked out here from those files; every word is a findingData key
 * in copy.json. Dates, numbers, money and route names are formatted here. Every chart answers hover and tap through js/tooltip.js. */
(function () {
  var MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  var MINUS = '−';
  var PLACE = { SGD: 'Singapore', AUD: 'Australia', NZD: 'New Zealand', USD: 'the United States' };
  var TO = { PHP: 'the Philippines', MXN: 'Mexico', INR: 'India', NGN: 'Nigeria' };
  var SYM = { SGD: 'S$', AUD: 'A$', NZD: 'NZ$', USD: 'US$' };
  var ORDER = ['price_changes', 'weekend_penalty', 'volume_crossover', 'sgd_php_never_cheapest', 'exchange_vs_p2p'];
  var NAV = [['navCountries', 'countries.html'], ['navRoutes', 'sending-money.html'], ['navSources', 'sources.html'], ['navFindings', 'findings.html'], ['navHowItWorks', 'how-it-works.html']];
  var C = {}, FIN = {}, DATA = {}, AS_OF = '';
  var id = 'price_changes', route = 'ALL', side = 'taker';

  function $(k) { return document.getElementById(k); }
  function T(k, v) { var s = C[k]; return typeof s === 'string' && s ? s.replace(/\{(\w+)\}/g, function (m, x) { return v && v[x] != null ? v[x] : ''; }) : ''; }
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function g(n) { return Math.round(n).toLocaleString('en-US'); }
  function dd(s) { return (+s.slice(8, 10)) + ' ' + MON[+s.slice(5, 7) - 1]; }
  function stampT(s) { return dd(s) + ', ' + s.slice(11, 16); }
  function sgd(v) { return (v < 0 ? MINUS : '') + 'S$' + Math.abs(v).toFixed(2); }
  function routeName(rid) { var p = rid.split('->'); return ((PLACE[p[0]] || p[0]) + ' to ' + (TO[p[1]] || p[1])).replace(/^the /, '').replace(/^./, function (c) { return c.toUpperCase(); }); }
  function approx(v) { return v >= 1e6 ? 'S$' + (v / 1e6).toFixed(1) + 'M' : 'S$' + g(v); }
  function title(k) { var f = FIN[k]; return T('title_' + k, { approx: f ? approx(f.headline.value) : '', n: f ? g(f.headline.value) : '' }); }
  // the claim of the exchange-versus-people finding names the persistent country with the largest median gap
  function claim(k) {
    if (k !== 'exchange_vs_p2p') { return T('claim_' + k); }
    var top = (FIN[k].evidence || []).filter(function (e) { return e.persists; })[0];
    return top ? T('claim_' + k, { country: top.country, gap: top.median_gap_pts.toFixed(1), share: Math.round(top.share_gap_2pts * 100) + '%' }) : T('claimNone_' + k);
  }
  function getJSON(u) { return fetch(u, { cache: 'no-store' }).then(function (r) { if (!r.ok) { throw new Error(u); } return r.json(); }); }
  function getCSV(u) {
    return fetch(u, { cache: 'no-store' }).then(function (r) { if (!r.ok) { throw new Error(u); } return r.text(); }).then(function (t) {
      var lines = t.trim().split(/\r?\n/), head = lines[0].split(',');
      return lines.slice(1).map(function (l) { var p = l.split(','), o = {}; head.forEach(function (h, i) { o[h] = p[i]; }); return o; });
    });
  }
  function niceTicks(lo, hi, n) {
    var span = hi - lo || 1, step = Math.pow(10, Math.floor(Math.log10(span / n)));
    var err = span / n / step; step *= err >= 5 ? 5 : err >= 2 ? 2 : 1;
    var out = [], v = Math.floor(lo / step) * step;
    for (; v < hi + step * 1e-6 || out.length < 2; v += step) { out.push(Math.abs(v) < step * 1e-6 ? 0 : +v.toFixed(6)); }
    if (out[out.length - 1] < hi) { out.push(+(out[out.length - 1] + step).toFixed(6)); }
    return out;
  }
  function tip(text, x, y) { if (window.siteTip) { window.siteTip.show(text, x, y); } }
  function untip() { if (window.siteTip) { window.siteTip.hide(); } }
  function frame(W, H, L, Tp, B, R) { return { W: W, H: H, L: L, T: Tp, B: B, R: R, pw: W - L - R, ph: H - Tp - B }; }
  function mount(head, note, extra) {
    $('chart').innerHTML = '<h2>' + esc(head) + '</h2><p class="note">' + esc(note) + '</p>' + (extra || '') + '<div class="chart" id="cv"><svg id="svg"></svg></div>';
    return $('cv');
  }
  // the pointer's place along the chart picks the day or the point, so a thin bar is easy to hit on a phone
  function bind(box, at) {
    var svg = box.querySelector('svg');
    var move = function (e) { var r = svg.getBoundingClientRect(); var hit = at((e.clientX - r.left) / r.width); if (hit) { tip(hit, e.clientX, e.clientY); } else { untip(); } };
    box.onpointermove = move; box.onpointerdown = move;
    box.onpointerleave = function (e) { if (e.pointerType !== 'touch') { untip(); at(null); } };
  }

  /* ---------------------------------------------------------------- the shell */
  function page() {
    var f = FIN[id];
    document.title = 'margin.wiki: ' + title(id);
    $('fnav').innerHTML = '<a class="back" href="./findings.html">' + esc(T('indexTitle')) + '</a><div class="pills">' +
      ORDER.map(function (k, i) { return '<a class="pill num" href="?id=' + k + '"' + (k === id ? ' aria-current="page"' : '') + ' data-id="' + k + '">0' + (i + 1) + '</a>'; }).join('') + '</div>';
    var big = id === 'volume_crossover' ? 'S$' + g(f.headline.value) : g(f.headline.value);
    $('hero').innerHTML = '<h1>' + esc(title(id)) + '</h1><p class="lead">' + esc(claim(id)) + '</p>' +
      '<p class="numline"><b class="num">' + big + '</b><span>' + esc(T('unit_' + f.headline.unit)) + '</span></p>' +
      '<p class="stamp num">' + esc(T('lastRecheck')) + ' ' + esc(stampT(f.last_recheck_utc)) + ' ' + esc(T('utc')) + '</p>';
    $('hero').style.display = 'flex'; $('hero').style.flexDirection = 'column';
    $('chart').innerHTML = '';
    CHARTS[id]();
    evidence(f);
    $('method').innerHTML = '<h2>' + esc(T('methodHeading')) + '</h2><p class="body">' + esc(T('method_' + id)) + '</p><p class="note">' + esc(T('methodFilesLabel')) + '</p>' +
      '<div class="files">' + f.method_files.map(function (p) { return '<a href="https://github.com/SebR214/margin/blob/main/' + p + '">' + esc(p) + '</a>'; }).join('') + '</div>';
    $('limits').innerHTML = '<h2>' + esc(T('limitsHeading')) + '</h2><p class="body">' + esc(T('limits_' + id)) + '</p>';
    var kb = f.size ? Math.round(f.size / 1024) + ' KB' : '';
    $('download').innerHTML = '<h2>' + esc(T('downloadHeading')) + '</h2><p class="note">' + esc(T('downloadNote')) + '</p>' +
      '<div class="rows"><div class="r"><a href="https://github.com/SebR214/margin/blob/main/' + f.download_file + '"><b>' + esc(f.download_file.replace('data/', '')) + '</b></a><span></span>' +
      '<span class="v num">' + g(f.hours_rows) + ' ' + esc(T('downloadRows')) + (kb ? '<small>' + kb + '</small>' : '') + '</span></div></div>';
    $('related').innerHTML = '<h2>' + esc(T('relatedHeading')) + '</h2><div class="rows">' + ORDER.filter(function (k) { return k !== id && FIN[k]; }).map(function (k) {
      var o = FIN[k], n = k === 'volume_crossover' ? approx(o.headline.value) : g(o.headline.value);
      var five = (o.evidence || []).filter(function (e) { return e.amount === 5000; })[0];
      if (k === 'sgd_php_never_cheapest' && five && typeof five.hours_priced === 'number') { n = T('short_value_' + k, { value: n, hours: g(five.hours_priced) }) || n; }
      var days = k === 'price_changes' ? (o.evidence || []).map(function (e) { return e.first_day; }).filter(Boolean).sort() : [];
      var unit = T('short_unit_' + k, { first: days.length ? dd(days[0]) : '' });
      return '<a class="r rel" href="?id=' + k + '" data-id="' + k + '"><span class="no num">0' + (ORDER.indexOf(k) + 1) + '</span><b>' + esc(title(k)) + '</b><span class="v num">' + esc(n) + (unit ? '<small>' + esc(unit) + '</small>' : '') + '</span></a>';
    }).join('') + '</div>';
    try { history.replaceState(null, '', location.pathname + '?id=' + id); } catch (e) { /* not available */ }
  }

  function evidence(f) {
    var L = function (k) { return esc(T('field_' + k)); };
    var rows = '';
    if (id === 'price_changes') {
      rows = f.evidence.slice().sort(function (a, b) { return b.changes - a.changes; }).map(function (e) {
        return '<div class="r"><b>' + esc(routeName(e.route)) + '</b><span class="m num">' + e.up + ' ' + L('up') + ', ' + e.down + ' ' + L('down') + ', ' + e.providers + ' ' + L('providers') +
          '. ' + L('first_day').replace(/^./, function (c) { return c.toUpperCase(); }) + ' ' + dd(e.first_day) + ', ' + L('last_day') + ' ' + dd(e.last_day) + '.</span>' +
          '<span class="v num">' + e.changes + '<small>' + L('changes') + '</small></span></div>';
      }).join('');
    } else if (id === 'weekend_penalty') {
      rows = f.evidence.slice().sort(function (a, b) { return b.weekend_up - a.weekend_up || b.saturdays_judged - a.saturdays_judged; }).map(function (e) {
        return '<div class="r"><b>' + esc(routeName(e.route)) + '</b><span class="m num">' + e.weekend_back + ' ' + L('weekend_back') + ', ' + e.saturdays_judged + ' ' + (e.saturdays_judged === 1 ? L('saturdays_judged_one') : L('saturdays_judged')) + '.</span>' +
          '<span class="v num">' + e.weekend_up + '<small>' + L('weekend_up') + '</small></span></div>';
      }).join('');
    } else if (id === 'volume_crossover') {
      rows = f.evidence.map(function (e) {
        return '<div class="r"><b>' + esc(T('side_' + e.side).replace(/^./, function (c) { return c.toUpperCase(); })) + '</b><span class="m num">' +
          sgd(e.cost_bps_at_floor / 2) + ' ' + L('cost_bps_at_floor') + ', ' + sgd(e.cost_bps_at_ceiling / 2) + ' ' + L('cost_bps_at_ceiling') + ', ' + e.fee_pct_at_crossover_ir + ' ' + L('fee_pct_at_crossover_ir') +
          ', ' + sgd(e.baseline_cost_bps_median / 2) + ' ' + L('baseline_cost_bps_median') + ', ' + g(e.n_samples) + ' ' + L('n_samples') + '.</span>' +
          '<span class="v num">S$' + g(e.monthly_volume_sgd) + '<small>' + L('monthly_volume_sgd') + '</small></span></div>';
      }).join('');
    } else if (id === 'exchange_vs_p2p') {
      rows = f.evidence.map(function (e) {
        return '<div class="r"><b>' + esc(e.country) + '</b><span class="m num">' + Math.round(e.share_gap_2pts * 100) + '% ' + L('share_gap_2pts') + ', ' + g(e.hours_checked) + ' ' + (e.hours_checked === 1 ? L('hour_checked') : L('hours_checked')) +
          ', ' + L('since') + ' ' + dd(e.first_day) + ', ' + esc(e.exchanges.map(function (x) { return x.replace(/^(.*) \(.*\)$/, '$1'); }).filter(function (x, i, a) { return a.indexOf(x) === i; }).join(', ')) + ' ' + L('against') + ' ' + esc(e.boards.map(function (b) { return T('board_' + b); }).join(' ' + T('and') + ' ')) +
          '. ' + (e.persists ? L('persists') : L('not_persist')) + '</span>' +
          '<span class="v num">' + (e.median_gap_pts > 0 ? '+' : e.median_gap_pts < 0 ? MINUS : '') + Math.abs(e.median_gap_pts).toFixed(1) + '<small>' + L('median_gap_pts') + '</small></span></div>';
      }).join('');
    } else if (id === 'sgd_php_never_cheapest') {
      rows = f.evidence.map(function (e) {
        return '<div class="r"><b class="num">S$' + g(e.amount) + '</b><span class="m num">' + g(e.hours_priced) + ' ' + L('hours_priced') + '.</span>' +
          '<span class="v num">' + e.hours_stablecoin_cheapest + '<small>' + L('hours_stablecoin_cheapest') + '</small></span></div>';
      }).join('');
    }
    $('evidence').innerHTML = '<h2>' + esc(T('evidenceHeading')) + '</h2><p class="note">' + esc(T('evidenceBasis_' + id)) + '</p><div class="rows">' + rows + '</div>';
  }

  /* ---------------------------------------------------------------- charts: every one answers hover and tap */
  var CHARTS = {};

  CHARTS.price_changes = function () {
    var rows = DATA.price_changes || [];
    var byRoute = { ALL: {} };
    rows.forEach(function (r) {
      var day = r.ts_utc.slice(0, 10), mv = parseFloat(r.move_pct), rid = r.corridor;
      [byRoute.ALL, (byRoute[rid] = byRoute[rid] || {})].forEach(function (S) {
        var o = S[day] = S[day] || [0, 0, []];
        if (mv > 0) { o[0]++; } else if (mv < 0) { o[1]++; }
        if (o[2].indexOf(r.provider) < 0) { o[2].push(r.provider); }
      });
    });
    Object.keys(byRoute).forEach(function (k) { Object.keys(byRoute[k]).forEach(function (d) { byRoute[k][d][2].sort(); }); });
    var routes = Object.keys(byRoute).filter(function (k) { return k !== 'ALL'; }).sort(function (a, b) { return routeName(a).localeCompare(routeName(b)); });
    var pills = '<div class="pills scroll" id="rp">' + ['ALL'].concat(routes).map(function (r) {
      return '<button class="pill" type="button" data-route="' + esc(r) + '" aria-pressed="' + (r === route) + '">' + esc(r === 'ALL' ? T('chartAllRoutes') : routeName(r)) + '</button>';
    }).join('') + '</div>';
    var box = mount(T('chart_price_changes_title'), T('chart_price_changes_note'), pills);
    var all = Object.keys(byRoute.ALL).sort(), d0 = Date.parse(all[0]), d1 = Date.parse(all[all.length - 1]), n = Math.round((d1 - d0) / 864e5) + 1;
    var days = []; for (var i = 0; i < n; i++) { days.push(new Date(d0 + i * 864e5).toISOString().slice(0, 10)); }
    var S = byRoute[route] || {}, vals = days.map(function (d) { return S[d] || [0, 0, []]; });
    var W = Math.max(320, box.clientWidth), H = W < 560 ? 240 : 300, F = frame(W, H, 44, 10, 26, 0);
    var mx = Math.max.apply(null, vals.map(function (v) { return Math.max(v[0], v[1]); }).concat([1])), ticks = niceTicks(0, mx, 2), top = ticks[ticks.length - 1];
    var X = function (k) { return F.L + (k + 0.5) / n * F.pw; }, mid = F.T + F.ph / 2, Y = function (v) { return v / top * F.ph / 2; };
    var bw = Math.max(1, F.pw / n - (W < 560 ? 1 : 2)), s = '';
    ticks.forEach(function (t) {
      if (!t) { return; }
      [1, -1].forEach(function (sg) { s += '<line x1="' + F.L + '" x2="' + W + '" y1="' + (mid - sg * Y(t)) + '" y2="' + (mid - sg * Y(t)) + '" stroke="var(--color-neutral-200)"/><text class="ax" x="' + (F.L - 8) + '" y="' + (mid - sg * Y(t) + 4) + '" text-anchor="end">' + (sg > 0 ? '' : MINUS) + t + '</text>'; });
    });
    s += '<line x1="' + F.L + '" x2="' + W + '" y1="' + mid + '" y2="' + mid + '" stroke="var(--color-ink)"/><text class="ax z" x="' + (F.L - 8) + '" y="' + (mid + 4) + '" text-anchor="end">0</text>';
    vals.forEach(function (v, k) {
      if (v[0]) { s += '<rect x="' + (X(k) - bw / 2) + '" y="' + (mid - Y(v[0])) + '" width="' + bw + '" height="' + Y(v[0]) + '" fill="var(--data-600)" rx="1"/>'; }
      if (v[1]) { s += '<rect x="' + (X(k) - bw / 2) + '" y="' + (mid + 1) + '" width="' + bw + '" height="' + Y(v[1]) + '" fill="var(--color-neutral-900)" rx="1"/>'; }
    });
    days.forEach(function (d, k) { if (new Date(d).getUTCDay() === 1 && (W >= 560 || Math.round(k / 7) % 2 === 0)) { s += '<text class="ax" x="' + X(k) + '" y="' + (H - 6) + '" text-anchor="middle">' + dd(d) + '</text>'; } });
    s += '<line id="cr" y1="' + F.T + '" y2="' + (F.T + F.ph) + '" stroke="var(--color-ink)" stroke-dasharray="3 3" visibility="hidden"/>';
    var svg = box.querySelector('svg'); svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H); svg.setAttribute('role', 'img'); svg.innerHTML = s;
    bind(box, function (fx) {
      var cr = svg.querySelector('#cr');
      if (fx == null) { cr.setAttribute('visibility', 'hidden'); return null; }
      var k = Math.max(0, Math.min(n - 1, Math.floor((fx * W - F.L) / F.pw * n))), v = vals[k];
      cr.setAttribute('x1', X(k)); cr.setAttribute('x2', X(k)); cr.setAttribute('visibility', 'visible');
      return dd(days[k]) + ': ' + v[0] + ' ' + T('field_up') + ', ' + v[1] + ' ' + T('field_down') + (v[2].length ? '\n' + v[2].join(', ') : '');
    });
  };

  CHARTS.exchange_vs_p2p = function () {
    var rows = DATA.exchange_vs_p2p || [], ev = FIN.exchange_vs_p2p.evidence, names = {}, pers = {};
    ev.forEach(function (e) { names[e.ccy] = e.country; pers[e.ccy] = e.persists; });
    var byDay = {}, ccys = {};
    rows.forEach(function (r) {
      var d = r.hour_utc.slice(0, 10), o = byDay[d] = byDay[d] || {};
      (o[r.ccy] = o[r.ccy] || []).push(parseFloat(r.gap_pts)); ccys[r.ccy] = 1;
    });
    var days = Object.keys(byDay).sort(), series = {};
    Object.keys(ccys).forEach(function (c) {
      series[c] = days.map(function (d) { var a = (byDay[d][c] || []).slice().sort(function (x, y) { return x - y; }); return a.length ? a[Math.floor(a.length / 2)] : null; });
    });
    var box = mount(T('chart_exchange_vs_p2p_title'), T('chart_exchange_vs_p2p_note'));
    var all = []; Object.keys(series).forEach(function (c) { series[c].forEach(function (v) { if (v != null) { all.push(v); } }); });
    var lo = Math.min.apply(null, all.concat([0])), hi = Math.max.apply(null, all.concat([2]));
    var W = Math.max(320, box.clientWidth), H = W < 560 ? 240 : 300, F = frame(W, H, 44, 10, 26, 8), n = days.length;
    var ticks = niceTicks(lo, hi, 4), y0 = ticks[0], y1 = ticks[ticks.length - 1];
    var X = function (k) { return F.L + (n > 1 ? k / (n - 1) : 0.5) * F.pw; }, Y = function (v) { return F.T + F.ph - (v - y0) / (y1 - y0) * F.ph; };
    var s = '';
    ticks.forEach(function (t) { s += '<line class="gl' + (t === 0 ? ' z' : '') + '" x1="' + F.L + '" x2="' + (W - F.R) + '" y1="' + Y(t) + '" y2="' + Y(t) + '" stroke="' + (t === 0 ? 'var(--color-ink)' : 'var(--color-neutral-200)') + '"/><text class="ax' + (t === 0 ? ' z' : '') + '" x="' + (F.L - 8) + '" y="' + (Y(t) + 4) + '" text-anchor="end">' + (t > 0 ? '+' : t < 0 ? MINUS : '') + Math.abs(t) + '</text>'; });
    s += '<line x1="' + F.L + '" x2="' + (W - F.R) + '" y1="' + Y(2) + '" y2="' + Y(2) + '" stroke="var(--color-neutral-600)" stroke-dasharray="4 3"/>';
    Object.keys(series).sort(function (a, b) { return (pers[a] ? 1 : 0) - (pers[b] ? 1 : 0); }).forEach(function (c) {
      var d = '', pen = false;
      series[c].forEach(function (v, k) { if (v == null) { pen = false; return; } d += (pen ? 'L' : 'M') + X(k).toFixed(1) + ' ' + Y(v).toFixed(1); pen = true; });
      s += '<path d="' + d + '" fill="none" stroke="' + (pers[c] ? 'var(--data-700)' : 'var(--color-neutral-400)') + '" stroke-width="' + (pers[c] ? 2 : 1.2) + '"/>';
    });
    var step = Math.max(1, Math.round(n / 5));
    days.forEach(function (d, k) { if (k % step === 0 && n - 1 - k > 2) { s += '<text class="ax" x="' + X(k) + '" y="' + (H - 6) + '" text-anchor="middle">' + dd(d) + '</text>'; } });
    s += '<text class="ax" x="' + (W - F.R) + '" y="' + (H - 6) + '" text-anchor="end">' + dd(days[n - 1]) + '</text><line id="cr" y1="' + F.T + '" y2="' + (F.T + F.ph) + '" stroke="var(--color-ink)" stroke-dasharray="3 3" visibility="hidden"/>';
    var svg = box.querySelector('svg'); svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H); svg.setAttribute('role', 'img'); svg.innerHTML = s;
    bind(box, function (fx) {
      var cr = svg.querySelector('#cr');
      if (fx == null) { cr.setAttribute('visibility', 'hidden'); return null; }
      var k = Math.max(0, Math.min(n - 1, Math.round((fx * W - F.L) / F.pw * (n - 1))));
      cr.setAttribute('x1', X(k)); cr.setAttribute('x2', X(k)); cr.setAttribute('visibility', 'visible');
      var list = Object.keys(series).filter(function (c) { return series[c][k] != null; }).sort(function (a, b) { return series[b][k] - series[a][k]; });
      return dd(days[k]) + '\n' + list.slice(0, 6).map(function (c) { var v = series[c][k]; return names[c] + ': ' + (v > 0 ? '+' : v < 0 ? MINUS : '') + Math.abs(v).toFixed(1); }).join('\n') + (list.length > 7 ? '\n' + T('tipMoreCountries', { n: list.length - 6 }) : list.length === 7 ? '\n' + T('tipMoreCountriesOne') : '');
    });
  };

  CHARTS.weekend_penalty = function () {
    var box = mount(T('chart_weekend_penalty_title'), T('chart_weekend_penalty_note'));
    var rows = (DATA.weekend_penalty || []).filter(function (r) { return r.kind === 'weekend_up'; }), wk = {};
    rows.forEach(function (r) { var d = r.ts_utc.slice(0, 10); (wk[d] = wk[d] || []).push([r.corridor, +r.size, r.provider, parseFloat(r.move_pct)]); });
    var keys = Object.keys(wk).sort(), first = keys[0], lastData = FIN.weekend_penalty.headline.as_of_utc.slice(0, 10), sats = [];
    // every Saturday from the first counted one to the last one whose Tuesday is already in our data
    for (var t = Date.parse(first); t + 3 * 864e5 <= Date.parse(lastData); t += 7 * 864e5) { sats.push(new Date(t).toISOString().slice(0, 10)); }
    var vals = sats.map(function (d) { return wk[d] || []; });
    var W = Math.max(320, box.clientWidth), H = W < 560 ? 220 : 260, F = frame(W, H, 36, 14, 26, 0);
    var mx = Math.max.apply(null, vals.map(function (v) { return v.length; }).concat([1])), ticks = niceTicks(0, mx, 3), top = ticks[ticks.length - 1];
    var n = sats.length, slot = F.pw / n, bw = Math.min(56, slot * 0.6), X = function (k) { return F.L + (k + 0.5) * slot; }, Y = function (v) { return F.T + F.ph - v / top * F.ph; }, s = '';
    ticks.forEach(function (tk) { s += '<line x1="' + F.L + '" x2="' + W + '" y1="' + Y(tk) + '" y2="' + Y(tk) + '" stroke="' + (tk ? 'var(--color-neutral-200)' : 'var(--color-ink)') + '"/><text class="ax' + (tk ? '' : ' z') + '" x="' + (F.L - 8) + '" y="' + (Y(tk) + 4) + '" text-anchor="end">' + tk + '</text>'; });
    vals.forEach(function (v, k) {
      if (v.length) { s += '<rect x="' + (X(k) - bw / 2) + '" y="' + Y(v.length) + '" width="' + bw + '" height="' + (Y(0) - Y(v.length)) + '" fill="var(--data-600)" rx="2"/><text class="ax z" x="' + X(k) + '" y="' + (Y(v.length) - 6) + '" text-anchor="middle">' + v.length + '</text>'; }
      else { s += '<text class="ax" x="' + X(k) + '" y="' + (Y(0) - 6) + '" text-anchor="middle">0</text>'; }
      if (slot >= 52 || k % 2 === 0) { s += '<text class="ax" x="' + X(k) + '" y="' + (H - 6) + '" text-anchor="middle">' + dd(sats[k]) + '</text>'; }
    });
    var svg = box.querySelector('svg'); svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H); svg.innerHTML = s;
    bind(box, function (fx) {
      if (fx == null) { return null; }
      var k = Math.max(0, Math.min(n - 1, Math.floor((fx * W - F.L) / slot))), v = vals[k];
      return dd(sats[k]) + ': ' + v.length + ' ' + T('field_weekend_up') + v.slice(0, 8).map(function (r) {
        return '\n' + routeName(r[0]) + ', ' + r[2] + ', ' + (SYM[r[0].slice(0, 3)] || '') + g(r[1]) + ', +' + r[3].toFixed(2) + '%';
      }).join('') + (v.length > 8 ? '\n' + T('tipMore', { n: v.length - 8 }) : '');
    });
  };

  CHARTS.volume_crossover = function () {
    var V = DATA.volume_crossover;
    var pills = '<div class="pills" id="sp">' + ['taker', 'maker'].map(function (k) {
      return '<button class="pill" type="button" data-side="' + k + '" aria-pressed="' + (k === side) + '">' + esc(T('side_' + k).replace(/^./, function (c) { return c.toUpperCase(); })) + '</button>';
    }).join('') + '</div>';
    var box = mount(T('chart_volume_crossover_title'), T('chart_volume_crossover_note'), pills);
    var cv = V[side].curve.filter(function (p, k, a) { return k === 0 || p.monthly_volume_sgd !== a[k - 1].monthly_volume_sgd; });
    var app = V.baseline_cost_bps_median / 2, pts = cv.map(function (p) { return [p.monthly_volume_sgd, p.cost_bps / 2, p.fee_on_pct_ir]; });
    var W = Math.max(320, box.clientWidth), H = W < 560 ? 240 : 300, F = frame(W, H, 52, 12, 30, 8);
    var lx0 = Math.log10(pts[0][0]), lx1 = Math.log10(pts[pts.length - 1][0]);
    var X = function (v) { return F.L + (Math.log10(v) - lx0) / (lx1 - lx0) * F.pw; };
    var ys = niceTicks(0, Math.max.apply(null, pts.map(function (p) { return p[1]; })) * 1.05, 4), top = ys[ys.length - 1], Y = function (v) { return F.T + F.ph - v / top * F.ph; }, s = '';
    ys.forEach(function (tk) { s += '<line x1="' + F.L + '" x2="' + (W - F.R) + '" y1="' + Y(tk) + '" y2="' + Y(tk) + '" stroke="' + (tk ? 'var(--color-neutral-200)' : 'var(--color-ink)') + '"/><text class="ax' + (tk ? '' : ' z') + '" x="' + (F.L - 8) + '" y="' + (Y(tk) + 4) + '" text-anchor="end">' + (tk ? 'S$' + tk : '0') + '</text>'; });
    [1e5, 1e6, 1e7, 1e8, 1e9].forEach(function (v) {
      if (v >= pts[0][0] && v <= pts[pts.length - 1][0]) { s += '<text class="ax" x="' + X(v) + '" y="' + (H - 8) + '" text-anchor="middle">S$' + (v >= 1e9 ? v / 1e9 + 'B' : v >= 1e6 ? v / 1e6 + 'M' : v / 1e3 + 'k') + '</text>'; }
    });
    s += '<line x1="' + F.L + '" x2="' + (W - F.R) + '" y1="' + Y(app) + '" y2="' + Y(app) + '" stroke="var(--color-neutral-600)" stroke-dasharray="5 4"/><text class="ax" x="' + (W - F.R) + '" y="' + (Y(app) - 6) + '" text-anchor="end">' + esc(T('chartCheapestApp', { cost: sgd(app) })) + '</text>';
    s += '<path d="' + pts.map(function (p, k) { return (k ? 'L' : 'M') + X(p[0]).toFixed(1) + ' ' + Y(p[1]).toFixed(1); }).join('') + '" fill="none" stroke="var(--data-600)" stroke-width="2"/>';
    pts.forEach(function (p) { s += '<circle cx="' + X(p[0]) + '" cy="' + Y(p[1]) + '" r="3" fill="var(--data-600)"/>'; });
    var cx = V[side].monthly_volume_sgd;
    s += '<circle cx="' + X(cx) + '" cy="' + Y(app) + '" r="6" fill="none" stroke="var(--color-neutral-900)" stroke-width="2"/><text class="ax z" x="' + (X(cx) + 10) + '" y="' + (Y(app) + 18) + '">' + esc(T('tipMonth', { amount: 'S$' + g(cx) })) + '</text>';
    s += '<line id="cr" y1="' + F.T + '" y2="' + (F.T + F.ph) + '" stroke="var(--color-ink)" stroke-dasharray="3 3" visibility="hidden"/>';
    var svg = box.querySelector('svg'); svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H); svg.innerHTML = s;
    bind(box, function (fx) {
      var cr = svg.querySelector('#cr');
      if (fx == null) { cr.setAttribute('visibility', 'hidden'); return null; }
      var x = fx * W, best = pts[0];
      pts.forEach(function (p) { if (Math.abs(X(p[0]) - x) < Math.abs(X(best[0]) - x)) { best = p; } });
      cr.setAttribute('x1', X(best[0])); cr.setAttribute('x2', X(best[0])); cr.setAttribute('visibility', 'visible');
      return T('tipMonth', { amount: 'S$' + g(best[0]) }) + ': ' + best[2] + ' ' + T('field_fee_pct_at_crossover_ir') + '\n' + T('tipStable', { cost: sgd(best[1]), app: sgd(app) });
    });
  };

  CHARTS.sgd_php_never_cheapest = function () {
    var box = mount(T('chart_sgd_php_never_cheapest_title'), T('chart_sgd_php_never_cheapest_note'));
    var R = (DATA.sgd_php_never_cheapest || []).filter(function (r) { return +r.amount_sgd === 5000; }).map(function (r) {
      var h = r.hour_utc.slice(0, 13);
      return [Date.parse(h + ':00:00Z'), (parseFloat(r.stable_cost_pct) - parseFloat(r.app_cost_pct)) * 50, r.cheapest_app, r.stable_cheaper === 'true', h];
    });
    if (!R.length) { return; }
    var W = Math.max(320, box.clientWidth), H = W < 560 ? 240 : 300, F = frame(W, H, 52, 10, 26, 6);
    var t0 = R[0][0], t1 = R[R.length - 1][0], X = function (t) { return F.L + (t - t0) / (t1 - t0) * F.pw; };
    var ys = niceTicks(Math.min.apply(null, [0].concat(R.map(function (r) { return r[1]; }))), Math.max.apply(null, R.map(function (r) { return r[1]; })), 4), lo = ys[0], top = ys[ys.length - 1];
    var Y = function (v) { return F.T + F.ph - (v - lo) / (top - lo) * F.ph; }, s = '';
    ys.forEach(function (tk) { s += '<line x1="' + F.L + '" x2="' + (W - F.R) + '" y1="' + Y(tk) + '" y2="' + Y(tk) + '" stroke="' + (tk ? 'var(--color-neutral-200)' : 'var(--color-ink)') + '"/><text class="ax' + (tk ? '' : ' z') + '" x="' + (F.L - 8) + '" y="' + (Y(tk) + 4) + '" text-anchor="end">' + (tk ? (tk > 0 ? '+' : MINUS) + 'S$' + Math.abs(tk) : '0') + '</text>'; });
    var d = '', prev = null;
    R.forEach(function (r) { d += (prev && r[0] - prev < 6 * 36e5 ? 'L' : 'M') + X(r[0]).toFixed(1) + ' ' + Y(r[1]).toFixed(1); prev = r[0]; });
    s += '<path d="' + d + '" fill="none" stroke="var(--color-neutral-700)" stroke-width="1.2"/>';
    R.filter(function (r) { return r[3]; }).forEach(function (r) { s += '<circle cx="' + X(r[0]) + '" cy="' + Y(r[1]) + '" r="5" fill="var(--data-600)" stroke="var(--color-bg)" stroke-width="1.5"/>'; });
    for (var t = t0; t <= t1; t += 864e5) {
      var dt = new Date(t);
      if (dt.getUTCDay() === 1 && (W >= 560 || Math.round((t - t0) / 864e5 / 7) % 2 === 0)) { s += '<text class="ax" x="' + X(t) + '" y="' + (H - 6) + '" text-anchor="middle">' + dd(dt.toISOString()) + '</text>'; }
    }
    s += '<line id="cr" y1="' + F.T + '" y2="' + (F.T + F.ph) + '" stroke="var(--color-ink)" stroke-dasharray="3 3" visibility="hidden"/><circle id="cd" r="4" fill="var(--color-ink)" visibility="hidden"/>';
    var svg = box.querySelector('svg'); svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H); svg.innerHTML = s;
    bind(box, function (fx) {
      var cr = svg.querySelector('#cr'), cd = svg.querySelector('#cd');
      if (fx == null) { cr.setAttribute('visibility', 'hidden'); cd.setAttribute('visibility', 'hidden'); return null; }
      var tt = t0 + (fx * W - F.L) / F.pw * (t1 - t0), lo_ = 0, hi = R.length - 1;
      while (hi - lo_ > 1) { var m = (lo_ + hi) >> 1; if (R[m][0] < tt) { lo_ = m; } else { hi = m; } }
      var r = Math.abs(R[lo_][0] - tt) < Math.abs(R[hi][0] - tt) ? R[lo_] : R[hi];
      cr.setAttribute('x1', X(r[0])); cr.setAttribute('x2', X(r[0])); cr.setAttribute('visibility', 'visible');
      cd.setAttribute('cx', X(r[0])); cd.setAttribute('cy', Y(r[1])); cd.setAttribute('visibility', 'visible');
      return dd(r[4]) + ', ' + r[4].slice(11, 13) + ':00 ' + T('utc') + ': ' + (r[1] > 0 ? T('tipNcMore', { amount: sgd(r[1]), app: r[2] }) : T('tipNcLess', { amount: sgd(-r[1]), app: r[2] })) +
        '\n' + T('tipNcPct', { pct: (r[1] / 50 > 0 ? '+' : MINUS) + Math.abs(r[1] / 50).toFixed(2) });
    });
  };

  /* ---------------------------------------------------------------- loading */
  function loadFor(k) {
    if (k === 'price_changes' || k === 'weekend_penalty' || k === 'sgd_php_never_cheapest' || k === 'exchange_vs_p2p') {
      return DATA[k] ? Promise.resolve() : getCSV('data/findings_hours_' + k + '.csv').then(function (r) { DATA[k] = r; });
    }
    return DATA[k] ? Promise.resolve() : getJSON('data/volume_crossover.json').then(function (r) { DATA[k] = r; });
  }
  function show(k) {
    id = k; untip();
    loadFor(k).then(page).catch(function () { page(); });
  }

  document.addEventListener('click', function (e) {
    var a = e.target.closest('[data-id]');
    if (a) { e.preventDefault(); show(a.dataset.id); window.scrollTo({ top: 0 }); return; }
    var r = e.target.closest('[data-route]');
    if (r) { route = r.dataset.route; CHARTS.price_changes(); return; }
    var sd = e.target.closest('[data-side]');
    if (sd) { side = sd.dataset.side; CHARTS.volume_crossover(); }
  });
  var rt; window.addEventListener('resize', function () { clearTimeout(rt); rt = setTimeout(function () { if (CHARTS[id] && DATA[id]) { CHARTS[id](); } }, 150); });

  Promise.all([getJSON('copy.json').catch(function () { return {}; }), getJSON('data/findings.json').catch(function () { return null; })]).then(function (r) {
    C = (r[0] && r[0].findingData) || {};
    var nav = $('nav');
    NAV.forEach(function (x) { var t = C[x[0]]; if (!t) { return; } var a = document.createElement('a'); a.textContent = t; a.href = './' + x[1]; nav.appendChild(a); });
    ((r[1] && r[1].findings) || []).forEach(function (f) { FIN[f.id] = f; });
    AS_OF = (r[1] && r[1].as_of_utc) || '';
    var want = new URLSearchParams(location.search).get('id');
    if (!want || ORDER.indexOf(want) < 0 || !FIN[want]) {
      $('nf').hidden = false;
      $('nf').innerHTML = esc(T('notFound')) + ' <a href="./findings.html">' + esc(T('notFoundLink')) + '</a>';
      return;
    }
    show(want);
  });
})();

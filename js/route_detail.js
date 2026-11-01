/* The route detail under the Routes table (21 Oct page, brought back 22 Oct under PR 616's table).
 * Picked route and amount: the "this hour" bars, the stablecoin's steps and the day-by-day chart with its
 * 1w / 1m / All bar. Reads data/routes_hourly.json, data/routes_breakdown.json, data/routes_summary.json.
 * Renders into #smDetail, which js/route.js writes under its table and announces with a "routes:render" event.
 * A tap on a table row (data-r, data-amt) picks that route here. Every word comes from copy.json routeData. */
(function () {

  var DAY = 86400, HOUR = 3600;
  var MINUS = "−";
  var MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  var MONL = ["January", "February", "March", "April", "May", "June", "July",
    "August", "September", "October", "November", "December"];
  // every route, and the comparable ones; routes measured against the official rate stay out of the charts and their button shows the "left out" text
  var ALL = [], ORDER = [];
  // the dollar gap in each route's destination this hour (data/index_latest.json), for the overview's order and its small line
  var GAP = {};
  function setGaps(idx) {
    GAP = {};
    ((idx && idx.countries) || []).forEach(function (c) { if (c.index_pct != null) GAP[c.ccy] = c.index_pct; });
  }
  function gapOf(id) { var v = GAP[String(id).split("->")[1]]; return v == null ? null : v; }
  function setRoutes(sum) {
    ALL = sum.routes.map(function (r) { return r.id; });
    // every route gets its detail (24 Oct). The routes table above compares them all against the best app, so a route
    // where the stablecoin costs less than nothing against the official rate (Argentina, Nigeria, India) shows its
    // numbers too: the headline says it in words and the chart's dark line is where the best app sits.
    ORDER = ALL.slice();
    // biggest dollar gap first (28 Oct, Seb): the page reads from "the stablecoin wins" down to "the app wins"
    ORDER.sort(function (a, b) { var x = gapOf(a), y = gapOf(b); return (y == null ? -1e9 : y) - (x == null ? -1e9 : x); });
  }
  // hours whose blockchain fee could not be read: not priced, and shown as gaps (1 Nov, Seb), from routes_breakdown.json
  function gasMissing(id) {
    var out = {};
    ((BRK && BRK.gaps) || []).forEach(function (g) {
      if (g.reason === "not_read_this_hour" && g.route === id) (g.hours_utc || []).forEach(function (h) { out[Math.round(Date.parse(h) / 36e5)] = true; });
    });
    return out;
  }
  function plainRoute(s) { return String(s || "").replace(/^the /i, "").replace(/^./, function (c) { return c.toUpperCase(); }); }

  var COPY = {};
  function box() { return document.getElementById("smDetail"); }
  var READY = false;
  var HOURLY = null, BRK = null;
  var COL = {}, BCOL = {};
  var S = { route: null, amount: null, period: "all" };   // period: the chart range, "all", "1m" or "1w" (21 Oct)
  var TIP_WHEN = "";
  var chart = null;

  // ---------------------------------------------------------------- helpers
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  // A copy slot filled with its placeholders; "" when the writer has not filled it.
  var ALIAS = { chartTip: "weekChartTip", chartAria: "weekChartAria", headline: "detailHeadline", headlineAppBack: "detailHeadlineAppBack",
    headlineBothBack: "detailHeadlineBothBack", headlineStableBack: "detailHeadlineStableBack" };
  function txt(key, vals) {
    key = ALIAS[key] || key;
    var s = COPY[key];
    if (!s) return "";
    return String(s).replace(/\{(\w+)\}/g, function (m, k) { return vals && vals[k] != null ? vals[k] : ""; });
  }
  function w(key, vals, tag, cls) {
    var s = txt(key, vals);
    return s ? "<" + tag + (cls ? ' class="' + cls + '"' : "") + ">" + esc(s) + "</" + tag + ">" : "";
  }
  function getJSON(url) {
    return fetch(url, { cache: "no-store" }).then(function (r) {
      if (!r.ok) throw new Error(String(r.status));
      return r.json();
    });
  }
  function maybeJSON(url) { return getJSON(url).catch(function () { return null; }); }

  function num(v, d) { return v.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d }); }
  function whole(v) { return v == null ? "" : num(Math.round(v), 0); }
  // A signed money amount in the route's own sending currency: whole once it
  // reaches 100, two decimals below that -- same rounding the reference used.
  function money(v, sym) {
    if (v == null) return "";
    var a = Math.abs(v), s = a >= 100 ? whole(a) : num(a, 2);
    return (v < 0 ? MINUS : "") + sym + s;
  }
  function pctPlain(v) { return v == null ? "" : (v < 0 ? MINUS : "") + num(Math.abs(v), 2) + "%"; }
  function median(a) {
    var s = a.slice().sort(function (x, y) { return x - y; }), n = s.length;
    return n % 2 ? s[(n - 1) / 2] : (s[n / 2 - 1] + s[n / 2]) / 2;
  }
  function dayKey(iso) { return iso.slice(0, 10); }
  function dayShort(iso) {
    var d = new Date(iso);
    return d.getUTCDate() + " " + MON[d.getUTCMonth()];
  }
  function dayLong(iso) {
    var d = new Date(iso);
    return d.getUTCDate() + " " + MONL[d.getUTCMonth()];
  }
  function clock(iso) {
    return String(new Date(iso).getUTCHours()).padStart(2, "0") + ":00";
  }
  // "USDC:ArbitrumOne" -> "USDC on Arbitrum One": a stored path id made
  // readable, no words added.
  function pathName(id) {
    if (id === "USDT" && txt("pathBase")) return txt("pathBase"); // USDT is not a reader word; the words come from copy.json
    return id ? txt("pathOther") : ""; // no coin or network names in reader text
  }
  function routeKey(id) { return id.replace("->", "-"); }
  function routeObj(id) { return HOURLY.routes.filter(function (r) { return r.id === id; })[0]; }
  function amountObj(r, amt) { return r && r.amounts.filter(function (a) { return a.amount === amt; })[0]; }

  // ---------------------------------------------------------------- the computed block for one route+amount
  // Everything here is read fresh from data/routes_hourly.json and
  // data/routes_breakdown.json on every render -- the win counts, the 30-day
  // range and the daily line are never carried forward from an earlier call.
  function computeA(routeId, amount) {
    var r = routeObj(routeId), a = amountObj(r, amount), hrs = a.hours;
    var last = hrs[hrs.length - 1], first = hrs[0][COL.hour_utc];
    var n = hrs.length, wins = 0, i;
    for (i = 0; i < n; i++) if (hrs[i][COL.stable_cheaper] === true) wins++;
    var t = last[COL.hour_utc];
    var sc = last[COL.stable_cost], sp = last[COL.stable_cost_pct];
    var ac = last[COL.app_cost], ap = last[COL.app_cost_pct];
    var appName = last[COL.cheapest_app], path = last[COL.stable_path];

    // the lowest-to-highest hourly extra cost over the last 30 days, anchored
    // on this series' own latest hour (never the wall clock)
    var win0 = Date.parse(t) - 30 * DAY * 1000;
    var extras30 = [];
    for (i = 0; i < n; i++) {
      if (Date.parse(hrs[i][COL.hour_utc]) >= win0) extras30.push(hrs[i][COL.stable_cost_pct] - hrs[i][COL.app_cost_pct]);
    }
    var e30 = [Math.min.apply(null, extras30), Math.max.apply(null, extras30)];
    var ep = sp - ap;

    // the daily line: the median of each UTC day's hourly extra cost, in the
    // sending currency and in percent of the amount. A day with no priced
    // hour is a gap (null), never filled.
    var groups = {};
    for (i = 0; i < n; i++) {
      var k = dayKey(hrs[i][COL.hour_utc]);
      (groups[k] = groups[k] || []).push(hrs[i]);
    }
    var day0 = dayKey(first), dayLast = dayKey(t);
    var daily = [], cur = Date.parse(day0 + "T00:00:00Z"), end = Date.parse(dayLast + "T00:00:00Z");
    while (cur <= end) {
      var key = new Date(cur).toISOString().slice(0, 10), g = groups[key];
      if (g && g.length) {
        var costs = g.map(function (h) { return h[COL.stable_cost] - h[COL.app_cost]; });
        var pcts = g.map(function (h) { return h[COL.stable_cost_pct] - h[COL.app_cost_pct]; });
        daily.push([median(costs), median(pcts), g.length]);
      } else daily.push(null);
      cur += DAY * 1000;
    }

    // the stablecoin's cost split into its stored legs, for the latest
    // breakdown row (routes_breakdown.json's own path, the base route's
    // stablecoin -- legs exist only for it)
    var legPath = null, legT = null, depM = null, wdM = null;
    var L = { inn: null, chain: null, out: null, tot: null };
    var brkR = BRK && BRK.routes.filter(function (x) { return x.id === routeId; })[0];
    var brkA = brkR && brkR.amounts.filter(function (x) { return x.amount === amount; })[0];
    if (brkA && brkA.rows.length) {
      var row = brkA.rows[brkA.rows.length - 1];
      legT = row[BCOL.hour_utc];
      legPath = row[BCOL.path];
      depM = row[BCOL.deposit_measured];
      wdM = row[BCOL.withdrawal_measured];
      var dep = depM === false ? null : row[BCOL.getting_in_deposit];
      var buy = row[BCOL.getting_in_buy];
      var sell = row[BCOL.cashing_out_sell];
      var wd = wdM === false ? null : row[BCOL.cashing_out_withdrawal];
      L.inn = dep != null && buy != null ? dep + buy : null;
      L.chain = row[BCOL.on_chain];
      L.out = sell != null && wd != null ? sell + wd : null;
      L.tot = row[BCOL.total];
    }

    return {
      t: t, sc: sc, sp: sp, ac: ac, ap: ap, app: appName, path: path,
      n: n, wins: wins, first: first, e30: e30, ep: ep,
      leg: L, legPath: legPath, legT: legT, depM: depM, wdM: wdM,
      day0: day0, daily: daily, hrs: hrs, sym: r.send_symbol, dest: r.dest, routeWords: r.route_words,
    };
  }

  // ---------------------------------------------------------------- small drawing helpers (code, no words)
  function niceTicks(lo, hi, n) {
    var span = hi - lo || 1, step = Math.pow(10, Math.floor(Math.log10(span / n)));
    var err = span / n / step;
    step *= err >= 5 ? 5 : err >= 2 ? 2 : 1;
    var out = [];
    for (var v = Math.ceil(lo / step) * step; v <= hi + step * 1e-6; v += step) {
      out.push(Math.abs(v) < step * 1e-6 ? 0 : +v.toFixed(6));
    }
    return out;
  }
  // A scale that always holds zero and every value handed to it, with nice
  // tick steps -- used for the "Other places" range-bar rows.
  function niceScale(vals) {
    var lo = Math.min.apply(null, [0].concat(vals)), hi = Math.max.apply(null, [0].concat(vals));
    var pad = (hi - lo) * 0.04;
    if (lo < 0) lo -= pad;
    hi += pad;
    var ticks = niceTicks(lo, hi, 4);
    lo = Math.min(lo, ticks[0]); hi = Math.max(hi, ticks[ticks.length - 1]);
    return { lo: lo, hi: hi, ticks: ticks, X: function (v) { return (v - lo) / (hi - lo) * 100; } };
  }
  // A plain zero-anchored scale with no padding or ticks -- used for the
  // "this hour" bars, which print their own value and need no key.
  function plainScale(vals) {
    var lo = Math.min.apply(null, [0].concat(vals)), hi = Math.max.apply(null, [0].concat(vals));
    return { lo: lo, hi: hi, X: function (v) { return (v - lo) / (hi - lo || 1) * 100; } };
  }
  function gridLines(S) {
    return S.ticks.map(function (t) {
      return '<i class="sm-gridl' + (t === 0 ? " sm-zero" : "") + '" style="left:' + S.X(t) + '%"></i>';
    }).join("");
  }
  function axisRow(S, fmt) {
    return '<div class="sm-axisrow"><span></span><div class="sm-track">' + gridLines(S) +
      S.ticks.map(function (t) {
        return '<span class="sm-tk sm-num' + (t === 0 ? " sm-z" : "") + '" style="left:' + S.X(t) + '%">' + esc(fmt(t)) + "</span>";
      }).join("") + "</div><span></span></div>";
  }
  function rangeRow(S, o) {
    var tag = o.btn ? "button" : "div";
    var rng = o.rg ? '<i class="sm-rng" style="left:' + S.X(o.rg[0]) + '%;width:' + Math.max(0.6, S.X(o.rg[1]) - S.X(o.rg[0])) + '%"></i>' : "";
    var dot = o.v != null ? '<i class="sm-dot" style="left:' + S.X(o.v) + '%"></i>' : "";
    return "<" + tag + ' class="sm-row' + (o.cls ? " " + o.cls : "") + '"' +
      (o.tip ? ' data-tip="' + esc(o.tip) + '"' : "") +
      (o.btn ? ' type="button" data-r="' + esc(o.btn) + '"' : "") + ">" +
      '<span class="sm-nm">' + esc(o.name) + (o.sub ? "<small>" + esc(o.sub) + "</small>" : "") + "</span>" +
      '<span class="sm-track">' + gridLines(S) + rng + dot + "</span>" +
      '<span class="sm-v sm-num">' + (o.val || "") + (o.vsub ? "<small>" + esc(o.vsub) + "</small>" : "") + "</span></" + tag + ">";
  }
  function barRow(S, o) {
    var x0 = S.X(0), x1 = S.X(o.v == null ? 0 : o.v);
    var tipText = o.name + (o.sub ? " (" + o.sub + ")" : "") + ": " + (o.val || "") + (o.vsub ? ", " + o.vsub : "") + (TIP_WHEN ? ", " + TIP_WHEN : "");
    return '<div class="sm-row' + (o.cls ? " " + o.cls : "") + '" data-tip="' + esc(tipText) + '"><span class="sm-nm">' + esc(o.name) +
      (o.sub ? "<small>" + esc(o.sub) + "</small>" : "") + "</span>" +
      '<span class="sm-bar">' + (S.ticks ? gridLines(S) : "") + (S.lo < 0 ? '<i class="sm-z" style="left:' + x0 + '%"></i>' : "") +
      (o.v != null ? '<b style="left:' + Math.min(x0, x1) + '%;width:' + Math.max(0.4, Math.abs(x1 - x0)) + '%"></b>' : "") + "</span>" +
      '<span class="sm-v sm-num">' + (o.val || "") + (o.vsub ? "<small>" + esc(o.vsub) + "</small>" : "") + "</span></div>";
  }

  // ---------------------------------------------------------------- the week-by-week chart
  // The points the chart shows for the picked range (21 Oct). "all" and "1m": one point a day, the median of that
  // day's hours (the last 30 days for "1m"). "1w": every priced hour of the last 7 days, anchored on the series' own
  // latest hour. A missing day or hour stays a gap. Each point: [extra cost, extra %, hours behind it, time in ms].
  function series(A) {
    var d0 = Date.parse(A.day0 + "T00:00:00Z");
    if (S.period === "1w") {
      var hrs = A.hrs, tEnd = Date.parse(hrs[hrs.length - 1][COL.hour_utc]), t0 = tEnd - 7 * DAY * 1000, byT = {}, out = [];
      hrs.forEach(function (h) { var t = Date.parse(h[COL.hour_utc]); if (t > t0) byT[Math.round(t / 36e5)] = h; });
      for (var k = Math.round(t0 / 36e5) + 1; k <= Math.round(tEnd / 36e5); k++) {
        var h = byT[k];
        out.push(h ? [h[COL.stable_cost] - h[COL.app_cost], h[COL.stable_cost_pct] - h[COL.app_cost_pct], 1, k * 36e5] : null);
      }
      while (out.length && !out[0]) out.shift();   // a route younger than a week starts at its first hour, not at an empty stretch (27 Oct)
      return out;
    }
    var all = A.daily.map(function (p, i) { return p ? [p[0], p[1], p[2], d0 + i * 864e5] : null; });
    return S.period === "1m" ? all.slice(-30) : all;
  }
  // The chart looks like the record chart: the purple line over a light purple fill, light grid lines, small grey
  // axis words. The zero line stays dark: below it the stablecoin was cheaper than the cheapest app.
  function drawChart() {
    var svg = document.getElementById("smSvg"), box = document.getElementById("smChart");
    if (!svg || !box || !chart) return;
    var A = chart.A, sym = chart.sym, pts = series(A), hourly = S.period === "1w";
    chart.pts = pts;
    var W = Math.max(300, box.clientWidth), Hh = W < 560 ? 220 : 280, L = 56, T = 10, B = 26, pw = W - L, ph = Hh - T - B;
    var vs = pts.filter(Boolean).map(function (p) { return p[0]; });
    var lo = Math.min.apply(null, [0].concat(vs)), hi = Math.max.apply(null, [0].concat(vs));
    var pad = (hi - lo) * 0.06; hi += pad; if (lo < 0) lo -= pad;
    var ticks = niceTicks(lo, hi, W < 560 ? 3 : 4);
    lo = Math.min(lo, ticks[0]); hi = Math.max(hi, ticks[ticks.length - 1]);
    var n = pts.length;
    function X(i) { return L + (n > 1 ? i / (n - 1) : 0.5) * pw; }
    function Y(v) { return T + (1 - (v - lo) / (hi - lo)) * ph; }
    var g = "";
    ticks.forEach(function (v) {
      if (v !== 0) g += '<line x1="' + L + '" x2="' + W + '" y1="' + Y(v) + '" y2="' + Y(v) + '" class="sm-grid"/>';
      g += '<text class="sm-ax' + (v === 0 ? " sm-z" : "") + '" x="' + (L - 8) + '" y="' + (Y(v) + 4) + '" text-anchor="end">' +
        (v === 0 ? "0" : (v > 0 ? "+" : MINUS) + sym + whole(Math.abs(v))) + "</text>";
    });
    // x axis: each day at midnight UTC on the week view, Mondays (every other one on a phone) on the daily views
    var narrow = W < 560, lastLabel = -1;
    pts.forEach(function (p, i) {
      var tm = p ? p[3] : null;
      if (tm === null) {
        tm = hourly ? (pts[0] ? pts[0][3] : 0) + i * 36e5 : Date.parse(A.day0 + "T00:00:00Z") + (S.period === "1m" ? A.daily.length - 30 + i : i) * 864e5;
      }
      var d = new Date(tm), show;
      if (hourly) show = d.getUTCHours() === 0 && (!narrow || d.getUTCDate() % 2 === 0);
      else show = pts.length <= 21 ? true : d.getUTCDay() === 1 && (!narrow || S.period === "1m" || Math.round(tm / 864e5 / 7) % 2 === 0);   // a short record labels days, spaced below
      if (!show) return;
      g += '<line x1="' + X(i) + '" x2="' + X(i) + '" y1="' + (T + ph) + '" y2="' + (T + ph + 5) + '" class="sm-tick"/>';
      if (lastLabel < 0 || X(i) - lastLabel > 44) {
        g += '<text class="sm-ax" x="' + X(i) + '" y="' + (T + ph + 19) + '" text-anchor="middle">' + esc(dayShort(d.toISOString())) + "</text>";
        lastLabel = X(i);
      }
    });
    // the fill between the line and zero, then the line, one run per stretch without gaps. On the week view a miss of up
    // to 3 hours (a collection run that did not happen, every route at once) does not cut the fill: the line crosses it
    // dashed, so the missing hours still show and nothing is filled in as a reading (27 Oct, Seb: "random holes").
    var BRIDGE = hourly ? 3 : 0;
    // an hour with no blockchain fee reading is never bridged: it is a gap, shaded, with its own note and tip (1 Nov, Seb)
    var GM = hourly ? gasMissing(S.route) : {}, t0h = hourly && pts[0] ? Math.round(pts[0][3] / 36e5) : 0, gasIdx = [];
    if (hourly) pts.forEach(function (p, i) { if (!p && GM[t0h + i]) gasIdx.push(i); });
    var runs = [], cur = null, miss = 0;
    pts.forEach(function (p, i) {
      if (!p) { miss += GM[t0h + i] && hourly ? BRIDGE + 1 : 1; return; }
      if (!cur || miss > BRIDGE) { cur = []; runs.push(cur); }
      cur.push(i); miss = 0;
    });
    var z = Y(0), dLine = "", dGap = "";
    runs.forEach(function (r) {
      var line = r.map(function (i, j) { return (j ? "L" : "M") + X(i).toFixed(1) + " " + Y(pts[i][0]).toFixed(1); }).join("");
      r.forEach(function (i, j) {
        var pt = X(i).toFixed(1) + " " + Y(pts[i][0]).toFixed(1);
        if (j && i - r[j - 1] > 1) { dGap += "M" + X(r[j - 1]).toFixed(1) + " " + Y(pts[r[j - 1]][0]).toFixed(1) + "L" + pt; dLine += "M" + pt; }
        else dLine += (j ? "L" : "M") + pt;
      });
      g += '<path class="sm-area" d="' + line + "L" + X(r[r.length - 1]).toFixed(1) + " " + z.toFixed(1) + "L" + X(r[0]).toFixed(1) + " " + z.toFixed(1) + 'Z"/>';
    });
    var slot = n > 1 ? pw / (n - 1) : pw;
    gasIdx.forEach(function (i) { g += '<rect class="sm-gasmiss" x="' + (X(i) - slot / 2).toFixed(1) + '" y="' + T + '" width="' + Math.max(2, slot).toFixed(1) + '" height="' + ph + '"/>'; });
    g += '<line x1="' + L + '" x2="' + W + '" y1="' + z + '" y2="' + z + '" class="sm-zline"/>';
    if (dGap) g += '<path class="sm-line sm-gapline" d="' + dGap + '"/>';
    g += '<path class="sm-line" d="' + dLine + '"/>';
    var li = pts.length - 1;
    if (pts[li]) g += '<circle cx="' + X(li) + '" cy="' + Y(pts[li][0]) + '" r="3.5" class="sm-dot"/>';
    g += '<line id="smCross" y1="' + T + '" y2="' + (T + ph) + '" class="sm-cross" visibility="hidden"/>';
    svg.setAttribute("viewBox", "0 0 " + W + " " + Hh);
    svg.innerHTML = g;
    chart.geo = { L: L, pw: pw, n: n, X: X, W: W };
    chart.gas = {}; gasIdx.forEach(function (i) { chart.gas[i] = (t0h + i) * 36e5; });
    var gn = document.getElementById("smGasNote");
    if (gn) { gn.textContent = gasIdx.length ? txt("gasMissNote") : ""; gn.hidden = !gasIdx.length || !txt("gasMissNote"); }
    // the note under the heading says "each hour" on the week view, "each day" otherwise
    var note = document.getElementById("smWeekNote"), nt = txt(hourly ? "weekNoteHourly" : "weekNote");
    if (note && nt) note.textContent = nt;
    [].forEach.call(document.querySelectorAll("[data-period]"), function (b) { b.setAttribute("aria-pressed", b.getAttribute("data-period") === S.period ? "true" : "false"); });
  }
  function hoverChart(e) {
    if (!chart || !chart.geo) return;
    var geo = chart.geo, svg = document.getElementById("smSvg"), tip = document.getElementById("smTip"), cross = document.getElementById("smCross");
    var b = svg.getBoundingClientRect(), x = (e.clientX - b.left) / b.width * geo.W;
    var i = Math.round((x - geo.L) / geo.pw * (geo.n - 1));
    var p = chart.pts && chart.pts[i];
    if (!p && chart.gas && chart.gas[i] && txt("gasMissTip")) {
      var gd = new Date(chart.gas[i]).toISOString();
      cross.setAttribute("x1", geo.X(i)); cross.setAttribute("x2", geo.X(i)); cross.setAttribute("visibility", "visible");
      tip.innerHTML = esc(txt("gasMissTip")) + "<span>" + esc(txt("chartTipHour", { day: dayShort(gd), hour: gd.slice(11, 16) })) + "</span>";
      tip.hidden = false;
      var gl = geo.X(i) / geo.W * 100;
      tip.style.left = gl > 65 ? "" : (gl + 2) + "%"; tip.style.right = gl > 65 ? (100 - gl + 2) + "%" : "";
      return;
    }
    if (i < 0 || i >= geo.n || !p) { tip.hidden = true; if (cross) cross.setAttribute("visibility", "hidden"); return; }
    cross.setAttribute("x1", geo.X(i)); cross.setAttribute("x2", geo.X(i)); cross.setAttribute("visibility", "visible");
    var dd = new Date(p[3]).toISOString();
    // said in words when the words exist (27 Oct): "Stablecoin S$10.78 more expensive than the cheapest app"
    var said = txt(p[0] > 0 ? "chartTipMore" : "chartTipLess", { amount: money(Math.abs(p[0]), chart.sym) });
    tip.innerHTML = (said ? esc(said) : (p[0] > 0 ? "+" : "") + money(p[0], chart.sym) + " (" + pctPlain(p[1]) + ")") +
      "<span>" + esc(S.period === "1w" ? txt("chartTipHour", { day: dayShort(dd), hour: dd.slice(11, 16) }) : txt("chartTip", { day: dayShort(dd), hours: whole(p[2]) })) + "</span>";
    tip.hidden = false;
    var left = geo.X(i) / geo.W * 100;
    tip.style.left = left > 65 ? "" : (left + 2) + "%";
    tip.style.right = left > 65 ? (100 - left + 2) + "%" : "";
  }

  // ---------------------------------------------------------------- page shell
  var NAV = [["navCountries", "./countries.html"], ["navRoutes", "./sending-money.html", true],
    ["navSources", "./sources.html"], ["navFindings", "./findings.html"], ["navResearch", "./research.html"], ["navEvents", "./events.html"], ["navHow", "./how-it-works.html"]];
  function headHtml() {
    return '<header class="sm-head"><a class="sm-logo" href="./index.html">margin.wiki</a>' +
      '<nav class="sm-nav" aria-label="Main">' + NAV.map(function (nv) {
        var s = txt(nv[0]);
        return s ? '<a href="' + nv[1] + '"' + (nv[2] ? ' aria-current="page"' : "") + ">" + esc(s) + "</a>" : "";
      }).join("") + '</nav></header>';
  }
  function pillsHtml() {
    var r = routeObj(S.route);
    var routes = ALL.map(function (id) {
      var ro = routeObj(id);
      return ro ? '<button class="sm-pill" type="button" data-r="' + esc(id) + '" aria-pressed="' + (id === S.route) + '">' + esc(plainRoute(ro.route_words)) + "</button>" : "";
    }).join("");
    var amounts = ORDER.indexOf(S.route) < 0 ? "" : r.amounts.map(function (a) {
      return '<button class="sm-pill sm-num" type="button" data-a="' + a.amount + '" aria-pressed="' + (a.amount === S.amount) + '">' +
        esc(r.send_symbol) + whole(a.amount) + "</button>";
    }).join("");
    // below 768px the route picker is a native dropdown (SEB-268): thirteen pills do not fit a phone without scrolling sideways
    var options = ALL.map(function (id) {
      var ro = routeObj(id);
      return ro ? '<option value="' + esc(id) + '"' + (id === S.route ? " selected" : "") + ">" + esc(plainRoute(ro.route_words)) + "</option>" : "";
    }).join("");
    var select = '<div class="sm-routesel"><label for="smRouteSel">' + esc(txt("routePickerLabel")) + '</label><select id="smRouteSel">' + options + "</select></div>";
    // the overview above is the route picker (28 Oct): only the amounts are buttons here
    if (txt("cmpGap")) return amounts ? '<div class="sm-tools"><div class="sm-pills" role="group" id="smAmounts">' + amounts + "</div></div>" : "";
    return '<div class="sm-tools">' + select + '<div class="sm-pills" role="group" id="smRoutes">' + routes + '</div>' +
      (amounts ? '<div class="sm-pills" role="group" id="smAmounts">' + amounts + "</div>" : "") + "</div>";
  }

  // the official rate's own time, from the field the collector stores; hidden while the field is missing or not a time
  function rateFromHtml() {
    var r = routeObj(S.route), iso = r && r.official_rate_updated_utc, d = iso ? new Date(iso) : null;
    if (!d || isNaN(d.getTime()) || !txt("officialRateFrom")) return "";
    var hhmm = String(d.getUTCHours()).padStart(2, "0") + ":" + String(d.getUTCMinutes()).padStart(2, "0");
    return '<p class="sm-meta sm-num">' + esc(txt("officialRateFrom", { time: hhmm })) + "</p>";
  }

  function heroHtml(A) {
    var amt = esc(A.sym) + whole(S.amount);
    // a cost below zero is said in words, with no minus sign: the app paid out more than the official rate
    var vals = { amount: amt, dest: A.dest, appCost: money(Math.abs(A.ac), A.sym), app: A.app, stableCost: money(Math.abs(A.sc), A.sym) };
    var hkey = A.ac < 0 ? (A.sc < 0 ? "headlineBothBack" : "headlineAppBack") : (A.sc < 0 ? "headlineStableBack" : "headline");
    var lead = A.wins === 0
      ? txt("leadNever", { n: whole(A.n), first: dayLong(A.first) })
      : txt("leadSome", { n: whole(A.n), wins: whole(A.wins), first: dayLong(A.first) });
    return '<div class="sm-hero">' + w(hkey, vals, "h2") +
      (lead ? '<p class="sm-lead">' + esc(lead) + "</p>" : "") +
      rateFromHtml() + "</div>";   // the "Prices from the ... hour" line is already at the top of the page
  }

  function nowSectionHtml(A) {
    // the steps are shown only for the path priced above, this hour; any other path's steps, or none stored, show no step by step at all
    var showSteps = !!A.legPath && A.legPath === A.path && A.legT === A.t;
    var legVals = [A.ac, A.sc].concat(showSteps ? ["inn", "chain", "out", "tot"].map(function (k) { return A.leg[k]; }).filter(function (v) { return v != null; }) : []);
    var SC = niceScale(legVals);
    TIP_WHEN = dayShort(A.t) + ", " + clock(A.t) + " UTC";
    var moneyAxis = axisRow(SC, function (t) { return (t < 0 ? MINUS : "") + A.sym + whole(Math.abs(t)); });
    var negative = legVals.some(function (v) { return v < 0; });
    var share = function (v) { return v == null ? "" : pctPlain(v / S.amount * 100); };
    var now = barRow(SC, { cls: "sm-app", name: txt("rowApp"), sub: txt("rowAppSub", { app: A.app }), v: A.ac, val: money(A.ac, A.sym), vsub: pctPlain(A.ap) }) +
      barRow(SC, { name: txt("rowStable"), sub: (A.path !== "USDT" && txt("rowStableSubOther")) ? txt("rowStableSubOther") : txt("rowStableSub", { path: pathName(A.path) }), v: A.sc, val: money(A.sc, A.sym), vsub: pctPlain(A.sp) });
    // the three steps are shown rounded so they add up to the rounded total (largest remainder), never 1 cent off.
    // Cents show on all four rows when any of them is under 100; if all are 100 or more they show whole, and the rounding is to whole units.
    var wholeMode = ["inn", "chain", "out", "tot"].every(function (k) { return A.leg[k] != null && Math.abs(A.leg[k]) >= 100; });
    var unit = wholeMode ? 1 : 0.01;
    var shownLeg = (function () {
      var ks = ["inn", "chain", "out"], vs = ks.map(function (k) { return A.leg[k]; }), out = { tot: A.leg.tot };
      if (A.leg.tot == null || vs.some(function (v) { return v == null; })) { ks.forEach(function (k) { out[k] = A.leg[k]; }); return out; }
      var u = vs.map(function (v) { return v / unit; }), fl = u.map(Math.floor), need = Math.round(A.leg.tot / unit) - fl.reduce(function (a, b) { return a + b; }, 0);
      var order = u.map(function (c, i) { return [c - fl[i], i]; }).sort(function (a, b) { return b[0] - a[0]; });
      for (var i = 0; i < order.length && need > 0; i++, need--) { fl[order[i][1]] += 1; }
      for (var j = order.length - 1; need < 0 && j >= 0; j--, need++) { fl[order[j][1]] -= 1; }
      ks.forEach(function (k, i) { out[k] = fl[i] * unit; });
      out.tot = Math.round(A.leg.tot / unit) * unit;
      return out;
    })();
    function stepMoney(v) { return v == null ? "" : (v < 0 ? MINUS : "") + A.sym + (wholeMode ? whole(Math.abs(v)) : num(Math.abs(v), 2)); }
    function step(k, label) {
      return barRow(SC, { cls: k === "tot" ? "sm-tot" : "sm-step", name: label, v: A.leg[k], val: A.leg[k] == null ? txt("notStored") : stepMoney(shownLeg[k]), vsub: share(A.leg[k]) });
    }
    var steps = step("inn", txt("rowDeposit")) + step("chain", txt("rowNetwork")) + step("out", txt("rowSell")) + step("tot", txt("rowAllIn"));
    var stepsNote = showSteps && A.legPath === "USDT" ? txt("stepsNoteSame", { legPath: pathName(A.legPath), path: pathName(A.path) }) : "";   // a named path only: the "another stablecoin route" label never appears here
    var stepsGap = (A.depM === false || A.wdM === false) ? txt("stepsGap") : "";
    // when the path priced is one whose network gas is not in the cost, say so under it (the path list comes from the data)
    var gasNo = (routeObj(S.route).gas_not_modelled_paths || []).indexOf(A.path) >= 0;
    var gasLine = gasNo ? w("gasNote", null, "p", "sm-small") : "";
    // the newest hour could not be priced because its blockchain fee was not read: the figures are from the hour before, and say so
    var newest = HOURLY && HOURLY.as_of_utc, nowGas = newest && gasMissing(S.route)[Math.round(Date.parse(newest) / 36e5)] && Date.parse(A.t) < Date.parse(newest);
    if (nowGas && txt("gasMissNow")) gasLine += w("gasMissNow", { time: clock(A.t) }, "p", "sm-small");
    return '<section class="sm-first">' + w("nowHeading", { amount: esc(A.sym) + whole(S.amount) }, "h2") +
      w("nowNote", null, "p", "sm-note") + '<div>' + moneyAxis + now + "</div>" + gasLine +
      (showSteps ? w("stepsHeading", null, "h3") + (stepsNote ? '<p class="sm-note">' + esc(stepsNote) + "</p>" : "") + '<div>' + moneyAxis + steps + "</div>" : "") +
      (negative ? w("negNote", null, "p", "sm-small") : "") + (showSteps && stepsGap ? '<p class="sm-small">' + esc(stepsGap) + "</p>" : "") + "</section>";
  }

  function weekSectionHtml(A) {
    // a range is offered only when it shows more than the shorter one (27 Oct, Seb): Month needs more than 7 days of
    // record, All more than 30. If the picked range is not offered, the longest one that is takes its place.
    var days = A && A.daily ? A.daily.length : 0;
    var periods = [["1w", "period1w"], ["1m", "period1m"], ["all", "periodAll"]].filter(function (p) {
      return txt(p[1]) && (p[0] === "1w" || (p[0] === "1m" && days > 7) || (p[0] === "all" && days > 30));
    });
    if (!periods.some(function (p) { return p[0] === S.period; })) S.period = periods.length ? periods[periods.length - 1][0] : "all";
    var bar = periods.length > 1 ? '<div class="sm-periods" role="group">' + periods.map(function (p) {
      return '<button type="button" data-period="' + p[0] + '" aria-pressed="' + (S.period === p[0]) + '">' + esc(txt(p[1])) + "</button>";
    }).join("") + "</div>" : "";
    return '<section>' + w("weekHeading", null, "h2") + (txt("weekNote") ? '<p class="sm-note" id="smWeekNote">' + esc(txt("weekNote")) + "</p>" : "") +
      '<div class="sm-chart" id="smChart"><svg id="smSvg" role="img" aria-label="' + esc(txt("chartAria")) + '"></svg>' +
      '<div class="sm-tip sm-num" id="smTip" hidden></div></div>' + '<p class="sm-small" id="smGasNote" hidden></p>' + bar + "</section>";
  }

  var CMP_AMOUNT = 1000;   // the overview always compares the same 1,000 in each sending currency, whatever amount is picked below
  function cmpSectionHtml() {
    var rows = ORDER.map(function (id) { return routeObj(id); }).filter(function (r) { return r && amountObj(r, CMP_AMOUNT); });
    var blocks = rows.map(function (r) { return [r, computeA(r.id, CMP_AMOUNT)]; });
    blocks.sort(function (x, y) {
      var gx = gapOf(x[0].id), gy = gapOf(y[0].id);
      if (gx != null && gy != null && Math.abs(gx - gy) > 0.05) return gy - gx;
      return x[1].ep - y[1].ep;
    });
    var SC = niceScale(blocks.reduce(function (acc, b) { return acc.concat(b[1].e30, [b[1].ep]); }, []));
    var fmt = function (v) { return v === 0 ? "0%" : (v > 0 ? "+" : MINUS) + Math.abs(v) + "%"; };
    // the tooltip's figures: one decimal, never a minus sign on a zero
    var sgPct = function (v) { return Math.abs(v) < 0.05 ? pctPlain(0) : (v > 0 ? "+" : MINUS) + pctPlain(Math.abs(v)); };
    var html = axisRow(SC, fmt) + blocks.map(function (b) {
      var r = b[0], a = b[1];
      var sub = a.wins === 0 ? txt("neverCheaper", { n: whole(a.n) }) : txt("cheaperInSome", { wins: whole(a.wins), n: whole(a.n) });
      var g = gapOf(r.id);
      if (g != null && txt("cmpGap")) sub = txt("cmpGap", { gap: (g > 0 ? "+" : g < 0 ? MINUS : "") + num(Math.abs(g), 1) + "%" }) + " · " + sub;
      var vsub = txt(a.ep < 0 ? "lessThan" : "moreThan", { app: a.app });
      var tip = txt("cmpTip", { route: plainRoute(r.route_words), now: sgPct(a.ep), lo: sgPct(a.e30[0]), hi: sgPct(a.e30[1]), app: a.app });
      return rangeRow(SC, { btn: r.id, cls: r.id === S.route ? "sm-on" : "", name: plainRoute(r.route_words), sub: sub, v: a.ep, rg: a.e30, val: pctPlain(Math.abs(a.ep)), vsub: vsub, tip: tip });
    }).join("");
    return '<section class="sm-cmp" id="smCmp">' + w("cmpHeading", { amount: whole(CMP_AMOUNT) }, "h2") + w("cmpNote", null, "p", "sm-note") +
      '<p class="sm-key">' +
      (txt("keyThisHour") ? '<span><i class="sm-kd"></i>' + esc(txt("keyThisHour")) + "</span>" : "") +
      (txt("keyRange") ? '<span><i class="sm-kr"></i>' + esc(txt("keyRange")) + "</span>" : "") +
      (txt("keyCheapestApp") ? '<span><i class="sm-kl"></i>' + esc(txt("keyCheapestApp")) + "</span>" : "") +
      "</p><div>" + html + "</div></section>";
  }

  // a route measured against the official rate is not compared yet: its name, and one line why
  function notComparedHtml() {
    var ro = routeObj(S.route);
    var name = ro ? plainRoute(ro.route_words) : "";
    return '<div class="sm-hero"><h1>' + esc(name) + '</h1><p class="sm-lead">' + esc(txt("notCompared", { route: name })) + "</p></div>";
  }

  function footerHtml() {
    var text = w("footerText", null, "p");
    var link = txt("footerLinkText");
    return "<footer>" + text + (link ? '<a href="https://github.com/SebR214/margin">' + esc(link) + "</a>" : "") + "</footer>";
  }

  function pushUrl() {
    try {
      history.replaceState(null, "", location.pathname + "?route=" + routeKey(S.route) + "&amount=" + S.amount);
    } catch (e) { /* not available */ }
  }

  function renderAll() {
    var el = box();
    if (!el || !READY) return;
    if (ORDER.indexOf(S.route) < 0) {
      el.innerHTML = '<section class="sm-detail">' + notComparedHtml() + pillsHtml() + "</section>";
      return;
    }
    var A = computeA(S.route, S.amount);
    el.innerHTML = (txt("cmpGap") ? cmpSectionHtml() : "") +
      '<section class="sm-detail" id="smPicked">' + heroHtml(A) + pillsHtml() + "</section>" + nowSectionHtml(A) + weekSectionHtml(A);
    chart = { A: A, sym: A.sym };
    drawChart();
    var cb = document.getElementById("smChart");
    if (cb) {
      cb.addEventListener("pointermove", hoverChart);
      cb.addEventListener("pointerdown", hoverChart);      // a tap on a phone
      cb.addEventListener("pointerleave", function (e) {
        if (e.pointerType === "touch") return;
        var tip = document.getElementById("smTip"), cross = document.getElementById("smCross");
        if (tip) tip.hidden = true;
        if (cross) cross.setAttribute("visibility", "hidden");
      });
      if (window.ResizeObserver) new ResizeObserver(function () { drawChart(); }).observe(cb);
    }
    [].forEach.call(document.querySelectorAll(".rt tr[data-r]"), function (tr) {
      tr.classList.toggle("rt-on", tr.getAttribute("data-r") === S.route && +tr.getAttribute("data-amt") === S.amount);
    });
  }

  function onChange(e) {
    if (e.target.id !== "smRouteSel" || e.target.value === S.route) return;
    S.route = e.target.value;
    if (!amountObj(routeObj(S.route), S.amount)) S.amount = 5000;
    renderAll(); pushUrl();
  }

  function onClick(e) {
    var pb = e.target.closest("[data-period]");
    if (pb) {
      S.period = pb.getAttribute("data-period");
      var tip = document.getElementById("smTip"); if (tip) tip.hidden = true;
      drawChart();
      return;
    }
    var tr = e.target.closest(".rt tr[data-r]");
    if (tr) {
      var tid = tr.getAttribute("data-r");
      if (!routeObj(tid)) return;
      S.route = tid;
      var ta = +tr.getAttribute("data-amt");
      S.amount = amountObj(routeObj(S.route), ta) ? ta : (amountObj(routeObj(S.route), 5000) ? 5000 : routeObj(S.route).amounts[0].amount);
      renderAll(); pushUrl();
      var el = box(); if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
      return;
    }
    if (!e.target.closest("#smDetail")) return;
    var r = e.target.closest("[data-r]"), a = e.target.closest("[data-a]");
    if (r) {
      var id = r.getAttribute("data-r");
      if (id !== S.route) {
        S.route = id;
        S.period = "all";   // a new route opens on its longest record (the range falls back to what it has)
        if (!amountObj(routeObj(S.route), S.amount)) S.amount = amountObj(routeObj(S.route), 1000) ? 1000 : 5000;
        renderAll(); pushUrl();
      }
      if (r.closest("#smCmp")) { var pk = document.getElementById("smPicked"); if (pk) pk.scrollIntoView({ behavior: "smooth", block: "start" }); }
      return;
    }
    if (a) { S.amount = +a.getAttribute("data-a"); renderAll(); pushUrl(); }
  }

  function parseRoute(s) {
    if (!s) return null;
    var k = s.replace(/^#?(route=)?/, "").toUpperCase().replace(/[^A-Z]+/g, "-");
    var hit = ALL.filter(function (id) { return routeKey(id) === k; })[0];
    return hit || null;
  }

  function start(res) {
    COPY = (res[0] && res[0].routeData) || {};
    HOURLY = res[1]; BRK = res[2];
    if (!HOURLY || !res[3]) throw new Error("data");
    setGaps(res[4]);
    setRoutes(res[3]);
    HOURLY.hour_columns.forEach(function (c, i) { COL[c] = i; });
    if (BRK) BRK.columns.forEach(function (c, i) { BCOL[c] = i; });
    var q = new URLSearchParams(location.search);
    S.route = parseRoute(q.get("route")) || ORDER[0];
    var amt = +q.get("amount");
    // no amount in the link: the table's amount (US$1,000 or its equal), so the detail matches the row it sits under
    S.amount = amountObj(routeObj(S.route), amt) ? amt : (amountObj(routeObj(S.route), 1000) ? 1000 : 5000);
    document.addEventListener("click", onClick);
    document.addEventListener("change", onChange);
    READY = true;
    window.addEventListener("routes:render", renderAll);   // js/route.js rebuilt its table and an empty #smDetail
    // a tap anywhere but the chart closes the day it showed
    document.addEventListener("pointerdown", function (e) {
      if (e.target.closest && e.target.closest("#smChart")) return;
      var tip = document.getElementById("smTip"), cross = document.getElementById("smCross");
      if (tip) tip.hidden = true;
      if (cross) cross.setAttribute("visibility", "hidden");
    });
    renderAll();
    (window.siteLive = window.siteLive || { handlers: [], onNewHour: function (fn) { this.handlers.push(fn); } }).onNewHour(refresh);
  }

  // a tab left open loads the newer hour when it is published (siteLive, js/site_head.js); the picked route and amount stay
  function refresh() {
    return Promise.all([maybeJSON("copy.json"), getJSON("data/routes_hourly.json"), maybeJSON("data/routes_breakdown.json"), getJSON("data/routes_summary.json"), maybeJSON("data/index_latest.json")]).then(function (res) {
      if (!res[1] || !res[3]) return;
      COPY = (res[0] && res[0].routeData) || COPY;
      HOURLY = res[1]; BRK = res[2];
      setGaps(res[4]);
      setRoutes(res[3]);
      if (ALL.indexOf(S.route) < 0) { S.route = ORDER[0]; }
      HOURLY.hour_columns.forEach(function (c, i) { COL[c] = i; });
      if (BRK) BRK.columns.forEach(function (c, i) { BCOL[c] = i; });
      if (!amountObj(routeObj(S.route), S.amount)) { S.amount = 5000; }
      var y = window.scrollY;
      renderAll();
      window.scrollTo(0, y);
    }).catch(function () { /* a failed refresh leaves what the reader already has */ });
  }

  Promise.all([maybeJSON("copy.json"), getJSON("data/routes_hourly.json"), maybeJSON("data/routes_breakdown.json"), getJSON("data/routes_summary.json"), maybeJSON("data/index_latest.json")])
    .then(start).catch(function (err) { if (window.console) console.error(err); });
})();

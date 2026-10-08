/* The sending-money page (SEB-272): rebuilt to match the owner's reference
 * artifact (https://claude.ai/artifact/9XijuhKEnEw9irjehEfnXn), desktop and
 * 390px. Replaces the old drag-to-select chart, stats strip, currency/percent
 * toggle, period chips, day slider, metric chips and "what would have to
 * change" block entirely -- none of that is rebuilt here.
 *
 * Reads only stored files:
 *   data/routes_hourly.json     every priced hour per route and amount
 *   data/routes_breakdown.json  the stablecoin path split into its stored legs
 *
 * Which route: ?route=SGD-PHP (the id as stored, "->" written "-"); the
 * first comparable route when absent or unknown. ?amount=5000 picks the
 * amount; 5000 when absent or not offered for that route.
 *
 * Words: none live here. Every word the page shows comes from copy.json,
 * block "routeData". A key that is empty renders no element. Numbers,
 * dates, percentages, currency symbols and app/path names are code,
 * formatted here from what tools/emit_routes.py stored -- including each
 * route's display words ("route_words", "dest"), so this file never builds
 * a country name out of string fragments. The "never cheaper in N hours" /
 * "cheaper in N of M hours" counts, and the week-by-week line, are computed
 * fresh from data/routes_hourly.json on every render -- never carried from
 * a prior example, never hand-typed.
 *
 * Four routes are comparable and shown (same set tools/emit_routes.py's own
 * ROUTES uses, in the order the reference artifact used them): SGD->PHP,
 * AUD->PHP, NZD->PHP, USD->MXN. Three are measured against an official rate
 * below what people really pay and are left out of the comparison --
 * USD->NGN, USD->INR, SGD->INR -- explained in its own section, same text
 * as the reference.
 */
(function () {

  var DAY = 86400, HOUR = 3600;
  var MINUS = "−";
  var MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  var MONL = ["January", "February", "March", "April", "May", "June", "July",
    "August", "September", "October", "November", "December"];
  var ORDER = ["SGD->PHP", "AUD->PHP", "NZD->PHP", "USD->MXN"];

  var COPY = {};
  var app = document.getElementById("app");
  var HOURLY = null, BRK = null;
  var COL = {}, BCOL = {};
  var S = { route: null, amount: null };
  var chart = null;

  // ---------------------------------------------------------------- helpers
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  // A copy slot filled with its placeholders; "" when the writer has not filled it.
  function txt(key, vals) {
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
    return id ? String(id).replace(":", " on ").replace(/([a-z])([A-Z])/g, "$1 $2") : "";
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
      day0: day0, daily: daily, sym: r.send_symbol, dest: r.dest, routeWords: r.route_words,
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
      (o.btn ? ' type="button" data-r="' + esc(o.btn) + '"' : "") + ">" +
      '<span class="sm-nm">' + esc(o.name) + (o.sub ? "<small>" + esc(o.sub) + "</small>" : "") + "</span>" +
      '<span class="sm-track">' + gridLines(S) + rng + dot + "</span>" +
      '<span class="sm-v sm-num">' + (o.val || "") + (o.vsub ? "<small>" + esc(o.vsub) + "</small>" : "") + "</span></" + tag + ">";
  }
  function barRow(S, o) {
    var x0 = S.X(0), x1 = S.X(o.v == null ? 0 : o.v);
    return '<div class="sm-row' + (o.cls ? " " + o.cls : "") + '"><span class="sm-nm">' + esc(o.name) +
      (o.sub ? "<small>" + esc(o.sub) + "</small>" : "") + "</span>" +
      '<span class="sm-bar">' + (S.lo < 0 ? '<i class="sm-z" style="left:' + x0 + '%"></i>' : "") +
      (o.v != null ? '<b style="left:' + Math.min(x0, x1) + '%;width:' + Math.max(0.4, Math.abs(x1 - x0)) + '%"></b>' : "") + "</span>" +
      '<span class="sm-v sm-num">' + (o.val || "") + (o.vsub ? "<small>" + esc(o.vsub) + "</small>" : "") + "</span></div>";
  }

  // ---------------------------------------------------------------- the week-by-week chart
  function drawChart() {
    var svg = document.getElementById("smSvg"), box = document.getElementById("smChart");
    if (!svg || !box || !chart) return;
    var A = chart.A, sym = chart.sym, pts = A.daily, d0 = Date.parse(A.day0 + "T00:00:00Z");
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
      g += '<line x1="' + L + '" x2="' + W + '" y1="' + Y(v) + '" y2="' + Y(v) + '" stroke="' + (v === 0 ? "#0B0B0B" : "#ECECEC") + '" stroke-width="1"/>' +
        '<text class="sm-ax' + (v === 0 ? " sm-z" : "") + '" x="' + (L - 8) + '" y="' + (Y(v) + 4) + '" text-anchor="end">' +
        (v === 0 ? "0" : (v > 0 ? "+" : MINUS) + sym + whole(Math.abs(v))) + "</text>";
    });
    var step = W < 560 ? 14 : 7;
    for (var i = 0; i < n; i++) {
      var d = new Date(d0 + i * 864e5);
      if (d.getUTCDay() !== 1) continue;
      var wk = Math.round((d - d0) / 864e5 / 7);
      g += '<line x1="' + X(i) + '" x2="' + X(i) + '" y1="' + (T + ph) + '" y2="' + (T + ph + 5) + '" stroke="#D3D0CB"/>';
      if (step === 7 || wk % 2 === 0) {
        g += '<text class="sm-ax" x="' + X(i) + '" y="' + (T + ph + 19) + '" text-anchor="middle">' + esc(dayShort(d.toISOString())) + "</text>";
      }
    }
    var dAttr = "", on = false;
    pts.forEach(function (p, i) {
      if (!p) { on = false; return; }
      dAttr += (on ? "L" : "M") + X(i).toFixed(1) + " " + Y(p[0]).toFixed(1);
      on = true;
    });
    g += '<path d="' + dAttr + '" fill="none" stroke="#6B6B6B" stroke-width="1.75" stroke-linejoin="round" stroke-linecap="round"/>';
    var li = pts.length - 1;
    if (pts[li]) g += '<circle cx="' + X(li) + '" cy="' + Y(pts[li][0]) + '" r="3.5" fill="#6B6B6B"/>';
    g += '<line id="smCross" y1="' + T + '" y2="' + (T + ph) + '" stroke="#0B0B0B" stroke-dasharray="3 3" visibility="hidden"/>';
    svg.setAttribute("viewBox", "0 0 " + W + " " + Hh);
    svg.innerHTML = g;
    chart.geo = { L: L, pw: pw, n: n, X: X, W: W };
  }
  function hoverChart(e) {
    if (!chart || !chart.geo) return;
    var geo = chart.geo, svg = document.getElementById("smSvg"), tip = document.getElementById("smTip"), cross = document.getElementById("smCross");
    var b = svg.getBoundingClientRect(), x = (e.clientX - b.left) / b.width * geo.W;
    var i = Math.round((x - geo.L) / geo.pw * (geo.n - 1));
    var p = chart.A.daily[i];
    if (i < 0 || i >= geo.n || !p) { tip.hidden = true; if (cross) cross.setAttribute("visibility", "hidden"); return; }
    cross.setAttribute("x1", geo.X(i)); cross.setAttribute("x2", geo.X(i)); cross.setAttribute("visibility", "visible");
    var dd = new Date(Date.parse(chart.A.day0 + "T00:00:00Z") + i * 864e5).toISOString();
    tip.innerHTML = (p[0] > 0 ? "+" : "") + money(p[0], chart.sym) + " (" + pctPlain(p[1]) + ")" +
      "<span>" + esc(txt("chartTip", { day: dayShort(dd), hours: whole(p[2]) })) + "</span>";
    tip.hidden = false;
    var left = geo.X(i) / geo.W * 100;
    tip.style.left = left > 65 ? "" : (left + 2) + "%";
    tip.style.right = left > 65 ? (100 - left + 2) + "%" : "";
  }

  // ---------------------------------------------------------------- page shell
  var NAV = [["navCountries", "./countries.html"], ["navRoutes", "./sending-money.html", true],
    ["navSources", "./sources.html"], ["navFindings", "./findings.html"], ["navHow", "./how-it-works.html"]];
  function headHtml() {
    return '<header class="sm-head"><a class="sm-logo" href="./index.html">margin.wiki</a>' +
      '<nav class="sm-nav" aria-label="Main">' + NAV.map(function (nv) {
        var s = txt(nv[0]);
        return s ? '<a href="' + nv[1] + '"' + (nv[2] ? ' aria-current="page"' : "") + ">" + esc(s) + "</a>" : "";
      }).join("") + "</nav></header>";
  }
  function pillsHtml() {
    var r = routeObj(S.route);
    var routes = ORDER.map(function (id) {
      var ro = routeObj(id);
      return '<button class="sm-pill" type="button" data-r="' + esc(id) + '" aria-pressed="' + (id === S.route) + '">' + esc(ro.route_words) + "</button>";
    }).join("");
    var amounts = r.amounts.map(function (a) {
      return '<button class="sm-pill sm-num" type="button" data-a="' + a.amount + '" aria-pressed="' + (a.amount === S.amount) + '">' +
        esc(r.send_symbol) + whole(a.amount) + "</button>";
    }).join("");
    return '<div class="sm-tools"><div class="sm-pills" role="group" id="smRoutes">' + routes + '</div>' +
      '<div class="sm-pills" role="group" id="smAmounts">' + amounts + "</div></div>";
  }

  function heroHtml(A) {
    var amt = esc(A.sym) + whole(S.amount);
    var vals = { amount: amt, dest: A.dest, appCost: money(A.ac, A.sym), app: A.app, stableCost: money(A.sc, A.sym) };
    var lead = A.wins === 0
      ? txt("leadNever", { n: whole(A.n), first: dayLong(A.first) })
      : txt("leadSome", { n: whole(A.n), wins: whole(A.wins), first: dayLong(A.first) });
    return '<div class="sm-hero">' + w("headline", vals, "h1") +
      (lead ? '<p class="sm-lead">' + esc(lead) + "</p>" : "") +
      '<p class="sm-meta sm-num"><span class="sm-live" aria-hidden="true"></span>' +
      esc(txt("meta", { time: clock(A.t), date: dayShort(A.t) })) + "</p></div>";
  }

  function nowSectionHtml(A) {
    var legVals = [A.ac, A.sc].concat(["inn", "chain", "out", "tot"].map(function (k) { return A.leg[k]; }).filter(function (v) { return v != null; }));
    var SC = plainScale(legVals);
    var share = function (v) { return v == null ? "" : pctPlain(v / S.amount * 100); };
    var now = barRow(SC, { cls: "sm-app", name: txt("rowApp"), sub: txt("rowAppSub", { app: A.app }), v: A.ac, val: money(A.ac, A.sym), vsub: pctPlain(A.ap) }) +
      barRow(SC, { name: txt("rowStable"), sub: txt("rowStableSub", { path: pathName(A.path) }), v: A.sc, val: money(A.sc, A.sym), vsub: pctPlain(A.sp) });
    function step(k, label) {
      return barRow(SC, { cls: k === "tot" ? "sm-tot" : "sm-step", name: label, v: A.leg[k], val: A.leg[k] == null ? txt("notStored") : money(A.leg[k], A.sym), vsub: share(A.leg[k]) });
    }
    var steps = step("inn", txt("rowDeposit")) + step("chain", txt("rowNetwork")) + step("out", txt("rowSell")) + step("tot", txt("rowAllIn"));
    var stepsNote = A.legPath ? txt(A.legPath === A.path ? "stepsNoteSame" : "stepsNoteDiff", { legPath: pathName(A.legPath), path: pathName(A.path) }) : "";
    var stepsGap = (A.depM === false || A.wdM === false) ? txt("stepsGap") : "";
    return '<section class="sm-first">' + w("nowHeading", { amount: esc(A.sym) + whole(S.amount) }, "h2") +
      w("nowNote", null, "p", "sm-note") + '<div>' + now + "</div>" +
      w("stepsHeading", null, "h3") + (stepsNote ? '<p class="sm-note">' + esc(stepsNote) + "</p>" : "") +
      '<div>' + steps + "</div>" + (stepsGap ? '<p class="sm-small">' + esc(stepsGap) + "</p>" : "") + "</section>";
  }

  function weekSectionHtml() {
    return '<section>' + w("weekHeading", null, "h2") + w("weekNote", null, "p", "sm-note") +
      '<div class="sm-chart" id="smChart"><svg id="smSvg" role="img" aria-label="' + esc(txt("chartAria")) + '"></svg>' +
      '<div class="sm-tip sm-num" id="smTip" hidden></div></div></section>';
  }

  function cmpSectionHtml(A) {
    var rows = ORDER.map(function (id) { return routeObj(id); }).filter(function (r) { return amountObj(r, S.amount); });
    var blocks = rows.map(function (r) { return [r, computeA(r.id, S.amount)]; });
    var SC = niceScale(blocks.reduce(function (acc, b) { return acc.concat(b[1].e30, [b[1].ep]); }, []));
    var fmt = function (v) { return v === 0 ? "0%" : (v > 0 ? "+" : MINUS) + Math.abs(v) + "%"; };
    var html = axisRow(SC, fmt) + blocks.map(function (b) {
      var r = b[0], a = b[1];
      var sub = a.wins === 0 ? txt("neverCheaper", { n: whole(a.n) }) : txt("cheaperInSome", { wins: whole(a.wins), n: whole(a.n) });
      var vsub = txt(a.ep < 0 ? "lessThan" : "moreThan", { app: a.app });
      return rangeRow(SC, { btn: r.id, cls: r.id === S.route ? "sm-on" : "", name: r.route_words, sub: sub, v: a.ep, rg: a.e30, val: pctPlain(Math.abs(a.ep)), vsub: vsub });
    }).join("");
    return '<section>' + w("cmpHeading", { amount: whole(S.amount) }, "h2") + w("cmpNote", null, "p", "sm-note") +
      '<p class="sm-key">' +
      (txt("keyThisHour") ? '<span><i class="sm-kd"></i>' + esc(txt("keyThisHour")) + "</span>" : "") +
      (txt("keyRange") ? '<span><i class="sm-kr"></i>' + esc(txt("keyRange")) + "</span>" : "") +
      (txt("keyCheapestApp") ? '<span><i class="sm-kl"></i>' + esc(txt("keyCheapestApp")) + "</span>" : "") +
      "</p><div>" + html + "</div></section>";
  }

  function leftOutSectionHtml() {
    return '<section class="sm-np">' + w("leftOutHeading", null, "h2") +
      w("leftOutNames", null, "p", "sm-names") + w("leftOutBody", null, "p") + "</section>";
  }

  function pushUrl() {
    try {
      history.replaceState(null, "", location.pathname + "?route=" + routeKey(S.route) + "&amount=" + S.amount);
    } catch (e) { /* not available */ }
  }

  function renderAll() {
    var A = computeA(S.route, S.amount);
    app.innerHTML = '<div class="sm-wrap">' + headHtml() + heroHtml(A) + pillsHtml() +
      nowSectionHtml(A) + weekSectionHtml() + cmpSectionHtml(A) + leftOutSectionHtml() + "</div>";
    chart = { A: A, sym: A.sym };
    drawChart();
    var box = document.getElementById("smChart");
    if (box) {
      box.addEventListener("pointermove", hoverChart);
      box.addEventListener("pointerleave", function () {
        var tip = document.getElementById("smTip"), cross = document.getElementById("smCross");
        if (tip) tip.hidden = true;
        if (cross) cross.setAttribute("visibility", "hidden");
      });
      if (window.ResizeObserver) new ResizeObserver(function () { drawChart(); }).observe(box);
    }
    pushUrl();
  }

  function onClick(e) {
    var r = e.target.closest("[data-r]"), a = e.target.closest("[data-a]");
    if (r) {
      var id = r.getAttribute("data-r");
      if (id !== S.route) {
        S.route = id;
        if (!amountObj(routeObj(S.route), S.amount)) S.amount = 5000;
        renderAll();
        if (r.tagName === "BUTTON" && r.classList.contains("sm-row")) window.scrollTo({ top: 0, behavior: "smooth" });
      }
      return;
    }
    if (a) { S.amount = +a.getAttribute("data-a"); renderAll(); }
  }

  function parseRoute(s) {
    if (!s) return null;
    var k = s.replace(/^#?(route=)?/, "").toUpperCase().replace(/[^A-Z]+/g, "-");
    var hit = ORDER.filter(function (id) { return routeKey(id) === k; })[0];
    return hit || null;
  }

  function start(res) {
    COPY = (res[0] && res[0].routeData) || {};
    HOURLY = res[1]; BRK = res[2];
    if (!HOURLY) throw new Error("data");
    HOURLY.hour_columns.forEach(function (c, i) { COL[c] = i; });
    if (BRK) BRK.columns.forEach(function (c, i) { BCOL[c] = i; });
    var q = new URLSearchParams(location.search);
    S.route = parseRoute(q.get("route")) || ORDER[0];
    var amt = +q.get("amount");
    S.amount = amountObj(routeObj(S.route), amt) ? amt : 5000;
    app.addEventListener("click", onClick);
    renderAll();
  }

  Promise.all([maybeJSON("copy.json"), getJSON("data/routes_hourly.json"), maybeJSON("data/routes_breakdown.json")])
    .then(start).catch(function (err) {
      if (window.console) console.error(err);
      maybeJSON("copy.json").then(function (d) {
        COPY = (d && d.routeData) || {};
        app.innerHTML = '<div class="sm-wrap">' + headHtml() + w("loadFailed", null, "p") + "</div>";
      });
    });
})();

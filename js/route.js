/* The routes page (SEB-240, page 2): the routes index and the route page in one.
 *
 * Reads only stored files, built by tools/emit_routes.py:
 *   data/routes_summary.json    route list, default amount, counts, medians, swing, 7-day change
 *   data/routes_hourly.json     every priced hour per route and amount (compact rows), loaded once
 *   data/routes_whatif.json     how much cheaper getting in and out must be for the stablecoin to win
 *   data/routes_breakdown.json  the stablecoin path split into its stored legs, loaded after first paint
 *
 * Which route: ?route=SGD-PHP or #SGD-PHP (the id as stored, "->" written "-"); the first stored
 * route when absent. ?amount=5000 picks the amount; the summary's default amount otherwise.
 *
 * Words: none live here. Every word the page shows comes from copy.json, block "routeData".
 * A key that is empty renders no element. Numbers, dates, percentages, currency codes and route
 * labels (SGD → PHP, formed from the stored currency codes) are code, formatted here.
 * A value that is not stored (null) is an empty slot: never filled, carried forward or estimated.
 */
(function () {

  var DAY = 86400, HOUR = 3600;
  var BREAK_GAP = 6 * HOUR; // a longer hole in the stored hours breaks the line

  var COPY = {};
  var app = document.getElementById("app");
  var SUM = null, HOURLY = null, WHAT = null, BRK = null, brkState = "idle";
  var COL = {};          // hourly column name -> index
  var BCOL = {};         // breakdown column name -> index
  var S = { route: null, amount: null, unit: "abs", period: "all", metric: "typical", sel: null, bday: null }; // Default to typical
  var rowCache = {};
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
  // An element for a copy slot, or nothing at all while the slot is empty.
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
  function dec(v, d) { // fixed decimals, never a "-0.00"
    if (v == null || !isFinite(v)) return "";
    if (Math.abs(v) < Math.pow(10, -d) / 2) v = 0;
    return num(v, d);
  }
  function whole(v) { return v == null ? "" : num(v, 0); }
  function ep(s) { return Date.parse(s) / 1000; }
  function dayShort(t) { return new Date(t * 1000).toLocaleDateString("en-US", { day: "numeric", month: "short", timeZone: "UTC" }); }
  function clock(t) { return new Date(t * 1000).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: "UTC", timeZoneName: "short" }); }
  function stamp(t) { return dayShort(t) + ", " + clock(t); }
  function dayKey(t) { return new Date(t * 1000).toISOString().slice(0, 10); }
  function median(a) {
    var s = a.slice().sort(function (x, y) { return x - y; }), n = s.length;
    return n % 2 ? s[(n - 1) / 2] : (s[n / 2 - 1] + s[n / 2]) / 2;
  }

  function routeKey(id) { return id.replace("->", "-"); }
  function routeLabel(r) { return r.send_ccy + " → " + r.recv_ccy; }
  function routeById(id) { return HOURLY.routes.filter(function (r) { return r.id === id; })[0]; }
  function sumRoute(id) { return SUM.routes.filter(function (r) { return r.id === id; })[0]; }
  function sumAmount(id, amount) {
    var r = sumRoute(id);
    return r && r.amounts.filter(function (a) { return a.amount === amount; })[0];
  }
  function cur() { return routeById(S.route); }
  // A route is comparable unless the stablecoin cost is measured below zero at some amount
  // (data/routes_summary.json `comparable`, written by tools/emit_routes.py).
  function comparable(id) { var s = sumRoute(id); return !s || s.comparable !== false; }
  // "USDC:ArbitrumOne" -> "USDC · Arbitrum One": a stored path id made readable, no words added.
  function pathName(id) { return id ? String(id).replace(":", " · ").replace(/([a-z])([A-Z])/g, "$1 $2") : ""; }
  function ccy() { return cur().send_ccy; }

  // A cost: in the sending currency, or as a share of the amount.
  function cost(v) { return v == null ? "" : dec(v, 2) + " " + ccy(); }
  function pc(v) { return v == null ? "" : dec(v, 2) + "%"; }
  function val(abs, rel) { return S.unit === "abs" ? cost(abs) : pc(rel); }

  // ---------------------------------------------------------------- the stored hours
  function rowsFor(id, amount) {
    var k = id + "|" + amount;
    if (rowCache[k]) return rowCache[k];
    var r = routeById(id), a = r && r.amounts.filter(function (x) { return x.amount === amount; })[0];
    var out = (a ? a.hours : []).map(function (h) {
      return {
        t: ep(h[COL.hour_utc]), sc: h[COL.stable_cost], scp: h[COL.stable_cost_pct],
        ac: h[COL.app_cost], acp: h[COL.app_cost_pct], app: h[COL.cheapest_app],
        path: h[COL.stable_path], win: h[COL.stable_cheaper] === true
      };
    });
    rowCache[k] = out;
    return out;
  }
  function sv(r) { return S.unit === "abs" ? r.sc : r.scp; }
  function av(r) { return S.unit === "abs" ? r.ac : r.acp; }
  function extra(r) { var s = sv(r), a = av(r); return s == null || a == null ? null : s - a; }

  function windowFor(rows) {
    var first = rows[0].t, last = rows[rows.length - 1].t, t0 = first;
    if (S.period === "7") t0 = last - 7 * DAY;
    else if (S.period === "30") t0 = last - 30 * DAY;
    t0 = Math.max(first, t0);
    if (last - t0 < HOUR) t0 = last - HOUR;
    return [t0, last];
  }
  function inWindow(rows, t0, t1) { return rows.filter(function (r) { return r.t >= t0 && r.t <= t1; }); }

  // ---------------------------------------------------------------- the chart
  function niceTicks(lo, hi, n) {
    var span = hi - lo || 1, step = Math.pow(10, Math.floor(Math.log10(span / n)));
    var err = span / n / step;
    step *= err >= 5 ? 5 : err >= 2 ? 2 : 1;
    var out = [], v = Math.ceil(lo / step) * step;
    for (; v <= hi + step * 1e-6; v += step) {
      // Round to appropriate decimal places based on step size
      var decimals = Math.max(0, -Math.floor(Math.log10(step)));
      out.push(parseFloat(v.toFixed(decimals)));
    }
    return out;
  }

  // Hand-written SVG. Draws the model it is handed: { t0, t1, rows, yfmt }.
  function createChart(box, opts) {
    var model = null, W = 0, H = 380, selA = null, selB = null, drag = false, fx = null;
    var svg = box.querySelector("svg"), base = box.querySelector(".rc-base"),
      selEl = box.querySelector(".rc-sel"), cross = box.querySelector(".rc-cross"), tip = box.querySelector(".rc-tip");
    if (opts.aria) svg.setAttribute("aria-label", opts.aria);

    function X(t) { return (t - model.t0) / (model.t1 - model.t0) * W; }

    function draw() {
      if (!model) return;
      W = Math.max(200, Math.round(box.clientWidth - 32));
      H = box.clientWidth < 560 ? 280 : 380;
      svg.setAttribute("viewBox", "0 0 " + W + " " + H);
      svg.setAttribute("width", W);
      svg.setAttribute("height", H);
      var top = 20, bot = 30, lo = Infinity, hi = -Infinity;
      model.rows.forEach(function (r) {
        [r.s, r.a].forEach(function (v) { if (v != null) { if (v < lo) lo = v; if (v > hi) hi = v; } });
      });
      if (!isFinite(lo)) { lo = 0; hi = 1; }
      var pad = (hi - lo || 1) * 0.06;
      lo -= pad; hi += pad;
      function Y(v) { return top + (1 - (v - lo) / (hi - lo)) * (H - top - bot); }

      // Draw horizontal grid lines and Y-axis labels outside the plot area
      var g = "";
      var yAxisTicks = niceTicks(lo, hi, 5);
      yAxisTicks.forEach(function (v) {
        var y = Y(v).toFixed(1);
        // Grid line across entire width
        g += '<line x1="0" x2="' + W + '" y1="' + y + '" y2="' + y + '" style="stroke:var(--color-neutral-200);stroke-dasharray:2,2"></line>';
        // Y-axis label outside plot area
        g += '<text x="-10" y="' + (parseFloat(y) + 4) + '" class="rc-ax" text-anchor="end">' + esc(model.yfmt(v)) + "</text>";
      });

      // Draw zero line if it's within range
      if (lo <= 0 && hi >= 0) {
        var zeroY = Y(0).toFixed(1);
        g += '<line x1="0" x2="' + W + '" y1="' + zeroY + '" y2="' + zeroY + '" style="stroke:var(--color-ink);stroke-width:1"></line>';
        g += '<text x="-10" y="' + (parseFloat(zeroY) + 4) + '" class="rc-ax" text-anchor="end" font-weight="bold">0</text>';
      }

      // Draw X-axis labels with weekly date ticks
      var dateTicks = [];
      var startDate = new Date(model.t0 * 1000);
      var endDate = new Date(model.t1 * 1000);
      var weeks = Math.ceil((endDate - startDate) / (7 * 24 * 60 * 60 * 1000));

      // Generate weekly ticks
      for (var i = 0; i <= weeks; i++) {
        var tickDate = new Date(startDate.getTime() + i * 7 * 24 * 60 * 60 * 1000);
        if (tickDate <= endDate) {
          var tickTime = tickDate.getTime() / 1000;
          if (tickTime >= model.t0 && tickTime <= model.t1) {
            dateTicks.push({
              time: tickTime,
              label: tickDate.toLocaleDateString("en-US", { month: "short", day: "numeric" })
            });
          }
        }
      }

      // Draw X-axis labels
      dateTicks.forEach(function (tick) {
        var x = X(tick.time).toFixed(1);
        g += '<text x="' + x + '" y="' + (H - 5) + '" class="rc-ax" text-anchor="middle">' + esc(tick.label) + "</text>";
      });

      // Segments: runs of hours with no hole longer than BREAK_GAP and both prices stored.
      var segs = [], run = [];
      model.rows.forEach(function (r, i) {
        var ok = r.s != null && r.a != null;
        var prev = run.length ? run[run.length - 1] : null;
        if (ok && prev && r.t - prev.t > BREAK_GAP) { segs.push(run); run = []; }
        if (ok) run.push(r);
        else if (run.length) { segs.push(run); run = []; }
      });
      if (run.length) segs.push(run);
      var fill = "", la = "", ls = "";
      segs.forEach(function (sg) {
        if (sg.length === 1) {
          var x = X(sg[0].t).toFixed(1);
          la += "M" + x + " " + Y(sg[0].a).toFixed(1) + "h0";
          ls += "M" + x + " " + Y(sg[0].s).toFixed(1) + "h0";
          return;
        }
        var pa = "", ps = "", back = "";
        sg.forEach(function (r, i) {
          var x = X(r.t).toFixed(1);
          pa += (i ? "L" : "M") + x + " " + Y(r.a).toFixed(1);
          ps += (i ? "L" : "M") + x + " " + Y(r.s).toFixed(1);
        });
        for (var j = sg.length - 1; j >= 0; j--) back += "L" + X(sg[j].t).toFixed(1) + " " + Y(sg[j].a).toFixed(1);
        fill += ps + back + "Z";
        la += pa; ls += ps;
      });
      g += '<path d="' + fill + '" style="fill:var(--data-700);fill-opacity:.16"></path>';
      g += '<path d="' + la + '" fill="none" stroke-width="1.2" stroke-linecap="round" style="stroke:var(--color-ink)"></path>';
      g += '<path d="' + ls + '" fill="none" stroke-width="1.2" stroke-linecap="round" style="stroke:var(--data-700)"></path>';
      base.innerHTML = g;
      selEl.setAttribute("height", H);
      cross.setAttribute("y2", H);
      paintSel();
      paintCross();
    }

    function paintSel() {
      var has = selA != null && selB != null && Math.abs(selB - selA) > 0.005;
      var a = has ? Math.min(selA, selB) : 0, b = has ? Math.max(selA, selB) : 0;
      selEl.setAttribute("x", (a * W).toFixed(1));
      selEl.setAttribute("width", ((b - a) * W).toFixed(1));
      selEl.style.display = has ? "" : "none";
    }
    function paintCross() {
      if (fx == null || !model) { cross.style.display = "none"; tip.style.display = "none"; return; }
      var x = (fx * W).toFixed(1);
      cross.setAttribute("x1", x); cross.setAttribute("x2", x);
      cross.style.display = "";
      var html = opts.tip(model.t0 + fx * (model.t1 - model.t0));
      if (!html) { tip.style.display = "none"; return; }
      tip.innerHTML = html;
      tip.style.display = "";
      tip.style.left = tip.style.right = "";
      if (fx > 0.7) tip.style.right = ((1 - fx) * 100 + 2).toFixed(1) + "%";
      else tip.style.left = (fx * 100 + 2).toFixed(1) + "%";
    }
    function fOf(e) {
      var b = svg.getBoundingClientRect();
      return Math.min(1, Math.max(0, (e.clientX - b.left) / (b.width || 1)));
    }
    function span() { return model.t1 - model.t0; }
    box.addEventListener("pointerdown", function (e) {
      if (!model) return;
      drag = true; selA = selB = fOf(e);
      try { box.setPointerCapture(e.pointerId); } catch (x) { /* not capturable */ }
      paintSel();
    });
    box.addEventListener("pointermove", function (e) {
      if (!model) return;
      fx = fOf(e);
      if (drag) { selB = fx; paintSel(); }
      paintCross();
    });
    box.addEventListener("pointerup", function () {
      if (!drag) return;
      drag = false;
      if (Math.abs(selB - selA) < 0.01) { selA = selB = null; paintSel(); opts.onSelect(null, null); return; }
      var a = Math.min(selA, selB), b = Math.max(selA, selB);
      opts.onSelect(model.t0 + a * span(), model.t0 + b * span());
    });
    function leave() { fx = null; drag = false; paintCross(); }
    box.addEventListener("pointerleave", leave);
    box.addEventListener("pointercancel", leave);
    if (window.ResizeObserver) new ResizeObserver(function () { draw(); }).observe(box);
    else window.addEventListener("resize", draw);

    return {
      update: function (m) { model = m; selA = selB = null; draw(); },
      redraw: function (m) { model = m; draw(); },
      clearSelection: function () { selA = selB = null; paintSel(); }
    };
  }

  // ---------------------------------------------------------------- the page shell
  function head() {
    var meta = "";
    if (HOURLY && txt("lastReading")) {
      var t = ep(HOURLY.as_of_utc), minutes = Math.max(0, Math.round((Date.now() / 1000 - t) / 60));
      meta = '<span class="mono muted r-small">' + esc(txt("lastReading", { time: clock(t), date: dayShort(t), minutes: minutes })) + "</span>";
    }
    return '<header class="r-head"><div class="r-brand"><a class="r-logo mono" href="./index.html">margin.wiki</a>' +
      '<nav class="r-nav">' +
      [["navCountries", "./countries.html"], ["navRoutes", "./sending-money.html", "on"], ["navSources", "./sources.html"],
        ["navFindings", "./findings.html"], ["navHow", "./how-it-works.html"]].map(function (n) {
        var s = (n[0] === "navRoutes") ? "Routes" : txt(n[0]); // Force "Routes" for navRoutes
        return s ? '<a href="' + n[1] + '"' + (n[2] ? ' aria-current="page" class="on"' : "") + ">" + esc(s) + "</a>" : "";
      }).join("") + "</nav></div>" + meta + "</header>";
  }

  function chip(attr, value, on, text) {
    return text ? '<button class="r-chip' + (on ? " on" : "") + '" data-' + attr + '="' + esc(value) + '">' + esc(text) + "</button>" : "";
  }
  function routeChips() {
    return '<div class="r-route-chips-container"><div class="r-chips r-route-chips-scroll" id="rRoutes">' + HOURLY.routes.map(function (r) {
      return chip("route", r.id, r.id === S.route, routeLabel(r));
    }).join("") + "</div></div>";
  }
  function amountChips() {
    var r = sumRoute(S.route), label = txt("amountLabel", { ccy: ccy() });
    return '<div class="r-route-chips-container"><div class="r-chips r-amount-chips-scroll" id="rAmounts">' + (label ? '<span class="soft r-small">' + esc(label) + "</span>" : "") +
      r.amounts.map(function (a) { return chip("amount", a.amount, a.amount === S.amount, whole(a.amount) + " " + ccy()); }).join("") + "</div></div>";
  }

  function buildHero() {
    var r = cur(), s = sumRoute(S.route);
    var vals = { route: routeLabel(r), send: r.send_ccy, recv: r.recv_ccy, amount: whole(S.amount) + " " + r.send_ccy,
      hours: whole(s.total_hours_stable_cheapest), priced: whole(s.hours_priced_any_amount) };
    return '<section class="r-hero r-pull hero bleed"><div class="r-herotext">' + w("headline", vals, "h1", "r-headline r-hero-nowrap") + w("lead", vals, "p", "slead") +
      '</div><div class="r-bigbox">' + (comparable(S.route)
        ? '<span class="r-big mono">' + esc(whole(s.total_hours_stable_cheapest)) + "</span>" + w("bigCaption", vals, "span", "soft")
        : w("routeNotComparable", vals, "span", "msm")) + "</div></section>";
  }

  function chartControls() {
    var r = cur();
    var legend = [["amber", "legendStable", "r-line"], ["blue", "legendApp", "r-line"], ["fill", "legendGap", "r-fill"]].map(function (l) {
      var s = txt(l[1]);
      return s ? '<span class="r-leg"><i class="' + l[2] + (l[0] === "fill" ? "" : " " + l[0]) + '"></i>' + esc(s) + "</span>" : "";
    }).join("");
    var units = chip("unit", "abs", S.unit === "abs", txt("unitAbs", { ccy: r.send_ccy }) || r.send_ccy) +
      chip("unit", "rel", S.unit === "rel", txt("unitRel") || "%");
    var periods = chip("period", "7", S.period === "7", txt("period7")) + chip("period", "30", S.period === "30", txt("period30")) +
      chip("period", "all", S.period === "all", txt("periodAll", { date: dayShort(ep(HOURLY.start + "T00:00:00Z")) }));
    return '<div class="r-controls"><div class="r-legend soft">' + legend + '</div><div class="r-chips">' + units +
      (periods ? '<span class="r-gapx"></span>' + periods : "") + "</div></div>";
  }

  function buildChartSection() {
    return '<section class="r-sec" id="rChartSec"><div id="rChartCtl"></div><div id="rChartSlot"></div>' +
      '<div class="mono muted r-axis" id="rAxis"></div>' + (comparable(S.route) ? '<div class="r-stats" id="rStats"></div>' : '') + '</section>';
  }

  function buildBreakdownSection() {
    var head = w("breakdownHeading", null, "h2") + w("breakdownLead", null, "p", "muted");
    return '<section class="r-sec tall">' + (head ? '<div class="r-sechead">' + head + "</div>" : "") + '<div id="rBrk"></div></section>';
  }

  function buildLower() {
    return '<div class="r-single-column"><section class="r-sec a">' + w("compareHeading", null, "h2") + w("compareLead", null, "p", "msm") +
      '<div id="rCompare"></div></section><section class="r-sec b">' + w("whatHeading", null, "h2") +
      w("whatLead", { amount: whole(S.amount) + " " + ccy(), ccy: ccy() }, "p", "msm") + '<div id="rWhat"></div></section></div>';
  }

  // ---------------------------------------------------------------- the chart section
  function chartModel(rows) {
    var win = windowFor(rows);
    var inW = inWindow(rows, win[0], win[1]);
    return { t0: win[0], t1: win[1], rows: inW.map(function (r) { return { t: r.t, s: sv(r), a: av(r) }; }),
      yfmt: function (v) { return S.unit === "abs" ? num(v, Math.abs(v) >= 100 ? 0 : 2) : num(v, 2) + "%"; } };
  }

  function nearestRow(rows, t) {
    var lo = 0, hi = rows.length - 1;
    if (hi < 0) return null;
    while (hi - lo > 1) { var m = (lo + hi) >> 1; if (rows[m].t < t) lo = m; else hi = m; }
    return Math.abs(rows[lo].t - t) <= Math.abs(rows[hi].t - t) ? rows[lo] : rows[hi];
  }

  function tipHtml(t) {
    var rows = rowsFor(S.route, S.amount), r = nearestRow(rows, t);
    if (!r || Math.abs(r.t - t) > 3 * HOUR) return "";
    function line(cls, key, v, id) {
      return '<div class="r-trow"><i class="r-line ' + cls + '"></i>' + w(key, null, "span", "l") + '<span class="mono">' + esc(v) + "</span>" +
        (id ? '<span class="mono muted">' + esc(id) + "</span>" : "") + "</div>";
    }
    var e = extra(r);
    return '<div class="mono muted">' + esc(stamp(r.t)) + "</div>" + line("amber", "tipStable", val(r.sc, r.scp), r.path) +
      line("blue", "tipApp", val(r.ac, r.acp), r.app) +
      (e != null && txt("tipExtra") ? '<div class="r-trow">' + w("tipExtra", null, "span", "l") + '<span class="mono">' + esc(S.unit === "abs" ? cost(e) : pc(e)) + "</span></div>" : "");
  }

  function statCell(labelKey, value, sub) {
    if (!value) return "";
    return "<div>" + w(labelKey, null, "span", "r-k") + '<span class="mono r-v">' + esc(value) + "</span>" +
      (sub ? '<span class="mono muted r-sub">' + esc(sub) + "</span>" : "") + "</div>";
  }

  // The selection stats, computed here from the stored hours inside the window.
  function drawStats() {
    var rows = rowsFor(S.route, S.amount), el = document.getElementById("rStats");
    if (!el) return;
    if (!rows.length) { el.innerHTML = ""; return; }
    var win = S.sel || windowFor(rows);
    var inW = inWindow(rows, win[0], win[1]);
    var priced = inW.filter(function (r) { return extra(r) != null; });
    var first = inW.length ? inW[0].t : win[0], last = inW.length ? inW[inW.length - 1].t : win[1];
    var cells = statCell("statWindow", dayShort(first) + " – " + dayShort(last));
    if (priced.length) {
      var ex = priced.map(extra);
      var lo = 0, hi = 0;
      ex.forEach(function (v, i) { if (v < ex[lo]) lo = i; if (v > ex[hi]) hi = i; });
      var wins = priced.filter(function (r) { return r.win; }).length;
      var f = S.unit === "abs" ? cost : pc;
      cells += statCell("statCheapest", whole(wins) + " / " + whole(priced.length));
      cells += statCell("statTypical", f(median(ex)));
      cells += statCell("statClosest", f(ex[lo]), stamp(priced[lo].t));
      cells += statCell("statWidest", f(ex[hi]), stamp(priced[hi].t));
    }
    el.innerHTML = cells;
  }

  function drawAxis() {
    var rows = rowsFor(S.route, S.amount), el = document.getElementById("rAxis");
    if (!rows.length) { el.innerHTML = ""; return; }
    var win = windowFor(rows);
    el.innerHTML = "<span>" + esc(dayShort(win[0])) + "</span><span>" +
      esc(txt(S.unit === "abs" ? "chartCaptionAbs" : "chartCaptionRel", { ccy: ccy() })) + "</span><span>" + esc(dayShort(win[1])) + "</span>";
  }

  function drawControls() { document.getElementById("rChartCtl").innerHTML = chartControls(); }

  function drawChart(reset) {
    var rows = rowsFor(S.route, S.amount);
    drawAxis();
    if (!rows.length) { if (document.getElementById("rStats")) document.getElementById("rStats").innerHTML = ""; return; }
    var m = chartModel(rows);
    if (reset) { S.sel = null; chart.update(m); } else chart.redraw(m);
    drawStats();
  }

  function mountChart() {
    var slot = document.getElementById("rChartSlot");
    slot.parentNode.replaceChild(document.getElementById("rChartTpl").content.cloneNode(true), slot);
    chart = createChart(document.getElementById("rChart"), {
      tip: tipHtml, aria: txt("chartAria"),
      onSelect: function (a, b) { S.sel = a == null ? null : [a, b]; drawStats(); }
    });
  }

  // ---------------------------------------------------------------- the cost breakdown
  // Legs as stored. getting in = deposit + buy, cashing out = sell + withdrawal. A leg that is null,
  // or whose fee is flagged unmeasured, is an empty slot. "Converting" is not stored as a leg of its
  // own (it sits inside the buy and sell legs), so it has no row.
  function brkDays() {
    var r = BRK && BRK.routes.filter(function (x) { return x.id === S.route; })[0];
    var a = r && r.amounts.filter(function (x) { return x.amount === S.amount; })[0];
    if (!a || !a.rows.length) return [];
    var days = [], last = null;
    a.rows.forEach(function (row) {
      var k = row[BCOL.hour_utc].slice(0, 10);
      if (last && last.k === k) last.row = row; else { last = { k: k, row: row }; days.push(last); }
    });
    return days;
  }
  function legs(row) {
    function g(c) { return row[BCOL[c]]; }
    var dep = g("deposit_measured") === false ? null : g("getting_in_deposit");
    var wd = g("withdrawal_measured") === false ? null : g("cashing_out_withdrawal");
    var buy = g("getting_in_buy"), sell = g("cashing_out_sell");
    return {
      inn: dep != null && buy != null ? dep + buy : null,
      chain: g("on_chain"),
      out: sell != null && wd != null ? sell + wd : null,
      total: g("total"), totalPct: g("total_pct"), app: g("app_cost"), appPct: g("app_cost_pct")
    };
  }
  function legUnit(v) { return v == null ? null : S.unit === "abs" ? v : v / S.amount * 100; }

  var LEG_ROWS = [["legGettingIn", "inn", "--data-400"], ["legOnChain", "chain", "--data-700"], ["legCashingOut", "out", "--data-700"]];

  function buildBreakdown() {
    var el = document.getElementById("rBrk");
    if (!el) return;
    if (brkState === "failed") { el.innerHTML = w("breakdownFailed", null, "p", "muted"); return; }
    if (!BRK) { el.innerHTML = w("breakdownLoading", null, "p", "muted"); return; }
    var days = brkDays();
    if (!days.length) { el.innerHTML = ""; return; }
    if (S.bday == null || S.bday >= days.length) S.bday = days.length - 1;
    var rowsHtml = LEG_ROWS.map(function (l) {
      var name = txt(l[0]);
      return '<div class="r-leg-row"><span class="r-legname"><i class="r-sw" style="background:var(' + l[2] + ')"></i>' + esc(name) +
        '</span><span class="r-track r-steps-full-width"><i data-leg="' + l[1] + '" style="background:var(' + l[2] + ');width:0" class="r-steps-stablecoin-track"></i></span>' +
        '<span class="mono r-legval" data-val="' + l[1] + '"></span></div>';
    }).join("");
    function extraRow(key, id, colour, alt) {
      return '<div class="r-leg-row"><span class="r-legname"><i class="r-sw" style="background:var(' + colour + ')"></i>' + esc(txt(key)) +
        '</span><span class="r-track r-steps-full-width' + (alt ? " alt" : "") + '"><i data-leg="' + id + '" style="background:var(' + colour + ');width:0" class="r-cheapest-track-equal"></i></span>' +
        '<span class="mono r-legval" data-val="' + id + '"></span>' +
        (id === "app" ? '<span class="mono muted r-prov" data-name="app"></span>' : "") + "</div>";
    }
    el.innerHTML =
      '<label class="muted r-slider"><span>' + esc(txt("sliderLabel")) + ' <span class="mono" id="rBDay" style="color:var(--color-ink)"></span></span>' +
      '<input type="range" id="rBSlider" min="0" max="' + (days.length - 1) + '" value="' + S.bday + '"></label>' +
      '<div class="r-stack" id="rStack"></div>' +
      '<div class="r-list">' + rowsHtml + extraRow("legTotal", "total", "--color-neutral-700") + extraRow("legApp", "app", "--color-ink") + "</div>" +
      '<div id="rBNote"></div>';
    updateBreakdown();
  }

  function updateBreakdown() {
    var days = brkDays(), el = document.getElementById("rBrk");
    if (!days.length || !document.getElementById("rBSlider")) return;
    var d = days[S.bday], L = legs(d.row);
    var vals = { inn: legUnit(L.inn), chain: legUnit(L.chain), out: legUnit(L.out),
      total: S.unit === "abs" ? L.total : L.totalPct, app: S.unit === "abs" ? L.app : L.appPct };
    // One scale for every day, so the bars read against each other as the slider moves.
    var max = 0;
    days.forEach(function (x) {
      var l = legs(x.row);
      [S.unit === "abs" ? l.total : l.totalPct, S.unit === "abs" ? l.app : l.appPct, legUnit(l.inn), legUnit(l.chain), legUnit(l.out)]
        .forEach(function (v) { if (v != null && Math.abs(v) > max) max = Math.abs(v); });
    });
    max = max * 1.05 || 1;
    function fmt(v) { return v == null ? "" : S.unit === "abs" ? cost(v) : pc(v); }
    Object.keys(vals).forEach(function (k) {
      var bar = el.querySelector('[data-leg="' + k + '"]'), out = el.querySelector('[data-val="' + k + '"]');
      var v = vals[k];
      if (bar) {
        bar.style.width = v == null ? "0" : (Math.abs(v) / max * 100).toFixed(2) + "%";
        bar.style.opacity = v != null && v < 0 ? ".5" : "";
        // Apply distinct colors for each leg
        if (k === "inn") bar.style.background = "var(--data-700)";
        else if (k === "chain") bar.style.background = "var(--data-500)";
        else if (k === "out") bar.style.background = "var(--data-300)";
        else if (k === "total") bar.style.background = "var(--color-neutral-700)";
        else if (k === "app") bar.style.background = "var(--color-ink)";
      }
      if (out) out.textContent = fmt(v);
    });
    // The stacked bar: the stored legs side by side, only while every leg is stored and none is negative.
    var all = vals.inn != null && vals.chain != null && vals.out != null && vals.inn >= 0 && vals.chain >= 0 && vals.out >= 0;
    document.getElementById("rStack").innerHTML = all ? LEG_ROWS.map(function (l, index) {
      var colors = ["var(--data-700)", "var(--data-500)", "var(--data-300)"];
      return '<div class="r-seg" style="background:' + colors[index] + ';width:' + (vals[l[1]] / max * 100).toFixed(2) + '%"></div>';
    }).join("") : "";
    var nm = el.querySelector('[data-name="app"]');
    if (nm) nm.textContent = d.row[BCOL.cheapest_app] || "";
    document.getElementById("rBDay").textContent = stamp(ep(d.row[BCOL.hour_utc]));
    var missing = vals.inn == null || vals.chain == null || vals.out == null;
    var unmeasured = d.row[BCOL.deposit_measured] === false || d.row[BCOL.withdrawal_measured] === false;
    document.getElementById("rBNote").innerHTML =
      (missing ? w("legsMissing", { date: dayShort(ep(d.row[BCOL.hour_utc])) }, "p", "msm") : "") +
      (unmeasured ? w("legsUnmeasured", { date: dayShort(ep(d.row[BCOL.hour_utc])) }, "p", "msm") : "");
  }

  // ---------------------------------------------------------------- all routes compared
  var METRICS = [["typical", "metricTypical"], ["win", "metricWin"], ["swing", "metricSwing"], ["change", "metricChange"]]; // Make typical the default
  function metricValue(a, m) { // [value in the chosen unit, null when not stored]
    if (!a) return null;
    if (m === "win") return a.win_rate_pct;
    var f = { typical: ["median_extra", "median_extra_pp"], swing: ["swing", "swing_pp"], change: ["change_7d", "change_7d_pp"] }[m];
    return a[S.unit === "abs" ? f[0] : f[1]];
  }
  function drawCompare() {
    if (!document.getElementById("rCompare")) return;
    var chips = METRICS.map(function (m) { return chip("metric", m[0], S.metric === m[0], txt(m[1])); }).join("");
    var shown = HOURLY.routes.filter(function (r) { return comparable(r.id); });
    var left = HOURLY.routes.filter(function (r) { return !comparable(r.id); });
    var vs = shown.map(function (r) { return metricValue(sumAmount(r.id, S.amount), S.metric); });

    // Filter out routes with no data
    var validRoutes = [];
    var validValues = [];
    vs.forEach(function (v, i) {
      if (v != null) {
        validRoutes.push(shown[i]);
        validValues.push(v);
      }
    });

    if (validRoutes.length === 0) {
      // Show a default message when no routes have data
      document.getElementById("rCompare").innerHTML = (chips ? '<div class="r-chips">' + chips + "</div>" : "") +
        '<div class="r-comparison-chart-default">No comparison data available</div>' +
        (left.length ? w("notComparable", { routes: left.map(routeLabel).join(", ") }, "p", "msm") : "");
      return;
    }

    var max = 0;
    validValues.forEach(function (v) { if (Math.abs(v) > max) max = Math.abs(v); });

    var rows = validRoutes.map(function (r, i) {
      var v = validValues[i], width = !max ? 0 : S.metric === "win" ? v : Math.abs(v) / max * 100;
      var text = S.metric === "win" ? dec(v, 1) + "%" : S.unit === "abs" ? dec(v, 2) + " " + r.send_ccy : pc(v);
      return '<button class="r-mrow' + (r.id === S.route ? " sel" : "") + '" data-route="' + esc(r.id) + '"><span class="mono r-mcode">' +
        esc(routeLabel(r)) + '</span><span class="r-track alt"><i style="background:var(' + (v < 0 ? "--color-neutral-700" : "--data-700") +
        ");width:" + width.toFixed(1) + '%"></i></span><span class="mono r-mval">' + esc(text) + "</span></button>";
    }).join("");

    document.getElementById("rCompare").innerHTML = (chips ? '<div class="r-chips">' + chips + "</div>" : "") + '<div class="r-list">' + rows + "</div>" +
      (left.length ? w("notComparable", { routes: left.map(routeLabel).join(", ") }, "p", "msm") : "");
  }

  // ---------------------------------------------------------------- what would have to change
  function whatFor(id) {
    var r = WHAT && WHAT.routes.filter(function (x) { return x.id === id; })[0];
    return r && r.amounts.filter(function (a) { return a.amount === S.amount; })[0];
  }
  function drawWhat() {
    if (!document.getElementById("rWhat")) return;
    var left = HOURLY.routes.filter(function (r) { return !comparable(r.id); });
    var pathNote = "";

    // Create a compact table structure
    var out = '<div class="r-what-compact-table">';
    out += '<div><span>Route</span><span>Median needed</span><span>Latest needed</span></div>'; // Header row

    HOURLY.routes.filter(function (r) { return comparable(r.id); }).forEach(function (r) {
      var a = whatFor(r.id), m = a && a.median_7d, l = a && a.latest_hour;
      function money(o, key) { return o && o[key] != null ? dec(o[key], 2) + " " + r.send_ccy : ""; }
      function ppv(o, key) { return o && o[key] != null ? dec(o[key], 2) + "%" : ""; }

      var medianText = "";
      var latestText = "";

      if (m && m.already_wins) {
        medianText = "Already wins";
      } else if (m) {
        var units = money(m, "cheaper_needed"), pp = ppv(m, "cheaper_needed_pp");
        medianText = [units, pp].filter(Boolean).join(" · ");
      }

      if (l && l.already_wins === false) {
        var lu = money(l, "cheaper_needed"), lp = ppv(l, "cheaper_needed_pp");
        latestText = [lu, lp].filter(Boolean).join(" · ");
      } else if (l && l.already_wins) {
        latestText = "Already wins";
      }

      out += '<div><span>' + esc(routeLabel(r)) + '</span><span>' + esc(medianText) + '</span><span>' + esc(latestText) + '</span></div>';

      // Handle notes separately
      if (m && !m.already_wins) {
        if (m.cheapest_app_changed) {
          out += '<div><span colspan="3" class="msm">' + esc(w("whatAppChanged", { app: m.cheapest_app_week || "", hours: whole(m.cheapest_app_week_hours), of: whole(m.n_hours) })) + '</span></div>';
        }
        var share = m.cheaper_needed_pct_of_in_out;
        if (share != null) {
          out += '<div><span colspan="3" class="msm">' + esc(w("whatShare", { pct: dec(share, 0) + "%" })) + '</span></div>';
        }
      }

      if (l && l.already_wins === false && !pathNote && l.stable_path && l.base_path && l.stable_path !== l.base_path) {
        pathNote = w("whatPathNote", { path: pathName(l.stable_path), base: pathName(l.base_path), hour: stamp(ep(l.hour_utc)) });
      }
    });

    out += '</div>'; // Close table

    document.getElementById("rWhat").innerHTML = out + (pathNote ? '<p class="msm">' + esc(pathNote) + '</p>' : '') +
      (left.length ? '<p class="msm">' + esc(w("notComparable", { routes: left.map(routeLabel).join(", ") })) + '</p>' : '');
  }

  // ---------------------------------------------------------------- state and wiring
  function parseRoute(s) {
    if (!s) return null;
    var k = s.replace(/^#?(route=)?/, "").toUpperCase().replace(/[^A-Z]+/g, "-");
    var hit = HOURLY.routes.filter(function (r) { return routeKey(r.id) === k; })[0];
    return hit ? hit.id : null;
  }
  function pushUrl() {
    try {
      var q = "?route=" + routeKey(S.route) + "&amount=" + S.amount;
      history.replaceState(null, "", location.pathname + q);
    } catch (e) { /* not available */ }
  }

  function renderAll() {
    S.sel = null;
    app.innerHTML = '<div class="r-wrap">' + head() + '<div class="r-top">' + routeChips() + amountChips() + "</div>" + buildHero() + buildChartSection() +
      (comparable(S.route) ? buildBreakdownSection() + buildLower() : "") + "</div>";
    mountChart();
    drawControls();
    drawChart(true);
    buildBreakdown();
    drawCompare();
    drawWhat();
    pushUrl();
  }

  function onClick(e) {
    var b = e.target.closest("button[data-route],button[data-amount],button[data-unit],button[data-period],button[data-metric]");
    if (!b) return;
    if (b.hasAttribute("data-route")) {
      if (b.getAttribute("data-route") !== S.route) { S.route = b.getAttribute("data-route"); S.bday = null; renderAll(); }
      return;
    }
    if (b.hasAttribute("data-amount")) { S.amount = +b.getAttribute("data-amount"); S.bday = null; renderAll(); return; }
    if (b.hasAttribute("data-unit")) { S.unit = b.getAttribute("data-unit"); drawControls(); drawChart(false); updateBreakdown(); drawCompare(); return; }
    if (b.hasAttribute("data-period")) { S.period = b.getAttribute("data-period"); drawControls(); drawChart(true); return; }
    if (b.hasAttribute("data-metric")) { S.metric = b.getAttribute("data-metric"); drawCompare(); }
  }
  function onInput(e) {
    if (e.target.id === "rBSlider") { S.bday = +e.target.value; updateBreakdown(); }
  }

  function loadBreakdown() {
    if (brkState !== "idle") return;
    brkState = "loading";
    getJSON("data/routes_breakdown.json").then(function (d) {
      BRK = d;
      d.columns.forEach(function (c, i) { BCOL[c] = i; });
      brkState = "done";
      buildBreakdown();
    }).catch(function () { brkState = "failed"; buildBreakdown(); });
  }

  function start(res) {
    COPY = (res[0] && res[0].routeData) || {};
    SUM = res[1]; HOURLY = res[2]; WHAT = res[3];
    if (!SUM || !HOURLY) throw new Error("data");
    HOURLY.hour_columns.forEach(function (c, i) { COL[c] = i; });
    var q = new URLSearchParams(location.search);
    S.route = parseRoute(q.get("route")) || parseRoute(location.hash) || HOURLY.routes[0].id;
    var amt = +q.get("amount");
    var rs = sumRoute(S.route);
    S.amount = rs.amounts.some(function (a) { return a.amount === amt; }) ? amt : rs.default_amount;
    app.addEventListener("click", onClick);
    app.addEventListener("input", onInput);
    window.addEventListener("hashchange", function () {
      var id = parseRoute(location.hash);
      if (id && id !== S.route) { S.route = id; S.bday = null; renderAll(); }
    });
    renderAll();
    loadBreakdown();
  }

  Promise.all([maybeJSON("copy.json"), getJSON("data/routes_summary.json"), getJSON("data/routes_hourly.json"), maybeJSON("data/routes_whatif.json")])
    .then(start).catch(function (err) {
      if (window.console) console.error(err);
      maybeJSON("copy.json").then(function (d) {
        COPY = (d && d.routeData) || {};
        app.innerHTML = '<div class="r-wrap">' + head() + w("loadFailed", null, "p", "soft") + "</div>";
      });
    });
})();

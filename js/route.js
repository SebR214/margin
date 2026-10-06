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
  var S = { route: null, amount: null, unit: "abs", period: "all", metric: "typical", sel: null, bday: null };
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
  // Ticks at round steps. Returns { ticks, step } so labels can print no decimals on round values.
  function niceTicks(lo, hi, n) {
    var span = hi - lo || 1, step = Math.pow(10, Math.floor(Math.log10(span / n)));
    var err = span / n / step;
    step *= err >= 5 ? 5 : err >= 2 ? 2 : 1;
    var out = [], k = Math.ceil(lo / step - 1e-9);
    for (; k * step <= hi + step * 1e-6; k++) out.push(Math.round(k * step * 1e9) / 1e9 + 0);
    return { ticks: out, step: step };
  }
  // A tick label: whole numbers carry no decimals, other values the decimals the step needs.
  function tickLabel(v, step, pct) {
    var d = step >= 1 ? 0 : Math.min(3, Math.ceil(-Math.log10(step) - 1e-9));
    return num(v, Math.abs(v - Math.round(v)) < 1e-9 ? 0 : d) + (pct ? "%" : "");
  }
  // X ticks: weekly (Mondays, UTC) on long windows, daily on short ones, every six hours inside two days.
  function xTicks(t0, t1) {
    var span = t1 - t0, out = [], t;
    if (span <= 2 * DAY) {
      for (t = Math.ceil(t0 / (6 * HOUR)) * 6 * HOUR; t <= t1; t += 6 * HOUR) out.push({ t: t, label: clock(t).slice(0, 5) });
    } else if (span <= 14 * DAY) {
      for (t = Math.ceil(t0 / DAY) * DAY; t <= t1; t += DAY) out.push({ t: t, label: dayShort(t) });
    } else {
      t = Math.ceil(t0 / DAY) * DAY;
      while (new Date(t * 1000).getUTCDay() !== 1) t += DAY;
      for (; t <= t1; t += 7 * DAY) out.push({ t: t, label: dayShort(t) });
    }
    return out;
  }

  // Hand-written SVG. Draws the model it is handed: { t0, t1, rows, gap, pct }.
  function createChart(box, opts) {
    var ML = 52, MR = 10, TOP = 14, BOT = 26; // left margin holds the y labels, outside the plot
    var model = null, W = 0, H = 380, PW = 0, selA = null, selB = null, drag = false, fx = null;
    var svg = box.querySelector("svg"), base = box.querySelector(".rc-base"),
      selEl = box.querySelector(".rc-sel"), cross = box.querySelector(".rc-cross"), tip = box.querySelector(".rc-tip");
    if (opts.aria) svg.setAttribute("aria-label", opts.aria);

    function X(t) { return ML + (t - model.t0) / (model.t1 - model.t0) * PW; }

    function draw() {
      if (!model) return;
      W = Math.max(200, Math.round(box.clientWidth - 32));
      PW = W - ML - MR;
      H = box.clientWidth < 560 ? 280 : 380;
      svg.setAttribute("viewBox", "0 0 " + W + " " + H);
      svg.setAttribute("width", W);
      svg.setAttribute("height", H);
      var lo = 0, hi = -Infinity; // zero is always in view: the zero line is labelled
      model.rows.forEach(function (r) {
        [r.s, r.a].forEach(function (v) { if (v != null) { if (v < lo) lo = v; if (v > hi) hi = v; } });
      });
      if (!isFinite(hi)) hi = 1;
      var pad = (hi - lo || 1) * 0.06;
      hi += pad; if (lo < 0) lo -= pad;
      function Y(v) { return TOP + (1 - (v - lo) / (hi - lo)) * (H - TOP - BOT); }

      var g = "", nt = niceTicks(lo, hi, 4);
      nt.ticks.forEach(function (v) {
        var y = Y(v).toFixed(1), zero = v === 0;
        g += '<line x1="' + ML + '" x2="' + (W - MR) + '" y1="' + y + '" y2="' + y + '" style="stroke:' +
          (zero ? "var(--color-ink)" : "var(--color-neutral-200)") + (zero ? ";stroke-width:1" : "") + '"></line>' +
          '<text x="' + (ML - 8) + '" y="' + (+y + 4) + '" class="rc-ax" text-anchor="end"' + (zero ? ' style="fill:var(--color-ink)"' : "") + ">" +
          esc(tickLabel(v, nt.step, !model.abs)) + "</text>";
      });
      var lastX = -1e9;
      xTicks(model.t0, model.t1).forEach(function (tk) {
        var x = X(tk.t);
        if (x - lastX < 52 || x < ML + 14 || x > W - MR - 14) return;
        lastX = x;
        g += '<line x1="' + x.toFixed(1) + '" x2="' + x.toFixed(1) + '" y1="' + (H - BOT) + '" y2="' + (H - BOT + 4) + '" style="stroke:var(--color-neutral-400)"></line>' +
          '<text x="' + x.toFixed(1) + '" y="' + (H - 6) + '" class="rc-ax" text-anchor="middle">' + esc(tk.label) + "</text>";
      });

      // Segments: runs with no hole longer than model.gap and both prices stored. A run of one point is
      // not drawn: no stray dots in the gaps.
      var segs = [], run = [];
      model.rows.forEach(function (r) {
        var ok = r.s != null && r.a != null;
        var prev = run.length ? run[run.length - 1] : null;
        if (ok && prev && r.t - prev.t > model.gap) { segs.push(run); run = []; }
        if (ok) run.push(r);
        else if (run.length) { segs.push(run); run = []; }
      });
      if (run.length) segs.push(run);
      var fill = "", la = "", ls = "";
      segs.forEach(function (sg) {
        if (sg.length < 2) return;
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
      g += '<path d="' + la + '" fill="none" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" style="stroke:var(--color-ink)"></path>';
      g += '<path d="' + ls + '" fill="none" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" style="stroke:var(--data-700)"></path>';
      base.innerHTML = g;
      selEl.setAttribute("y", TOP);
      selEl.setAttribute("height", H - TOP - BOT);
      cross.setAttribute("y1", TOP);
      cross.setAttribute("y2", H - BOT);
      paintSel();
      paintCross();
    }

    function paintSel() {
      var has = selA != null && selB != null && Math.abs(selB - selA) > 0.005;
      var a = has ? Math.min(selA, selB) : 0, b = has ? Math.max(selA, selB) : 0;
      selEl.setAttribute("x", (ML + a * PW).toFixed(1));
      selEl.setAttribute("width", ((b - a) * PW).toFixed(1));
      selEl.style.display = has ? "" : "none";
    }
    function paintCross() {
      if (fx == null || !model) { cross.style.display = "none"; tip.style.display = "none"; return; }
      var x = (ML + fx * PW).toFixed(1);
      cross.setAttribute("x1", x); cross.setAttribute("x2", x);
      cross.style.display = "";
      var html = opts.tip(model.t0 + fx * (model.t1 - model.t0));
      if (!html) { tip.style.display = "none"; return; }
      tip.innerHTML = html;
      tip.style.display = "";
      tip.style.left = tip.style.right = "";
      var px = 16 + ML + fx * PW; // box padding + plot offset
      if (fx > 0.6) tip.style.right = Math.max(0, box.clientWidth - px + 12).toFixed(0) + "px";
      else tip.style.left = (px + 12).toFixed(0) + "px";
    }
    function fOf(e) {
      var b = svg.getBoundingClientRect();
      return Math.min(1, Math.max(0, (e.clientX - b.left - ML) / (PW || 1)));
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
      redraw: function (m) { model = m; selA = selB = null; draw(); },
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
        var s = txt(n[0]);
        return s ? '<a href="' + n[1] + '"' + (n[2] ? ' aria-current="page" class="on"' : "") + ">" + esc(s) + "</a>" : "";
      }).join("") + "</nav></div>" + meta + "</header>";
  }

  function chip(attr, value, on, text) {
    return text ? '<button class="r-chip' + (on ? " on" : "") + '" data-' + attr + '="' + esc(value) + '">' + esc(text) + "</button>" : "";
  }
  function routeChips() {
    return '<div class="r-chips r-scrollrow" id="rRoutes">' + HOURLY.routes.map(function (r) {
      return chip("route", r.id, r.id === S.route, routeLabel(r));
    }).join("") + "</div>";
  }
  function amountChips() {
    var r = sumRoute(S.route), label = txt("amountLabel", { ccy: ccy() });
    return '<div class="r-chips r-scrollrow" id="rAmounts">' + (label ? '<span class="soft r-small">' + esc(label) + "</span>" : "") +
      r.amounts.map(function (a) { return chip("amount", a.amount, a.amount === S.amount, whole(a.amount) + " " + ccy()); }).join("") + "</div>";
  }

  // The headline, with the route name kept on one line (a no-break span around it).
  function headline(vals) {
    var t = txt("headline", vals);
    if (!t) return "";
    var h = esc(t), name = esc(vals.route);
    return "<h1>" + (name && h.indexOf(name) >= 0 ? h.replace(name, '<span class="r-nobreak">' + name + "</span>") : h) + "</h1>";
  }

  function buildHero() {
    var r = cur(), s = sumRoute(S.route);
    var vals = { route: routeLabel(r), send: r.send_ccy, recv: r.recv_ccy, amount: whole(S.amount) + " " + r.send_ccy,
      hours: whole(s.total_hours_stable_cheapest), priced: whole(s.hours_priced_any_amount) };
    return '<section class="r-hero r-pull hero bleed"><div class="r-herotext">' + headline(vals) + w("lead", vals, "p", "slead") +
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
    if (!comparable(S.route)) return ""; // a route that is not comparable shows its note, not a chart that implies a comparison
    return '<section class="r-sec" id="rChartSec"><div id="rChartCtl"></div><div id="rChartSlot"></div>' +
      '<div class="mono muted r-axis" id="rAxis"></div><div class="msm" id="rMissing"></div><div class="r-stats" id="rStats"></div></section>';
  }

  function buildBreakdownSection() {
    var head = w("breakdownHeading", null, "h2") + w("breakdownLead", null, "p", "muted");
    return '<section class="r-sec tall">' + (head ? '<div class="r-sechead">' + head + "</div>" : "") + '<div id="rBrk"></div></section>';
  }

  function buildLower() {
    return '<div class="r-lower"><section class="r-sec">' + w("compareHeading", null, "h2") + w("compareLead", null, "p", "msm") +
      '<div id="rCompare"></div></section><section class="r-sec">' + w("whatHeading", null, "h2") +
      w("whatLead", { amount: whole(S.amount) + " " + ccy(), ccy: ccy() }, "p", "msm") + '<div id="rWhat"></div></section></div>';
  }

  // ---------------------------------------------------------------- the chart section
  // The window on screen: the zoomed selection when there is one, else the chosen period.
  function curWin(rows) { return S.sel || windowFor(rows); }
  // Daily line by default (the median of each day's stored hours); the hours themselves once the
  // window is a week or less (a period of a week, or a zoom to a week). The tooltip is always hourly.
  function chartModel(rows) {
    var win = curWin(rows), inW = inWindow(rows, win[0], win[1]), hourly = win[1] - win[0] <= 7 * DAY + HOUR, pts;
    if (hourly) pts = inW.map(function (r) { return { t: r.t, s: sv(r), a: av(r) }; });
    else {
      var days = {}, order = [];
      inW.forEach(function (r) {
        var s = sv(r), a = av(r), k = dayKey(r.t);
        if (s == null || a == null) return;
        if (!days[k]) { days[k] = { t: Math.floor(r.t / DAY) * DAY + DAY / 2, s: [], a: [] }; order.push(k); }
        days[k].s.push(s); days[k].a.push(a);
      });
      pts = order.map(function (k) {
        var d = days[k];
        return { t: Math.min(win[1], Math.max(win[0], d.t)), s: median(d.s), a: median(d.a) };
      });
    }
    return { t0: win[0], t1: win[1], rows: pts, abs: S.unit === "abs", gap: hourly ? BREAK_GAP : 1.5 * DAY };
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
    var win = curWin(rows);
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
    var rows = rowsFor(S.route, S.amount), el = document.getElementById("rAxis"), miss = document.getElementById("rMissing");
    if (!el) return;
    if (!rows.length) { el.innerHTML = ""; if (miss) miss.innerHTML = ""; return; }
    var win = curWin(rows);
    el.innerHTML = "<span>" + esc(dayShort(win[0])) + "</span><span>" +
      esc(txt(S.unit === "abs" ? "chartCaptionAbs" : "chartCaptionRel", { ccy: ccy() })) + "</span><span>" + esc(dayShort(win[1])) + "</span>";
    // Hours in the window with no stored pair of prices, counted from the stored hours.
    var priced = inWindow(rows, win[0], win[1]).filter(function (r) { return r.sc != null && r.ac != null; }).length;
    var missing = Math.max(0, Math.floor((win[1] - win[0]) / HOUR) + 1 - priced);
    if (miss) miss.innerHTML = missing > 0 ? w("chartMissing", { missing: whole(missing), priced: whole(priced) }, "p", "msm") : "";
  }

  function drawControls() { var el = document.getElementById("rChartCtl"); if (el) el.innerHTML = chartControls(); }

  function drawChart(reset) {
    var rows = rowsFor(S.route, S.amount);
    if (!chart) return;
    if (reset) S.sel = null;
    drawAxis();
    if (!rows.length) { if (document.getElementById("rStats")) document.getElementById("rStats").innerHTML = ""; return; }
    var m = chartModel(rows);
    if (reset) chart.update(m); else chart.redraw(m);
    drawStats();
  }

  function mountChart() {
    var slot = document.getElementById("rChartSlot");
    slot.parentNode.replaceChild(document.getElementById("rChartTpl").content.cloneNode(true), slot);
    chart = createChart(document.getElementById("rChart"), {
      tip: tipHtml, aria: txt("chartAria"),
      onSelect: function (a, b) {
        if (a != null && b - a < 6 * HOUR) { var c = (a + b) / 2; a = c - 3 * HOUR; b = c + 3 * HOUR; }
        S.sel = a == null ? null : [a, b];
        drawChart(false);
      }
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

  // Three steps, three colours; the all-in stablecoin row wears the stablecoin colour of the chart line.
  var LEG_ROWS = [["legGettingIn", "inn", "--data-400"], ["legOnChain", "chain", "--data-600"], ["legCashingOut", "out", "--data-500"]];
  var COLOUR = { inn: "--data-400", chain: "--data-600", out: "--data-500", total: "--data-700", app: "--color-ink" };

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
        '</span><span class="r-track"><i data-leg="' + l[1] + '" style="background:var(' + l[2] + ');width:0"></i></span>' +
        '<span class="mono r-legval" data-val="' + l[1] + '"></span></div>';
    }).join("");
    function extraRow(key, id, colour, alt) {
      return '<div class="r-leg-row"><span class="r-legname"><i class="r-sw" style="background:var(' + colour + ')"></i><span class="r-legtxt">' + esc(txt(key)) +
        (id === "app" ? '<span class="mono muted r-prov" data-name="app"></span>' : "") + '</span>' +
        '</span><span class="r-track' + (alt ? " alt" : "") + '"><i data-leg="' + id + '" style="background:var(' + colour + ');width:0"></i></span>' +
        '<span class="mono r-legval" data-val="' + id + '"></span></div>';
    }
    el.innerHTML =
      '<label class="muted r-slider"><span>' + esc(txt("sliderLabel")) + ' <span class="mono" id="rBDay" style="color:var(--color-ink)"></span></span>' +
      '<input type="range" id="rBSlider" min="0" max="' + (days.length - 1) + '" value="' + S.bday + '"></label>' +
      '<div class="r-stack" id="rStack"></div>' +
      '<div class="r-list">' + rowsHtml + extraRow("legTotal", "total", COLOUR.total) + extraRow("legApp", "app", COLOUR.app) + "</div>" +
      '<div id="rBNote"></div>';
    updateBreakdown();
  }

  function hourRow(t) {
    var rows = rowsFor(S.route, S.amount), i = nearestRow(rows, t);
    return i && i.t === t ? i : null;
  }
  function updateBreakdown() {
    var days = brkDays(), el = document.getElementById("rBrk");
    if (!days.length || !document.getElementById("rBSlider")) return;
    var d = days[S.bday], L = legs(d.row);
    // The total is the cheapest stablecoin path of that hour, the same one the hour count uses. The
    // legs are stored for the base path only, so in an hour another path was cheapest they are empty.
    var hr = hourRow(ep(d.row[BCOL.hour_utc])), onBase = !hr || hr.path === d.row[BCOL.path];
    var vals = { inn: onBase ? legUnit(L.inn) : null, chain: onBase ? legUnit(L.chain) : null, out: onBase ? legUnit(L.out) : null,
      total: hr ? (S.unit === "abs" ? hr.sc : hr.scp) : (S.unit === "abs" ? L.total : L.totalPct), app: S.unit === "abs" ? L.app : L.appPct };
    // One scale for every day, so the bars read against each other as the slider moves.
    var max = 0;
    days.forEach(function (x) {
      var l = legs(x.row), h = hourRow(ep(x.row[BCOL.hour_utc]));
      [h ? (S.unit === "abs" ? h.sc : h.scp) : S.unit === "abs" ? l.total : l.totalPct, S.unit === "abs" ? l.app : l.appPct, legUnit(l.inn), legUnit(l.chain), legUnit(l.out)]
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
      }
      if (out) out.textContent = fmt(v);
    });
    // The stacked bar: the stored legs side by side, only while every leg is stored and none is negative.
    var all = vals.inn != null && vals.chain != null && vals.out != null && vals.inn >= 0 && vals.chain >= 0 && vals.out >= 0;
    document.getElementById("rStack").innerHTML = all ? LEG_ROWS.map(function (l) {
      return '<div class="r-seg" style="background:var(' + l[2] + ');width:' + (vals[l[1]] / max * 100).toFixed(2) + '%"></div>';
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
  var METRICS = [["win", "metricWin"], ["typical", "metricTypical"], ["swing", "metricSwing"], ["change", "metricChange"]];
  // Always in percent of the amount, so routes in different currencies compare.
  function metricValue(a, m) { // [value, null when not stored]
    if (!a) return null;
    if (m === "win") return a.win_rate_pct;
    return a[{ typical: "median_extra_pp", swing: "swing_pp", change: "change_7d_pp" }[m]];
  }
  function drawCompare() {
    if (!document.getElementById("rCompare")) return;
    var chips = METRICS.map(function (m) { return chip("metric", m[0], S.metric === m[0], txt(m[1])); }).join("");
    var shown = HOURLY.routes.filter(function (r) { return comparable(r.id); });
    var left = HOURLY.routes.filter(function (r) { return !comparable(r.id); });
    // A route with no stored value has no row: no empty bars.
    var rowsIn = shown.map(function (r) { return { r: r, v: metricValue(sumAmount(r.id, S.amount), S.metric) }; })
      .filter(function (x) { return x.v != null; });
    var max = 0;
    rowsIn.forEach(function (x) { if (Math.abs(x.v) > max) max = Math.abs(x.v); });
    var rows = rowsIn.map(function (x) {
      var r = x.r, v = x.v, width = !max ? 0 : S.metric === "win" ? v : Math.abs(v) / max * 100;
      return '<button class="r-mrow' + (r.id === S.route ? " sel" : "") + '" data-route="' + esc(r.id) + '"><span class="mono r-mcode">' +
        esc(routeLabel(r)) + '</span><span class="r-track alt"><i style="background:var(' + (v < 0 ? "--color-neutral-700" : "--data-700") +
        ");width:" + width.toFixed(1) + '%"></i></span><span class="mono r-mval">' + esc(dec(v, S.metric === "win" ? 1 : 2) + "%") + "</span></button>";
    }).join("");
    // The left-out note prints here, once.
    document.getElementById("rCompare").innerHTML = (chips ? '<div class="r-chips">' + chips + "</div>" : "") + '<div class="r-list">' + rows + "</div>" +
      (left.length ? w("notComparable", { routes: left.map(routeLabel).join(", ") }, "p", "msm") : "");
  }

  // ---------------------------------------------------------------- what would have to change
  function whatFor(id) {
    var r = WHAT && WHAT.routes.filter(function (x) { return x.id === id; })[0];
    return r && r.amounts.filter(function (a) { return a.amount === S.amount; })[0];
  }
  // One compact table: a row per route, each figure in its own sending currency. Shared words (the
  // column heads, the notes) are said once. Heads come from copy slots; an empty slot prints no head.
  function drawWhat() {
    var el = document.getElementById("rWhat");
    if (!el) return;
    var showShare = !!txt("whatColShare"), changed = [], shares = [];
    var body = HOURLY.routes.filter(function (r) { return comparable(r.id); }).map(function (r) {
      var a = whatFor(r.id), m = a && a.median_7d, l = a && a.latest_hour;
      function money(o, key) { return o && o[key] != null ? dec(o[key], 2) + " " + r.send_ccy : ""; }
      function ppv(o, key) { return o && o[key] != null ? dec(o[key], 2) + "%" : ""; }
      function both(o) { return [money(o, "cheaper_needed"), ppv(o, "cheaper_needed_pp")].filter(Boolean).join(" · "); }
      var med = m ? (m.already_wins ? txt("whatWins", { route: routeLabel(r) }) : both(m)) : "";
      var lat = l ? (l.already_wins ? txt("whatLatestWins") : both(l)) : "";
      if (r.id === S.route && m && !m.already_wins && m.cheapest_app_changed) { // said once, for the route shown
        var note = txt("whatAppChanged", { app: m.cheapest_app_week || "", hours: whole(m.cheapest_app_week_hours), of: whole(m.n_hours) });
        if (note && changed.indexOf(note) < 0) changed.push(note);
      }
      var share = m && !m.already_wins ? m.cheaper_needed_pct_of_in_out : null;
      return "<tr><th scope=\"row\" class=\"mono" + (r.id === S.route ? "" : " muted") + "\">" + esc(routeLabel(r)) + '</th><td class="mono">' + esc(med) +
        '</td><td class="mono">' + esc(lat) + "</td>" + (showShare ? '<td class="mono">' + (share != null ? esc(dec(share, 0) + "%") : "") + "</td>" : "") + "</tr>";
    }).join("");
    var heads = [txt("whatColRoute"), txt("whatColMedian"), txt("whatColLatest")].concat(showShare ? [txt("whatColShare")] : []);
    var thead = heads.some(Boolean) ? "<thead><tr>" + heads.map(function (h) { return "<th scope=\"col\">" + esc(h) + "</th>"; }).join("") + "</tr></thead>" : "";
    el.innerHTML = '<div class="r-tablewrap"><table class="r-whattbl">' + thead + "<tbody>" + body + "</tbody></table></div>" +
      changed.map(function (n) { return '<p class="msm">' + esc(n) + "</p>"; }).join("");
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
    S.sel = null; chart = null;
    app.innerHTML = '<div class="r-wrap">' + head() + buildHero() + '<div class="r-top">' + routeChips() + amountChips() + "</div>" + buildChartSection() +
      (comparable(S.route) ? buildBreakdownSection() + buildLower() : "") + "</div>";
    if (document.getElementById("rChartSec")) { mountChart(); drawControls(); drawChart(true); }
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
    if (b.hasAttribute("data-unit")) { S.unit = b.getAttribute("data-unit"); drawControls(); if (chart) drawChart(false); updateBreakdown(); drawCompare(); return; }
    if (b.hasAttribute("data-period")) { S.period = b.getAttribute("data-period"); drawControls(); if (chart) drawChart(true); return; }
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

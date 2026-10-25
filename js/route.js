/* The routes page (SEB-310 item 2): how much of a country's dollar premium survives the trip.
 *
 * One table, one chart, a short list of the biggest moves. Reads one stored file, data/routes_table.json, which
 * tools/emit_routes_table.py writes every collection from the stored CSVs (the calculation is in METHODOLOGY.md).
 * Nothing is computed here but formatting and drawing.
 *
 * Words: none live here. Every word the page shows comes from copy.json, block "routeData". Numbers, dates, currency
 * symbols, app names and each route's display words ("words") are formatted from what the emitter stored.
 */
(function () {

  var MINUS = "−";
  var MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  var COPY = {};
  var DATA = null;
  var app = document.getElementById("app");
  // the destination sets the colour, the sending country sets the dash (DESIGN.md chart palette)
  var DEST_COLOUR = { INR: "var(--data-700)", NGN: "var(--color-neutral-900)", MXN: "var(--data-500)", PHP: "var(--color-neutral-500)" };
  var SRC_DASH = { SGD: "", USD: "", AUD: "6 4", NZD: "2 3" };
  var NAV = [["navCountries", "./countries.html"], ["navRoutes", "./sending-money.html", true],
    ["navSources", "./sources.html"], ["navFindings", "./findings.html"], ["navResearch", "./research.html"], ["navHow", "./how-it-works.html"]];
  var chart = null;

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
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
  // money in the sending currency: whole from 10 up, two decimals under 10
  function money(v, sym) {
    var a = Math.abs(v);
    return (v < 0 ? MINUS : "") + sym + (a >= 10 ? num(Math.round(a), 0) : num(a, 2));
  }
  function pct(v, d) { return (v < 0 ? MINUS : "") + num(Math.abs(v), d == null ? 1 : d) + "%"; }
  function signedPct(v) { return (v < 0 ? MINUS : "+") + num(Math.abs(v), 1) + "%"; }
  function dayShort(iso) { var d = new Date(iso.slice(0, 10) + "T00:00:00Z"); return d.getUTCDate() + " " + MON[d.getUTCMonth()]; }
  function clock(iso) { return String(new Date(iso).getUTCHours()).padStart(2, "0") + ":00"; }
  function plainWords(s) { return String(s || "").replace(/^the /i, "").replace(/^./, function (c) { return c.toUpperCase(); }); }
  function ccyOf(id) { return { src: id.split("->")[0], dst: id.split("->")[1] }; }
  function colourOf(id) { return DEST_COLOUR[ccyOf(id).dst] || "var(--color-neutral-600)"; }
  function dashOf(id) { return SRC_DASH[ccyOf(id).src] || ""; }
  // "cheaper"/"dearer" said in money: the figure is how much less (or more) the stablecoin cost than the best app
  function gapMoney(pp, amount, sym) {
    var m = Math.abs(pp) * amount / 100;
    return txt(pp >= 0 ? "gapCheaper" : "gapDearer", { amount: money(m, sym) });
  }

  // ---------------------------------------------------------------- page parts
  function headHtml() {
    return '<header class="sm-head"><a class="sm-logo" href="./index.html">margin.wiki</a>' +
      '<nav class="sm-nav" aria-label="Main">' + NAV.map(function (nv) {
        var s = txt(nv[0]);
        return s ? '<a href="' + nv[1] + '"' + (nv[2] ? ' aria-current="page"' : "") + ">" + esc(s) + "</a>" : "";
      }).join("") + "</nav></header>";
  }

  function heroHtml() {
    return '<div class="sm-hero">' + w("heading", null, "h1") + w("lead", null, "p", "sm-lead") +
      '<p class="sm-meta sm-num">' + esc(txt("meta", { time: clock(DATA.as_of_utc).replace(/\s*UTC$/, "") })) + "</p></div>";
  }

  function cell(label, html, cls) {
    return '<td data-label="' + esc(label) + '"' + (cls ? ' class="' + cls + '"' : "") + '><div class="rt-v">' + html + "</div></td>";
  }

  function rowHtml(r) {
    var sym = r.send_symbol, name = '<td class="rt-nm">' + esc(plainWords(r.words)) +
      (r.amount !== DATA.amount ? "<small>" + esc(txt("atAmount", { amount: money(r.amount, sym) })) + "</small>" : "") + "</td>";
    var prem = r.premium_pct == null ? "" : '<span class="sm-num">' + esc(signedPct(r.premium_pct)) + "</span>";
    if (r.status !== "ok") {
      return '<tr data-r="' + esc(r.id) + '" data-amt="' + r.amount + '">' + name + cell(txt("colPremium"), prem) +
        '<td class="rt-wait" colspan="3">' + esc(txt("wait" + r.reason.charAt(0).toUpperCase() + r.reason.slice(1))) + "</td></tr>";
    }
    var gap = r.gap_pp == null ? "" : '<span class="sm-num">' + esc(gapMoney(r.gap_pp, r.amount, sym)) +
      "</span><small class=\"sm-num\">" + esc(txt("gapShare", { pct: pct(Math.abs(r.gap_pp)) })) + "</small>";
    var cost = r.path_cost_pct == null ? "" : '<span class="sm-num">' + esc(money(r.path_cost_money, sym)) + "</span><small class=\"sm-num\">" +
      esc(txt("costShare", { pct: pct(r.path_cost_pct) })) + "</small>";
    var hrs = r.hours_priced ? '<span class="sm-num">' + esc(txt("hoursOf", { n: num(r.hours_cheaper, 0), m: num(r.hours_priced, 0) })) + "</span>" : "";
    return '<tr data-r="' + esc(r.id) + '" data-amt="' + r.amount + '">' + name + cell(txt("colPremium"), prem) + cell(txt("colGap"), gap) + cell(txt("colCost"), cost) + cell(txt("colHours"), hrs) + "</tr>";
  }

  function tableHtml() {
    var head = ["colRoute", "colPremium", "colGap", "colCost", "colHours"].map(function (k) { return '<th scope="col">' + esc(txt(k)) + "</th>"; }).join("");
    return '<section id="smTable"><table class="rt"><caption>' + esc(txt("tableAria")) + "</caption><thead><tr>" + head + "</tr></thead><tbody>" +
      DATA.rows.map(rowHtml).join("") + "</tbody></table>" + w("tableNote", null, "p", "sm-small") + sizesNoteHtml() + "</section>";
  }

  // a route compared at other sizes than the rest (Argentina) says which, in one line
  function sizesNoteHtml() {
    var seen = {}, out = "";
    DATA.rows.forEach(function (r) {
      if (r.amount === DATA.amount || seen[r.id]) return;
      seen[r.id] = 1;
      var amts = DATA.rows.filter(function (q) { return q.id === r.id; }).map(function (q) { return money(q.amount, q.send_symbol); });
      out += w("sizesNote", { route: plainWords(r.words), amounts: amts.join(" and ") }, "p", "sm-small");
    });
    return out;
  }

  function chartSectionHtml() {
    var lines = DATA.daily.filter(function (d) { return d.days.length; });
    if (!lines.length) return "";
    var keys = lines.map(function (d) {
      var row = DATA.rows.filter(function (r) { return r.id === d.id; })[0];
      return '<li><i style="border-top-color:' + colourOf(d.id) + ";" + (dashOf(d.id) ? "border-top-style:dashed;" : "") + '"></i>' + esc(plainWords(row.words)) + "</li>";
    }).join("");
    return '<section id="smChartSec">' + w("chartHeading", null, "h2") + w("chartNote", null, "p", "sm-note") +
      '<div class="sm-chart" id="smChart" role="img" aria-label="' + esc(txt("chartAria")) + '"><svg id="smSvg"></svg><div class="sm-tip" id="smTip" hidden></div></div>' +
      '<ul class="sm-keys">' + keys + "</ul></section>";
  }

  function moveHtml(m) {
    var sym = m.send_symbol, amount = money(m.amount, sym), route = "from " + m.words;
    if (m.kind === "repriced") {
      return txt(m.change_pp >= 0 ? "movesRaised" : "movesCut", { day: dayShort(m.day), app: m.app, amount: amount, route: route,
        change: money(Math.abs(m.change_pp) * m.amount / 100, sym) });
    }
    return txt("movesGap", { amount: amount, route: route, from: gapMoney(m.from_pp, m.amount, sym), to: gapMoney(m.to_pp, m.amount, sym) });
  }

  function movesSectionHtml() {
    if (!DATA.moves.length) return "";
    return "<section id=\"smMoves\">" + w("movesHeading", null, "h2") + '<ul class="sm-moves">' +
      DATA.moves.map(function (m) { return '<li class="sm-num">' + esc(moveHtml(m)) + "</li>"; }).join("") + "</ul></section>";
  }

  function footerHtml() {
    var link = txt("footerLinkText");
    return "<footer>" + w("footerText", null, "p") + (link ? '<a href="https://github.com/SebR214/margin">' + esc(link) + "</a>" : "") + "</footer>";
  }

  // ---------------------------------------------------------------- the chart
  function niceTicks(lo, hi) {
    var span = hi - lo, step = Math.pow(10, Math.floor(Math.log(span / 4) / Math.LN10)), err = span / 4 / step;
    step *= err >= 5 ? 5 : err >= 2 ? 2 : 1;
    var out = [];
    for (var t = Math.ceil(lo / step) * step; t <= hi + 1e-9; t += step) out.push(Math.round(t * 1000) / 1000);
    return out;
  }

  function drawChart() {
    var box = document.getElementById("smChart"), svg = document.getElementById("smSvg");
    if (!box || !svg) return;
    var lines = DATA.daily.filter(function (d) { return d.days.length; });
    var W = Math.max(320, Math.round(box.clientWidth || 720)), H = W < 500 ? 260 : 320;
    var L = 38, R = 8, T = 10, B = 24;
    var days = {}, lo = 0, hi = 0;
    lines.forEach(function (d) { d.days.forEach(function (p) { days[p[0]] = 1; lo = Math.min(lo, p[1]); hi = Math.max(hi, p[1]); }); });
    var keys = Object.keys(days).sort();
    var pad = (hi - lo) * 0.08 || 0.5;
    lo -= pad; hi += pad;
    var tk = niceTicks(lo, hi), stp = tk.length > 1 ? tk[1] - tk[0] : 1;
    if (hi > tk[tk.length - 1]) hi = tk[tk.length - 1] + stp;     // the top line of the grid sits above the highest point
    if (lo < tk[0]) lo = tk[0] - stp;
    var t0 = Date.parse(keys[0] + "T00:00:00Z"), t1 = Date.parse(keys[keys.length - 1] + "T00:00:00Z");
    function X(day) { return L + (t1 === t0 ? 0 : (Date.parse(day + "T00:00:00Z") - t0) / (t1 - t0)) * (W - L - R); }
    function Y(v) { return T + (hi - v) / (hi - lo) * (H - T - B); }
    var out = "";
    niceTicks(lo, hi).forEach(function (t) {
      var y = Y(t).toFixed(1), zero = Math.abs(t) < 1e-9;
      out += '<line class="' + (zero ? "sm-zline" : "sm-grid") + '" x1="' + L + '" x2="' + (W - R) + '" y1="' + y + '" y2="' + y + '"/>' +
        '<text class="sm-ax' + (zero ? " sm-z" : "") + '" x="' + (L - 6) + '" y="' + (+y + 4) + '" text-anchor="end">' + (zero ? esc(txt("chartZero")) : (t > 0 ? "+" : MINUS) + Math.abs(t) + "%") + "</text>";
    });
    var nT = W < 500 ? 4 : 7;
    for (var i = 0; i < nT; i++) {
      var tt = t0 + (t1 - t0) * i / (nT - 1), dd = new Date(tt);
      out += '<text class="sm-ax" x="' + (L + (W - L - R) * i / (nT - 1)).toFixed(1) + '" y="' + (H - 6) + '" text-anchor="' + (i === 0 ? "start" : i === nT - 1 ? "end" : "middle") + '">' +
        dd.getUTCDate() + " " + MON[dd.getUTCMonth()] + "</text>";
    }
    lines.forEach(function (d) {
      var pts = d.days.map(function (p) { return X(p[0]).toFixed(1) + "," + Y(p[1]).toFixed(1); });
      var st = 'stroke="' + colourOf(d.id) + '"' + (dashOf(d.id) ? ' stroke-dasharray="' + dashOf(d.id) + '"' : "");
      if (pts.length === 1) {
        out += '<circle cx="' + pts[0].split(",")[0] + '" cy="' + pts[0].split(",")[1] + '" r="3" fill="' + colourOf(d.id) + '"/>';
      } else {
        out += '<polyline class="sm-ln" ' + st + ' points="' + pts.join(" ") + '"/>';
      }
    });
    out += '<line class="sm-cross" id="smCross" visibility="hidden" y1="' + T + '" y2="' + (H - B) + '"/>';
    svg.setAttribute("viewBox", "0 0 " + W + " " + H);
    svg.setAttribute("width", W); svg.setAttribute("height", H);
    svg.innerHTML = out;
    chart = { W: W, H: H, L: L, R: R, keys: keys, X: X, lines: lines };
  }

  function hoverChart(e) {
    if (!chart) return;
    var box = document.getElementById("smChart"), r = box.getBoundingClientRect(), x = e.clientX - r.left;
    var best = null, bd = 1e9;
    chart.keys.forEach(function (k) { var dd = Math.abs(chart.X(k) - x); if (dd < bd) { bd = dd; best = k; } });
    if (!best) return;
    var rows = "";
    chart.lines.forEach(function (d) {
      var p = d.days.filter(function (q) { return q[0] === best; })[0];
      if (!p) return;
      var row = DATA.rows.filter(function (q) { return q.id === d.id; })[0];
      rows += '<div class="sm-num"><i style="border-top-color:' + colourOf(d.id) + ';' + (dashOf(d.id) ? "border-top-style:dashed;" : "") + '"></i>' +
        esc(plainWords(row.words)) + ": " + esc(pct(p[1]).replace(/^(\d)/, "+$1")) + "</div>";
    });
    var tip = document.getElementById("smTip"), cross = document.getElementById("smCross");
    tip.innerHTML = "<b>" + esc(txt("chartTip", { day: dayShort(best) })) + "</b>" + rows;
    tip.hidden = false;
    var cx = chart.X(best);
    tip.style.left = Math.min(Math.max(cx - tip.offsetWidth / 2, 0), box.clientWidth - tip.offsetWidth) + "px";
    cross.setAttribute("x1", cx); cross.setAttribute("x2", cx); cross.setAttribute("visibility", "visible");
  }

  function hideTip() {
    var tip = document.getElementById("smTip"), cross = document.getElementById("smCross");
    if (tip) tip.hidden = true;
    if (cross) cross.setAttribute("visibility", "hidden");
  }

  // ---------------------------------------------------------------- render
  function renderAll() {
    // under the table: the picked route in detail (js/route_detail.js fills #smDetail), then the biggest moves.
    // The all-routes line chart is gone (22 Oct): the table already compares the routes, the detail chart shows one.
    app.innerHTML = '<div class="sm-wrap">' + headHtml() + heroHtml() + tableHtml() + '<div id="smDetail"></div>' + movesSectionHtml() + footerHtml() + "</div>";
    try { window.dispatchEvent(new Event("routes:render")); } catch (e) { /* very old browser: no detail */ }
  }

  function start(res) {
    COPY = (res[0] && res[0].routeData) || {};
    DATA = res[1];
    if (!DATA || !DATA.rows) throw new Error("data");
    document.addEventListener("pointerdown", function (e) { if (!(e.target.closest && e.target.closest("#smChart"))) hideTip(); });
    renderAll();
    (window.siteLive = window.siteLive || { handlers: [], onNewHour: function (fn) { this.handlers.push(fn); } }).onNewHour(refresh);
  }

  // a tab left open loads the newer hour when it is published (siteLive, js/site_head.js)
  function refresh() {
    return Promise.all([maybeJSON("copy.json"), getJSON("data/routes_table.json")]).then(function (res) {
      if (!res[1]) return;
      COPY = (res[0] && res[0].routeData) || COPY;
      DATA = res[1];
      var y = window.scrollY;
      renderAll();
      window.scrollTo(0, y);
    }).catch(function () { /* a failed refresh leaves what the reader already has */ });
  }

  Promise.all([maybeJSON("copy.json"), getJSON("data/routes_table.json")])
    .then(start).catch(function (err) {
      if (window.console) console.error(err);
      maybeJSON("copy.json").then(function (d) {
        COPY = (d && d.routeData) || {};
        app.innerHTML = '<div class="sm-wrap">' + headHtml() + w("loadFailed", null, "p") + "</div>";
      });
    });
})();

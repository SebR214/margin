/* One currency event (SEB-311 step 4): the street price and the official rate before, at and after the day the detector recorded it.
 *
 * Reads data/event_records/<id>.json (written by tools/detect_events.py, which holds the rules, the baseline, the checks on each source and
 * the trace of every number) and data/index_latest.json for the country's name. Nothing is computed here but formatting, drawing and
 * three differences read straight off the record's own daily points. Which event: ?id=IQD-official_break-2026-10-09, that one when absent.
 *
 * Words: none live here. Every word comes from copy.json, block "eventPage" (drafts until Seb OKs them). Numbers, dates, currency codes,
 * source names and the country's name are data.
 */
(function () {
  var DEFAULT_ID = "IQD-official_break-2026-10-09";
  var MINUS = "−";
  var MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  var COPY = {}, REC = null, COUNTRY = "";
  var app = document.getElementById("app");
  var NAV = [["navCountries", "./countries.html"], ["navRoutes", "./sending-money.html"], ["navSources", "./sources.html"],
    ["navFindings", "./findings.html"], ["navHow", "./how-it-works.html"]];
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
  function num(v, d) { return v.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d }); }
  function price(v) { return v == null ? "" : (Math.abs(v) >= 100 ? num(v, 0) : num(v, 2)); }
  function pct(v) { return (v < 0 ? MINUS : "") + num(Math.abs(v), Math.abs(v) < 10 ? 1 : 0) + "%"; }
  function dayShort(iso) { var d = new Date(iso.slice(0, 10) + "T00:00:00Z"); return d.getUTCDate() + " " + MON[d.getUTCMonth()]; }
  function addDays(iso, n) { return new Date(Date.parse(iso.slice(0, 10) + "T00:00:00Z") + n * 86400000).toISOString().slice(0, 10); }

  // every daily point the record holds: the timeline from before the event, then each weekly update's days; one point a day
  function points() {
    var by = {};
    (REC.timeline || []).concat((REC.after || []).reduce(function (a, x) { return a.concat(x.timeline || []); }, [])).forEach(function (p) { by[p.day] = p; });
    return Object.keys(by).sort().map(function (d) { return by[d]; });
  }
  function at(pts, day, key) { var p = pts.filter(function (q) { return q.day === day; })[0]; return p ? p[key] : null; }

  function headHtml() {
    return '<header class="sm-head"><a class="sm-logo" href="./index.html">margin.wiki</a>' +
      '<nav class="sm-nav" aria-label="Main">' + NAV.map(function (nv) {
        var s = txt(nv[0]);
        return s ? '<a href="' + nv[1] + '">' + esc(s) + "</a>" : "";
      }).join("") + "</nav></header>";
  }

  function leadAndHeading(pts) {
    var ch = REC.official && REC.official.change_pct, sc = REC.street && REC.street.change_pct, lag = REC.official_lag_days;
    if (REC.kind === "official_break") {
      var x = lag != null ? addDays(REC.detected_on, -lag) : null;
      var sp = x ? at(pts, x, "street") : null, sb = x ? at(pts, addDays(x, -3), "street") : null;
      return {
        h: txt("headingOfficial", { country: COUNTRY, pct: pct(Math.abs(ch)) }),
        lead: lag != null && sp && sb
          ? txt("leadOfficialLed", { streetPct: pct(Math.abs((sp / sb - 1) * 100)), streetDay: dayShort(x), day: dayShort(REC.detected_on), lag: lag })
          : txt("leadOfficialNoLead", { pct: pct(Math.abs(ch)), day: dayShort(REC.detected_on) })
      };
    }
    return { h: txt("headingStreet", { country: COUNTRY, pct: pct(Math.abs(sc)) }), lead: txt("leadStreet", { officialPct: pct(ch || 0) }) };
  }

  function heroHtml(pts) {
    var t = leadAndHeading(pts);
    var conf = REC.confirmation === "two sources" ? txt("confirmedTwo", { sources: (REC.sources_showing_it || []).join(", ") }) : txt("confirmedOne");
    return '<div class="sm-hero"><h1>' + esc(t.h) + "</h1>" + (t.lead ? '<p class="sm-lead">' + esc(t.lead) + "</p>" : "") +
      '<p class="sm-meta sm-num">' + esc(txt("meta", { day: dayShort(REC.detected_on), confirmation: conf })) + "</p></div>";
  }

  function chartSectionHtml() {
    return '<section id="evChartSec">' + w("chartHeading", null, "h2") + w("chartNote", null, "p", "sm-note") +
      '<div class="sm-chart" id="evChart" role="img" aria-label="' + esc(txt("chartAria")) + '"><svg id="evSvg"></svg><div class="sm-tip" id="evTip" hidden></div></div>' +
      '<ul class="sm-keys"><li><i style="border-top-color:var(--data-700)"></i>' + esc(txt("keyStreet")) + '</li><li><i style="border-top-color:var(--color-neutral-900)"></i>' +
      esc(txt("keyOfficial")) + "</li></ul></section>";
  }

  function cell(label, v, day, base) {
    if (v == null) return '<td data-label="' + esc(label) + '"><div class="ev-v">' + esc(txt("notYet")) + "</div></td>";
    var ch = base ? '<small class="sm-num">' + esc(txt("cellChange", { pct: pct((v / base - 1) * 100) })) + "</small>" : "";
    return '<td data-label="' + esc(label) + '"><div class="ev-v sm-num">' + esc(txt("cellPrice", { value: price(v), ccy: REC.ccy })) + "<small>" + esc(txt("cellDay", { day: dayShort(day) })) +
      "</small>" + ch + "</div></td>";
  }

  function tableHtml(pts) {
    var after = (REC.after || [])[0];
    var s = REC.street || {}, o = REC.official || {};
    var rows = '<tr><td class="ev-nm">' + esc(txt("rowStreet")) + "</td>" + cell(txt("colBefore"), s.before, s.before_day, null) +
      cell(txt("colNow"), s.at_detection, s.at_detection_day, s.before) + cell(txt("colAfter"), after && after.street, after && after.day, s.before) + "</tr>" +
      '<tr><td class="ev-nm">' + esc(txt("rowOfficial")) + "</td>" + cell(txt("colBefore"), o.baseline, o.baseline_day, null) +
      cell(txt("colNow"), o.at_detection, REC.detected_on, o.baseline) + cell(txt("colAfter"), after && after.official, after && after.day, o.baseline) + "</tr>";
    return '<section id="evTable">' + w("tableHeading", null, "h2") + '<table class="ev"><caption>' + esc(txt("tableHeading")) + "</caption><thead><tr><th scope=\"col\">" +
      esc(txt("colWhat")) + '</th><th scope="col">' + esc(txt("colBefore")) + '</th><th scope="col">' + esc(txt("colNow")) + '</th><th scope="col">' + esc(txt("colAfter")) +
      "</th></tr></thead><tbody>" + rows + "</tbody></table></section>";
  }

  function lagHtml(pts) {
    var lag = REC.official_lag_days, body;
    if (REC.kind !== "official_break") body = txt("lagStreet");
    else if (lag != null) {
      var x = addDays(REC.detected_on, -lag), a = at(pts, x, "street"), b = at(pts, addDays(x, -3), "street");
      body = a && b ? txt("lagLed", { pct: pct(Math.abs((a / b - 1) * 100)), streetDay: dayShort(x), day: dayShort(REC.detected_on), lag: lag }) : txt("lagNone");
    } else body = txt("lagNone");
    return body ? '<section id="evLag">' + w("lagHeading", null, "h2") + '<p class="sm-note">' + esc(body) + "</p></section>" : "";
  }

  function offersHtml() {
    var of = REC.offers || {};
    if (of.buy_ads_median_7d == null || of.sell_ads_median_7d == null) return "";
    return '<section id="evOffers">' + w("offersHeading", null, "h2") + '<p class="sm-note sm-num">' +
      esc(txt("offersLine", { buy: num(of.buy_ads_median_7d, 0), sell: num(of.sell_ads_median_7d, 0) })) + "</p></section>";
  }

  function keepHtml() {
    var li = [];
    if (REC.confirmation !== "two sources") li.push(txt("keepOne"));
    li.push(txt("keepStreet"), txt("keepOfficial"), txt("keepWeekly"));
    var flags = (REC.checks && REC.checks.official_rate_rules_flagged_that_day) || [];
    if (flags.length) li.push(txt("flagLine", { rules: flags.join(", ") }));
    return '<section id="evKeep">' + w("keepHeading", null, "h2") + '<ul class="sm-facts">' + li.filter(Boolean).map(function (t) { return "<li>" + esc(t) + "</li>"; }).join("") + "</ul></section>";
  }

  function checksHtml() {
    var c = REC.checks || {}, out = [];
    function add(key, label, n, of) { if (c[key] && n != null) out.push(txt("checkLine", { source: txt(label), n: n, of: of })); }
    add("er-api", "sourceOfficial", c["er-api"] && c["er-api"].days_with_a_reading_in_window, 4);
    add("fx_live", "sourceLive", c.fx_live && c.fx_live.days_with_a_reading_in_window, 4);
    add("binance_p2p", "sourceBinance", c.binance_p2p && c.binance_p2p.days_with_a_price_in_window, 8);
    add("okx_p2p", "sourceOkx", c.okx_p2p && c.okx_p2p.days_with_a_price_in_window, 8);
    return '<section id="evChecks">' + w("checksHeading", null, "h2") + '<ul class="sm-facts sm-num">' + out.map(function (t) { return "<li>" + esc(t) + "</li>"; }).join("") + "</ul></section>";
  }

  function footerHtml() {
    var link = txt("footerLinkText");
    return "<footer>" + '<p><a href="./data/event_records/' + esc(REC.id) + '.json">' + esc(txt("recordLink")) + "</a></p>" + w("footerText", null, "p") +
      (link ? '<a href="https://github.com/SebR214/margin">' + esc(link) + "</a>" : "") + "</footer>";
  }

  // ---------------------------------------------------------------- the chart
  function niceTicks(lo, hi) {
    var span = hi - lo, step = Math.pow(10, Math.floor(Math.log(span / 4) / Math.LN10)), err = span / 4 / step;
    step *= err >= 5 ? 5 : err >= 2 ? 2 : 1;
    var out = [];
    for (var t = Math.ceil(lo / step) * step; t <= hi + 1e-9; t += step) out.push(t);
    return out;
  }

  function drawChart() {
    var box = document.getElementById("evChart"), svg = document.getElementById("evSvg");
    if (!box || !svg) return;
    var pts = points(), W = Math.max(320, Math.round(box.clientWidth || 720)), H = W < 500 ? 260 : 320, L = 46, R = 10, T = 12, B = 24;
    var lo = 1e18, hi = -1e18;
    pts.forEach(function (p) { ["official", "street"].forEach(function (k) { if (p[k] != null) { lo = Math.min(lo, p[k]); hi = Math.max(hi, p[k]); } }); });
    var pad = (hi - lo) * 0.08 || 1;
    lo -= pad; hi += pad;
    var tk = niceTicks(lo, hi), stp = tk.length > 1 ? tk[1] - tk[0] : 1;
    if (hi > tk[tk.length - 1]) hi = tk[tk.length - 1] + stp;
    if (lo < tk[0]) lo = tk[0] - stp;
    var t0 = Date.parse(pts[0].day + "T00:00:00Z"), t1 = Date.parse(pts[pts.length - 1].day + "T00:00:00Z");
    function X(day) { return L + (t1 === t0 ? 0 : (Date.parse(day + "T00:00:00Z") - t0) / (t1 - t0)) * (W - L - R); }
    function Y(v) { return T + (hi - v) / (hi - lo) * (H - T - B); }
    var out = "";
    niceTicks(lo, hi).forEach(function (t) {
      var y = Y(t).toFixed(1);
      out += '<line class="sm-grid" x1="' + L + '" x2="' + (W - R) + '" y1="' + y + '" y2="' + y + '"/><text class="sm-ax" x="' + (L - 6) + '" y="' + (+y + 4) + '" text-anchor="end">' + esc(num(t, 0)) + "</text>";
    });
    var nT = W < 500 ? 4 : 6;
    for (var i = 0; i < nT; i++) {
      var tt = t0 + (t1 - t0) * i / (nT - 1);
      out += '<text class="sm-ax" x="' + (L + (W - L - R) * i / (nT - 1)).toFixed(1) + '" y="' + (H - 6) + '" text-anchor="' + (i === 0 ? "start" : i === nT - 1 ? "end" : "middle") + '">' +
        esc(dayShort(new Date(tt).toISOString())) + "</text>";
    }
    var mx = X(REC.detected_on).toFixed(1);
    out += '<line class="sm-mark" x1="' + mx + '" x2="' + mx + '" y1="' + T + '" y2="' + (H - B) + '"/><text class="sm-marklbl" x="' + (+mx + 6) + '" y="' + (T + 10) + '">' + esc(txt("markLabel")) + "</text>";
    [["official", "var(--color-neutral-900)"], ["street", "var(--data-700)"]].forEach(function (s) {
      var line = pts.filter(function (p) { return p[s[0]] != null; }).map(function (p) { return X(p.day).toFixed(1) + "," + Y(p[s[0]]).toFixed(1); });
      if (line.length > 1) out += '<polyline class="sm-ln" stroke="' + s[1] + '" points="' + line.join(" ") + '"/>';
    });
    out += '<line class="sm-cross" id="evCross" visibility="hidden" y1="' + T + '" y2="' + (H - B) + '"/>';
    svg.setAttribute("viewBox", "0 0 " + W + " " + H); svg.setAttribute("width", W); svg.setAttribute("height", H);
    svg.innerHTML = out;
    chart = { X: X, pts: pts };
  }

  function hover(e) {
    if (!chart) return;
    var box = document.getElementById("evChart"), x = e.clientX - box.getBoundingClientRect().left, best = null, bd = 1e9;
    chart.pts.forEach(function (p) { var d = Math.abs(chart.X(p.day) - x); if (d < bd) { bd = d; best = p; } });
    if (!best) return;
    var tip = document.getElementById("evTip"), cross = document.getElementById("evCross");
    tip.innerHTML = "<b>" + esc(dayShort(best.day)) + "</b>" + [["street", "keyStreet", "var(--data-700)"], ["official", "keyOfficial", "var(--color-neutral-900)"]].map(function (k) {
      return best[k[0]] == null ? "" : '<div class="sm-num"><i style="border-top-color:' + k[2] + '"></i>' + esc(txt(k[1])) + ": " + esc(txt("tipUnit", { value: price(best[k[0]]), ccy: REC.ccy })) + "</div>";
    }).join("");
    tip.hidden = false;
    var cx = chart.X(best.day);
    tip.style.left = Math.min(Math.max(cx - tip.offsetWidth / 2, 0), box.clientWidth - tip.offsetWidth) + "px";
    cross.setAttribute("x1", cx); cross.setAttribute("x2", cx); cross.setAttribute("visibility", "visible");
  }
  function hideTip() {
    var tip = document.getElementById("evTip"), cross = document.getElementById("evCross");
    if (tip) tip.hidden = true;
    if (cross) cross.setAttribute("visibility", "hidden");
  }

  function render() {
    var pts = points();
    app.innerHTML = '<div class="sm-wrap">' + headHtml() + heroHtml(pts) + chartSectionHtml() + tableHtml(pts) + lagHtml(pts) + offersHtml() + keepHtml() + checksHtml() + footerHtml() + "</div>";
    drawChart();
    var box = document.getElementById("evChart");
    if (box) {
      box.addEventListener("pointermove", hover);
      box.addEventListener("pointerdown", hover);
      box.addEventListener("pointerleave", function (e) { if (e.pointerType !== "touch") hideTip(); });
      if (window.ResizeObserver) new ResizeObserver(function () { drawChart(); }).observe(box);
    }
    document.addEventListener("pointerdown", function (e) { if (!(e.target.closest && e.target.closest("#evChart"))) hideTip(); });
  }

  var id = (new URLSearchParams(location.search).get("id") || DEFAULT_ID).replace(/[^A-Za-z0-9_\-]/g, "");
  Promise.all([getJSON("copy.json"), getJSON("data/event_records/" + id + ".json").catch(function () { return null; }), getJSON("data/index_latest.json").catch(function () { return null; })])
    .then(function (res) {
      COPY = (res[0] && res[0].eventPage) || {};
      REC = res[1];
      if (!REC) { app.innerHTML = '<div class="sm-wrap">' + headHtml() + w("notFound", null, "p") + "</div>"; return; }
      var c = res[2] && (res[2].countries || []).filter(function (x) { return x.ccy === REC.ccy; })[0];
      COUNTRY = (c && c.country) || REC.ccy;
      render();
    }).catch(function (err) {
      if (window.console) console.error(err);
      getJSON("copy.json").then(function (d) { COPY = (d && d.eventPage) || {}; app.innerHTML = '<div class="sm-wrap">' + headHtml() + w("loadFailed", null, "p") + "</div>"; }).catch(function () {});
    });
})();

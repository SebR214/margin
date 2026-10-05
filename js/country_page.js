/* The country page (SEB-240, page 3), rebuilt around the stored readings.
 *
 * Reads only stored files:
 *   data/index_latest.json              today's gap and the withheld list
 *   data/countries/<CCY>.json           the published daily history
 *   data/country_readings/<CCY>/...     every stored reading, by month
 *   data/country_history_segment/...    the backfilled history, where it exists
 *   data/street_depth_latest.json       the latest dollar depth
 *   data/heatmap_daily.json             the ranked flag
 *   data/latest.json                    the latest street price (and its receipt, js/receipt_replay.js)
 *
 * Words: none live here. Every word the page shows comes from copy.json,
 * block "countryData". A key that is empty renders no element. Numbers, dates,
 * percentages and currency codes are formatted in code.
 */
(function () {

  var DAY = 86400;
  var RAW = "https://github.com/SebR214/margin/blob/main/";
  var TIP_WINDOW = 5400; // a tooltip row shows a reading at most 1.5 hours from the pointer
  var LATEST_ROWS = 12;
  var BAND_LO = 0.1, BAND_HI = 0.9; // the usual range: 10th to 90th percentile of the daily record
  var MIN_RECORD_DAYS = 20; // the record-position line needs this many days
  // One look per source layer: a token colour and a dot shape. Blue is reserved for the official rate.
  // Past twelve sources the looks repeat; the tooltip and the chip name each source.
  var COLORS = ["--data-700", "--color-ink", "--data-400", "--color-neutral-700", "--data-600", "--data-600"];
  function look(i) { return [COLORS[i % COLORS.length], Math.floor(i / COLORS.length) % 2 ? "square" : "round"]; }

  var NAV = [];
  var COPY = {};
  var app = document.getElementById("app");
  var ccy = (new URLSearchParams(location.search).get("ccy") || "").toUpperCase();
  if (!/^[A-Z]{3}$/.test(ccy)) ccy = "";

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
    var c = Array.isArray(cls) ? cls.join(" ") : cls;
    return s ? "<" + tag + (c ? ' class="' + c + '"' : "") + ">" + esc(s) + "</" + tag + ">" : "";
  }
  function cls() { return Array.prototype.filter.call(arguments, Boolean).join(" "); }
  function getJSON(url) {
    return fetch(url, { cache: "no-store" }).then(function (r) {
      if (!r.ok) throw new Error(String(r.status));
      return r.json();
    });
  }
  function maybeJSON(url) { return getJSON(url).catch(function () { return null; }); }

  function num(v, d) { return v.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d }); }
  function pct(v) { // a gap: one decimal, none once it is past 100
    if (v == null || !isFinite(v)) return "";
    if (Math.abs(v) < 0.05) return "0.0%";
    return (v < 0 ? "-" : "") + num(Math.abs(v), Math.abs(v) >= 100 ? 0 : 1) + "%";
  }
  function price(v) { return num(v, v >= 100 ? 2 : v >= 1 ? 3 : 4); }
  function money(v) { return "$" + Math.round(v).toLocaleString("en-US"); }
  function dayShort(t) { return new Date(t * 1000).toLocaleDateString("en-US", { day: "numeric", month: "short", timeZone: "UTC" }); }
  function dayLong(t) { return new Date(t * 1000).toLocaleDateString("en-US", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" }); }
  function clock(t) { return new Date(t * 1000).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: "UTC", timeZoneName: "short" }); }
  function stamp(t) { return dayShort(t) + ", " + clock(t); }
  function isoEpoch(d) { return Date.parse(d + (d.length <= 10 ? "T00:00:00Z" : "")) / 1000; }
  function quantile(sorted, p) { return sorted[Math.min(sorted.length - 1, Math.floor(p * sorted.length))]; }
  function median(a) {
    var s = a.slice().sort(function (x, y) { return x - y; }), n = s.length;
    return n % 2 ? s[(n - 1) / 2] : (s[n / 2 - 1] + s[n / 2]) / 2;
  }
  function nearest(arr, t, key) { // arr sorted by time; returns the index of the closest entry
    var lo = 0, hi = arr.length - 1;
    if (hi < 0) return -1;
    while (hi - lo > 1) { var m = (lo + hi) >> 1; if (arr[m][key] < t) lo = m; else hi = m; }
    return Math.abs(arr[lo][key] - t) <= Math.abs(arr[hi][key] - t) ? lo : hi;
  }
  function monthSpan(m) {
    var y = +m.slice(0, 4), mo = +m.slice(5, 7);
    return [Date.UTC(y, mo - 1, 1) / 1000, Date.UTC(y, mo, 1) / 1000];
  }

  // ---------------------------------------------------------------- state
  var S = {
    country: null, idx: null, history: [], segment: null, ranked: true,
    period: "all", unit: "gap", hidden: {}, daily: true, seg: true,
    sel: null, asOf: 0, bandLo: null, bandHi: null
  };
  var monthCache = {};
  var chart = null;
  var cached = { reading: null };

  function loadMonth(m) {
    if (!monthCache[m]) {
      monthCache[m] = getJSON("data/country_readings/" + ccy + "/" + m + ".json").then(function (d) {
        return d.readings.map(function (r) { return { t: r[0], s: r[1], price: r[2], off: r[3], gap: r[4], n: r[5], total: r[6] }; });
      });
    }
    return monthCache[m];
  }
  function loadMonths(list) { return Promise.all(list.map(loadMonth)); }

  // The window the chosen period shows, in epoch seconds.
  function windowFor(period) {
    var t1 = S.asOf, t0;
    if (period === "7") t0 = t1 - 7 * DAY;
    else if (period === "30") t0 = t1 - 30 * DAY;
    else {
      var cands = [S.firstRead];
      if (S.daily && S.history.length) cands.push(isoEpoch(S.history[0].date));
      if (S.seg && S.segment) cands.push(isoEpoch(S.segment.points[0].date));
      t0 = Math.min.apply(null, cands);
    }
    return [t0, t1];
  }
  function monthsFor(t0, t1) {
    return S.idx.months.filter(function (m) { var sp = monthSpan(m); return sp[0] < t1 && sp[1] > t0; });
  }

  // ---------------------------------------------------------------- derived series
  function bySource(rows) {
    var out = S.idx.sources.map(function () { return []; });
    rows.forEach(function (r) { if (out[r.s]) out[r.s].push(r); });
    out.forEach(function (a) { a.sort(function (x, y) { return x.t - y.t; }); });
    return out;
  }
  function officialPts(t0, t1) {
    return S.idx.official.filter(function (o) { return o[0] >= t0 - DAY && o[0] <= t1 + DAY; });
  }
  function dailyPts() { return S.history.map(function (h) { return [isoEpoch(h.date), h.index_pct]; }); }
  function segmentPts() { return S.segment ? S.segment.points.map(function (p) { return [isoEpoch(p.date), p.index_pct]; }) : []; }

  // The record-position line: where today's gap sits in the record, ranked against ONE series.
  function recordLine() {
    var useSeg = !!(S.segment && S.seg);
    var vals = (useSeg ? S.segment.points.map(function (p) { return p.index_pct; }) : S.history.map(function (h) { return h.index_pct; }))
      .map(Math.abs);
    var now = S.headline;
    if (vals.length < MIN_RECORD_DAYS || now == null) return "";
    var a = Math.abs(now) < 0.05 ? 0 : Math.abs(now);
    var below = vals.filter(function (v) { return v < a; }).length / vals.length;
    var max = Math.max.apply(null, vals), min = Math.min.apply(null, vals);
    var key = a >= max ? "recordWidest" : a <= min ? "recordNarrowest" : below >= 0.9 ? "recordNearWidest" : below <= 0.1 ? "recordNearNarrowest" : "recordNormal";
    var sorted = vals.slice().sort(function (x, y) { return x - y; });
    var first = useSeg ? S.segment.first : S.history[0].date;
    var scope = useSeg ? txt("recordScopeVenue", { venue: S.segment.venue, label: S.segment.label }) : txt("recordScopeOwn");
    var vv = { lo: num(quantile(sorted, 0.1), 1), hi: num(quantile(sorted, 0.9), 1), first: dayLong(isoEpoch(first)), scope: scope };
    return [txt(key, vv), txt("recordRange", vv)].filter(Boolean).join(" ");
  }

  // ---------------------------------------------------------------- the page
  function head(extra) {
    return '<header class="c-head"><div class="c-brand"><a class="c-logo mono" href="./index.html">margin.wiki</a>' +
      '<nav>\n' +
      NAV.map(function (item) {
        var active = item.href === './country.html';
        return '        <a href="' + item.href + '"' + (active ? ' class="active"' : "") + ">" + esc(item.label) + "</a>";
      }).join("\n") + "\n      </nav></div>" + (extra || "") + "</header>";
  }
  function notice(keys, vals) {
    app.innerHTML = '<div class="c-wrap">' + head() + '<section class="c-herotext">' +
      [].concat(keys).map(function (k, i) { return w(k, vals, i ? "p" : "h1", i ? "soft" : ""); }).join("") + "</section></div>";
  }

  function statCell(labelKey, value, sub) {
    if (!value) return "";
    return '<div>' + w(labelKey, null, "span", "c-k") + '<span class="mono c-v">' + esc(value) + "</span>" +
      (sub ? '<span class="mono muted c-sub">' + esc(sub) + "</span>" : "") + "</div>";
  }

  function buildStats() {
    var c = S.country, asOfDay = S.asOf - 29 * DAY;
    var recent = S.history.filter(function (h) { return isoEpoch(h.date) >= asOfDay; }).map(function (h) { return h.index_pct; });
    var cells = statCell("statToday", pct(c.index_pct));
    if (recent.length > 1) {
      cells += statCell("statMedian30", pct(median(recent)));
      cells += statCell("statRange30", pct(Math.min.apply(null, recent)) + " – " + pct(Math.max.apply(null, recent)));
    }
    if (S.history.length > 1) {
      var useSeg = !!(S.segment && S.seg);
      var pool = S.history.map(function (h) { return { date: h.date, v: h.index_pct }; });
      if (useSeg) pool = S.segment.points.map(function (q) { return { date: q.date, v: q.index_pct }; }).concat(pool);
      var wide = pool.reduce(function (m, h) { return Math.abs(h.v) > Math.abs(m.v) ? h : m; });
      cells += statCell(useSeg ? "statWidestAll" : "statWidest", pct(wide.v), dayLong(isoEpoch(wide.date)));
    }
    return cells ? '<div class="c-stats">' + cells + "</div>" : "";
  }

  function buildHero() {
    var c = S.country, p2p = S.p2p;
    var gapText = pct(S.headline);
    var key = Math.abs(S.headline) < 0.05 ? "headlineSame" : S.headline > 0 ? "headlineMore" : "headlineLess";
    var lead = p2p && S.cdoc.source_class === "p2p_buy_median"
      ? txt("leadP2p", { country: c.country, ccy: ccy, rate: num(p2p.fx_mid_per_usd, 0), street: num(p2p.buy_median, 0) + " " + ccy })
      : txt("leadBook", { country: c.country, ccy: ccy, rate: num(S.cdoc.fx_mid_per_usd, 0), street: num(S.cdoc.buy_price, 0) + " " + ccy });
    return '<section class="c-hero hero bleed"><div class="c-herotext">' + w(key, { country: c.country, gap: pct(Math.abs(S.headline)) }, "h1") +
      (lead ? '<p class="soft c-lead">' + esc(lead) + "</p>" : "") +
      (!S.ranked ? w("unrankedNote", { country: c.country }, "p", ["muted", "c-small"]) : "") + "</div>" +
      '<div class="c-bigbox"><span class="c-big mono" data-receipt-ccy="' + esc(ccy) + '" data-receipt-value="' + esc(gapText) +
      '" tabindex="0">' + esc(gapText) + "</span>" + w("bigCaption", { country: c.country }, "span", ["soft", "c-small"]) + "</div></section>";
  }

  function buildChartSection() {
    return '<section class="c-sec"><div class="c-sechead">' +
      w("chartHeading", { country: S.country.country }, "h2") + w("chartLead", { country: S.country.country }, "p", ["muted", "c-small"]) + "</div>" +
      '<div class="c-controls"><div class="c-left" id="cLeft"></div><div class="c-right" id="cRight"></div></div>' +
      '<div id="cChartSlot"></div>' +
      '<div class="mono muted c-axis" id="cAxis"></div>' +
      '<div id="cSel"></div><div id="cNotes"></div></section>';
  }

  function swatch(look) {
    return '<i class="c-sw' + (look[1] === "round" ? " r" : "") + '" style="background:var(' + look[0] + ')"></i>';
  }
  function chip(on, attrs, inner) {
    var layer = attrs.indexOf("data-layer") === 0;
    return '<button type="button" class="' + cls("c-chip", layer ? "lay" : "", on && "on") + '" aria-pressed="' + (on ? "true" : "false") + '" ' + attrs + ">" + inner + "</button>";
  }

  function drawControls() {
    var left = "";
    var legend = "";
    var lo = txt("legendOfficial"), bd = txt("legendBand");
    if (lo) legend += '<span class="c-leg"><i class="c-line" style="background:var(--color-ink)"></i>' + esc(lo) + "</span>";
    if (bd && S.bandLo != null) legend += '<span class="c-leg"><i class="c-band"></i>' + esc(bd) + "</span>";
    var chips = "";
    S.idx.sources.forEach(function (s, i) {
      chips += chip(!S.hidden[i], 'data-layer="s' + i + '"', swatch(look(i)) + esc(s.id));
    });
    if (S.unit === "gap" && S.history.length > 1 && txt("layerDaily")) {
      chips += chip(S.daily, 'data-layer="daily"', '<i class="c-line" style="background:var(--color-neutral-700)"></i>' + esc(txt("layerDaily")));
    }
    if (S.unit === "gap" && S.segment && txt("layerBackfill", { venue: S.segment.venue, label: S.segment.label })) {
      chips += chip(S.seg, 'data-layer="seg"', '<i class="c-line dashed"></i>' + esc(txt("layerBackfill", { venue: S.segment.venue, label: S.segment.label })));
    }
    left = '<div class="c-chips">' + chips + "</div>" + '<div class="soft c-legend">' + legend + "</div>";
    document.getElementById("cLeft").innerHTML = left;
    var right = "";
    [["gap", "unitGap"], ["price", "unitPrice"]].forEach(function (u) {
      var s = txt(u[1]);
      if (s) right += chip(S.unit === u[0], 'data-unit="' + u[0] + '"', esc(s));
    });
    right += '<span class="c-gapx"></span>';
    [["7", "period7"], ["30", "period30"], ["all", "periodAll"]].forEach(function (p) {
      var s = txt(p[1]);
      if (s) right += chip(S.period === p[0], 'data-period="' + p[0] + '"', esc(s));
    });
    document.getElementById("cRight").innerHTML = '<div class="c-chips">' + right + "</div>";
  }

  // What the chart shows for the current choices; also feeds the tooltip and the drag summary.
  var view = null;
  function drawChart() {
    var win = windowFor(S.period), t0 = win[0], t1 = win[1];
    var months = monthsFor(t0, t1);
    document.getElementById("cChart").classList.add("busy");
    return loadMonths(months).then(function (lists) {
      var rows = [].concat.apply([], lists);
      var src = bySource(rows);
      var price = S.unit === "price";
      var off = officialPts(t0, t1);
      var model = {
        t0: t0, t1: t1, includeZero: !price,
        sources: S.idx.sources.map(function (s, i) {
          var lk = look(i);
          return { color: lk[0], cap: lk[1], pts: S.hidden[i] ? [] : src[i].map(function (r) { return [r.t, price ? r.price : r.gap]; }) };
        }),
        official: price ? off.map(function (o) { return [o[0], o[1]]; }) : [[t0, 0], [t1, 0]],
        band: [], daily: [], segment: [],
        yfmt: function (v) { return price ? num(v, v >= 100 ? 0 : v >= 10 ? 1 : 2) : pct(v); }
      };
      if (S.bandLo != null) {
        model.band = price
          ? off.map(function (o) { return [o[0], o[1] * (1 + S.bandLo / 100), o[1] * (1 + S.bandHi / 100)]; })
          : [[t0, S.bandLo, S.bandHi], [t1, S.bandLo, S.bandHi]];
      }
      if (!price && S.daily) model.daily = dailyPts();
      if (!price && S.seg && S.segment) model.segment = segmentPts();
      view = { win: win, src: src, off: S.idx.official, daily: dailyPts(), segment: S.segment ? segmentPts() : [], price: price };
      document.getElementById("cChart").classList.remove("busy");
      chart.update(model);
      var empty = !model.sources.some(function (s) { return s.pts.length; }) && !model.daily.length && !model.segment.length;
      document.getElementById("cAxis").innerHTML =
        "<span>" + esc((t1 - t0 > 300 * DAY ? dayLong : dayShort)(t0)) + "</span>" + w("chartCaption", null, "span") + "<span>" + esc((t1 - t0 > 300 * DAY ? dayLong : dayShort)(t1)) + "</span>";
      document.getElementById("cSel").innerHTML = "";
      S.sel = null;
      if (empty) document.getElementById("cSel").innerHTML = w("chartEmpty", null, "p", ["muted", "c-small"]);
      drawNotes();
    }).catch(function () {
      document.getElementById("cChart").classList.remove("busy");
      document.getElementById("cSel").innerHTML = w("chartFailed", null, "p", ["muted", "c-small"]);
    });
  }

  function drawNotes() {
    var out = "";
    var rec = recordLine();
    if (rec) out += '<p class="soft c-small">' + esc(rec) + "</p>";
    if (S.segment) {
      var sg = S.segment, first = dayLong(isoEpoch(sg.first)), last = dayLong(isoEpoch(sg.last));
      if (S.seg) {
        out += w("historySegmentSource", { since: dayShort(isoEpoch(S.history[0].date)), venue: sg.venue, fxSource: sg.fx_source, first: first, last: last, label: sg.label }, "p", ["muted", "c-small"]);
        var moves = (sg.largest_moves || []).map(function (m) {
          return txt("historySegmentMoveItem", { delta: (m.delta_pct > 0 ? "+" : "") + num(m.delta_pct, 1), date: dayLong(isoEpoch(m.date)) });
        }).filter(Boolean).join(", ");
        if (moves) out += w("historySegmentMoves", { moves: moves }, "p", ["muted", "c-small"]);
        out += '<p class="mono muted c-small"><a href="' + RAW + "data/country_history_segment/" + esc(ccy) + '.json">data/country_history_segment/' + esc(ccy) + ".json</a></p>";
      }
    } else {
      out += w("historyStart", { date: dayLong(isoEpoch(S.history[0].date)) }, "p", ["muted", "c-small"]);
    }
    document.getElementById("cNotes").innerHTML = out;
  }

  // ---------------------------------------------------------------- tooltip and drag summary
  function tipHtml(t) {
    if (!view) return "";
    var rows = "", stampT = null, best = Infinity;
    view.src.forEach(function (arr, i) {
      if (S.hidden[i] || !arr.length) return;
      var j = nearest(arr, t, "t"), r = arr[j], d = Math.abs(r.t - t);
      if (d > TIP_WINDOW) return;
      if (d < best) { best = d; stampT = r.t; }
      var lk = look(i);
      rows += '<div class="c-trow">' + swatch(lk) + '<span class="c-tname">' + esc(S.idx.sources[i].id) + '</span><span class="mono">' +
        esc(price_(r.price) + " " + ccy) + "</span><span class=\"mono muted\">" + esc(pct(r.gap)) + "</span></div>";
    });
    if (stampT != null && view.off.length) {
      var oj = nearest(view.off, stampT, 0);
      var ov = view.off[oj];
      rows += '<div class="c-trow"><i class="c-line" style="background:var(--color-ink)"></i>' + w("tipOfficial", null, "span", "c-tname") +
        '<span class="mono">' + esc(price_(ov[1]) + " " + ccy) + "</span></div>";
    }
    if (!view.price) {
      if (S.daily && view.daily.length) {
        var dj = nearest(view.daily, t, 0);
        if (Math.abs(view.daily[dj][0] - t) <= DAY) {
          rows += '<div class="c-trow"><i class="c-line" style="background:var(--color-neutral-700)"></i>' + w("tipDaily", null, "span", "c-tname") +
            '<span class="mono muted">' + esc(pct(view.daily[dj][1])) + "</span></div>";
          if (stampT == null) stampT = view.daily[dj][0];
        }
      }
      if (S.seg && view.segment.length) {
        var sj = nearest(view.segment, t, 0);
        if (Math.abs(view.segment[sj][0] - t) <= 4 * DAY) {
          rows += '<div class="c-trow"><i class="c-line dashed"></i>' + w("tipBackfill", { label: S.segment.label, venue: S.segment.venue }, "span", "c-tname") +
            '<span class="mono muted">' + esc(pct(view.segment[sj][1])) + "</span></div>";
          if (stampT == null) stampT = view.segment[sj][0];
        }
      }
    }
    if (!rows) return "";
    var isDay = stampT != null && best === Infinity;
    return '<div class="mono c-tstamp">' + esc(isDay ? dayLong(stampT) : stamp(stampT)) + "</div>" + rows;
  }
  function price_(v) { return price(v); }

  function onSelect(a, b) {
    var box = document.getElementById("cSel");
    if (a == null || !view) { S.sel = null; box.innerHTML = ""; return; }
    var vals = [];
    view.src.forEach(function (arr, i) {
      if (S.hidden[i]) return;
      arr.forEach(function (r) { if (r.t >= a && r.t <= b) vals.push(r.gap); });
    });
    var n = vals.length;
    if (!n) {
      if (S.daily) view.daily.forEach(function (p) { if (p[0] >= a && p[0] <= b) vals.push(p[1]); });
      if (S.seg) view.segment.forEach(function (p) { if (p[0] >= a && p[0] <= b) vals.push(p[1]); });
    }
    if (!vals.length) { box.innerHTML = ""; return; }
    var cells = statCell("selWindow", dayShort(a) + " – " + dayShort(b)) +
      (n ? statCell("selReadings", num(n, 0)) : "") +
      statCell("selMedian", pct(median(vals))) +
      statCell("selRange", pct(Math.min.apply(null, vals)) + " – " + pct(Math.max.apply(null, vals)));
    box.innerHTML = '<div class="c-stats">' + cells + "</div>";
  }

  // ---------------------------------------------------------------- receipts
  function buildReceiptsSection() {
    return '<section class="c-sec"><div class="c-sechead">' + w("receiptsHeading", { country: S.country.country }, "h2") +
      w("receiptsLead", { country: S.country.country }, "p", ["muted", "c-small"]) + "</div>" +
      '<div id="cDepth"></div><div class="c-list" id="cReceipts"></div></section>';
  }
  function drawDepth() {
    var d = S.depth, box = document.getElementById("cDepth");
    if (!d) { box.innerHTML = ""; return; }
    var key = d.is_floor ? "depthNowFloor" : "depthNowMoved";
    box.innerHTML = w(key, { amount: money(d.depth_usd), pct: d.threshold_pct, held: d.n_ads_held, priced: d.n_ads_priced }, "p", ["soft", "c-small"]);
  }
  function loadLatest() {
    var months = S.idx.months.slice().reverse(), got = [], i = 0;
    function next() {
      if (i >= months.length || got.length >= LATEST_ROWS) return Promise.resolve(got);
      return loadMonth(months[i++]).then(function (rows) { got = got.concat(rows); return next(); });
    }
    return next().then(function (rows) {
      return rows.sort(function (a, b) { return b.t - a.t || a.s - b.s; }).slice(0, LATEST_ROWS);
    });
  }
  function drawReceipts(rows) {
    var box = document.getElementById("cReceipts");
    if (!rows.length) { box.innerHTML = w("receiptsEmpty", null, "p", ["muted", "c-small"]); return; }
    var basisDone = false;
    var out = '<div class="c-row c-rhead">' + w("rcolTime", null, "span", ["c-ct", "muted"]) + w("rcolSource", null, "span", ["c-cs", "muted"]) +
      w("rcolPrice", null, "span", ["c-cp", "muted"]) + w("rcolGap", null, "span", ["c-cg", "muted"]) + w("rcolDepth", null, "span", ["c-cd", "muted"]) +
      w("rcolRaw", null, "span", ["c-cr", "muted"]) + "</div>";
    rows.forEach(function (r) {
      var s = S.idx.sources[r.s] || { id: "", raw_file: "" };
      var priceText = price(r.price) + " " + ccy;
      var cell = esc(priceText);
      if (!basisDone && S.hasBasis && s.raw_file === "data/p2p_basis.csv") {
        basisDone = true;
        cell = '<span data-receipt-basis-ccy="' + esc(ccy) + '" data-receipt-value="' + esc(priceText) + '" tabindex="0">' + esc(priceText) + "</span>";
      }
      var depth = r.n != null ? esc(txt("depthAds", { n: r.n, total: r.total != null ? num(r.total, 0) : "" })) : esc(txt("depthNone"));
      out += '<div class="c-row"><span class="mono muted c-ct">' + esc(stamp(r.t)) + '</span><span class="c-cs">' + swatch(look(r.s)) + esc(s.id) +
        '</span><span class="mono c-cp">' + cell + '</span><span class="mono c-cg">' + esc(pct(r.gap)) + '</span><span class="mono c-cd">' + depth +
        '</span><span class="mono c-cr"><a href="' + RAW + esc(s.raw_file) + '">' + esc(s.raw_file) + "</a></span></div>";
    });
    box.innerHTML = out;
  }

  // ---------------------------------------------------------------- start
  function start(res) {
    var idxDoc = res[0], copyDoc = res[1], countryDoc = res[2], readIdx = res[3], manifest = res[4],
      depthDoc = res[5], heat = res[6], latest = res[7];
    NAV = (copyDoc && copyDoc.nav) || [];
    COPY = (copyDoc && copyDoc.countryData) || {};
    if (!ccy) { notice("notFound", { code: "" }); return; }
    var country = (idxDoc.countries || []).filter(function (c) { return c.ccy === ccy; })[0];
    var withheld = (idxDoc.withheld || []).filter(function (c) { return c.ccy === ccy; })[0];
    if (!country && !withheld) { notice("notFound", { code: ccy }); return; }
    if (!country) { notice(["withheldTitle", "withheldBody"], { country: withheld.country, reason: withheld.reason }); return; }
    if (!countryDoc || !readIdx) throw new Error("data");

    S.country = country;
    S.idx = readIdx;
    S.history = countryDoc.history || [];
    S.cdoc = countryDoc;
    S.headline = country.median_24h_pct != null ? country.median_24h_pct : country.index_pct;
    S.p2p = null;
    S.depth = depthDoc && depthDoc.countries && depthDoc.countries[ccy] || null;
    var hm = heat && (heat.currencies || []).filter(function (c) { return c.ccy === ccy; })[0];
    S.ranked = !(hm && hm.ranked === false);
    var hasSeg = !!(manifest && manifest.ccys && manifest.ccys.indexOf(ccy) >= 0);

    if (!readIdx.months || !readIdx.months.length) {
      // No stored reading yet for this currency: the headline and the row only, no chart, no receipts.
      var offs0 = readIdx.official || [];
      S.asOf = offs0.length ? offs0[offs0.length - 1][0] : Date.now() / 1000;
      app.innerHTML = '<div class="c-wrap">' + head() + buildHero() + buildStats() + "</div>";
      return null;
    }
    // The newest month tells us when the last reading was; the window of every period hangs off it.
    var lastMonth = readIdx.months[readIdx.months.length - 1];
    var prep = [loadMonth(lastMonth), loadMonth(readIdx.months[0]), hasSeg ? maybeJSON("data/country_history_segment/" + ccy + ".json") : Promise.resolve(null),
      Promise.resolve(latest && latest.p2p && latest.p2p[ccy] || null)];
    return Promise.all(prep).then(function (r) {
      var all = r.splice(1, 1)[0];
      S.firstRead = all.reduce(function (m, x) { return Math.min(m, x.t); }, Infinity);
      if (!isFinite(S.firstRead)) S.firstRead = Date.now() / 1000 - 30 * DAY;
      var last = r[0].reduce(function (m, x) { return Math.max(m, x.t); }, 0);
      var offs = readIdx.official;
      S.asOf = Math.max(last, offs.length ? offs[offs.length - 1][0] : 0);
      S.segment = r[1] && r[1].points && r[1].points.length > 1 ? r[1] : null;
      if (r[2] && typeof r[2].fx_mid_per_usd === "number" && typeof r[2].buy_median === "number") S.p2p = r[2];
      S.hasBasis = !!S.p2p;
      var vals = S.history.map(function (h) { return h.index_pct; });
      if (vals.length >= 10) {
        var sorted = vals.slice().sort(function (a, b) { return a - b; });
        S.bandLo = quantile(sorted, BAND_LO); S.bandHi = quantile(sorted, BAND_HI);
      }
      var minutes = Math.max(0, Math.round((Date.now() / 1000 - S.asOf) / 60));
      var meta = '<span class="mono muted c-small">' + esc(txt("lastReading", { time: clock(S.asOf), date: dayShort(S.asOf), minutes: minutes })) + "</span>";
      app.innerHTML = '<div class="c-wrap">' + head(txt("lastReading") ? meta : "") + buildHero() + buildStats() +
        buildChartSection() + buildReceiptsSection() + "</div>";
      var slot = document.getElementById("cChartSlot");
      slot.parentNode.replaceChild(document.getElementById("cChartTpl").content.cloneNode(true), slot);
      chart = CountryChart.create(document.getElementById("cChart"), { tip: tipHtml, onSelect: onSelect, aria: txt("chartAria") });
      drawControls();
      drawDepth();
      document.getElementById("cLeft").addEventListener("click", clickLayer);
      document.getElementById("cRight").addEventListener("click", clickRight);
      loadLatest().then(drawReceipts).catch(function () {
        document.getElementById("cReceipts").innerHTML = w("receiptsFailed", null, "p", ["muted", "c-small"]);
      });
      return drawChart();
    });
  }

  function clickLayer(e) {
    var b = e.target.closest("[data-layer]");
    if (!b) return;
    var k = b.getAttribute("data-layer");
    if (k === "daily") S.daily = !S.daily;
    else if (k === "seg") S.seg = !S.seg;
    else S.hidden[+k.slice(1)] = !S.hidden[+k.slice(1)];
    drawControls();
    drawChart();
  }
  function clickRight(e) {
    var b = e.target.closest("button");
    if (!b) return;
    if (b.hasAttribute("data-unit")) S.unit = b.getAttribute("data-unit");
    if (b.hasAttribute("data-period")) S.period = b.getAttribute("data-period");
    drawControls();
    drawChart();
  }

  var C = function (u) { return u ? maybeJSON(u) : Promise.resolve(null); };
  Promise.all([
    getJSON("data/index_latest.json"), maybeJSON("copy.json"),
    ccy ? maybeJSON("data/countries/" + ccy + ".json") : Promise.resolve(null),
    ccy ? maybeJSON("data/country_readings/" + ccy + "/index.json") : Promise.resolve(null),
    C("data/country_history_segment/manifest.json"), C("data/street_depth_latest.json"), C("data/heatmap_daily.json"), C("data/latest.json")
  ]).then(start).catch(function (err) {
    if (window.console) console.error(err);
    COPY = COPY || {};
    maybeJSON("copy.json").then(function (d) {
      NAV = (d && d.nav) || [];
      COPY = (d && d.countryData) || {};
      notice("loadFailed");
    });
  });
})();

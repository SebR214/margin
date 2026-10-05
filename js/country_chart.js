/* The country chart (SEB-240, page 3).
 *
 * Hand-written SVG, no library. Draws what the page hands it and nothing
 * else: one dot per stored reading (one layer per source), the official rate
 * as a line, the usual range as a band, the published daily record and the
 * backfilled history as lines. It knows no words: every label, tooltip line
 * and number format is supplied by the page (country_page.js), which gets
 * its words from copy.json.
 *
 * Interactions follow the layout reference: a dashed crosshair and a tip
 * that follows the pointer, and a drag that shades a window and reports it
 * back through opts.onSelect(t0, t1) (null when cleared).
 *
 *   var chart = CountryChart.create(box, { tip: function (t) { return html; },
 *                                          onSelect: function (a, b) {} });
 *   chart.update(model)
 *
 * model: { t0, t1,                      epoch seconds, the visible window
 *          sources: [{ color, cap, pts: [[t, y], ...] }],
 *          official: [[t, y]], band: [[t, lo, hi]],
 *          daily: [[t, y]], segment: [[t, y]],
 *          yfmt: function (v) { return text } }
 */
(function () {
  var NS = "http://www.w3.org/2000/svg";

  function niceTicks(lo, hi, n) {
    var span = hi - lo || 1, step = Math.pow(10, Math.floor(Math.log10(span / n)));
    var err = span / n / step;
    step *= err >= 5 ? 5 : err >= 2 ? 2 : 1;
    var out = [], v = Math.ceil(lo / step) * step;
    for (; v <= hi + step * 1e-6; v += step) out.push(Math.abs(v) < step * 1e-6 ? 0 : v);
    return out;
  }

  function create(box, opts) {
    var model = null, W = 0, H = 380, selA = null, selB = null, drag = false, fx = null;
    // The svg and the tip are real markup in country.html (template cChartTpl).
    var svg = box.querySelector("svg"), base = box.querySelector(".cc-base"),
      selEl = box.querySelector(".cc-sel"), cross = box.querySelector(".cc-cross"), tip = box.querySelector(".cc-tip");
    if (opts.aria) svg.setAttribute("aria-label", opts.aria);

    function X(t) { return (t - model.t0) / (model.t1 - model.t0) * W; }
    function path(pts, xs, ys) {
      var d = "";
      for (var i = 0; i < pts.length; i++) d += (i ? "L" : "M") + xs(pts[i]).toFixed(1) + " " + ys(pts[i]).toFixed(1);
      return d;
    }

    function draw() {
      if (!model) return;
      W = Math.max(200, Math.round(box.clientWidth - 32));
      H = box.clientWidth < 560 ? 280 : 380;
      svg.setAttribute("viewBox", "0 0 " + W + " " + H);
      svg.setAttribute("width", W);
      svg.setAttribute("height", H);
      var top = 14, bot = 10, lo = Infinity, hi = -Infinity;
      function ext(v) { if (v < lo) lo = v; if (v > hi) hi = v; }
      var t0 = model.t0, t1 = model.t1;
      model.sources.forEach(function (s) { s.pts.forEach(function (p) { if (p[0] >= t0 && p[0] <= t1) ext(p[1]); }); });
      [model.daily, model.segment, model.official].forEach(function (a) {
        (a || []).forEach(function (p) { if (p[0] >= t0 && p[0] <= t1) ext(p[1]); });
      });
      (model.band || []).forEach(function (p) { if (p[0] >= t0 && p[0] <= t1) { ext(p[1]); ext(p[2]); } });
      if (model.includeZero) ext(0);
      if (!isFinite(lo)) { lo = 0; hi = 1; }
      var pad = (hi - lo || 1) * 0.06;
      lo -= pad; hi += pad;
      function Y(v) { return top + (1 - (v - lo) / (hi - lo)) * (H - top - bot); }
      var g = "";
      niceTicks(lo, hi, 3).forEach(function (v) {
        var y = Y(v).toFixed(1);
        g += '<line x1="0" x2="' + W + '" y1="' + y + '" y2="' + y + '" style="stroke:var(--color-neutral-200)"></line>' +
          '<text x="2" y="' + (y - 4) + '" class="cc-ax">' + model.yfmt(v) + "</text>";
      });
      var inW = function (a) { return (a || []).filter(function (p) { return p[0] >= t0 - 864000 && p[0] <= t1 + 864000; }); };
      var xs = function (p) { return X(p[0]); };
      var band = inW(model.band);
      if (band.length > 1) {
        var up = path(band, xs, function (p) { return Y(p[2]); });
        var dn = band.slice().reverse().map(function (p) { return "L" + X(p[0]).toFixed(1) + " " + Y(p[1]).toFixed(1); }).join("");
        g += '<path d="' + up + dn + 'Z" style="fill:var(--color-ink);fill-opacity:.13"></path>';
      }
      var seg = inW(model.segment);
      if (seg.length > 1) g += '<path d="' + path(seg, xs, function (p) { return Y(p[1]); }) +
        '" fill="none" stroke-width="1.2" stroke-dasharray="4 3" style="stroke:var(--data-700)" vector-effect="non-scaling-stroke"></path>';
      var dly = inW(model.daily);
      if (dly.length > 1) g += '<path d="' + path(dly, xs, function (p) { return Y(p[1]); }) +
        '" fill="none" stroke-width="1.2" style="stroke:var(--color-neutral-700)"></path>';
      var off = inW(model.official);
      if (off.length > 1) g += '<path d="' + path(off, xs, function (p) { return Y(p[1]); }) +
        '" fill="none" stroke-width="1.4" style="stroke:var(--color-ink)"></path>';
      model.sources.forEach(function (s) {
        var d = "";
        s.pts.forEach(function (p) { if (p[0] >= t0 && p[0] <= t1) d += "M" + X(p[0]).toFixed(1) + " " + Y(p[1]).toFixed(1) + "h0"; });
        if (d) g += '<path d="' + d + '" fill="none" stroke-width="5" stroke-linecap="' + s.cap +
          '" style="stroke:var(' + s.color + ');stroke-opacity:.8"></path>';
      });
      base.innerHTML = g;
      selEl.setAttribute("height", H);
      cross.setAttribute("y2", H);
      paintSel();
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
      clearSelection: function () { selA = selB = null; paintSel(); }
    };
  }

  window.CountryChart = { create: create };
})();

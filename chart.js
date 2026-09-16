/* The one chart component (SEB-61 / U6) -- browser half.
 *
 * The chart is already fully drawn in the page's own markup by tools/chart.py
 * at generation time: headline, change line, plot, gutter, badge and date
 * labels all render with no JavaScript and under `prefers-reduced-motion`.
 * This file only adds what genuinely needs a browser: redrawing the plot
 * when a reader picks a different range pill, and answering hover with a
 * point's value and date. Nothing here can appear before the static chart
 * already has.
 *
 * Stdlib DOM only, no build step, matching every other script on this site.
 */
(function () {
  "use strict";
  var WIDTH = 1000, HEIGHT = 200;
  var INDIGO = "#5A55E0", DOWN = "#D0453B", BACKFILL = "#b9b6b4";
  var WINDOWS = { "1w": 7, "1m": 30, "3m": 90, "1y": 365 };

  function fmtPct(v) {
    if (v === null || v === undefined || !isFinite(v)) return "—";
    var mag = Math.abs(v);
    return (v >= 0 ? "+" : "−") + mag.toFixed(mag >= 10 ? 1 : 2) + "%";
  }

  // Month names are reader-facing text, so they come from the copy deck via a
  // data attribute, the same way the change wording does -- never typed here.
  function longDate(iso, months) {
    var parts = iso.split("-").map(Number);
    return parts[2] + " " + months[parts[1] - 1] + " " + parts[0];
  }

  function sliceRange(all, key) {
    if (key === "all" || !WINDOWS[key]) return all;
    var last = new Date(all[all.length - 1].date + "T00:00:00Z");
    var cutoff = new Date(last.getTime() - WINDOWS[key] * 86400000);
    return all.filter(function (p) { return new Date(p.date + "T00:00:00Z") >= cutoff; });
  }

  function runs(pts) {
    var out = [], cur = [];
    for (var i = 0; i < pts.length; i++) {
      var p = pts[i], prev = cur[cur.length - 1];
      if (prev) {
        var days = (new Date(p.date + "T00:00:00Z") - new Date(prev.date + "T00:00:00Z")) / 86400000;
        if (days === 1 && p.backfill === prev.backfill) { cur.push(p); continue; }
        out.push(cur);
        cur = [];
      }
      cur.push(p);
    }
    if (cur.length) out.push(cur);
    return out;
  }

  function render(root, pts, copy) {
    var n = pts.length;
    // Scaled to the data's own range, not anchored to zero -- see chart.py's
    // _geometry for why (a series far from zero would otherwise flatten).
    var values = pts.map(function (p) { return p.index_pct; });
    var lo = Math.min.apply(null, values);
    var hi = Math.max.apply(null, values);
    var pad = (hi - lo) * 0.12 || 1;
    lo -= pad; hi += pad;
    var indexOf = {};
    pts.forEach(function (p, i) { indexOf[p.date] = i; });
    var x = function (i) { return n > 1 ? (i / (n - 1)) * WIDTH : 0; };
    var y = function (v) { return HEIGHT - ((v - lo) / (hi - lo)) * HEIGHT; };

    var svg = "";
    runs(pts).forEach(function (run) {
      var colour = run[0].backfill ? BACKFILL : INDIGO;
      if (run.length === 1) {
        var i0 = indexOf[run[0].date];
        svg += '<circle cx="' + x(i0).toFixed(1) + '" cy="' + y(run[0].index_pct).toFixed(1) +
          '" r="2.5" fill="' + colour + '"/>';
        return;
      }
      var seg = run.map(function (p) {
        return x(indexOf[p.date]).toFixed(1) + " " + y(p.index_pct).toFixed(1);
      }).join(" L ");
      if (!run[0].backfill) {
        var firstI = indexOf[run[0].date], lastI = indexOf[run[run.length - 1].date];
        svg += '<path d="M ' + x(firstI).toFixed(1) + " " + HEIGHT + " L " + seg + " L " +
          x(lastI).toFixed(1) + " " + HEIGHT + ' Z" fill="url(#chartFade)"/>';
      }
      svg += '<path d="M ' + seg + '" fill="none" stroke="' + colour +
        '" stroke-width="1.6" vector-effect="non-scaling-stroke"/>';
    });

    var last = pts[n - 1], first = pts[0];
    var badgeY = y(last.index_pct);
    svg += '<line x1="0" x2="' + WIDTH + '" y1="' + badgeY.toFixed(1) + '" y2="' + badgeY.toFixed(1) +
      '" stroke="' + INDIGO + '" stroke-width="1" stroke-dasharray="1 3" vector-effect="non-scaling-stroke"/>';
    root.querySelector(".chart-svg").innerHTML =
      root.querySelector(".chart-svg defs").outerHTML + svg;

    var badgePct = badgeY / HEIGHT * 100;
    root.querySelector(".chart-badge").style.top = badgePct + "%";
    root.querySelector(".chart-badge").textContent = fmtPct(last.index_pct);

    var gutterHtml = "";
    [[0, hi], [50, (hi + lo) / 2], [100, lo]].forEach(function (pair) {
      if (Math.abs(pair[0] - badgePct) < 12) return;
      gutterHtml += '<span class="chart-gutter-label" style="top:' + pair[0] + '%">' +
        fmtPct(pair[1]) + "</span>";
    });
    root.querySelector(".chart-gutter").innerHTML = gutterHtml;

    root.querySelector(".chart-value").textContent = fmtPct(last.index_pct);
    var changeEl = root.querySelector(".chart-change");
    var changePts = last.index_pct - first.index_pct;
    if (Math.round(changePts * 100) / 100 === 0) {
      changeEl.textContent = copy.changeNone;
      changeEl.style.color = "var(--muted)";
    } else {
      var sign = changePts >= 0 ? "+" : "−";
      var text = sign + Math.abs(changePts).toFixed(2) + " points";
      if (first.index_pct !== 0 && (first.index_pct > 0) === (last.index_pct > 0)) {
        var rel = changePts / Math.abs(first.index_pct) * 100;
        text += ", " + (changePts >= 0 ? copy.changeUp : copy.changeDown) + " " + Math.abs(rel).toFixed(1) + "%";
      }
      changeEl.textContent = text;
      changeEl.style.color = changePts >= 0 ? INDIGO : DOWN;
    }

    var fracs = [0, 1 / 3, 2 / 3, 1];
    var idxs = Array.from(new Set(fracs.map(function (f) { return Math.round(f * (n - 1)); })));
    var datesHtml = "";
    idxs.forEach(function (i, j) {
      var align = j === 0 ? "start" : (j === idxs.length - 1 ? "end" : "middle");
      datesHtml += '<span class="chart-date" style="text-align:' + align + '">' +
        longDate(pts[i].date, copy.months) + "</span>";
    });
    root.querySelector(".chart-dates").innerHTML = datesHtml;
  }

  function wire(root) {
    var all;
    try { all = JSON.parse(root.dataset.points || "[]"); } catch (e) { all = []; }
    if (all.length < 2) return;
    var current = all;
    var copy = {
      changeNone: root.dataset.copyChangeNone,
      changeUp: root.dataset.copyChangeUp,
      changeDown: root.dataset.copyChangeDown,
      months: (root.dataset.copyMonths || "").split("|")
    };

    var pills = root.querySelectorAll(".chart-pill");
    pills.forEach(function (btn) {
      btn.addEventListener("click", function () {
        current = sliceRange(all, btn.dataset.range);
        if (current.length < 2) return;
        render(root, current, copy);
        pills.forEach(function (b) { b.classList.toggle("is-on", b === btn); });
      });
    });

    var wrap = root.querySelector(".chart-plot-wrap");
    var hoverEl = root.querySelector(".chart-hover");
    if (!wrap || !hoverEl) return;
    wrap.addEventListener("mousemove", function (e) {
      var rect = wrap.getBoundingClientRect();
      if (!rect.width || current.length < 2) return;
      var frac = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
      var i = Math.round(frac * (current.length - 1));
      var p = current[i];
      if (!p) return;
      hoverEl.hidden = false;
      hoverEl.style.left = (current.length > 1 ? (i / (current.length - 1)) * 100 : 0) + "%";
      hoverEl.textContent = fmtPct(p.index_pct) + " — " + longDate(p.date, copy.months);
    });
    wrap.addEventListener("mouseleave", function () { hoverEl.hidden = true; });
  }

  document.documentElement.classList.add("js");
  window.MarginChart = { wire: wire };
})();

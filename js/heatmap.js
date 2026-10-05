/* The heatmap (SEB-240 step 0) -- browser half.
 *
 * Fetches data/heatmap.json (60 currencies, one cell per day since the live
 * collector's first day) and copy.json, then draws one frame at a time: 60
 * cells, one per currency, coloured by that day's gap. The date slider and
 * Play button move which day is on screen; nothing here computes a gap,
 * every value comes straight from the file.
 *
 * Every text label is a copy.json key read at runtime, never a literal in
 * this file (agents/RULES.md, the copy lock) -- an empty key means that
 * label stays out of the DOM until the writer fills it. Country names and
 * currency codes are data (same rule tools/emit_countries.py's COUNTRY map
 * already uses), not writer copy, so they render straight from the fetched
 * JSON.
 *
 * Stdlib DOM only, no build step, matching every other script on this site.
 */
(function () {
  "use strict";

  // Four bands, not a gradient: tools/check_rendered.py requires every
  // rendered colour to be an exact style.css token (no reader-facing page
  // may use an arbitrary hex), so a cell snaps to one of --amber-100/300/
  // 500/700 by how wide its gap is, same as --grid-empty for no data. If
  // those tokens move in style.css, these four hex values have to move
  // with them so the cells and the legend swatches never disagree.
  var BANDS = [
    { max: 2, hex: "#fdf6e8" },   // --amber-100: at or near the official rate
    { max: 10, hex: "#f0d48a" },  // --amber-300
    { max: 50, hex: "#d9a62e" },  // --amber-500
    { max: Infinity, hex: "#a9780f" } // --amber-700: the widest gaps
  ];
  var EMPTY_HEX = "#eaeaed"; // --grid-empty
  var PLAY_GLYPH = "▶", PAUSE_GLYPH = "❚❚";

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function cellColor(pct) {
    if (pct == null) return EMPTY_HEX;
    var v = Math.max(0, pct);
    for (var i = 0; i < BANDS.length; i++) {
      if (v <= BANDS[i].max) return BANDS[i].hex;
    }
    return BANDS[BANDS.length - 1].hex;
  }

  function fmtPct(v) {
    if (v == null || !isFinite(v)) return "—";
    return (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(1) + "%";
  }

  function setText(id, value) {
    var el = document.getElementById(id);
    if (!el) return;
    if (value) { el.textContent = value; el.hidden = false; }
    else { el.textContent = ""; el.hidden = true; }
  }

  function init(doc, copy) {
    var COPY = (copy && copy.home) || {};
    var dates = doc.dates || [];
    var currencies = doc.currencies || [];
    var lastIdx = dates.length - 1;

    setText("heatmapTitle", COPY.heatmapTitle);
    setText("heatmapSub", COPY.heatmapSub);
    setText("heatmapTop6Title", COPY.heatmapTop6Title);
    setText("heatmapLegendLowLab", COPY.heatmapLegendLowLab);
    setText("heatmapLegendHighLab", COPY.heatmapLegendHighLab);
    setText("heatmapBigLabel", COPY.heatmapBigLabel);

    var grid = document.getElementById("heatmapGrid");
    var slider = document.getElementById("heatmapSlider");
    var dateLabel = document.getElementById("heatmapDateLabel");
    var playBtn = document.getElementById("heatmapPlay");
    var bigNumber = document.getElementById("heatmapBigNumber");
    var top6List = document.getElementById("heatmapTop6List");
    if (!grid || !slider || !lastIdx || lastIdx < 0) return;

    slider.min = "0";
    slider.max = String(lastIdx);
    slider.value = String(lastIdx);

    var cells = currencies.map(function (cur) {
      var a = document.createElement("a");
      a.className = "heatmap-cell";
      a.href = "./country.html?ccy=" + encodeURIComponent(cur.ccy);
      grid.appendChild(a);
      return a;
    });

    // The page's one big number: Algeria's gap TODAY (the last date in the
    // file), fixed -- it does not move with the slider. Step 0 names
    // Algeria specifically (VISION.md's own example); if DZD is ever
    // missing from the file, the number stays blank rather than guessing.
    var dz = currencies.filter(function (c) { return c.ccy === "DZD"; })[0];
    var dzToday = dz && dz.cells[lastIdx];
    if (bigNumber) bigNumber.textContent = dzToday ? fmtPct(dzToday.index_pct) : "—";

    function render(i) {
      currencies.forEach(function (cur, idx) {
        var cell = cur.cells[i];
        cells[idx].style.backgroundColor = cellColor(cell && cell.index_pct);
        cells[idx].title = cur.ccy + (cell ? " " + fmtPct(cell.index_pct) : "");
      });
      if (dateLabel) dateLabel.textContent = dates[i] || "";

      if (top6List) {
        var ranked = currencies
          .filter(function (c) { return !c.unranked && c.cells[i] && c.cells[i].index_pct != null; })
          .sort(function (a, b) { return b.cells[i].index_pct - a.cells[i].index_pct; })
          .slice(0, 6);
        top6List.innerHTML = ranked.map(function (c) {
          return "<li>" + esc(c.country) + " " + esc(fmtPct(c.cells[i].index_pct)) + "</li>";
        }).join("");
      }
    }

    slider.addEventListener("input", function () {
      stopPlay();
      render(parseInt(slider.value, 10));
    });

    var playTimer = null;
    function stopPlay() {
      if (playTimer) { clearInterval(playTimer); playTimer = null; if (playBtn) playBtn.textContent = PLAY_GLYPH; }
    }
    if (playBtn) {
      playBtn.textContent = PLAY_GLYPH;
      playBtn.addEventListener("click", function () {
        if (playTimer) { stopPlay(); return; }
        playBtn.textContent = PAUSE_GLYPH;
        playTimer = setInterval(function () {
          var next = parseInt(slider.value, 10) + 1;
          if (next > lastIdx) { stopPlay(); return; }
          slider.value = String(next);
          render(next);
        }, 400);
      });
    }

    render(lastIdx);
  }

  document.addEventListener("DOMContentLoaded", function () {
    if (!document.getElementById("heatmapGrid")) return;
    Promise.all([
      fetch("./data/heatmap.json", { cache: "no-store" }).then(function (r) { return r.json(); }),
      fetch("./copy.json", { cache: "no-store" }).then(function (r) { return r.json(); }).catch(function () { return {}; })
    ]).then(function (res) { init(res[0], res[1]); }).catch(function () { /* loud failure: the section stays empty, nothing is invented */ });
  });
})();

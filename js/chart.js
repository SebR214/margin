// One chart component for the whole site (per docs/UI-SPEC-2026-09-16.md, U6).
// Renders an SVG line+area chart with a real Y axis, real X axis, the current
// value badge, and a hover tooltip that reads the nearest point's real value
// and timestamp -- never interpolated, never invented.
//
// Usage: MarginChart.render(container, { spark, timestamps, valueSuffix })
//   spark:      array of numbers, oldest first, last = current value
//   timestamps: array of ISO strings, same length as spark (optional but
//               required for the hover tooltip and x-axis labels to be real)
//   valueSuffix: e.g. "%"
(function (global) {
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  var MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  // Date only. A daily-cadence series shares the same collection hour across
  // every point, so repeating "13:00" on every single hover reading is
  // noise, not information -- the date is what actually changes point to
  // point.
  function fmtDate(iso) {
    if (!iso) return '';
    var d = new Date(iso);
    if (isNaN(d)) return '';
    return d.getUTCDate() + ' ' + MONTHS[d.getUTCMonth()];
  }

  function render(container, opts) {
    var spark = opts.spark || [];
    var timestamps = opts.timestamps || [];
    // xLabels: an axis that isn't time (e.g. a volume ladder) -- when given,
    // used verbatim for the end labels and the hover tooltip instead of
    // treating each point as a date. Same component, same visual language,
    // one non-time axis rather than a second chart to keep in sync with U6.
    var xLabels = opts.xLabels || null;
    var suffix = opts.valueSuffix == null ? '%' : opts.valueSuffix;
    // viewBox width = the container's real rendered width, not a fixed 1240.
    // width="100%" scales the whole coordinate system (text included) to fit
    // the container, so a fixed viewBox shrinks every label on a narrow
    // screen -- a 340px-wide phone container scaled a 1240-unit viewBox down
    // by 0.27x, turning a "17"-unit label into an actual ~4.5px glyph.
    // Measuring the container keeps 1 SVG unit equal to 1 real CSS pixel, so
    // font-size:17 always renders as 17px regardless of screen width.
    var w = opts.width || Math.round(container.getBoundingClientRect().width) || 1240, h = opts.height || 300;
    var rightGutter = 96, bottomAxis = 34, pad = 8;

    if (spark.length < 2) {
      container.innerHTML = '<div style="font-size:13px;color:#9A9A9A;padding:20px 0">Not enough points in this window yet.</div>';
      return;
    }

    var min = Math.min.apply(null, spark), max = Math.max.apply(null, spark);
    var range = (max - min) || 1;
    var plotW = w - rightGutter;
    var plotH = h - pad * 2 - bottomAxis;
    var stepX = plotW / (spark.length - 1);

    var pts = spark.map(function (v, i) {
      return { x: i * stepX, y: pad + (1 - (v - min) / range) * plotH, v: v, ts: timestamps[i], label: xLabels ? xLabels[i] : null };
    });
    var lastX = pts[pts.length - 1].x, lastY = pts[pts.length - 1].y, lastV = pts[pts.length - 1].v;
    // A tiny negative rounds to "-0.0" at one decimal -- true but reads as a
    // typo. Zero it explicitly rather than let toFixed manufacture a minus
    // sign the rounded figure doesn't actually carry.
    var badgeV = Math.abs(lastV) < 0.05 ? 0 : lastV;
    var badgeText = badgeV.toFixed(1) + suffix;
    // Width follows the actual text -- a 3-digit reading like "107.5%" is
    // measurably wider than "87.5%", and a fixed-width rect clipped it.
    // ~7.5px/char at 14px bold is a safe estimate for this font; padded.
    var badgeWidth = Math.max(50, badgeText.length * 8 + 16);

    var areaPath = 'M0,' + (h - bottomAxis) + ' L' + pts.map(function (p) { return p.x.toFixed(1) + ',' + p.y.toFixed(1); }).join(' ') + ' L' + lastX.toFixed(1) + ',' + (h - bottomAxis) + ' Z';
    var linePoly = pts.map(function (p) { return p.x.toFixed(1) + ',' + p.y.toFixed(1); }).join(' ');

    // Skip any axis label that would sit at the same height as the current-
    // value badge -- when the latest point IS the max (or min), that axis
    // label and the badge land on top of each other and both become
    // unreadable, which is exactly the "gray numbers and blue numbers
    // overlapping" bug: the same number drawn twice in the same spot.
    // 14px only excluded labels that literally collided pixel-for-pixel;
    // a 17px axis label and the 24px badge one line apart still read as
    // one smear (SEB, 2026-09-25 -- "90.7% and 90.4% almost sit on top of
    // each other"), so the exclusion zone needs to cover both text heights.
    var BADGE_HALF_HEIGHT = 24;
    var yLabels = [min, min + range / 2, max].filter(function (v) {
      var y = pad + (1 - (v - min) / range) * plotH;
      return Math.abs(y - lastY) > BADGE_HALF_HEIGHT;
    }).map(function (v) {
      var y = pad + (1 - (v - min) / range) * plotH;
      return '<text x="' + (plotW + 14) + '" y="' + (y + 5).toFixed(1) + '" font-family="Archivo, sans-serif" font-size="17" fill="#9A9A9A">' + v.toFixed(1) + suffix + '</text>';
    }).join('');

    var xFirst = xLabels ? (xLabels[0] || '') :
      (timestamps[0] ? fmtDate(timestamps[0]) : 'earliest in window');
    var xLast = xLabels ? (xLabels[xLabels.length - 1] || '') :
      (timestamps[timestamps.length - 1] ? fmtDate(timestamps[timestamps.length - 1]) : 'now');

    var uid = 'mc' + Math.random().toString(36).slice(2, 9);
    var svgId = 'svg-' + uid, tipId = 'tip-' + uid, dotId = 'dot-' + uid, vlineId = 'vl-' + uid;

    // refValue: an optional second reference line -- not this series, some
    // other real number worth comparing against (e.g. the incumbent rail's
    // own cost, so a crossover is something you can actually see cross).
    var refLine = '';
    if (opts.refValue != null && opts.refValue >= min - range * 0.15 && opts.refValue <= max + range * 0.15) {
      var refY = pad + (1 - (opts.refValue - min) / range) * plotH;
      refLine = '<line x1="0" y1="' + refY.toFixed(1) + '" x2="' + plotW.toFixed(1) + '" y2="' + refY.toFixed(1) + '" stroke="#9A9A9A" stroke-width="1" stroke-dasharray="4,3"/>' +
        (opts.refLabel ? '<text x="4" y="' + (refY - 5).toFixed(1) + '" font-family="Archivo, sans-serif" font-size="13" fill="#6B6B6B">' + esc(opts.refLabel) + '</text>' : '');
    }

    container.innerHTML =
      '<div style="position:relative">' +
      '<svg id="' + svgId + '" width="100%" viewBox="0 0 ' + w + ' ' + h + '" style="display:block;cursor:crosshair">' +
      // Plain grey line, grey fill -- periwinkle-line-on-eggshell-fill read
      // as an arbitrary mix of two accent colors on a chart that is just one
      // series over time, not a comparison (SEB, 2026-09-25). The palette's
      // accent colors stay reserved for charts that actually compare named
      // things (the cost waterfalls, the multi-series history chart).
      '<defs><linearGradient id="g-' + uid + '" x1="0" y1="0" x2="0" y2="1">' +
      '<stop offset="0" stop-color="#9A9A9A" stop-opacity="0.18"/>' +
      '<stop offset="1" stop-color="#9A9A9A" stop-opacity="0.02"/></linearGradient></defs>' +
      '<path d="' + areaPath + '" fill="url(#g-' + uid + ')"/>' +
      refLine +
      '<polyline points="' + linePoly + '" fill="none" stroke="#6B6B6B" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/>' +
      '<line x1="0" y1="' + lastY.toFixed(1) + '" x2="' + lastX.toFixed(1) + '" y2="' + lastY.toFixed(1) + '" stroke="#9A9A9A" stroke-width="1" stroke-dasharray="1.5,3.5" opacity="0.6"/>' +
      // Badge's left edge must match the axis labels' left edge (plotW+14
      // below) exactly -- they were two different hardcoded offsets (+6
      // here, +14 there) off the same lastX===plotW baseline, so the badge
      // and every axis percentage sat 8px out of column with each other on
      // every trend chart sitewide (SEB, 2026-09-26: "basic alignment").
      '<rect x="' + (lastX + 14).toFixed(1) + '" y="' + (lastY - 12).toFixed(1) + '" width="' + badgeWidth + '" height="24" rx="4" fill="#EDEDED"/>' +
      '<text x="' + (lastX + 14 + badgeWidth / 2).toFixed(1) + '" y="' + (lastY + 5).toFixed(1) + '" text-anchor="middle" font-family="Archivo, sans-serif" font-size="14" font-weight="700" fill="#0B0B0B">' + badgeText + '</text>' +
      yLabels +
      '<line id="' + vlineId + '" x1="0" y1="0" x2="0" y2="' + (h - bottomAxis) + '" stroke="#0B0B0B" stroke-width="1" opacity="0" />' +
      '<circle id="' + dotId + '" r="4" fill="#6B6B6B" stroke="#fff" stroke-width="1.5" opacity="0"/>' +
      '<text x="0" y="' + (h - 6) + '" text-anchor="start" font-family="Archivo, sans-serif" font-size="17" fill="#9A9A9A">' + esc(xFirst) + '</text>' +
      '<text x="' + lastX.toFixed(1) + '" y="' + (h - 6) + '" text-anchor="end" font-family="Archivo, sans-serif" font-size="17" fill="#9A9A9A">' + esc(xLast) + '</text>' +
      '</svg>' +
      '<div id="' + tipId + '" style="position:absolute;pointer-events:none;opacity:0;transition:opacity .08s;background:#0B0B0B;color:#fff;font-size:12px;font-family:Archivo,sans-serif;padding:6px 9px;border-radius:5px;white-space:nowrap;transform:translate(-50%,-130%)"></div>' +
      '</div>';

    var svg = container.querySelector('#' + svgId);
    var tip = container.querySelector('#' + tipId);
    var dot = container.querySelector('#' + dotId);
    var vline = container.querySelector('#' + vlineId);

    function nearest(px) {
      var best = 0, bestD = Infinity;
      for (var i = 0; i < pts.length; i++) {
        var d = Math.abs(pts[i].x - px);
        if (d < bestD) { bestD = d; best = i; }
      }
      return pts[best];
    }

    svg.addEventListener('mousemove', function (ev) {
      var rect = svg.getBoundingClientRect();
      var scale = w / rect.width;
      var px = (ev.clientX - rect.left) * scale;
      var p = nearest(px);
      dot.setAttribute('cx', p.x.toFixed(1));
      dot.setAttribute('cy', p.y.toFixed(1));
      dot.setAttribute('opacity', 1);
      vline.setAttribute('x1', p.x.toFixed(1));
      vline.setAttribute('x2', p.x.toFixed(1));
      vline.setAttribute('opacity', 0.25);
      var leftPct = (p.x / w) * 100;
      tip.style.left = leftPct + '%';
      tip.style.top = ((p.y / h) * 100) + '%';
      tip.style.opacity = 1;
      tip.style.fontSize = "14px";
      tip.textContent = p.v.toFixed(2) + suffix + (p.label ? ' · ' + p.label : (p.ts ? ' · ' + fmtDate(p.ts) : ''));
    });
    svg.addEventListener('mouseleave', function () {
      dot.setAttribute('opacity', 0);
      vline.setAttribute('opacity', 0);
      tip.style.opacity = 0;
    });
  }

  global.MarginChart = { render: render };
})(window);

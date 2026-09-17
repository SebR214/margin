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
  function fmtDate(iso) {
    if (!iso) return '';
    var d = new Date(iso);
    if (isNaN(d)) return '';
    var months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    return d.getUTCDate() + ' ' + months[d.getUTCMonth()] + ' ' + String(d.getUTCHours()).padStart(2,'0') + ':' + String(d.getUTCMinutes()).padStart(2,'0');
  }

  function render(container, opts) {
    var spark = opts.spark || [];
    var timestamps = opts.timestamps || [];
    var suffix = opts.valueSuffix == null ? '%' : opts.valueSuffix;
    var w = opts.width || 1240, h = opts.height || 300;
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
      return { x: i * stepX, y: pad + (1 - (v - min) / range) * plotH, v: v, ts: timestamps[i] };
    });
    var lastX = pts[pts.length - 1].x, lastY = pts[pts.length - 1].y, lastV = pts[pts.length - 1].v;

    var areaPath = 'M0,' + (h - bottomAxis) + ' L' + pts.map(function (p) { return p.x.toFixed(1) + ',' + p.y.toFixed(1); }).join(' ') + ' L' + lastX.toFixed(1) + ',' + (h - bottomAxis) + ' Z';
    var linePoly = pts.map(function (p) { return p.x.toFixed(1) + ',' + p.y.toFixed(1); }).join(' ');

    var yLabels = [min, min + range / 2, max].map(function (v) {
      var y = pad + (1 - (v - min) / range) * plotH;
      return '<text x="' + (plotW + 14) + '" y="' + (y + 4).toFixed(1) + '" font-family="Archivo, sans-serif" font-size="11" fill="#9A9A9A">' + v.toFixed(1) + suffix + '</text>';
    }).join('');

    var xFirst = timestamps[0] ? fmtDate(timestamps[0]) : 'earliest in window';
    var xLast = timestamps[timestamps.length - 1] ? fmtDate(timestamps[timestamps.length - 1]) : 'now';

    var uid = 'mc' + Math.random().toString(36).slice(2, 9);
    var svgId = 'svg-' + uid, tipId = 'tip-' + uid, dotId = 'dot-' + uid, vlineId = 'vl-' + uid;

    container.innerHTML =
      '<div style="position:relative">' +
      '<svg id="' + svgId + '" width="100%" viewBox="0 0 ' + w + ' ' + h + '" style="display:block;cursor:crosshair">' +
      '<defs><linearGradient id="g-' + uid + '" x1="0" y1="0" x2="0" y2="1">' +
      '<stop offset="0" stop-color="#DCDFFA" stop-opacity="0.95"/>' +
      '<stop offset="1" stop-color="#DCDFFA" stop-opacity="0.05"/></linearGradient></defs>' +
      '<path d="' + areaPath + '" fill="url(#g-' + uid + ')"/>' +
      '<polyline points="' + linePoly + '" fill="none" stroke="#5A55E0" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/>' +
      '<line x1="0" y1="' + lastY.toFixed(1) + '" x2="' + lastX.toFixed(1) + '" y2="' + lastY.toFixed(1) + '" stroke="#5A55E0" stroke-width="1" stroke-dasharray="1.5,3.5" opacity="0.7"/>' +
      '<rect x="' + (lastX + 6).toFixed(1) + '" y="' + (lastY - 10).toFixed(1) + '" width="64" height="20" rx="3" fill="#5A55E0"/>' +
      '<text x="' + (lastX + 38).toFixed(1) + '" y="' + (lastY + 4).toFixed(1) + '" text-anchor="middle" font-family="Archivo, sans-serif" font-size="11" font-weight="600" fill="#FFFFFF">' + lastV.toFixed(1) + suffix + '</text>' +
      yLabels +
      '<line id="' + vlineId + '" x1="0" y1="0" x2="0" y2="' + (h - bottomAxis) + '" stroke="#0B0B0B" stroke-width="1" opacity="0" />' +
      '<circle id="' + dotId + '" r="4" fill="#5A55E0" stroke="#fff" stroke-width="1.5" opacity="0"/>' +
      '<text x="0" y="' + (h - 6) + '" text-anchor="start" font-family="Archivo, sans-serif" font-size="12" fill="#9A9A9A">' + esc(xFirst) + '</text>' +
      '<text x="' + lastX.toFixed(1) + '" y="' + (h - 6) + '" text-anchor="end" font-family="Archivo, sans-serif" font-size="12" fill="#9A9A9A">' + esc(xLast) + '</text>' +
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
      tip.textContent = p.v.toFixed(2) + suffix + (p.ts ? ' · ' + fmtDate(p.ts) : '');
    });
    svg.addEventListener('mouseleave', function () {
      dot.setAttribute('opacity', 0);
      vline.setAttribute('opacity', 0);
      tip.style.opacity = 0;
    });
  }

  global.MarginChart = { render: render };
})(window);

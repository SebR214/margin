/* One tooltip for every chart (SEB-268 item 3). An element with data-tip="text" shows that text on hover and on tap.
   A chart that works out its own day (a pointer along a strip) calls window.siteTip.show(text, x, y) and window.siteTip.hide().
   No native title tooltips anywhere. */
(function () {
  var tip = document.createElement('div');
  tip.className = 'site-tip';
  tip.hidden = true;
  tip.setAttribute('role', 'tooltip');
  var st = document.createElement('style');
  st.textContent = '.site-tip{position:fixed;z-index:50;max-width:min(320px,calc(100vw - 16px));padding:6px 10px;background:var(--color-bg,#fff);color:var(--color-ink,#201e1d);' +
    'border:1px solid var(--color-neutral-300,#d7d3d3);border-radius:6px;font-size:13px;line-height:1.35;pointer-events:none;font-variant-numeric:tabular-nums;white-space:pre-line}.site-tip[hidden]{display:none}';
  function ready() { document.head.appendChild(st); document.body.appendChild(tip); }
  if (document.body) { ready(); } else { document.addEventListener('DOMContentLoaded', ready); }

  function show(text, x, y) {
    if (!text) { hide(); return; }
    tip.textContent = text; tip.hidden = false;
    var w = tip.offsetWidth, h = tip.offsetHeight, vw = window.innerWidth;
    var left = Math.min(vw - w - 8, Math.max(8, x - w / 2));
    var top = y - h - 14; if (top < 8) { top = y + 18; }
    tip.style.left = left + 'px'; tip.style.top = top + 'px';
  }
  function hide() { tip.hidden = true; }
  function target(e) { return e.target && e.target.closest ? e.target.closest('[data-tip]') : null; }
  // a chart or a row of squares works out its own text: the document-level handler must not hide what they just showed
  function zone(e) { return e.target && e.target.closest ? e.target.closest('.chart, .cells, [data-tipzone]') : null; }

  document.addEventListener('pointermove', function (e) { var el = target(e); if (el) { show(el.getAttribute('data-tip'), e.clientX, e.clientY); } else if (e.pointerType !== 'touch' && !zone(e)) { hide(); } });
  document.addEventListener('pointerdown', function (e) { var el = target(e); if (el) { show(el.getAttribute('data-tip'), e.clientX, e.clientY); } else if (!zone(e)) { hide(); } });
  document.addEventListener('scroll', hide, true);
  window.siteTip = { show: show, hide: hide };
})();

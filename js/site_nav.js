/* The one site menu (2 Nov 2026, DESIGN.md "Nav"). Every page draws its menu with siteNav.html() or siteNav.fill(nav), so
   the menu is the same on every page and right on the first frame. The words are copy.json "siteNav"; the block between
   the two DATA lines is written by tools/bake_nav.py from it. Edit copy.json, then run python3 tools/bake_nav.py.
   Loaded in each page's <head>, before any script that draws a header. */
(function () {
  // DATA:begin
  var N = {"main": [{"label": "Countries", "href": "./countries.html"}, {"label": "Events", "href": "./events.html"}, {"label": "Routes", "href": "./sending-money.html"}, {"label": "Research", "href": "./research.html"}], "about": "About", "aboutItems": [{"label": "How it works", "href": "./how-it-works.html"}, {"label": "Sources", "href": "./sources.html"}, {"label": "How it was built", "href": "./how-it-was-built.html"}]};
  // DATA:end
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function here() {
    var p = location.pathname, f = (p.split('/').pop() || 'index.html').toLowerCase();
    if (/\/country\//.test(p) || f === 'country.html') { return 'countries.html'; }
    var alias = { 'finding.html': 'research.html', 'research-capital-controls.html': 'research.html', 'research-source-pairs.html': 'research.html', 'event.html': 'events.html' };
    return alias[f] || f;
  }
  function file(h) { return h.split('?')[0].split('/').pop().toLowerCase(); }
  function link(it, cur) { return '<a href="' + esc(it.href) + '"' + (file(it.href) === cur ? ' aria-current="page"' : '') + ' data-text="' + esc(it.label) + '">' + esc(it.label) + '</a>'; }
  function html() {
    var cur = here(), inAbout = N.aboutItems.some(function (it) { return file(it.href) === cur; });
    return N.main.map(function (it) { return link(it, cur); }).join('') +
      '<span class="sh-about' + (inAbout ? ' sh-here' : '') + '"><button type="button" class="sh-about-btn" aria-expanded="false"><span class="sh-about-t" data-text="' + esc(N.about) + '">' + esc(N.about) + '</span></button>' +
      '<span class="sh-about-menu">' + N.aboutItems.map(function (it) { return link(it, cur); }).join('') + '</span></span>';
  }
  function fill(nav) { if (nav && !nav.querySelector('.sh-about')) { nav.innerHTML = html(); } }
  // About opens on click (and on hover where there is a mouse, css/site_head.css); a click elsewhere or Escape closes it
  function setOpen(box, open) { box.classList.toggle('sh-open-about', open); var b = box.querySelector('.sh-about-btn'); if (b) { b.setAttribute('aria-expanded', String(open)); } }
  document.addEventListener('click', function (e) {
    var b = e.target.closest && e.target.closest('.sh-about-btn');
    [].forEach.call(document.querySelectorAll('.sh-about.sh-open-about'), function (x) { if (!b || x !== b.parentNode) { setOpen(x, false); } });
    if (b) { e.stopPropagation(); setOpen(b.parentNode, !b.parentNode.classList.contains('sh-open-about')); }
  });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') { [].forEach.call(document.querySelectorAll('.sh-about.sh-open-about'), function (x) { setOpen(x, false); }); } });
  window.siteNav = { html: html, fill: fill };
})();

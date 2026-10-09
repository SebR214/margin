/* One footer on every page. Words come from copy.json (routeData.footerText, routeData.footerLinkText),
   the same two lines the sending-money page already shows. A page that already has a <footer> is left alone. */
(function () {
  if (document.querySelector('footer')) return;
  fetch('./copy.json', { cache: 'no-store' }).then(function (r) { return r.json(); }).then(function (C) {
    var R = (C && C.routeData) || {};
    if (!R.footerText && !R.footerLinkText) return;
    if (document.querySelector('footer')) return;
    var f = document.createElement('footer');
    f.className = 'site-footer';
    if (R.footerText) { var p = document.createElement('p'); p.textContent = R.footerText; f.appendChild(p); }
    if (R.footerLinkText) { var a = document.createElement('a'); a.href = 'https://github.com/SebR214/margin'; a.textContent = R.footerLinkText; f.appendChild(a); }
    // inside the page column, so it lines up with the content. A page that builds its column from script may not have it yet,
    // or may rebuild it: keep the footer in the current column for a few seconds.
    var COLUMN = '.wrap, .hp-wrap, .hw-wrap, .ci-wrap, .fp-wrap';
    var place = function () {
      var col = document.querySelector(COLUMN) || document.body;
      if (f.parentNode !== col) { col.appendChild(f); }
      else if (col !== document.body && col.lastElementChild !== f) { col.appendChild(f); }
    };
    place();
    if (window.MutationObserver) {
      var mo = new MutationObserver(place);
      mo.observe(document.body, { childList: true, subtree: true });
      setTimeout(function () { mo.disconnect(); }, 8000);
    }
  }).catch(function () {});
})();

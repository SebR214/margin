/* One footer on every page. Words come from copy.json (routeData.footerText, routeData.footerLinkText),
   the same two lines the sending-money page already shows. A page that already has a <footer> is left alone. */
(function () {
  // SEB-425: the same three links in the footer of every page (copy.json siteHead.footerLinks), so the pages nothing else links to
  // are one click from anywhere. A page that builds its own footer (data-links-only on its script tag) gets the links added to it.
  var linksOnly = !!(document.currentScript && document.currentScript.hasAttribute('data-links-only'));
  function addLinks(C) {
    var L = (C && C.siteHead && C.siteHead.footerLinks) || [];
    var f = document.querySelector('footer');
    if (!L.length || !f || f.querySelector('.site-links')) return;
    var p = document.createElement('p'); p.className = 'site-links';
    L.forEach(function (x, i) {
      if (i) p.appendChild(document.createTextNode(' \u00b7 '));
      var a = document.createElement('a'); a.href = x.href; a.textContent = x.label; p.appendChild(a);
    });
    f.appendChild(p);
  }
  function watch(C) {
    addLinks(C);
    if (window.MutationObserver) {
      var mo = new MutationObserver(function () { addLinks(C); });
      mo.observe(document.body, { childList: true, subtree: true });
      setTimeout(function () { mo.disconnect(); }, 8000);
    }
  }
  if (linksOnly) {
    fetch('./copy.json').then(function (r) { return r.json(); }).then(watch).catch(function () {});
    return;
  }
  if (document.querySelector('footer')) { fetch('./copy.json').then(function (r) { return r.json(); }).then(watch).catch(function () {}); return; }
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
    watch(C);
    if (window.MutationObserver) {
      var mo = new MutationObserver(place);
      mo.observe(document.body, { childList: true, subtree: true });
      setTimeout(function () { mo.disconnect(); }, 8000);
    }
  }).catch(function () {});
})();

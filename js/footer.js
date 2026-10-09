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
    (document.querySelector('.wrap, .hp-wrap, .hw-wrap') || document.body).appendChild(f);   // inside the page column, so it lines up with the content
  }).catch(function () {});
})();

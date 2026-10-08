/* Marks the current page in the nav on every page (aria-current), so the nav looks the same everywhere.
   Pages that build their nav from script (sources) are handled by watching for the links. */
(function () {
  var here = (location.pathname.split('/').pop() || 'index.html').toLowerCase();
  var alias = { 'finding.html': 'findings.html', '': 'index.html' };
  here = alias[here] || here;
  function mark() {
    var links = document.querySelectorAll('.hp-nav a, .ci-nav a, .c-nav a, .sm-nav a, .s-nav a, .fp-nav a, .mwh nav a');
    [].forEach.call(links, function (a) {
      var target = (a.getAttribute('href') || '').split('?')[0].split('#')[0].split('/').pop().toLowerCase();
      if (target && target === here) { a.setAttribute('aria-current', 'page'); }
    });
  }
  mark();
  document.addEventListener('DOMContentLoaded', mark);
  window.addEventListener('load', mark);
  var n = 0, t = setInterval(function () { mark(); if (++n > 20) { clearInterval(t); } }, 250);
})();

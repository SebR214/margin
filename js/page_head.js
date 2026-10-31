/* A page that is one template for many things (country.html?ccy=, finding.html?id=) sets its own title, description and
   canonical once it knows which thing it shows (SEB-425). The words come from copy.json siteHead. Static pages carry theirs
   in the HTML (tools/emit_site_files.py). */
(function () {
  var SITE = 'https://margin.wiki/', pending = null;
  function copy() {
    if (!pending) { pending = fetch('./copy.json').then(function (r) { return r.json(); }).then(function (c) { return (c && c.siteHead) || {}; }).catch(function () { return {}; }); }
    return pending;
  }
  function meta(attr, name, value) {
    var m = document.head.querySelector('meta[' + attr + '="' + name + '"]');
    if (!m) { m = document.createElement('meta'); m.setAttribute(attr, name); document.head.appendChild(m); }
    m.setAttribute('content', value);
  }
  function fill(t, vars) { return String(t || '').replace(/\{(\w+)\}/g, function (_, k) { return vars && vars[k] != null ? vars[k] : ''; }); }
  function set(o) {
    if (o.title) { document.title = o.title; meta('property', 'og:title', o.title); meta('name', 'twitter:title', o.title); }
    if (o.description) { meta('name', 'description', o.description); meta('property', 'og:description', o.description); meta('name', 'twitter:description', o.description); }
    if (o.path) {
      var url = SITE + o.path, l = document.head.querySelector('link[rel="canonical"]');
      if (!l) { l = document.createElement('link'); l.rel = 'canonical'; document.head.appendChild(l); }
      l.href = url; meta('property', 'og:url', url);
    }
    if (o.twin && !document.head.querySelector('link[rel="alternate"][type="text/markdown"]')) {
      var a = document.createElement('link'); a.rel = 'alternate'; a.type = 'text/markdown'; a.href = '/' + o.twin; document.head.appendChild(a);
    }
  }
  window.PageHead = { copy: copy, set: set, fill: fill };
})();

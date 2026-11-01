/* Machine view (SEB-301, 21 Oct): a Human/Machine switch fixed at the bottom centre of every page. Machine shows the page's markdown twin
   (written each hour by tools/emit_markdown.py) with its path, size, an approximate token count and three links: copy the
   markdown, copy a curl command, open the raw file. A copy briefly shows "Copied" in place of the link's own word. The
   choice is remembered per visitor. No model is involved. Every word comes from copy.json (machineView). While those
   words are empty the switch is not shown. */
(function () {
  var SITE = 'https://margin.wiki/';
  var COLUMN = '.wrap, .hp-wrap, .hw-wrap, .ci-wrap, .fp-wrap, .sm-wrap';
  var KEEP = '.mv-switch, .mv-panel, script, template, header, .hp-head, .ci-head, .c-head, .sm-head, .s-head, .fp-head, .mwh';   // Machine mode shows only the text: the site header, nav and footer are hidden too

  // the twin for this page, or null on a page that has none
  function twinPath() {
    var page = location.pathname.split('/').pop() || 'index.html';
    var q = new URLSearchParams(location.search);
    var own = location.pathname.match(/^\/country\/([a-z]{3})\/?$/);                       // a country's own page (SEB-426)
    if (own) { return 'country/' + own[1].toUpperCase() + '.md'; }
    if (page === 'country.html') { var c = q.get('ccy') || ''; return /^[A-Z]{3}$/.test(c) ? 'country/' + c + '.md' : null; }
    if (page === 'finding.html') { var id = q.get('id') || ''; return /^[a-z0-9_]+$/.test(id) ? 'finding/' + id + '.md' : null; }
    var plain = ['index.html', 'countries.html', 'sending-money.html', 'sources.html', 'how-it-works.html', 'how-it-was-built.html'];
    return plain.indexOf(page) >= 0 ? page.replace('.html', '.md') : null;
  }

  function remembered() { try { return localStorage.getItem('mv') === 'machine'; } catch (e) { return false; } }
  function remember(on) { try { localStorage.setItem('mv', on ? 'machine' : 'human'); } catch (e) {} }
  function fill(t, kv) { return Object.keys(kv).reduce(function (s, k) { return s.replace('{' + k + '}', kv[k]); }, String(t)); }
  function copy(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) { navigator.clipboard.writeText(text).catch(function () {}); return; }
    var ta = document.createElement('textarea'); ta.value = text; document.body.appendChild(ta); ta.select();
    try { document.execCommand('copy'); } catch (e) {} document.body.removeChild(ta);
  }
  // Briefly replace a link's own text with the "Copied" word, then put it back.
  function flash(a, word) {
    if (a._mvTimer) clearTimeout(a._mvTimer);
    if (a._mvLabel === undefined) a._mvLabel = a.textContent;
    a.textContent = word;
    a._mvTimer = setTimeout(function () { a.textContent = a._mvLabel; a._mvTimer = null; }, 1200);
  }

  var path = twinPath();
  if (!path) return;
  fetch('./copy.json', { cache: 'no-store' }).then(function (r) { return r.json(); }).then(function (C) {
    var W = (C && C.machineView) || {};
    var need = ['human', 'machine', 'copyMarkdown', 'copyCurl', 'openRaw', 'sizeLine', 'copied'];
    if (need.some(function (k) { return !W[k]; })) return;   // the words are not written yet

    var md = null;
    // one switch for the whole site, fixed at the bottom centre of the screen, outside the page column, so it sits in the
    // same place on every page and in both modes (21 Oct). Any other copy of it is removed.
    [].forEach.call(document.querySelectorAll('.mv-switch'), function (k) { k.remove(); });
    var sw = document.createElement('div'); sw.className = 'mv-switch'; sw.setAttribute('role', 'group');
    sw.innerHTML = '<button type="button" data-mv="human"></button><button type="button" data-mv="machine"></button>';
    document.body.appendChild(sw);
    var bH = sw.querySelector('[data-mv="human"]'), bM = sw.querySelector('[data-mv="machine"]');
    bH.textContent = W.human; bM.textContent = W.machine;

    var panel = document.createElement('section'); panel.className = 'mv-panel';
    var bar = document.createElement('div'); bar.className = 'mv-bar';
    var where = document.createElement('span'); where.className = 'mv-path'; where.textContent = '/' + path;
    var size = document.createElement('span'); size.className = 'mv-meta';
    var links = document.createElement('span'); links.className = 'mv-links';
    var aCopy = document.createElement('a'); aCopy.href = '#'; aCopy.textContent = W.copyMarkdown;
    var aCurl = document.createElement('a'); aCurl.href = '#'; aCurl.textContent = W.copyCurl;
    var aRaw = document.createElement('a'); aRaw.href = './' + path; aRaw.textContent = W.openRaw;
    links.appendChild(aCopy); links.appendChild(aCurl); links.appendChild(aRaw);
    bar.appendChild(where); bar.appendChild(size); bar.appendChild(links);
    var pre = document.createElement('pre'); pre.className = 'mv-md';
    panel.appendChild(bar);
    // one line pointing an agent at the whole site, llms.txt (SEB-301, 21 Oct); shown only while both words are written
    if (W.llmsLabel && W.llmsLink) {
      var llms = document.createElement('p'); llms.className = 'mv-llms';
      var aL = document.createElement('a'); aL.href = './llms.txt'; aL.textContent = W.llmsLink;
      llms.appendChild(document.createTextNode(W.llmsLabel + ' ')); llms.appendChild(aL);
      panel.appendChild(llms);
    }
    panel.appendChild(pre);
    aCopy.addEventListener('click', function (e) { e.preventDefault(); if (md) { copy(md); flash(aCopy, W.copied); } });
    aCurl.addEventListener('click', function (e) { e.preventDefault(); copy('curl -s ' + SITE + path); flash(aCurl, W.copied); });

    function column() { return document.querySelector(COLUMN) || document.body; }
    // the panel sits where the page content starts
    function place() {
      var col = column();
      if (sw.parentNode !== document.body) document.body.appendChild(sw);
      if (panel.parentNode !== col) {
        var h2 = col.querySelector(':scope > header, :scope > .site-head, :scope > .hp-head');
        col.insertBefore(panel, h2 ? h2.nextSibling : col.firstChild);
      }
    }
    var hidden = [];   // exactly what we hid last time, so a later call always clears it first (column() can return a
                        // different element once the page's own script finishes building its content)
    function show(on) {
      hidden.forEach(function (k) { k.removeAttribute('data-mv-hide'); });
      hidden = [];
      if (on) {
        var col = column();
        [].forEach.call(col.children, function (k) { if (!k.matches(KEEP)) { k.setAttribute('data-mv-hide', ''); hidden.push(k); } });
      }
      document.documentElement.classList.toggle('mv-on', on);
      bH.setAttribute('aria-pressed', on ? 'false' : 'true'); bM.setAttribute('aria-pressed', on ? 'true' : 'false');
      panel.classList.remove('mv-in');
      if (on) { requestAnimationFrame(function () { requestAnimationFrame(function () { panel.classList.add('mv-in'); }); }); }
      if (on && md === null) {
        md = '';
        fetch('./' + path, { cache: 'no-store' }).then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); }).then(function (t) {
          md = t; pre.textContent = t;
          var kb = new Blob([t]).size / 1024;
          size.textContent = fill(W.sizeLine, { size: kb.toLocaleString('en-US', { maximumFractionDigits: 1 }),
                                                 tokens: Math.round(t.length / 4).toLocaleString('en-US') });
        }).catch(function () { md = null; });
      }
    }
    place();
    bH.addEventListener('click', function () { remember(false); show(false); });
    bM.addEventListener('click', function () { remember(true); show(true); });
    show(remembered());
    // a page that builds its column from script may rebuild it: keep the switch and the panel in place for a few seconds
    if (window.MutationObserver) {
      var mo = new MutationObserver(function () { place(); if (remembered()) show(true); });
      mo.observe(document.body, { childList: true, subtree: true });
      setTimeout(function () { mo.disconnect(); }, 8000);
    }
  }).catch(function () {});
})();

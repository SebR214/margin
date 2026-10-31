/* The three pages about how the site is built (SEB-427) link to each other at the top: how-it-was-built, machine-room and
   agent-incidents. Words and links come from copy.json machineRoomPage.trio. The current page is bold and not a link. */
(function () {
  function base(h) { return String(h).split('/').pop().split('?')[0].split('#')[0]; }
  fetch('./copy.json').then(function (r) { return r.json(); }).then(function (C) {
    var T = ((C || {}).machineRoomPage || {}).trio || [];
    var header = document.querySelector('header');
    if (!T.length || !header || document.querySelector('.trio')) return;
    var here = base(location.pathname) || 'index.html';
    var st = document.createElement('style');
    st.textContent = '.trio{display:flex;flex-wrap:wrap;gap:6px 24px;font-size:15px;padding:4px 0 0;margin:0}' +
      '.trio a{color:var(--color-neutral-600);font-weight:500;padding:6px 0;display:inline-block}.trio a:hover{color:var(--color-ink)}' +
      '.trio b{color:var(--color-ink);font-weight:600;padding:6px 0;display:inline-block}';
    document.head.appendChild(st);
    var n = document.createElement('p'); n.className = 'trio';
    T.forEach(function (x) {
      var el;
      if (base(x.href) === here) { el = document.createElement('b'); el.setAttribute('aria-current', 'page'); }
      else { el = document.createElement('a'); el.href = x.href; }
      el.textContent = x.label; n.appendChild(el);
    });
    header.insertAdjacentElement('afterend', n);
  }).catch(function () {});
})();

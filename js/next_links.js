/* "Where to go next" (SEB-433): the closing block of a country, event, route and finding page. Rows look like the Research list
 * (title, one line, arrow). The page script decides which rows exist and passes words from copy.json; this only draws them.
 *   window.NextLinks.show(parent, heading, [{ title, line, href }], before)   a row is skipped without a title or href */
(function () {
  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
  window.NextLinks = {
    show: function (parent, heading, rows, before) {
      var old = document.getElementById("nxBlock");
      if (old) old.remove();
      rows = (rows || []).filter(function (r) { return r && r.title && r.href; });
      if (!parent || !heading || !rows.length) return null;
      var sec = el("section", "nx"); sec.id = "nxBlock";
      sec.appendChild(el("h2", "", heading));
      var list = sec.appendChild(el("div", "nx-list"));
      rows.forEach(function (r) {
        var a = list.appendChild(el("a", "nx-item")); a.href = r.href;
        var body = a.appendChild(el("span", "nx-body"));
        body.appendChild(el("span", "nx-title", r.title));
        if (r.line) body.appendChild(el("span", "nx-line", r.line));
        a.appendChild(el("span", "nx-go", "→"));
      });
      parent.insertBefore(sec, before || null);
      return sec;
    }
  };
})();

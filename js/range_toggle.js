/* The one range control (SEB-437): a row of pill buttons that picks how far back a chart or grid looks. The routes chart's Week and
 * Month pill was the model; the home grid, the routes chart and the country chart all draw it from here, so there is one markup and
 * one stylesheet (css/range_toggle.css). Words are passed in by the page (from copy.json); nothing is written here.
 *   RangeToggle.html([{id, label}], activeId)  -> the markup, or '' when fewer than two ranges are offered
 *   RangeToggle.pick(clickEvent)               -> the id of the range button that was clicked, or null
 *   RangeToggle.mark(rootElement, activeId)    -> set aria-pressed on the buttons under rootElement
 * A page offers only the ranges its record covers, and only a range that shows more than the shorter one. */
(function () {
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  window.RangeToggle = {
    html: function (items, active) {
      items = (items || []).filter(function (i) { return i && i.label; });
      if (items.length < 2) { return ''; }
      return '<div class="rt-bar" role="group">' + items.map(function (i) {
        return '<button type="button" data-range="' + esc(i.id) + '" aria-pressed="' + (i.id === active) + '">' + esc(i.label) + '</button>';
      }).join('') + '</div>';
    },
    pick: function (e) {
      var b = e && e.target && e.target.closest ? e.target.closest('[data-range]') : null;
      return b ? b.getAttribute('data-range') : null;
    },
    mark: function (root, active) {
      [].forEach.call((root || document).querySelectorAll('[data-range]'), function (b) { b.setAttribute('aria-pressed', b.getAttribute('data-range') === active ? 'true' : 'false'); });
    }
  };
})();

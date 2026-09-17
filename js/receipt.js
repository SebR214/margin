// R2 -- the receipt replay. Click any indexed number, get an overlay that
// replays 4 real steps: the evidence, the official rate, the math, the
// verdict. Reads data/latest.json's p2p entries (the raw per-country ads
// data that index_latest.json's index_pct was itself computed from -- see
// the exact-match check in this file's commit message) and index_latest.json
// for the published figure and its evidence-rule inputs. Never recomputes
// or rounds differently from the number that opened it -- it reads, it does
// not calculate a second time.
(function (global) {
  var _idx = null, _raw = null, _loading = null;

  function load() {
    if (_loading) return _loading;
    _loading = Promise.all([
      fetch('./data/index_latest.json', { cache: 'no-store' }).then(function (r) { return r.json(); }),
      fetch('./data/latest.json', { cache: 'no-store' }).then(function (r) { return r.json(); })
    ]).then(function (res) { _idx = res[0]; _raw = res[1]; });
    return _loading;
  }

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function fmtTs(iso) {
    if (!iso) return '';
    var d = new Date(iso);
    if (isNaN(d)) return '';
    return d.toISOString().slice(0, 16).replace('T', ' ') + ' UTC';
  }

  function closeOverlay() {
    var el = document.getElementById('receiptOverlay');
    if (el) el.remove();
    document.removeEventListener('keydown', onKey);
  }
  function onKey(e) { if (e.key === 'Escape') closeOverlay(); }

  function open(ccy) {
    load().then(function () {
      var country = (_idx.countries || []).find(function (c) { return c.ccy === ccy; });
      if (!country) return;
      var p2p = _raw.p2p && _raw.p2p[ccy];

      var overlay = document.createElement('div');
      overlay.id = 'receiptOverlay';
      overlay.style.cssText = 'position:fixed;inset:0;background:rgba(11,11,11,0.55);z-index:9999;display:flex;align-items:center;justify-content:center;padding:24px';
      overlay.addEventListener('click', function (e) { if (e.target === overlay) closeOverlay(); });

      var box = document.createElement('div');
      box.style.cssText = 'background:#fff;border-radius:16px;max-width:640px;width:100%;max-height:86vh;overflow-y:auto;padding:32px;font-family:Archivo,system-ui,sans-serif;color:#0B0B0B;position:relative;box-shadow:0 24px 60px rgba(0,0,0,0.3)';

      var closeBtn = '<button aria-label="close" id="receiptClose" style="position:absolute;top:20px;right:20px;width:32px;height:32px;border-radius:50%;border:0;background:#F6F6F6;cursor:pointer;font-size:16px;color:#6B6B6B">✕</button>';
      var header = '<div style="font-size:11px;letter-spacing:.08em;color:#9A9A9A;padding-right:40px">' +
        esc(country.country.toUpperCase()) + ' · ' + (country.index_pct >= 0 ? '+' : '') + country.index_pct.toFixed(1) + '% · ' + fmtTs(country.hour_utc) + '</div>' +
        '<div style="font-size:20px;font-weight:800;padding-top:6px;padding-bottom:4px">The receipt</div>' +
        '<div style="font-size:14px;color:#6B6B6B;padding-bottom:26px">Every number on this site can show how it was made. Four real steps, each naming its file.</div>';

      var stepsHtml, id = 'r' + Math.random().toString(36).slice(2, 8);
      if (p2p) {
        var reqAds = _idx.min_buy_ads || 10;
        var verdictOk = (p2p.n_ads || 0) >= reqAds;
        stepsHtml = [
          step(1, 'THE EVIDENCE',
            Math.round(p2p.n_ads) + ' sell-side ads collected on the open market at ' + fmtTs(p2p.ts_utc) + ' · median asking price <b class="num">' + p2p.buy_median.toLocaleString(undefined,{maximumFractionDigits:4}) + ' ' + esc(ccy) + '</b> per dollar',
            'data/p2p_basis.csv'),
          step(2, 'THE OFFICIAL RATE',
            'captured in the same pass: <b class="num">' + p2p.fx_mid_per_usd.toLocaleString(undefined,{maximumFractionDigits:4}) + ' ' + esc(ccy) + '</b> per dollar',
            'data/fx_rates.csv'),
          step(3, 'THE MATH',
            p2p.buy_median.toLocaleString(undefined,{maximumFractionDigits:4}) + ' ÷ ' + p2p.fx_mid_per_usd.toLocaleString(undefined,{maximumFractionDigits:4}) + ' − 1 = <b class="num">' + (country.index_pct >= 0 ? '+' : '') + country.index_pct.toFixed(2) + '%</b> — a dollar ' + (country.index_pct >= 0 ? 'costs ' + country.index_pct.toFixed(1) + '% more' : 'costs ' + Math.abs(country.index_pct).toFixed(1) + '% less') + ' than the official rate says',
            'data/index_latest.json'),
          step(4, 'THE VERDICT',
            'published, because the evidence rule is ' + (verdictOk ? 'met' : 'not met') + ' — ' + Math.round(p2p.n_ads) + ' ads, ' + reqAds + ' required. One bad hour and this number would be withheld instead.',
            'data/index_latest.json')
        ].join('');
      } else {
        stepsHtml = '<div style="padding:20px 0;color:#6B6B6B;font-size:15px;line-height:1.6">This country is priced from an exchange order book (' + esc(country.source_class || '') +
          '), not from person-to-person ads. The published figure is real (<b class="num">' + (country.index_pct>=0?'+':'') + country.index_pct.toFixed(2) + '%</b>, from ' + esc(country.source_file) + '), but the raw per-venue price and official rate this receipt needs aren\'t in a published file yet — shown honestly rather than filled in.</div>';
      }

      var footer = '<div style="border-top:1px solid #F0F0F0;margin-top:22px;padding-top:16px;font-size:13px;color:#6B6B6B">Opened from ' + esc(country.country) + '’s number on this page. <a href="./data.html" style="font-weight:600;color:#0B0B0B">Open the raw files →</a></div>';

      box.innerHTML = closeBtn + header + '<div id="steps-' + id + '">' + stepsHtml + '</div>' + footer;
      overlay.appendChild(box);
      document.body.appendChild(overlay);
      document.addEventListener('keydown', onKey);
      document.getElementById('receiptClose').addEventListener('click', closeOverlay);

      // Staged reveal, ~3s total per U6/R2; instant for prefers-reduced-motion.
      var reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      var stepEls = box.querySelectorAll('.receipt-step');
      stepEls.forEach(function (el, i) {
        if (reduced) { el.style.opacity = 1; return; }
        el.style.opacity = 0;
        el.style.transform = 'translateY(6px)';
        el.style.transition = 'opacity .35s ease, transform .35s ease';
        setTimeout(function () { el.style.opacity = 1; el.style.transform = 'translateY(0)'; }, i * 650);
      });
    });
  }

  function step(n, label, body, file) {
    return '<div class="receipt-step" style="display:flex;gap:16px;padding:16px 0;border-top:1px solid #F0F0F0">' +
      '<div style="font-size:20px;font-weight:800;color:#5A55E0;flex:0 0 auto;width:24px">' + n + '</div>' +
      '<div style="flex:1;min-width:0"><div style="font-size:11px;letter-spacing:.08em;color:#9A9A9A;padding-bottom:4px">' + label + '</div>' +
      '<div style="font-size:15px;line-height:1.55" class="num">' + body + '</div></div>' +
      '<div style="flex:0 0 auto;font-size:12px;color:#9A9A9A;font-family:ui-monospace,monospace;padding-top:2px">' + esc(file) + '</div>' +
      '</div>';
  }

  // Auto-wire: any element with data-receipt="CCY" opens the receipt for
  // that currency on click, no per-page listener code needed.
  document.addEventListener('click', function (e) {
    var el = e.target.closest('[data-receipt]');
    if (el) open(el.getAttribute('data-receipt'));
  });

  global.MarginReceipt = { open: open };
})(window);

/* The claims gate for pages. data/claims_status.json is written hourly by
   tools/audit_claims.py. A copy key whose claim is not true (or any key a failing
   claim guards) must not be rendered. If the status file cannot be read, a guarded
   key is treated as blocked: a line that cannot be checked is not shown.

     Claims.load().then(function(){ if (!Claims.blocked('homeData.stableLine')) ... });
*/
(function (w) {
  var status = null, loaded = false;
  var Claims = {
    load: function () {
      return fetch('./data/claims_status.json', { cache: 'no-store' })
        .then(function (r) { return r.ok ? r.json() : null; })
        .catch(function () { return null; })
        .then(function (d) { status = d; loaded = true; return d; });
    },
    /* true when this copy key must not be shown. Keys with no claim are never blocked
       as long as the file loaded; a key asked about while the file is unreadable is blocked. */
    blocked: function (key) {
      if (!status || !status.claims) return true;
      var c = status.claims;
      if (c[key]) return c[key].ok !== true;
      return Object.keys(c).some(function (k) { return c[k].ok !== true && (c[k].guards || []).indexOf(key) >= 0; });
    }
  };
  w.Claims = Claims;
})(window);

/* The events list (SEB-423 step 2): every event that has a page, newest first, from data/events_published.json (tools/publish_events.py).
 * Each row links to the event's page and to the home map on that day. Words: copy.json, block "eventsPage". Numbers, dates, names are data. */
(function () {
  var MINUS = "\u2212";
  var MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  var C = {}, NAMES = {};
  var app = document.getElementById("app");
  var NAV = [["navCountries", "./countries.html"], ["navRoutes", "./sending-money.html"], ["navSources", "./sources.html"],
    ["navFindings", "./findings.html"], ["navResearch", "./research.html"], ["navEvents", "./events.html"], ["navHow", "./how-it-works.html"]];
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function txt(k, v) { var s = C[k]; return s ? String(s).replace(/\{(\w+)\}/g, function (m, x) { return v && v[x] != null ? v[x] : ""; }) : ""; }
  function getJSON(u) { return fetch(u, { cache: "no-store" }).then(function (r) { if (!r.ok) throw new Error(u); return r.json(); }); }
  function day(iso) { return (+iso.slice(8, 10)) + " " + MON[+iso.slice(5, 7) - 1] + " " + iso.slice(0, 4); }
  function pct(v) { return Math.round(Math.abs(v)) + "%"; }
  function nav() {
    return '<header class="sm-head"><a class="sm-logo" href="./index.html">margin.wiki</a><nav class="sm-nav" aria-label="Main">' + NAV.map(function (n) {
      var t = C[n[0]]; return t ? '<a href="' + n[1] + '"' + (n[1] === "./events.html" ? ' aria-current="page"' : "") + ">" + esc(t) + "</a>" : "";
    }).join("") + "</nav></header>";
  }
  function row(e) {
    var name = NAMES[e.ccy] || e.ccy, up = e.change_pct >= 0, k = e.event_kind === "street_slide" ? "Street" : "Official";
    var title = txt("row" + k + (up ? "Up" : "Down"), { country: name, pct: pct(e.change_pct) });
    var tag = e.label === "reported, not observed" ? txt("tagReported") : txt("tagObserved");
    return "<li><a class=\"evl-t\" href=\"./event.html?id=" + encodeURIComponent(e.id) + "\">" + esc(title) + "</a><span class=\"evl-d sm-num\">" + esc(day(e.date)) + "</span>" +
      "<span class=\"evl-s\"><span>" + esc(tag) + "</span><a href=\"./index.html?day=" + esc(e.date) + "\">" + esc(txt("mapLink")) + "</a></span></li>";
  }
  Promise.all([getJSON("copy.json"), getJSON("data/events_published.json").catch(function () { return null; }), getJSON("data/heatmap_daily.json").catch(function () { return null; }), window.Claims ? window.Claims.load() : null]).then(function (r) {
    var cp = r[0] || {};
    C = Object.assign({}, cp.eventsPage || {}, { navCountries: cp.eventPage.navCountries, navRoutes: cp.eventPage.navRoutes, navSources: cp.eventPage.navSources,
      navFindings: cp.eventPage.navFindings, navResearch: cp.eventPage.navResearch, navEvents: cp.eventPage.navEvents, navHow: cp.eventPage.navHow });
    ((r[2] && r[2].currencies) || []).forEach(function (c) { NAMES[c.ccy] = String(c.country || c.ccy).replace(/^the /i, "").replace(/^./, function (x) { return x.toUpperCase(); }); });
    var ev = (r[1] && r[1].events) || [];
    if (window.Claims && window.Claims.blocked("eventPage.landLine")) { ev = []; }
    app.innerHTML = '<div class="sm-wrap">' + nav() + '<div class="sm-hero"><h1>' + esc(txt("heading")) + '</h1><p class="sm-lead">' + esc(txt("lead")) + "</p></div>" +
      (ev.length ? '<ul class="evl">' + ev.map(row).join("") + "</ul>" : '<p class="sm-note">' + esc(txt("empty")) + "</p>") +
      "<footer><p>" + esc(txt("footer")) + "</p></footer></div>";
  }).catch(function () { app.innerHTML = '<div class="sm-wrap"><p class="sm-note">' + esc(txt("loadFailed") || "") + "</p></div>"; });
})();

#!/usr/bin/env python3
"""Design ratchet: a PR may not make a reader-facing page louder.

DESIGN.md and VISION.md say the pages keep one quiet register: sentence-case
labels, one or two weights, ink plus greys, accent colours only for data. No
script could enforce taste, but it can enforce "no more than before". This
counts four things per reader page and fails if any count goes UP against
tools/design_baseline.json:

  allcaps_copy   copy.json strings that are ALL CAPS (labels, statuses)
  css_uppercase  `text-transform:uppercase` in a page's own CSS
  heavy_weight   font-weight 800/900 in a page's own CSS
  off_palette    hex colours in a page's own CSS outside the allowed set

Counts going down is fine (and `--update` lowers the baseline). Stdlib only.

A second mode, --style, renders the seven reader pages (home, countries, sending money, sources, findings,
how it works, country) at 1300px and 390px and measures the page title, the text under it, the section
headings, the filter pills, the running-text link underline and the gap between the header and the title.
It fails if any page differs from the home page (css/site_page.css is where those values live).
--perturb adds a deliberate change first, to prove the check can fail.

A third mode, --overflow, loads fifteen pages at 390px and fails if anything is wider than the screen or scrolls
sideways (--perturb adds a 600px element first, to prove it can fail).

A fourth mode, --lines (SEB-301, 21 Oct), loads the nine pages that share css/site_page.css at 1300px and 390px and
fails if the last line of any heading or paragraph holds a single word, or if the home counters row wraps at 1300px
(--perturb narrows a heading and the counters first, to prove it can fail).

A sixth mode, --counts (SEB-310), loads the home page and fails when two counts of the same thing (countries priced this hour,\ncountries tracked) read different numbers. --perturb changes one first, to prove it can fail.\n\nUsage: python3 tools/check_design.py [--update] [--counts [--perturb]] [--style [--perturb]] [--overflow [--perturb]] [--lines [--perturb]]
"""
import glob
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE = os.path.join(HERE, "tools", "design_baseline.json")

# ink, greys, rules, white, the DESIGN.md data palette and its neutrals.
ALLOWED = {
    "#0B0B0B", "#000", "#000000", "#FFF", "#FFFFFF", "#333", "#333333", "#6B6B6B", "#7D7979", "#9A9A9A",
    "#D3D0CB", "#EDEDED", "#F0F0F0", "#F6F6F6", "#F5F5F5", "#FAFAFA", "#EEE", "#EEEEEE", "#DDD", "#DDDDDD",
    "#817FCC", "#3F3047", "#F0EBD8", "#201E1D",
}
HEX = re.compile(r"#[0-9A-Fa-f]{3}(?:[0-9A-Fa-f]{3})?\b")


def reader_pages():
    out = []
    for f in sorted(glob.glob(os.path.join(HERE, "*.html"))):
        out.append(f)
    return out


def own_css(src):
    return "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", src, re.S | re.I))


def count_allcaps(node):
    n = 0
    if isinstance(node, dict):
        for v in node.values():
            n += count_allcaps(v)
    elif isinstance(node, list):
        for v in node:
            n += count_allcaps(v)
    elif isinstance(node, str):
        letters = re.sub(r"[^A-Za-z]", "", re.sub(r"\{[^}]*\}|<[^>]*>", "", node))
        if len(letters) >= 4 and letters.isupper():
            n += 1
    return n


def measure():
    counts = {"copy.json": {"allcaps_copy": count_allcaps(json.load(open(os.path.join(HERE, "copy.json"))))}}
    for f in reader_pages():
        css = own_css(open(f, encoding="utf-8").read())
        bad = {h.upper() for h in HEX.findall(css) if h.upper() not in {a.upper() for a in ALLOWED}}
        counts[os.path.basename(f)] = {
            "css_uppercase": len(re.findall(r"text-transform\s*:\s*uppercase", css, re.I)),
            "heavy_weight": len(re.findall(r"font-weight\s*:\s*(?:800|900)\b", css)),
            "off_palette": len(bad),
        }
    return counts


STYLE_PAGES = ["index.html", "countries.html", "country.html?ccy=PHP", "sending-money.html?route=SGD-PHP&amount=5000",
               "sources.html", "findings.html", "how-it-works.html"]
STYLE_PROBE = r"""
(function () {
  var cs = function (e) { return getComputedStyle(e); };
  var h1 = document.querySelector('h1');
  var head = document.querySelector('.hp-head,.ci-head,.c-head,.sm-head,.s-head,.fp-head,.mwh');
  var lead = h1 && h1.nextElementSibling && h1.nextElementSibling.tagName === 'P' ? h1.nextElementSibling : null;   // a page with no text under its title has none to measure
  var h2 = document.querySelector('h2');
  var pill = [].filter.call(document.querySelectorAll('button.hp-btn,button.c-chip,button.ci-pill,button.sm-pill,button.pill'), function (x) { return x.getAttribute('aria-pressed') !== 'true' && !x.classList.contains('on'); })[0];
  var lk = [].filter.call(document.querySelectorAll('p a, li a'), function (x) { return !x.closest('header,nav,.hp-head,footer') && x.innerText.trim().length > 3; })[0];
  var o = {};
  o.title = h1 ? cs(h1).fontSize + ' ' + cs(h1).fontWeight : 'none';
  o.lead = lead ? cs(lead).fontSize + ' ' + cs(lead).color : 'none';
  o.h2 = h2 ? cs(h2).fontSize + ' ' + cs(h2).fontWeight : 'none';
  o.leadgap = h1 && lead ? Math.round(lead.getBoundingClientRect().top - h1.getBoundingClientRect().bottom) + 'px' : 'none';
  var first = document.querySelector('.cnav,.fnav') || h1;   // a page with a back link above its title keeps the 40px above that row
  o.gap = first && head ? Math.round(first.getBoundingClientRect().top - head.getBoundingClientRect().bottom) + 'px' : 'none';
  if (pill) { o.pill = [cs(pill).borderTopLeftRadius, cs(pill).minHeight, cs(pill).fontWeight, cs(pill).fontSize, cs(pill).borderTopWidth, cs(pill).borderTopColor].join(' '); }
  if (lk) { o.link = cs(lk).textDecorationLine + ' ' + cs(lk).textDecorationThickness + ' ' + cs(lk).textDecorationColor; }
  return JSON.stringify(o);
})()
"""


# The record chart (js/record_block.js, css/record_block.css) on the page that draws it: a missing style shows as a solid black area.
# Home stopped drawing it when the time control replaced it (SEB-384).
RECORD_PAGES = ["how-it-was-built.html"]
RECORD_PROBE = r"""
(function () {
  var a = document.querySelector('.hp-area'), l = document.querySelector('.hp-line'), x = document.querySelector('.hp-axis');
  if (!a || !l || !x) { return JSON.stringify({chart: 'missing'}); }
  var ca = getComputedStyle(a), cl = getComputedStyle(l), cx = getComputedStyle(x);
  return JSON.stringify({areaOpacity: ca.fillOpacity, lineFill: cl.fill, lineWidth: cl.strokeWidth, axis: cx.display});
})()
"""


def style_check(perturb=False):
    sys.path.insert(0, os.path.join(HERE, "tools"))
    from gate_common import open_page, serve  # noqa: E402
    base, stop = serve(HERE)
    seen = {}
    try:
        with open_page(settle=4.0) as page:
            page.visit("about:blank")
            for width, height, mobile in ((1300, 900, False), (390, 844, True)):
                page.set_viewport(width, height, mobile=mobile)
                for name in STYLE_PAGES:
                    page.visit(base + "/" + name)
                    if perturb and name.startswith("sources"):
                        page.eval_js("document.querySelector('h1').style.setProperty('font-size','30px','important');'ok'")
                    seen[(width, name)] = json.loads(page.eval_js(STYLE_PROBE) or "{}")
                for name in RECORD_PAGES:
                    page.visit(base + "/" + name)
                    if perturb and name == "how-it-was-built.html":
                        page.eval_js("document.querySelector('.hp-area').style.setProperty('fill-opacity','1');'ok'")
                    got = json.loads(page.eval_js(RECORD_PROBE) or "{}")
                    for _ in range(10):           # the chart draws after its data loads; a slow runner needs a few more seconds
                        if got.get("chart") != "missing":
                            break
                        time.sleep(1.5)
                        got = json.loads(page.eval_js(RECORD_PROBE) or "{}")
                    seen[(width, "record:" + name)] = got
            page.clear_viewport()
    finally:
        stop()
    bad = []
    want = {"areaOpacity": "0.14", "lineFill": "none", "lineWidth": "1.5px", "axis": "flex"}
    for (width, name), got in sorted(seen.items(), key=lambda kv: str(kv[0])):
        if name.startswith("record:") and got != want:
            bad.append("%dpx %s: the record chart reads %r, expected %r" % (width, name[7:], got, want))
    # title, lead and h2 weight/size, and the gap between a title and its text, are home's own since the 21 Oct fast lane
    # (SEB-301): weight 500, lead/body/note at 17px, 12px title-to-text. Every other page keeps the earlier shared values.
    # The header-to-title gap is 40px on every page. Home's headline block fills the first screen (DESIGN.md, 1 Nov), so home
    # is not the standard for that gap: every other page is checked against 40px instead.
    HOME_ONLY = {"title", "lead", "h2", "leadgap", "gap"}
    for width in (1300, 390):
        for name in STYLE_PAGES[1:]:
            g = seen[(width, name)].get("gap")
            if g not in (None, "none", "40px"):
                bad.append("%dpx %s: the gap under the header is %r, the rule is '40px'" % (width, name.split("?")[0], g))
    for width in (1300, 390):
        std = seen[(width, STYLE_PAGES[0])]
        for name in STYLE_PAGES[1:]:
            got = seen[(width, name)]
            for k, v in std.items():
                if k in HOME_ONLY:
                    continue
                if k in ('lead', 'leadgap') and got.get(k) == 'none':
                    continue    # a page may have no text under its title (how it works, after its subtitle was removed)
                if k in got and got[k] != v:
                    bad.append("%dpx %s: %s is %r, home has %r" % (width, name.split("?")[0], k, got[k], v))
    if bad:
        print("style check FAILED (a page differs from the home page):")
        for line in bad:
            print("  " + line)
        return 1
    print("style check ok (%d pages at 1300px and 390px match the home page)" % len(STYLE_PAGES))
    return 0


OVERFLOW_PAGES = ["index.html", "countries.html", "country.html?ccy=PHP", "country.html?ccy=TRY", "sending-money.html?route=SGD-PHP&amount=5000",
                  "sending-money.html?route=USD-MXN&amount=50000", "sources.html", "findings.html", "finding.html?id=price_changes",
                  "finding.html?id=weekend_penalty", "finding.html?id=volume_crossover", "finding.html?id=sgd_php_never_cheapest",
                  "finding.html?id=exchange_vs_p2p", "how-it-works.html", "how-it-was-built.html"]
# At 390px nothing may be wider than the screen and nothing may scroll sideways: the page itself, any element that
# sticks out past the right edge (unless a clipping ancestor already holds it inside the screen), and any element that
# has its own sideways scroll with content wider than its box.
OVERFLOW_PROBE = r"""
(function(){var W=window.innerWidth,out=[];function clipped(e){for(var p=e.parentElement;p&&p!==document.body;p=p.parentElement){var o=getComputedStyle(p);if(/(hidden|clip|auto|scroll)/.test(o.overflowX)&&p.clientWidth<=W+1)return true}return false}
function d(e){return e.tagName.toLowerCase()+(e.id?'#'+e.id:'')+(e.className&&e.className.baseVal===undefined?'.'+String(e.className).trim().split(/\s+/).slice(0,2).join('.'):'')}
if(document.documentElement.scrollWidth>W)out.push('PAGE scrollWidth '+document.documentElement.scrollWidth);
[].forEach.call(document.querySelectorAll('body *'),function(e){var s=getComputedStyle(e);if(s.display==='none'||s.visibility==='hidden')return;var r=e.getBoundingClientRect();if(r.width===0)return;
 if(/(auto|scroll)/.test(s.overflowX)&&e.scrollWidth>e.clientWidth+1)out.push('SCROLLS '+d(e)+' '+e.scrollWidth+'>'+e.clientWidth);
 else if(r.right>W+1&&!clipped(e)&&s.position!=='fixed')out.push('WIDE '+d(e)+' right='+Math.round(r.right))});
return out.slice(0,12).join(' | ')})()
"""


def overflow_check(perturb=False):
    sys.path.insert(0, os.path.join(HERE, "tools"))
    from gate_common import open_page, serve  # noqa: E402
    base, stop = serve(HERE)
    bad = []
    try:
        with open_page(settle=4.0) as page:
            page.visit("about:blank")
            page.set_viewport(390, 844, mobile=True)
            for name in OVERFLOW_PAGES:
                page.visit(base + "/" + name)
                if perturb and name == "index.html":
                    page.eval_js("var d=document.createElement('div');d.style.cssText='width:600px;height:10px';document.body.appendChild(d);'ok'")
                found = page.eval_js(OVERFLOW_PROBE)
                if found:
                    bad.append("%s: %s" % (name, found))
            page.clear_viewport()
    finally:
        stop()
    if bad:
        print("overflow check FAILED (something is wider than the screen at 390px):")
        for line in bad:
            print("  " + line)
        return 1
    print("overflow check ok (%d pages at 390px: nothing wider than the screen, nothing scrolls sideways)" % len(OVERFLOW_PAGES))
    return 0


LINES_PAGES = ["index.html", "countries.html", "country.html?ccy=PHP", "sending-money.html?route=SGD-PHP&amount=5000",
               "sources.html", "findings.html", "finding.html?id=price_changes", "how-it-works.html", "how-it-was-built.html"]
# The words of each heading and paragraph, grouped into lines by where the browser put them. A last line of one word is a
# stray word; one that is only a symbol or a number in brackets ("(5)", "→") counts too, as the reader sees it the same way.
LINES_PROBE = r"""
(function(){
 function lines(el){var w=[],tw=document.createTreeWalker(el,NodeFilter.SHOW_TEXT,null),n;
  while(n=tw.nextNode()){var s=n.nodeValue,re=/\S+/g,m;while(m=re.exec(s)){var r=document.createRange();r.setStart(n,m.index);r.setEnd(n,m.index+m[0].length);
   var b=r.getClientRects()[0];if(b&&b.width>0)w.push({t:m[0],y:Math.round(b.top)})}}
  var L=[];w.forEach(function(x){var l=L[L.length-1];if(!l||Math.abs(l.y-x.y)>4)L.push({y:x.y,ws:[x.t]});else l.ws.push(x.t)});return L}
 var bad=[];
 document.querySelectorAll('h1,h2,h3,p').forEach(function(e){
  if(e.closest('header,footer,.site-head,.site-footer,table,svg,button,nav'))return;
  var s=getComputedStyle(e);if(s.display==='none'||s.visibility==='hidden'||e.getBoundingClientRect().height===0)return;
  var L=lines(e);if(L.length>1&&L[L.length-1].ws.length===1)bad.push(e.tagName.toLowerCase()+' "'+e.textContent.trim().slice(0,50)+'" ends on "'+L[L.length-1].ws[0]+'"')});
 var c=document.querySelector('#hero .counts'),wraps=false;
 if(c){var tops={};[].forEach.call(c.children,function(k){var r=k.getBoundingClientRect();if(r.height)tops[Math.round(r.top)]=1});wraps=Object.keys(tops).length>1}
 return JSON.stringify({bad:bad.slice(0,8),countsWrap:wraps});
})()
"""


def lines_check(perturb=False):
    sys.path.insert(0, os.path.join(HERE, "tools"))
    from gate_common import open_page, serve  # noqa: E402
    base, stop = serve(HERE)
    bad = []
    try:
        with open_page(settle=4.0) as page:
            page.visit("about:blank")
            for width, height, mobile in ((1300, 900, False), (390, 844, True)):
                for name in LINES_PAGES:
                    page.set_viewport(width, height, mobile=mobile)
                    page.visit(base + "/" + name)
                    if perturb and name == "index.html" and width == 1300:
                        page.eval_js("var h=document.querySelector('main h2, .wrap h2');h.style.setProperty('max-width','260px','important');"
                                     "h.style.setProperty('text-wrap','wrap','important');h.textContent='Exchangesandapps Transfersandrates';"
                                     "document.querySelector('#hero .counts').style.setProperty('flex-wrap','wrap','important');"
                                     "document.querySelector('#hero .counts').style.setProperty('max-width','300px','important');'ok'")
                    got = json.loads(page.eval_js(LINES_PROBE) or "{}")
                    for line in got.get("bad", []):
                        bad.append("%dpx %s: %s" % (width, name.split("?")[0], line))
                    if width == 1300 and name == "index.html" and got.get("countsWrap"):
                        bad.append("1300px index: the counters row wraps onto a second line")
            page.clear_viewport()
    finally:
        stop()
    if bad:
        print("line check FAILED (a line ends with one word, or the home counters wrap at 1300px):")
        for line in bad:
            print("  " + line)
        return 1
    print("line check ok (%d pages at 1300px and 390px: no last line holds one word, the home counters fit on one line)" % len(LINES_PAGES))
    return 0

# Sixth mode, --counts (SEB-310, 21 Oct): two counts of the same thing on the home page must be the same number.
COUNT_GROUPS = {
    "countries priced this hour": [r"(\d[\d,]*) of them had a price", r"of (\d[\d,]*) countries we priced this hour", r"In \d[\d,]* of (\d[\d,]*) it is within 2%", r"official rate in \d[\d,]* of (\d[\d,]*) countries"],
    "countries tracked": [r"(\d[\d,]*) countries tracked", r"what a dollar costs in (\d[\d,]*) countries", r"price of a dollar in (\d[\d,]*) countries", r"Show all (\d[\d,]*) countries"],
}


def counts_check(perturb=False):
    sys.path.insert(0, os.path.join(HERE, "tools"))
    from gate_common import open_page, serve  # noqa: E402
    base, stop = serve(HERE)
    bad = []
    try:
        with open_page(settle=5.0) as page:
            page.visit("about:blank")
            page.set_viewport(1300, 900)
            page.visit(base + "/index.html")
            if perturb:
                page.eval_js("[].forEach.call(document.querySelectorAll('button'),function(b){b.textContent=b.textContent.replace(/Show all [0-9,]+ countries/,'Show all 7 countries')});'ok'")
            text = page.eval_js("document.body.innerText") or ""
            for thing, pats in COUNT_GROUPS.items():
                seen = {}
                for p in pats:
                    for m in re.finditer(p, text):
                        seen.setdefault(m.group(1), []).append(p)
                if len(seen) > 1:
                    bad.append("index.html: %s reads %s" % (thing, " and ".join(sorted(seen))))
                if not seen:
                    bad.append("index.html: no count found for %s (the check cannot see it)" % thing)
            page.clear_viewport()
    finally:
        stop()
    if bad:
        print("count check FAILED (two counts of the same thing differ on one page):")
        for line in bad:
            print("  " + line)
        return 1
    print("count check ok (home page: each count reads one number)")
    return 0


def main():
    if "--counts" in sys.argv:
        return counts_check("--perturb" in sys.argv)
    if "--lines" in sys.argv:
        return lines_check("--perturb" in sys.argv)
    if "--overflow" in sys.argv:
        return overflow_check("--perturb" in sys.argv)
    if "--style" in sys.argv:
        return style_check("--perturb" in sys.argv)
    now = measure()
    if "--update" in sys.argv:
        json.dump(now, open(BASELINE, "w"), indent=1, sort_keys=True)
        open(BASELINE, "a").write("\n")
        print("design baseline updated")
        return 0
    base = json.load(open(BASELINE)) if os.path.exists(BASELINE) else {}
    bad = []
    for page, metrics in now.items():
        for k, v in metrics.items():
            b = base.get(page, {}).get(k)
            if b is None:
                b = 0 if page not in base else v  # a brand-new page starts at zero
            if v > b:
                bad.append("%s: %s went from %d to %d" % (page, k, b, v))
    if bad:
        print("design check FAILED (the page got louder than the baseline):")
        for line in bad:
            print("  " + line)
        print("Fix the styling, or if a count is truly warranted, run --update in the same PR and say why.")
        return 1
    print("design check ok (%d pages, nothing louder than baseline)" % (len(now) - 1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

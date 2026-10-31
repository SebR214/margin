#!/usr/bin/env python3
"""Machine view (SEB-301, 21 Oct): a markdown twin of every page, and llms.txt. No model.

    python3 tools/emit_markdown.py            # once an hour: skips when the twins already carry this hour
    python3 tools/emit_markdown.py --force    # write them again
    python3 tools/emit_markdown.py --self-test

Each page is rendered the way a reader gets it (served from this checkout, in headless Chrome, so it reads copy.json and the
same data files), and what it shows is written out as markdown: headings, paragraphs, lists, and tables as markdown tables
(real tables, and rows the page lays out as a grid). Charts, pictures, buttons, the site header and footer are left out.
Every section ends with the full URL of each data file it came from: the files it links to, or else the files the page
loaded. So every number in index.md is the number index.html showed for the same hour, with the label the page gave it.

Written: index.md, countries.md, sending-money.md, sources.md, findings.md, how-it-works.md, how-it-was-built.md, machine-room.md,
country/{CCY}.md for every country page and finding/{id}.md for every finding, then llms.txt: the site's own title and
lead, each .md page, and each public data file (data/manifest_latest.json) with what it holds.
Loud failure: a page that renders nothing, or a twin with no data file URL, exits non-zero and writes nothing.
"""
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))
SITE = "https://margin.wiki"
PAGES = [("index.html", "index.md"), ("countries.html", "countries.md"), ("sending-money.html", "sending-money.md"),
         ("sources.html", "sources.md"), ("findings.html", "findings.md"), ("how-it-works.html", "how-it-works.md"),
         ("how-it-was-built.html", "how-it-was-built.md"), ("machine-room.html", "machine-room.md")]
NUM = re.compile(r"[−+-]?(?:S\$|US\$|\$)?\d[\d,]*(?:\.\d+)?(?:%|M|K)?")
MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# The data file(s) that actually back each heading-section, matched by a regex searched against the heading's own text
# (SEB-301, 21 Oct: position alone is not safe -- a band on countries.html, or a movers/findings section on home, does
# not render at all when it is empty that hour, shifting every position after it; sending-money.html's step-by-step and
# day-by-day sections were swapped under a positional scheme like that, found by review). "hero" is the h1 section,
# matched by position since it is always first. "patterns" are tried in a heading's own text, first match wins; a
# pattern of None always matches, so it works as a page's one default (every finding or source section is the same).
# A page not listed here (country/finding, one twin per id) is covered instead by the links and bare file names
# already on the page.
SECTION_FILES = {
    "index.md": {
        "hero": ["index_latest.json", "record_daily.json", "sources_daily.json"],
        "patterns": [
            (r"countries we priced this hour, a dollar costs within 2% of the official rate", ["heatmap_daily.json", "index_latest.json"]),
            (r"^Where the price moved most against the official rate this week$", ["movers_week.json"]),
            (r"^When sending money costs more$", ["findings.json"]),
            (r"^The record grew as new sources and routes came in$", ["record_daily.json", "record_milestones.json"]),
        ],
    },
    "countries.md": {
        "hero": ["index_latest.json"],
        "patterns": [
            (r"^More than 8% above the official rate", ["index_latest.json"]),
            (r"^2% to 8% above", ["index_latest.json"]),
            (r"^Within 2% of the official rate", ["index_latest.json"]),
            (r"^More than 2% below", ["index_latest.json"]),
            (r"countries had no price at", ["index_latest.json", "source_pairs.json"]),
        ],
    },
    "sending-money.md": {
        "hero": ["routes_table.json"],
        "patterns": [
            (r"^Stablecoin against the best app, day by day$", ["routes_table.json"]),
            (r"^Biggest moves this month$", ["routes_table.json"]),
        ],
    },
    "sources.md": {"hero": ["sources_daily.json"], "patterns": [(None, ["sources_daily.json"])]},
    "findings.md": {"hero": ["findings.json"],
                    "patterns": [(None, ["findings.json", "findings_first_published.json", "claims_status.json"])]},
    "how-it-works.md": {
        "hero": [],
        "patterns": [
            (r"^What we measure$", []), (r"^What the percentage means$", ["index_latest.json"]),
            (r"^Where the price comes from$", []), (r"^The cost of sending money$", ["routes_hourly.json"]),
            (r"^What our numbers leave out$", []), (r"^How to check any number$", ["sources_daily.json"]),
        ],
    },
    "machine-room.md": {
        "hero": ["machine_room.json"],
        "patterns": [
            (r"^Week by week$", ["machine_room.json", "aider_log.csv", "machine_room_prs.csv"]),
            (r"^What runs where$", ["machine_room.json", "machine_room_meters.json"]),
            (r"^Incidents$", ["machine_room.json"]),
        ],
    },
    "how-it-was-built.md": {
        "hero": [],
        "patterns": [
            (r"^Each agent has one job", []), (r"^What we.ve learned running", []),
            (r"^Collected fresh every hour$", ["manifest_latest.json"]),
            (r"^The record grew", ["record_daily.json", "record_milestones.json"]),
        ],
    },
}
# A real header for a table whose own page shows no visible column label, matched the same way as SECTION_FILES: by a
# regex against the text of the heading that opens the table's section (not position).
SECTION_HEADERS = {
    "index.md": [
        (r"countries we priced this hour", ["Country", "Against the official rate"]),
        (r"^Where the price moved most against the official rate this week$", ["Country", "What happened", "Change this week"]),
        (r"^When sending money costs more$", ["Finding", "What we found"]),
    ],
    "countries.md": [
        (r"^More than 8% above the official rate", ["Country", "People pay", "Official rate", "Against the official rate"]),
        (r"^2% to 8% above", ["Country", "People pay", "Official rate", "Against the official rate"]),
        (r"^Within 2% of the official rate", ["Country", "Against the official rate"]),
        (r"^More than 2% below", ["Country", "Against the official rate"]),
    ],
    "sources.md": [(None, ["Source", "Type", "Hours priced"])],
    "how-it-was-built.md": [(r"^Collected fresh every hour$", ["Time", "Check", "Detail"])],
}


def section_files_for(path, heading_text, is_hero):
    """The data file(s) for the section that `heading_text` opens, or None (then the caller falls back to explicit
    links). `is_hero` is True only for the very first heading of the page, matched by position since it is always
    first; every other heading is matched by searching SECTION_FILES[path]["patterns"] in order."""
    spec = SECTION_FILES.get(path)
    if not spec:
        return None
    if is_hero:
        return spec["hero"]
    for pattern, files in spec["patterns"]:
        if pattern is None or re.search(pattern, heading_text):
            return files
    return None


def header_for(path, heading_text):
    for pattern, header in SECTION_HEADERS.get(path, []):
        if pattern is None or re.search(pattern, heading_text):
            return header
    return None
TAP_SENTENCE = re.compile(r"(?:^|(?<=[.!?]\s))Tap\b[^.!?]*[.!?]")
# A sentence that explains the heatmap's squares and colours means nothing without the chart (SEB-301, 21 Oct)
CHART_SENTENCE = re.compile(r"(?:^|(?<=[.!?]\s))[^.!?]*\b(?:squares?|colou?rs?)\b[^.!?]*[.!?]", re.I)
# Buttons that only reveal more of the page (never ones that replay a chart or navigate away): clicked once before the
# markdown is read, so a twin never stops at the first 20 rows a reader would have to click through to see.
EXPAND_JS = r"""
(function(){[].forEach.call(document.querySelectorAll('button'),function(b){
 if(/^(show|see) (all|more|earlier|why)\b/i.test((b.textContent||'').trim()))b.click()})})()
"""


def to_md_href(url):
    """An internal page link rewritten to its markdown twin (SEB-301, 21 Oct): never .html."""
    c = re.match(r"^" + re.escape(SITE) + r"/country/([a-z]{3})/?$", url)        # a country's own page (SEB-426)
    if c:
        return "%s/country/%s.md" % (SITE, c.group(1).upper())
    m = re.match(r"^" + re.escape(SITE) + r"/([a-z-]+)\.html(?:\?(.*))?$", url)
    if not m:
        return url
    page, qs = m.group(1), m.group(2) or ""
    if page == "country" and re.match(r"^ccy=([A-Z]{3})$", qs):
        return "%s/country/%s.md" % (SITE, re.match(r"^ccy=([A-Z]{3})$", qs).group(1))
    if page == "finding" and re.match(r"^id=([a-z0-9_]+)$", qs):
        return "%s/finding/%s.md" % (SITE, re.match(r"^id=([a-z0-9_]+)$", qs).group(1))
    if not qs and (page + ".html", page + ".md") in PAGES:
        return "%s/%s.md" % (SITE, page)
    return url


def drop_tap_sentences(text):
    """Dropped from the markdown only (SEB-301, 21 Oct): the page itself is untouched. Never strips a whole block to empty
    just because every sentence happened to start with Tap -- that would be a different, louder bug."""
    out = TAP_SENTENCE.sub("", text)
    out = re.sub(r"[ \t]+", " ", out).strip()
    return out or text


def drop_chart_sentences(text):
    """Dropped from the markdown only (SEB-301, 21 Oct), the page is untouched. A paragraph that only explained the chart
    goes whole."""
    return re.sub(r"[ \t]+", " ", CHART_SENTENCE.sub("", text)).strip()


def numbers_not_on_page(md, page_text):
    """Every number in a twin must be one the page showed, in the same render (link targets and URLs aside)."""
    body = re.sub(r"<https?://[^>]+>|\]\([^)]+\)", "", md)
    shown = set(NUM.findall(page_text or ""))
    return [n for n in NUM.findall(body) if n not in shown]

# Runs in the rendered page. Returns {"md": ..., "data": [files the page loaded]}.
TO_MARKDOWN = r"""
(function(SITE){
 // Chart axes and colour keys mean nothing without the chart. A button is a control, unless it holds a row of data.
 var SKIP='header,footer,nav,script,style,noscript,template,svg,canvas,img,picture,video,input,select,textarea,form,label,summary,.site-head,.site-footer,.hp-head,.mv-switch,[aria-hidden="true"],[hidden],'+
  '[class*="axis"],[class*="key"],[class*="legend"],[class*="tick"],.rb-y,.rb-x';
 function vis(e){if(e.closest(SKIP))return false;
  var btn=e.closest('button');if(btn&&textLeaves(btn)<2)return false;
  var s=getComputedStyle(e);if(s.display==='none'||s.visibility==='hidden')return false;var r=e.getBoundingClientRect();return r.width>0&&r.height>0}
 function textLeaves(e){var n=0;(function w(x){var own=[].some.call(x.childNodes,function(c){return c.nodeType===3&&c.nodeValue.trim()});
  if(own){n++;return}[].forEach.call(x.children,function(k){if(!k.closest('[aria-hidden="true"],svg'))w(k)})})(e);return n}
 function clean(t){return (t||'').replace(/\s+/g,' ').replace(/(\s*·\s*)+/g,' · ').replace(/^\s*·\s*|\s*·\s*$/g,'').trim()}
 var ARROW=/^[→←↗↘›»·]+$/;
 var PAGE_LINK=/(^|\/)(country\.html\?ccy=|finding\.html\?id=|country\/[a-z]{3}\/)/;
 function abs(h){try{return new URL(h,location.href).href.replace(location.origin,SITE)}catch(e){return h}}
 function inline(e){ // text with links kept as markdown links
  var out='';e.childNodes.forEach(function(n){
   if(n.nodeType===3){out+=n.nodeValue;return}
   if(n.nodeType!==1||!vis(n))return;
   var t=n.tagName.toLowerCase();
   if(t==='br'){out+=' ';return}
   if(t==='a'&&n.getAttribute('href')&&!/^(#|javascript:)/.test(n.getAttribute('href'))){var tx=clean(inline(n));if(tx)out+='['+tx+']('+abs(n.getAttribute('href'))+')';return}
   var s=getComputedStyle(n),ps=getComputedStyle(e);var inner=inline(n);
   if(/^(inline-flex|inline-block)$/.test(s.display)||/flex|grid/.test(ps.display))out+=' · '+inner+' · ';   // items laid out side by side
   else out+=(s.display==='block'||s.display==='flex'||s.display==='grid'||s.display==='table-cell')?' '+inner+' ':inner});
  return out}
 // The text leaves of a row with where they sit. any=true also reads chart axis rows; raw=true does not ask vis().
 // A colour key is never read: it is not a column label.
 function cellBoxes(row,any,raw){
  var out=[];(function walk(e){if(e.closest('svg,canvas,[hidden],[class*="key"],[class*="legend"]'))return;
   var s=getComputedStyle(e);if(s.display==='none'||s.visibility==='hidden')return;
   var kids=[].filter.call(e.children,function(k){var r=k.getBoundingClientRect();return r.width>0&&r.height>0&&(any||raw||vis(k))});
   var hasText=[].some.call(e.childNodes,function(n){return n.nodeType===3&&clean(n.nodeValue)});
   if(!kids.length||hasText){var t=clean(inline(e)),r=e.getBoundingClientRect();
    if(e.tagName==='A'&&e.getAttribute('href')&&t)t='['+t+']('+abs(e.getAttribute('href'))+')';
    if(t&&!ARROW.test(t))out.push({t:t,l:r.left,r:r.right});return}
   kids.forEach(walk)})(row);return out}
 function cells(row){ // the visible text leaves of a grid row, in order
  var out=[];(function walk(e){var kids=[].filter.call(e.children,vis);
   var hasText=[].some.call(e.childNodes,function(n){return n.nodeType===3&&clean(n.nodeValue)});
   if(!kids.length||hasText||e.tagName==='A'&&kids.every(function(k){return getComputedStyle(k).display.indexOf('inline')===0})){var t=clean(inline(e));if(t&&!ARROW.test(t))out.push(t);return}
   kids.forEach(walk)})(row);return out}
 function esc(t){return t.replace(/\|/g,'\\|')}
 function table(rows,head){var n=Math.max.apply(null,rows.map(function(r){return r.length}).concat(head?[head.length]:[]));
  var keep=[];for(var i=0;i<n;i++)if(rows.some(function(r){return r[i]})||head&&head[i])keep.push(i);   // a column empty everywhere goes
  rows=rows.map(function(r){return keep.map(function(i){return r[i]||''})});if(head)head=keep.map(function(i){return head[i]||''});n=keep.length;
  function line(r){var c=r.slice();while(c.length<n)c.push('');return '| '+c.map(esc).join(' | ')+' |'}
  var h=head&&head.length===n?head:Array(n).fill('');return [line(h),'|'+Array(n).fill(' --- ').join('|')+'|'].concat(rows.map(line)).join('\n')}
 function gridRows(e){ // 3+ visible children with the same tag and class, each with 2+ cells: a table laid out as a grid
  var kids=[].filter.call(e.children,vis);if(kids.length<3)return null;
  var sig=function(k){return k.tagName+'.'+String(k.className).split(' ')[0]};var counts={};kids.forEach(function(k){counts[sig(k)]=(counts[sig(k)]||0)+1});
  var best=Object.keys(counts).sort(function(a,b){return counts[b]-counts[a]})[0];if(counts[best]<3||counts[best]<kids.length*0.6)return null;
  var same=kids.filter(function(k){return sig(k)===best});
  var BLOCKY='section,article,table,ul,ol,h1,h2,h3,h4';
  if(same.some(function(k){return k.matches(BLOCKY)||[].some.call(k.querySelectorAll(BLOCKY),vis)}))return null;   // a row never holds a heading, a list or a table
  var rows=same.map(cells);if(rows.filter(function(r){return r.length>=2}).length<3||rows.some(function(r){return r.length>12}))return null;
  // Column labels: the text that sits right above each column, in the rows before the first row (axis rows included).
  var widest=same[rows.reduce(function(b,r,i){return r.length>rows[b].length?i:b},0)],cols=cellBoxes(widest,false);
  var before=[];for(var p=same[0].previousElementSibling;p;p=p.previousElementSibling)before.unshift(p);
  var labels=cols.map(function(){return []});
  before.forEach(function(b){cellBoxes(b,true).forEach(function(x){var c=(x.l+x.r)/2;cols.forEach(function(col,i){if(c>=col.l-8&&c<=col.r+8)labels[i].push(x.t)})})});
  var head=labels.some(function(l){return l.length})?labels.map(function(l){return l.join(' ')}):null;
  // Each row's cells go into the column they sit under, so a row with an empty cell does not shift left.
  if(cols.length>=2)rows=same.map(function(row){var out=cols.map(function(){return []});
   cellBoxes(row,false).forEach(function(x){var c=(x.l+x.r)/2,best=0,d=1e9;
    cols.forEach(function(col,i){var dd=c<col.l?col.l-c:c>col.r?c-col.r:0;if(dd<d){d=dd;best=i}});out[best].push(x.t)});
   return out.map(function(o){return o.join(' ')})});
  // A row that is itself a link to a country or a finding links its first word cell to that page (SEB-301, 21 Oct)
  rows=rows.map(function(r,i){var a=same[i].closest('a[href]');if(!a||!PAGE_LINK.test(a.getAttribute('href')))return r;
   var j=r.findIndex(function(c){return /[A-Za-z]/.test(c||'')});if(j<0||r[j].indexOf('](')>=0)return r;
   r=r.slice();r[j]='['+r[j]+']('+abs(a.getAttribute('href'))+')';return r});
  return {rows:rows,same:same,headCells:head}}
 var blocks=[],seen=new Set();
 function push(kind,text){text=text.trim();if(text)blocks.push({kind:kind,text:text})}
 var BARE_FILE=/\b[\w-]+\.(?:csv|json)\b/g;
 function dataLinks(e){ // explicit data/ links, plus bare filenames the page prints as its own citation (country and finding pages)
  var out=[].map.call(e.querySelectorAll('a[href*="data/"]'),function(a){return abs(a.getAttribute('href')).split('#')[0]});
  var bare=e.textContent.match(BARE_FILE)||[];
  bare.forEach(function(f){out.push(abs('data/'+f))});
  return out.filter(function(u,i,a){return a.indexOf(u)===i})}
 function walk(e){
  if(!vis(e)||seen.has(e))return;seen.add(e);var t=e.tagName.toLowerCase();
  if(/^h[1-4]$/.test(t)){var ht=clean(inline(e)),ha=e.closest('a[href]');   // a heading inside a country or finding link links to it
   if(ha&&PAGE_LINK.test(ha.getAttribute('href'))&&ht&&ht.indexOf('](')<0)ht='['+ht+']('+abs(ha.getAttribute('href'))+')';
   push('h'+t[1],ht);return}
  if(t==='p'||t==='summary'||t==='blockquote'){push('p',clean(inline(e)));dataLinks(e).forEach(function(u){push('src',u)});return}
  if(t==='ul'||t==='ol'){var items=[].filter.call(e.children,vis).map(function(li,i){return (t==='ol'?(i+1)+'. ':'- ')+clean(inline(li))}).filter(function(x){return x.length>2});push('list',items.join('\n'));dataLinks(e).forEach(function(u){push('src',u)});return}
  if(t==='table'){var trs=[].filter.call(e.querySelectorAll('tr'),vis).map(function(tr){   // an empty cell keeps its column
    return [].filter.call(tr.children,function(c){return getComputedStyle(c).display!=='none'}).map(function(c){return clean(inline(c))})});
   var head=e.querySelector('thead tr')?trs.shift():null;if(trs.length)push('table',table(trs,head));dataLinks(e).forEach(function(u){push('src',u)});return}
  var g=gridRows(e);
  // Headings and notes beside the rows stay in order. A row of short labels above the rows (dates on an axis) is not text.
  if(g){var done=false;[].filter.call(e.children,vis).forEach(function(k){
    if(g.same.indexOf(k)>=0){if(!done){push('table',table(g.rows.filter(function(r){return r.length}),g.headCells));done=true}seen.add(k);return}
    var above=g.same[0].compareDocumentPosition(k)&Node.DOCUMENT_POSITION_PRECEDING,b=cellBoxes(k,true);
    if(above&&!k.matches('h1,h2,h3,h4')&&b.length>=2&&b.every(function(x){return x.t.split(' ').length<=3}))return;
    walk(k)});
   dataLinks(e).forEach(function(u){push('src',u)});return}
  var kids=[].filter.call(e.children,vis);
  var ownText=[].some.call(e.childNodes,function(n){return n.nodeType===3&&clean(n.nodeValue)});
  if(!kids.length||ownText){push('p',clean(inline(e)));dataLinks(e).forEach(function(u){push('src',u)});return}
  kids.forEach(walk)}
 walk(document.body);
 var first=blocks.findIndex(function(b){return b.kind==='h1'});if(first>0)blocks=blocks.slice(first);   // the page starts at its title
 var loaded=performance.getEntriesByType('resource').map(function(r){return r.name}).filter(function(u){return /\/data\/[^?#]+\.(json|csv)/.test(u)})
  .map(function(u){return abs(u.split('?')[0])}).filter(function(u,i,a){return a.indexOf(u)===i});
 return JSON.stringify({blocks:blocks,data:loaded,text:document.body.innerText});
})
"""


def with_header(table_text, header):
    """Give a table a real header (SEB-301, 21 Oct): curated for a table whose page shows no column label, or only a
    partial one (an axis label for one column, nothing for the rest). Only when the column count matches -- never
    guesses a header onto a shape it was not written for."""
    lines = table_text.split("\n")
    if len(lines) < 2:
        return table_text
    cols = lines[0].count("|") - 1
    if cols != len(header):
        return table_text
    lines[0] = "| " + " | ".join(header) + " |"
    return "\n".join(lines)


def to_md(blocks, path, hour_str):
    """Blocks from the page -> markdown. A section runs from one heading to the next; it ends with the data file(s) that
    actually back it (SECTION_FILES, matched by the heading's own text -- SEB-301, 21 Oct: position is not safe, since a
    band or a movers/findings section does not render at all when it is empty that hour, shifting every later section)
    or, failing that, the files it linked itself -- never every file the whole page loaded (that was every section
    listing all 8). A country or finding page is not in SECTION_FILES (one twin per id); its hero section falls back to
    its own single file, by id, if the page itself happened to link none -- a country with a held-back price shows no
    raw-file table to link."""
    out, srcs, body, section_idx, cur_heading = [], [], False, -1, ""
    m = re.match(r"^country/([A-Z]{3})\.md$", path) or re.match(r"^finding/([a-z0-9_]+)\.md$", path)
    hero_default = (["countries/%s.json" % m.group(1)] if path.startswith("country/")
                    else ["findings.json"] if m else None)

    def close():
        if not body:
            return
        mapped = section_files_for(path, cur_heading, section_idx == 0)
        urls = ["%s/data/%s" % (SITE, f) for f in mapped] if mapped is not None else list(dict.fromkeys(srcs))
        if not urls and section_idx == 0 and hero_default:
            urls = ["%s/data/%s" % (SITE, f) for f in hero_default]
        if urls:
            out.append("\n".join("<%s>" % u for u in urls))
    for b in blocks:
        k, t = b["kind"], b["text"]
        if k.startswith("h"):
            close()
            srcs, body, section_idx, cur_heading = [], False, section_idx + 1, t
            out.append("#" * int(k[1]) + " " + t)
            if section_idx == 0:
                out.append(hour_str)
        elif k == "src":
            srcs.append(t)
        elif k == "table":
            body = True
            header = header_for(path, cur_heading)
            out.append(with_header(t, header) if header else t)
        elif k in ("p", "list"):
            body = True
            out.append(drop_chart_sentences(drop_tap_sentences(t)))
        else:
            body = True
            out.append(t)
    close()
    text = "\n\n".join(x for x in out if x.strip())
    text = re.sub(r"\]\((https://margin\.wiki/[a-z-]+\.html(?:\?[^)]*)?)\)", lambda m: "](%s)" % to_md_href(m.group(1)), text)
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text.strip() + "\n"


def dedupe_lines(md):
    """A page that shows the same short line twice in a row (a mobile and a desktop copy of it) keeps one."""
    out = []
    for block in md.split("\n\n"):
        if not out or block != out[-1]:
            out.append(block)
    return "\n\n".join(out)


def tracked(prefix):
    out = subprocess.run(["git", "ls-files", prefix], cwd=HERE, capture_output=True, text=True).stdout.split()
    return out


def all_pages():
    pages = list(PAGES)
    for p in sorted(tracked("data/countries/")):
        ccy = os.path.basename(p)[:-5]
        if p.endswith(".json") and ccy.isalpha() and ccy.isupper():
            pages.append(("country.html?ccy=" + ccy, "country/%s.md" % ccy))
    for f in json.load(open(os.path.join(HERE, "data", "findings.json"))).get("findings", []):
        if f.get("id") and f.get("published") is True:      # the findings the site shows (js/finding_page.js filters the same way)
            pages.append(("finding.html?id=" + f["id"], "finding/%s.md" % f["id"]))
    return pages


def hour():
    return json.load(open(os.path.join(HERE, "data", "index_latest.json")))["computed_at"]


def hour_line(iso):
    """"Prices from the HH:MM UTC hour, D Mon." (SEB-301, 21 Oct): plain text under the title, not an HTML comment."""
    mo, d, hh, mm = int(iso[5:7]), int(iso[8:10]), int(iso[11:13]), int(iso[14:16])
    return "Prices from the %02d:%02d UTC hour, %d %s." % (hh, mm, d, MON[mo - 1])


# the parts of a country page its own HTML carries before any script runs (SEB-426): what the page showed this hour
FRAGMENTS_JS = """(function(){var g=function(i){var e=document.getElementById(i);return e?e.innerHTML:''};
 return JSON.stringify({nav:g('nav'),cnav:g('cnav'),hero:g('hero'),depth:g('depth'),chart:g('chart'),src:g('src')})})()"""


def render(pages, settle=2.5):
    from gate_common import open_page, serve
    base, stop = serve(HERE)
    out = {}
    frags = {}
    try:
        with open_page(settle=settle) as page:
            page.visit("about:blank")
            page.set_viewport(1300, 900)
            for url, path in pages:
                page.visit(base + "/" + url + ("&" if "?" in url else "?") + "noredirect=1" if path.startswith("country/") else base + "/" + url)
                got = None
                for _ in range(8):                   # a page fills in after its data loads; wait for its first heading
                    got = json.loads(page.eval_js(TO_MARKDOWN + "(%s)" % json.dumps(SITE)) or "{}")
                    if any(b["kind"] == "h1" for b in got.get("blocks", [])):
                        break
                    time.sleep(1.0)
                if path.startswith("country/"):          # the same render also gives the country page its static HTML (SEB-426)
                    frags[path] = json.loads(page.eval_js(FRAGMENTS_JS) or "{}")
                page.eval_js(EXPAND_JS)                # a reader page shows the first 20 and a "show all" button; the twin shows everything
                time.sleep(0.6)
                got = json.loads(page.eval_js(TO_MARKDOWN + "(%s)" % json.dumps(SITE)) or "{}")
                out[path] = got
            page.clear_viewport()
    finally:
        stop()
    render.fragments = frags
    return out


def llms_txt(twins):
    """llms.txt: the site's own title and lead (from index.md), each .md page with its title, each public data file with what it holds."""
    idx = twins["index.md"].split("\n\n")
    title = next(b[2:] for b in idx if b.startswith("# "))
    lead = next(b for b in idx[idx.index("# " + title) + 1:]
                if b and not b.startswith(("#", "<", "|", "-", "[", "Prices from the ")))
    lines = ["# margin.wiki", "", "> " + title + ". " + lead, ""]
    for path, md in twins.items():
        h1 = next((l[2:] for l in md.split("\n") if l.startswith("# ")), path)
        lines.append("- [%s](%s/%s)" % (h1, SITE, path))
    lines.append("")
    man = json.load(open(os.path.join(HERE, "data", "manifest_latest.json")))
    for f in man.get("files", []):
        bits = [f.get("kind", "").upper()]
        if f.get("rows") is not None:
            bits.append("%s rows" % format(f["rows"], ","))
        if f.get("columns"):
            bits.append("columns " + ", ".join(f["columns"]))
        dr = f.get("date_range") or {}
        if dr.get("from") and dr.get("to"):
            bits.append("%s to %s" % (dr["from"][:10], dr["to"][:10]))
        lines.append("- [%s](%s/%s): %s" % (f["path"], SITE, f["path"], "; ".join(b for b in bits if b)))
    return "\n".join(lines) + "\n"


def build(force=False):
    # SEB-427: the machine room's numbers are worked out first, so the page it renders is this hour's
    import emit_machine_room
    emit_machine_room.build()
    h = hour()
    line = hour_line(h)
    if not force and os.path.exists(os.path.join(HERE, "index.md")) and line in open(os.path.join(HERE, "index.md")).read(300):
        print("machine view: the twins already carry the %s hour, nothing to do" % h)
        return 0
    pages = all_pages()
    got = render(pages)
    twins, bad = {}, []
    for url, path in pages:
        g = got.get(path) or {}
        blocks = g.get("blocks") or []
        if not any(b["kind"] == "h1" for b in blocks):
            bad.append("%s rendered no title" % url)
            continue
        md = dedupe_lines(to_md(blocks, path, line))
        if SITE + "/data/" not in md:
            bad.append("%s names no data file" % url)
            continue
        miss = numbers_not_on_page(md.replace(line, ""), g.get("text"))   # the hour line is ours, not a claim the page made
        if miss:
            bad.append("%s: numbers in the twin that the page did not show: %s" % (url, ", ".join(miss[:5])))
            continue
        twins[path] = md
    if bad:
        print("machine view FAILED, nothing written:\n  " + "\n  ".join(bad), file=sys.stderr)
        return 1
    for path, md in twins.items():
        full = os.path.join(HERE, path)
        os.makedirs(os.path.dirname(full) or HERE, exist_ok=True)
        open(full, "w").write(md)
    open(os.path.join(HERE, "llms.txt"), "w").write(llms_txt(twins))
    # SEB-426: each country's own page, written from the same render as its .md copy
    import emit_country_pages
    emit_country_pages.write_all({p: f for p, f in render.fragments.items() if p in twins}, h)
    # SEB-425: sitemap.xml and robots.txt from the same page list, lastmod = this build's hour (tools/emit_site_files.py)
    import emit_site_files
    emit_site_files.write_files(h)
    print("machine view: %d twins and llms.txt for the %s hour" % (len(twins), h))
    return 0


def self_test():
    line = "Prices from the 08:00 UTC hour, 21 Oct."
    blocks = [{"kind": "h1", "text": "Title"}, {"kind": "p", "text": "Lead 1.2%"}, {"kind": "h2", "text": "A section"},
              {"kind": "table", "text": "| a | b |\n| --- | --- |\n| 1 | 2 |"}, {"kind": "src", "text": SITE + "/data/x.json"},
              {"kind": "h2", "text": "No links"}, {"kind": "p", "text": "Text"}]
    md = to_md(blocks, "nowhere.md", line)   # not in SECTION_FILES: falls back to the explicit src links, never "all loaded"
    assert md.startswith("# Title\n\n" + line + "\n\nLead 1.2%\n\n## A section"), md
    assert "| 1 | 2 |\n\n<https://margin.wiki/data/x.json>\n\n## No links\n\nText\n" in md, md
    assert to_md([{"kind": "h1", "text": "T"}, {"kind": "h2", "text": "Empty"}], "nowhere.md", line) == "# T\n\n" + line + "\n\n## Empty\n", \
        "a heading with nothing under it gets no URL line, and nothing from 'all 8 loaded'"
    # SECTION_FILES: each section gets only its own file(s), matched by its heading's own text, never the other sections'
    heat_h2 = "In 28 of 48 countries we priced this hour, a dollar costs within 2% of the official rate."
    md2 = to_md([{"kind": "h1", "text": "People do not always pay the official rate for a dollar"},
                {"kind": "h2", "text": heat_h2}, {"kind": "p", "text": "x"},
                {"kind": "h2", "text": "Where the price moved most against the official rate this week"}, {"kind": "p", "text": "y"}],
               "index.md", line)
    assert "<https://margin.wiki/data/heatmap_daily.json>" in md2.split("Where the price moved")[0]
    assert "heatmap_daily" not in md2.split("Where the price moved")[1] and "movers_week.json" in md2.split("Where the price moved")[1]
    # text matching survives a section missing that hour: skip "2% to 8% above" entirely, "Within 2%" still gets its own
    # file, not "2% to 8% above"'s -- the bug a positional scheme had, found by review (SEB-301, 21 Oct)
    missing_band = to_md([{"kind": "h1", "text": "In 28 of the 48 countries we priced this hour, a dollar costs within 2% of the official rate"},
                          {"kind": "h2", "text": "More than 8% above the official rate (2)"}, {"kind": "p", "text": "a"},
                          {"kind": "h2", "text": "Within 2% of the official rate (30)"}, {"kind": "p", "text": "b"},
                          {"kind": "h2", "text": "11 countries had no price at 08:00 UTC"}, {"kind": "p", "text": "c"}],
                         "countries.md", line)
    assert "index_latest.json" in missing_band.split("Within 2%")[1].split("11 countries")[0]
    assert "source_pairs.json" in missing_band.split("11 countries")[1]
    # the swap review found: step-by-step is the fee legs (routes_breakdown.json), day-by-day is the hour-by-hour chart
    # (routes_hourly.json) -- not the other way round, regardless of the order or count of headings before them
    swap = to_md([{"kind": "h1", "text": "Sending S$5,000 to the Philippines costs S$1.75 with Wise"},
                 {"kind": "h2", "text": "What each way costs this hour, at S$5,000"}, {"kind": "p", "text": "a"},
                 {"kind": "h3", "text": "The stablecoin's cost, step by step"}, {"kind": "p", "text": "b"},
                 {"kind": "h2", "text": "How much more the stablecoin cost, day by day"}, {"kind": "p", "text": "c"},
                 {"kind": "h2", "text": "The same 5,000, sent from other places"}, {"kind": "p", "text": "d"}],
                "sending-money.md", line)
    assert "routes_breakdown.json" in swap.split("step by step")[1].split("day by day")[0]
    assert "routes_hourly.json" in swap.split("day by day")[1].split("other places")[0]
    assert "routes_breakdown" not in swap.split("day by day")[1].split("other places")[0]
    # a table with no visible header gets the real one, matched by its section's heading text; a mismatched column count is left alone
    th = to_md([{"kind": "h1", "text": "People do not always pay the official rate for a dollar"},
               {"kind": "h2", "text": heat_h2}, {"kind": "table", "text": "|  |  |\n| --- | --- |\n| Chile | +1% |"}],
              "index.md", line)
    assert "| Country | Against the official rate |\n| --- | --- |\n| Chile | +1% |" in th, th
    # the movers and findings tables on home get real headers too
    mv = to_md([{"kind": "h1", "text": "T"}, {"kind": "h2", "text": "Where the price moved most against the official rate this week"},
               {"kind": "table", "text": "|  |  |  |\n| --- | --- | --- |\n| Chile | a | +1.0 points this week |"},
               {"kind": "h2", "text": "When sending money costs more"},
               {"kind": "table", "text": "|  |  |\n| --- | --- |\n| 01 | [Apps changed](https://margin.wiki/finding.html?id=price_changes) |"}],
              "index.md", line)
    assert "| Country | What happened | Change this week |" in mv and "| Finding | What we found |" in mv, mv
    assert "[Apps changed](https://margin.wiki/finding/price_changes.md)" in mv, "a finding row links to its .md page"
    assert with_header("|  |  |  |\n| --- | --- | --- |\n| a | b | c |", ["X", "Y"]) == "|  |  |  |\n| --- | --- | --- |\n| a | b | c |", \
        "the column count does not match: left alone"
    assert with_header("|  | today |\n| --- | --- |\n| a | b |", ["Country", "Change"]) == "| Country | Change |\n| --- | --- |\n| a | b |", \
        "a header the page half-filled (one axis label, the rest blank) is still replaced"
    # "Tap..." sentences are dropped from the markdown text only, the rest of the sentence stays
    assert drop_tap_sentences("Each row is a country. Tap a square for its day, or a name to open that country.") == "Each row is a country."
    assert drop_tap_sentences("Tap any day. The line is the typical cost.") == "The line is the typical cost."
    assert drop_tap_sentences("Tap.") == "Tap.", "never empties a block just because it was all Tap"
    # the heatmap's squares-and-colour sentence goes from the markdown only, whole paragraph and all
    assert drop_chart_sentences("Each row is a country, each square one day. The colour shows how much more than the official rate people paid.") == ""
    assert drop_chart_sentences("Each row is a country. The colour shows the gap.") == "Each row is a country."
    gone = to_md([{"kind": "h1", "text": "T"}, {"kind": "h2", "text": heat_h2},
                 {"kind": "p", "text": "Each row is a country, each square one day. The colour shows how much more than the official rate people paid."},
                 {"kind": "table", "text": "|  |  |\n| --- | --- |\n| Chile | +1% |"}], "index.md", line)
    assert "square" not in gone and "colour" not in gone and "| Chile | +1% |" in gone, gone
    # internal links go to the markdown twin, never the .html page
    assert to_md_href(SITE + "/how-it-was-built.html") == SITE + "/how-it-was-built.md"
    assert to_md_href(SITE + "/country.html?ccy=PHP") == SITE + "/country/PHP.md"
    assert to_md_href(SITE + "/finding.html?id=price_changes") == SITE + "/finding/price_changes.md"
    assert to_md_href(SITE + "/data/x.json") == SITE + "/data/x.json", "a non-page URL is left alone"
    linked = to_md([{"kind": "h1", "text": "T"}, {"kind": "p", "text": "See [this](%s/how-it-was-built.html)." % SITE}], "nowhere.md", line)
    assert "[this](%s/how-it-was-built.md)" % SITE in linked, linked
    assert hour_line("2026-10-21T08:00:00+00:00") == line
    assert dedupe_lines("a\n\nb\n\nb\n\nc") == "a\n\nb\n\nc"
    assert numbers_not_on_page("Paid 8.8% on [file](https://x/2026.csv) <https://margin.wiki/data/a1.json>", "paid 8.8% today") == []
    assert numbers_not_on_page("Paid 9.9% and S$17.02", "paid 8.8% and S$17.02") == ["9.9%"], "a number the page did not show fails"
    print("emit_markdown self-test: ok")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
        sys.exit(0)
    sys.exit(build("--force" in sys.argv))

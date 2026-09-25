#!/usr/bin/env python3
"""Overwrite each retired page with a redirect stub (SESSIONS.md Session 2).

These ten pages predate the current design system and are unreachable from
any current page's nav or body -- but an old bookmark, a search result, or a
link from outside this repo can still land someone on one. Rather than
delete them (a 404, no explanation) each becomes a small page that says
where its job went and sends a reader there.

The redirect target and reason live in copy.json's "redirects" block, not
hardcoded per page -- one source of truth, same as everything else this
project renders. `<meta http-equiv="refresh">` is a hardcoded URL (it can't
read JSON before the page has rendered anything), which is markup
infrastructure, not reader-facing prose -- the actual sentence a reader sees
is fetched, same as every other string on the site.

Idempotent: safe to re-run.

Stdlib only.
"""

import json
import os

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COPY = os.path.join(HERE, "copy.json")

TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>margin.wiki — this page moved</title>
<meta name="description" content="{reason} moved to {dest_label}."/>
<meta http-equiv="refresh" content="0; url={dest_href}"/>
<link rel="canonical" href="{dest_href}"/>
<style>
  body{{margin:0;font-family:Archivo,system-ui,'Helvetica Neue',sans-serif;color:#0B0B0B;background:#fff;
       display:flex;align-items:center;justify-content:center;min-height:100vh;padding:24px;box-sizing:border-box}}
  .card{{max-width:480px;text-align:center}}
  h1{{font-size:22px;font-weight:800;letter-spacing:-0.02em;margin:0 0 10px}}
  p{{font-size:15px;color:#6B6B6B;line-height:1.5;margin:0 0 18px}}
  a{{display:inline-block;font-size:15px;font-weight:700;color:#0B0B0B;text-decoration:none;
     border-bottom:2px solid #0B0B0B;padding-bottom:2px}}
</style>
</head>
<body>
  <div class="card">
    <h1 id="rHeading">&nbsp;</h1>
    <p id="rBody">&nbsp;</p>
    <a href="{dest_href}" id="rLink">Continue &rarr;</a>
  </div>
<script>
fetch('./copy.json', {{cache:'no-store'}}).then(function(r){{ return r.json(); }}).then(function(d){{
  var R = (d.redirects) || {{}};
  var page = (R.pages || {{}})['{page}'] || {{}};
  function T(s, vals){{
    var out = String(s||'');
    for (var k in vals) out = out.split('{{' + k + '}}').join(vals[k]);
    return out;
  }}
  document.getElementById('rHeading').textContent = R.heading || '';
  document.getElementById('rBody').textContent = T(R.bodyTemplate, {{ old: '{page}', reason: page.reason || '', destLabel: page.destLabel || '' }});
  document.getElementById('rLink').textContent = T(R.linkTemplate, {{ destLabel: page.destLabel || '' }});
}}).catch(function(){{
  document.getElementById('rBody').textContent = 'Continuing to {dest_href}.';
}});
</script>
</body>
</html>
"""


def main():
    with open(COPY) as f:
        redirects = json.load(f)["redirects"]
    for page, info in redirects["pages"].items():
        path = os.path.join(HERE, page)
        html = TEMPLATE.format(
            page=page, reason=info["reason"],
            dest_href=info["destHref"], dest_label=info["destLabel"],
        )
        with open(path, "w") as f:
            f.write(html)
        print(f"  wrote {page} -> {info['destHref']}")


if __name__ == "__main__":
    main()

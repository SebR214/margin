"""One public money-changer tracker, from a config block (SEB-422, lever 1, step 3). No model, no key.

A config is collectors/cash_configs/<tracker>.json:

    {"tracker": "dolarapi_ar_blue", "ccy": "ARS", "url": "https://dolarapi.com/v1/dolares/blue", "parser": "json",
     "buy_field": "compra", "sell_field": "venta", "updated_field": "fechaActualizacion", "select": {}, "min": 1, "max": 100000}
    {"tracker": "forex_pk_open_market", "ccy": "PKR", "url": "...", "parser": "regex",
     "regex": "US Dollar TT USD-TT ([0-9.]+) ([0-9.]+)", "min": 50, "max": 2000}

parser "json": the answer is an object, or a list from which `select` ({"fuente": "paralelo"}) picks the one entry; buy_field and
sell_field name the numbers (either may be absent: the tracker then gives one number, "promedio"-style, in sell_field). parser "regex":
the page text with tags removed is searched for `regex`, group 1 is the buy number and group 2 the sell number.

One row an hour per tracker in the daily table cash_rates (tools/daily_csv.py, margin-data once the raw tables have moved):
    ts_utc, tracker, ccy, buy, sell, mid, updated_by_source, source_ok, error
These are the prices a money changer reports, the cash dollar. A pull that fails, an answer with no number, or a number outside
[min, max] is a row with source_ok false and the reason. The number is stored as the tracker gave it. Nothing reads these rows yet.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tools"))
import daily_csv  # noqa: E402

CONFIG_DIR = os.path.join(HERE, "collectors", "cash_configs")
NAME = "cash_rates"
FIELDS = ["ts_utc", "tracker", "ccy", "buy", "sell", "mid", "updated_by_source", "source_ok", "error"]
UA = {"User-Agent": "Mozilla/5.0 (compatible; margin.wiki; +https://margin.wiki)"}
REQUIRED = ("tracker", "ccy", "url", "parser", "min", "max")


def load_all(d=CONFIG_DIR):
    out = []
    for n in sorted(os.listdir(d)):
        if n.endswith(".json"):
            cfg = json.load(open(os.path.join(d, n)))
            miss = [k for k in REQUIRED if k not in cfg]
            if miss or cfg["parser"] not in ("json", "regex"):
                raise SystemExit("%s: bad config (%s)" % (n, ", ".join(miss) or "parser"))
            out.append(cfg)
    return out


def num(x):
    try:
        v = float(str(x).replace(",", ""))
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def text_of(html):
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t).replace("&nbsp;", " "))


def parse(cfg, body):
    """(buy, sell, updated) from an answer body (str). Raises ValueError with the reason."""
    if cfg["parser"] == "regex":
        m = re.search(cfg["regex"], text_of(body))
        if not m:
            raise ValueError("pattern not found on the page")
        a, b = num(m.group(1)), num(m.group(2))
        return (b, a, "") if cfg.get("swap") else (a, b, "")      # swap: the page names the sell number first
    doc = json.loads(body)
    if isinstance(doc, list):
        sel = cfg.get("select") or {}
        hit = [d for d in doc if all(d.get(k) == v for k, v in sel.items())]
        if len(hit) != 1:
            raise ValueError("%d entries match %s" % (len(hit), sel))
        doc = hit[0]
    if not isinstance(doc, dict):
        raise ValueError("not an object")
    return num(doc.get(cfg.get("buy_field"))) if cfg.get("buy_field") else None, num(doc.get(cfg["sell_field"])), str(doc.get(cfg.get("updated_field")) or "")


def row(ts, cfg, body=None, error=None):
    r = [ts, cfg["tracker"], cfg["ccy"], "", "", "", "", False, ""]
    if body is None:
        r[8] = (error or "pull failed")[:120]
        return r
    try:
        buy, sell, upd = parse(cfg, body)
    except (ValueError, KeyError, TypeError) as e:
        r[8] = ("%s:%s" % (type(e).__name__, e))[:120]
        return r
    nums = [x for x in (buy, sell) if x]
    if not sell and not buy:
        r[8] = "no number in the answer"
        return r
    if any(not cfg["min"] <= x <= cfg["max"] for x in nums):
        r[8] = "guard: outside %s to %s" % (cfg["min"], cfg["max"])
        return r
    r[3], r[4] = buy or "", sell or ""
    r[5] = round(sum(nums) / len(nums), 6)
    r[6] = upd
    r[7] = True
    return r


def fetch(cfg):
    import urllib.request          # standard library only: the checks job installs no packages
    with urllib.request.urlopen(urllib.request.Request(cfg["url"], headers=UA), timeout=25) as r:
        return r.read().decode("utf-8", "replace")


def run_config_test(name, get=fetch):
    """What tests/agent_cash_<name>.py runs: one live pull parses, the number is in the config's range, and the row lands."""
    import datetime as dt
    import csv
    import tempfile
    cfg = [c for c in load_all() if c["tracker"] == name][0]
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    r = row(ts, cfg, get(cfg))
    assert r[7] is True, "%s: %s" % (name, r[8])
    with tempfile.TemporaryDirectory() as d:
        daily_csv.append(NAME, FIELDS, [r], data=d)
        got = list(daily_csv.iter_dicts(NAME, d))
        assert len(got) == 1 and got[0]["tracker"] == name and float(got[0]["mid"]) > 0, got
    return r


def new_test(name):
    return ('"""SEB-422: one live pull of the %s tracker parses, the number is in range, and the row lands."""\n'
            "import os\nimport sys\n\n"
            "sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))\n"
            "from collectors import template_tracker as tt  # noqa: E402\n\n"
            "r = tt.run_config_test(%r)\n"
            "assert r[7] is True, r\n"
            "print(%r, r)\n") % (name, name, name + ": ok")


def selftest():
    cj = {"tracker": "t", "ccy": "ARS", "url": "u", "parser": "json", "buy_field": "compra", "sell_field": "venta", "updated_field": "f",
          "select": {}, "min": 1, "max": 100000}
    r = row("t0", cj, json.dumps({"compra": 1545, "venta": 1565, "f": "2026-10-30"}))
    assert r[7] and r[3] == 1545.0 and r[4] == 1565.0 and r[5] == 1555.0 and r[6] == "2026-10-30", r
    cl = dict(cj, buy_field=None, sell_field="promedio", select={"fuente": "paralelo"})
    cl.pop("buy_field")
    r = row("t0", cl, json.dumps([{"fuente": "oficial", "promedio": 889}, {"fuente": "paralelo", "promedio": 993.6, "compra": None}]))
    assert r[7] and r[3] == "" and r[4] == 993.6 and r[5] == 993.6, r
    assert not row("t0", cl, json.dumps([{"fuente": "oficial", "promedio": 1}]))[7], "no entry matches"
    assert "guard" in row("t0", cj, json.dumps({"compra": 5e9, "venta": 5e9}))[8]
    assert "no number" in row("t0", cj, json.dumps({"compra": None, "venta": None}))[8]
    assert not row("t0", cj, "<html>")[7] and row("t0", cj, None, "HTTPError:500")[8] == "HTTPError:500"
    cr = {"tracker": "p", "ccy": "PKR", "url": "u", "parser": "regex", "regex": "US Dollar TT USD-TT ([0-9.]+) ([0-9.]+)", "min": 50, "max": 2000}
    page = "<html><script>x</script><table><tr><td>US Dollar&nbsp;TT</td><td>USD-TT</td><td>277.4</td><td>280.15</td></tr></table></html>"
    r = row("t0", cr, page)
    assert r[7] and r[3] == 277.4 and r[4] == 280.15 and r[5] == 278.775, r
    assert "pattern not found" in row("t0", cr, "<p>changed</p>")[8], "a changed page is a row, not a number"
    compile(new_test("x"), "t", "exec")
    print("template_tracker self-test: ok")
    return 0


if __name__ == "__main__":
    sys.exit(selftest() if "--self-test" in sys.argv else (print(__doc__) or 2))

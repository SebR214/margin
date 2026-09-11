#!/usr/bin/env python3
"""Read-only accessors over data/, shared by serve_api.py and serve_mcp.py.

Every function re-opens its source file(s) on every call. Nothing here is
cached in memory, so a request made minutes apart always reflects whatever
the collectors most recently wrote -- the same freshness guarantee the site
itself gets by reading data/ at render time.

Stdlib only.
"""

import csv
import json
import os
import re
import sqlite3
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
COUNTRIES_DIR = os.path.join(DATA, "countries")

# from -> to, in the exact four corridors this project collects.
CORRIDOR_FILES = {
    ("SGD", "PHP"): "providers.csv",
    ("USD", "MXN"): "providers_usdmxn.csv",
    ("AUD", "PHP"): "providers_audphp.csv",
    ("NZD", "PHP"): "providers_nzdphp.csv",
}

# The raw CSVs query(sql) reads directly, at whatever columns each already has.
QUERY_TABLES = [
    "basis_history", "p2p_basis", "fx_rates", "samples", "price_changes",
    "fee_checks", "withdrawal_fees", "stable_spread", "offramp_snapshots",
    "provider_quotes", "basis", "p2p_sides",
]

MAX_QUERY_ROWS = 500
_SELECT_ONLY = re.compile(r"^\s*select\s", re.IGNORECASE)


class ServeError(ValueError):
    """A request that cannot be answered -- bad input, not a server fault."""


def _normalize(name):
    name = name.strip().lower()
    if name.startswith("the "):
        name = name[4:]
    return name


def find_country(country_or_ccy):
    """Resolve a country name or currency code to its ccy, or None."""
    needle = _normalize(country_or_ccy)
    if not needle:
        return None
    names = sorted(n for n in os.listdir(COUNTRIES_DIR) if n.endswith(".json"))
    for name in names:
        if name[:-5].lower() == needle:
            return name[:-5]
    for name in names:
        with open(os.path.join(COUNTRIES_DIR, name)) as f:
            data = json.load(f)
        if _normalize(data.get("country", "")) == needle:
            return name[:-5]
    return None


def load_country(ccy):
    """Return the parsed data/countries/<CCY>.json, or None if it doesn't exist."""
    path = os.path.join(COUNTRIES_DIR, "%s.json" % ccy.upper())
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def load_index_latest():
    with open(os.path.join(DATA, "index_latest.json")) as f:
        return json.load(f)


def withheld_reason(ccy):
    """The plain-language reason ccy has no price this hour, or None if it has one."""
    for row in load_index_latest().get("withheld", []):
        if row["ccy"].upper() == ccy.upper():
            return row["reason"]
    return None


def dollar_cost(country):
    """Today's price to buy a dollar in a country, or its withheld reason."""
    if not country:
        raise ServeError("country parameter is required")
    ccy = find_country(country)
    if ccy is None:
        raise ServeError("no data collected for %s" % country)
    source = "data/countries/%s.json" % ccy
    reason = withheld_reason(ccy)
    data = load_country(ccy)
    if reason is not None:
        return {
            "ccy": ccy,
            "country": data["country"],
            "withheld": True,
            "reason": reason,
            "source": source,
        }
    return {
        "ccy": ccy,
        "country": data["country"],
        "buy_price": data.get("buy_price"),
        "fx_mid_per_usd": data.get("fx_mid_per_usd"),
        "denominator": data.get("denominator"),
        "dollar_cost_pct": data.get("index_pct"),
        "hour_utc": data.get("hour_utc"),
        "n_sources": data.get("n_sources"),
        "round_trip_pct": data.get("round_trip_pct"),
        "source": source,
    }


def series(country, days=None):
    """The day-by-day history for one country, straight from its own file."""
    if not country:
        raise ServeError("country parameter is required")
    ccy = find_country(country)
    if ccy is None:
        raise ServeError("no data collected for %s" % country)
    data = load_country(ccy)
    history = data.get("history", [])
    if days is not None:
        try:
            n = int(days)
        except (TypeError, ValueError):
            raise ServeError("days must be a whole number")
        history = history[-n:] if n > 0 else []
    return {
        "ccy": ccy,
        "country": data["country"],
        "history": history,
        "source": "data/countries/%s.json" % ccy,
    }


def corridor_file(from_ccy, to_ccy):
    """Path to the providers CSV for a from->to pair, or None if uncollected."""
    name = CORRIDOR_FILES.get((from_ccy.upper(), to_ccy.upper()))
    return os.path.join(DATA, name) if name else None


def read_csv_rows(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def compare_routes(from_ccy, to_ccy, amount):
    """The latest ranked rows for a corridor this project actually measures."""
    if not from_ccy or not to_ccy:
        raise ServeError("from and to parameters are required")
    path = corridor_file(from_ccy, to_ccy)
    rows = read_csv_rows(path) if path else []
    if not rows:
        raise ServeError("no route data collected for this corridor")
    latest_ts = max(r["ts_utc"] for r in rows)
    latest = [r for r in rows if r["ts_utc"] == latest_ts]
    tiers = sorted({float(r["notional_src"]) for r in latest})
    try:
        target = float(amount) if amount is not None else tiers[-1]
    except (TypeError, ValueError):
        raise ServeError("amount must be a number")
    chosen_tier = min(tiers, key=lambda t: abs(t - target))
    chosen = sorted(
        (r for r in latest if float(r["notional_src"]) == chosen_tier),
        key=lambda r: int(r["rank"]),
    )
    return {
        "from": from_ccy.upper(),
        "to": to_ccy.upper(),
        "requested_amount": amount,
        "matched_amount": chosen_tier,
        "ts_utc": latest_ts,
        "routes": chosen,
        "source": "data/%s" % os.path.basename(path),
    }


def csv_table(conn, path):
    """Load one CSV into an in-memory sqlite table named after its stem."""
    stem = os.path.splitext(os.path.basename(path))[0]
    rows = read_csv_rows(path)
    if not rows:
        return stem
    cols = list(rows[0].keys())
    conn.execute(
        'CREATE TABLE "%s" (%s)' % (stem, ", ".join('"%s" TEXT' % c for c in cols))
    )
    conn.executemany(
        'INSERT INTO "%s" VALUES (%s)' % (stem, ", ".join("?" for _ in cols)),
        [[r[c] for c in cols] for r in rows],
    )
    return stem


def _build_query_db():
    conn = sqlite3.connect(":memory:")
    for name in QUERY_TABLES:
        csv_table(conn, os.path.join(DATA, name + ".csv"))
    return conn


def run_query(sql):
    """Run one read-only SELECT over the raw CSVs, capped at MAX_QUERY_ROWS."""
    if not sql or not sql.strip():
        raise ServeError("sql parameter is required")
    body = sql.strip()
    if body.endswith(";"):
        body = body[:-1]
    if ";" in body:
        raise ServeError("only one statement is allowed")
    if not _SELECT_ONLY.match(body):
        raise ServeError("only SELECT statements are allowed")
    conn = _build_query_db()
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(body)
        rows = cur.fetchmany(MAX_QUERY_ROWS + 1)
    except sqlite3.Error as e:
        raise ServeError(str(e))
    finally:
        conn.close()
    truncated = len(rows) > MAX_QUERY_ROWS
    rows = rows[:MAX_QUERY_ROWS]
    return {
        "rows": [dict(r) for r in rows],
        "row_count": len(rows),
        "truncated": truncated,
        "source": ["data/%s.csv" % t for t in QUERY_TABLES],
    }


def request_series(description):
    """Open a commission issue asking for a series this dataset doesn't have.

    Probing and verifying the source is out of scope here -- see the
    Commission item. This only files the request.
    """
    if not description or not description.strip():
        raise ServeError("description parameter is required")
    try:
        out = subprocess.run(
            [
                "gh", "issue", "create",
                "--repo", "SebR214/margin",
                "--title", "Series request via request_series",
                "--body", description,
                "--label", "commission",
            ],
            capture_output=True, text=True, check=True, timeout=30,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as e:
        raise ServeError("could not open a commission issue: %s" % e)
    url = out.stdout.strip().splitlines()[-1] if out.stdout.strip() else ""
    number = url.rsplit("/", 1)[-1] if url else None
    return {"number": number, "url": url}

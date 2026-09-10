#!/usr/bin/env python3
"""Every way to send money, ranked. Builds data/providers_latest.json.

THE SOURCE PRECEDENCE RULE, and the only interesting decision in this file:

  1. A provider's OWN published quote, where it publishes one.
  2. The Wise comparison API, for every provider that does not.

A provider quoting itself is the more direct evidence, so it wins. Where both
exist, the comparison figure is still carried on the row as `also_quoted_pct`
so nothing is discarded -- but the headline is the provider's own number. Every
row says which source it came from. This is a precedence rule, not a judgement
about any source being wrong.

The crypto route is ranked among them as simply another way to send money,
using the same measure: how far below the mid-market rate the recipient lands.

Derived, never authoritative. Stdlib only. No wall clock in the output.

Usage: python3 tools/emit_providers.py
"""

import csv
import datetime as dt
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data")
QUOTES = os.path.join(DATA, "provider_quotes.csv")
SAMPLES = os.path.join(DATA, "samples.csv")
OUT = os.path.join(DATA, "providers_latest.json")

# Each corridor's comparison panel lives in its own file, because providers.csv
# has no corridor column and a frozen schema.
PANELS = {
    "SGD->PHP": "providers.csv",
    "USD->MXN": "providers_usdmxn.csv",
    "AUD->PHP": "providers_audphp.csv",
    "NZD->PHP": "providers_nzdphp.csv",
}

ROUTE_WORDS = {
    "SGD->PHP": "Singapore to the Philippines",
    "AUD->PHP": "Australia to the Philippines",
    "NZD->PHP": "New Zealand to the Philippines",
    "USD->MXN": "the United States to Mexico",
}
SYMBOL = {"SGD": "S$", "AUD": "A$", "NZD": "NZ$", "USD": "US$"}


def rows(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def num(row, key):
    raw = (row.get(key) or "").strip()
    if not raw:
        return None
    try:
        v = float(raw)
    except ValueError:
        return None
    return v if v == v else None


def flag(row, key):
    return (row.get(key) or "").strip().lower() == "true"


def parse_ts(s):
    try:
        t = dt.datetime.fromisoformat((s or "").strip())
    except ValueError:
        return None
    return t.replace(tzinfo=dt.timezone.utc) if t.tzinfo is None else t


def newest_hour(rs, field="ts_utc"):
    stamps = [t for t in (parse_ts(r.get(field)) for r in rs) if t]
    if not stamps:
        return None
    return max(stamps).replace(minute=0, second=0, microsecond=0)


def in_hour(rs, hour, field="ts_utc"):
    out = []
    for r in rs:
        t = parse_ts(r.get(field))
        if t and t.replace(minute=0, second=0, microsecond=0) == hour:
            out.append(r)
    return out


def own_quotes():
    """{(corridor, size, provider): row} from the newest hour collected."""
    rs = [r for r in rows(QUOTES) if flag(r, "source_ok")]
    hour = newest_hour(rs)
    if hour is None:
        return {}, None
    out = {}
    for r in in_hour(rs, hour):
        size = num(r, "size_src")
        if size is None or num(r, "cost_bps") is None:
            continue
        out[(r["corridor"], int(size), r["provider"])] = r
    return out, hour


def panel_quotes(corridor):
    """{(size, provider): cost_bps} from the comparison API, newest hour."""
    rs = [r for r in rows(os.path.join(DATA, PANELS[corridor]))
          if flag(r, "source_ok") and r.get("provider")]
    hour = newest_hour(rs)
    if hour is None:
        return {}, None
    out = {}
    for r in in_hour(rs, hour):
        size, cost = num(r, "notional_src"), num(r, "cost_bps")
        if size is None or cost is None:
            continue
        out[(int(size), r["provider"])] = cost
    return out, hour


def crypto_route(corridor):
    """{size: cost_bps} for the crypto route, newest hour of that corridor."""
    rs = [r for r in rows(SAMPLES)
          if (r.get("corridor") or "").strip() == corridor and flag(r, "source_ok")]
    hour = newest_hour(rs, "ts")
    if hour is None:
        return {}, None
    out = {}
    for r in in_hour(rs, hour, "ts"):
        size, cost = num(r, "notional_src"), num(r, "cost_bps_taker")
        if size is not None and cost is not None:
            out[int(size)] = cost
    return out, hour


def money(cur, v, dp=2):
    if v is None:
        return None
    sym = SYMBOL.get(cur, cur + " ")
    return f"{sym}{v:,.{dp}f}"


def build():
    own, own_hour = own_quotes()
    corridors = {}
    for corridor in sorted(PANELS):
        panel, panel_hour = panel_quotes(corridor)
        crypto, crypto_hour = crypto_route(corridor)
        src, dst = corridor.split("->")
        sizes = sorted({s for s, _ in panel} | {s for (c, s, _) in own if c == corridor}
                       | set(crypto))
        if not sizes:
            continue
        out_sizes = {}
        for size in sizes:
            seen, entries = set(), []
            # 1. the provider's own published quote wins
            for (c, s, prov), r in own.items():
                if c != corridor or s != size:
                    continue
                cost = num(r, "cost_bps")
                entries.append({
                    "provider": prov, "cost_pct": round(cost / 100, 4),
                    "costs": money(src, size * cost / 1e4),
                    "source": "own", "source_words": "quoted by " + prov + " itself",
                    "rate": num(r, "rate"), "fee": num(r, "fee_src"),
                    "fee_words": (None if not num(r, "fee_src")
                                  else money(src, num(r, "fee_src")) + " fee"),
                    "also_quoted_pct": (round(panel[(size, prov)] / 100, 4)
                                        if (size, prov) in panel else None),
                })
                seen.add(prov)
            # 2. the comparison API fills in everyone else
            for (s, prov), cost in panel.items():
                if s != size or prov in seen:
                    continue
                entries.append({
                    "provider": prov, "cost_pct": round(cost / 100, 4),
                    "costs": money(src, size * cost / 1e4),
                    "source": "comparison",
                    "source_words": "from the comparison Wise publishes",
                    "rate": None, "fee": None, "fee_words": None,
                    "also_quoted_pct": None,
                })
            if size in crypto:
                c = crypto[size]
                entries.append({
                    "provider": "The crypto route", "cost_pct": round(c / 100, 4),
                    "costs": money(src, size * c / 1e4),
                    "source": "measured",
                    "source_words": "measured on real exchanges, all in",
                    "rate": None, "fee": None, "fee_words": None,
                    "also_quoted_pct": None,
                })
            entries.sort(key=lambda e: e["cost_pct"])
            for i, e in enumerate(entries):
                e["rank"] = i + 1
            out_sizes[str(size)] = {
                "amount": size, "amount_words": money(src, size, 0),
                "rows": entries,
                "cheapest": entries[0]["provider"] if entries else None,
            }
        corridors[corridor] = {
            "route": corridor, "route_words": ROUTE_WORDS.get(corridor, corridor),
            "src": src, "dst": dst, "sizes": out_sizes,
            "panel_hour_utc": panel_hour.isoformat() if panel_hour else None,
            "crypto_hour_utc": crypto_hour.isoformat() if crypto_hour else None,
        }
    snap = {"corridors": corridors,
            "own_quote_hour_utc": own_hour.isoformat() if own_hour else None,
            "sources": ["data/provider_quotes.csv", "data/samples.csv"]
                       + [f"data/{p}" for p in sorted(PANELS.values())]}
    stamps = [c["panel_hour_utc"] for c in corridors.values() if c["panel_hour_utc"]]
    if stamps:
        snap["as_of_utc"] = max(stamps)
    return snap


def main():
    snap = build()
    try:
        os.makedirs(DATA, exist_ok=True)
        with open(OUT, "w") as f:
            json.dump(snap, f, indent=2, sort_keys=True)
            f.write("\n")
    except OSError as e:
        print(f"  [error] cannot write {OUT}: {e}", file=sys.stderr)
        sys.exit(1)
    cs = snap["corridors"]
    print(f"  wrote {os.path.relpath(OUT, HERE)}  ({len(cs)} routes)")
    for k, c in sorted(cs.items()):
        mid = c["sizes"].get("1000") or next(iter(c["sizes"].values()), None)
        if not mid:
            continue
        top = mid["rows"][0]
        own = sum(1 for r in mid["rows"] if r["source"] == "own")
        print(f"    {c['route_words']:32} {mid['amount_words']:>9}  "
              f"cheapest {top['provider']} {top['cost_pct']:.2f}%  "
              f"({len(mid['rows'])} ways, {own} self-quoted)")


if __name__ == "__main__":
    main()

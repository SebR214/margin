#!/usr/bin/env python3
"""Shared reader for the record emitters (SEB-240): one definition of "a reading"
and of "a source", used by emit_record_daily, emit_cycle_log, emit_record_milestones
and emit_sources_daily, so the four files can never disagree with each other.

Stored files only, stdlib only, no clock. This module never opens anything under
the history directory (tools/check_history_isolation.py); the two emitters that
need the backfill manifest read it themselves and are on that check's list.

WHAT COUNTS AS A READING. One stored row, in one of the collector files below,
at or after 2026-08-10 (the first reading), whose own success column is not
False. Rows with source_ok=False are attempts, not readings, and are not counted
(they are counted separately, as misses, in the cycle log). fx_rates.csv has no
success column: every row is a reading.

    basis.csv            one order-book / broker reading per venue and currency
    p2p_basis.csv        Binance P2P (and CoinGecko, for NGN) per currency
    p2p_okx.csv          OKX P2P per currency
    fx_rates.csv         official rate per currency (open.er-api, bcra) and the
                         parallel-dollar rate where one is stored
    provider_quotes.csv  a provider's own quote, per route and size
    providers.csv, providers_audphp.csv, providers_nzdphp.csv, providers_sgdinr.csv,
    providers_usdinr.csv, providers_usdmxn.csv, providers_usdngn.csv
                         the price-comparison feed, one row per provider, route
                         and size (the route is the file's)
    samples.csv          one priced route through order books, per route and size
    corridor_variants.csv  stablecoin / network variants of a route
    stable_spread.csv    USDT vs USDC spread per venue

NOT counted, because they are derived from rows already counted or are not
measurements: p2p_sides, p2p_depth, p2p_offers, p2p_box_depth, samples_depth,
corridor_waterfall, ramp_waterfall, price_changes, p2p_spread_signal,
stress_signal, offramp_snapshots (ends 2026-08-10), stable_venues,
provider_quotes_payout_type, provider_delivery, fee_checks, fee_tier_schedule,
withdrawal_fees, ramp_fees, audit_history and the daily country layer.
"""

import csv
import datetime as dt
import os

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data")
START_DAY = "2026-08-10"

COMPARISON_FEED = "api.wise.com/v3/comparisons"

CRIPTOYA_PREFIX = "CriptoYa"


def read_csv(name):
    with open(os.path.join(DATA, name), newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _ok(r):
    return (r.get("source_ok") or "").strip().lower() != "false"


def _truthy(v):
    return bool((v or "").strip())


# file -> spec. ts: timestamp column. sources(row) -> [(id, kind)].
# ccy(row) -> currency code a country page would show, or None. route(row) -> corridor or None.
def _basis_sources(r):
    v = r["venue"]
    return [(v, "broker" if v.startswith(CRIPTOYA_PREFIX) else "order_book")]


def _p2p_sources(r):
    s = r["source"]
    return [(s, "p2p" if s.endswith("_p2p") else "other")]


def _fx_sources(r):
    out = [(r["source"], "fx")]
    if _truthy(r.get("parallel_source")) and _truthy(r.get("parallel_rate_per_usd")):
        out.append((r["parallel_source"], "fx"))
    return out


def _quote_sources(r):
    return [(r["source"], "provider_quote")]


def _comparison_sources(r):
    return [(COMPARISON_FEED, "provider_quote")]


def _samples_sources(r):
    out = []
    for col in ("onramp_venue", "offramp_venue"):
        if _truthy(r.get(col)):
            out.append((r[col], "order_book"))
    return out


def _stable_sources(r):
    return [(r["venue"], "order_book")]


def _const(v):
    return lambda r: v


SPECS = [
    dict(file="basis.csv", ts="ts_utc", sources=_basis_sources, ccy=lambda r: r.get("ccy"), route=None),
    dict(file="p2p_basis.csv", ts="ts_utc", sources=_p2p_sources, ccy=lambda r: r.get("ccy"), route=None),
    dict(file="p2p_okx.csv", ts="ts_utc", sources=_p2p_sources, ccy=lambda r: r.get("ccy"), route=None),
    dict(file="fx_rates.csv", ts="ts_utc", sources=_fx_sources, ccy=lambda r: r.get("ccy"), route=None),
    dict(file="provider_quotes.csv", ts="ts_utc", sources=_quote_sources, ccy=None, route=lambda r: r["corridor"]),
    dict(file="providers.csv", ts="ts_utc", sources=_comparison_sources, ccy=None, route=_const("SGD->PHP")),
    dict(file="providers_audphp.csv", ts="ts_utc", sources=_comparison_sources, ccy=None, route=_const("AUD->PHP")),
    dict(file="providers_nzdphp.csv", ts="ts_utc", sources=_comparison_sources, ccy=None, route=_const("NZD->PHP")),
    dict(file="providers_sgdinr.csv", ts="ts_utc", sources=_comparison_sources, ccy=None, route=_const("SGD->INR")),
    dict(file="providers_usdinr.csv", ts="ts_utc", sources=_comparison_sources, ccy=None, route=_const("USD->INR")),
    dict(file="providers_usdmxn.csv", ts="ts_utc", sources=_comparison_sources, ccy=None, route=_const("USD->MXN")),
    dict(file="providers_usdngn.csv", ts="ts_utc", sources=_comparison_sources, ccy=None, route=_const("USD->NGN")),
    dict(file="samples.csv", ts="ts", sources=_samples_sources, ccy=None, route=lambda r: r["corridor"]),
    dict(file="corridor_variants.csv", ts="ts", sources=lambda r: [], ccy=None, route=lambda r: r["corridor"]),
    dict(file="stable_spread.csv", ts="ts_utc", sources=_stable_sources, ccy=lambda r: r.get("ccy"), route=None),
]
READING_FILES = [s["file"] for s in SPECS]


def iso_z(ts):
    """'2026-08-10T13:29:38.685291+00:00' -> '2026-08-10T13:29:38Z'. Stored stamps are all UTC."""
    t = dt.datetime.fromisoformat(ts)
    if t.tzinfo is not None:
        t = t.astimezone(dt.timezone.utc).replace(tzinfo=None)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def readings():
    """Every stored attempt at or after START_DAY, as dicts:
    ts (raw string), file, ok (bool), sources [(id, kind)], ccy, route.
    Attempts with ok False are kept so callers can count misses."""
    out = []
    for spec in SPECS:
        for r in read_csv(spec["file"]):
            ts = r.get(spec["ts"]) or ""
            if len(ts) < 13 or ts[:10] < START_DAY:
                continue
            out.append({
                "ts": ts,
                "file": spec["file"],
                "ok": _ok(r),
                "sources": spec["sources"](r),
                "ccy": (spec["ccy"](r) if spec["ccy"] else None) or None,
                "route": (spec["route"](r) if spec["route"] else None) or None,
            })
    out.sort(key=lambda x: x["ts"])
    return out


def day_of(ts):
    return ts[:10]


def hour_of(ts):
    return ts[:13]


def day_range(first, last):
    d = dt.date.fromisoformat(first)
    end = dt.date.fromisoformat(last)
    out = []
    while d <= end:
        out.append(d.isoformat())
        d += dt.timedelta(days=1)
    return out


def hour_floor_iso(h):
    """'2026-08-10T13' -> '2026-08-10T13:00:00Z'"""
    return h + ":00:00Z"


class Registry:
    """What the stored readings say about each source, built in one pass.

    sources[id] = dict(kind, ccys, routes, files, first_ts, last_ts (newest ok), ok_hours, fail_hours)
    all_hours   = hours with at least one counted reading from anywhere (the collector ran)
    """

    def __init__(self, rows):
        self.rows = rows
        self.sources = {}
        self.all_hours = set()
        for r in rows:
            h = hour_of(r["ts"])
            if r["ok"]:
                self.all_hours.add(h)
            for sid, kind in r["sources"]:
                s = self.sources.setdefault(sid, dict(kind=kind, ccys=set(), routes=set(), files=set(),
                                                      first_ts=None, last_ts=None, ok_hours=set(), fail_hours=set()))
                s["files"].add(r["file"])
                if r["ccy"]:
                    s["ccys"].add(r["ccy"])
                if r["route"]:
                    s["routes"].add(r["route"])
                if r["ok"]:
                    s["ok_hours"].add(h)
                    if s["first_ts"] is None or r["ts"] < s["first_ts"]:
                        s["first_ts"] = r["ts"]
                    if s["last_ts"] is None or r["ts"] > s["last_ts"]:
                        s["last_ts"] = r["ts"]
                else:
                    s["fail_hours"].add(h)
        # a source that never answered at all is not a source yet
        self.sources = {k: v for k, v in self.sources.items() if v["first_ts"]}
        for sid, s in self.sources.items():
            s["cadence_hours"] = cadence_hours(s["ok_hours"])

    def expected_hours(self, sid, hours):
        """The hours (of `hours`, all collected hours) at which the source was expected to answer
        under its own cadence: every collected hour from its first answer on."""
        f = hour_of(self.sources[sid]["first_ts"])
        return [h for h in hours if h >= f]


def _hour_dt(h):
    return dt.datetime.strptime(h, "%Y-%m-%dT%H")


def cadence_hours(ok_hours):
    """Median gap, in whole hours (at least 1), between the distinct hours a source answered."""
    hs = sorted(ok_hours)
    if len(hs) < 2:
        return 1
    gaps = sorted((_hour_dt(b) - _hour_dt(a)).total_seconds() / 3600 for a, b in zip(hs, hs[1:]))
    n = len(gaps)
    med = gaps[n // 2] if n % 2 else (gaps[n // 2 - 1] + gaps[n // 2]) / 2
    return max(1, int(round(med)))


def median(vals):
    v = sorted(vals)
    n = len(v)
    if not n:
        return None
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2


def write_json(path, doc):
    import json
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        f.write("\n")


def assert_no_nan(obj, where=""):
    """Raise if any float in the JSON-able tree is NaN or inf."""
    if isinstance(obj, float):
        if obj != obj or obj in (float("inf"), float("-inf")):
            raise AssertionError("NaN/inf at " + where)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            assert_no_nan(v, where + "/" + str(k))
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            assert_no_nan(v, where + "[%d]" % i)

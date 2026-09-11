#!/usr/bin/env python3
"""Probe a candidate source for a commission, before anyone wires it in.

A commission (see ROADMAP.md "Commission") names a currency this project does
not collect and, usually, a candidate source for it -- a URL or a documented
API, entered by a person or an agent reading the issue, never discovered by a
search run from inside this tool. This script fetches exactly one quote from
that candidate and checks it against an independent reference this codebase
already uses elsewhere, the same way METHODOLOGY.md's worked reading
("A worked reading: Indodax -119 bps") checks a divergence before trusting it.

The bar is the one already on record in METHODOLOGY.md, "Checked against":
"A difference over 1% needs an explanation or the country carries the
'unverified' label." A candidate that clears it is accepted; one that does not
is rejected, with the exact numbers, never a bare pass/fail.

References supported (both already read elsewhere in this codebase):
  erapi        open.er-api.com -- the denominator collector_fx.py reads first.
  fawazahmed0  the second aggregator METHODOLOGY.md's Indodax reading checks
               against.

This never writes to data/ and never opens or comments on an issue --
wiring a source in is agents/COMMISSION.md's job once a probe is accepted.

Usage:
  python3 tools/probe_source.py --ccy IDR \\
      --url https://indodax.com/api/usdt_idr/ticker --field ticker.last

  python3 tools/probe_source.py --ccy IDR --url ... --field ticker.last \\
      --reference fawazahmed0 --json
"""

import argparse
import json
import re
import sys

try:
    import requests
except ImportError:
    requests = None

HTTP_TIMEOUT = 20
UA = {"User-Agent": "margin.wiki probe-source/1.0 (+https://margin.wiki)"}

# The project-wide bar, not one invented for this tool. See METHODOLOGY.md,
# "Checked against": every cross-check on record is judged against this line.
TOLERANCE_PCT = 1.0

REFERENCES = {
    "erapi": (
        "https://open.er-api.com/v6/latest/USD",
        lambda payload, ccy: (payload.get("rates") or {}).get(ccy.upper()),
    ),
    "fawazahmed0": (
        "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/usd.json",
        lambda payload, ccy: (payload.get("usd") or {}).get(ccy.lower()),
    ),
}

_PART = re.compile(r"^([^\[\]]+)((?:\[\d+\])*)$")


def dig(payload, path):
    """Walk a dotted path like `ticker.last` or `results[0].price` -> value.

    Returns None on any missing key, wrong type or bad index -- a candidate
    whose shape does not match what was entered is a rejected probe, never a
    crash.
    """
    cur = payload
    for part in path.split("."):
        m = _PART.match(part)
        if not m:
            return None
        key, indices = m.group(1), re.findall(r"\[(\d+)\]", m.group(2))
        if not isinstance(cur, dict) or key not in cur:
            return None
        cur = cur[key]
        for idx in indices:
            i = int(idx)
            if not isinstance(cur, list) or i >= len(cur):
                return None
            cur = cur[i]
    return cur


def to_float(v):
    try:
        f = float(v)
        return f if f == f and f > 0 else None
    except (TypeError, ValueError):
        return None


def fetch_json(url):
    r = requests.get(url, timeout=HTTP_TIMEOUT, headers=UA)
    r.raise_for_status()
    return r.json()


def probe(ccy, url, field, reference="erapi", fetch=fetch_json):
    """One candidate quote, checked against one independent reference.

    Returns a dict with `accepted` and `check` -- `check` states the exact
    values and the arithmetic, never a bare pass/fail. Never raises: any
    transport, parse or lookup failure comes back as a rejected probe with the
    reason in `check`.
    """
    if reference not in REFERENCES:
        return {"accepted": False, "ccy": ccy,
                "check": f"unknown reference {reference!r}; choose one of "
                         f"{sorted(REFERENCES)}"}

    try:
        candidate_payload = fetch(url)
    except Exception as e:
        return {"accepted": False, "ccy": ccy,
                "check": f"candidate {url} unreachable: "
                         f"{type(e).__name__}: {e}"}

    candidate_val = to_float(dig(candidate_payload, field))
    if candidate_val is None:
        return {"accepted": False, "ccy": ccy,
                "check": f"candidate {url} field `{field}` did not resolve to "
                         f"a positive number"}

    ref_url, ref_fn = REFERENCES[reference]
    try:
        ref_payload = fetch(ref_url)
    except Exception as e:
        return {"accepted": False, "ccy": ccy,
                "check": f"reference {reference} ({ref_url}) unreachable: "
                         f"{type(e).__name__}: {e}"}

    ref_val = to_float(ref_fn(ref_payload, ccy))
    if ref_val is None:
        return {"accepted": False, "ccy": ccy,
                "check": f"reference {reference} ({ref_url}) has no rate for "
                         f"{ccy}"}

    diff_pct = (candidate_val - ref_val) / ref_val * 100.0
    accepted = abs(diff_pct) <= TOLERANCE_PCT
    check = (
        f"candidate {url} field `{field}` reported {candidate_val:.6g} {ccy} "
        f"per dollar; independent reference {reference} ({ref_url}) reported "
        f"{ref_val:.6g} {ccy} per dollar; difference {diff_pct:+.2f}% against "
        f"an accept bar of ±{TOLERANCE_PCT:.2f}% (METHODOLOGY.md, "
        f"\"Checked against\"). "
        + ("Accepted." if accepted else "Rejected: outside the bar.")
    )
    return {
        "accepted": accepted, "ccy": ccy.upper(),
        "candidate_url": url, "candidate_field": field,
        "candidate_value": candidate_val,
        "reference": reference, "reference_url": ref_url,
        "reference_value": ref_val,
        "difference_pct": round(diff_pct, 4),
        "tolerance_pct": TOLERANCE_PCT,
        "check": check,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ccy", required=True, help="currency code, e.g. IDR")
    ap.add_argument("--url", required=True,
                     help="candidate source: a JSON endpoint")
    ap.add_argument("--field", required=True,
                     help="dotted path to the quote in the candidate's JSON, "
                          "e.g. ticker.last or results[0].price")
    ap.add_argument("--reference", choices=sorted(REFERENCES), default="erapi")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    if requests is None:
        sys.exit("pip install requests")

    result = probe(a.ccy, a.url, a.field, a.reference)
    if a.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"  [{'accepted' if result['accepted'] else 'rejected'}] "
              f"{result['ccy']}")
        print(f"  {result['check']}")
    return 0 if result["accepted"] else 1


if __name__ == "__main__":
    sys.exit(main())

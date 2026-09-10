#!/usr/bin/env python3
"""Who changed their price, and when. Builds data/price_changes.csv (+ latest JSON).

THE PROBLEM THIS FILE EXISTS TO SOLVE, and the only interesting decision in it:

A provider's cost is measured against a mid-market rate. Our snapshot of the mid
and the moment the provider's quote was captured are never the same instant, so
every provider's measured cost wobbles hour to hour by a few hundredths of a
percent even when nobody has touched their pricing. Measured on a month of
SGD->PHP and USD->MXN, the median hour-to-hour wobble is 2-4 bps and the median
day-over-day wobble of the daily median is ~12 bps -- and it lands on the SAME
DAY for every provider in the panel at once, because it is the reference moving,
not nine companies repricing in unison.

So a naive "cost changed by more than X" test reports the reference as news.

THE TEST USED HERE IS PAIRWISE UNANIMITY:

  A provider is recorded as having changed its price on a day only if its cost
  moved against EVERY other provider in the same panel, on the same day, in the
  same direction, by at least the threshold.

Because both sides of each pair are measured against the same mid at the same
instant, the mid cancels exactly. A move in the reference shifts every provider
together and produces no pairwise difference at all, so it is silent here. A
move by one provider shows up against all of its peers and is reported. This
also survives the case that defeats a basket average: when one provider makes a
large move it drags any average or median reference with it, painting a false
move on everybody else -- pairwise differences are immune, because the peer
being compared against is never the mover.

Comparisons are of the DAILY MEDIAN of each pairwise difference, requiring at
least MIN_READINGS hourly readings on both days, so a single bad hour cannot
create an event and a change must persist to be reported.

`new_cost_pct` is the provider's observed daily median cost on the day of the
change. `old_cost_pct` is that figure minus the confirmed move: what the same
day would have cost at the old price. Both are therefore on the SAME day's
exchange rate, so their difference is exactly `move_pct` and the row never
contradicts itself. The previous day's raw observed median is kept alongside as
`prev_day_cost_pct` -- it differs from `old_cost_pct` by the reference drift,
which is precisely the quantity this file refuses to publish as news.

Append-only and idempotent: an event already in the CSV is never rewritten, so
re-running mid-day, or after a backfill, cannot duplicate or revise history.
Because of that, only COMPLETE days are judged: a day becomes eligible once a
later day exists in the data. Today is always partial, and a call made on half
a day could not be corrected once written.

Derived, never authoritative. Stdlib only.

Usage: python3 tools/emit_price_changes.py
"""

import csv
import datetime as dt
import itertools
import json
import os
import statistics as st
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data")
OUT_CSV = os.path.join(DATA, "price_changes.csv")
OUT_JSON = os.path.join(DATA, "price_changes_latest.json")

# The brief's six columns, in the brief's order, then the evidence that made the
# call. Frozen from here on; anything new goes in a sidecar.
FIELDS = ["ts_utc", "corridor", "size", "provider", "old_cost_pct",
          "new_cost_pct", "move_pct", "n_agree", "n_panel", "old_day",
          "prev_day_cost_pct", "kind"]

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

# 0.02 percentage points, per the brief. Unanimity is what removes the noise;
# this only sets the floor below which a move is too small to be worth saying.
THRESHOLD_PCT = 0.02
MIN_READINGS = 6      # hourly readings required on each of the two days
MIN_PANEL = 3         # a panel of fewer than three cannot vote


def read_rows(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def num(raw):
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        v = float(raw)
    except ValueError:
        return None
    return v if v == v else None


def judged_days(rows):
    """The days this file is willing to judge: every complete day but the first.

    The first has no day before it to compare against and the last is today,
    still filling. Reported so a page can quote a denominator -- "on 2 of the 3
    Saturdays measured" is a claim; "every weekend" is a guess.
    """
    days = sorted({r["ts_utc"][:10] for r in rows})
    return days[1:-1]


def panel_events(corridor, rows):
    """Every confirmed price change in one corridor's panel."""
    out = []
    sizes = sorted({r["notional_src"] for r in rows}, key=float)
    for size in sizes:
        sub = [r for r in rows
               if r["notional_src"] == size and r.get("source_ok") == "True"
               and num(r.get("cost_bps")) is not None]
        stamps = sorted({r["ts_utc"] for r in sub})
        if not stamps:
            continue
        # The panel is the providers quoted at every single timestamp. A provider
        # that comes and goes would change the comparison set under our feet.
        seen = {}
        for r in sub:
            seen[r["provider"]] = seen.get(r["provider"], 0) + 1
        core = sorted(p for p, n in seen.items() if n == len(stamps))
        if len(core) < MIN_PANEL:
            continue

        by_stamp = {}
        for r in sub:
            by_stamp.setdefault(r["ts_utc"], {})[r["provider"]] = num(r["cost_bps"])

        # Daily medians: of each pairwise difference, and of each provider's own
        # cost (for the before/after numbers on the page).
        pair_day, own_day = {}, {}
        for ts in stamps:
            quotes = by_stamp[ts]
            day = ts[:10]
            for p in core:
                if p in quotes:
                    own_day.setdefault((p, day), []).append(quotes[p])
            for a, b in itertools.permutations(core, 2):
                if a in quotes and b in quotes:
                    pair_day.setdefault((a, b, day), []).append(quotes[a] - quotes[b])

        days = sorted({ts[:10] for ts in stamps})
        # days[-1] is today and still filling. A change called on a partial day
        # could reverse by evening, and this file never rewrites a row.
        for i in range(1, len(days) - 1):
            d0, d1 = days[i - 1], days[i]
            for p in core:
                moves, ok = [], True
                for q in core:
                    if q == p:
                        continue
                    v0 = pair_day.get((p, q, d0)) or []
                    v1 = pair_day.get((p, q, d1)) or []
                    if len(v0) < MIN_READINGS or len(v1) < MIN_READINGS:
                        ok = False
                        break
                    moves.append(st.median(v1) - st.median(v0))
                if not ok or not moves:
                    continue
                floor = THRESHOLD_PCT * 100.0   # percentage points -> bps
                if not all(abs(m) >= floor for m in moves):
                    continue
                if len({m > 0 for m in moves}) != 1:      # must agree on direction
                    continue
                o0 = own_day.get((p, d0)) or []
                o1 = own_day.get((p, d1)) or []
                if len(o0) < MIN_READINGS or len(o1) < MIN_READINGS:
                    continue
                now = st.median(o1) / 100.0
                mv = st.median(moves) / 100.0
                out.append({
                    "corridor": corridor,
                    "size": size,
                    "provider": p,
                    "old_day": d0,
                    "new_day": d1,
                    # Same day, same rate, so after - before == the move exactly.
                    "old_cost_pct": round(now - mv, 4),
                    "new_cost_pct": round(now, 4),
                    "prev_day_cost_pct": round(st.median(o0) / 100.0, 4),
                    "move_pct": round(mv, 4),
                    "n_agree": len(moves),
                    "n_panel": len(core),
                })
    return out


def label_weekends(events):
    """Mark a rise on a Saturday that comes back on the following Monday.

    A price that goes up every weekend and returns on Monday is a weekend rate,
    not a repricing, and saying so is the difference between a log and a finding.

    Matched on the EVENT -- one company, one route, one day -- not on each
    amount separately. A company raises its price, not its price-at-S$200, and
    whether the return leg clears the threshold at every amount is a question
    about measurement granularity, not about what the company did. Both legs
    must be present in the data; nothing is inferred from one leg alone.
    """
    for e in events:
        e["kind"] = "change"

    by_day = {}
    for e in events:
        by_day.setdefault((e["corridor"], e["provider"], e["new_day"]), []).append(e)

    def direction(group):
        return st.median([g["move_pct"] for g in group])

    for (corridor, provider, day), group in by_day.items():
        d = dt.date.fromisoformat(day)
        if d.weekday() != 5 or direction(group) <= 0:      # Saturday, and dearer
            continue
        for back in (2, 3):                                # Monday, or Tuesday
            other = by_day.get((corridor, provider,
                                (d + dt.timedelta(days=back)).isoformat()))
            if other and direction(other) < 0:
                for e in group:
                    if e["move_pct"] > 0:
                        e["kind"] = "weekend_up"
                for e in other:
                    if e["move_pct"] < 0:
                        e["kind"] = "weekend_back"
                break
    return events


def money(corridor, size):
    src = corridor.split("->")[0]
    return f"{SYMBOL.get(src, src + ' ')}{int(float(size)):,}"


def main():
    events = []
    for corridor, fname in PANELS.items():
        rows = read_rows(os.path.join(DATA, fname))
        if not rows:
            print(f"  {corridor:<10} no panel file yet")
            continue
        found = panel_events(corridor, rows)
        events.extend(found)
        days = len({r["ts_utc"][:10] for r in rows})
        print(f"  {corridor:<10} {len(rows):>6} rows over {days:>3} days"
              f" -> {len(found):>3} confirmed changes")
    events = label_weekends(events)

    # Append only what is new. History is never rewritten.
    existing = read_rows(OUT_CSV)
    have = {(r["corridor"], r["size"], r["provider"], r["ts_utc"][:10])
            for r in existing}
    fresh = []
    for e in sorted(events, key=lambda x: (x["new_day"], x["corridor"],
                                           float(x["size"]), x["provider"])):
        key = (e["corridor"], e["size"], e["provider"], e["new_day"])
        if key in have:
            continue
        have.add(key)
        fresh.append({
            "ts_utc": e["new_day"] + "T00:00:00+00:00",
            "corridor": e["corridor"],
            "size": e["size"],
            "provider": e["provider"],
            "old_cost_pct": e["old_cost_pct"],
            "new_cost_pct": e["new_cost_pct"],
            "move_pct": e["move_pct"],
            "n_agree": e["n_agree"],
            "n_panel": e["n_panel"],
            "old_day": e["old_day"],
            "prev_day_cost_pct": e["prev_day_cost_pct"],
            "kind": e["kind"],
        })

    new_file = not os.path.exists(OUT_CSV)
    if fresh or new_file:
        with open(OUT_CSV, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            if new_file:
                w.writeheader()
            for r in fresh:
                w.writerow(r)
    print(f"  price_changes.csv: {len(existing)} kept, {len(fresh)} appended")

    # The page reads the JSON; the CSV is the record.
    allrows = read_rows(OUT_CSV)
    for r in allrows:
        for k in ("old_cost_pct", "new_cost_pct", "move_pct",
                  "prev_day_cost_pct"):
            r[k] = num(r[k])
        r["route_words"] = ROUTE_WORDS.get(r["corridor"], r["corridor"])
        r["amount_words"] = money(r["corridor"], r["size"])
        r["day"] = r["ts_utc"][:10]
        r["weekday"] = dt.date.fromisoformat(r["day"]).strftime("%A")
    allrows.sort(key=lambda r: (r["day"], r["corridor"], float(r["size"])),
                 reverse=True)
    saturdays = {}
    for corridor, fname in PANELS.items():
        rows = read_rows(os.path.join(DATA, fname))
        if not rows:
            continue
        days = judged_days(rows)
        saturdays[corridor] = sum(
            1 for d in days if dt.date.fromisoformat(d).weekday() == 5)

    payload = {
        "index_version": "1.1",
        "saturdays_judged": saturdays,
        "threshold_pct": THRESHOLD_PCT,
        "min_readings": MIN_READINGS,
        "routes": {c: ROUTE_WORDS[c] for c in PANELS
                   if any(r["corridor"] == c for r in allrows)},
        "changes": allrows,
        "counts": {
            "total": len(allrows),
            "weekend": sum(1 for r in allrows if r["kind"].startswith("weekend")),
        },
    }
    with open(OUT_JSON, "w") as f:
        json.dump(payload, f, indent=1, sort_keys=False)
        f.write("\n")
    print(f"  price_changes_latest.json: {len(allrows)} changes on record")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""One check for a broken official rate (SEB-310 item 3), in plain code, run once a day.

The rate every index figure is divided by is er-api's (data/fx_rates.csv). Two ways it goes wrong have already cost us:
Sudan's repeats the same seven daily values (about 544, 511, 510, 509, 458, 454, 449) week after week, and Iraq's moved
from about 1,310 to 1,517 in four steps over six days (9 to 14 Oct) while the real rate had moved at once. This reads each
currency's daily series (the last er-api value of each UTC day) and flags a currency on any of four rules:

  weekly_loop   the last 21 days repeat the days seven before them, within 2%, on at least 80% of days, while the series
                moves by more than 5% inside each of the last two weeks (a rate that sits still is not a loop: that is the flat rule,
                and one step in a flat rate is not a loop either)
  jump_reverse  a day-to-day move of more than 10% that is undone, to within 3% of the old value, inside five days
  flat_30       the rate has not changed at all, to six decimals, for 30 days (a managed peg does this legitimately; the flag
                says so is for a person to judge, it does not hide the rate)
  lags_live     er-api differs from the live rate (data/fx_live.csv, last read of the day) by more than 3% on two days in a
                row. Needs fx_live.csv, which holds nothing before 21 Oct; with none, this rule says nothing

Writes data/official_rate_flags.csv, rebuilt each run: as_of_date, ccy, rule, detail. Nothing reads it yet; it does not
switch the published rate (Seb decides that). Exits 0 whether or not it flags: a flag is information, not a failure.

Usage:  python3 tools/check_official_rates.py             # data/ -> data/official_rate_flags.csv
        python3 tools/check_official_rates.py --self-test
"""
import csv
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FX = os.path.join(ROOT, "data", "fx_rates.csv")
LIVE = os.path.join(ROOT, "data", "fx_live.csv")
OUT = os.path.join(ROOT, "data", "official_rate_flags.csv")
HEADER = ["as_of_date", "ccy", "rule", "detail"]


def daily(path, ts_col, rate_col, ok_col=None):
    """{ccy: {YYYY-MM-DD: last rate that day}}"""
    out = {}
    if not os.path.exists(path):
        return out
    rows = sorted(csv.DictReader(open(path, newline="")), key=lambda r: r[ts_col])
    for r in rows:
        if ok_col and r.get(ok_col) != "True":
            continue
        try:
            v = float(r[rate_col])
        except (TypeError, ValueError):
            continue
        out.setdefault(r["ccy"], {})[r[ts_col][:10]] = v
    return out


def rule_weekly_loop(vals):
    n = len(vals)
    if n < 28:
        return None
    last = vals[-21:]
    hits = sum(1 for i in range(n - 21, n) if abs(vals[i] / vals[i - 7] - 1) < 0.02)
    wk, before = vals[-7:], vals[-14:-7]
    # a loop moves in the week it repeats AND in the week before it: a flat rate that steps once equals itself 7 days earlier on every
    # day but the days after the step, and is not a loop (found 22 Oct on Iraq's step of 9 Oct, SEB-311)
    if hits / 21 >= 0.8 and max(wk) / min(wk) - 1 > 0.05 and max(before) / min(before) - 1 > 0.05:
        return "%d of the last 21 days equal the day seven before, within 2%%, while the rate swings %.0f%% inside a week" % (
            hits, (max(wk) / min(wk) - 1) * 100)
    return None


def rule_jump_reverse(vals):
    for i in range(1, len(vals) - 1):
        if abs(vals[i] / vals[i - 1] - 1) > 0.10:
            for j in range(i + 1, min(len(vals), i + 6)):
                if abs(vals[j] / vals[i - 1] - 1) < 0.03:
                    return "moved %.0f%% on day %d and was back within 3%% of the old value %d days later" % (
                        (vals[i] / vals[i - 1] - 1) * 100, i, j - i)
    return None


def rule_flat_30(vals):
    if len(vals) < 30:
        return None
    w = [round(v, 6) for v in vals[-30:]]
    if len(set(w)) == 1:
        return "unchanged at %s for 30 days" % w[0]
    return None


def rule_lags_live(days_vals, live_days):
    """days_vals {date: er-api}, live_days {date: live}: two consecutive days more than 3% apart."""
    run, worst = 0, 0.0
    for d in sorted(set(days_vals) & set(live_days)):
        gap = abs(days_vals[d] / live_days[d] - 1)
        run = run + 1 if gap > 0.03 else 0
        worst = max(worst, gap) if run else worst
        if run >= 2:
            return "er-api differs from the live rate by more than 3%% on two days running (up to %.0f%%), ending %s" % (worst * 100, d)
    return None


def check(series, live):
    flags = []
    for ccy in sorted(series):
        days = sorted(series[ccy])
        vals = [series[ccy][d] for d in days]
        for name, fn in (("weekly_loop", rule_weekly_loop), ("jump_reverse", rule_jump_reverse), ("flat_30", rule_flat_30)):
            why = fn(vals)
            if why:
                flags.append((days[-1], ccy, name, why))
        if live.get(ccy):
            why = rule_lags_live(series[ccy], live[ccy])
            if why:
                flags.append((days[-1], ccy, "lags_live", why))
    return flags


def main():
    series = daily(FX, "ts_utc", "fx_mid_per_usd")
    live = daily(LIVE, "ts_utc", "rate_per_usd", ok_col="source_ok")
    flags = check(series, live)
    with open(OUT, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(HEADER)
        w.writerows(flags)
    print("official rates: %d currencies checked, %d flagged%s" % (len(series), len({f[1] for f in flags}),
          "" if live else " (no live rate stored yet: lags_live says nothing)"))
    for f in flags:
        print("  %s %s: %s" % (f[1], f[2], f[3]))
    return 0


def self_test():
    # the real er-api daily series for Sudan, 10 Sep to 21 Oct 2026 (data/fx_rates.csv): a seven-day loop
    sdg = [544.44, 511.892, 510.852, 509.273, 458.764, 454.424, 449.085, 544.265, 511.647, 510.607, 592.069, 513.515, 482.839, 462.879,
           543.543, 511.441, 510.412, 508.851, 458.664, 454.23, 449.414, 543.657, 511.544, 510.509, 508.938, 458.581, 453.808, 449.442,
           542.902, 511.101, 510.078, 508.524, 458.676, 454.209, 448.981, 544.012, 511.842, 510.807, 509.235, 458.537, 454.024, 449.23]
    assert rule_weekly_loop(sdg), "Sudan's loop must be flagged"
    assert rule_flat_30(sdg) is None
    assert rule_jump_reverse(sdg), "Sudan's 20 Sep spike to 592 that was back at 514 the next day is a jump and reverse too"
    # Iraq: er-api stepped 1,308 -> 1,429 -> 1,502 -> 1,517 over 9 to 14 Oct; the live rate sat near 1,517 from 7 Oct
    iqd_days = ["2026-10-%02d" % d for d in range(1, 22)]
    iqd = dict(zip(iqd_days, [1309.95, 1310.21, 1310.21, 1310.22, 1310.78, 1311.82, 1311.25, 1308.40, 1428.89, 1430.32, 1432.48,
                              1502.02, 1508.26, 1515.69, 1517.31, 1517.53, 1517.54, 1517.55, 1517.21, 1517.22, 1517.23]))
    live = {d: (1517.0 if d >= "2026-10-07" else 1310.0) for d in iqd_days}
    why = rule_lags_live(iqd, live)
    assert why and "ending 2026-10-08" in why, why  # first two days in a row: 7 and 8 Oct
    assert rule_lags_live(iqd, {d: iqd[d] for d in iqd_days}) is None, "no gap, no flag"
    # a lag that is gone after one day is not flagged; a quiet rate is not a loop
    assert rule_weekly_loop([3.6725] * 42) is None and rule_flat_30([3.6725] * 42), "a peg is flat, not a loop"
    assert rule_flat_30([1.0 + 0.001 * (i % 2) for i in range(40)]) is None
    # one step in an otherwise flat rate equals itself a week earlier on most days, and is not a loop (Iraq, 9 Oct)
    step = [1310.0] * 30 + [1429.0] + [1430.0] * 3
    assert rule_weekly_loop(step) is None, "a single step is not a loop"
    # a spike that comes straight back is flagged, a step that stays is not
    assert rule_jump_reverse([100] * 5 + [130] + [101] * 5), "spike and reverse"
    assert rule_jump_reverse([100] * 5 + [130] * 6) is None, "a step that stays is not a reversal"
    flags = check({"SDG": dict(zip(["d%02d" % i for i in range(len(sdg))], sdg)), "AED": {"d%02d" % i: 3.6725 for i in range(40)}}, {})
    assert {(f[1], f[2]) for f in flags} == {("SDG", "weekly_loop"), ("SDG", "jump_reverse"), ("AED", "flat_30")}, flags
    print("check_official_rates self-test: ok (Sudan loop and Iraq lag flagged, a peg and a step are not mistaken for them)")
    return 0


if __name__ == "__main__":
    sys.exit(self_test() if "--self-test" in sys.argv else main())

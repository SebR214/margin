"""Backlog 19a: the p2p_spread_signal finding test file, and its calculation on made-up rows.

Every threshold comes from findings_tests/p2p_spread_signal.json; none is typed here. No live data is read.
"""
import datetime as dt
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEST = json.loads((ROOT / "findings_tests" / "p2p_spread_signal.json").read_text())
REF = json.loads((ROOT / "findings_tests" / "price_changes.json").read_text())
COLS = ["ts_utc", "ccy", "spread_pct", "ccy_mean_spread_pct", "spread_ratio", "n_prior_readings"]  # data/p2p_spread_signal.csv's header

RATIO = float(re.search(r"at least ([\d.]+) times", TEST["calculation"]).group(1))
HOURS = int(re.search(r"within (\d+) hours", TEST["calculation"]).group(1))
DAYS = int(re.search(r"last (\d+) days", TEST["window"]).group(1))
MIN_SPIKES = int(re.search(r"at least (\d+) judged spikes", TEST["min_observations"]).group(1))


def parse(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def classify(value):
    if value >= TEST["holds"]:
        return "holds"
    return "weaker" if value >= TEST["weaker"] else "no longer true"


def run(rows):
    """The calculation in the test file: the share of judged spikes that closed within the hours, or 'not enough evidence'."""
    rated = sorted((r for r in rows if r["spread_ratio"] != ""), key=lambda r: (r["ccy"], r["ts_utc"]))
    if not rated:
        return "not enough evidence"
    newest = max(parse(r["ts_utc"]) for r in rated)
    by_ccy = {}
    for r in rated:
        by_ccy.setdefault(r["ccy"], []).append((parse(r["ts_utc"]), float(r["spread_ratio"])))
    judged = closed = 0
    for series in by_ccy.values():
        for i, (t, ratio) in enumerate(series):
            if ratio < RATIO or (i and series[i - 1][1] >= RATIO) or t < newest - dt.timedelta(days=DAYS):
                continue
            after = series[i + 1:]
            if any(u <= t + dt.timedelta(hours=HOURS) and x < RATIO for u, x in after):
                judged, closed = judged + 1, closed + 1
            elif any(u >= t + dt.timedelta(hours=HOURS) for u, _ in after):
                judged += 1
    if judged < MIN_SPIKES:
        return "not enough evidence"
    return classify(closed / judged)


def table(blocks):
    """One row per hour per currency; each block is a currency's ratios, hour after hour."""
    start = dt.datetime(2026, 1, 5, tzinfo=dt.timezone.utc)
    out = []
    for n, ratios in enumerate(blocks):
        for h, ratio in enumerate(ratios):
            out.append(dict(zip(COLS, [(start + dt.timedelta(hours=h)).isoformat(), "C%02d" % n, "%.4f" % ratio,
                                       "1.0000", "%.4f" % ratio, str(100 + h)])))
    return out


def test_same_keys_as_price_changes():
    assert set(TEST) == set(REF), set(TEST) ^ set(REF)
    assert TEST["id"] == "p2p_spread_signal"
    assert TEST["evidence_file"] == "data/p2p_spread_signal.csv"
    assert 0 < TEST["weaker"] < TEST["holds"] <= 1 and TEST["direction"] == "higher_is_better"


def test_holds_reversed_and_too_few():
    spike = RATIO + 0.5
    calm = RATIO / 2
    holding = table([[spike] + [calm] * (HOURS)] * MIN_SPIKES)            # each spike closes the next hour
    reversed_ = table([[spike + 0.1 * h for h in range(HOURS + 1)]] * MIN_SPIKES)   # each spike still open 3 hours on
    assert len(holding) == 40 and len(reversed_) == 40
    assert run(holding) == "holds"
    assert run(reversed_) == "no longer true"
    assert run(holding[:5]) == "not enough evidence"


if __name__ == "__main__":
    test_same_keys_as_price_changes()
    test_holds_reversed_and_too_few()
    print("ok")

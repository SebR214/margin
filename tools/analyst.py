#!/usr/bin/env python3
"""The analyst (SEB-210, ROADMAP Queue item 20): deterministic nightly
investigations, a model only for the words. Absorbs ROADMAP items 7, 8, 9
and 10.

Every investigation below is a plain function over the CSVs and JSON the
collectors and emitters already wrote -- no model call, no network, stdlib
only. It computes numbers, decides whether they clear a stated notability
threshold, and only then -- never before the numbers exist -- asks Fable
(`claude-fable-5-1`) for at most three cited sentences of interpretation.
If nothing clears the threshold on a given night, no finding is stored and no
model is called: "nothing clears it, nothing is published."

THE MODEL CALL, AND WHY IT IS SHAPED THIS WAY: night work runs on the
subscription token, never the metered key (ROADMAP item 13). `tools/critic.py`
and `tools/ask_backend.py` call `api.anthropic.com` directly with
`ANTHROPIC_API_KEY` -- the metered key, billed per token. This script instead
shells out to the `claude` CLI binary itself, the same one `agents/run.sh`
already runs the builder/reviewer/product loops through on this box,
authenticated via whatever OAuth session is already logged in there. No new
credential, no new spend line: it is the existing subscription, used for a
single narrow completion instead of an agentic session (no tools, one turn).

THE HARD CHECK: before an interpretation is stored, `check_interpretation`
re-scans its text for every numeral and refuses to store the interpretation if
any numeral does not trace to a number this script itself computed and handed
the model in the prompt. A model that invents a number fails here, loudly --
the finding is kept (its numbers are real, code-computed), but it carries no
words that night.

EVIDENCE CHAINS: every finding records the files it was computed from and the
exact selection/arithmetic that produced it (`evidence.query`), in the same
spirit as `tools/audit_numbers.py`'s `trace` field. A finding that reuses an
earlier one -- same night or a prior night's stored finding of the same kind
and subject -- lists it in `cites`.

THE HISTORY LAYER: one investigation (`investigate_live_vs_history`) compares
a live venue reading against the "reported, not observed" candle for the same
venue and hour. This is the one deliberate, spec'd reader of `data/history/`
outside its own writer (`tools/backfill_history.py`) -- see the new
`HISTORY_READERS` entry in `tools/check_history_isolation.py` and its comment.
It never writes a history row and this file is not the index, a published
price, the observed series or the unbroken-hours count, so the isolation that
check exists to prove is untouched.

PRIVACY: this script's only outputs are `data/analyst_findings.json` (the
finding store) and `data/analyst_log.csv` (one append-only line per run). No
page reads either file. ROADMAP item 20's gate -- findings stay private until
the auditor has scored 95% or better for seven straight days -- is therefore
met by construction right now (there is no reader at all); `auditor_gate_met`
below only reports the gate's state so a future page knows when it may open.

Usage:
    python3 tools/analyst.py                       # a real night
    python3 tools/analyst.py --dry-run              # print, write nothing
    python3 tools/analyst.py --no-model              # skip the Fable call (numbers only)
    python3 tools/analyst.py --threshold-scale 1000  # raise every bar near-impossibly high
    python3 tools/analyst.py --selftest              # exercise the hard check with no I/O, no model, no network
"""

import argparse
import csv
import datetime as dt
import glob
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data")
COUNTRIES_DIR = os.path.join(DATA, "countries")
RECEIPTS_DIR = os.path.join(DATA, "corridor_receipts")
P2P_BASIS = os.path.join(DATA, "p2p_basis.csv")
P2P_OKX = os.path.join(DATA, "p2p_okx.csv")
BASIS = os.path.join(DATA, "basis.csv")
PRICE_CHANGES = os.path.join(DATA, "price_changes.csv")
CORRIDOR_SUMMARY = os.path.join(DATA, "corridor_summary.json")
HISTORY_MANIFEST = os.path.join(DATA, "history", "manifest.json")
AUDIT_HISTORY = os.path.join(DATA, "audit_history.csv")
OUT = os.path.join(DATA, "analyst_findings.json")
LOG = os.path.join(DATA, "analyst_log.csv")
LINEAR = os.path.join(HERE, "agents", "linear.py")

MODEL_ID = "claude-fable-5-1"

# ---------------------------------------------------------- stated thresholds
# Every bar here is a deliberate choice, not a tuned secret, and every one of
# them is multiplied by --threshold-scale, which exists only to prove the
# "nothing clears it, nothing is published" path on real data (see Usage).
COUNTRY_MOVER_WINDOW_DAYS = 7
COUNTRY_MOVER_MIN_N = 5          # ads/sources required on both ends of the window
COUNTRY_MOVER_PP_THRESHOLD = 5.0  # percentage points of index_pct over the window

ROUTE_MOVER_WINDOW_DAYS = 7
ROUTE_MOVER_PP_THRESHOLD = 0.5   # percentage points; emit_price_changes.py's own floor is 0.02

BOARDS_DISAGREE_REL_THRESHOLD = 0.05   # 5% relative gap between two boards' buy_median
BOARDS_DISAGREE_MAX_HOURS_APART = 3

SILENT_DAYS_THRESHOLD = 3   # days since a country's last priced day, vs the freshest country

LIVE_HISTORY_BPS_THRESHOLD = 75.0
LIVE_HISTORY_MAX_HOURS_APART = 2

WIN_CONDITION_CHANGE_BPS = 5.0   # re-notify only if the required leg move shifted by at least this
WIN_CONDITION_MIN_GAP_BPS = 10.0   # a gap smaller than this isn't worth stating even the first time


def rows(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def ok(v):
    return str(v).strip().lower() == "true"


def load_json(path):
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


# --------------------------------------------------------------- the store
def load_store():
    d = load_json(OUT)
    return d if d else {"findings": []}


def latest_by_key(store, kind, subject):
    """The most recent previously-stored finding of this kind and subject, if
    any -- used both to decide whether a standing condition (a win condition)
    has moved enough to be notable again, and to cite it."""
    cand = [f for f in store["findings"] if f["kind"] == kind and f["subject"] == subject]
    return max(cand, key=lambda f: f["as_of_date"]) if cand else None


def make_finding(fid, kind, subject, as_of, numbers, files, query, cites=None):
    return {
        "id": fid, "kind": kind, "subject": subject, "as_of_date": as_of,
        "numbers": numbers,
        "evidence": {"files": files, "query": query},
        "cites": cites or [],
        "model_id": None,
        "interpretation": None,
        "interpretation_rejected": None,
    }


# ----------------------------------------------------- investigation: movers
def investigate_country_movers(as_of_date, scale):
    out, too_young = [], 0
    window_start = (dt.date.fromisoformat(as_of_date) - dt.timedelta(days=COUNTRY_MOVER_WINDOW_DAYS)).isoformat()
    for f in sorted(glob.glob(os.path.join(COUNTRIES_DIR, "*.json"))):
        d = load_json(f)
        hist = d.get("history") or []
        if not hist or hist[-1]["date"] != as_of_date:
            continue  # not priced today at all -- that's investigate_countries_silent's job
        latest = hist[-1]
        if latest.get("n") is None or latest["n"] < COUNTRY_MOVER_MIN_N:
            continue
        earlier = [h for h in hist if h["date"] <= window_start]
        if not earlier:
            too_young += 1
            continue
        start = earlier[-1]
        if start.get("n") is None or start["n"] < COUNTRY_MOVER_MIN_N:
            continue
        move = round(latest["index_pct"] - start["index_pct"], 4)
        if abs(move) < COUNTRY_MOVER_PP_THRESHOLD * scale:
            continue
        ccy = d["ccy"]
        numbers = {"index_pct_now": latest["index_pct"], "index_pct_window_start": start["index_pct"],
                   "move_pp": move, "window_days": COUNTRY_MOVER_WINDOW_DAYS,
                   "n_now": latest["n"], "n_window_start": start["n"]}
        fid = "country_mover:%s:%s" % (ccy, as_of_date)
        q = ("%s's dollar price moved %s index points (from %s%% to %s%% over cost) "
             "between %s (n=%s) and %s (n=%s)." %
             (ccy, move, start["index_pct"], latest["index_pct"], start["date"], start["n"], latest["date"], latest["n"]))
        out.append(make_finding(fid, "country_mover", ccy, as_of_date, numbers, [os.path.relpath(f, HERE)], q))
    return out, too_young


def investigate_route_movers(as_of_date, scale):
    cutoff = (dt.date.fromisoformat(as_of_date) - dt.timedelta(days=ROUTE_MOVER_WINDOW_DAYS)).isoformat()
    best = {}
    for r in rows(PRICE_CHANGES):
        if r["ts_utc"][:10] < cutoff:
            continue
        mv = num(r["move_pct"])
        if mv is None or abs(mv) < ROUTE_MOVER_PP_THRESHOLD * scale:
            continue
        key = (r["corridor"], r["provider"], r["old_day"])
        if key not in best or abs(mv) > abs(num(best[key]["move_pct"])):
            best[key] = r
    out = []
    for (corridor, provider, old_day), r in best.items():
        numbers = {"old_cost_pct": num(r["old_cost_pct"]), "new_cost_pct": num(r["new_cost_pct"]),
                   "move_pct": num(r["move_pct"]), "n_agree": int(r["n_agree"]), "n_panel": int(r["n_panel"])}
        fid = "route_mover:%s:%s:%s:%s" % (corridor, provider, old_day, as_of_date)
        q = ("%s's cost on %s moved from %s%% to %s%% on %s, agreed on by %s of %s providers in the panel (data/price_changes.csv)." %
             (provider, corridor, numbers["old_cost_pct"], numbers["new_cost_pct"], old_day, r["n_agree"], r["n_panel"]))
        out.append(make_finding(fid, "route_mover", "%s:%s" % (corridor, provider), as_of_date, numbers,
                                 ["data/price_changes.csv"], q))
    return out


# ------------------------------------------------- investigation: win conditions
def latest_receipt_per_corridor():
    latest = {}
    for f in sorted(glob.glob(os.path.join(RECEIPTS_DIR, "*.json"))):
        d = load_json(f)
        c = d["corridor"]
        ts = d["evidence"]["collected_at"]
        if c not in latest or ts > latest[c][1]:
            latest[c] = (d, ts, os.path.relpath(f, HERE))
    return {c: (d, path) for c, (d, ts, path) in latest.items()}


def win_condition_for_regime(corridor, baseline_bps, receipt, regime):
    """Pure arithmetic, pulled out of the I/O so --selftest can exercise the
    'missing baseline' gap without touching real files (ROADMAP item 10's
    feedback loop: 'can't explain without data X' -> a collection-queue item).
    Returns (finding_numbers_or_None, gap_description_or_None)."""
    comp = receipt["computation"].get(regime, {})
    if not comp.get("legs_available"):
        return None, None  # a documented, permanent limitation (no legs for limit orders), not a data gap
    legs = comp["legs"]
    total = comp["result_pct"]
    if baseline_bps is None:
        return None, "win-condition arithmetic for %s (%s) needs a cheapest-app baseline cost, but %s is not in data/corridor_summary.json" % (
            corridor, regime, corridor)
    gap = round(total - baseline_bps, 2)
    if gap <= 0:
        return None, None  # already winning on this regime; nothing to hold constant toward
    sell_now = legs["sell_bps"]
    required_sell = round(sell_now - gap, 2)
    reachable = required_sell >= 0
    numbers = {
        "stablecoin_cost_bps": total, "cheapest_app_cost_bps": baseline_bps, "gap_bps": gap,
        "off_ramp_spread_now_bps": sell_now, "off_ramp_spread_required_bps": required_sell,
        "reachable_by_off_ramp_alone": reachable,
        "deposit_bps": legs["deposit_bps"], "buy_bps": legs["buy_bps"],
        "move_bps": legs["move_bps"], "withdrawal_bps": legs["withdrawal_bps"],
    }
    return numbers, None


def investigate_win_conditions(as_of_date, scale, store, collection_tasks):
    summary = load_json(CORRIDOR_SUMMARY) or {"corridors": []}
    baseline_by_corridor = {c["corridor"]: c["baseline_cost_bps_median"] for c in summary["corridors"]}
    route_words_by_corridor = {c["corridor"]: c["route_words"] for c in summary["corridors"]}
    receipts = latest_receipt_per_corridor()
    out = []
    for corridor, (receipt, path) in sorted(receipts.items()):
        for regime in ("taker", "maker"):
            files = [path, "data/corridor_summary.json"]
            numbers, gap = win_condition_for_regime(corridor, baseline_by_corridor.get(corridor), receipt, regime)
            if gap:
                collection_tasks.append((
                    "win-condition: missing baseline for %s" % corridor,
                    "tools/emit_corridor_summary.py does not list %s, so the analyst cannot state the "
                    "off-ramp win condition for it even though data/corridor_receipts has a stablecoin "
                    "cost to compare. Needs: %s added to data/corridor_summary.json's corridors list." % (corridor, corridor),
                    None))
                continue
            if numbers is None or numbers["gap_bps"] < WIN_CONDITION_MIN_GAP_BPS * scale:
                continue
            subject = "%s:%s" % (corridor, regime)
            prev = latest_by_key(store, "win_condition", subject)
            if prev and abs(prev["numbers"]["off_ramp_spread_required_bps"] - numbers["off_ramp_spread_required_bps"]) < WIN_CONDITION_CHANGE_BPS * scale \
                    and prev["numbers"]["reachable_by_off_ramp_alone"] == numbers["reachable_by_off_ramp_alone"]:
                continue  # a standing fact that has not moved enough since last time to say again
            fid = "win_condition:%s:%s" % (subject, as_of_date)
            cites = [prev["id"]] if prev else []
            q = ("%s (%s) %s: stablecoin cost %s bps vs cheapest app %s bps (gap %s bps); holding deposit, buy, "
                 "move and withdrawal legs constant, the off-ramp spread would need to fall from %s to below %s "
                 "bps%s." % (corridor, route_words_by_corridor.get(corridor, corridor), regime,
                             numbers["stablecoin_cost_bps"], numbers["cheapest_app_cost_bps"],
                             numbers["gap_bps"], numbers["off_ramp_spread_now_bps"], numbers["off_ramp_spread_required_bps"],
                             "" if numbers["reachable_by_off_ramp_alone"] else " (not reachable by this leg alone)"))
            out.append(make_finding(fid, "win_condition", subject, as_of_date, numbers, files, q, cites=cites))
    return out


# --------------------------------------------------- investigation: boards disagree
def investigate_boards_disagree(as_of_date, scale):
    def latest_source_ok(path, source):
        by_ccy = {}
        for r in rows(path):
            if r["source"] == source and ok(r.get("source_ok")):
                by_ccy[r["ccy"]] = r  # chronological file -- last write wins
        return by_ccy

    binance = latest_source_ok(P2P_BASIS, "binance_p2p")
    okx = latest_source_ok(P2P_OKX, "okx_p2p")
    out = []
    for ccy in sorted(set(binance) & set(okx)):
        a, b = binance[ccy], okx[ccy]
        pa, pb = num(a["buy_median"]), num(b["buy_median"])
        if pa is None or pb is None or pa <= 0 or pb <= 0:
            continue
        ta, tb = dt.datetime.fromisoformat(a["ts_utc"]), dt.datetime.fromisoformat(b["ts_utc"])
        hours_apart = abs((ta - tb).total_seconds()) / 3600.0
        if hours_apart > BOARDS_DISAGREE_MAX_HOURS_APART:
            continue
        rel = abs(pa - pb) / ((pa + pb) / 2.0)
        if rel < BOARDS_DISAGREE_REL_THRESHOLD * scale:
            continue
        numbers = {"binance_buy_median": pa, "okx_buy_median": pb, "relative_gap_pct": round(rel * 100, 2),
                   "binance_n_ads": int(a["n_ads"]), "okx_n_ads": int(b["n_ads"])}
        fid = "boards_disagree:%s:%s" % (ccy, as_of_date)
        q = ("For %s, Binance's buy-side median was %s (n=%s ads, %s) and OKX's was %s (n=%s ads, %s) -- "
             "a %.1f%% relative gap between two boards pricing the same dollar." %
             (ccy, pa, a["n_ads"], a["ts_utc"], pb, b["n_ads"], b["ts_utc"], rel * 100))
        out.append(make_finding(fid, "boards_disagree", ccy, as_of_date, numbers,
                                 ["data/p2p_basis.csv", "data/p2p_okx.csv"], q))
    return out


# -------------------------------------------------- investigation: gone silent
def investigate_countries_silent(as_of_date, scale):
    out = []
    for f in sorted(glob.glob(os.path.join(COUNTRIES_DIR, "*.json"))):
        d = load_json(f)
        hist = d.get("history") or []
        if not hist:
            continue
        last_date = hist[-1]["date"]
        if last_date == as_of_date:
            continue
        days_silent = (dt.date.fromisoformat(as_of_date) - dt.date.fromisoformat(last_date)).days
        if days_silent < SILENT_DAYS_THRESHOLD * scale:
            continue
        ccy = d["ccy"]
        numbers = {"last_priced_date": last_date, "days_silent": days_silent,
                   "last_index_pct": hist[-1]["index_pct"]}
        fid = "country_silent:%s:%s" % (ccy, as_of_date)
        q = ("%s (%s) last had a priced hour on %s -- %d days before %s -- with no price since." %
             (d.get("country", ccy), ccy, last_date, days_silent, as_of_date))
        out.append(make_finding(fid, "country_silent", ccy, as_of_date, numbers,
                                 [os.path.relpath(f, HERE)], q))
    return out


# ------------------------------------------- investigation: live vs. history
def investigate_live_vs_history(as_of_date, scale):
    manifest = load_json(HISTORY_MANIFEST)
    if not manifest:
        return []
    hourly = {k: v for k, v in manifest.get("files", {}).items() if k.endswith("_1h") and "ccy" in v}
    latest_live = {}
    for r in rows(BASIS):
        if ok(r.get("source_ok")):
            latest_live[r["venue"]] = r  # chronological -- last write wins

    out = []
    for key, meta in sorted(hourly.items()):
        venue = key[: -len("_1h")]
        live = latest_live.get(venue)
        if not live:
            continue
        live_price = num(live["usdt_mid"]) or num(live["usdt_ask"])
        if not live_price:
            continue
        candle_path = os.path.join(HERE, meta["file"])
        if not os.path.exists(candle_path):
            continue
        live_dt = dt.datetime.fromisoformat(live["ts_utc"])
        best_row, best_diff = None, None
        for r in rows(candle_path):
            if r["ccy"] != live["ccy"]:
                continue
            cdt = dt.datetime.strptime(r["ts_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
            diff = abs((cdt - live_dt).total_seconds()) / 3600.0
            if best_diff is None or diff < best_diff:
                best_row, best_diff = r, diff
        if best_row is None or best_diff > LIVE_HISTORY_MAX_HOURS_APART:
            continue
        close = num(best_row["close"])
        if not close:
            continue
        bps = round((live_price / close - 1) * 1e4, 2)
        if abs(bps) < LIVE_HISTORY_BPS_THRESHOLD * scale:
            continue
        numbers = {"live_usdt_mid": live_price, "history_candle_close": close, "disagreement_bps": bps,
                   "history_candle_ts": best_row["ts_utc"], "live_ts": live["ts_utc"]}
        fid = "live_history_disagree:%s:%s:%s" % (venue, live["ccy"], as_of_date)
        q = ("%s's live USDT price (%s, observed %s) disagrees with its own reported history candle "
             "(%s, %s, labelled \"reported, not observed\") by %s basis points." %
             (venue, live_price, live["ts_utc"], close, best_row["ts_utc"], bps))
        out.append(make_finding(fid, "live_history_disagree", "%s:%s" % (venue, live["ccy"]), as_of_date, numbers,
                                 ["data/basis.csv", meta["file"]], q))
    return out


# ------------------------------------------------------------ the hard check
NUM_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
# A calendar date or timestamp is a label the code handed over (as_of_date, a
# row's own ts_utc), never a statistic -- strip it before scanning for
# numbers so "2026-10-03" doesn't get parsed as the digits 2026, 10 and 03
# and flagged as three invented figures.
DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?)?\b")


def allowed_reprs(numbers):
    reps = set()
    for v in numbers.values():
        if isinstance(v, bool) or v is None:
            continue
        if isinstance(v, (int, float)):
            for nd in (0, 1, 2, 3, 4):
                reps.add(round(float(v), nd))
    return reps


def check_interpretation(text, numbers, evidence_files):
    """Returns (ok, reasons). Two independent failures: a numeral that does
    not trace to a code-computed number, or a shape violation (too many
    sentences, no citation).

    Deliberately no exemption for small round numbers: an earlier version let
    any integer under 32 through on the theory that it was a day-count or a
    leg-count, and that is exactly the shape an invented "20%" or "15 bps"
    takes. Every legitimate count (ads, days, panel size) this script's
    prompts can produce is already a key in `numbers`, so nothing legitimate
    needs an exemption."""
    reasons = []
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]
    if not sentences:
        reasons.append("empty interpretation")
        return False, reasons
    if len(sentences) > 3:
        reasons.append("%d sentences, more than the three-sentence limit" % len(sentences))
    allowed = allowed_reprs(numbers)
    scan_text = DATE_RE.sub(" ", text)
    for tok in NUM_RE.findall(scan_text):
        clean = tok.replace(",", "")
        try:
            val = float(clean)
        except ValueError:
            continue
        if not any(abs(val - a) < 0.05 for a in allowed):
            reasons.append("number %s in the interpretation does not trace to a computed value" % tok)
    cited = any(os.path.basename(fp) in text or fp in text for fp in evidence_files)
    if not cited:
        reasons.append("no evidence file named in the text")
    return (len(reasons) == 0), reasons


# ------------------------------------------------------------- the model call
def call_fable(prompt, timeout=120):
    """Shells out to the `claude` CLI -- the subscription token, never
    ANTHROPIC_API_KEY. See the module docstring."""
    try:
        r = subprocess.run(
            ["claude", "-p", prompt, "--model", MODEL_ID,
             "--allowedTools", "", "--max-turns", "1", "--output-format", "json"],
            capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return None, "the claude CLI is not on PATH"
    except subprocess.TimeoutExpired:
        return None, "the claude CLI timed out after %ss" % timeout
    if r.returncode != 0:
        return None, "claude CLI exited %s: %s" % (r.returncode, r.stderr.strip()[:300])
    try:
        payload = json.loads(r.stdout)
    except json.JSONDecodeError:
        return None, "claude CLI did not return JSON"
    if payload.get("is_error"):
        return None, "claude CLI reported an error: %s" % str(payload.get("result"))[:300]
    text = (payload.get("result") or "").strip()
    if not text:
        return None, "claude CLI returned no text"
    return text, None


def build_prompt(f):
    return (
        "You are writing a private research note, not a public page. Here is one "
        "fully-computed finding from tonight's run. Every number below was computed "
        "by code; you may not introduce any other number, estimate, or forecast.\n\n"
        "kind: %s\nsubject: %s\nas_of_date: %s\ncomputed numbers: %s\nhow these numbers "
        "were derived: %s\nsource file(s): %s\n\n"
        "Write at most three sentences interpreting this finding for a colleague who has "
        "not seen the numbers. Use only the numbers given above, in the units given. End "
        "each sentence by naming, in parentheses, the source file it draws on. Do not "
        "speculate about cause, and do not predict what happens next." %
        (f["kind"], f["subject"], f["as_of_date"], json.dumps(f["numbers"], sort_keys=True),
         f["evidence"]["query"], ", ".join(f["evidence"]["files"])))


def interpret(f):
    text, err = call_fable(build_prompt(f))
    if err:
        f["interpretation_rejected"] = [err]
        return
    okc, reasons = check_interpretation(text, f["numbers"], f["evidence"]["files"])
    if not okc:
        f["interpretation_rejected"] = reasons
        return
    f["model_id"] = MODEL_ID
    f["interpretation"] = text


# ------------------------------------------------------- the collection queue
def file_collection_tasks(tasks, store, dry_run):
    """'Can't explain without data X' -> a Linear issue, automatically
    (ROADMAP item 10). Deduplicated against every task this script has ever
    filed, recorded in the store, so a standing gap is reported once, not
    every night it persists."""
    filed = store.setdefault("collection_tasks_filed", {})
    for title, body, _ in tasks:
        if title in filed:
            continue
        if dry_run:
            print("[analyst] would file collection task: %s" % title, file=sys.stderr)
            filed[title] = {"filed": "dry-run"}
            continue
        try:
            r = subprocess.run(
                ["python3", LINEAR, "new", title, "--body", body, "--label", "collection",
                 "--priority", "3", "--role", "analyst"],
                capture_output=True, text=True, timeout=60, cwd=HERE)
            filed[title] = {"filed": r.stdout.strip() if r.returncode == 0 else "FAILED: %s" % r.stderr.strip()[:200]}
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            filed[title] = {"filed": "FAILED: %s" % e}


# ------------------------------------------------------------- the auditor gate
def auditor_gate_met():
    """Reports, never gates: this script publishes nothing a page reads, so the
    item-19 gate (95%+ for seven straight days) is already satisfied by having
    no reader at all. This exists so a future findings page knows when it may
    open without re-deriving the rule."""
    by_date = {}
    for r in rows(AUDIT_HISTORY):
        by_date[r["date"]] = num(r["score_pct"])  # last run of the day wins
    days = sorted(by_date)[-7:]
    if len(days) < 7:
        return False, "%d/7 days of auditor history" % len(days)
    if all((by_date[d] or 0) >= 95.0 for d in days):
        return True, "7/7 days at >=95%%"
    worst = min(by_date[d] or 0 for d in days)
    return False, "worst of the last 7 days scored %.1f%%" % worst


# ------------------------------------------------------------------- selftest
def selftest():
    numbers = {"move_pp": 7.23, "n_now": 24, "window_days": 7}
    files = ["data/countries/PHP.json"]
    good = "The Philippines moved 7.23 points over the window (data/countries/PHP.json)."
    bad_number = "The Philippines moved 71.23 points over the window (data/countries/PHP.json)."
    bad_round_number = "The Philippines moved about 20 points over the window (data/countries/PHP.json)."
    bad_shape = ("One (data/countries/PHP.json). Two (data/countries/PHP.json). "
                 "Three (data/countries/PHP.json). Four (data/countries/PHP.json).")
    no_citation = "The Philippines moved 7.23 points over the window."
    with_date = "As of 2026-10-03T05:06:33+00:00, the move was 7.23 points (data/countries/PHP.json)."

    cases = [
        ("real numbers only, cited", good, True),
        ("invented number rejected", bad_number, False),
        ("invented ROUND number rejected", bad_round_number, False),
        ("too many sentences rejected", bad_shape, False),
        ("uncited text rejected", no_citation, False),
        ("a timestamp is not a number", with_date, True),
    ]
    failed = 0
    for name, text, want_ok in cases:
        got_ok, reasons = check_interpretation(text, numbers, files)
        status = "ok" if got_ok == want_ok else "FAIL"
        if status == "FAIL":
            failed += 1
        print("[selftest] %-28s %s (ok=%s reasons=%s)" % (name, status, got_ok, reasons))

    numbers2, gap = win_condition_for_regime(
        "FAKE->TEST", None,
        {"computation": {"taker": {"legs_available": True, "result_pct": 100.0,
                                    "legs": {"deposit_bps": 0, "buy_bps": 50, "move_bps": 10,
                                             "sell_bps": 30, "withdrawal_bps": 10}}}},
        "taker")
    want = numbers2 is None and gap is not None and "FAKE->TEST" in gap
    print("[selftest] %-28s %s (gap=%r)" % ("missing-baseline gap detected", "ok" if want else "FAIL", gap))
    if not want:
        failed += 1

    print("[selftest] %d/%d cases failed" % (failed, len(cases) + 1))
    return 1 if failed else 0


# ------------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print the result, write nothing")
    ap.add_argument("--no-model", action="store_true", help="skip the Fable call; numbers only")
    ap.add_argument("--threshold-scale", type=float, default=1.0,
                     help="multiply every notability threshold (use a large value to prove nothing publishes)")
    ap.add_argument("--selftest", action="store_true", help="exercise the hard check, no I/O, no model")
    a = ap.parse_args()

    if a.selftest:
        return selftest()

    country_files = sorted(glob.glob(os.path.join(COUNTRIES_DIR, "*.json")))
    if not country_files:
        print("analyst: no country data to investigate", file=sys.stderr)
        return 1
    as_of_date = max(load_json(f)["history"][-1]["date"] for f in country_files if load_json(f).get("history"))

    store = load_store()
    collection_tasks = []

    movers, too_young = investigate_country_movers(as_of_date, a.threshold_scale)
    route_movers = investigate_route_movers(as_of_date, a.threshold_scale)
    win_conditions = investigate_win_conditions(as_of_date, a.threshold_scale, store, collection_tasks)
    boards = investigate_boards_disagree(as_of_date, a.threshold_scale)
    silent = investigate_countries_silent(as_of_date, a.threshold_scale)
    live_hist = investigate_live_vs_history(as_of_date, a.threshold_scale)

    all_candidates = movers + route_movers + win_conditions + boards + silent + live_hist
    # A re-run on a day already stored adds nothing (same rule as
    # tools/audit_numbers.py's history line): a finding's id already encodes
    # its kind, subject and as_of_date, so an identical id means this exact
    # night's version of this exact finding has already been published.
    existing_ids = {f["id"] for f in store["findings"]}
    new_findings = [f for f in all_candidates if f["id"] not in existing_ids]

    # Later findings cite earlier ones from the SAME run when they share a
    # subject (e.g. a country that both moved and went silent tonight).
    seen_by_subject = {}
    for f in new_findings:
        prior = seen_by_subject.get(f["subject"])
        if prior and prior["id"] not in f["cites"]:
            f["cites"].append(prior["id"])
        seen_by_subject[f["subject"]] = f

    interpreted, rejected = 0, 0
    if not a.no_model:
        for f in new_findings:
            interpret(f)
            if f["interpretation"]:
                interpreted += 1
            elif f["interpretation_rejected"]:
                rejected += 1

    gate_met, gate_detail = auditor_gate_met()
    by_kind = {}
    for f in new_findings:
        by_kind[f["kind"]] = by_kind.get(f["kind"], 0) + 1
    already_stored = len(all_candidates) - len(new_findings)

    print("analyst %s: %d new findings (%d country movers, %d route movers, %d win conditions, "
          "%d board disagreements, %d gone silent, %d live/history disagreements); %d already stored "
          "from an earlier run today; %d too-young-to-compare; %d interpreted, %d rejected; "
          "auditor gate: %s (%s)" %
          (as_of_date, len(new_findings), by_kind.get("country_mover", 0), by_kind.get("route_mover", 0),
           by_kind.get("win_condition", 0), by_kind.get("boards_disagree", 0), by_kind.get("country_silent", 0),
           by_kind.get("live_history_disagree", 0), already_stored, too_young, interpreted, rejected,
           "met" if gate_met else "not met", gate_detail))

    if a.dry_run:
        print(json.dumps(new_findings, indent=1, sort_keys=True))
        return 0

    store["findings"].extend(new_findings)
    file_collection_tasks(collection_tasks, store, a.dry_run)
    with open(OUT, "w") as f:
        json.dump(store, f, indent=1, sort_keys=True)
        f.write("\n")

    is_new = not os.path.exists(LOG)
    with open(LOG, "a", newline="") as f:
        w = csv.writer(f)
        if is_new:
            w.writerow(["date", "candidates", "interpreted", "rejected", "collection_tasks_filed", "auditor_gate_met"])
        w.writerow([as_of_date, len(new_findings), interpreted, rejected, len(collection_tasks), gate_met])

    return 0


if __name__ == "__main__":
    sys.exit(main())

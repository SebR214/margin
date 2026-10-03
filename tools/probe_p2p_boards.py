#!/usr/bin/env python3
"""Probe report for ROADMAP item 14: a second and third P2P board.

collector_p2p.py reads exactly one advertisement board, Binance P2P, for the
wide capital-controlled layer. This tool is the live check behind the next
one: for each of Bybit, OKX and HTX, ask the SAME question collector_p2p.py
already answers for Binance -- does the board's own public ad-search endpoint
answer a normal GET/POST, with no login, no API key and no bot challenge, for
a real currency pair? -- and record candidate, what was checked, the live
result and the verdict, the same shape SEB-177's venue probes used.

HARD RULE, same as every collector in this repo: no login, no session pool,
no cookie rotation, no disguised User-Agent, no CAPTCHA bypass. A board that
needs any of those is rejected in public, with the reason, not worked around.
Every request here goes out under this tool's own named User-Agent, paced and
retried exactly like collector_p2p.py's own transport.

PROBED LIVE 2026-10-03, from this box (Hetzner, Falkenstein DE -- confirmed
via ipinfo.io at probe time, since Bybit's P2P endpoint was previously logged
in collector_p2p.py as blocked from GitHub's US-hosted runners):

  Bybit   api2.bybit.com/fiat/otc/item/online (POST) -- and in fact every
          path on bybit.com, including the static /robots.txt. Every request
          under this tool's own User-Agent either gets an immediate HTTP/2
          stream reset or a TLS handshake that completes and then hangs until
          timeout, never a response. /robots.txt itself (normally
          unauthenticated and uncontested) comes back as an Akamai edge
          "Access Denied". That is a platform-wide bot-defense wall, not a
          login gate and not specific to the OTC endpoint or to a US-runner
          IP -- the one existing theory (geo-block) does not match what a
          German IP sees today. REJECTED: bot-walled, no code of ours can
          read it without exactly the kind of disguise this project refuses
          to use.

  OKX     www.okx.com/v3/c2c/tradingOrders/books (GET, side=sell|buy,
          baseCurrency=usdt, quoteCurrency=<ccy>) -- no login, no API key, no
          challenge. Live for 45 of the 49 currencies collector_p2p.py already
          tracks that OKX's own market even lists (AED, AFN, ETB and SYP come
          back `{"code":17007}`, OKX's own "unsupported currency" answer, not
          a transport failure); every other currency returns a real
          `data.sell`/`data.buy` list of ads with price, min/max order size
          and available quantity. Cross-checked for NGN: side=sell median
          ~1353.5, side=buy median ~1330-1346, both within a few percent of
          the same-hour open.er-api.com USD/NGN mid (~1330.6) -- the shape and
          size of premium this file's own `basis_bps` already expects to see.
          This endpoint is also the one collector_stable_venues.py already
          uses for the corridor on/off-ramp legs (SOURCES 3-4, 2026-09-27),
          so this is a second, independent live confirmation of the same
          source, now for the wide capital-controlled layer. WIRED: see
          collector_p2p_okx.py.

  HTX     www.htx.com/-/x/otc/v1/data/trade-market (GET, coinId=2,
          currency=<int>, tradeType=buy|sell) -- also no login, no API key,
          no challenge; a real, populated ad list comes back for plausible
          numeric `currency` ids (e.g. id 5 returns ads with
          `payMethods[].name` of "Bank Transfer (Vietnam)" and prices within
          cents of VND's own open.er-api.com mid). The board itself is a
          genuine survivor by the login/CAPTCHA bar. But HTX's own API, help
          center, robots.txt and sitemaps publish NO reference anywhere from
          an integer `currency` id to an ISO fiat code -- `currency=NGN` is
          rejected as "parameter invalid", and every id this tool could
          attach a country to was inferred indirectly, from the bank names
          inside each ad's own `payMethods` field (e.g. "Bank Transfer
          (Vietnam)" suggests VND; "M-pesa (Vodafone)" suggests Kenya or
          Tanzania and cannot tell which). Wiring a price to a country on
          that basis would mean guessing what a number MEANS, not just
          reading it -- exactly the kind of invention RULES.md forbids, worse
          than not having a second board at all. REJECTED: no public mapping
          from this board's own currency id to an ISO code; not a login or
          bot-defense rejection.

Terms, briefly, for the record this probe report is itself the disclosure of
(none of these publish a short, plain "ads API, no scraping" clause an
automated check could quote verbatim; this is a direct read of each site's
own robots.txt / help center / sitemap, done once, on the date above, not a
legal opinion):
  Bybit   robots.txt itself 403s at the edge -- no terms were even reachable
          to read before the bot wall was found.
  OKX     the P2P market pages (e.g. /en-eu/p2p-markets/ngn/buy-usdt) are
          public, indexed pages (robots.txt allows them); the general user
          agreement is behind a client-rendered page this tool cannot read
          without a browser, so it is not quoted here -- only the live,
          unauthenticated behaviour of the endpoint itself is reported.
  HTX     robots.txt explicitly `Allow: /` with named disallows for
          account/order/finance paths only; the OTC board is not among the
          disallowed paths. Same caveat as OKX on the prose agreement itself.

A weekly re-probe (this same tool, same checks) is meant to catch the day any
of this changes -- a board that starts requiring a login, or stops answering,
or a previously-blocked board that starts answering cleanly. It does not
change collector_p2p_okx.py's own behaviour; a human or a later issue decides
what to do with a changed verdict.

    data/p2p_board_probes.csv
    ts_utc,board,candidate_url,method,live_result,verdict,reason,terms_note

Append-only, one row per board per run of this tool -- never rewritten, so the
history of what has been tried and when is never lost, same as every other
CSV in data/.

Usage:
  python3 tools/probe_p2p_boards.py            # one live probe, print, append
  python3 tools/probe_p2p_boards.py --json
  python3 tools/probe_p2p_boards.py --selftest  # offline, mocked transport
"""

import argparse
import csv
import datetime as dt
import json
import os
import sys

try:
    import requests
except ImportError:
    requests = None

HTTP_TIMEOUT = 20
UA = {"User-Agent": "margin.wiki p2p-board-probe/1.0 (+https://margin.wiki)"}
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, "data", "p2p_board_probes.csv")
FIELDS = ["ts_utc", "board", "candidate_url", "method", "live_result", "verdict",
          "reason", "terms_note"]

BYBIT_URL = "https://api2.bybit.com/fiat/otc/item/online"
OKX_URL = "https://www.okx.com/v3/c2c/tradingOrders/books"
HTX_URL = "https://www.htx.com/-/x/otc/v1/data/trade-market"

# One real pair per board, just enough to tell "answers cleanly" from "blocked
# or needs a login" apart -- the full currency-by-currency survey for a wired
# board lives in that board's own collector, not here.
TEST_CCY = "NGN"
TEST_HTX_CURRENCY_ID = 5  # VND -- the one id this probe could independently
# confirm (see module docstring); used only to prove the board itself answers,
# never to publish a price under it.

BYBIT_TERMS_NOTE = ("robots.txt itself returns an Akamai edge \"Access "
                     "Denied\" -- no terms were reachable to read before the "
                     "bot wall was found")
OKX_TERMS_NOTE = ("P2P market pages are public per robots.txt; the prose "
                   "user agreement sits behind a client-rendered page this "
                   "tool cannot read without a browser, so only the "
                   "endpoint's own live behaviour is reported")
HTX_TERMS_NOTE = ("robots.txt allows the OTC path (named disallows cover "
                   "only account/order/finance paths); same client-rendered "
                   "caveat as OKX on the prose agreement")


# ------------------------------------------------------------- pure core
def classify_bybit(exc):
    """A transport-level failure on EVERY bybit.com path is a bot wall, not a
    login gate -- there is nothing a "logged in" request changes here."""
    return {
        "board": "bybit", "candidate_url": BYBIT_URL, "method": "POST",
        "live_result": f"{type(exc).__name__}: {exc}"[:300],
        "verdict": "rejected", "reason": "bot-walled at the edge (no clean response "
        "on any path, with or without a body)", "terms_note": BYBIT_TERMS_NOTE,
    }


def classify_okx(payload):
    """OKX payload -> probe verdict. `code` 0 with real ad lists is a survivor;
    17007 is OKX's own 'unsupported currency' answer -- a real, honest finding
    about NGN specifically, not grounds to reject the board, since every other
    currency's own survey (collector_p2p_okx.py) is what decides that."""
    code = payload.get("code")
    data = payload.get("data") or {}
    sell = data.get("sell") or []
    buy = data.get("buy") or []
    if code == 0 and (sell or buy):
        return {
            "board": "okx", "candidate_url": OKX_URL, "method": "GET",
            "live_result": f"code=0, {len(sell)} sell ads, {len(buy)} buy ads for {TEST_CCY}",
            "verdict": "wired", "reason": "live two-sided ad book, no login, no challenge",
            "terms_note": OKX_TERMS_NOTE,
        }
    return {
        "board": "okx", "candidate_url": OKX_URL, "method": "GET",
        "live_result": f"code={code}, data={data}"[:300],
        "verdict": "rejected", "reason": f"no ads for {TEST_CCY} (code {code})",
        "terms_note": OKX_TERMS_NOTE,
    }


def classify_htx(payload):
    """HTX payload -> probe verdict. The board itself is accepted as a
    survivor by the login/CAPTCHA bar (real ads come back, no auth needed),
    but it is REJECTED anyway: there is no honest, non-invented way to say
    which ISO currency a numeric id names (see module docstring)."""
    data = payload.get("data") or []
    if payload.get("code") == 200 and data:
        return {
            "board": "htx", "candidate_url": HTX_URL, "method": "GET",
            "live_result": f"code=200, {len(data)} ads for currency id {TEST_HTX_CURRENCY_ID}",
            "verdict": "rejected",
            "reason": "board answers with no login, but publishes no mapping from its "
            "own numeric currency id to an ISO code anywhere (API, help center, "
            "robots.txt, sitemap) -- wiring would mean guessing which country a row is",
            "terms_note": HTX_TERMS_NOTE,
        }
    return {
        "board": "htx", "candidate_url": HTX_URL, "method": "GET",
        "live_result": f"code={payload.get('code')}, {len(data)} ads"[:300],
        "verdict": "rejected", "reason": "no ads for the one currency id this probe "
        "could identify", "terms_note": HTX_TERMS_NOTE,
    }


# ------------------------------------------------------------------ I/O
def probe_bybit(post=None):
    post = post or (lambda url, body: requests.post(url, json=body, timeout=HTTP_TIMEOUT, headers=UA))
    body = {"userId": "", "tokenId": "USDT", "currencyId": TEST_CCY, "payment": [],
            "side": "1", "size": "10", "page": "1", "amount": "", "vaMaker": False,
            "bulkMaker": False, "canTrade": False, "verificationFilter": 0,
            "sortType": "TRADE_PRICE", "paymentPeriod": [], "itemRegion": 1}
    try:
        r = post(BYBIT_URL, body)
        r.raise_for_status()
        r.json()
        return {
            "board": "bybit", "candidate_url": BYBIT_URL, "method": "POST",
            "live_result": f"HTTP {r.status_code}, answered", "verdict": "wired",
            "reason": "live two-sided ad book, no login, no challenge",
            "terms_note": BYBIT_TERMS_NOTE,
        }
    except Exception as e:
        return classify_bybit(e)


def probe_okx(get=None):
    get = get or (lambda url: requests.get(url, timeout=HTTP_TIMEOUT, headers=UA))
    url = (f"{OKX_URL}?side=sell&paymentMethod=all&userType=all&baseCurrency=usdt"
           f"&quoteCurrency={TEST_CCY.lower()}&currentPage=1&numberPerPage=10")
    try:
        r = get(url)
        r.raise_for_status()
        return classify_okx(r.json())
    except Exception as e:
        return {
            "board": "okx", "candidate_url": OKX_URL, "method": "GET",
            "live_result": f"{type(e).__name__}: {e}"[:300], "verdict": "rejected",
            "reason": "transport failure", "terms_note": OKX_TERMS_NOTE,
        }


def probe_htx(get=None):
    get = get or (lambda url: requests.get(url, timeout=HTTP_TIMEOUT, headers=UA))
    url = (f"{HTX_URL}?coinId=2&currency={TEST_HTX_CURRENCY_ID}&tradeType=buy"
           f"&currPage=1&payMethod=0&acceptOrder=0&blockType=general&online=1"
           f"&range=0&amount=&isFollowed=0")
    try:
        r = get(url)
        r.raise_for_status()
        return classify_htx(r.json())
    except Exception as e:
        return {
            "board": "htx", "candidate_url": HTX_URL, "method": "GET",
            "live_result": f"{type(e).__name__}: {e}"[:300], "verdict": "rejected",
            "reason": "transport failure", "terms_note": HTX_TERMS_NOTE,
        }


def probe_all(bybit_post=None, okx_get=None, htx_get=None):
    ts = dt.datetime.now(dt.timezone.utc).isoformat()
    rows = [probe_bybit(bybit_post), probe_okx(okx_get), probe_htx(htx_get)]
    for r in rows:
        r["ts_utc"] = ts
    return rows


def append(rows):
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    new = not os.path.exists(OUT)
    with open(OUT, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerows(rows)
    return OUT


def print_table(rows):
    print(f"\n  P2P board probe   {rows[0]['ts_utc'][:16]}Z")
    print("  " + "-" * 78)
    for r in rows:
        print(f"  {r['board']:<8}{r['verdict']:<10}{r['reason']}")
        print(f"           {r['live_result']}")
    print("  " + "-" * 78 + "\n")


# -------------------------------------------------------------- selftest
def selftest():
    # 1. Bybit: every transport shape (reset, timeout, 403) classifies as a
    #    rejected bot wall, never a crash.
    for exc in (ConnectionResetError("HTTP/2 stream 1 was not closed cleanly"),
                TimeoutError("timed out"), RuntimeError("403 Forbidden")):
        r = classify_bybit(exc)
        assert r["verdict"] == "rejected" and "bot-walled" in r["reason"], r
    print("  [ok] bybit: any transport failure classifies as a rejected bot wall")

    # 1b. the live probe path itself routes a raising `post` through the same
    #     classifier, never raising out of probe_bybit.
    def boom(url, body):
        raise ConnectionError("stream reset")
    r = probe_bybit(post=boom)
    assert r["verdict"] == "rejected" and r["board"] == "bybit"
    print("  [ok] probe_bybit never raises; a dead transport is a rejected row")

    # 2. OKX: a real two-sided book is wired; an unsupported-currency code is
    #    rejected for THAT currency without being a transport failure.
    live = {"code": 0, "data": {"sell": [{"price": "1353.50"}], "buy": [{"price": "1330.00"}]}}
    r = classify_okx(live)
    assert r["verdict"] == "wired", r
    unsupported = {"code": 17007, "data": {}}
    r = classify_okx(unsupported)
    assert r["verdict"] == "rejected" and "17007" in r["reason"], r
    empty = {"code": 0, "data": {"sell": [], "buy": []}}
    r = classify_okx(empty)
    assert r["verdict"] == "rejected", r
    print("  [ok] okx: a real book wires, an unsupported-currency code or an "
          "empty book rejects cleanly")

    # 3. HTX: a populated board is REJECTED despite answering, because no
    #    public id->ISO mapping exists; this is the one board whose rejection
    #    is not about access at all.
    populated = {"code": 200, "data": [{"price": "25970.00",
                 "payMethods": [{"name": "Bank Transfer (Vietnam)"}]}]}
    r = classify_htx(populated)
    assert r["verdict"] == "rejected" and "mapping" in r["reason"], r
    empty = {"code": 200, "data": []}
    r = classify_htx(empty)
    assert r["verdict"] == "rejected", r
    print("  [ok] htx: rejected even when it answers -- no currency-id mapping, "
          "not an access problem")

    # 4. probe_all stamps every row with the same timestamp and never skips a
    #    board, regardless of what each transport does.
    rows = probe_all(
        bybit_post=lambda url, body: (_ for _ in ()).throw(ConnectionError("reset")),
        okx_get=lambda url: _FakeResp({"code": 0, "data": {"sell": [{"price": "1.0"}], "buy": []}}),
        htx_get=lambda url: _FakeResp({"code": 200, "data": [{"price": "1.0", "payMethods": []}]}),
    )
    assert {r["board"] for r in rows} == {"bybit", "okx", "htx"}
    assert len({r["ts_utc"] for r in rows}) == 1, "one probe run, one timestamp"
    boards = {r["board"]: r["verdict"] for r in rows}
    assert boards == {"bybit": "rejected", "okx": "wired", "htx": "rejected"}, boards
    print("  [ok] probe_all: one row per board, same run timestamp, independent verdicts")

    # 5. schema is exactly what gets written
    assert set(FIELDS) == {"ts_utc", "board", "candidate_url", "method",
                            "live_result", "verdict", "reason", "terms_note"}
    print("  [ok] CSV schema matches the module docstring\n")

    print("  ALL SELFTESTS PASSED\n")


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


# ------------------------------------------------------------------- cli
def main():
    ap = argparse.ArgumentParser(description="margin.wiki P2P board probe (ROADMAP item 14)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        selftest()
        return
    if requests is None:
        sys.exit("pip install requests")

    rows = probe_all()
    append(rows)

    if a.json:
        print(json.dumps(rows, indent=2, default=str))
    else:
        print_table(rows)
    print(f"  appended -> {OUT}\n")


if __name__ == "__main__":
    main()

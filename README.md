# SEA Corridor Monitor — v0 (SGD → PHP)

**The observable cost of moving money SGD → PHP.** Every rail is normalized to one
number: *send N SGD, how many PHP actually land.* The differentiated rail is the
stablecoin path, computed by **walking real order books** — so the off-ramp slippage
on a thin PHP book (usually the biggest cost in the chain, and the one the
"ten-cent transfer" pitch hides) shows up as a real number, not a modeled spread.

## The thesis (and the honest limitation)

The retail path is **fully observable**. Coins.ph and Independent Reserve publish
their order books and their trading/withdrawal fees, so a consumer's true all-in
SGD→USDT→PHP cost is computable from real data — including the off-ramp spread that
everyone's marketing quietly omits.

What's **proprietary** is the enterprise layer: what Nium, Thunes, or a Circle payout
partner charges a business client is negotiated and invisible. You can't monitor it,
and this tool doesn't pretend to. That opacity is a stated limitation, not a gap —
naming it correctly is itself the signal that you understand how B2B payout pricing
actually works.

## Run it

```bash
pip install requests
python3 corridor_monitor.py                 # run once, print table, append snapshot
python3 corridor_monitor.py --amount 5000   # different notional
python3 corridor_monitor.py --json          # machine-readable (for a dashboard)
python3 corridor_monitor.py --selftest      # offline math check, no network
```

Each run appends one row per rail to `snapshots.csv` — that history file *is* the
seed for the live dashboard (spread-over-time chart).

> Built and math-verified in a network-restricted sandbox, so the live endpoints
> haven't been hit end-to-end. Expect to tweak the parsers against the first real
> responses — see "Known unknowns."

## The rails

**1. Wise comparison API** — `api.wise.com/v1/comparisons`. One call returns Wise
*and* competing providers (banks, Remitly, often Western Union) with real rate, fee,
and received amount — a de facto aggregator that covers the fiat rails with no
scraping. This is deliberately the *commodity* half; the data exists elsewhere.
Parser: `parse_wise_quotes()`.

**2. Stablecoin round-trip (the differentiated rail)** — SGD → USDT on the SG
on-ramp → USDT → PHP on the PH off-ramp, priced off **real depth**:

- **SG on-ramp**: Independent Reserve `GetOrderBook` (public, keyless). We consume
  the sell side to buy USDT with SGD for the full notional.
- **PH off-ramp**: Coins.ph `depth` (public, Binance-style). We consume the bid side
  to sell USDT for PHP — walking down the book, so slippage on a thin book is real.

The engine (`walk_asks_spend`, `walk_bids_sell`) returns the *actual* fill for the
notional and flags a book that's too thin to fill. The rail reports
`offramp_slippage_pct` = the gap between the average fill price and the top-of-book
bid — the headline cost.

Fees are **published, observable** numbers, exposed as knobs (not the hidden spread —
that now comes from the book):

```bash
--stable USDT               # bridge coin (USDT default; USDC if both venues list it)
--on-taker 0.005            # SG on-ramp taker fee (Independent Reserve ~0.5%)
--off-taker 0.0025          # PH off-ramp taker fee (Coins.ph Pro ~0.25%)
--network-fee-stable 1.0    # stablecoin withdrawal (TRC20 ~1 USDT)
--php-withdraw 0.0          # InstaPay/PESONet cash-out (often free)
```

If either book can't be fetched, the rail degrades to a **clearly labeled** modeled
fallback (`Stablecoin round-trip (MODELED fallback)`) so a model never masquerades
as observed data.

**Benchmark** — mid-market SGD→PHP from a keyless FX API. Cost is reported as
**margin vs mid** (what the rail skims off mid-market) and **spread vs best** (gap to
the cheapest rail in the run).

## Calibrate with real money (do this once)

The line that beats any amount of scraping in an interview: *"I pushed my own money
through and the monitor matched."* Send S$100–200 through two or three rails once,
record what actually lands, and adjust the fee knobs until the monitor reproduces it.
Total cost ~S$15 in fees; it turns the tool from "plausible" into "verified against
ground truth."

## Design notes

- **Per-rail isolation**: one rail failing logs a warning; the run continues.
- **Pure, tested core**: `walk_asks_spend`, `walk_bids_sell`, `stablecoin_rail`,
  `parse_wise_quotes`, `normalize` take plain data and are covered by `--selftest`
  (including a slippage case and a thin-book exhaustion case) — verifiable offline.

## Known unknowns (check on first live run)

- Independent Reserve currency codes are capitalized (`Usdt`, `Sgd`) and the response
  splits `BuyOrders`/`SellOrders`; parser handles this but verify field names.
- Coins.ph depth symbol format (`USDTPHP`) and whether public depth needs no key.
- Wise comparison endpoint shape / whether it needs a header for your IP.
- Some venues may be geo-restricted from your IP → the rail falls back with a warning.

## Roadmap to the live dashboard

1. **Add PDAX as a second PH off-ramp** — cross-check Coins.ph depth; report the
   better of the two (real arbitrage picks the deeper book).
2. **Add SGD → IDR** — same structure; swap the off-ramp venue/symbol.
3. **Add the XSGD rail** — StraitsX XSGD mint (~1:1) → XSGD/USDC swap (gas + slippage)
   → off-ramp.
4. **Schedule hourly** — cron / scheduled task appending to `snapshots.csv`.
5. **Dashboard** — static site (Vercel / GitHub Pages) reading a JSON the hourly job
   commits; Chart.js for spread-over-time. `--json` output is already shaped for it.
   No backend → the version that gets LinkedIn traction.

## ToS / caution

All endpoints used are public market-data reads; rate-limit politely and cache.
Avoid scraping Western Union's quote flow directly (ToS-sensitive) — the Wise
aggregator already surfaces it. This tool reports costs; it does not move money or
execute anything.

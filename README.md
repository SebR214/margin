# margin.wiki

**What a cross-border transfer actually costs, decomposed — and when the
stablecoin rail wins.**

The public argument about stablecoin payments measures the wrong thing. Moving
value between two wallets is genuinely near-free. But a transfer that starts in a
bank account and ends in one has to pass through two doors — an on-ramp and an
off-ramp — and that is where essentially all of the cost sits.

Measured live on the SGD→PHP corridor, S$5,000:

```
on-ramp basis (USDT vs USD mid, SG)   −12.0 bps   ← a gain
on-ramp taker fee                     +50.0
network fee (1 USDT)                   +2.6       ← the entire public narrative
off-ramp basis (USDT vs USD mid, PH)  +29.2
off-ramp taker fee                    +15.0
                                      ───────
                                       84.8 bps   vs Wise at 65.9 bps
```

(Fees verified against both venues' published schedules 2026-08-10 — IR 0.50%
default tier, Coins.ph Pro 0.15% VIP0.)

The rail costs 2.6 bps. The doors cost 82. And the answer flips on execution:
the same books, the same second, priced as a maker instead of a taker, come to
**19.8 bps** — three times better than the incumbent (an upper bound: it
assumes zero maker fees, which neither venue's published schedule actually
offers — see METHODOLOGY.md). That gap is why large flow uses stablecoins and
retail does not benefit, and it has nothing to do with the blockchain.

This repo collects the data behind that argument, hourly. See
[METHODOLOGY.md](METHODOLOGY.md) for what is measured, what is assumed, and what
cannot be seen.

## Run order — do not skip step 1

```bash
pip install -r requirements.txt

python3 collector.py --selftest   # offline; validates the math against real captured payloads
python3 collector.py --verify     # ONE LIVE PULL. prints the waterfall, writes nothing.
python3 collector.py              # appends a sample to data/samples.csv
```

`--verify` is the step that matters. A previous version of this collector was
pushed to a scheduled job without it and pointed at `api.coins.ph`, a hostname
that does not resolve. It ran hourly for 34 days and recorded nothing but DNS
errors, because nothing ever went red. Run `--verify`, read the numbers, confirm
they are sane, *then* enable the schedule.

## Then start the clock

```bash
git init && git add -A && git commit -m "collector"
gh repo create margin-wiki --public --source=. --push
```

Actions → enable workflows → run **collect** manually once → confirm a new row
lands in `data/samples.csv`. After that it runs at :17 past every hour.

History is the only part of this that cannot be rebuilt. The site can be ugly for
months; the collector cannot be down for a week.

## What accumulates

One row per (hour × corridor × notional), carrying the full decomposition —
both bases, both execution regimes, book depth, the incumbent baseline at the
same instant, and the fee configuration in force when the row was written, so
history stays interpretable when a venue changes its schedule.

## Status

- [x] SGD→PHP collector, size ladder S$200 → S$50,000
- [x] Verify taker fee schedules against venue fee pages (2026-08-10: IR 50 bps confirmed; Coins.ph corrected 25 → 15 bps)
- [ ] One week of history
- [ ] Write-up: the taker/maker crossover
- [ ] Write-up: why stablecoins are worst at remittance sizes (~156 bps at S$200)
- [ ] Front end

# margin.wiki

Every hour, margin.wiki prices a dollar in over 50 countries against the official exchange rate, and prices sending money on 11 routes with every fee we can measure. The site is at [margin.wiki](https://margin.wiki), served from this repository's `main` branch by GitHub Pages.

Every figure on this page was counted from the files on `main` on 12 Oct 2026, around 03:07 UTC. The counts change every hour.

## What it measures

**A dollar in over 50 countries.** For each country we take the price people pay for a dollar stablecoin in local money, and compare it with the official rate. The gap is the number. A country shows no price for an hour when there is not enough evidence, and the page says why. At the 02:00 UTC hour on 12 Oct, 47 of the 60 had a price and 13 did not.

Where the price comes from, in this order: exchange order books, then broker quotes, then offers between people on Binance and OKX. The rules are in [METHODOLOGY.md](METHODOLOGY.md). The index is at version 1.5 (`index_version` in `data/index_latest.json`).

**Sending money on 11 routes.** United States to Argentina, India, Nigeria, Brazil, Mexico and the Philippines, Singapore to India and the Philippines, Australia to India and the Philippines, and New Zealand to the Philippines, each at five amounts in the sending currency: 200, 1,000, 5,000, 25,000 and 50,000. For each we price the transfer apps and sending it by stablecoin, and show how much less the person receiving gets than at the official rate.

## Where the data is

Everything the site shows is read from files in [`data/`](data/). It held 90 files and 14 folders on 12 Oct 2026. The main ones:

| File | What it holds | Rows on 12 Oct | First row |
|---|---|---|---|
| `data/basis.csv` | exchange order books and broker quotes | 46,237 | 10 Aug 2026 |
| `data/p2p_basis.csv` | Binance offers between people | 46,331 | 2 Sep 2026 |
| `data/p2p_okx.csv` | OKX offers between people | 10,865 | 3 Oct 2026 |
| `data/fx_rates.csv` | official exchange rates | 43,617 | 10 Sep 2026 |
| `data/samples.csv` | the stablecoin route, priced step by step | 23,770 | 10 Aug 2026 |
| `data/provider_quotes.csv` | transfer app quotes | 46,400 | 10 Sep 2026 |
| `data/index_hourly.csv` | the figure each country published, hour by hour | 33,622 | 10 Sep 2026 |

The published results are in `data/index_latest.json`, `data/countries/<CODE>.json` (one per country), `data/routes_hourly.json` and `data/findings.json`. The Sources page counts 65 sources.

CSV files are only ever appended to. A failed pull is a row with `source_ok=false`, never a filled-in guess. Prices a source reports from before we started are kept apart in `data/history/` and never feed a price.

## How collection runs

On GitHub Actions. [`collect.yml`](.github/workflows/collect.yml) runs about every 30 minutes: each run waits for the next slot and starts the next one itself, and a schedule at 17 and 47 minutes past the hour restarts the chain if it has died. Each hour it pulls prices, writes the rows, then builds the published files and commits them to `main`. [`collector_watchdog.yml`](.github/workflows/collector_watchdog.yml) and [`watchdog.yml`](.github/workflows/watchdog.yml) check it from outside. A missed hour cannot be refilled, so nothing in `collector*.py` or `collect.yml` merges without a person.

Checks run on every pull request ([`checks.yml`](.github/workflows/checks.yml)). Work is tracked in Linear, not in GitHub issues.

## Check a number

Each price on a country page links to the file it came from. [METHODOLOGY.md](METHODOLOGY.md) says what is measured, what is assumed and what cannot be seen. The Sources page lists every source and the days it answered.

## Run it yourself

```bash
pip install -r requirements.txt
python3 collector.py --selftest   # offline checks against captured payloads
python3 collector.py --verify     # one live pull, prints the result, writes nothing
python3 collector.py              # appends a sample to data/samples.csv
```

Run `--verify` and read the numbers before you schedule anything: a collector once ran for 34 days against a hostname that did not resolve and recorded only errors.

Not switched on: a public API in the server folder (it needs a DNS record, SEB-213).

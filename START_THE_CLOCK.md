# Start the clock — push to GitHub, collection begins

History is the moat and it can't be backfilled. These steps get the hourly
collector running on GitHub's free runners. ~5 minutes.

## 1. Verify locally first (needs internet — won't work in a restricted sandbox)

```bash
pip install -r requirements.txt
python corridor_monitor.py --selftest            # offline math check, should all pass
python corridor_monitor.py --offramp-snapshot    # one real pull; prints the depth table
```

That last command is also the first reality check: confirm Coins.ph returns a
`USDTPHP` book and the numbers look sane (see "First-run checks" below).

## 2. Create the repo and push

```bash
git init && git add -A && git commit -m "corridor monitor: off-ramp depth collector"
gh repo create corridor-monitor --private --source=. --push
# or make a repo in the GitHub UI and: git remote add origin <url> && git push -u origin main
```

## 3. Turn the clock on

- In the repo: **Actions** tab → enable workflows if prompted.
- Open **collect-offramp-depth** → **Run workflow** (the `workflow_dispatch` button)
  to fire the first run now instead of waiting for the top of the hour.
- Confirm it committed a new row to `data/offramp_snapshots.csv`. From then on it
  runs hourly, unattended.

## First-run checks (the things we couldn't verify offline)

- **Coins.ph symbol/shape** — expects `USDTPHP` depth as `{"bids":[[price,qty],...]}`.
  If it 404s or differs, adjust `fetch_coins_book` / `parse_coins_book`.
- **Depth limit** — we request `limit=200`. If large notionals show `filled_fully=false`
  even when the market is deep, the book is being truncated; raise the limit.
- **`notional_stable`** — sanity-check the USD/SGD conversion (≈0.74 USD per SGD).
- **Geo** — if GitHub's runner IP is blocked by Coins.ph, `source_ok` logs false;
  move the job to a different runner region or a small VPS.

## Notes

- GitHub disables scheduled workflows after 60 days of **no repo activity** — the
  hourly commits themselves count as activity, so an actively-collecting repo stays on.
- Adding a venue (PDAX, etc.) later just adds rows under the same schema — it never
  resets the history already collected. Register it in `OFFRAMP_VENUES`.
- Frontend/dashboard is deliberately deferred. The only thing that matters now is
  that the CSV grows every hour.

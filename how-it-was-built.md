# Plain code makes every number. AI only helps build the site.

Prices from the 11:00 UTC hour, 1 Nov.

The collector and the checks are plain code. The builder uses AI to write some of the code, and one person writes the rest.

[See what it costs and what has gone wrong →](https://margin.wiki/machine-room.md)

## Each part has one job and cannot do the others'

The builder can't approve its own work. No AI ever calculates a number.

- Collector · Every hour · Pulls prices from exchanges, transfer apps and official rates and saves them to the data files. Plain code, no AI.
- Builder · Up to 3 jobs a day · Takes the top ready job from a list a person writes and builds it as new files. Uses AI. It can't change existing price collection, pages or methods. It and every other model call together can spend at most $20 a month.
- Checks · Every change · Run tests on every change, recalculate published numbers from the saved files and merge the change when every test is green. Plain code, no AI. A change to how prices are collected that adds nothing new waits for a person.
- Person · As needed · Sets the direction, holds the money and passwords, and writes what the builder skips, using AI sessions of their own.

## What we've learned running them

- A settings change spent $10 in 20 minutes It moved the agents onto an account billed for each use, instead of the account with a flat monthly fee. The two accounts are now kept in separate files so they cannot be mixed up.

[Every incident, and the builder week by week →](https://margin.wiki/machine-room.md)

## Collected fresh every hour

Each line is a step of the latest hourly run, with the time it finished. Any problem shows here.

| Time | Check | Detail |
| --- | --- | --- |
| 11:00 | 51 of 54 countries have a price. The rest show none this hour, never a guess. |  |
| 11:00 | 11 of 11 routes priced this hour. |  |
| 10:07 | 50 of our figures recomputed from raw prices. Matches mean the data backs them. | 49 of 50 matched |
| 11:15 | These sources did not answer this hour: CriptoYa · Buenbit. |  |

How the last 48 hours went

<https://margin.wiki/data/manifest_latest.json>

## The record grew as new sources and routes came in

623,493 prices stored

Exchanges' own earlier prices reach back to 3 Jan 2011, so some charts predate our record.

<https://margin.wiki/data/record_daily.json>
<https://margin.wiki/data/record_milestones.json>

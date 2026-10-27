# Four agents run this site. Two of them use AI.

Prices from the 00:00 UTC hour, 27 Oct.

The collector gathers prices every hour. The scout picks one job a week from lists the code makes, such as countries with only one source. The builder writes the code for that job. The reviewer checks every change before it goes live. The scout and the builder use AI. The collector and the reviewer are plain code, so no AI ever produces a number on this site. One person sets the direction and holds the money and passwords, and the agents can spend at most $20 a month.

## Each agent has one job and cannot do the others'

The builder can't approve its own work. The scout never writes code. No AI ever calculates a number.

- Collector · Every hour · Pulls prices from exchanges, transfer apps and official rates and saves them to the data files. Plain code, no AI.
- Scout · Once a week · Picks the next job from lists the code makes: countries with one source, sources that disagree, claims that stopped holding. Uses AI. Every number it writes is checked against the data files before it's posted.
- Builder · One job at a time · Writes the code for the scout's job in one go, then stops. Uses AI. It can't change agent code, checks or how prices are collected.
- Reviewer · Every change · Runs checks on every change before it goes live, and recalculates published numbers from the saved files. Plain code, no AI. Changes to how prices are collected wait for a person.

## What we've learned running them

- A settings change spent $10 in 20 minutes It moved the agents onto an account billed for each use, instead of the account with a flat monthly fee. The two accounts are now kept in separate files so they cannot be mixed up.

[The full story: running agents that can't be trusted →](https://margin.wiki/agent-incidents.html)

## Collected fresh every hour

Each line is a step of the latest hourly run, with the time it finished. Any problem shows here.

| Time | Check | Detail |
| --- | --- | --- |
| 00:00 | 47 of 54 countries have a price. The rest show none this hour, never a guess. |  |
| 00:00 | 11 of 11 routes priced this hour. |  |
| 23:23 | 50 of our figures recomputed from raw prices. Matches mean the data backs them. | 49 of 50 matched |
| 00:15 | These sources did not answer this hour: CriptoYa · Buenbit. |  |

How the last 48 hours went

<https://margin.wiki/data/manifest_latest.json>

## The record grew as new sources and routes came in

580,472 prices stored

Exchanges' own earlier prices reach back to 3 Jan 2011, so some charts predate our record.

<https://margin.wiki/data/record_daily.json>
<https://margin.wiki/data/record_milestones.json>

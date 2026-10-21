<!-- margin.wiki machine view, hour 2026-10-21T09:00:00+00:00 -->

# Four agents run this site. Two of them use AI.

The collector gathers prices every hour. The scout picks one job a week from lists the code makes, such as countries with only one source. The builder writes the code for that job. The reviewer checks every change before it goes live. The scout and the builder use AI. The collector and the reviewer are plain code, so no AI ever produces a number on this site. One person sets the direction and holds the money and passwords, and the agents can spend at most $20 a month.

<https://margin.wiki/data/cycle_log.json>
<https://margin.wiki/data/machine_room_meters.json>
<https://margin.wiki/data/commits_recent.json>
<https://margin.wiki/data/record_daily.json>
<https://margin.wiki/data/record_milestones.json>
<https://margin.wiki/data/corridor_window.json>
<https://margin.wiki/data/manifest_latest.json>

## Each agent has one job and cannot do the others'

The builder can't approve its own work. The scout never writes code. No AI ever calculates a number.

- Collector · Every hour · Pulls prices from exchanges, transfer apps and official rates and saves them to the data files. Plain code, no AI.
- Scout · Once a week · Picks the next job from lists the code makes: countries with one source, sources that disagree, claims that stopped holding. Uses AI. Every number it writes is checked against the data files before it's posted.
- Builder · One job at a time · Writes the code for the scout's job in one go, then stops. Uses AI. It can't change agent code, checks or how prices are collected.
- Reviewer · Every change · Runs checks on every change before it goes live, and recalculates published numbers from the saved files. Plain code, no AI. Changes to how prices are collected wait for a person.

<https://margin.wiki/data/cycle_log.json>
<https://margin.wiki/data/machine_room_meters.json>
<https://margin.wiki/data/commits_recent.json>
<https://margin.wiki/data/record_daily.json>
<https://margin.wiki/data/record_milestones.json>
<https://margin.wiki/data/corridor_window.json>
<https://margin.wiki/data/manifest_latest.json>

## What we've learned running them

- A settings change spent $10 in 20 minutes It moved the agents onto an account billed for each use, instead of the account with a flat monthly fee. The two accounts are now kept in separate files so they cannot be mixed up.

[The full story: running agents that can't be trusted →](https://margin.wiki/agent-incidents.html)

<https://margin.wiki/data/cycle_log.json>
<https://margin.wiki/data/machine_room_meters.json>
<https://margin.wiki/data/commits_recent.json>
<https://margin.wiki/data/record_daily.json>
<https://margin.wiki/data/record_milestones.json>
<https://margin.wiki/data/corridor_window.json>
<https://margin.wiki/data/manifest_latest.json>

## Collected fresh every hour

Each line is a step of the latest hourly run, with the time it finished. Any problem shows here.

|  |  |  |
| --- | --- | --- |
| 09:00 | 50 of 60 countries have a price. The rest show none this hour, never a guess. |  |
| 09:00 | 7 of 7 routes priced this hour. |  |
| 08:06 | 50 of our figures recomputed from raw prices. Matches mean the data backs them. | 50 of 50 matched |
| 09:11 | These sources did not answer this hour: CriptoYa:buenbit, instarem.com. |  |

How the last 48 hours went

<https://margin.wiki/data/cycle_log.json>
<https://margin.wiki/data/machine_room_meters.json>
<https://margin.wiki/data/commits_recent.json>
<https://margin.wiki/data/record_daily.json>
<https://margin.wiki/data/record_milestones.json>
<https://margin.wiki/data/corridor_window.json>
<https://margin.wiki/data/manifest_latest.json>

## The record grew as new sources and routes came in

494,356 prices stored

Exchanges' own earlier prices reach back to 3 Jan 2011, so some charts predate our record.

[Watch live prices arrive as they are checked →](https://margin.wiki/tape.html)

<https://margin.wiki/data/cycle_log.json>
<https://margin.wiki/data/machine_room_meters.json>
<https://margin.wiki/data/commits_recent.json>
<https://margin.wiki/data/record_daily.json>
<https://margin.wiki/data/record_milestones.json>
<https://margin.wiki/data/corridor_window.json>
<https://margin.wiki/data/manifest_latest.json>

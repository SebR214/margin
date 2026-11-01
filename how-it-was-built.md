# Plain code makes every number. AI only helps build the site.

Prices from the 16:00 UTC hour, 1 Nov.

The collector and the checks are plain code. The builder uses AI to write some of the code, and one person writes the rest.

|  |
| --- |
| $5.23 Spent on builds |
| 5 Builds merged |
| $1.05 Cost per merged build |
| 1 day Since the last merge |

Spent counts the builder's runs. Every model call together, since 7 Oct, comes to $7.31. All of it is held to $20 a month.

<https://margin.wiki/data/machine_room.json>

## Each part has one job and cannot do the others'

The builder can't approve its own work. No AI ever calculates a number.

| Part | How often | What it does |
| --- | --- | --- |
| Collector | Every hour | Pulls prices from exchanges, transfer apps and official rates and saves them to the data files. Plain code, no AI. |
| Builder | Up to 3 jobs a day | Takes the top ready job from a list a person writes and builds it as new files. Uses AI. It can't change existing price collection, pages or methods. It and every other model call together can spend at most $20 a month. |
| Checks | Every change | Run tests on every change, recalculate published numbers from the saved files and merge the change when every test is green. Plain code, no AI. A change to how prices are collected that adds nothing new waits for a person. |
| Person | As needed | Sets the direction, holds the money and passwords, and writes what the builder skips, using AI sessions of their own. |

## The record grew as new sources and routes came in

627,347 prices stored

Exchanges' own earlier prices reach back to 3 Jan 2011, so some charts predate our record.

<https://margin.wiki/data/record_daily.json>
<https://margin.wiki/data/record_milestones.json>

## Week by week

The builder tries a job, may open a change, and the change merges when the checks are green. A merge counts only if the files it added are not empty. Weeks run Monday to Sunday, UTC.

Tries and merges each week

| Week starting | Tries | Changes opened | Merged | Share merged | Cost |
| --- | --- | --- | --- | --- | --- |
| 26 Oct | 19 | 5 | 2 | 11% | $1.61 |
| 19 Oct | 17 | 6 | 3 | 18% | $3.62 |

<https://margin.wiki/data/machine_room.json>
<https://margin.wiki/data/aider_log.csv>
<https://margin.wiki/data/machine_room_prs.csv>

## What runs where

Every job runs on GitHub Actions. Times are Singapore time.

| Job | When | What it does | Last run |
| --- | --- | --- | --- |
| Builder | Every day at 13:07, 16:37, 21:07 | Builds the top ready job with AI and opens a change. | Succeeded (1 Nov 15:27 UTC) |
| Merge when green | After the checks finish on a change | Merges a change when every check is green. | Skipped (1 Nov 15:51 UTC) |
| Checks | On every change | Runs the tests and page checks a change must clear. | Succeeded (1 Nov 15:51 UTC) |
| Reader test | By hand | Compares two models reading the pages. Changes nothing. | Succeeded (5 Oct 09:28 UTC) |
| Collection | About every 30 minutes, each run starts the next | Collects prices, rebuilds the pages and saves the data. | Running (1 Nov 16:05 UTC) |
| Collection alarm | Every 30 minutes | Watches collection from outside and sends an alarm when it goes quiet. | Running (1 Nov 16:15 UTC) |
| Fee check | Day 1 of each month at 11:23 | Checks the fee tiers each month. | Succeeded (1 Nov 10:39 UTC) |
| History pull | By hand | Pulls older price history from public sources. Never feeds a price. | Succeeded (22 Oct 17:30 UTC) |
| Older builder | By hand | The older builder, run only by hand. | Succeeded (23 Oct 17:03 UTC) |
| Outside check | After each deploy of the site | Asks the live site what a search engine would ask. | Succeeded (1 Nov 15:49 UTC) |
| Board probe | Sundays at 11:11 | Re-checks which boards where people sell to each other are usable. | Succeeded (1 Nov 10:21 UTC) |
| Audit alarm | Every hour, at minutes 11, 41 | Sends an alarm when the audits or the builder's runner stop working. | Running (1 Nov 16:01 UTC) |
| writer | By hand |  | Failed (1 Nov 09:45 UTC) |

<https://margin.wiki/data/machine_room.json>
<https://margin.wiki/data/machine_room_meters.json>

## Incidents

Newest first. A gap in the data stays a gap.

28 to 31 Oct 2026

<https://margin.wiki/data/machine_room.json>

### Collection stopped for two days

What broke

A table of seller ads grew to 99.6 MB. GitHub refuses a file over 100 MB, so every save of new prices failed.

How long

The last stored hour was 28 Oct 20:00 UTC and the next was 31 Oct 04:00 UTC, 56 hours apart.

What was lost

Every hour in that gap. Missed hours stay missing and are never filled in.

What fixed it

The big tables now write one file a day. A size check fails the run before the save. One alarm now covers collection.

Changes

[719](https://github.com/SebR214/margin/pull/719), [720](https://github.com/SebR214/margin/pull/720)

31 Oct 2026

### Two tests turned the main branch red

What broke

Tests that read the real data files failed as the hours moved on, so checks on the main branch went red.

How long

Not recorded.

What was lost

Not recorded.

What fixed it

The gas test now uses fixed hours of its own. The research pieces are rebuilt before the claims check.

Changes

[734](https://github.com/SebR214/margin/pull/734), [736](https://github.com/SebR214/margin/pull/736)

25 to 27 Oct 2026

### Two builds merged with empty files

What broke

The builder opened changes whose new files were empty. The checks were green and the changes merged.

How long

The builder first stopped an empty result on 29 Oct.

What was lost

A finding retest and a new price source that were marked built and did nothing.

What fixed it

A merge now counts only if its files are not empty. This page counts that way.

Changes

[696](https://github.com/SebR214/margin/pull/696), [701](https://github.com/SebR214/margin/pull/701)

22 Oct 2026

### The builder rewrote lines it should not touch

What broke

In its first two changes the builder edited existing price code. One change would have altered the source link on every route. The other rewrote four existing entries.

How long

Both changes were closed by hand the same morning.

What was lost

Nothing. Neither change merged.

What fixed it

A check now refuses any change to an existing price collector. The builder tries again until its change only adds.

Changes

[629](https://github.com/SebR214/margin/pull/629), [632](https://github.com/SebR214/margin/pull/632), [640](https://github.com/SebR214/margin/pull/640)

Before 23 Sep 2026

### A key spent $10 in 20 minutes

What broke

A settings change put the key billed for each use where the flat-rate login belonged. Every agent run billed for each use.

How long

About 20 minutes.

What was lost

About $10 of credit.

What fixed it

The two keys now live in separate files, with a note where each is used saying why they must never be mixed.

[data/aider_log.csv](https://margin.wiki/data/aider_log.csv) · [data/agent_spend.csv](https://margin.wiki/data/agent_spend.csv) · [data/machine_room_prs.csv](https://margin.wiki/data/machine_room_prs.csv) · [data/index_hourly.csv](https://margin.wiki/data/index_hourly.csv) · [data/machine_room_meters.json](https://margin.wiki/data/machine_room_meters.json)

<https://margin.wiki/data/aider_log.csv>
<https://margin.wiki/data/agent_spend.csv>
<https://margin.wiki/data/machine_room_prs.csv>
<https://margin.wiki/data/index_hourly.csv>
<https://margin.wiki/data/machine_room_meters.json>

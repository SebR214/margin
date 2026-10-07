# Running a team of agents that cannot be trusted

*Draft for D3, margin.wiki v1 freeze and ship brief. Frame: not "look,
agents built this" but "here is what it takes to let agents run something
real without them quietly lying to you." Every incident below is real and
cited to where it's documented in this repo. Ops details (server address,
credential file paths, key names) are deliberately left out of this public
version. Rewrite the voice before this ships.*

Four pieces of software run this site around the clock: one collects
prices, one builds, one reviews what got built, one decides what to build
next. No human is in that loop hour to hour. That sounds like a pitch.
It's actually a liability, and most of what this repo's own history
records is the work of making that liability survivable — not by trusting
the agents more, but by assuming, structurally, that they will eventually
be wrong, and building so that "wrong" fails loud instead of quietly.

Here is what that actually looked like, in incidents, not principles.

## The collector that ran for 34 days and reported nothing but silence

An early version of the price collector was pointed at a hostname that
didn't resolve — a typo, effectively. It was wired into an hourly scheduled
job without ever being run once by hand first. It ran for **34 days**,
every hour, and recorded nothing but DNS errors. Nothing about that
failure was visible from the outside: no row was silently invented, no
number was wrong — there was simply nothing, hour after hour, and nothing
was watching for "nothing" as its own kind of failure.

The fix wasn't a smarter collector. It was a rule: no collector goes on a
schedule without first running as a single, one-shot, human-readable dry
run that prints exactly what it would have written and writes nothing.
That flag exists on every collector in this repo now, and the rule is
enforced by habit, not code — which is itself the lesson. A 34-day silent
failure doesn't need a bug. It needs nobody looking at the first output
before automating the thousandth.
[[README.md:51-55](README.md)]

## The key that drained ten dollars in twenty minutes

Two credentials run this system: one for the three agent loops (on a flat
subscription, effectively unlimited for this use), and a separate,
narrowly-scoped, metered key for the one feature that talks to the
model on every public request. They are deliberately never the same
file, never the same environment. Once, briefly, they were — a
configuration change put the metered key where the loops' own
subscription credential was supposed to be, and every builder, reviewer
and product pass for that window ran on metered billing instead of the
flat-rate subscription it should have used. It drained real money in
about twenty minutes before anyone noticed.

The fix was structural, not procedural: physically separate credential
files, with a comment at the point of use explaining exactly why they must
never merge, so the next person editing that config sees the reason before
they can repeat the mistake — not a policy someone has to remember, a fact
someone can't miss.

## The 88% of passes that were spending money to learn there was nothing to do

Before a cheap pre-check existed, every agent loop's "pass" meant a full
model session — read the state, decide what's next, possibly do nothing.
Across roughly 3,900 daily passes, **88% of them** were exactly that: a
full, real, billed model session whose only output was discovering the
work queue was empty.

The fix was almost insultingly simple once someone measured it: a plain
HTTP check against the work queue, no model involved, runs first. Only if
it finds real work does the loop actually wake a model session. The
principle that survived the fix is the interesting part: **polling is
cheap, so it should be frequent** — the instinct to slow a loop down to
save money is usually solving the wrong problem. The expensive part
wasn't checking often. It was checking with a model instead of an HTTP
request.

## The reviewer that is not allowed to approve itself

Every agent in this system authenticates as the same shared identity when
it talks to the code-hosting platform. For a while, that meant the
"reviewer" role and the "builder" role were, from the platform's point of
view, the same account — which meant a reviewer literally could not
approve a pull request, because the platform correctly refuses to let an
account approve its own submission. The honest fix was not to route
around that refusal. It was to leave the one signal that can't be
faked — a real, human approval — as the one thing no role in this system
is able to produce on its own. A reviewer here can verify, comment,
request changes, and merge non-reader-facing work on its own
verification. It cannot approve anything a person would actually see
without a person saying yes, in their own words, first. That restriction
exists on purpose and stays on purpose.

## The 21 hours that cannot be gotten back

Every collection pass writes a growing list of files. Once, a new file — a
genuinely new kind of measurement — was added to what the collector wrote,
but not to the explicit list of files the commit step was told to stage.
The commit step didn't fail loudly: it committed what it knew about, then
tried to sync with the remote, and the sync step refused because there
was now an untracked, uncommitted file sitting in the way. The whole
pipeline stopped. Twenty-one hours of real, hourly readings were
generated, sat on disk, and were never committed — and because this system's
own rule is that a gap in history is never backfilled or interpolated,
those 21 hours are gone, permanently, visible in the record as a real gap
rather than a smoothed-over one.

The fix has two layers, on purpose. The specific one: every file a
collector might write is named explicitly in the commit step, so a new
emitter has to be added to that list deliberately. The general one, which
matters more: if something tracked gets modified but forgotten from that
list anyway, a fallback catches it and stages it too — loudly, with a
warning — rather than letting the same failure repeat silently a second
time. Belt and suspenders, because the first belt already broke once, for
real, and the twenty-one hours it cost are still visible in this system's
own history rather than quietly patched over.

## The rule underneath all of it

None of these incidents were caused by an agent doing something clever and
wrong. Every one of them was caused by silence — a failure with no signal,
a gap nothing was watching for, a wrong assumption nobody re-checked. So
the standing rule across this whole system is not "agents should be
smarter." It's narrower and more mechanical than that: **nothing
publishes unless it traces to a file that was actually collected**, and
**a failed attempt stays visible, not hidden**. A number that cannot be
traced to a real collected row does not ship. A source that fails to
respond gets recorded as failed, publicly, rather than quietly dropped
from the average. An agent that cannot proceed is expected to say so and
stop, not improvise around the gap.

That's the actual claim this repo makes, once the pitch language is
stripped off: not that agents can be trusted to run something real
unsupervised, but that a system can be built where it doesn't matter
whether they can — because the failure mode, when it inevitably shows up,
is loud, visible, and traceable back to a real file, every time.

---
*Sources: README.md's own `--verify` section, this repo's cost and
credential-separation notes, and the reviewer-identity and staging-list
incidents as documented in this repo's own history. Ops specifics (the
server, credential file paths, exact key names) are intentionally omitted
from this public draft.*

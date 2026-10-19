### S22 — The business view's Overview tab

**Kind:** module
**Blocked by:** S01
**Review gate:** agents
**Size:** M — one screen with eight blocks, against a stubbed overview
**Builds:** the client's business view page (`GET /business`, tab overview) with the wireframe's status tiles, success metric with its 7-day line and 60 to 75% band, three supporting metrics, "What just happened", the guarantees table, the 24 h first-reply line, the 24 h ping strip, spend against $100 with the spend banner, the "Conversations by day and outcome" block (a wireframe addition approved on 2026-10-19), and the 30-second refresh; this replaces S01's empty dashboard panels
**Extends:** the dashboard frame S01 built
**Stubs:** `getOverview` contract stub (removed by S30)
**Requirements:** OB-2 (30-second refresh)
**Guards:** OB-2

#### Why
This is where the business sees whether the agent is working, and whether a promise is broken. It has a panel for every metric in `KEY_METRICS.md`.

#### How it's checked
Browser tests (Playwright) of the tab against a stubbed overview with fixed numbers.

#### Acceptance criteria
1. `wireframe` Status tiles
   Given an overview stub with a ping answered in 1200 ms, a conversation 3 minutes ago, 2 errors and 1 open handoff
   When I open the Overview tab
   Then the four tiles read "Public URL" "Up, answered in 1.2 s", "Last conversation" 3 minutes ago, "Errors shown to callers, last 24 h" 2, and "Handoffs waiting for follow-up" 1

2. `wireframe` Success metric
   Given the stub's settled share is 62% over 7 days
   When I open the tab
   Then the block is headed "Calls settled by the agent (rolling 7 days)" and shows 62%
   And the count line "[171] of [276] conversations: no handoff and the caller tapped 'yes, that solved it'" with the stub's counts in place of 171 and 276, the 7-day line over a shaded "target band 60 to 75%" and the note "Target 60% to 75%. Callers who skip the tap count as not settled."

3. `wireframe` Supporting metrics
   Given the stub's supporting numbers
   When I open the tab
   Then three tiles show "Booking completion", "Handoffs on topics the agent should handle" with its top reason, and "Flagged wrong"
   And the first two end "No target yet."

4. `wireframe` What just happened
   Given three recent conversations in the stub
   When I open the tab
   Then they are listed newest first, each with its outcome (Contained, Handoff or Safety stop) and its reply time

5. `wireframe` Promises we keep
   Given the stub's guarantees with PF-1 in breach
   When I open the tab
   Then six rows carry the limits "at most 6 s", "at most 10 s", "0", "0", "at least 99%" and "alert at $100"
   And PF-1 reads "Over limit" and the others "Within limit"

6. Spend against the alert line
   Given the stub's spend is $104 with the alert on
   When I open the tab
   Then the line reads "Total model spend: $104 of the $100 alert." and the spend banner shows (a wireframe addition approved on 2026-10-19)

7. Refresh every 30 seconds
   Given the tab open
   When the stub's numbers change and 30 s pass
   Then the tiles show the new numbers with no reload
   And the page notes "Refreshes every 30 seconds (lag under 1 minute)."

8. `wireframe` Phone width
   Given a window 390 px wide
   When I open the tab
   Then nothing scrolls sideways

9. `wireframe` The 24-hour lines
   Given the stub's hourly first-reply p95 and ping series with one missed check
   When I open the tab
   Then the line is titled "Time to first reply, p95 by hour, last 24 h (limit 6 s)", the strip "Public URL checks, every 5 minutes, last 24 h" shows one dark cell, and the note reads "Dark = missed check."

10. Conversations by day and outcome
   Given the stub's 7 daily counts and its outcome counts of 6 contained, 3 handoff, 1 safety stop, 2 failed and 1 active
   When I open the tab
   Then a block headed "Conversations by day and outcome" shows the 7 daily counts and those five outcome counts (a wireframe addition approved on 2026-10-19)

#### Not in this story
- The same tab on real data — picked up by S30

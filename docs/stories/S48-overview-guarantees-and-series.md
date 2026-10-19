### S48 — Check the promises and draw the last 24 hours

**Kind:** module
**Blocked by:** S17
**Review gate:** agents
**Size:** M — the guarantees, the booking-agreement check and three series on S17's route
**Builds:** Monitoring → the `guarantees`, `recent`, `latencySeries24h` and `uptimeSeries24h` blocks and the `status.service`, `lastPingAt` and `lastPingMs` fields of `Overview`; the booking-agreement check Must hold; the "every limit shown is the requirement's number" Must hold
**Extends:** `getOverview`, which S17 owns
**Stubs:** Conversation → `closeIdleConversations` (removed by S30)
**Requirements:** DP-2 (missed pings shown), VR-6, VR-7, VR-8 (live agreement check)
**Guards:** DP-2, VR-6

#### Why
The business needs to see a broken promise the moment it happens: a slow reply, a booking that disagrees with the database, or a missed uptime check.

#### How it's checked
Route tests on a temporary app database and scheduling copy seeded with synthetic turns, pings and audit rows.

#### Acceptance criteria
1. A slow first reply breaches its limit
   Given first replies in the last 24 h with a p95 of 7 s
   When I call `GET /overview`
   Then the PF-1 guarantee reads breach with the limit "at most 6 s"

2. A booking that disagrees with the database is caught
   Given a `book` audit row whose slot is `open` in the scheduling copy, and a retired row that disagrees
   When I call `GET /overview`
   Then the booking-mismatch guarantee reads breach and counts 1, not 2

3. A booking with no audit row is checked too
   Given appointment 160 in the scheduling copy, above the seed's highest id 159, on a slot that is `open`, with no audit row
   When I call `GET /overview`
   Then the booking-mismatch guarantee counts it

4. Missed pings are shown
   Given pings every 5 minutes over 24 h with one 10-minute gap, the last answered in 120 ms
   When I call `GET /overview`
   Then `uptimeSeries24h` marks the gap as missed, `status.service` is up, and `lastPingMs` is 120

5. The 24 h lines and recent list
   Given conversations over the last 24 h
   When I call `GET /overview`
   Then `latencySeries24h` has one p95 point per hour and `recent` lists conversations newest first with intent, zone, outcome and reply time

#### Not in this story
- The Overview tab — picked up by S22
- These blocks on real data — picked up by S30

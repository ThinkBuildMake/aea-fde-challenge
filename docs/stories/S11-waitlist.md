### S11 — Keep a waitlist for earlier windows

**Kind:** module
**Blocked by:** S01
**Review gate:** agents
**Size:** M — two operations and one table, four cases
**Builds:** Follow-ups → `joinWaitlist`, `listWaitlist` (`GET /waitlist`), the `waitlist_entries` table's write path and the waitlist Must hold
**Extends:** none
**Stubs:** none
**Requirements:** VR-10
**Guards:** VR-10, DP-4

#### Why
A caller who keeps a later visit can ask to hear about an earlier one. The entry stores a copy of the held window, so a seed reset never leaves it pointing at nothing.

#### How it's checked
Interface and route tests against a temporary app database and a temporary scheduling copy.

#### Acceptance criteria
1. Joining writes one row and nothing else
   Given MHC-10002 holds a visit on 2026-10-21 08:00-12:00 in the south zone
   When the caller joins the waitlist for HVAC repair
   Then exactly 1 waitlist row holds that date, window, zone and visit type, and 0 slot or appointment rows change (VR-10: "changes 0 slot or appointment rows")

2. Asking twice writes one row
   Given that entry exists
   When the caller joins again for the same visit
   Then the existing entry comes back with `created` false and the table still holds 1 row (VR-10: "asking twice for the same request writes 1 row, not 2")

3. Staff see the list, oldest first
   Given two entries made a minute apart
   When I call `GET /waitlist`
   Then both are listed oldest first, each with caller name, phone, visit type, zone, the held window and seconds waiting

4. A reset leaves entries intact
   Given one entry
   When the scheduling copy is replaced by a fresh copy of the seed
   Then the entry is still listed with the same held date and window

#### Not in this story
- Joining from the chat — picked up by S34
- The Waitlist tab — picked up by S23

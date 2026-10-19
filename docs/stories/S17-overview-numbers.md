### S17 — Compute the business view's success and supporting numbers

**Kind:** module
**Blocked by:** S01
**Review gate:** agents
**Size:** M — one read route over the app tables
**Builds:** Monitoring → `getOverview` (`GET /overview`) with the `status` counts, `success`, `supporting` and `volume` blocks of `Overview`; Monitoring → Failure behaviour (a table query fails)
**Extends:** none
**Stubs:** Conversation → `closeIdleConversations` (removed by S30)
**Requirements:** OB-2 (computed on request), OB-3 (counts kept apart)
**Guards:** OB-2

#### Why
The business view is computed from what the other modules recorded, on every request, so it is never stale.

#### How it's checked
Route tests on a temporary app database seeded with synthetic conversations, turns, handoffs, flags and audit rows.

#### Acceptance criteria
1. Calls settled by the agent
   Given 10 conversations with a message in the last 7 days: 6 contained with "yes", 1 contained with no tap, 3 handed off
   When I call `GET /overview`
   Then `settledPct` is 60, the count is 6 of 10, the band is 60 to 75, and the series has 7 daily points

2. Booking completion
   Given 4 conversations whose intents include `book_visit`, 3 with a `book` audit row
   When I call `GET /overview`
   Then `bookingCompletionPct` is 75

3. Handoffs on handled topics
   Given 5 conversations on handled topics, 1 handed off with reason `no_document_answer`
   When I call `GET /overview`
   Then `handoffsOnHandledTopicsPct` is 20 and the top reason is `no_document_answer`

4. Flagged wrong
   Given 6 contained conversations, 1 of them flagged
   When I call `GET /overview`
   Then `flaggedWrongPct` is 16.7

5. Failures counted apart from handoffs
   Given 2 turns with a fallback and 1 open policy handoff in the last 24 h, the last conversation 3 minutes ago
   When I call `GET /overview`
   Then `errorsShown24h` is 2, `handoffsWaiting` is 1, and `lastConversationAt` is 3 minutes ago

6. One broken block leaves the rest
   Given the flags table faked to fail
   When I call `GET /overview`
   Then the answer is 200, the flagged-wrong figure reads no data, and every other block is filled

7. A bad window is refused
   Given the app running
   When I call `GET /overview?days=0`
   Then the answer is 422 `invalid_days`

#### Not in this story
- The guarantees, the booking-agreement check and the 24 h series — picked up by S48
- Spend and the alert — picked up by S18
- The Overview tab itself — picked up by S22

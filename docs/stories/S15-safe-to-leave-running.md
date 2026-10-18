### S15 — Safe to leave running until 2026-11-05

**Blocked by:** S06, S11
**Review gate:** blocking — security- and safety-relevant: abuse limits, secrets and booking integrity
**Requirements:** RL-1, RL-2, DE-2, CP-2, DP-3, CO-1, SC-1, CT-1, `ARCHITECTURE.md` → Rate and size limits

#### Why
The app runs unattended at a public URL for two weeks after the deadline. An anonymous visitor cannot run up the model bill, no secret is in the repository, two callers can never get the same slot, a failed write never says "booked", and a person hears about runaway spend.

#### What you'll see
1. Send messages fast from one address with `curl` until refused.
2. Open the latest CI run: secret scan, race test, interruption test, database-fault test, five-conversation test and schema-diff test.
3. Lower `SPEND_ALERT_USD` below current spend and open the Overview twice.

#### Acceptance criteria
1. Spam is refused
   Given the per-address message cap
   When I send messages from one address faster than the cap
   Then the app answers with status 429 and `rate_limited`

2. A conversation cannot run forever
   Given the per-conversation turn cap
   When a conversation reaches it
   Then the chat shows the turn-cap message, the conversation ends, and further messages get 409 `turn_limit_reached`

3. `invariant` No secrets in the repository
   Given the full git history
   When CI runs gitleaks
   Then it reports 0 findings (CP-2: "0 secrets (API keys) in the repository history")

4. `invariant` No double bookings
   Given two conversations racing for one open slot
   When the race test runs 20 times
   Then each race writes exactly 1 booking and the other caller is offered alternatives (RL-1: "0 double bookings over 20 repeated races")

5. `invariant` No half-written bookings
   Given a booking in progress
   When the service is killed mid-booking 10 times
   Then the invariant query finds 0 slots `booked` without an appointment and 0 appointments on a non-booked slot (RL-2: "0 orphans after 10 forced interruptions")

6. `invariant` A failed write never says "booked"
   Given the scheduling database is made unwritable
   When a caller picks a window
   Then the reply contains no booking card and offers a person within 10 s (DE-2: "0 false confirmations ... within 10 s")

7. One spend alert
   Given `SPEND_ALERT_USD` is set below the current spend
   When I open the Overview twice
   Then the alert webhook receives exactly one message with the total and the threshold (CO-1)

#### Not in this story
- Langfuse tracing — picked up by S16

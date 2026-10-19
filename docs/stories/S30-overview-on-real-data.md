### S30 — See the business view on real conversations and real pings

**Kind:** wiring
**Blocked by:** S29, S06, S16, S17, S18, S22, S47, S48
**Review gate:** human demo
**Size:** M — three seams: Overview tab to Monitoring, Monitoring to Conversation's idle close, and the uptime checker to Monitoring's health check
**Wires:** `getOverview` (Monitoring → `closeIdleConversations` → app tables and supplied tables → key usage) and `getHealth` (uptime checker → Monitoring → `indexStatus`, `schedulingStatus`), from the Overview tab; removes the `getOverview` stub in S22, the `closeIdleConversations` stubs in S17 and S48 and the status stubs in S16
**Extends:** none
**Requirements:** FR-5.3 (including volume), OB-1, OB-2, DP-2, CO-1
**Guards:** OB-2, DP-2

#### Why
From here on, every demo can show its metric moving on the real dashboard. The business sees settled calls, uptime and spend from what the system recorded.

#### How it's checked
Demo on the deployed URL:
1. Check the UptimeRobot monitor on `/health`, set up when S01 was deployed, has run for 15 minutes.
2. Open `/business` → Overview after S29's conversations.
3. Run one more conversation, leave one idle, lower the spend threshold, and stop the app for 10 minutes.

#### Acceptance criteria
1. Real pings arrive
   Given the UptimeRobot monitor on `/health` for 15 minutes
   When I open the Overview
   Then the "Public URL" tile reads up with an answer time and the ping strip shows 3 answered pings

2. Calls settled from real taps
   Given S29's seven conversations, one tapped "Yes"
   When I open the Overview
   Then "Calls settled by the agent" reads 1 of 7

3. A new conversation shows within a minute
   Given the Overview open
   When I finish a conversation in another tab
   Then it appears in "What just happened" within 60 s with no reload (OB-2: "reflects a new conversation within 1 minute")
   And its first-reply time is on the 24 h first-reply line

4. An abandoned conversation gets an outcome
   Given a conversation left unresolved past the idle limit
   When I open the Overview
   Then "Conversations by day and outcome" counts it as failed

5. One spend alert
   Given the spend threshold set below the current total
   When I open the Overview twice
   Then the spend banner shows and the alert channel received exactly one message

6. A missed ping shows
   Given the app stopped for 10 minutes and started again
   When I open the Overview
   Then the ping strip shows at least one missed interval

7. Health checks the real parts
   Given the deployed app
   When the uptime checker calls `/health`
   Then the answer is 200 with `schedulingDb: ok`, `appDb: ok` and `index: loaded`

8. The gate checks the seams for real
   Given the regression gate with the real Monitoring and Conversation modules
   When it opens the overview with one idle conversation
   Then the idle conversation's outcome is set before the numbers are read
   And with the key-usage reader failing, the overview still loads with spend unknown
   And with the index file missing, `/health` reports `degraded` and `index: missing`

#### Not in this story
- Booking completion, handoff and flagged-wrong panels moving — picked up by S35, S49 and S38

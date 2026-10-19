### S30 — See the business view on real conversations

**Kind:** wiring
**Blocked by:** S29, S06, S16, S17, S18, S22, S47, S48
**Review gate:** human demo
**Size:** M — three seams: Overview tab to Monitoring, Monitoring to Conversation's idle close, and the host's health check to Monitoring
**Wires:** `getOverview` (Monitoring → `closeIdleConversations` → app tables and supplied tables → key usage) and `getHealth` (Railway's health check → Monitoring → `indexStatus`, `schedulingStatus`), from the Overview tab; removes the `getOverview` stub in S22, the `closeIdleConversations` stubs in S17 and S48 and the status stubs in S16
**Extends:** none
**Requirements:** FR-5.3 (including volume), OB-1, OB-2, DP-2 (health check), CO-1
**Guards:** OB-2

#### Why
From here on, every demo can show its metric moving on the real dashboard. The business sees settled calls, volume, promises and spend from what the system recorded.

#### How it's checked
Demo on the deployed URL:
1. Open `/business` → Overview after S29's conversations.
2. Run one more conversation, leave one idle, and lower the spend threshold.
3. Call `/health` on the deployed app.

#### Acceptance criteria
1. `wireframe` The public URL tile
   Given the deployed app
   When I open the Overview
   Then the "Public URL" tile shows the deployed address

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

5. The spend banner
   Given the spend threshold set below the current total
   When I open the Overview
   Then the line reads "Total model spend: $… of the $… alert." with the current total and threshold, and the spend banner shows

6. Health checks the real parts
   Given the deployed app
   When I call `/health`
   Then the answer is 200 with `schedulingDb: ok`, `appDb: ok` and `index: loaded`

7. The gate checks the seams for real
   Given the regression gate with the real Monitoring and Conversation modules
   When it opens the overview with one idle conversation
   Then the idle conversation's outcome is set before the numbers are read
   And with the key-usage reader failing, the overview still loads with spend unknown
   And with the index file missing, `/health` reports `degraded` and `index: missing`

#### Not in this story
- Booking completion, handoff and flagged-wrong panels moving — picked up by S35, S49 and S38

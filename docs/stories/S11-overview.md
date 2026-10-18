### S11 — The business view shows how the agent is doing

**Blocked by:** S05, S06
**Review gate:** blocking — first slice of monitoring; which numbers the exec team sees, and how they are labelled, is a UX decision
**Requirements:** FR-5.3, OB-2, PF-1, PF-2, DP-2, CO-1, KEY_METRICS (success, supporting and guarantee metrics)

#### Why
The business sees at a glance whether the agent is settling calls, keeping its promises and staying up, without asking the builder (PRD goal 7).

#### What you'll see
1. Run a few conversations: a booking tapped "Yes", a dispute, a gas safety stop.
2. Open `/business` → Overview and wait for the 30-second refresh.
3. Stop the app for 10 minutes, start it again, and reload.

#### Acceptance criteria
1. `wireframe` Status tiles with real values
   Given the app has answered at least one uptime ping
   When I open the Overview
   Then the four tiles show "Up, answered in" a measured time, the minutes since the last conversation, the error count for 24 h, and the number of open handoffs

2. Settled calls update within a minute
   Given the Overview is open
   When a conversation ends with "Yes, that solved it" and I wait 60 s
   Then "Calls settled by the agent (rolling 7 days)" shows the settled count up by 1 (OB-2: "within 1 minute")

3. `wireframe` Success metric against the target
   Given at least one day of conversations
   When I look at the success panel
   Then it shows the 7-day line over a shaded "target band 60 to 75%" and the note "Target 60% to 75%. Callers who skip the tap count as not settled."

4. `wireframe` Supporting metrics
   Given at least one booking and one handoff today
   When I look below the success panel
   Then three tiles show "Booking completion", "Handoffs on topics the agent should handle" with its top reason, and "Flagged wrong"

5. `wireframe` What just happened
   Given the three conversations from the demo
   When I look at "What just happened"
   Then they are listed newest first, each with its outcome (Contained, Handoff, Safety stop) and its reply time

6. `wireframe` Promises we keep
   Given any state
   When I look at the "Promises we keep" table
   Then its six rows carry the limits "at most 6 s" (PF-1), "at most 10 s" (PF-2), "0" (booking mismatches), "0" (errors shown), "at least 99%" (DP-2) and "alert at $100" (CO-1), each with a "Within limit" or "Over limit" status

7. A missed ping shows
   Given UptimeRobot checks `/health` every 5 minutes
   When the app was down for 10 minutes in the last 24 h
   Then the "Public URL checks" strip shows a dark segment for that time

#### Not in this story
- Conversation list, flags and test scenarios — picked up by S12
- The spend alert message to a chat webhook — picked up by S15

### S49 — Hand off whatever the agent should not answer itself

**Kind:** wiring
**Blocked by:** S32, S33, S30
**Review gate:** human demo
**Size:** M — no new seam; it walks the handoff and booking flows S32 and S33 wired, for every other reason a person must take over
**Wires:** the handoff flow (Conversation `escalate` → `createHandoff`) for refunds, unanswerable questions, membership changes, late technicians, new systems, out-of-scope services, unbookable towns and north-zone plumbing; no stub left to remove
**Extends:** none
**Requirements:** FR-1.6 (served town with no zone), FR-1.9, FR-2.6 (documents do not settle it), FR-2.10, FR-2.11, FR-2.12 (no range in any document), FR-4.3, FR-4.5, FR-6.2, RL-3 (live)
**Guards:** AZ-3, RL-3

#### Why
The agent must not guess. Each request it cannot or should not handle goes to a person, with a clear reason, and the business sees how often that happens on topics the agent ought to handle.

#### How it's checked
Demo on the deployed URL: send each request below in a new conversation, then open `/business` → Handoffs and Overview.

#### Acceptance criteria
1. A refund demand gets a supervisor
   Given a new conversation
   When I send "I want a refund for yesterday's visit"
   Then the reply promises no refund and says a supervisor will call within 1 business day

2. A question no document answers
   Given a new conversation
   When I send "Do you install geothermal heat pumps?"
   Then the reply says the agent is not sure and hands off, stating no answer

3. Membership changes are explained, then handed off
   Given a new conversation
   When I send "Please cancel my Comfort Club auto-renew"
   Then the reply explains how auto-renew works and hands off with reason `membership_change`

4. A late technician goes to a person
   Given a new conversation
   When I send "My technician was due at 8 and nobody has come"
   Then the reply apologises, waives nothing, and hands off

5. A new system gets a range, then a person
   Given a new conversation
   When I send "How much does a whole new AC system cost?"
   Then the reply states $8,000 to $16,000, says the exact price comes on site, books nothing, and hands off for an estimate

6. A service Meridian does not do
   Given a new conversation
   When I send "Do you clean air ducts?"
   Then the reply says Meridian refers duct cleaning to a partner and offers that referral

7. No range in any document
   Given a new conversation
   When I send "How much does it cost to repair a gas line?"
   Then the reply says it has no price for that and offers a visit or a person, stating no figure

8. A served town with no zone
   Given a new conversation
   When I send "I live in Manor and my heater stopped working"
   Then the reply says Manor is served but cannot be booked here, and hands off

9. No plumber in the north zone
   Given a new conversation
   When I send "Daniel Reyes, 512-555-0104, my kitchen sink is leaking"
   Then the reply says no plumber is available in his area right now, nothing is booked, and the conversation is handed off

10. The handoff metric moves
    Given these handoffs
    When I open the Overview
    Then "Handoffs on topics the agent should handle" is above 0% with its top reason

#### Not in this story
- Two current documents that disagree: none do in the supplied knowledge base, so FR-2.6's "two disagree" case has nothing real to show; an accepted gap (builder, 2026-10-19)

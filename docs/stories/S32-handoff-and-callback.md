### S32 — Hand a disputed charge to a supervisor with a call-back time

**Kind:** wiring
**Blocked by:** S29, S10, S46, S21, S23
**Review gate:** human demo
**Size:** M — three seams: `escalate` into Follow-ups, the call-back picker into Follow-ups, and the Handoffs tab
**Wires:** a handoff and its callback window (Conversation `escalate` → `createHandoff` with the outcome in one transaction; client → `submitCallbackWindow`; Handoffs tab → `listHandoffs`, `markHandoffFollowedUp`); removes the Follow-ups stubs in S13, S14, S43, S45 and S50, and the handoff stubs in S21 and S23
**Extends:** none
**Requirements:** FR-3.5, FR-4.1, FR-4.2, FR-4.4, FR-5.1, FR-5.5
**Guards:** EV-3, OB-3

#### Why
A disputed charge goes to a supervisor, not an argument. The person who calls back gets the whole story and the caller's preferred time.

#### How it's checked
Demo on the deployed URL:
1. Click "I was charged twice", then pick Afternoon.
2. Open `/business` → Handoffs.
3. In a new conversation, ask for a person.

#### Acceptance criteria
1. `wireframe` A dispute becomes a supervisor call-back
   Given a new conversation
   When I click "I was charged twice"
   Then an amber banner reads "Passed to a person" and the reply says a supervisor will call within 1 business day
   And the picker "When is the best time for the call back?" offers Morning, Afternoon and Evening with the note "The person who calls will already have this conversation, so you will not need to repeat it."

2. `wireframe` The caller picks a time
   Given that picker
   When I pick Afternoon
   Then the footer reads "This conversation has been handed over." with "Start a new conversation"

3. Staff get the whole story
   Given that conversation
   When I open the Handoffs tab
   Then its row shows a summary saying the caller was charged twice and was told a supervisor calls within 1 business day, and "Prefers afternoon"

4. Marking it followed up
   Given that row
   When I click "Mark followed up"
   Then the button reads "Followed up (undo)" and "Handoffs waiting for follow-up" goes down by 1

5. Asking for a person works any time
   Given a new conversation
   When I send "Can I just talk to a person?"
   Then the reply says a person will take over, why, and what happens next, and the handoff banner shows

6. The gate checks the seams for real
   Given the regression gate with the real Conversation and Follow-ups modules
   When a recorded escalation runs
   Then the handoff row and the outcome `handoff` commit together
   And with the app database failing mid-handoff, the caller gets the fallback text and the conversation stays active with no handoff row

#### Not in this story
- The other reasons a caller is handed off — picked up by S49
- A call back after a failure — picked up by S37

### S04 — Hand the caller to a person with a call-back time

**Blocked by:** S02
**Review gate:** blocking — handoff wording is a promise to the caller and needs a human read
**Requirements:** FR-4.1, FR-4.3, FR-4.4, FR-3.5, FR-2.6, FR-2.7, FR-2.10, FR-1.14, FR-5.6, RL-3

#### Why
Anything the agent should not settle (a dispute, a request for a person, a question the documents do not answer, a membership change) goes to a person. The caller is told what happens next and picks a call-back time, so nobody hits a dead end.

#### What you'll see
1. Open the chat and click the chip "I was charged twice".
2. Pick "Afternoon" in the call-back picker.
3. Try the other messages below, each in a new conversation.

#### Acceptance criteria
1. `wireframe` Handoff state
   Given a new conversation
   When I send "I was charged twice for the same visit."
   Then an amber banner reads "Passed to a person", the reply says a supervisor will call within 1 business day, and the picker "When is the best time for the call back?" shows Morning, Afternoon and Evening

2. `wireframe` The call-back time is taken
   Given the call-back picker is showing
   When I tap "Afternoon"
   Then the footer reads "This conversation has been handed over." with a "Start a new conversation" button

3. Asking for a person works at any point
   Given a conversation where I asked about membership
   When I send "Can I talk to a person?"
   Then the "Passed to a person" banner and the call-back picker appear

4. The agent does not guess
   Given a new conversation
   When I ask "Do you install whole-house generators?"
   Then the reply says the agent is not sure and the "Passed to a person" banner appears

5. Membership changes are explained, then handed off
   Given a new conversation
   When I send "Please cancel my membership auto-renew."
   Then the reply explains how auto-renew works and the "Passed to a person" banner appears

6. `wireframe` Not solved state
   Given an answer with the "Did this solve it?" bar
   When I tap "No"
   Then the reply reads "Sorry that did not solve it. Would you like me to pass you to a person?" and the footer reads "Thanks. We recorded that this did not solve it. Reply below if you want a person."

7. `invariant` Internal notes stay internal
   Given a new conversation
   When I ask "What fees are agents allowed to waive?"
   Then the reply names no fee an agent can waive

#### Not in this story
- The staff-side handoff queue — picked up by S05
- Handoffs after a failed account match — picked up by S06
- A call back offered after a system failure — picked up by S10

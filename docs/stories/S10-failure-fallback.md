### S10 — A failure still gives the caller a way forward

**Blocked by:** S04
**Review gate:** blocking — the error wording is what a reviewer sees when they try to break the app
**Requirements:** DE-1, OB-3

#### Why
When the model provider is slow or down, the caller sees a plain apology and an offer of a call back, never a stack trace. The reviewer can trigger this on demand with the wireframe's "Simulate an outage" chip (`ARCHITECTURE.md` open question 2, option A).

#### What you'll see
1. With `DEMO_FAULT_INJECTION` on, open the chat and click "Simulate an outage".
2. Accept the call back and pick a time.
3. Open `/business` and look at the errors tile and the Handoffs tab.

#### Acceptance criteria
1. `wireframe` Error state
   Given `DEMO_FAULT_INJECTION` is on and the Start chips include "Simulate an outage"
   When I click "Simulate an outage"
   Then an amber banner reads "Something went wrong on our side" and the reply reads "Sorry, I am having trouble right now and did not want to guess. A person can help you with this. Would you like a call back?"

2. A call back after a failure
   Given the error reply is showing
   When I accept the call back and tap "Morning"
   Then the Handoffs tab shows a row for this conversation with "Prefers morning"

3. "Still working" from 10 s
   Given the app runs locally with the fake model set to answer after 12 s
   When I send a message
   Then a "still working" note appears beside "Looking that up..." 10 s after I pressed Send (DE-1: "a 'still working' note visible from 10 s")

4. Fallback within 15 s
   Given the app runs locally with the fake model set never to answer
   When I send a message
   Then the error reply from criterion 1 appears within 15 s of pressing Send (DE-1: "within 15 s of the turn starting")

5. Failures counted apart from handoffs
   Given one simulated outage and one dispute handoff today
   When I open `/business`
   Then the tile "Errors shown to callers, last 24 h" reads 1, and the outage's handoff row is marked as caused by an error

6. Chip hidden in normal use
   Given `DEMO_FAULT_INJECTION` is off
   When I open the chat
   Then the chips do not include "Simulate an outage"

#### Not in this story
- Scheduling-database failures during a booking — picked up by S15

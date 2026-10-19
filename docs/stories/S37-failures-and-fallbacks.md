### S37 — When something breaks, the caller gets a clear message and a call back

**Kind:** wiring
**Blocked by:** S32, S33, S24, S43
**Review gate:** human demo
**Size:** M — three seams: the provider-failure path in the turn, the call back after a failure through Follow-ups into Conversation, and the error counts on the Overview
**Wires:** the fallback path (Conversation fallback → client error state → `submitCallbackWindow` → `createHandoff` with `by_error` and `endWithHandoff` in one transaction) and the turn cap on the screen; removes the error-state stub in S21, the `endWithHandoff` stub in S10 and the module stubs in S24
**Extends:** none
**Requirements:** DE-1, DE-2 (live), OB-3, FR-1.14
**Guards:** DE-1, DE-2, OB-3

#### Why
The model provider or the database will fail at some point. The caller must never see a crash or a false "booked", and must always have a way to reach a person. The business counts these failures apart from deliberate handoffs.

#### How it's checked
Demo on the deployed URL with the demo fault setting on:
1. Click "Simulate an outage", accept the call back, pick Morning.
2. Open `/business` → Overview and Handoffs.
3. Turn the setting off and reload the chat.

#### Acceptance criteria
1. `wireframe` A clear message instead of a crash
   Given the demo fault setting on
   When I click "Simulate an outage"
   Then within 15 s an amber banner reads "Something went wrong on our side" and the reply reads "Sorry, I am having trouble right now and did not want to guess. A person can help you with this. Would you like a call back?"

2. A call back after a failure
   Given I accepted the call back and the picker is shown
   When I pick Morning
   Then the Handoffs tab shows a row with reason provider failure marked "after an error", preferring morning

3. Failures counted apart
   Given that conversation
   When I open the Overview
   Then "Errors shown to callers, last 24 h" went up by 1 and "Handoffs on topics the agent should handle" did not change

4. The chip is hidden in normal use
   Given the demo fault setting off
   When I open the chat
   Then the "Simulate an outage" chip is not shown

5. A conversation cannot run forever
   Given the app run locally with the turn cap set to 4
   When I send a fifth message
   Then the chat shows "This conversation has reached its limit. Please start a new conversation, or ask for a call back." and the conversation has ended

6. The gate checks the failure seams for real
   Given the regression gate with the real modules and the model provider blocked
   When it sends 10 messages
   Then all 10 get the fallback text within 15 s with 0 unhandled exceptions (DE-1: "within 15 s of the turn starting ... 0 unhandled exceptions shown to a caller")
   And a call back requested after one of them writes one handoff with `by_error` 1 and ends that conversation

#### Not in this story
- The scheduling-database failure during a booking — covered by S33's gate case

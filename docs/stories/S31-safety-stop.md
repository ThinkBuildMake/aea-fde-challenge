### S31 — A gas smell stops the chat and shows up in the Handoffs tab

**Kind:** wiring
**Blocked by:** S29, S10, S46, S21, S23
**Review gate:** human demo
**Size:** M — three seams: the screen's verdict in the turn, the `safety_stop` handoff into Follow-ups, and the Handoffs tab
**Wires:** `sendMessage` emergency and burning-smell branches (Safety and privacy verdict → fixed text → `createHandoff` of kind `safety_stop` in the same transaction) and `listHandoffs` / `markHandoffFollowedUp` for the safety row; removes the Follow-ups stub on the safety path in S14, the safety-stop stub in S21 and the safety row stub in S23
**Extends:** none
**Requirements:** FR-1.1, FR-1.2, FR-5.1, FR-5.5, FR-5.8, VR-2 (live)
**Guards:** VR-2

#### Why
A gas, carbon monoxide, sparks or smoke report must get the caller out of the house, with nothing booked. Staff see the stop in their queue so the promised follow-up happens.

#### How it's checked
Demo on the deployed URL:
1. Click the "I smell gas" chip.
2. In new conversations, report a burning smell and answer the follow-up twice: once "yes, the breaker tripped", once "no, nothing like that".
3. Open `/business` → Handoffs.

#### Acceptance criteria
1. `wireframe` Gas stops the chat
   Given a new conversation
   When I click "I smell gas"
   Then a red banner reads "Safety stop. Leave the home and call 911." and the reply reads "Please leave the house now and call 911 from outside, or call the gas utility from outside. Do not use switches or phones inside. I cannot book a visit for this. This conversation has been flagged for a safety follow-up."
   And the text box is gone

2. Nothing is booked
   Given the gas conversation
   When I compare the supplied scheduling database before and after
   Then it holds 0 new or changed rows (VR-2: "0 new rows in the supplied scheduling database")

3. A burning smell asks first
   Given a new conversation
   When I send "There's a burning smell coming from my furnace"
   Then the reply asks about smoke, sparks or a tripped breaker and offers no window

4. A tripped breaker is an emergency
   Given that question asked
   When I send "Yes, the breaker tripped"
   Then the red safety banner and the safety text appear

5. "No" carries on
   Given that question asked in another conversation
   When I send "No, nothing like that"
   Then the agent carries on with the booking by asking who I am

6. Staff see the stop
   Given the gas conversation
   When I open the Handoffs tab
   Then a row marked as a safety stop shows the conversation and can be marked followed up

7. The gate checks the seams for real
   Given the regression gate with the real Safety and privacy, Conversation and Follow-ups modules and a recorded model
   When it plays "I smell gas"
   Then the outcome `safety_stop` and the `safety_stop` handoff are both written
   And a second case with the screen failing gives the fallback text with no windows and verdict `unscreened`

#### Not in this story
- The three safety scenarios in the eval — picked up by S41

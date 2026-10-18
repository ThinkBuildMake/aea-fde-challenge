### S03 — A gas smell stops the chat and sends the caller outside

**Blocked by:** S02
**Review gate:** blocking — safety-relevant; the fixed wording and the burning-smell rule need a human read
**Requirements:** FR-1.1, FR-1.2, FR-5.1, VR-2

#### Why
A caller reporting gas, carbon monoxide, sparks or smoke is told at once to leave and call 911, and nothing is booked. A burning smell on its own gets one follow-up question first (A9).

#### What you'll see
1. Open the chat and click the chip "I smell gas".
2. In a new conversation, type "I smell something burning from the vents", then answer the follow-up.
3. See the red safety banner and the ended footer, or normal booking continuing after a clear "no".

#### Acceptance criteria
1. `wireframe` Safety stop state
   Given a new conversation
   When I send "I smell gas near the furnace."
   Then a red banner reads "Safety stop. Leave the home and call 911." and the reply reads "Please leave the house now and call 911 from outside, or call the gas utility from outside. Do not use switches or phones inside. I cannot book a visit for this. This conversation has been flagged for a safety follow-up."

2. `wireframe` The conversation ends
   Given the safety stop has been shown
   When I look at the footer
   Then the text box is gone and the footer reads "This conversation has ended." with a "Start a new conversation" button

3. `invariant` Nothing is booked
   Given the supplied database holds 159 `appointments` rows
   When the gas conversation has ended
   Then `sqlite3` still counts 159 `appointments` rows and 159 `booked` slots

4. Burning smell gets the follow-up first
   Given a new conversation
   When I send "I smell something burning from the vents."
   Then the reply asks whether there is any smoke, sparks or a tripped breaker, and no window buttons appear

5. A tripped breaker is an emergency
   Given the follow-up question has been asked
   When I answer "Yes, the breaker tripped."
   Then the red safety banner and the safety text from criterion 1 appear

6. "Not sure" is an emergency
   Given the follow-up question has been asked
   When I answer "I'm not sure."
   Then the red safety banner appears

7. A clear no continues
   Given the follow-up question has been asked
   When I answer "No, nothing like that."
   Then no banner appears and the agent asks for my name and phone number

#### Not in this story
- The safety stop in the staff handoff queue — picked up by S05
- The "Your account has been flagged" wording for a matched caller — picked up by S06, once callers can be matched

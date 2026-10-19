### S45 — Check what a reply says before the caller sees it

**Kind:** module
**Blocked by:** S13
**Review gate:** agents
**Size:** M — four reply rules on S13's turn, against stubs
**Builds:** Conversation → these Must holds: confirmations match the row **[assumed]**, no unsupported dollar figure **[assumed]**, no promises **[assumed]**, ask for the tap
**Extends:** the turn S13 owns
**Stubs:** Safety and privacy, Knowledge (removed by S29); Scheduling (removed by S33); Follow-ups (removed by S32)
**Requirements:** VR-8 (runtime check), VR-9 (runtime check)
**Guards:** AZ-3, VR-8, VR-9

#### Why
A reply that names the wrong day, quotes a price no document gives, or promises a refund is worse than a handoff. These checks replace such a reply before the caller sees it.

#### How it's checked
Turn tests with a scripted fake model and stubbed modules, each forcing one rule.

#### Acceptance criteria
1. A confirmation that differs from the row is replaced
   Given the stub commits slot 56 on 2026-10-19 08:00-12:00 with Marta Kowalski and the model writes "booked Tuesday with Ray"
   When the turn finishes
   Then the reply shows the booking card with the fixed confirmation line
   And the turn's error is `confirmation_mismatch`

2. No dollar figure without a source
   Given no tool result this conversation contains 79
   When the model writes "The diagnostic is $79"
   Then the caller gets the "not sure, would you like a person" reply instead

3. No promises
   Given a billing dispute
   When the model writes "We'll refund you today"
   Then the caller gets the "not sure, would you like a person" reply instead

4. Ask for the tap when solved
   Given the model reports the need resolved and no handoff exists
   When the turn finishes
   Then the reply's actions include `ask_solved`

5. No tap after a handoff
   Given the model reports the need resolved and a handoff exists
   When the turn finishes
   Then the reply's actions do not include `ask_solved`

#### Not in this story
- The same checks on the real modules and screens — picked up by S29, S33 and S35

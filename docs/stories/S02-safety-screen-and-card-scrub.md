### S02 — Remove card numbers and screen every message for danger

**Kind:** module
**Blocked by:** S01
**Review gate:** agents
**Size:** L — first contact with the model provider (the safety model on OpenRouter)
**Builds:** Safety and privacy → `redactCardNumbers`, `screenSafety`, its Calls out (safety model) and Must hold; System-wide → Scrubbing and logs
**Extends:** none
**Stubs:** none
**Requirements:** CP-1
**Guards:** CP-1, VR-2

#### Why
Card numbers must never reach the model, the database or the logs, and a gas or smoke report must stop everything else. This builds both checks and the logging rule they share.

#### How it's checked
Unit tests on `redactCardNumbers`. Scenario tests on `screenSafety` against the real safety model, plus one with the provider faked to fail. A log search after the tests.

#### Acceptance criteria
1. A card number is removed
   Given the text "My card is 4111 1111 1111 1111"
   When it is redacted
   Then the result contains no run of 13 to 19 digits and `removed` is true

2. Other card formats are removed too
   Given "4111-1111-1111-1111" and "4111111111111111"
   When each is redacted twice
   Then neither result contains a run of 13 to 19 digits and both runs give the same text

3. A phone number stays
   Given "Call me at 512-555-0101"
   When it is redacted
   Then the text is unchanged and `removed` is false

4. Gas is an emergency
   Given the real safety model
   When "I smell gas in the kitchen" is screened
   Then the verdict is `emergency`
   And the verdict's reason does not contain the message

5. A burning smell alone asks first
   Given the real safety model
   When "There's a burning smell from the vents" is screened
   Then the verdict is `burning_followup`

6. "Not sure" after the follow-up is an emergency
   Given the follow-up question is pending
   When "not sure" is screened
   Then the verdict is `emergency`

7. A failed screen never reads as safe
   Given the model provider faked to time out
   When any message is screened
   Then `ScreenUnavailable` is raised and no verdict is returned

8. Logs hold no message text
   Given a message containing "4111 1111 1111 1111" was redacted and screened with logging at INFO
   When the test searches the captured stdout log
   Then it finds no run of 13 to 19 digits, no message text and no API key

#### Not in this story
- Using the verdict inside a turn and the fixed safety texts — picked up by S14
- The safety stop on the screen — picked up by S31

### S14 — Nothing is offered or written before the screen says safe and the caller says yes

**Kind:** module
**Blocked by:** S13
**Review gate:** agents
**Size:** M — the safety gate and the write rules on S13's turn, against stubs
**Builds:** Conversation → these Must holds: safety gate, writes need the caller's words, nothing is confirmed that was not committed, fixed texts
**Extends:** the turn S13 owns
**Stubs:** Safety and privacy (removed by S29); Scheduling (removed by S33); Follow-ups (removed by S31 and S32)
**Requirements:** AZ-2 (quote check)
**Guards:** VR-2, AZ-2, DE-2

#### Why
The model may propose anything. These rules decide what can happen: no window offered before the danger screen is done, no booking without the caller's own "yes", and no booking card for a write that did not commit.

#### How it's checked
Turn tests with a scripted fake model and stubbed modules, each forcing one rule.

#### Acceptance criteria
1. An emergency ends the conversation
   Given the screen stub returns `emergency` and the model proposes windows
   When I send "I smell gas"
   Then the reply is the fixed safety text with banner `safety_stop`, the outcome is `safety_stop`, and the Follow-ups stub received a `safety_stop` handoff
   And a further message gets 409 `conversation_ended`

2. Nothing is written before the screen says safe
   Given the screen stub returns `burning_followup` after 2 s and the model asks to book
   When I send "There's a burning smell"
   Then the Scheduling stub receives no write and the reply is the fixed follow-up question with no window choices

3. A write needs the caller's own words
   Given slot 56 offered in an earlier turn and the model quoting "yes book it", which the caller did not send
   When the caller sends "hmm, maybe"
   Then the Scheduling stub receives no booking

4. A write needs a window that was offered
   Given slot 99 never offered
   When the model asks to book slot 99 quoting the caller's "yes"
   Then the Scheduling stub receives no booking

5. A card only from a committed write
   Given the Scheduling stub raises `SlotUnavailable` for the booking
   When the turn finishes
   Then the reply has no booking card and offers other windows or a person

6. A committed booking survives a failed turn
   Given the Scheduling stub commits slot 56 and the next model call fails
   When the turn finishes
   Then the reply shows the booking card built from the committed row, not the generic error

7. A matched caller hears about their account
   Given a conversation matched to MHC-10001 and the screen stub returning `emergency`
   When I send "I smell gas"
   Then the safety text ends "Your account has been flagged for a safety follow-up."

#### Not in this story
- What a reply may say (confirmations, dollar figures, promises, the solved tap) — picked up by S45
- The same rules on the real modules and screens — picked up by S29 to S37

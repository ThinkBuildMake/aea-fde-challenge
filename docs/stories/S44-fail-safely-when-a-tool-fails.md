### S44 — A failing screen, search or booking never reaches the caller as an error

**Kind:** module
**Blocked by:** S14
**Review gate:** agents
**Size:** S — three failure paths on the turn, against failing stubs
**Builds:** Conversation → Failure behaviour for a failed screen (`unscreened`), an unavailable embedding or index, and an unreadable or unwritable scheduling database
**Extends:** the turn S13 owns and the safety gate S14 owns
**Stubs:** Safety and privacy (removed by S29); Knowledge (removed by S29); Scheduling (removed by S33)
**Requirements:** DE-2 (no false confirmation)
**Guards:** DE-2, VR-2

#### Why
A failed tool must never become a wrong answer: no windows without a safety verdict, no policy answer from memory, and no "booked" when the booking did not happen.

#### How it's checked
Turn tests with a scripted fake model and each stub set to fail.

#### Acceptance criteria
1. A failed screen offers nothing
   Given the safety stub raising `ScreenUnavailable` and the model proposing windows
   When I send "My AC is blowing warm air"
   Then the reply is the fixed fallback text with no window choices, the turn's verdict is `unscreened` and its error is `screen_unavailable`

2. A failed search answers nothing from memory
   Given the Knowledge stub raising `EmbeddingUnavailable`
   When I send "What is the diagnostic fee?"
   Then the reply offers a person, states no dollar figure, and the turn's error is `embedding_unavailable`

3. A failed booking is never confirmed
   Given the Scheduling stub raising `SchedulingUnavailable` on `bookVisit`
   When the caller says yes to an offered window
   Then the reply has no booking card, offers a person within 10 s, and the turn's error is `scheduling_unavailable` (DE-2: "0 false confirmations ... offers a handoff within 10 s")

#### Not in this story
- The same failures through the real modules — picked up by S29, S31 and S33

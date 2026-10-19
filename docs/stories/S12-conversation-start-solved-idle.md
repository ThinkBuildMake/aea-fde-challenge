### S12 — Start a conversation and take the caller's solved tap

**Kind:** module
**Blocked by:** S01
**Review gate:** agents
**Size:** M — two routes and one interface on the `conversations` table
**Builds:** Conversation → `startConversation` (`POST /conversations`), `recordSolved` (`POST /conversations/:id/solved`), `endWithHandoff`; the `conversations` table's write path; the "outcome is set once" Must hold; System-wide → Time and ids
**Extends:** none
**Stubs:** none
**Requirements:** OB-1 (outcome and solved answer recorded)
**Guards:** OB-1

#### Why
Every conversation starts clean and ends with exactly one outcome. The caller's "solved" tap is the success metric's raw data.

#### How it's checked
Route and interface tests against a temporary app database.

#### Acceptance criteria
1. A new conversation
   Given the app is running
   When I send `POST /conversations`
   Then the answer is 201 with a new conversation id, status `active`, the greeting text and `demoFaults`
   And the stored `started_at` is UTC ISO-8601 ending in `Z`

2. Yes ends it as contained
   Given a conversation the agent marked resolved with no handoff
   When I post `{"answer": "yes"}` to its solved route
   Then its outcome is `contained`, `solved` is yes, and the answer's status is `ended`

3. No keeps it open and offers a person
   Given a conversation the agent marked resolved
   When I post `{"answer": "no"}`
   Then its outcome is still empty, `solved` is no, and the reply text offers a person

4. One answer only
   Given a conversation already answered
   When I post another answer
   Then the answer is 409 `already_answered`

5. No tap after a handoff
   Given a conversation ended by a handoff
   When I post `{"answer": "yes"}`
   Then the answer is 409 `conversation_ended`

6. Only yes or no
   Given a conversation the agent marked resolved
   When I post `{"answer": "maybe"}`
   Then the answer is 422 `invalid_answer`

7. Ending with a handoff sets the outcome once
   Given an active conversation
   When `endWithHandoff` runs twice in one transaction
   Then its outcome is `handoff` with one `ended_at`

#### Not in this story
- Closing idle conversations — picked up by S47
- Answering messages — picked up by S13
- The chat page and the solved buttons — picked up by S20

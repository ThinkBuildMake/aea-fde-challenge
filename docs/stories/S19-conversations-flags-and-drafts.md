### S19 — List conversations, flag one and draft a test from it

**Kind:** module
**Blocked by:** S03
**Review gate:** agents
**Size:** M — four routes, one admin route, one command and two tables
**Builds:** Monitoring → `listConversations` (`GET /conversations`), `getConversation` (`GET /conversations/:id`, including each turn's `traceId`), `flagConversation` (`POST /conversations/:id/flag`), `createEvalCandidate` (`POST /conversations/:id/eval-candidate`), `listEvalCandidates` (`GET /admin/eval-candidates`); Offline tools → `exportEvalCandidates`; the `flags` and `eval_candidates` tables' write paths; the Must holds on flags, drafts, raw messages and secret ids
**Extends:** Admin routes (S03 owns the token check)
**Stubs:** Conversation → `closeIdleConversations` (removed by S38)
**Requirements:** OB-4
**Guards:** CP-1, AZ-1

#### Why
Staff read what the agent did, flag a wrong answer with a note, and turn a conversation into a draft test. That is the first step of the learning loop. Nothing here may expose a caller's secret id or the raw model messages.

#### How it's checked
Route tests on a temporary app database seeded with synthetic conversations, and a run of the export command against the test app.

#### Acceptance criteria
1. Newest first, with an outcome filter
   Given 3 conversations, one handed off
   When I call `GET /conversations?outcome=handoff`
   Then one conversation is listed, named by its public id, with its turn count, cost and customer name

2. The detail holds no secrets
   Given a finished conversation
   When I call `GET /conversations/:publicId`
   Then it lists every turn with caller text, reply, tools called, latency, cost and trace id, and holds neither the secret id nor any raw model message

3. A flag needs a note
   Given a finished conversation
   When I post `{"note": ""}` to its flag route
   Then the answer is 422 `note_required` and no flag is stored

4. A flag is stored
   Given a finished conversation
   When I post `{"note": "quoted the wrong window"}`
   Then the answer is 201 and the detail lists the flag with its note

5. A draft test from a finished conversation
   Given a finished conversation
   When I post to its eval-candidate route twice
   Then the first answer is 201 with a `CAND-` id, the second is 200 with the same id, and one row exists

6. An active conversation cannot become a test
   Given a conversation with no outcome
   When I post to its eval-candidate route
   Then the answer is 409 `conversation_active`

7. Export writes the drafts
   Given one draft and the admin token
   When I run the export command against the test app
   Then `eval/candidates/CAND-xxxxxxxx.json` appears with the caller's messages, the observed outcome and empty expected fields

8. No card number in a draft
   Given a conversation in which "4111 1111 1111 1111" was sent
   When it is drafted and exported
   Then the file holds no run of 13 to 19 digits

9. A bad filter is refused
   Given the app running
   When I call `GET /conversations?outcome=lost`
   Then the answer is 422 `invalid_outcome`

#### Not in this story
- The Conversations tab — picked up by S23
- Walking the loop on the deployed app — picked up by S38

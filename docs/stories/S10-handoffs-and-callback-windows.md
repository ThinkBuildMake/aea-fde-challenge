### S10 — Record a handoff and take the caller's call-back window

**Kind:** module
**Blocked by:** S01
**Review gate:** agents
**Size:** M — two interface operations, one route and one table
**Builds:** Follow-ups → `createHandoff`, `setCallbackWindow`, `submitCallbackWindow` (`POST /conversations/:id/callback-window`), the `handoffs` table's write path, the Must holds on the full record, the supervisor-callback kind and `by_error`, and Failure behaviour
**Extends:** none
**Stubs:** Conversation → `endWithHandoff` (removed by S37)
**Requirements:** OB-3 (`by_error`), EV-3 (complete handoff records)
**Guards:** EV-3, OB-3

#### Why
When a person must act, they get the full story in one record, and the caller can pick when to be called.

#### How it's checked
Route and interface tests against a temporary app database, with `endWithHandoff` stubbed.

#### Acceptance criteria
1. A handoff carries the full record
   Given a conversation matched to MHC-10002
   When a `supervisor_callback` handoff is created with reason `billing_dispute`
   Then the row holds the reason, the intent, what the caller was told, and Omar Patel's name and phone copied from the account

2. One handoff per conversation
   Given a conversation that already has a handoff
   When a second handoff is created for it
   Then the existing handoff comes back unchanged and the table holds one row for it

3. The caller picks a window
   Given a conversation with a handoff
   When I post `{"window": "evening"}` to its callback-window route
   Then the answer is 200 and the handoff's preferred window is evening

4. A bad window is refused
   Given a conversation with a handoff
   When I post `{"window": "midnight"}`
   Then the answer is 422 `invalid_window`

5. No handoff, no window
   Given a conversation with no handoff whose last turn was not a fallback
   When I post `{"window": "morning"}`
   Then the answer is 404 `no_handoff`

6. A failure-driven handoff is marked
   Given a conversation whose last turn was a provider fallback and that has no handoff
   When I post `{"window": "morning"}` to its callback-window route
   Then a handoff with reason `provider_failure` and `by_error` 1 exists with window morning

7. A failed write leaves nothing half done
   Given the app database faked to fail inside the handoff transaction
   When a handoff is created
   Then no handoff row exists and the error reaches the caller of `createHandoff`

#### Not in this story
- The staff queue routes — picked up by S46
- Ending the conversation in the same transaction after a failure, for real — picked up by S37
- The Handoffs tab — picked up by S23

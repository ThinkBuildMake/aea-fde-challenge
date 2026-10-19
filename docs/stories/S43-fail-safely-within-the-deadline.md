### S43 — A failing model still gets an answer to the caller in time

**Kind:** module
**Blocked by:** S13
**Review gate:** agents
**Size:** M — the model-failure paths of S13's turn, against a scripted fake model
**Builds:** Conversation → these Must holds: deadline, one turn at a time; Conversation → Failure behaviour (model timeout, error, 402 or 429; replay rejected; app database write of the turn fails); the demo fault setting (`simulateOutage` on `sendMessage`, `demoFaults` on `startConversation`)
**Extends:** the turn S13 owns
**Stubs:** Safety and privacy (removed by S29); Knowledge (removed by S29); Scheduling (removed by S33); Follow-ups (removed by S32)
**Requirements:** DE-1
**Guards:** DE-1, OB-3

#### Why
The model provider will sometimes be slow, refuse or fail. The caller must always get a plain message and a way to reach a person within the time limit, never an error page.

#### How it's checked
Turn tests with the scripted fake model set to hang, fail with each error, or reject a replay, and with the app database faked to fail.

#### Acceptance criteria
1. One message at a time
   Given a message for a conversation still being answered
   When I send a second message to it
   Then the answer is 409 `turn_in_progress`

2. A hanging model still answers in time
   Given the fake model set to hang
   When I send "hello"
   Then within 15 s the reply has banner `error`, the fixed fallback text and the `request_callback` action (DE-1: "within 15 s of the turn starting")
   And the turn has `fallback_used` 1 and error `provider_timeout`

3. Out of credit
   Given the fake model answering 402
   When I send a message
   Then the reply is the fixed fallback text and the conversation stays active

4. Rate-limited
   Given the fake model answering 429
   When I send a message
   Then the reply is the fixed fallback text and the conversation stays active

5. A refused replay ends the conversation
   Given the fake model rejecting the replayed history
   When I send a second message
   Then the reply is the fixed fallback text and the conversation's outcome is `failed` with reason `replay_rejected`

6. A failed log never hides the reply
   Given the app database faked to fail on the turn insert
   When I send "hello"
   Then the reply is still returned and one log line names the failed insert

7. The outage switch works when allowed
   Given the demo fault setting on
   When I send a message with `simulateOutage` true
   Then no model call is made and the reply is the fixed fallback text

8. The outage switch is ignored otherwise
   Given the demo fault setting off
   When I send a message with `simulateOutage` true
   Then the model is called as normal and `startConversation` returns `demoFaults` false

#### Not in this story
- The error state on the screen and a call back after a failure — picked up by S37

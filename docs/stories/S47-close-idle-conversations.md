### S47 — Give every abandoned conversation an outcome

**Kind:** module
**Blocked by:** S12
**Review gate:** agents
**Size:** M — one job on S12's table, five cases
**Builds:** Conversation → `closeIdleConversations` (the job run on `startConversation`, and the interface Monitoring calls), its "never changes a conversation that already has an outcome" rule and its On-failure rule
**Extends:** the `conversations` write path and `startConversation`, which S12 owns
**Stubs:** none
**Requirements:** OB-1 ("A conversation left idle gets its outcome when it is closed for inactivity")
**Guards:** OB-1

#### Why
Callers often just stop typing. Without this, their conversations would have no outcome and every metric would be missing them.

#### How it's checked
Interface tests against a temporary app database with the clock moved past the idle limit.

#### Acceptance criteria
1. An idle resolved conversation is contained
   Given a resolved conversation with no handoff, idle past the idle limit
   When a new conversation is started
   Then the idle one has outcome `contained`

2. An idle unresolved conversation failed
   Given an unresolved conversation idle past the limit
   When a new conversation is started
   Then it has outcome `failed` with reason `idle_unresolved`

3. A conversation with no message is left out
   Given a conversation that never received a message, idle past the limit
   When a new conversation is started
   Then it has outcome `failed` with reason `no_message`

4. An ended conversation is left alone
   Given a conversation ended by a handoff an hour ago
   When the sweep runs
   Then its outcome and `ended_at` are unchanged

5. A failed sweep never blocks a new conversation
   Given the sweep faked to fail
   When a new conversation is started
   Then the answer is still 201

#### Not in this story
- The sweep before the overview and the conversation list — picked up by S30 and S38

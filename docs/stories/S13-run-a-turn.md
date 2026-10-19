### S13 — Answer a message with the model, replaying the conversation exactly

**Kind:** module
**Blocked by:** S01
**Review gate:** agents
**Size:** L — the agent model on OpenRouter, and replaying its reasoning notes is not yet confirmed (open question 8)
**Builds:** Conversation → `sendMessage` (`POST /conversations/:id/messages`), its Calls out (agent model), the tool-calling loop, the `turns` table's write path, and these Must holds: replay is exact, every turn stores its fields, card-shaped text is removed before the model and the database
**Extends:** the `conversations` write path S12 owns (turn count, cost, intent)
**Stubs:** Safety and privacy (removed by S29); Knowledge (removed by S29); Scheduling (removed by S33); Follow-ups (removed by S32)
**Requirements:** OB-1 (turn fields), GC-3 (cost recorded)
**Guards:** PF-1, PF-2, CP-1

#### Why
This is the agent's loop: it sends the conversation to the model, runs the tools the model asks for, and logs every turn so the business view and the eval can read it.

#### How it's checked
Route tests with the other modules stubbed: most use the scripted fake model, and two use the real agent model.

#### Acceptance criteria
1. The real model answers with a tool
   Given the real agent model and Knowledge stubbed to return a passage stating the $89 diagnostic fee
   When I send "What is the diagnostic fee?"
   Then the reply mentions $89 and the turn's `tools_called` lists `search_knowledge`

2. The next turn replays the last one exactly
   Given the real agent model and one finished turn
   When I send a second message
   Then the provider accepts the request and the first turn's stored model messages were sent unchanged and in order

3. Every turn is stored whole
   Given a conversation of 3 messages
   When I read its turns
   Then each has latency, tools called, retrieved sources, cost and cost source filled
   And the conversation's turn count is 3 and its cost is their sum

4. The intent is recorded
   Given the model reports intent `book_visit` and then `membership_question`
   When I read the conversation
   Then `intent` is `membership_question` and `intents_seen` holds both in order

5. A card number never reaches the model or the database
   Given the scripted fake model recording what it receives
   When I send "My card is 4111 1111 1111 1111"
   Then the model received a placeholder saying a card number was removed and no run of 13 to 19 digits
   And the turn's stored caller text holds no run of 13 to 19 digits

#### Not in this story
- The agent tools and their injected arguments — picked up by S50
- The safety gate and the write rules — picked up by S14
- Failing safely within the time limit, one message at a time, and the outage switch — picked up by S43
- A failing screen, search or booking — picked up by S44
- What a reply may say — picked up by S45
- Sending each turn to Langfuse — picked up by S15
- Message length and per-conversation turn caps — picked up by S24

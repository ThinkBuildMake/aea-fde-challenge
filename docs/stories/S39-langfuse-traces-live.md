### S39 — Open any turn's trace in Langfuse from the business view

**Kind:** wiring
**Blocked by:** S38, S15
**Review gate:** human demo
**Size:** S — one seam: the live turn to Langfuse, linked from the conversation detail
**Wires:** Conversation → Calls out → Langfuse Cloud on the deployed app, and the "Open trace" link from `getConversation`'s `traceId` on the Conversations tab
**Extends:** none
**Requirements:** OB-1 (trace inspection, `STACK.md` §17), CP-1 (traces)
**Guards:** CP-1, PF-1

#### Why
A trace shows how a turn ran, step by step, with timing and cost. The builder tunes the agent with it and a reviewer can open any turn. Caller text in traces is scrubbed, and a Langfuse outage is invisible to callers.

#### How it's checked
Demo on the deployed URL with the Langfuse keys set:
1. Ask "Is the diagnostic fee $79?" in a new chat.
2. Open that conversation in `/business` → Conversations and click "Open trace" on a turn.
3. Send five card-shaped numbers, search Langfuse; point the Langfuse address at an unreachable host and ask a question.

#### Acceptance criteria
1. One trace per turn
   Given that conversation
   When I open its session in Langfuse, named by the conversation's public id
   Then there is one trace per turn, each with spans for the safety screen, every model call and every tool call, showing timing, tokens, cost and model

2. Linked from the business view
   Given that conversation open in the Conversations tab
   When I click "Open trace" beside a turn
   Then Langfuse opens that turn's trace

3. No card numbers leave the app
   Given five messages each containing a card-shaped number, including "4111 1111 1111 1111"
   When I search Langfuse for each number with and without spaces
   Then it finds 0 matches (CP-1: "0 card numbers appear in stored logs after sending 5 messages")

4. The secret id is never sent
   Given that conversation's secret id
   When I search Langfuse for it
   Then it finds 0 matches

5. A Langfuse outage never touches a turn
   Given the Langfuse address pointed at an unreachable host
   When I send "What is the diagnostic fee?"
   Then the reply states $89 within 6 s with no fallback text, and "Errors shown to callers" does not change

6. The gate checks the seam
   Given the regression gate with the real Conversation module and an in-memory trace recorder
   When it plays a recorded conversation with a card number
   Then each turn's `trace_id` names a recorded trace, and the trace holds no run of 13 to 19 digits
   And with the recorder failing, each turn still finishes with `trace_id` empty

#### Not in this story
- Eval runs as Langfuse experiments — picked up by S27 and S41
- After the first 50 conversations, the builder checks Langfuse's units used against the free tier (open question 14)

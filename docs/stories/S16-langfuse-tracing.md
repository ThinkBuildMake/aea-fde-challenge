### S16 — See every turn as a trace in Langfuse

**Blocked by:** S09, S12
**Review gate:** blocking — privacy-relevant: caller text leaves the app for an outside service
**Requirements:** OB-1, FR-5.3, CP-1, PF-1, `STACK.md` §17, `ARCHITECTURE.md` → Conversation → Calls out and Must hold, open question 14

#### Why
The business view shows what each conversation did. A trace shows how: what the safety screen decided, which model calls and tool calls ran, how long each took and what it cost. The builder uses it to tune prompts, and a reviewer can open any turn. The app's own tables stay the record, and traces carry no card numbers. If Langfuse is down, callers notice nothing.

#### What you'll see
1. With the Langfuse keys set, book a visit in the chat as Linda Foster.
2. Open `/business` → Conversations, click that conversation, and click "Open trace" on a turn.
3. Send five messages with card-shaped numbers, then search Langfuse for them.
4. Point `LANGFUSE_BASE_URL` at an unreachable host and send a message.
5. After the first 50 conversations, read the units used in Langfuse's usage page (open question 14).

#### Acceptance criteria
1. One trace per turn
   Given the Langfuse keys are set
   When I book a visit as "Linda Foster, 4412 Oak Hollow Dr."
   Then Langfuse shows one trace per turn, all in one session whose id is the conversation's public id, each with spans for the safety screen, every model call and every tool call, showing timing, tokens, cost and model

2. Linked from the business view
   Given the booking conversation is open in the Conversations tab
   When I click "Open trace" beside a turn
   Then Langfuse opens that turn's trace. This link is the one addition to the wireframe's detail panel, placed after "Tools called:"

3. `invariant` No card numbers leave the app
   Given five messages that each contain a card-shaped number, including "4111 1111 1111 1111"
   When I search Langfuse for each number with and without spaces
   Then it finds 0 matches (CP-1: "0 card numbers appear in stored logs after sending 5 messages")

4. `invariant` The secret conversation id is never sent
   Given the booking conversation's secret id
   When I search Langfuse for it
   Then it finds 0 matches

5. `invariant` A Langfuse outage never touches a turn
   Given `LANGFUSE_BASE_URL` points at an unreachable host
   When I send "What is the diagnostic fee?"
   Then the reply states $89 within 6 s with no fallback text (PF-1: "p95 time to first visible reply ≤ 6 s"), the turn's `trace_id` is empty, the "Errors shown to callers" tile does not change, and the log shows one warning

#### Not in this story
- Reporting eval runs to Langfuse as experiments: optional in `ARCHITECTURE.md`; the run record file stays the source of truth (DE-3)
- OpenRouter's Broadcast feed to Langfuse: not used, because it sends before the card scrubber runs

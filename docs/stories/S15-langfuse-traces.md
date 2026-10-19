### S15 — Send each turn to Langfuse as a scrubbed trace

**Kind:** module
**Blocked by:** S13
**Review gate:** agents
**Size:** L — first contact with Langfuse Cloud
**Builds:** Conversation → Calls out (Langfuse Cloud traces), the "traces carry only scrubbed text" Must hold, `turns.trace_id`
**Extends:** the turn S13 owns
**Stubs:** Safety and privacy; Knowledge (removed by S39)
**Requirements:** OB-1 (trace inspection, `STACK.md` §17), CP-1 (trace side)
**Guards:** CP-1, PF-1

#### Why
A trace shows how a turn ran: the safety screen, each model call and each tool, with timing, tokens and cost. Tracing must never leak a card number or the conversation's secret id, and never slow or break a turn.

#### How it's checked
Turn tests with the scripted fake model: against a Langfuse test project for the first criterion, and against an in-memory trace recorder for the rest.

#### Acceptance criteria
1. One trace per turn
   Given a Langfuse test project and a turn that calls `search_knowledge`
   When the turn finishes
   Then the project holds one trace in the session named by the conversation's public id, with spans for the screen, each model call and the search, each with timing, tokens and cost, and `turns.trace_id` names it

2. No card numbers in a trace
   Given a message "My card is 4111 1111 1111 1111"
   When its trace is recorded
   Then no span holds a run of 13 to 19 digits

3. No secret id in a trace
   Given any turn
   When its trace is recorded
   Then no span attribute equals the conversation's secret id

4. No raw model messages in a trace
   Given a turn whose model reply carries reasoning notes
   When its trace is recorded
   Then no span holds the reasoning notes or the raw model messages

5. A Langfuse outage never touches a turn
   Given the Langfuse address unreachable
   When I send "hello"
   Then the reply arrives with `fallback_used` 0, the turn's `trace_id` is empty, and one warning is logged

#### Not in this story
- The "Open trace" link in the business view — picked up by S23
- Traces from the live chat — picked up by S39

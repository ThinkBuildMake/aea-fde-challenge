### S24 — Abuse limits, security headers and five chats at once

**Kind:** module
**Blocked by:** S12, S13, S19, S46
**Review gate:** agents
**Size:** M — system-wide rules on the routes, with one gate test
**Builds:** System-wide → Rate and size limits (per-address caps on new conversations, messages and business-view writes; the per-conversation turn cap with its fixed text; the message length cap; empty messages), Security headers and cross-origin, Concurrency (`/health` never waits behind a turn); the regression gate's five-simultaneous-conversations test (SC-1)
**Extends:** `sendMessage` (S13), `startConversation` (S12) and the business-view write routes (S46, S19)
**Stubs:** Safety and privacy, Knowledge, Scheduling and Follow-ups (removed by S37, which runs the real modules with the caps on)
**Requirements:** SC-1 (latency part; the booking-invariant part is S33-7), GC-3 (runaway-spend protection)
**Guards:** SC-1, CO-1, PF-1

#### Why
The app runs unattended at a public URL until 2026-11-05. An anonymous visitor cannot run up the model bill, and the page cannot be framed or fed scripts from elsewhere.

#### How it's checked
Route tests with the caps set low, a header check on every page and route, and a gate test running five conversations against the fake provider.

#### Acceptance criteria
1. Too many messages from one address
   Given the per-address message cap set to 5 a minute
   When one address sends 6 messages in a minute
   Then the sixth answer is 429 `rate_limited`

2. Too many new conversations
   Given the per-address cap on new conversations set to 3
   When one address starts 4
   Then the fourth answer is 429 `rate_limited`

3. A conversation cannot run forever
   Given the turn cap set to 4
   When a fifth message is sent
   Then the answer is 409 `turn_limit_reached`, and the conversation's outcome is `failed` with reason `turn_cap`
   And the fourth reply ended with "This conversation has reached its limit. Please start a new conversation, or ask for a call back."

4. A long message is refused
   Given the length cap
   When I send a message one character over it
   Then the answer is 413 `message_too_long`

5. An empty message is refused
   Given the app running
   When I send a message of only spaces
   Then the answer is 422 `empty_message`

6. Security headers on every response
   Given the app running
   When I request `/`, `/business` and `/overview`
   Then each response carries a content policy allowing only the app's own scripts and styles, no framing, no content sniffing and a referrer policy

7. No cross-origin access
   Given a request with `Origin: https://example.org`
   When it calls `POST /conversations`
   Then the response carries no `Access-Control-Allow-Origin` header

8. Five chats at once stay fast
   Given the fake provider and the stubbed modules
   When the gate runs 5 conversations at once
   Then their p95 reply time is within 1.5 times the single-conversation p95 (SC-1: "p95 latency within 1.5× the single-conversation p95")
   And `/health` answers within 1 s throughout the run

#### Not in this story
- Showing the turn-cap text on the chat screen with a real model — picked up by S37

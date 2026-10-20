### S53 — Offer and join the waitlist in code, typed or tapped

**Kind:** module
**Blocked by:** S52
**Review gate:** agents
**Size:** S
**Builds:** Conversation → earlier-window detection and the waitlist join after a booking
**Requirements:** the booking use case's earlier-window path (BK-2), VR-1
**Guards:** no waitlist row the caller did not agree to; no promise of a call about an earlier window without a waitlist row

#### Why
The earlier-window flow keys on exact button text: `EARLIER_CHOICE.text` ("Can you do anything earlier?") turns on the waitlist offer, and a booking message ending in `JOIN_SUFFIX` makes the model *asked* (by instruction) to call `join_waitlist`. In the final S51/S52 eval run A, BK-2's caller typed "Is there anything earlier possible?", so no offer was made; the model said "if an earlier time opens up due to a cancellation, we can let you know", and "Okay, do that, and book the slot for Wednesday from 8 AM to 12 PM." booked with no waitlist row. One booking miss costs 14.3 points of projected containment. The human asked for this to be fixed in deterministic code (2026-10-20).

#### Acceptance criteria
1. A typed earlier request counts like the button
   Given a matched caller who has been shown windows
   When they write "Is there anything earlier possible?", "anything sooner?", "Do you have anything earlier?" or "Can you do anything earlier?"
   Then `wants_earlier` is true for the turn (earliest windows, `EARLIER_INSTRUCTION`, the three waitlist choices); and "I want an earlier start time on Wednesday", "earlier you said Wednesday" and "can I book Wednesday?" do not count

2. The app records the offer
   A turn where `wants_earlier` was true stores that the waitlist was offered (in `turns.offered`), the way cancel asks are stored

3. Accepting the offer joins in code
   Given the previous turn offered the waitlist
   When the caller's message books a window (the model calls `book_visit` and it commits) and the message accepts the offer — it ends with `JOIN_SUFFIX`, or contains a plain acceptance such as "do that", "yes", "both", "sounds good", "and the waitlist", "add me", with no refusal ("no", "not", "don't", "only", "just book", "without")
   Then the app itself joins the waitlist for that booking in the same turn (one row, the booked window held), whether or not the model calls `join_waitlist`; a second join for the same caller and visit type stays a no-op as today

4. Declining does not join
   "Book Wednesday 8 AM only", "just book it", "no waitlist, just book Wednesday" and a booking with no prior offer write no waitlist row

5. Live: BK-2 passes; BK-1 still passes

#### Not in this story
- Changing the waitlist table, the follow-ups module, or the choices' labels
- A guard that rewrites waitlist promises in replies (later, if 1–3 do not stop them)

## Plan

### Criterion map
| AC | Test |
|---|---|
| 1 | `tests/` unit cases for the new earlier-request matcher, plus a turn test that a typed request gets the waitlist choices |
| 2–4 | turn tests with the scripted fake model (`tests/test_turn.py` helpers; find the existing waitlist and JOIN_SUFFIX tests with `grep -rln "JOIN_SUFFIX\|join_waitlist" tests`) |
| 5 | live (orchestrator) |

### Subtask
1. Files: `app/conversation/tools.py` (`wants_earlier`, `_find_open_windows`, `_book_visit`, `ToolState` offered/load), `app/conversation/guards.py` (the matcher and acceptance regexes, plus a lookback like `last_cancel_asks`), `app/conversation/turn.py` only if the offer flag must be stored there; tests. Reuse `_join_waitlist`'s logic for the app-side join rather than duplicating it.

### Constraints
- Deterministic code; no prompt-only fix. No new dependency.
- Gate: ruff check, ruff format --check, pyright, pytest (gitleaks fails on known eval/runs tokens).
- Commits `S53: <what>` with the Co-Authored-By trailer.

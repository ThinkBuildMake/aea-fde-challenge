### S51 — Fix the agent faults that repeat across the S41 eval pair

**Kind:** module
**Blocked by:** S41
**Review gate:** agents
**Size:** S — one guard fix and two prompt sections
**Builds:** the cancel confirmation guard (Conversation), the billing and warranty rules in the agent instructions
**Requirements:** VR-1 (projected containment ≥ 60%), FR-1.10 to 1.12 (cancel), the billing and warranty use cases
**Guards:** no committed cancel without the caller's clear yes to terms they saw; no dollar figure the tools did not return; no promised waiver

#### Why
Both S41 runs (`eval/runs/run-20261020T022640Z-230217.json`, `run-20261020T022920Z-4ec2a2.json`, commit `091bddf`) project 26.8% and 36.5%, under the 60% floor. Four failures repeat in both runs and are agent faults, not scenario bugs (`docs/HANDOFF.md`, `eval/human_grades.json`):

- **AP-2:** the caller says "I accept the fee, please go ahead and cancel it. That is all." after asking a question about the terms. The visit is never cancelled. `guards.clear_yes` splits sentences on `.`, `!` and `;` only, so a comma-joined acceptance never starts a sentence with a yes. Also, `guards.last_cancel_asks` reads only the previous turn, so a question between the terms and the yes drops the ask unless the model re-calls `cancel_visit`.
- **BI-1, BI-2:** the agent gives the balance and invoice id but not the issued date, the due date, or whether the invoice is paid. `get_my_billing` returns all of them; the instructions only ask for "the balance with each open invoice id".
- **WA-1:** the agent answers the general rules and never uses the caller's record (`identify_customer` returns `system_brand` and `system_install_date`). It misses "Meridian registers every installed unit" and "the 2-year installation labor warranty ended in May 2025".
- **WA-2:** the agent does not check the caller's earlier Meridian repair (invoice INV-202738, 2026-07-14, via `get_my_billing`). It does not say the older rule the caller quotes is out of date, and it quotes the $89 diagnostic fee instead of "the return visit and labor are free" for a covered repeat failure.

#### How it's checked
Turn tests with the scripted fake model (`tests/test_turn.py` helpers) for the guard; prompt-carries-rule tests for the instructions; then live runs of the failing scenarios and the full eval pair.

#### Acceptance criteria
1. A comma-joined acceptance confirms a cancel
   Given the previous turn put appointment 25's terms (the $49 late fee) to the caller
   When the caller writes "I accept the fee, please go ahead and cancel it. That is all."
   Then `clear_yes` is true and the model's `cancel_visit` call cancels the visit

2. A question about the terms does not lose the ask
   Given turn 1 put appointment 25's terms to the caller, and in turn 2 the caller asks "don't I need to give 48 hours notice?" and the model answers with the $49 fee and a confirm question without calling `cancel_visit`
   When in turn 3 the caller writes a clear yes and the model calls `cancel_visit`
   Then the visit is cancelled; and if turn 2's shown reply does not state the $49 fee, the turn 3 yes does not cancel

3. Still not a yes
   "don't I need to give 48 hours notice?", "can you waive the fee?", "ok but only if there's no fee" and "I'm not sure" stay not-a-clear-yes (existing cases keep passing)

4. Billing answers carry the invoice dates
   The instructions tell the agent to give, for each open invoice, its id, balance, issued date and due date; and when explaining an invoice, its total, issued date, whether it is paid or unpaid, and every line item with its amount

5. Warranty answers use the caller's record
   The instructions tell the agent, for a warranty question about the caller's own system, to identify the caller first, then use `system_brand` and `system_install_date` from the match and the caller's earlier Meridian repairs from `get_my_billing`; to work out from today's date whether the 2-year installation labor warranty (or a 1-year repair labor warranty on the same part) is still running and say the date it ended or ends; to say Meridian registers every installed unit when the parts warranty depends on registration; when the caller quotes an older rule, to say it is out of date and give the current one without repeating the caller's figure; and, for a covered repeat failure, to say the return visit and labor are free instead of quoting the diagnostic fee

6. Live: the five scenarios pass
   AP-2, BI-1, BI-2, WA-1 and WA-2 are contained-correct on a live eval run of those scenarios

#### Not in this story
- Changing any eval scenario, the judge, or the weighting
- New tools or new fields on tool results
- BK-2, ME-2, T-1, T-3 (they flip between runs)

## Plan

### Criterion map
| AC | Test |
|---|---|
| 1 | `tests/test_cancel_confirm.py::test_comma_joined_acceptance_cancels` (new) plus a `clear_yes` unit case |
| 2 | `tests/test_cancel_confirm.py::test_question_between_terms_and_yes_keeps_the_ask`, `::test_question_turn_without_the_fee_drops_the_ask` |
| 3 | existing `clear_yes` tests (find them with `grep -rn clear_yes tests`) plus the four quoted cases |
| 4 | `tests/gate/test_booking_instructions.py` new test that INSTRUCTIONS carries "issued date", "due date", "paid or unpaid", "every line item" |
| 5 | same file: INSTRUCTIONS carries "system_install_date", "get_my_billing", "registers every installed unit", "return visit and labor are free", "out of date" |
| 6 | live: `uv run python -m app.evals.run --scenarios <dir with the five>` (orchestrator) |

### Subtasks
1. **Cancel confirmation** — Satisfies AC1–3. Files: `app/conversation/guards.py`, `app/conversation/tools.py`, `app/conversation/turn.py` (only the `keep_cancel_asks` call site near the end of the turn, never `INSTRUCTIONS`), `tests/test_cancel_confirm.py`. Approach: in `clear_yes`, also treat commas as clause breaks when looking for the yes, keeping every `_NOT_YES` and fee-acceptance check on the whole text. For AC2, a turn whose shown reply states each still-pending ask's fee and does not cancel carries the previous turn's cancel asks forward into its own `offered.cancelAppointmentIds` (so `last_cancel_asks` stays a one-turn lookback); a reply that does not state the fee drops them.
2. **Billing and warranty instructions** — Satisfies AC4–5. Files: `app/conversation/turn.py` (`INSTRUCTIONS` only), `tests/gate/test_booking_instructions.py`. Keep every rule string other tests assert on (`grep -rn INSTRUCTIONS tests`). Edit the existing "Billing:" and "Warranty coverage" paragraphs; do not add a new section elsewhere. The "never repeat the caller's figure" and "never promise a waiver" rules stay; "the return visit and labor are free" is the policy's own wording, stated as policy.

### Constraints
- No new dependency. No scenario, judge or weight change.
- Regression gate: `make gate` (needs `gitleaks` on PATH; if it is missing, run every gate step except the secret scan and say so).
- Commits: `S51: <what>`. Linear history; never commit `.demo/`.

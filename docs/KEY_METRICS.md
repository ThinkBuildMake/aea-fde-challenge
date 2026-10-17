# KEY_METRICS.md — Meridian AI Call Agent

## What success means

Every supplied call goes to one of eight human agents, and the PRD says that call center is capacity constrained: wait times are high and staff cannot keep up (`USERS.md` §2, taken from the PRD, not confirmed by the data). About 65% of calls are routine needs that Meridian's own documents already answer (`USERS.md` §2, §6).

Success means a caller with a routine need gets it settled correctly in one conversation, without waiting for a person, and everyone else is handed over cleanly.

## Success metric: Calls settled by the agent

**What is it?** The percentage of conversations the agent settles correctly with no human involved. A conversation counts when it ends with the need met (a booking made, a question answered, a payment link sent) and nobody has flagged it as wrong.

**How we measure it.** Contained conversations that were not flagged wrong ÷ all conversations, over a rolling 7 days. "Contained" is the outcome the system records on every conversation (OB-1). "Flagged wrong" is the reviewer or staff flag (FR-5.4). Before release the same ratio is computed on the eval set, where the expected answer and database change are known (VR-1, EV-3).

**Target.** Today 0% of calls are settled without a person; target 60% to 75% [src PRD-5, VR-1]. The ceiling with the first-iteration features is about 65% (274 of 420 provisionally labelled calls, VR-1); the final clustering may move it.

**Why it shows the need was met.** It counts only conversations where the caller's need was met, so a confident wrong answer and a dead end both lower it. A chat that simply ends with no handoff does not count.

**What it can't tell you.** Callers who give up quietly, and wrong answers nobody flags, look like successes; the eval set's measured accuracy (VR-4, VR-5) is how that gap is covered before release.

### Supporting metrics

| Metric | What it is | Recorded from | Why it explains the success metric |
|---|---|---|---|
| **Booking completion** | Share of conversations that asked for a visit and ended with a confirmed booking. | Intent label (OB-1) and the `appointments` row | Bookings are the largest group, 28.6% of calls (`USERS.md` §2). If settled calls drop and this dropped too, look at slot offers and the booking flow. |
| **Handoffs on handled topics** | Share of conversations about a handled topic (visits, fees, membership, warranty, hours, billing lookup) that ended in a handoff, with the reason. | Outcome and handoff reason (OB-1, OB-3) | If settled calls drop and this rose, the agent is declining things it should answer: look at the knowledge base and the "not sure" rule. |
| **Flagged-wrong rate** | Share of contained conversations flagged wrong. | Flags (FR-5.4) | If settled calls drop and this rose, answers are getting worse: look at the newest knowledge-base change. |

## Guarantee metrics

| Metric | Requirement | Threshold | Measured on | Recorded from |
|---|---|---|---|---|
| **Time to first reply** | PF-1 | p95 ≤ 6 s | First reply of every conversation, rolling 24 h and every eval run | Per-turn latency (OB-1) |
| **Time for a turn that books, moves or cancels** | PF-2 | p95 ≤ 10 s | Every turn with a database write, rolling 24 h and every eval run | Per-turn latency and tool calls (OB-1) |
| **Booking mismatches** | VR-6, VR-7, VR-8, DE-2 | 0 | A daily query over all bookings: slot and appointment row agree, no blocked, taken, wrong-zone or non-member slots, and every confirmation matches its row | `appointments`, `appointment_slots`, confirmation tool calls |
| **Errors shown to callers** | DE-1 | 0 unhandled errors; fallback message within 10 s of a model failure | Every conversation with a provider error or timeout, rolling 24 h | Error log and failure outcome (OB-1, OB-3) |
| **Uptime of the public URL** | DP-2 | ≥ 99% through 2026-11-05 | External ping every 5 minutes | Ping log |
| **Total model spend** | CO-1 | Alert at $100 cumulative | Running total of per-conversation cost | Cost field (OB-1), provider billing export |

## Upstream fixes and open questions

- Flagging is a Should (FR-5.4) but the success metric needs it → raise FR-5.4 to Must. Add a one-tap "did this solve it?" at the end of a contained conversation as a new FR-5 row, so settled calls rest on a recorded caller action, not only on flags.
- Contained-wrong ≤ 2% (VR-5) cannot be counted live without a person judging each case → stays an eval-set check (rerun after each knowledge-base change, CH-2).
- Booking completion and Handoffs on handled topics have no target → set after the first week of live and eval data.
- The 65% ceiling and the intent labels behind the supporting metrics depend on the final discovery clustering (EV-6).
- Safety, privacy and "never promise a fee waiver" rows (AZ-, VR-2, VR-3, CP-1) are tests that gate release, not tracked here.

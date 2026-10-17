# KEY_METRICS.md — Meridian AI Call Agent

## What success means

Every supplied call goes to one of eight human agents, and the PRD says that call center is capacity constrained: wait times are high and staff cannot keep up (`USERS.md` §2, taken from the PRD, not confirmed by the data). About 65% of calls are routine needs that Meridian's own documents already answer (`USERS.md` §2, §6).

Success means a caller with a routine need gets it settled correctly in one conversation, without waiting for a person, and everyone else is handed over cleanly.

## Success metric: Calls settled by the agent

**What is it?** A count and a percentage: how many conversations the caller marked "solved" after the agent finished, out of all conversations. One conversation counts when the agent ended it with no handoff and the caller tapped "yes, that solved it" (FR-5.6).

**How we measure it.** Conversations with outcome contained (OB-1) and a recorded "solved" tap ÷ all conversations, over a rolling 7 days; the raw count is shown beside it. Nobody judges anything: both pieces are events the system records. Before release a projected version of the same ratio is computed from the 31 key scenarios, weighted by the call mix (VR-1, EV-3).

**Target.** Today 0% of calls are settled without a person; target 60% to 75% [src PRD-5, VR-1]. The ceiling with the first-iteration features is about 65% (274 of 420 calls, `AUDIT.md` §3). Live callers who skip the tap count as not settled, so the live number reads low; the projection from the key scenarios is the reference.

**Why it shows the need was met.** It counts only conversations where the caller said their need was met, so a wrong answer, a dead end and a quiet abandonment all fail to count.

**What it can't tell you.** A caller can tap "solved" on a wrong answer; the key scenarios' accuracy (VR-4, VR-5) covers that before release, and flags catch some live.

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

- Add FR-5.6, a one-tap "did this solve it?" at the end of a contained conversation (done in `REQUIREMENTS.md`), and raise FR-5.4 flagging to Must (done).
- Contained-wrong (VR-5, 0 in the 31 scenarios) cannot be counted live without a person judging each case → stays an eval check (rerun after each knowledge-base change, CH-2).
- Booking completion and Handoffs on handled topics have no target → set after the first week of live and eval data.
- Ceiling is 65.2% on the handled drivers, up to 71.7% with burning-smell and scripted-redirect calls (`AUDIT.md` §3); the intent labels behind the supporting metrics still need the EV-6 second read.
- Safety, privacy and "never promise a fee waiver" rows (AZ-, VR-2, VR-3, VR-9, CP-1) are tests that gate release, not tracked here.

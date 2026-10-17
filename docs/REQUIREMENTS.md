# REQUIREMENTS.md — Meridian AI Call Agent

**Status:** draft (becomes `v1.0 — handed to architecture <date>` at handoff; row changes after that bump the version)

**Purpose.** Turn the problem statement (the PRD, `docs/AEA_FDE_Challenge.pdf`) and the users doc (`docs/USERS.md`, with `docs/USERS_handoff.md`) into testable requirements and constraints with numeric thresholds, so the key-metrics doc can measure against these numbers, the stack doc can choose technology against them and the architecture doc can design to them. Every requirement traces to a use case, a PRD goal, a dataset finding, or a given constraint.

**Scope.**

*This document decides:* what the agent must do per use case in the first iteration (USERS §6, features 1 to 7), the "must never" rules, numeric thresholds for quality attributes (authorization, correctness, performance, reliability, observability, compliance, evaluation, cost, deployment), how each is verified, and what is out of scope by design. Later iterations (USERS §6) get rows only as boundaries ("not in v1").

*This document defers:*
- Technology choices and their tradeoffs → the stack document.
- Modules, schemas, contracts, data flow, and the techniques used to meet a budget (chunking, retrieval, caching, parallelism) → the architecture document and the high-level design.
- Why the problem exists and where the cut line is → the PRD and USERS §2, §3, §7.
- Flows, personas and call-mix figures → USERS (cited, not restated).
- Which requirements become tracked metrics and dashboards → the key-metrics document.

If a row below names a library, a component, or a way of meeting a threshold, it is in the wrong document.

**How to read a requirement.**

| Field | Meaning |
|---|---|
| **Requirement** | *Functional:* from the caller's side (or the business's, in FR-5): what they do, what they expect back, what they are refused. No number. *Non-functional and given:* from the system's side; the requirement is the number itself, tagged. |
| **Verified by** | Non-functional and given rows only: the eval, test, query or config review that proves it. Functional rows are verified by seeing or using the feature in the demo. |
| **Trace** | `U§n` = USERS.md section n; `UC-n` = use case; `A-n` = USERS assumption; `PRD-n` = PRD required goal n; `D-n` = dataset finding (Definitions and §5 list them). |
| **Priority** | **Gate** = must hold before real caller data. **Must** = required for the product to be done. **Should** = required unless a documented tradeoff says otherwise. This document does not cut scope for the deadline; if a Gate or Must is deferred, the human decides when the stories are written. |

**Where the numbers come from.** **[src]** = from a cited source, or computed from one with the arithmetic shown. **[prop]** = proposed engineering target, the builder's to change with a stated reason. **[tbd]** = cannot be set until a measurement exists. Section 5 lists every [prop] and [tbd].

**Assumptions.** USERS §9 (A1 to A12) is the assumption set; no stakeholder is available to confirm it. One addition made here: **A13 — the payment link is a stub.** No payment system was supplied, so "send a payment link" means returning a generated link string that is logged; no money moves. Removes real payment processing from scope.

**Definitions.**

| Term | Meaning |
|---|---|
| Conversation | One chat session from the first caller message to the agent's last message or a handoff. The unit counted for containment (the dataset's unit is one call, so one scenario = one call). |
| Scenario | One test case in the eval set, built from one supplied transcript or written as an adversarial probe. Has an expected outcome and expected facts. |
| Outcome | Exactly one of: **contained** (need met, no handoff), **handoff** (clean transfer or supervisor callback), **safety stop** (told to leave and call 911), **failed** (error, dead end, or wrong action). |
| Contained-correct | A contained conversation whose answer facts and any database change match the scenario's expectations. **Containment rate** in this document means contained-correct conversations ÷ all scenarios [src A2]. A contained but wrong conversation counts against it. |
| Current document | A knowledge-base file outside `archive/`, not named `*old_copy*`, and not `scheduling_guide.md` (Rev 2024-11) where it conflicts with the 2026 FAQ [src A4]. |
| Superseded value | A fact stated only in an archive/old-copy/2024 file and contradicted by a current document: $79 diagnostic fee, 90-day repair warranty, $149 membership, 48-hour cancellation [D-1]. |
| Handoff record | The structured summary a human receives: caller identity (if matched), intent, what the agent told the caller, reason for handoff, and a preferred callback window when relevant. |
| Supervisor callback | The documented path for disputes, refunds, complaints and manager requests: a callback within 1 business day [src U§3]. |
| Zone | north / central / south, derived from the caller's city per `SCHEMA.md` [D-2]. |
| Open slot | A row in `appointment_slots` with status `open` (or `reserved_members` for a standard/plus member) matching zone and service type. |

**Dataset findings referenced (D-n).** D-1 conflicting superseded KB files; D-2 zone mapping and no plumbing slots in the north zone; D-3 holiday hours only in a PNG; D-4 fee schedule only in a PDF; D-5 internal agent notes in `internal/`; D-6 66 Sunday-timestamped calls vs. closed Sunday; D-7 scheduling guide (48 h) vs. FAQ (24 h) cancellation; D-8 four seeded test customers MHC-10001 to MHC-10004 and slots 2026-10-16 to 2026-11-05.

---

## 0. Requirements summary (one screen)

| Area | Headline threshold |
|---|---|
| Containment | 60% to 75% contained-correct on the eval set [src PRD-5]; reported with a 95% interval (±4.6 points at n = 420) |
| Safety | 0 bookings in any gas/CO/sparks/smoke scenario; ≥ 35 safety scenarios [prop] |
| Correctness | 0 superseded values stated across trap probes; ≥ 90% fact accuracy on handled drivers [prop] |
| Booking integrity | Every confirmed booking = exactly 1 `booked` slot + 1 `appointments` row; 0 double bookings |
| Privacy | 0 cross-account disclosures, 0 card numbers accepted or stored, 0 internal-note leaks |
| Escalation | ≥ 95% of must-escalate scenarios reach a handoff record [prop]; 100% of handoffs carry the full record |
| Latency | p95 first reply ≤ 6 s; p95 turn with a database write ≤ 10 s [prop] |
| Observability | Volume, containment, escalations, failures, latency visible with ≤ 1 min lag [prop] |
| Deployment | Public URL, no login; up through 2026-11-05; due 2026-10-21 11:59 PM Central |

---

## 0a. Key decisions

| # | Decision | Alternative rejected | Where |
|---|---|---|---|
| 1 | Containment counts only *correct* resolutions. | Counting any chat without a handoff, which rewards confident wrong answers. | VR-1, EV-3 |
| 2 | Safety screening precedes every other action, on every message. | Classifying intent first and screening only booking intents. | FR-1.1, FR-1.2, VR-2 |
| 3 | Newest current document wins; unresolved conflict → handoff. | Always handing off on conflict (lowers containment); picking silently. | FR-2.2, FR-2.6, VR-3 |
| 4 | Disputes, double-charge claims, refunds, complaints and manager requests go to a supervisor callback, never explained away. | Letting the agent explain double charges (the FAQ allows it). | FR-3.5, FR-4.3 |
| 5 | Reschedule/cancel/confirm in v1. | Later iteration (ceiling ≈ 58%, below the 60% floor). | FR-1.10 to 1.12 |
| 6 | The eval set is built from the supplied transcripts plus separately authored adversarial probes. | Transcripts only, which cannot test traps or attacks. | EV-1, EV-4, EV-5 |
| 7 | Bookings write to the supplied database as the reviewer will see it. | A separate booking store. | GC-6, CT-1 |

---

## 1. Givens

### 1.1 Given constraints (GC-)

| ID | Requirement | Verified by | Trace | Priority |
|---|---|---|---|---|
| GC-1 | Deployed and reviewable by **Wed 2026-10-21 11:59 PM US Central** [src U§8, builder]. If half done, build order: booking flow, knowledge-base answers and eval numbers first, then handoff, then monitoring view, then later iterations. | Deployed URL answering a booking request and a policy question before the deadline; commit timestamps | U§8 | Must |
| GC-2 | One builder; the deliverable set is exactly three: public URL, walkthrough video of 3:00 to 4:00 minutes, and a source repository with README and eval numbers [src PRD, U§8]. | Video length read from file metadata; the video covers four topics (how the drivers were found, chunking and retrieval choices, how escalation works, what the eval numbers say) [src PRD deliverable 2], checked against a four-item list; README contains how to run it plus containment, accuracy and escalation numbers | PRD deliverables | Must |
| GC-3 | Spend has no cap [src builder, 2026-10-16]; per-conversation and cumulative spend are still recorded (see CO-1). | CO-1 | U§8 | Should |
| GC-4 | Every paid service is from the approved list (Anthropic, Aqua Voice, Cohere, Cursor, DigitalOcean, ElevenLabs, Google One, Midjourney, OpenAI, OpenRouter, Railway, Vultr, Whisper) or is used on a free tier [src builder]. 0 off-list paid services. | Dependency/service inventory in the README reviewed against the list | U§8 | Must |
| GC-5 | The product is a web app at a public URL; chat is the baseline and voice is excluded from v1 [src PRD-6, builder 2026-10-16]. | Opening the URL in a clean browser | PRD-6, U§7 | Must |
| GC-6 | Integrates with the supplied scheduling database (SQLite, `SCHEMA.md`) and knowledge base as they are. Bookings really write: the reviewer tests against the same data and seeded customers MHC-10001 to MHC-10004 [src PRD, D-8]. | CT-1, FR-1 demo | PRD-3 | Must |
| GC-7 | Internal demo; synthetic company and data; no regulatory scope [src builder]. Nothing in this document is a compliance claim. | Config review | U§8 | Should |
| GC-8 | Scheduling reference date ("today") is 2026-10-16 and slots run 2026-10-16 to 2026-11-05 [src D-8]. | CT-3 | PRD, dataset README | Must |

### 1.2 Dependencies and environment (DE-)

| ID | Requirement | Verified by | Trace | Priority |
|---|---|---|---|---|
| DE-1 | If the language-model provider fails or times out, the caller sees a plain message and an offer of a human within 10 s [prop]; 0 unhandled exceptions shown to a caller. | Fault injection: block the provider, send 10 messages | PRD-4 | Must |
| DE-2 | If the scheduling database is unreadable or a write fails, the agent never states a booking is confirmed (0 false confirmations) and offers a handoff within 10 s [prop]. | Fault injection on read and on write | U§5 UC-1 must-never | Gate |
| DE-3 | The run environment (model names and versions, knowledge-base index version, database snapshot id) is recorded on every eval run, and the eval reruns from a clean checkout following the README. | Eval output file contains all four fields; clean-clone run reproduces counts within the stated interval | PRD-5 | Must |

---

## 2. Functional requirements

*Every row is verified by a user seeing or using the feature in the demo. What the system must accommodate for each row is in §3, traced back here.*

### FR-1 Visits: book, check, move, cancel (UC-1)

| ID | Requirement | Trace | Priority |
|---|---|---|---|
| FR-1.1 | A caller who mentions a gas smell, carbon monoxide alarm, sparks or smoke is told immediately to leave the home and call 911 (or the gas utility from outside); no booking is offered. | UC-1, U§6 #1 | Gate |
| FR-1.2 | A caller who mentions only a burning smell is asked whether there is smoke, sparks or a tripped breaker before any window is offered; yes or "not sure" leads to the FR-1.1 message, no leads to normal booking. | UC-1, A9 | Gate |
| FR-1.3 | The caller is identified by name and phone number; no account detail is shown before a match. | UC-1, UC-3, U§6 #2 | Gate |
| FR-1.4 | When no account matches, the caller is told so and handed off; no account is created. | A6 | Must |
| FR-1.5 | The caller describes the problem in plain words and the agent tells them which visit type it is booking (HVAC repair, tune-up, plumbing or estimate). | UC-1 | Must |
| FR-1.6 | The caller is told when their city is outside the service area and nothing is booked. | UC-1 | Must |
| FR-1.7 | The caller hears open windows for their zone and visit type with date, window and technician name; if the requested day has none, the nearest alternatives. | UC-1, PRD-3 | Must |
| FR-1.8 | Member-only slots are offered only to standard or plus members. | UC-1, D-2 | Must |
| FR-1.9 | A north-zone plumbing caller is told no plumber is available in their area right now and is handed off; nothing is booked across zones. | A10, D-2 | Must |
| FR-1.10 | A visit is booked only after the caller says yes to a specific window; the confirmation gives date, window, technician and the $89 diagnostic fee (credited toward repair, waived for members), said once. | UC-1 | Must |
| FR-1.11 | A caller with a visit on file hears its date, window and technician, and can move it to another open window; the old window becomes available. | UC-1, A8 | Must |
| FR-1.12 | A caller can cancel a visit only by explicitly saying so; the agent states the fee (free beyond 24 hours, $49 inside 24 hours) and does not waive or promise to waive it. | UC-1, A7 | Must |
| FR-1.13 | No repair price is quoted; the caller is told the technician confirms pricing on site, and only the diagnostic fee is stated. | UC-1, UC-2 | Gate |
| FR-1.14 | A caller who cannot be booked is told what happens next; no conversation ends without a next step. | UC-1 | Must |

### FR-2 Answers: fees, membership, warranty, hours, service area (UC-2)

| ID | Requirement | Trace | Priority |
|---|---|---|---|
| FR-2.1 | The caller gets a short answer to fee, membership, warranty, hours and service-area questions, with the condition that matters. | UC-2, U§6 #4 | Must |
| FR-2.2 | Answers use current documents only; a superseded value is never stated. | UC-2, A4, D-1 | Gate |
| FR-2.3 | Hours answers match the current FAQ (Mon to Fri 7 AM to 7 PM, Sat 8 AM to 4 PM, closed Sunday) and the 2026 holiday schedule held only in the image. | A11, D-3, D-6 | Must |
| FR-2.4 | Fee answers match the 2026 fee schedule held only in the PDF. | D-4 | Must |
| FR-2.5 | Warranty answers distinguish the manufacturer warranty, Meridian's repair warranty and the membership, and ask for the detail that decides (brand, age, part or labor) when needed. | UC-2 | Must |
| FR-2.6 | When current documents do not settle a question, or two disagree, the caller is told the agent is not sure and is handed off; the agent never picks one. | UC-2, A4, D-7 | Gate |
| FR-2.7 | Content from `internal/` agent notes is never read or paraphrased to a caller. | UC-2, D-5 | Gate |
| FR-2.8 | The agent never promises a refund, a waiver or a price the account is not entitled to. | UC-2, A7 | Gate |
| FR-2.9 | A caller who asks two things in one call (for example, a booking and a membership question) gets both answered in the same conversation. | U§3 Reason 3 | Must |
| FR-2.10 | Membership changes (autopay, cancel auto-renew, upgrade) are explained, then handed off; not performed in v1. Boundary: later-iteration #1. | U§6 later #1 | Must |
| FR-2.11 | Commercial, employment, duct-cleaning and appliance requests get "we don't offer that" or the documented redirect and, otherwise, a handoff. Boundary: later-iteration #3. | A12 | Should |

### FR-3 Billing (UC-3)

| ID | Requirement | Trace | Priority |
|---|---|---|---|
| FR-3.1 | A matched caller hears their own balance and open invoices. | UC-3, U§6 #5 | Must |
| FR-3.2 | A caller can ask what an invoice line is and gets it in plain words. | UC-3 | Should |
| FR-3.3 | A caller who wants to pay is sent a payment link; the agent never asks for or accepts a card number. | UC-3, A13 | Gate |
| FR-3.4 | A caller never sees or hears another customer's account. | UC-3 | Gate |
| FR-3.5 | A caller who disputes an amount or says they were charged twice is not argued with; the agent takes a preferred callback window and states a supervisor will call within 1 business day. May mention the FAQ's pending-authorization note. Boundary: later-iteration #5. | A5, U§6 #7 | Must |

### FR-4 Handoff (all use cases)

| ID | Requirement | Trace | Priority |
|---|---|---|---|
| FR-4.1 | Before any handoff the caller is told that a person will take over, why, and what happens next. | PRD-4 | Must |
| FR-4.2 | The person receiving the handoff sees a handoff record and does not need to ask the caller to repeat the story. | PRD-4, U§6 #7 | Must |
| FR-4.3 | Complaints, refund demands and manager requests produce a supervisor callback request, not an attempted resolution. | U§3, A5 | Must |
| FR-4.4 | A caller who asks for a person at any point is handed off. | PRD-4 | Must |
| FR-4.5 | Requests outside the handled drivers (new-system quotes, late technician, account creation) are handed off rather than answered from guesses. | PRD-4, U§6 later #2, #4 | Must |

### FR-5 Interface and business view (PRD-6, PRD-7)

| ID | Requirement | Trace | Priority |
|---|---|---|---|
| FR-5.1 | A reviewer opens a public URL, types messages, and sees the agent's replies, including a visible indication when the conversation has been escalated or ended in a safety stop. | PRD-6 | Must |
| FR-5.2 | A reviewer can start a new conversation without reloading and without carrying over the previous caller's identity. | PRD-6 | Must |
| FR-5.3 | The business can open a view showing how the agent is performing (volume, containment, escalations, failures, latency). | PRD-7 | Must |
| FR-5.4 | A reviewer or staff member can flag a conversation as wrong or poor, with a note. | PRD-7 | Must |
| FR-5.5 | The business view lists handoffs and supervisor callback requests awaiting follow-up. | PRD-4, PRD-7 | Should |
| FR-5.6 | When the agent finishes a conversation without a handoff, the caller can tap "yes, that solved it" or "no"; the answer is recorded. | PRD-5, PRD-7 | Must |

### FR-6 First-iteration boundaries

| ID | Requirement | Trace | Priority |
|---|---|---|---|
| FR-6.1 | No voice in v1; chat only. | U§7, GC-5 | Must |
| FR-6.2 | No estimate booking, no late-technician handling, no autopay/upgrade/cancel-membership action in v1 (later-iterations #1, #2, #4). | U§6 later | Must |

---

## 3. Non-functional requirements

*Groups absent on purpose: Contracts beyond CT-1 to CT-3 (no external consumers); Change beyond CH-1, CH-2 (later iterations need no mechanism yet); Scalability limited to SC-1 (internal demo).*

### 3.1 Authorization (AZ-)

| ID | Requirement | Verified by | Trace | Priority |
|---|---|---|---|---|
| AZ-1 | 0 of ≥ 15 cross-account probes [prop] disclose any other customer's balance, invoice, appointment or contact details (wrong phone with right name, right phone with wrong name, "I'm calling for my neighbor", direct invoice-number requests). | Probe suite in the eval set; string match on seeded data for the other three customers | FR-1.3, FR-3.4 | Gate |
| AZ-2 | 0 cancellations or moves occur without an explicit caller yes in the same conversation across all booking-change scenarios. | Database diff after each scenario against the transcript | FR-1.11, FR-1.12 | Gate |
| AZ-3 | 0 of ≥ 10 probes [prop] cause the agent to waive a fee, promise a refund or state a firm repair price. | Probe suite with string/judge checks | FR-1.12, FR-1.13, FR-2.8 | Gate |

### 3.2 Verification and correctness (VR-)

| ID | Requirement | Verified by | Trace | Priority |
|---|---|---|---|---|
| VR-1 | Containment rate is contained-correct ÷ scenarios and is ≥ 60% [src PRD-5 target 60% to 75%]; a result above 75% is not a failure but is flagged for a manual check that the scenarios are not too easy. Wrong answers lower the numerator, never raise it. The ceiling from USERS is 274 of 420 = 65.2% if every handled call works, so the working floor is: ≥ 92% of handled-driver scenarios must be contained-correct (60% ÷ 65.2%) [src arithmetic]. | Eval run, report with counts | A2, U§6 | Must |
| VR-2 | 100% of safety scenarios (the 25 provisional gas/CO/sparks/burning-smell calls plus ≥ 10 authored paraphrases [prop]) end in a safety stop or the A9 follow-up; 0 produce a booking. | Eval run; database diff shows no new rows | FR-1.1, FR-1.2 | Gate |
| VR-3 | 0 superseded values stated across ≥ 16 trap probes [prop] (8 traps × 2 phrasings: $79/$89, 90-day/1-year, $149/$189, 24/48 h cancellation, holiday-hours image, fee-schedule PDF, internal notes, Sunday hours). | Probe suite; automated string check for superseded values plus human read of failures | FR-2.2, FR-2.6, FR-2.7, D-1..D-6 | Gate |
| VR-4 | Fact accuracy on handled-driver scenarios ≥ 90% [prop]: every required fact in the expected answer is present and none is contradicted. | Eval run graded per EV-5 | FR-2.1, FR-2.5 | Must |
| VR-5 | Contained-wrong conversations (contained, but wrong fact or wrong action) ≤ 2% of scenarios [prop]. | Eval run | Decision 1 | Must |
| VR-6 | Every confirmed booking yields exactly 1 slot with status `booked` and exactly 1 new `appointments` row with matching slot, customer and service type; every move leaves the old slot `open` and the new slot `booked`; every cancel leaves the slot `open`. 0 violations. | Before/after database diff in every booking scenario | FR-1.10..1.12 | Gate |
| VR-7 | 0 bookings in a slot with status `blocked` or `booked`, or in `reserved_members` for a non-member; 0 bookings outside the caller's zone or outside 2026-10-16..2026-11-05. | Database invariant query after each eval run | FR-1.7, FR-1.8, GC-8 | Gate |
| VR-8 | When the agent's confirmation text names a date, window and technician, they equal the database row; 0 mismatches. | Eval run comparing confirmation to row | FR-1.10 | Gate |

### 3.3 Performance (PF-)

*Not requirements:* how the budgets are met is architecture. No latency data exists for Meridian; the human calls (median 111 s) are how long a person takes, not a target [src U§handoff].

| ID | Requirement | Verified by | Trace | Priority |
|---|---|---|---|---|
| PF-1 | p95 time to first visible reply ≤ 6 s over the eval run [prop]. A chat reply slower than a few seconds reads as broken. | Latency log, eval run | FR-5.1, PRD-7 | Should |
| PF-2 | p95 time for a turn containing a database write ≤ 10 s [prop]. | Latency log | FR-1.10..1.12 | Should |
| PF-3 | Median conversation for the booking scenarios ≤ 12 caller turns [prop]. A booking that takes a dozen exchanges is slower than the 137 s human median for the same job. | Eval run | FR-1 | Should |

### 3.4 Reliability and failure modes (RL-)

| ID | Requirement | Verified by | Trace | Priority |
|---|---|---|---|---|
| RL-1 | Two conversations racing for the same slot: exactly 1 booking is written, the other caller is offered alternatives; 0 double bookings over 20 repeated races [prop]. | Concurrent test script | FR-1.10, PRD-3 | Gate |
| RL-2 | A restart of the service mid-conversation never leaves a half-written booking (slot `booked` with no appointment row or the reverse); 0 orphans after 10 forced interruptions [prop]. | Interrupt test then VR-6 query | FR-1.10 | Gate |
| RL-3 | When the agent has no good answer, a handoff is the default: of the ≥ 25 deliberately unanswerable questions [prop] in the eval set, ≥ 95% [prop] hand off and 0 invent an answer. | Eval run | FR-2.6, PRD-4 | Must |

### 3.5 Observability (OB-)

*What must be recorded and checkable; which numbers to chart is the key-metrics doc.*

| ID | Requirement | Verified by | Trace | Priority |
|---|---|---|---|---|
| OB-1 | 100% of conversations are stored with: outcome (contained/handoff/safety stop/failed), intent label, turn count, per-turn latency, tools called, errors, and estimated cost. | Query a day's conversations for null fields: 0 | FR-5.3, PRD-7 | Must |
| OB-2 | The business view reflects a new conversation within 1 minute [prop]. | Run a conversation, time its appearance | FR-5.3 | Should |
| OB-3 | Failures (tool errors, provider fallbacks, forced handoffs by error) are separately countable from deliberate handoffs. | Inject one of each; counts differ | PRD-7 | Must |
| OB-4 | A flagged conversation (FR-5.4) can be turned into a candidate eval scenario with one documented command; the loop is described in the README even where only this first step is built [src PRD-7]. | Run the command on one flagged conversation; scenario file appears | FR-5.4 | Must |

### 3.6 Compliance and data handling (CP-)

| ID | Requirement | Verified by | Trace | Priority |
|---|---|---|---|---|
| CP-1 | 0 card numbers appear in stored logs after sending 5 messages containing card-number-shaped strings [prop]; the agent refuses them in the reply. | Log search after test messages | FR-3.3 | Gate |
| CP-2 | 0 secrets (API keys) in the repository history. | Secret scan on the repo | DP-3 | Gate |

### 3.7 Contracts and interfaces (CT-)

| ID | Requirement | Verified by | Trace | Priority |
|---|---|---|---|---|
| CT-1 | The database schema is used exactly as in `SCHEMA.md`: 0 changed or dropped columns/tables, so the reviewer's own queries still work; additions are allowed in separate tables only. | Schema diff against the supplied file | GC-6 | Gate |
| CT-2 | Seeded customers MHC-10001 to MHC-10004 each complete a lookup and a booking. | Four scripted scenarios | GC-6, D-8 | Must |
| CT-3 | The agent's reference date is a configuration value defaulting to 2026-10-16; no slot before it is offered. | Config review; set date to 2026-10-18 and confirm earlier slots are not offered | GC-8 | Must |

### 3.8 Evaluation suite (EV-)

| ID | Requirement | Verified by | Trace | Priority |
|---|---|---|---|---|
| EV-1 | The eval set holds ≥ 200 scenarios derived from the supplied transcripts [prop], covering every call-driver group in USERS §2 with ≥ 5 each [prop], plus the probe sets in AZ-1, AZ-3, VR-2, VR-3, RL-3 (counted separately). With all 420 calls used, the 95% interval on containment is ±4.6 points (1.96 × √(0.65 × 0.35 ÷ 420)); at 200 it is ±6.6. | Scenario count by group; interval computed | PRD-5 | Must |
| EV-2 | Each scenario states its expected outcome (contained/handoff/safety stop), expected facts and expected database change; the whole call is read to set them, because many calls begin with noise ("can you hear me") before the real need [src USERS_handoff]. | File schema check: 0 scenarios missing fields | PRD-5 | Must |
| EV-3 | Containment, accuracy on handled drivers, and escalation rate on the rest are reported in the README as counts and percentages with the 95% interval [src PRD-5]. | README review | PRD-5 | Must |
| EV-4 | Retrieval is evaluated alone, before end-to-end: ≥ 50 questions [prop] drawn from the top 3 drivers; the correct current document is in the top 5 results for ≥ 90% [prop]; superseded files appear in the top 5 in ≤ 5% [prop] of questions. | Retrieval eval script and report | PRD-2 | Must |
| EV-5 | Answer grading by an automated judge agrees with the builder's own grading on ≥ 85% [prop] of a 30-scenario sample. | Agreement computed on the sample | EV-3 | Should |
| EV-6 | The discovery step documents method, ranked top 4 to 5 drivers with counts, and which are handled vs. escalated; the final clustering replaces the provisional keyword labels. The builder's read of 50 random calls agrees with the final labels ≥ 85% [prop]. | Discovery doc and the agreement sample | PRD-1 | Must |
| EV-7 | One command runs the whole eval from a clean checkout in ≤ 30 minutes [prop] and prints the EV-3 numbers. | Timed clean-clone run | DE-3 | Should |

### 3.9 Cost (CO-)

| ID | Requirement | Verified by | Trace | Priority |
|---|---|---|---|---|
| CO-1 | Model/API cost per conversation and cumulative cost are recorded; an alert (or visible banner) fires when cumulative spend passes $100 [prop]. The builder set no cap, so this protects against a runaway loop, not a budget. | Query OB-1 cost field; trigger the threshold in a test | GC-3 | Should |

### 3.10 Scalability (SC-)

| ID | Requirement | Verified by | Trace | Priority |
|---|---|---|---|---|
| SC-1 | Supports 5 simultaneous conversations [prop] (the reviewer, one tester and the eval harness) with p95 latency within 1.5× the single-conversation p95 and 0 VR-6/VR-7 violations. No real caller volume exists to size against. | Concurrent run of the eval subset | FR-5.1 | Should |

### 3.11 Deployment (DP-)

| ID | Requirement | Verified by | Trace | Priority |
|---|---|---|---|---|
| DP-1 | The public URL opens in a clean browser with no login and answers a first message within PF-1. | Manual check from a second device | GC-5 | Must |
| DP-2 | The service is up from deployment through 2026-11-05 (last slot date) with ≥ 99% availability [prop], checked by an external ping every 5 minutes. | Ping log | PRD-6, D-8 | Should |
| DP-3 | Secrets live in environment configuration, not the repository. | CP-2 scan | CP-2 | Gate |
| DP-4 | One documented command restores the database to its supplied seed state, so the reviewer's bookings and the eval runs can be reset. | Run after a booking; VR-7 query and slot counts equal the seed | GC-6 | Must |
| DP-5 | A new machine goes from clone to running locally in ≤ 15 minutes [prop] following the README alone. | Timed run | PRD deliverable 3 | Should |

### 3.12 Change and later iterations (CH-)

| ID | Requirement | Verified by | Trace | Priority |
|---|---|---|---|---|
| CH-1 | Adding or replacing one knowledge-base document takes effect for answers after one documented re-index command, with 0 code changes; takes ≤ 5 minutes [prop]. Needed because the learning loop updates the knowledge base (PRD-7). | Add a document, ask a question only it answers | OB-4 | Should |
| CH-2 | After any knowledge-base or behavior change, the full eval can be rerun and compared with the previous run's counts. | Two stored eval outputs diffed | EV-7 | Should |

---

## 4. Traceability matrix

| Requirement group | UC-1 | UC-2 | UC-3 | All | PRD goal | Dataset findings |
|---|---|---|---|---|---|---|
| FR-1 | ● | | | | 3 | D-2, D-8 |
| FR-2 | | ● | | | 2 | D-1, D-3..D-7 |
| FR-3 | | | ● | | – | A5, A13 |
| FR-4 | | | | ● | 4 | |
| FR-5 | | | | ● | 6, 7 | |
| GC / DE | ● | ● | ● | ● | all | D-8 |
| AZ | ● | | ● | | 4 | |
| VR | ● | ● | ● | | 2, 3, 5 | D-1..D-7 |
| PF | ● | ● | ● | | 6 | |
| RL | ● | | | | 3 | |
| OB | | | | ● | 7 | |
| CP | | | ● | | – | |
| CT | ● | | | | 3 | D-8 |
| EV | ● | ● | ● | | 1, 2, 5 | |
| CO / SC / DP / CH | | | | ● | 6, 7 | |

---

## 5. Proposed thresholds

Every **[prop]** and **[tbd]** number. Status is *accepted*, *revised*, or *pending prototype*. [prop] rows not commented on at review are accepted; [tbd] rows are never accepted by silence. No [tbd] rows were needed: every threshold has an interim value.

| Row | Value | Reasoning | Status |
|---|---|---|---|
| DE-1, DE-2 | Fallback within 10 s | A caller waiting longer than ten seconds assumes the chat has died. | proposed |
| VR-2 | ≥ 10 authored safety paraphrases (35 total) | The 25 labelled calls are templated; paraphrases test the rule, not the template. | proposed |
| VR-3 | ≥ 16 trap probes | 8 traps × 2 phrasings. | proposed |
| VR-4 | ≥ 90% fact accuracy | Allows one miss in ten while keeping VR-1's 92% floor achievable. | proposed |
| VR-5 | ≤ 2% contained-wrong | Wrong confident answers are worse than a handoff (PRD); 2% of 420 ≈ 8 conversations. | proposed |
| AZ-1 | ≥ 15 cross-account probes | Four seeded customers × a few attack styles. | proposed |
| AZ-3 | ≥ 10 fee/price/refund probes | One per must-never wording, several phrasings. | proposed |
| PF-1, PF-2 | 6 s / 10 s p95 | No Meridian latency data; chat norms. | proposed |
| PF-3 | ≤ 12 turns | Keeps a booking in the neighborhood of the 137 s human median. | proposed |
| RL-1, RL-2 | 20 races, 10 interruptions | Enough to expose a missing lock/transaction; not a load test. | proposed |
| RL-3 | ≥ 25 unanswerable questions, ≥ 95% hand off | Directly measures "do not guess". | proposed |
| OB-2 | ≤ 1 min lag | A monitoring view older than a minute is not live for a demo. | proposed |
| CP-1 | 5 card-shaped messages | Minimal check of redaction and refusal. | proposed |
| EV-1 | ≥ 200 scenarios, ≥ 5 per group | At 200 the interval is ±6.6 points, still tighter than the 15-point target range. | proposed |
| EV-4 | ≥ 50 questions, ≥ 90% hit, ≤ 5% superseded | Retrieval must be good before trusting the agent (PRD-2). | proposed |
| EV-5 | ≥ 85% judge agreement, 30 samples | Common sanity bar for an automated grader. | proposed |
| EV-6 | 50-call read, ≥ 85% agreement | Checks the clustering on a sample. | proposed |
| EV-7 | ≤ 30 min | Fast enough to rerun after each change before the deadline. | proposed |
| CO-1 | $100 alert | Runaway-loop guard only; no cap given. | proposed |
| SC-1 | 5 concurrent; 1.5× | Reviewer plus tester plus harness. | proposed |
| DP-2 | ≥ 99%, 5-min ping | Up for the review window. | proposed |
| DP-5 | ≤ 15 min | A reviewer should run it without help. | proposed |
| CH-1 | ≤ 5 min | Learning loop must be cheap to apply. | proposed |

**Open items only a running system (or an upstream fix) can answer:**
1. The true containment ceiling: the 65.2% figure uses provisional keyword labels; the discovery clustering (EV-6) may move it, and VR-1's 92% floor moves with it.
2. Whether `invoices.line_items` gives readable descriptions (FR-3.2 stays Should until checked).
3. Which of 24 h (FAQ) or 48 h (2024 scheduling guide) cancellation notice applies is settled here by A4 (24 h); confirm no current document says otherwise.
4. The payment link is a stub (A13); a real payment provider is not specified.
5. Whether the reviewer will exercise voice despite GC-5; if so, a new requirements pass is needed.

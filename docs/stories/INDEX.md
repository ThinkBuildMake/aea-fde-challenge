# Story map — Meridian AI Call Agent

Written 2026-10-18 from `USERS.md`, `REQUIREMENTS.md`, `KEY_METRICS.md`, `HIGH_LEVEL_DESIGN.md`, `STACK.md`, `ARCHITECTURE.md`, `AUDIT.md`, `USERS_handoff.md`, the PRD (`AEA_FDE_Challenge.txt`) and the [Meridian Agent Wireframe](https://claude.ai/artifact/JY5CoLpz2ViQzaD8sMQ7Sa) (boards "1. Caller chat" and "2. Business view").

**Deadline.** Due Wed 2026-10-21 11:59 PM Central (GC-1). From the morning of 2026-10-18 that is about 3.5 working days for 15 stories, roughly 4 a day. That is tight. If the build falls behind, GC-1's order applies: booking, answers and eval numbers first (S01 to S06, S13, S14), then handoff and failures (S05, S10), then the business view (S11, S12), then the rest (S07, S08, S09, S15). Dropping a story still needs the builder's say-so.

## Following the wireframe

Every story with a screen must match the wireframe. "Match" means:

- **Kept exactly:** the layout and order of the parts, every button and chip label, the banner texts and colours (amber for "Passed to a person" and "Something went wrong on our side", red for the safety stop), the tile and table labels on the business view, and the fixed wording of the greeting, the safety message, the call-back picker and the solved-tap texts (`ARCHITECTURE.md` → Conversation → Must hold → Fixed texts).
- **Replaced with real data:** every `[placeholder]` (names, dates, technicians, prices, counts) is filled from the database or the knowledge base, never invented.
- **Dropped:** wireframe-only parts. These are the "Wireframe: preview a state" button row, the "(example data)" labels, and the word "Wireframe." in the footer note.
- **Phone width:** both pages work at 390 px wide with no sideways scroll. S01 checks this for both pages, and every later UI demo repeats the check.

Each UI story has at least one criterion tagged `wireframe` that names the wireframe state it must match.

| Wireframe state | Story |
|---|---|
| Caller: Start (greeting, chips, text box, New conversation) | S01 |
| Caller: Loading ("Looking that up...") | S01 |
| Caller: Answer + "Did this solve it?" + Thanks | S02 |
| Caller: Safety stop | S03 |
| Caller: Handoff (banner, call-back picker) + Not solved | S04 |
| Caller: Booking, Confirmed | S06 |
| Caller: Wants earlier, Waitlisted | S07 |
| Caller: Error + "Simulate an outage" chip | S10 |
| Business: tabs and status tiles (empty) | S01 |
| Business: Handoffs tab | S05 |
| Business: Waitlist tab | S07 |
| Business: Overview tab | S11 |
| Business: Conversations tab | S12 |

## Order
| # | Story | Blocked by | Review gate | Demo in one line |
|---|---|---|---|---|
| S01 | Open the chat and the business view at a public URL | none | blocking | The public URL shows the wireframe's Start screen, and a typed message gets a placeholder reply |
| S02 | Ask a policy question and get the current answer | S01 | blocking | "Is the diagnostic fee $79?" gets $89, and the caller taps "Yes, that solved it" |
| S03 | A gas smell stops the chat and sends the caller outside | S02 | blocking | "I smell gas" shows the red safety banner and ends the chat |
| S04 | Hand the caller to a person with a call-back time | S02 | blocking | "I was charged twice" shows "Passed to a person" and the call-back picker |
| S05 | Staff work the handoff queue | S03, S04 | blocking | The Handoffs tab lists who, why and what the caller was told, and "Mark followed up" works |
| S06 | Identify the caller and book a visit | S03, S04 | blocking | Omar Patel books Wednesday 8 AM to 12 PM with Jun Park, and the database shows the booking |
| S07 | Book the later window and join the waitlist | S06 | async | "Can you do anything earlier?" offers the three wireframe buttons, and the Waitlist tab shows the entry |
| S08 | Check, move or cancel a visit already booked | S06 | blocking | Linda Foster moves her Thursday visit for free, and a late cancel states $49 |
| S09 | Look up a balance and get a payment link | S06 | blocking | Omar Patel hears $478.00 owed on INV-204411 and gets a link, and a card number is refused |
| S10 | A failure still gives the caller a way forward | S04 | blocking | "Simulate an outage" shows the amber error banner and offers a call back |
| S11 | The business view shows how the agent is doing | S05, S06 | blocking | The Overview shows calls settled against the 60 to 75% band, the six promises and the ping strip |
| S12 | Flag a bad conversation and turn it into a test | S11 | async | A flagged conversation becomes `eval/candidates/CAND-xxxxxxxx.json` |
| S13 | Prove retrieval finds the right document | S02 | blocking | One command prints the right document in the top 5 for at least 18 of 20 questions |
| S14 | Run the 31 scenarios and print the containment numbers | S07, S08, S09, S10, S13 | blocking | One command prints 31 results, projected containment, accuracy and escalation |
| S15 | Safe to leave running until 2026-11-05 | S06, S11 | blocking | A 429 on spam, a green secret scan, 0 double bookings in 20 races, one spend alert |

## Requirement coverage
| Requirement | Threshold (quoted) | Story | Criterion |
|---|---|---|---|
| GC-1 | "Deployed and reviewable by Wed 2026-10-21 11:59 PM US Central" | S01 | 1 |
| GC-5 | "web app at a public URL; chat is the baseline" | S01 | 1 |
| GC-6 | "Bookings really write" | S06 | 4 |
| GC-8 / CT-3 | "reference date ... defaulting to 2026-10-16" | S08 | 4 |
| DE-1 | "plain message and an offer of a human within 15 s of the turn starting ... 'still working' note visible from 10 s" | S10 | 1, 3, 4 |
| DE-2 | "0 false confirmations ... offers a handoff within 10 s" | S15 | 6 |
| DE-3 | "eval output file contains all four fields" | S14 | demo step 4 (see Architectural issues 5) |
| FR-1.1 | leave the home and call 911; no booking | S03 | 1, 2, 3 |
| FR-1.2 | burning smell → follow-up question first | S03 | 4, 5, 6, 7 |
| FR-1.3 | name plus phone, account number or address | S06, S08, S09 | S06-2 (phone), S08-1 (address), S09-1 (account number) |
| FR-1.4 | no match → told so, handed off, no account created | S06 | 5 |
| FR-1.5 | agent says which visit type it is booking | S06 | 1 |
| FR-1.6 | city outside the service area → told so, nothing booked | S02 | 6 |
| FR-1.7 | open windows with date, window and technician | S06 | 2 |
| FR-1.8 | member-only slots for standard or plus only | S06 | 6 |
| FR-1.9 | north-zone plumbing → none available, handed off | S06 | 7 |
| FR-1.10 | booked only after a yes; $89 said once | S06 | 3 |
| FR-1.11 | hear the visit on file and move it; old window freed | S08 | 1, 2, 3 |
| FR-1.12 | cancel only on explicit request; free beyond 24 h, $49 inside, no waiver | S08 | 4, 5 |
| FR-1.13 | only $89 firm; ranges with "the technician confirms pricing on site" | S02 | 5 |
| FR-1.14 | no conversation ends without a next step | S04 | 1 |
| FR-1.15 | earliest window, book plus waitlist, or a person | S07 | 1–7 |
| FR-2.1 | short answer with the condition that matters | S02 | 2 |
| FR-2.2 | superseded value never stated | S02 | 1 |
| FR-2.3 | hours match the FAQ and the holiday image | S02 | 4 |
| FR-2.4 | fees match the 2026 PDF | S02 | 3 |
| FR-2.5 | warranty answers separate manufacturer, labor and membership | S14 | 4 (WA-1, WA-2 are handled-driver scenarios) |
| FR-2.6 | documents do not settle it → "not sure", handed off | S04 | 4 |
| FR-2.7 | internal notes never read out | S04 | 7 |
| FR-2.8 | no promised refund, waiver or price | S08 | 5 |
| FR-2.9 | two questions in one conversation, both answered | S09 | 7 |
| FR-2.10 | membership changes explained, then handed off | S04 | 5 |
| FR-2.11 | commercial, duct cleaning etc. → redirect or handoff | S14 | 5 (RD-1) |
| FR-2.12 | repair range from the current price book with the caveat | S02 | 5 |
| FR-3.1 | own balance and open invoices | S09 | 1 |
| FR-3.2 | an invoice line in plain words | S09 | 2 |
| FR-3.3 | payment link; never take a card number | S09 | 3, 4 |
| FR-3.4 | never another customer's account | S09 | 5, 6 |
| FR-3.5 | dispute → call-back window, supervisor within 1 business day | S04 | 1, 2 |
| FR-4.1 | caller told a person takes over, why, what next | S04 | 1 |
| FR-4.2 | the person sees the handoff record | S05 | 1 |
| FR-4.3 | supervisor calls "within 1 business day, never 'today' or two days" | S04 | 1 |
| FR-4.4 | asks for a person → handed off | S04 | 3 |
| FR-4.5 | out-of-scope drivers handed off | S14 | 5 (LT-1, NS-1) |
| FR-5.1 | type messages, see replies and escalation or safety indication | S01, S03, S04 | S01-3, S03-1, S04-1 |
| FR-5.2 | new conversation, no carried identity | S01 | 4 |
| FR-5.3 | business view of volume, containment, escalations, failures, latency | S11 | 1–7 |
| FR-5.4 | flag a conversation with a note | S12 | 3, 4 |
| FR-5.5 | handoffs listed, marked followed up | S05 | 1, 2, 3 |
| FR-5.6 | "yes, that solved it" or "no", recorded | S02, S04 | S02-7, S04-6 |
| FR-5.7 | waitlist with caller, visit type, zone, window held, time waiting | S07 | 5 |
| FR-5.8 (proposed, `ARCHITECTURE.md` OQ 1) | safety stop in the handoff queue | S05 | 4 |
| FR-6.1, FR-6.2 | no voice; no estimates, late-tech or membership actions | all | boundary: no story builds them |
| AZ-1 | "0 of 2 cross-account scenarios ... disclose" | S09, S14 | S09-5, S09-6, S14-6 |
| AZ-2 | "0 cancellations or moves occur without an explicit caller yes" | S08 | 6 |
| AZ-3 | "0 of 3 scenarios ... waive a fee, promise a refund or state a firm repair price" | S08, S14 | S08-5, S14-1 (AP-3, T-7, NS-1 results) |
| VR-1 | "Projected containment ≥ 60%" | S14 | 3 |
| VR-2 | "All 3 safety scenarios behave as specified" | S03, S14 | S03-3, S14-6 |
| VR-3 | "0 superseded values or internal-note contents" | S02, S14 | S02-1, S14-6 |
| VR-4 | "≥ 9 of 10" | S14 | 4 |
| VR-5 | "0 contained-wrong conversations among the 31" | S14 | 6 |
| VR-6, VR-7, VR-8 | "0 violations" / "0 mismatches" | S06, S08, S14 | S06-4, S08-3, S14-6 |
| VR-9 | "0 unsupported figures" | S14 | 6 |
| VR-10 | "writes exactly 1 row ... asking twice ... writes 1 row, not 2" | S07 | 3, 4 |
| PF-1 | "p95 time to first visible reply ≤ 6 s" | S01, S11 | S01-3, S11-6 |
| PF-2 | "p95 time for a turn containing a database write ≤ 10 s" | S11 | 6 |
| PF-3 | "Median conversation for the booking scenarios ≤ 12 caller turns" | S14 | demo step 4 |
| RL-1 | "0 double bookings over 20 repeated races" | S15 | 4 |
| RL-2 | "0 orphans after 10 forced interruptions" | S15 | 5 |
| RL-3 | "both unanswerable scenarios (WA-3 and T-8) end in a handoff" | S04, S14 | S04-4, S14-5 |
| OB-1 | "100% of conversations are stored with ..." | S12 | 2 |
| OB-2 | "reflects a new conversation within 1 minute" | S11 | 2 |
| OB-3 | failures "separately countable from deliberate handoffs" | S10 | 5 |
| OB-4 | flagged conversation → candidate scenario with one command | S12 | 5, 6 |
| CP-1 | "0 card numbers appear in stored logs after sending 5 messages" | S09, S12 | S09-4, S12-7 |
| CP-2 / DP-3 | "0 secrets (API keys) in the repository history" | S15 | 3 |
| CT-1 | "0 changed or dropped columns/tables" | S15 | demo step 2 (schema-diff test in CI) |
| CT-2 | "MHC-10001 to MHC-10004 each complete a lookup and a booking" | S14 | 7 |
| EV-1, EV-2, EV-3 | 31 scenarios; README reports each result | S14 | 1, demo step 4 |
| EV-4 | "≥ 20 questions ... top 5 ... for ≥ 18 ... superseded ... at most 1" | S13 | 1, 2 |
| EV-5 | "judge agrees ... on ≥ 9 of 10" | S14 | demo step 4 |
| EV-6 | "read of 20 random calls agrees ... on ≥ 17" | — | document work in `AUDIT.md`, no story |
| EV-7 | "≤ 15 minutes" | S14 | 2 |
| CO-1 | "alert ... when cumulative spend passes $100" | S11, S15 | S11-6, S15-7 |
| SC-1 | "5 simultaneous conversations ... within 1.5×" | S15 | demo step 2 (CI test) |
| SC-2 | "4 conversations at once ... each on its own copy" | S14 | 2 |
| DP-1 | "opens in a clean browser with no login" | S01 | 1 |
| DP-2 | "≥ 99% availability ... ping every 5 minutes" | S11 | 7 |
| DP-4 | "One documented command restores the scheduling database to its supplied seed state" | S08 | 7 |
| DP-5 | "clone to running locally in ≤ 15 minutes" | — | README work, no story |
| CH-1 | "re-index command, with 0 code changes; takes ≤ 5 minutes" | S13 | 3, 4 |
| CH-2 | "two stored eval outputs diffed" | S14 | demo step 5 |
| GC-2, GC-4 | video, README and service inventory | — | deliverable work outside the stories |

## Icebox
- **Langfuse Cloud tracing** (`ARCHITECTURE.md` → Conversation → Calls out; `STACK.md` §17). The builder iceboxed it on 2026-10-18. OB-1 is already met by the app's own tables, logs and business view, so dropping it costs a nice-to-have trace UI and no requirement. Open question 14 (Langfuse free tier and card text) goes with it.
- **Voice** (FR-6.1, PRD extra credit). Excluded by the builder.
- **Later iterations** (FR-6.2): estimate booking, late-technician handling, and the autopay, upgrade and cancel-membership actions. Each is handed off in v1 and checked in S04 and S14.

## Feasibility checks
- Scheduling database, read-only, 2026-10-18 (`sqlite3` on `meridian_scheduling.sqlite`). Seeded customers: MHC-10001 Linda Foster (Round Rock, north, standard, 512-555-0101, scheduled visit 159 on Thu 2026-10-22 08:00-12:00 with Marta Kowalski); MHC-10002 Omar Patel (Kyle, south, no membership, 512-555-0102, invoice INV-204411 with a $478.00 balance: diagnostic $89, contactor $245, after-hours dispatch $144); MHC-10003 Grace Okafor (Austin, central, plus); MHC-10004 Daniel Reyes (Georgetown, north, no membership). The earliest open south-zone HVAC repair window is Wed 2026-10-21 08:00-12:00 with Jun Park. The north zone has 0 plumbing slots. North-zone slot 1 (Fri 2026-10-16 08:00-12:00, Ray Mendoza) is `reserved_members`. Slot counts: 323 open, 159 booked, 42 reserved_members, 4 blocked.
- Knowledge-base values, read from the files on 2026-10-18: $89 diagnostic, $149 after-hours dispatch, $49 late cancel (FAQ and the PDF's text layer, via `pdftotext`); Comfort Club $189 a year (`membership/comfort_club_overview.md`); run capacitor $180 to $260 (`pricing/repair_price_book_2026.csv`).
- **Not confirmed:** the holiday-hours PNG was not read (that needs the model). The OpenRouter, Gemini, embeddings, Railway and UptimeRobot calls were not made. These are the architecture's day-1 checks (open questions 4, 6, 7, 8, 9) and belong to S01's and S02's plans. No story depends on a result they could rule out, because the architecture's fallbacks change no contract.

## Architectural issues
None that need an architecture amendment. Five upstream items, recorded so they are not lost:
1. **FR-5.8 is proposed, not added to `REQUIREMENTS.md`** (`ARCHITECTURE.md` open question 1, option A accepted 2026-10-18). S05 criterion 4 builds it. Adding the row is a requirements edit only.
2. **`KEY_METRICS.md` still says "fallback message within 10 s of a model failure"**, but DE-1 says 15 s from the turn start, with a note at 10 s. The fix is listed under the architecture's upstream fixes and not yet applied. The stories quote DE-1.
3. **D-12 (Dripping Springs and Manor) and D-13 (`technician_arrival_and_etas.md` is agent-only)** are listed in the architecture's upstream fixes and not yet in `REQUIREMENTS.md`. S02 criterion 6 and S13 rely on the architecture's resolution.
4. **Langfuse is iceboxed** (see Icebox). It is an outbound side channel, so dropping it changes no table, route or module contract.
5. **Several Should-level eval checks are demo steps in S14, not acceptance criteria** (DE-3 run record, EV-5 judge agreement, PF-3 turn count, CH-2 compare, the README numbers). With them, S14 would have 12 criteria. They are printed by the same command S14 builds, so they are checked at the S14 demo. Split S14 if the builder wants them as criteria.

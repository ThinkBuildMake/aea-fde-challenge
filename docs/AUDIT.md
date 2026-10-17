# AUDIT.md — Meridian call center, from the 420 supplied calls

**What this is.** What Meridian's human agents do today, read from every supplied transcript, plus the parts of the supplied database and knowledge base the calls touch. It is the discovery step the PRD asks for first (PRD goal 1). It replaces the keyword pass in `USERS.md` §2 with a whole-call reading, and records where the calls disagree with the documents written so far.

**Method.** Each call was read in full, not just its opening. A rule set (`analysis/audit_calls.py`) strips filler turns ("can you hear me", "I'm driving"), then labels the caller's need from their substantive turns and labels how the human agent resolved it from the agent's turns. Output: `analysis/call_labels.csv`, one row per call. Run `python3 -I analysis/audit_calls.py data/meridian_dataset` to reproduce every number below.

**Check on the labels.** 0 of 420 calls are unclassified. The caller-side label and the agent-side resolution agree in every group: all 120 booking calls end with the agent writing a booking, all 24 complaint/refund calls end with a supervisor callback, all 33 membership-change calls end with the agent acting or sending a link. The labels match the keyword pass on all 420 calls (four calls that ask for a visit and a plan question at once are counted as bookings). The calls are templated (about 400 distinct agent lines across 420 calls), which is why the rules fit so cleanly; real calls would not.

---

## 1. The corpus

| Fact | Value |
|---|---|
| Calls | 420, from 2026-07-06 to 2026-09-19 (76 days with calls) |
| Length | 40 to 175 seconds; median 111, 90th percentile 146 |
| Volume | 5.5 calls a day on average, at most 12 in a day; July 156, August 164, September 100 (to the 19th) |
| Most calls at once | 2 (from start time and duration) |
| Human agents | 8 (Kayla 70, Marcus 62, Denise 56, Brian 53, Jordan 46, Renee 45, Tasha 44, Eli 44) |
| Hours | 89 calls fall outside the published hours (Mon–Fri 7 AM–7 PM, Sat 8 AM–4 PM), 66 of them on Sunday |
| Noise | 92 calls (22%) contain a filler turn; 21 start with one |

**What this means.** The sample cannot show that the call center is overloaded: eight agents and at most two calls at once. The "capacity constrained" claim stays an assumption from the PRD (USERS A1). The sample also gives no load to size the system against, so sizing rests on SC-1.

## 2. What callers want

| Driver | Calls | Share | Median seconds | How the human resolved it |
|---|---|---|---|---|
| Book a visit | 120 | 28.6% | 137 | Booked a window (120 of 120) |
| Warranty | 45 | 10.7% | 105 | Explained (25), booked a warranty diagnostic or recall (20) |
| Billing lookup | 42 | 10.0% | 96 | Read balance or explained a line (15), sent a payment link or emailed a copy (27) |
| Membership question | 38 | 9.0% | 104 | Explained price, renewal or discount (38) |
| Membership change | 33 | 7.9% | 101 | Turned off auto-renew, sent an autopay link, or upgraded and sent a prorated link (33) |
| Existing appointment | 29 | 6.9% | 91 | Confirmed (8), moved (15), cancelled (6) |
| Billing dispute | 27 | 6.4% | 101 | Supervisor callback (16), explained a pending charge or the quote gap (11) |
| Safety | 25 | 6.0% | 118 | Told to leave and call 911 or the gas utility (9: 5 carbon monoxide, 3 gas, 1 sparks or smoke); booked a visit for a burning smell (16) |
| Complaint or refund | 24 | 5.7% | 94 | Supervisor callback (24) |
| Redirect, not residential | 16 | 3.8% | 89 | Commercial: took details for an estimator (5); employment: careers page (6); wrong number (5) |
| New system quote | 12 | 2.9% | 119 | Gave the price range and booked a Comfort Advisor estimate (12) |
| Late technician | 9 | 2.1% | 93 | Apologised, waived the diagnostic fee or promised a call from the technician (9) |

**Top five by volume:** booking, warranty, billing lookup, membership question, membership change: 278 of 420 (66.2%). Membership change is a top-five driver the first iteration cannot handle, because nothing supplied lets the agent change membership (FR-2.10). Existing appointments (29) is the sixth and is handled.

## 3. What the agent could settle

How the humans resolved each call, grouped by whether the agent in this project has the means to do the same:

| Group | Calls | Share |
|---|---|---|
| Handled in the first iteration: booking, warranty, membership question, billing lookup, existing appointment | 274 | 65.2% |
| Plus burning-smell calls, if the follow-up question clears them (A9) | +16 = 290 | 69.0% |
| Plus employment and wrong-number redirects, if answered with a script (FR-2.11) | +11 = 301 | 71.7% |
| Handoff by design: billing dispute, complaint or refund, safety stop, commercial | 65 | 15.5% |
| Handoff for lack of a tool: membership change, late technician, new-system estimate | 54 | 12.9% |

The 65.2% ceiling in `USERS.md` holds as the conservative figure. The 16 burning-smell calls are the main upside, but every human booked them without asking about smoke, sparks or a tripped breaker, so the calls carry no answer to the follow-up; the eval has to supply one (EV-2).

## 4. Where the calls and the documents disagree

| # | Finding | Evidence | What it changes |
|---|---|---|---|
| 1 | **The callers in the calls are not in the database.** 0 of 130 phone numbers, 0 of 131 account numbers, 0 of 42 invoice numbers and 0 of 48 street addresses appear in the supplied tables. | `customers.csv` (154 rows), `invoices.csv` (81 rows) | A transcript cannot be replayed against the database as it stands. Each eval scenario must be given a database customer (and, for balance and invoice calls, a real invoice) in place of the one in the call. EV-2 and CT-2 need a mapping rule. |
| 2 | **Humans identify callers three ways**, in about equal shares: account number plus name (131), name plus phone (130), name plus service address (115). 44 calls need no identification. | Agent lines "Do you have your account number handy?", "Name and the phone number on the account", "Name and service address?" | FR-1.3 names only name and phone. Either accept the other two or record the narrowing. |
| 3 | **Callback promises vary.** One business day (21 calls, matches the escalation policy), two business days for refunds (8), "today" from a service manager (16). | Agent lines on supervisor and manager escalations | The agent states one business day (FR-3.5, FR-4.3). Do not copy the other two. |
| 4 | **A waitlist is offered in 34 calls** (every caller who asked "can you do anything earlier?"), then the later slot is booked. | Agent line "I can add you to the waitlist for cancellations" | Only the 2024 scheduling guide, already marked superseded, mentions a waitlist; the database has no table for one. Decide: say no waitlist exists, or add a table. |
| 5 | **Humans quote price ranges**: compressor labor $600 to $900 and a full system $8,000 to $16,000, always followed by "the technician will quote exact" (19 calls). The ranges are in the customer-facing service catalog. | `services/service_catalog.md`, `pricing/repair_price_book_2026.csv` | FR-1.13 forbids any repair price. The documents allow stating a range. Decide which to follow. |
| 6 | **Humans waive the diagnostic fee** for a late technician, as the internal notes allow. | Late-technician calls (9) | The agent never waives (A7); these 9 calls are handoffs. No change. |
| 7 | **Humans change memberships directly** (33 calls), and `escalation_and_safety.md` lists this as something agents resolve. | Same document | Nothing supplied lets the agent do it; FR-2.10 stands and caps containment. |

## 5. What the calls do not test

| Topic in the knowledge base | Calls that ask about it |
|---|---|
| Opening hours, holidays, Sundays | 0 (though 66 calls are timed on a Sunday) |
| Service area, ZIP codes, towns served | 0 |
| The $79 diagnostic fee, the 90-day repair warranty, the 48-hour cancellation rule | 0 |
| The fee schedule PDF and the holiday-hours image | 0 asked directly; after-hours or weekend fees come up in 5 calls |
| The old $149 membership price | 14 callers say "I thought it was $149?" and the human answers "that was the old pricing" |
| Financing, troubleshooting, filters, gate codes | 0 |

The trap documents are therefore tested only by authored probes (VR-3, EV-4), not by transcripts. The hours and service-area rows in FR-2.1 and FR-2.3 come from the PRD and the knowledge base, not from caller demand.

## 6. Other things worth knowing

- **Invoice line items are readable** (for example "Diagnostic visit", "Condensate drain clearing", "Equipment disposal"), so the open item on FR-3.2 is closed.
- **Slots.** 528 rows, 2026-10-16 to 2026-11-05, 159 appointments all `scheduled`. Plumbing slots exist only in the central and south zones. Comfort Advisor `estimate` slots exist in the north and south (96 rows), so a later iteration can book new-system estimates.
- **Members** are 56 of 154 customers (38 standard, 18 plus).
- **Hours.** The published hours appear only in the FAQ. The 89 calls outside them were answered like any other call.

## 7. Upstream fixes

| Document | Change | Why |
|---|---|---|
| `USERS.md` §2 | Replace the provisional table with §2 above; note that hours, service area and the three superseded values do not appear in the calls | Whole-call reading; no call evidence for UC-2's hours and area examples |
| `REQUIREMENTS.md` EV-2 | Each scenario carries a database customer mapped from the call; balance and invoice scenarios carry a real invoice | Finding 1 |
| `REQUIREMENTS.md` FR-1.3 | Accept account number plus name, or name plus service address, as well as name plus phone [decision needed] | Finding 2 |
| `REQUIREMENTS.md` | Decide the waitlist (finding 4) and quoted ranges (finding 5) | Humans do both; documents are silent or stricter |
| `REQUIREMENTS.md` open items | Remove the invoice line-item item | Section 6 |
| `KEY_METRICS.md` | Ceiling note: 65.2% base, up to 71.7% if burning-smell and redirect calls are contained | Section 3 |

## 8. Limits

- The calls are synthetic and templated, so shares and the clean labels reflect how the data was made.
- Intent labels come from rules, not a second reader. EV-6 still asks for the builder's read of 50 random calls.
- Resolution labels come from what the agent said, not from a system record; a human who said "you're booked" is taken to have booked.
- No call contains wait time, hold time or abandonment, so no claim about those is made.

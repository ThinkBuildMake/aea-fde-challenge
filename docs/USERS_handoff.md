# Handoff: design and requirement content removed from USERS.md

These items came up while defining the user but describe how the product is built, not who it serves. Carry them into requirements, key metrics, the high-level design and architecture. Each maps to a use case ID.

## Access and trust
- Identify the caller by name and phone against `customers` before showing any account data; never expose another customer's invoices (UC-3).
- Never take card numbers by phone; payment is by secure link valid 24 hours (UC-3).
- The `internal/` knowledge-base folder is agent-facing only and must not be read to callers (UC-2).

## Verification and honesty
- Retrieve only from current documents. Superseded content to exclude or down-rank: `archive/comfort_club_overview.md`, `archive/warranty_terms_2023.txt`, `faq/faq_old_copy.md`, `scheduling_guide.md` (Rev 2024-11, conflicts with the FAQ on cancellation notice) (UC-2).
- Content that lives outside plain text must be ingested: `policies/holiday_hours_2026.png` (image) and `pricing/2026_fee_schedule.pdf` (table) (UC-2).
- Where documents disagree and no precedence is known, the agent must hand off rather than pick one (UC-2).
- Repair prices are never firm; only the $89 diagnostic fee is stated (UC-1, UC-2).

## Capabilities traced to use cases
| Capability | Required by |
|---|---|
| Safety screen before any booking (gas, CO, sparks/smoke; burning smell follow-up) | UC-1 |
| Map a symptom in plain words to a service type (`hvac_repair`, `hvac_tune_up`, `plumbing`, `estimate`) | UC-1 |
| Map city to zone (north / central / south) and match slots | UC-1 |
| Member-only slots (`reserved_members`) offered only to standard/plus members | UC-1 |
| Write a booking: set slot to `booked`, insert `appointments` row, return date, window and tech name | UC-1 |
| Look up scheduled appointments; reschedule or cancel and free the old slot (`open`) | UC-1 |
| Retrieval over the knowledge base with chunking suited to tables, an image and a PDF | UC-2 |
| Read `customers`, `invoices` (balance, line items) | UC-3 |
| Send a payment link | UC-3 |
| Structured handoff summary for a human; supervisor callback logging with a preferred window | all |

## Time budget
- Supplied calls run 57 to 175 seconds (median 111) between a human agent and the caller. This is how long a human takes, not a target for the AI (all).

## Scope boundaries with their design reasons
- Reschedule / cancel / confirm: documented in `SCHEMA.md` as expected behavior; promoted into the first iteration (A8) to clear the containment range. It adds an update path that frees the old slot and the 24-hour late-cancellation fee rule (UC-1).
- Emergencies are never booked: `SCHEMA.md` says "Emergency calls (safety) are NOT booked here — they escalate."

## Open questions for the requirements and research steps
- **The containment ceiling.** The seven first-iteration features resolve at most about 274 of 420 provisionally labelled calls (about 65%), against a 60 to 75% target. Little headroom: requirements should set the counting rule (A2) and the accuracy needed so wrong answers don't erode it.
- **Assumptions A1 to A12** in `USERS.md` Section 9 replace the exec-team questions; requirements should carry A4, A5, A9 and A10 as behaviors with tests.
- The final discovery clustering must replace the keyword labels in `USERS.md` Section 2 (PRD goal 1).
- The eval set must be built from the transcripts; many transcripts begin with noise ("can you hear me," "I'm driving") before the real intent, so labelling must read the full call.
- Check that the `invoices.line_items` JSON gives meaningful descriptions before claiming UC-3's value.
- No plumbing slots exist in the north zone: decide the behaviour (alternatives, waitlist, handoff).

## Monitoring and learning-loop content (implementer concerns, not caller features)
- Volume, containment, escalations, failures and latency must be visible to the business after launch; logged conversations and flagged failures must feed back into the knowledge base and eval set (PRD goal 7). Belongs in key metrics and architecture.

## Existing products in the same space
- Not researched. The outside benchmarks cited in `USERS.md` come from vendors selling AI receptionists; their pricing and limits were not checked, so none is cited as an alternative a Meridian caller could choose.

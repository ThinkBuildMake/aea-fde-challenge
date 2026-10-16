# USERS.md — Meridian AI Call Agent

## Scope

**This document covers:** who the Meridian call agent is for and who it is not for; what callers ask for today, with numbers from the 420 supplied transcripts; the moment the agent enters the caller's day; the use cases it serves and why this shape of product is the one callers would choose; the minimum first iteration and the features that come after; what is out of scope; and the constraints the project was given.

**This document does not cover:** how the agent is built, verified, measured or hosted. Requirements, key metrics, stack and architecture are separate documents that trace back to the use case IDs (UC-n) and the constraints here.

**Status:** Draft, interview with the builder (the FDE) on 2026-10-16, built from `docs/AEA_FDE_Challenge.pdf` (the PRD) and `data/meridian_dataset/`. The exec team has not been interviewed. Claims about their goals come from the PRD and are marked *(PRD)*; the open questions for them are in `MEETING_QUESTIONS.md`. Call-mix numbers come from a provisional rule-based labelling of each call's opening lines (`analysis/classify_openings.py`), not from the final discovery clustering the PRD asks for.

---

## 1. Target user

**A homeowner in the Austin metro who phones Meridian Home Comfort, an HVAC and plumbing company, with a routine, non-emergency need and wants it settled in one short call.**

Callers are existing customers or soon-to-be customers in Austin, Round Rock, Cedar Park, Pflugerville, Georgetown, Leander, Hutto, Kyle or Buda. They call from home, a car or work, usually because something in the house stopped working, a bill or email arrived that they don't understand, or they have a question about their Comfort Club membership or warranty. Their calls are short: the median supplied call lasts 111 seconds and the longest 175. They know the symptom, not the vocabulary: "the thermostat is blank," "water is pooling around the indoor unit," "I got an email saying my membership is renewing."

They are not trying to learn about Meridian. They want one of three outcomes: a technician booked, an answer they can trust, or a person who already knows their story.

**Not the target user:**
- **The human call-center agents (eight in the supplied data).** They receive what the AI hands off. They are a downstream reader of the handoff, not who this is designed around.
- **The exec team.** They judge the project by containment and monitoring. Those needs belong to the metrics document.
- **Commercial customers, job seekers and wrong numbers.** Meridian redirects these; they are not served by the agent beyond the redirect.
- **Anyone reporting a gas smell, carbon monoxide alarm, sparks or smoke.** They need 911, not a chatbot. See "Must never" in UC-1.

---

## 2. The problem, in numbers

### What callers actually ask for (the supplied transcripts)

The 420 transcripts run from 2026-07-06 to 2026-09-19 and carry no labels. Reading every call's opening lines, the 420 calls contain about 80 distinct openings that fall into roughly 25 intents. Grouped:

| What the caller wants | Calls | Share |
|---|---|---|
| Book a repair, plumbing or tune-up visit | 120 | 28.6% |
| Membership: what it includes, renewal charge, upgrade, discount, autopay, cancel | 71 | 16.9% |
| Warranty: coverage, transfer, repeat repair, manufacturer registration | 45 | 10.7% |
| Billing lookup: balance, pay an invoice, what a line item is | 42 | 10.0% |
| Something about an existing appointment: move or cancel it, confirm it, technician is late | 38 | 9.0% |
| Billing dispute: quote differs from invoice, charged twice | 27 | 6.4% |
| Complaint, manager request, refund demand | 24 | 5.7% |
| Burning smell (needs a safety check) or confirmed gas, CO or sparks | 25 | 6.0% |
| Replace a whole system (quote) | 12 | 2.9% |
| Employment, commercial, wrong number | 16 | 3.8% |

> **How to read this table.** The labels are our provisional pass, a keyword rule on each call's first two customer turns. They are good enough to size the scope, not to report as final. The PRD asks for a defensible clustering and a written method; that is a separate step.

At a glance, the three things callers most often want are a visit booked, a membership or warranty question answered, and a bill explained. All three are routine in the sense that Meridian's own documents already say what the answer is.

### What goes wrong today

The supplied data does not contain wait times, hold times, abandoned calls or staffing levels. The PRD states that the call center is capacity constrained, that wait times are high and that staff cannot keep up *(PRD)*. We could not confirm this from the data. These outside figures are context only:

- Benchmarks for home-services call answering differ by source and method. As reported by secondary summaries of CallRail (January 2025) and Invoca (July 2026), the share of home-services calls not reaching a person ranges from 14% to about 48%.
- A UK contact-centre survey (ContactBabel, 2024) reports a mean abandonment rate of 8.4% and an average 116 seconds to answer, as reported by secondary pages.

These are cited as context, not as Meridian's problem. The exec team's own wait, abandonment and staffing numbers are the first item in `MEETING_QUESTIONS.md`.

---

## 3. Why we target these moments

The agent enters the moment the caller has a routine need and a phone in their hand, and it ends at one of three points: the need is met, the caller is handed to a human with their story carried over, or the caller is told clearly to hang up and call 911. It does not try to be a general customer-service agent.

**Reason 1: most of what callers ask is already written down.** Meridian's policies cover fees, membership, warranty, hours and service area, and its scheduling database holds real slots. The 120 booking calls and the policy calls together are the bulk of the volume (see table above).

**Reason 2: a wrong answer here costs the caller money or safety.** Callers act on what they are told: they decline a tune-up because they think the diagnostic fee is $79, cancel a membership because they think they'll be refunded, or book a visit when they should leave the house. The supplied knowledge base contains older versions of its own pages with different prices and terms (for example $79 versus $89 diagnostic fee, a 90-day versus 1-year repair warranty). A confident wrong answer is worse than a handoff.

**Reason 3: the callers' needs are short and independent.** Each call is one need, sometimes two ("my AC is blowing warm, and what does the maintenance plan include?"). The agent does not need long-running memory of a caller, only the one call and the account behind it.

### Out of scope: the moments not targeted

Disputes, refunds, complaints and manager requests are different work: the caller is upset and wants a person to decide something. Meridian's internal escalation policy routes all of these to a supervisor callback within one business day. The agent's job there is to say so and capture the case, not to resolve it.

---

## 4. Workflow: where the agent enters the day

**Tuesday, 5:40 PM.** Priya lives in Cedar Park. She got home and the air from the vents is warm. The thermostat says 79°F and it was 91°F outside today. She has been meaning to call all day.

**The 30 seconds before calling:** she doesn't know whether it is a quick fix or a big bill, whether Meridian can come tomorrow, or whether she has to be home. She dials the number on the sticker on her indoor unit. → **UC-1**

**What she needs:** someone to tell her, within a couple of minutes, that a technician is coming, when, and roughly what it will cost to find out what's wrong.

**What she does with the answer:** she says yes to a Thursday 8 to 12 window, then asks one more thing: "Does the maintenance plan cover this?" → **UC-2**

**6:15 PM, the same evening.** Her husband Sam remembers an email about the bill. He calls to ask for his balance and whether he can pay by phone. → **UC-3**

**What happens if something doesn't fit:** Priya mentions a smell of burning from the vents and a tripped breaker. The agent stops the booking, tells her to leave the house and call 911 or the gas utility from outside, and flags the account. Or Sam says the invoice is $149 and the tech quoted $89. The agent says it can't settle that, takes a preferred callback window, and tells him when a supervisor will call.

(Priya and Sam are an illustrative composite, not a call from the data.)

---

## 5. Use cases

### UC-1: Book a repair, plumbing or tune-up visit

| | |
|---|---|
| **Trigger** | The caller says something is broken or they need a tune-up and want someone out. |
| **Input** | A problem in plain words, their name and phone, a preferred day, their city. |
| **What they need to see** | A clear yes or no: either "you're booked, Thursday 8 to 12, with [tech name]" or "nothing opens that day, here are the nearest options." The diagnostic fee, said once, in plain terms ($89, credited toward the repair, waived for members). If nothing can be booked, a clear handoff, not a dead end. |
| **What they do with it** | Accept a window, pick another, or ask for a person. They decide; the agent never books without a yes. |
| **Time available** | A booking call in the data runs about 137 seconds at the median. |
| **Must never** | Book a visit for a gas smell, CO alarm, sparks or smoke. Tell a caller they are booked when nothing was recorded. Book someone outside the service area. Promise a repair price: only the diagnostic fee is stated, and repair prices are "the technician will confirm on site." Send a caller away from a booking without saying what happens next. |

**Why an agent, not an online booking form or a phone menu:**
A form can do the lookup. If the caller already knows their city, the problem type and the day they want, a form can show open windows, and a phone menu can read them out. Neither needs this product for that.

What a form or menu can't do:
1. Callers don't arrive with a problem type. They say "water pooling around the indoor unit" or "my thermostat is blank." Mapping that to the right visit type (HVAC repair, plumbing, tune-up, estimate) and the right technician zone from their city is the work.
2. The first words of a call sometimes decide whether it should be booked at all. "I smell something burning from the vents" can be an electrical emergency or a dusty furnace; the agent has to ask the next question before offering a window.
3. Many callers say two things at once ("my AC is blowing warm, and what does the maintenance plan include?"), so the booking and the policy question belong in the same call.

The value is in the first sentence of the call, understanding what kind of visit this is and whether it is safe to book, more than in the lookup. This rests on the scheduling database actually containing slots per zone and service type; the data shows plumbing slots only in the central and south zones, so a north-zone plumbing caller currently cannot be booked, and the agent has to say so.

---

### UC-2: Get a correct answer about fees, membership, warranty, hours or service area

| | |
|---|---|
| **Trigger** | The caller asks what something costs, what a membership includes, whether something is under warranty, or when Meridian is open or whether it serves their area. |
| **Input** | A question in the caller's own words, often with details about their system (brand, age, last repair). |
| **What they need to see** | A short answer that matches the current policy, with the conditions that matter ("the manufacturer covers the part, Meridian's labor warranty may not"). When the documents don't settle it, a plain "I'm not sure, let me get someone who is." |
| **What they do with it** | Decide whether to join, cancel, book a visit, or file a warranty claim. |
| **Time available** | Policy calls in the data run about 100 to 110 seconds at the median. |
| **Must never** | Answer from an older, superseded policy. Quote a repair price as firm. Read the internal-only agent notes to a caller. Promise a refund, a waiver or a price the caller's account doesn't qualify for. Guess when two documents disagree. |

**Why an agent, not an FAQ page or a phone menu:**
A flat FAQ or menu can answer "how much is the maintenance plan" and "what are your hours." Those need no agent.

What it can't do:
1. Warranty and membership questions have conditions that combine. "My three-year-old Trane compressor died" depends on the brand, whether the unit was registered, who installed it, and whether the part or the labor is being asked about. The answer is one or two sentences, but reaching it means putting several documents together.
2. Callers phrase the same fact in many ways ("does the warranty transfer," "we just bought the house," "can I move the membership"), and the answer is different for the manufacturer warranty, Meridian's labor warranty and the membership.
3. The knowledge base has traps: archived and "old copy" files with different prices, a holiday-hours schedule that exists only as an image, a fee schedule that exists only as a PDF, and two documents that disagree on cancellation notice (24 versus 48 hours). A page that surfaces the wrong one is worse than no page.

The value is in the conditional and contradictory cases, and in saying "I don't know" when the documents don't decide. This depends on the knowledge base being read as it is, including the image and the PDF.

---

### UC-3: Look up a balance, pay an invoice, or understand a charge

| | |
|---|---|
| **Trigger** | The caller asks for their balance, asks to pay an invoice, or doesn't recognise an invoice line. |
| **Input** | Their name and phone number, sometimes an invoice number. |
| **What they need to see** | Their own balance or invoice, the line items in plain words, and a way to pay that never involves reading a card number aloud. |
| **What they do with it** | Pay through the link they are sent, or accept the explanation, or say they still disagree. |
| **Time available** | Billing lookups run about 90 to 115 seconds at the median. |
| **Must never** | Show or read anyone else's account. Take a card number by phone. Argue about a disputed amount or promise a refund: a caller who disagrees with an amount goes to a supervisor callback. |

**Why an agent, not a self-service portal:**
A portal can show a balance and line items, and a text link can take payment. If the caller is willing to log in, they don't need the agent.

What a portal can't do:
1. Callers are already on the phone and don't know their invoice number; they know their name and number.
2. "What is this $245 invoice for?" is a question about meaning ("diagnostic visit plus capacitor"), not a lookup.
3. The caller may want two things in one call (balance, then "how do I set up autopay?").

This is the weakest of the three cases. If the supplied invoice data is thin, the value is only convenience, and a payment link may be enough. The data check that confirms it is whether the `invoices` table's `line_items` give meaningful descriptions.

---

## 6. The minimum product

**First iteration.** A caller can phone (or type, in the demo) and get one of five outcomes: a visit booked, a correct policy answer, a balance or payment link, a safe handoff to a human with their story carried over, or an urgent safety message. This is what someone would open it for on a Tuesday evening.

| # | Feature | Use case | What it does for the caller | Acceptable in v1 |
|---|---|---|---|---|
| 1 | Safety check on every call | UC-1 | Gas, CO, sparks or smoke gets "leave the house, call 911," not a booking. A burning smell gets the follow-up question first. | Never books these. Not yet asked: how fast. |
| 2 | Find the caller's account by name and phone | UC-1, UC-3 | They don't repeat an account number. | Not yet asked: what to do if there is no match (treat as a new customer?). |
| 3 | Check availability and book | UC-1 | They hear a yes or a set of alternatives, with date, window and tech name. The booking is written to the scheduling database. | A confirmed booking is the bar *(PRD)*. Matches the caller's zone, service type and membership tier. |
| 4 | Answer fee, membership, warranty, hours and service-area questions | UC-2 | A short, correct answer with the condition that matters. | Wrong answer is worse than a handoff *(PRD)*. Not yet asked: wording of the "I'm not sure" reply. |
| 5 | Look up balance and invoice line items; send a payment link | UC-3 | They see what they owe and why, and pay without saying a card number. | Their own account only. |
| 6 | Hand off to a human, with context | all | The caller is told what is happening; the person who picks up knows what was said. Disputes, refunds, complaints and manager requests get a supervisor callback within one business day. | The human should not need to start over *(PRD)*. |

> **A tension to resolve.** Using the provisional counts, the six features above could in principle resolve about 58% of calls (booking 120, warranty 45, membership questions 38, billing lookups 42: 245 of 420) even if every one worked perfectly, which is just under the bottom of the PRD's range. The PRD target is 60 to 75% containment. Reaching the top of that range depends on items currently in "later iterations." This is the main open scope question.

**Later iterations,** in the order the caller would want them. Later is not out of scope; it's the plan.

| # | Feature | Use case | What it adds for the caller | Why not first |
|---|---|---|---|---|
| 1 | Confirm, move or cancel an existing appointment | UC-1 | The 38 calls (9.0%) about an appointment they already have; frees the old slot | Adds write paths and the 24-hour late-cancellation fee rules; the PRD says keep scheduling simple. The schema documents it, so a reviewer may probe it. |
| 2 | Membership actions: set up autopay, cancel auto-renew, upgrade | UC-2 | 33 calls (7.9%) that today need a person | The agent would have to change account state, which nothing supplied lets it do. |
| 3 | Book a free Comfort Advisor estimate for a new system | UC-1 | The 12 calls (2.9%) about replacing a system | Different appointment type; needs the estimate slots. |
| 4 | Redirect commercial, employment and wrong-number callers | UC-2 | Meridian's documented redirects, so the caller isn't stuck | Small volume (3.8%); mostly a script. |
| 5 | "My technician is late" handling | UC-1 | The 9 calls (2.1%) where the window has passed | Needs dispatch information the data doesn't have. |
| 6 | Double-charge explanation (pending authorization) | UC-3 | The 11 calls (2.6%) about two charges | The FAQ gives guidance, but the internal policy sends billing disputes to a supervisor; which applies is a question for the exec team. |

---

## 7. Explicitly out of scope

| Not doing | Why |
|---|---|
| Answering phone calls by voice | The PRD calls voice extra credit, and the builder has asked to ignore bonuses for now. The first iteration is chat. |
| Resolving disputes, refunds, complaints and manager requests | A person has to decide these. Meridian's policy sends them to a supervisor callback; the agent only captures the case. |
| Emergencies beyond the safety message | The caller needs 911 or the gas utility, and the scheduling database does not book them. |
| Quoting a firm repair price | Meridian's policy: "the technician will confirm pricing on site." |
| Taking card numbers by phone | Meridian never does; it sends a secure payment link. |
| Commercial work, duct cleaning, appliance repair, window units | Meridian doesn't do this, or refers it out. |

---

## 8. Constraints we were given

| Constraint | What it is | Given by |
|---|---|---|
| Timeline | Submission **Thu 2026-10-22**. Time of day and time zone not yet given. What to drop first if half done: not yet asked. Deliverables: a deployed public URL, a 3 to 4 minute walkthrough video, and a source repository with README and eval numbers. | The builder; deliverables from the PRD |
| Team | One person. | The builder |
| Spend | No cap for now. | The builder |
| Services / vendors | **Approved list (builder may choose from it):** Anthropic, Aqua Voice, Cohere, Cursor, DigitalOcean, ElevenLabs, Google One, Midjourney, OpenAI, OpenRouter, Railway, Vultr, Whisper. A free tier of anything outside the list is allowed. | The builder |
| Hardware in hand | None stated. The PRD requires a public web URL. | The PRD |
| Must integrate with | The supplied scheduling database (SQLite plus CSV, documented in `SCHEMA.md`) and the supplied knowledge base. Bookings must actually write to the database; the reviewer tests against the same data and four seeded customers. "Today" is 2026-10-16 and slots run for three weeks. | The PRD and dataset README |
| Intended use | Internal demo. | The builder |
| Regulatory / contractual | None stated. The company and data are synthetic. | The builder |

---

## 9. Evidence limitations

- **The call mix** is a provisional keyword labelling of the first two customer turns of 420 synthetic calls. It sizes scope; it is not the final clustering, and it would shift if calls were labelled by their full content.
- **The calls are synthetic and templated.** About 80 distinct openings repeat across 420 calls, so the mix reflects how the dataset was made. It may not match a real caller population.
- **The first-iteration ceiling of about 58%** is arithmetic on the provisional counts, assuming every handled call resolves. It is an illustration, not a prediction.
- **The outside call-answering and abandonment figures** are from secondary vendor pages and summaries of CallRail, Invoca and ContactBabel; the primary reports were not opened. They differ in definition and period, and are not combined. None measures Meridian.
- **Wait times, hold times and staffing** for Meridian are not in the data. The statement that the call center is capacity constrained comes from the PRD.
- None of these sources measures whether an AI agent improves outcomes for Meridian's callers.

---

## References

1. AEA FDE Challenge: AI Call Center Agent (PRD). `docs/AEA_FDE_Challenge.pdf`.
2. Meridian dataset: `data/meridian_dataset/` (420 transcripts, knowledge base, scheduling database).
3. Provisional call-intent labelling: `analysis/classify_openings.py`, output `analysis/provisional_labels.csv`.
4. Secondary summaries of home-services missed-call benchmarks (CallRail 2025, Invoca 2026): <https://www.zyratalk.com/blog/what-a-missed-call-actually-costs-a-home-service-business/>, <https://getaira.io/blog/missed-business-calls-statistics>.
5. Secondary summaries of call-abandonment benchmarks (ContactBabel 2024 UK): <https://www.ringly.io/blog/call-abandonment-rate-statistics-2026>.

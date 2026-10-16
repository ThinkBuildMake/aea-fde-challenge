# Questions for the Meridian exec team

Pass 1. `USERS.md` is provisional until the starred items are answered. Everything here is something the builder could not answer firsthand. Claims in `USERS.md` marked *(PRD)* come from the challenge brief and are what these questions test.

## Load-bearing (the answer changes who the user is or which moments we target)

- ★ What is the call center's current average wait, abandonment rate and number of staff on a typical day? — unblocks: Section 2. If waits are short, the case for the agent shifts from capacity to cost.
- ★ Is billing (balance, invoice line items, payment link) something the AI should handle, or does finance want those calls to stay with people? — unblocks: UC-3, Section 6 row 5.
- ★ Which counts as "contained" for you: a caller who got an answer and hung up, or one whose booking was written to the schedule? — unblocks: Section 6 (the minimum) and the metrics document.
- ★ For a caller who says "I was charged twice," should the agent explain pending authorizations (the FAQ's answer) or always send it to a supervisor (the internal escalation policy)? — unblocks: Section 6 later row 6.

## Detail (the answer fills a row)

- Which document wins when two disagree, for example cancellation notice (24 hours in the FAQ, 48 in the scheduling guide)? — unblocks: UC-2 "Must never".
- The FAQ says the phone line is closed Sunday, yet 66 supplied calls are timestamped on Sundays. Is the line open, or are those timestamps unreliable? — unblocks: UC-2.
- There are no plumbing slots in the north zone. Should a north-zone plumbing caller be offered a different zone, a waitlist or a human? — unblocks: UC-1.
- If the caller's name and phone don't match any account, treat them as a new customer or hand off? — unblocks: Section 6 row 2.
- How should a "burning smell from the vents" call be triaged when the caller doesn't mention a tripped breaker? The policy says electrical burning smell *combined with tripped breakers* is an emergency. — unblocks: UC-1 "Must never".
- What should the agent say, and promise, when it hands a caller to a supervisor callback ("within one business day")? — unblocks: Section 6 row 6.

## Things the dataset asserts that are worth confirming

- "Agents may waive the $49 late-cancellation fee once per year" (internal discretion notes): is this something the AI is allowed to do, or only people?
- `duct_cleaning.md` says "TODO — Marcy to write up partner referral process." Should the agent say "we refer this out" and nothing more?

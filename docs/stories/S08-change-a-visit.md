### S08 — Check, move or cancel a visit already booked

**Blocked by:** S06
**Review gate:** blocking — first slice of visit changes; the fee wording is a domain decision
**Requirements:** FR-1.11, FR-1.12, FR-2.8, AZ-2, AZ-3, VR-6, CT-3, DP-4

#### Why
Callers with a visit already booked (29 of 420 calls) hear what is on file and can move or cancel it. The fee rule is stated plainly and never waived by the agent. One command puts the database back to the seed for the next demo.

#### What you'll see
1. Reset the database. In the chat, send "Can you check my visit? Linda Foster, 512-555-0101."
2. Ask to move it to Monday afternoon, then check the old slot with `sqlite3`.
3. Set `REFERENCE_DATE=2026-10-21`, restart, and ask to cancel. Then run the reset command.

#### Acceptance criteria
1. The visit on file
   Given the seeded database
   When Linda Foster is matched and asks to check her visit
   Then the reply says Thursday 2026-10-22, 8 AM to 12 PM, with Marta Kowalski

2. A free move
   Given her visit is shown and the reference date is 2026-10-16
   When she asks to move it and picks Monday 2026-10-19, 12 PM to 4 PM, Ray Mendoza
   Then the "Visit booked" card shows the Monday window and the reply says the move is free

3. `invariant` The old window is freed
   Given the move from criterion 2
   When I query the supplied database
   Then the Thursday 2026-10-22 08:00-12:00 Marta Kowalski slot is `open` and appointment 159 points at slot 42

4. A late cancel states the fee
   Given a fresh seed and `REFERENCE_DATE=2026-10-21`
   When Linda Foster sends "Cancel my Thursday visit."
   Then the reply states the $49 late-cancellation fee because the visit is within 24 hours, and the visit is cancelled

5. `invariant` No waiver from the agent
   Given the $49 fee has been stated
   When she sends "Can you waive that fee for me?"
   Then the reply does not waive it and the "Passed to a person" banner appears

6. `invariant` No change without an explicit request
   Given Linda Foster is matched
   When she sends "I might not be home Thursday."
   Then appointment 159 is still `scheduled` on its original slot

7. Reset to the seed
   Given bookings and cancels from this demo
   When I run the documented reset command
   Then it reports 323 open, 159 booked, 42 reserved_members and 4 blocked slots, and the Handoffs tab still lists the earlier handoffs

#### Not in this story
- Moves or cancels that hit a database failure — picked up by S15

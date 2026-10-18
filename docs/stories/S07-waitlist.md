### S07 — Book the later window and join the waitlist

**Blocked by:** S06
**Review gate:** async — a later slice of booking; the wireframe already fixes the wording, so rework is cheap
**Requirements:** FR-1.15, FR-5.7, VR-10

#### Why
Human agents offer a waitlist in 34 of 420 calls (8.1%). A caller who wants something sooner keeps the earliest real booking and is told staff will call if an earlier window opens. Staff see who is waiting.

#### What you'll see
1. Reset the database, start Omar Patel's booking (S06 criteria 1 and 2), and tap "Nothing earlier? Ask for an earlier window".
2. Tap "Book ... and join the waitlist for earlier".
3. Open `/business` → Waitlist.

#### Acceptance criteria
1. `wireframe` Wants earlier state
   Given Omar Patel is matched and the window buttons are showing
   When I tap "Nothing earlier? Ask for an earlier window"
   Then the reply names Wednesday 2026-10-21, 8 AM to 12 PM as the earliest window, says the team will call if an earlier one opens, and shows three buttons: book it and join the waitlist, book it only, and "Talk to a person instead"

2. `wireframe` Waitlisted state
   Given the three buttons are showing
   When I tap the "and join the waitlist for earlier" button
   Then the "Visit booked" card shows the Wednesday window and the line "On the waitlist for an earlier window. The team will call you if one opens."

3. `invariant` The waitlist changes no slot
   Given the database holds the booking from criterion 2
   When I compare slot and appointment rows with the moment before the waitlist was joined
   Then exactly one `waitlist_entries` row was added and no slot or appointment row changed other than the booking itself

4. `invariant` Asking twice writes one row
   Given Omar Patel is already on the waitlist for the Wednesday window
   When I send "Please add me to the waitlist again."
   Then `waitlist_entries` still has one row for him

5. `wireframe` Waitlist tab
   Given the entry from criterion 2
   When I open the Waitlist tab
   Then a row shows Omar Patel, Kyle, "HVAC repair, earlier than Wednesday 2026-10-21 8 to 12", and how long ago he joined

6. Booking only
   Given the three buttons are showing
   When I tap the "only" button
   Then the "Visit booked" card shows no waitlist line and the Waitlist tab gains no row

7. A person instead
   Given the three buttons are showing
   When I tap "Talk to a person instead"
   Then the "Passed to a person" banner appears and nothing is booked

#### Not in this story
- Staff action on a waitlist entry: v1 lists entries only (FR-5.7)

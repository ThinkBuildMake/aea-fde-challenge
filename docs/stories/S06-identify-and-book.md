### S06 — Identify the caller and book a visit

**Blocked by:** S03, S04
**Review gate:** blocking — first slice of booking; writes to the supplied database the reviewer will inspect
**Requirements:** FR-1.3, FR-1.4, FR-1.5, FR-1.7, FR-1.8, FR-1.9, FR-1.10, GC-6, VR-6, VR-7, VR-8

#### Why
The largest call driver (120 of 420 calls). The caller describes the problem, is matched to their account, picks a real open window in their zone, and the booking is written to the scheduling database before the agent says "booked".

#### What you'll see
1. Reset the scheduling database to the seed (S08 criterion 7, or a fresh deploy).
2. Click the chip "My AC is blowing warm air", answer "No", then send "Omar Patel, 512-555-0102".
3. Tap the first window, then check the database with `sqlite3`.

#### Acceptance criteria
1. `wireframe` Booking state: safety question, then visit type
   Given I sent "My AC is blowing warm air." and was asked "Sorry to hear that. Is there any burning smell, smoke, sparks or a tripped breaker?"
   When I answer "No, it just blows warm."
   Then the reply says it will book an HVAC repair visit and asks for my name and phone number

2. `wireframe` Matched caller sees real windows
   Given the agent asked for my name and phone
   When I send "Omar Patel, 512-555-0102"
   Then window buttons appear, the first reading Wednesday 2026-10-21, 8 AM to 12 PM, Jun Park, and the last reading "Nothing earlier? Ask for an earlier window"

3. `wireframe` Confirmed state
   Given the window buttons are showing
   When I tap the Wednesday 8 AM to 12 PM button
   Then a green "Visit booked" card shows the date, "8 AM to 12 PM", "Technician Jun Park" and "Diagnostic fee $89, credited toward the repair", followed by the "Did this solve it?" bar

4. `invariant` The booking is really written
   Given the booking card is showing
   When I query the supplied database
   Then slot 115 is `booked` and exactly one new `appointments` row links slot 115 to MHC-10002

5. No match means no account and a person
   Given the agent asked for my name and phone
   When I send "Jane Doe, 512-555-9999"
   Then the reply says it cannot find the account, the "Passed to a person" banner appears, and `customers` still has 154 rows

6. Member-only windows stay with members
   Given Daniel Reyes (Georgetown, no membership) is matched for an HVAC repair
   When the window buttons appear
   Then none of them is Friday 2026-10-16, 8 AM to 12 PM, Ray Mendoza

7. No plumber in the north zone
   Given Daniel Reyes is matched
   When he sends "My kitchen sink is leaking under the cabinet."
   Then the reply says no plumber is available in his area right now, the "Passed to a person" banner appears, and no slot changes

#### Not in this story
- "Nothing earlier?" and the waitlist — picked up by S07
- Moving or cancelling this visit — picked up by S08
- Two callers racing for one slot — picked up by S15

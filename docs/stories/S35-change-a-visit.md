### S35 — Check, move or cancel a visit from the chat

**Kind:** wiring
**Blocked by:** S33, S08, S30
**Review gate:** human demo
**Size:** M — three seams: `lookup_my_appointments`, `move_visit` and `cancel_visit` into Scheduling, with the late fee from Knowledge
**Wires:** a visit change (Conversation → `listAppointments` → `moveVisit` or `cancelVisit` → supplied database commit → `visit_changes` → `getFee(FEE-LATE)`)
**Extends:** none
**Requirements:** FR-1.3 (service address), FR-1.10 (fee waived for members), FR-1.11, FR-1.12, FR-2.8, AZ-2 (live)
**Guards:** AZ-2, AZ-3, VR-6, PF-2

#### Why
A caller with a visit on file hears when it is and can move or cancel it. The old window frees up for someone else, and the late fee is stated, never waived.

#### How it's checked
Demo on the deployed URL, reference clock 2026-10-16 12:00 as deployed:
1. Identify as Linda Foster by service address, ask about her visit, move it, then cancel it.
2. As Grace Okafor, book plumbing slot 35 (Saturday 2026-10-17 8 AM, fewer than 24 hours away), then cancel it.
3. Open the supplied database and the Overview.

#### Acceptance criteria
1. A visit on file, by service address
   Given a new conversation
   When I send "When is my visit? Linda Foster, 4412 Oak Hollow Dr."
   Then the reply states Thursday 2026-10-22, 8 AM to 12 PM, with Marta Kowalski

2. A move frees the old window
   Given she asked to move it to Monday and Monday's windows are shown
   When I click the first
   Then the "Visit booked" card shows the new Monday window and reads "Diagnostic fee waived for members" (a wireframe addition approved on 2026-10-19)
   And the supplied database shows slot 159 `open` and the new slot `booked` on the same appointment

3. Nothing changes without a clear yes
   Given a new conversation as Linda Foster
   When I send "Maybe I'll cancel, I'm not sure"
   Then her appointment is still `scheduled`

4. A cancel more than 24 hours out is free
   Given Linda Foster's Monday visit
   When she sends "Cancel my visit"
   Then the reply says there is no fee and asks her to confirm

5. The cancel happens on a yes
   Given that question
   When she sends "Yes, cancel it"
   Then the appointment is `cancelled` and its slot is `open`

6. A cancel inside 24 hours states the fee
   Given Grace Okafor holds plumbing slot 35, Saturday 2026-10-17 8 AM to 12 PM
   When she sends "Cancel my visit"
   Then the reply states the $49 late-cancellation fee and asks her to confirm

7. The fee is not waived
   Given that conversation
   When she sends "Can you waive the $49?"
   Then the reply does not waive or promise to waive it and offers a person

8. Write turns stay fast and bookings agree
   Given the move and cancel turns
   When I open the Overview
   Then the "at most 10 s" row reads within limit (PF-2: "p95 time for a turn containing a database write ≤ 10 s")
   And "Booking completion" is above 0% and the booking-mismatch row reads 0, within limit

9. The gate checks the seams for real
   Given the regression gate with the real Conversation, Scheduling and Knowledge modules on a seed copy
   When a recorded conversation moves appointment 159
   Then slot 159 is `open`, the new slot is `booked`, and a `move` audit row exists
   And a forged cancel of an appointment the caller does not own changes nothing and the reply offers a person

#### Not in this story
- Rescheduling and cancellation scenarios in the eval — picked up by S41

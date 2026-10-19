### S34 — Book the earliest window and join the waitlist

**Kind:** wiring
**Blocked by:** S33, S11, S23
**Review gate:** human demo
**Size:** S — one seam: `join_waitlist` through `getAppointment` into Follow-ups, shown on the Waitlist tab
**Wires:** a waitlist join (Conversation → Scheduling `getAppointment` → Follow-ups `joinWaitlist`) and `listWaitlist` on the Waitlist tab; removes the waitlist stubs in S21 and S23
**Extends:** none
**Requirements:** FR-1.15, FR-5.7, VR-10 (live)
**Guards:** VR-10, DP-4

#### Why
Human agents offer this in 34 calls. A caller who wants sooner keeps the window they have and is called if an earlier one opens.

#### How it's checked
Demo on the deployed URL:
1. Reach Omar Patel's window buttons as in S33. Slot 115 is his from S33's demo, so the first window is now slot 119, Wednesday 2026-10-21 1 PM to 5 PM with Jun Park. Click "Nothing earlier? Ask for an earlier window".
2. Choose book and join the waitlist, then ask again.
3. Open `/business` → Waitlist.

#### Acceptance criteria
1. `wireframe` Wants earlier
   Given Omar Patel's window buttons
   When I click "Nothing earlier? Ask for an earlier window"
   Then the reply names Wednesday 2026-10-21, 1 PM to 5 PM as the earliest, says the team will call if an earlier one opens, and shows three buttons ending with "Talk to a person instead"

2. `wireframe` Booked and waitlisted
   Given those buttons
   When I choose to book it and join the waitlist
   Then the "Visit booked" card adds "On the waitlist for an earlier window. The team will call you if one opens."
   And the app database holds exactly 1 waitlist row for MHC-10002 and no slot other than 119 changed

3. Asking twice writes one row
   Given that entry
   When I send "Put me on the waitlist again"
   Then the reply says he is already on it and the waitlist still holds 1 row for him

4. No specific time promised
   Given the waitlist reply
   When I read it
   Then it names no day or time for the call

5. `wireframe` Staff see the entry
   Given that entry
   When I open the Waitlist tab
   Then a row shows Omar Patel, Kyle, south, "HVAC repair, earlier than Wednesday 2026-10-21 1 to 5", and how long ago he joined

6. The gate checks the seam for real
   Given the regression gate with the real Conversation, Scheduling and Follow-ups modules
   When a recorded conversation joins the waitlist and the scheduling data is then reset to the seed
   Then the entry is still listed with its held date and window
   And a join for an appointment the caller does not own writes no row and the reply offers a person

#### Not in this story
- Calling the caller when an earlier window opens: a person's work (A14)

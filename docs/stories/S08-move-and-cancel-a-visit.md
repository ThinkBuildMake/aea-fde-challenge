### S08 — Move or cancel a visit and free the old window

**Kind:** module
**Blocked by:** S07
**Review gate:** agents
**Size:** M — two write operations on S07's locked transaction and audit table
**Builds:** Scheduling → `moveVisit`, `cancelVisit`, the Move and Cancel rules, the own-visits-only Must hold
**Extends:** the locked transaction and the `visit_changes` write path S07 owns
**Stubs:** none
**Requirements:** AZ-2 (scheduling side)
**Guards:** VR-6, AZ-2

#### Why
A caller can change their own visit. The old window becomes free for someone else, and the 24-hour fee is known before the agent speaks.

#### How it's checked
Tests against a temporary copy of the supplied database, one with the reference clock moved to 2026-10-21 12:00.

#### Acceptance criteria
1. A move frees the old window
   Given the supplied database
   When I move appointment 159 for MHC-10001 to slot 56
   Then slot 56 is `booked`, slot 159 is `open`, `lateFeeApplies` is false, and a `move` row in `visit_changes` names slot 159 as the previous slot

2. A cancel inside 24 hours carries the fee
   Given the reference clock 2026-10-21 12:00
   When I cancel appointment 159 for MHC-10001
   Then the appointment is `cancelled`, slot 159 is `open`, `lateFeeApplies` is true and `hoursBefore` is 20

3. A cancel beyond 24 hours is free
   Given the reference clock 2026-10-16 12:00
   When I cancel appointment 159 for MHC-10001
   Then `lateFeeApplies` is false

4. Only the caller's own visit
   Given the supplied database
   When I cancel appointment 159 for MHC-10002
   Then `AppointmentNotFound` is raised and appointment 159 is still `scheduled`

5. A move into a taken slot changes nothing
   Given the supplied database
   When I move appointment 159 for MHC-10001 into a `booked` slot
   Then `SlotUnavailable` is raised and appointment 159 still holds slot 159

6. A cancelled visit cannot move
   Given appointment 159 cancelled
   When I move it for MHC-10001 to slot 56
   Then `NotEligible` is raised with reason `not_scheduled`

#### Not in this story
- Moving and cancelling from the chat — picked up by S35

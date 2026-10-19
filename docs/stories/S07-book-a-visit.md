### S07 — Book a visit in one locked step

**Kind:** module
**Blocked by:** S01
**Review gate:** agents
**Size:** M — one write operation, its audit table and two gate tests
**Builds:** Scheduling → `bookVisit`, the Book rule, the one-locked-transaction Must hold, Failure behaviour (slot taken, audit insert fails); the `visit_changes` table's write path; the regression gate's race test (RL-1) and forced-interruption test (RL-2)
**Extends:** none
**Stubs:** none
**Requirements:** RL-1, RL-2
**Guards:** VR-6, VR-7, CT-1, DE-2

#### Why
A booking writes the supplied database the reviewer checks. It must never double-book, never half-write, and never book a slot the caller may not have.

#### How it's checked
Tests against a temporary copy of the supplied database, including two gate tests that race and interrupt bookings.

#### Acceptance criteria
1. A booking writes one slot and one visit
   Given the supplied database
   When I book slot 56 for MHC-10004 with the issue "AC blowing warm air"
   Then slot 56 is `booked`
   And one new `scheduled` appointment holds that slot and customer with `created_at` 2026-10-16
   And one `book` row in `visit_changes` names its date, window and technician

2. A taken slot is refused
   Given the supplied database
   When I book slot 159 (already booked) for MHC-10004
   Then `SlotUnavailable` is raised and no row changes

3. Member-only slots need a member
   Given the supplied database
   When I book member-only slot 1 for MHC-10004 (no membership)
   Then `NotEligible` is raised with reason `member_only`

4. Another zone is refused
   Given the supplied database
   When I book south-zone slot 115 for MHC-10004 (north zone)
   Then `NotEligible` is raised with reason `wrong_zone`

5. Racing callers get one booking
   Given two bookings of the same open slot started together
   When the race test runs 20 times
   Then every race writes exactly 1 appointment and the other gets `SlotUnavailable` (RL-1: "0 double bookings over 20 repeated races")

6. An interrupted booking leaves no half
   Given a booking in progress
   When the interruption test kills it 10 times at random points
   Then the invariant query finds 0 booked slots without an appointment and 0 appointments on a non-booked slot (RL-2: "0 orphans after 10 forced interruptions")

7. A failed audit row does not undo the booking
   Given the app database faked to fail on insert
   When I book slot 56 for MHC-10004
   Then the booking is returned, slot 56 is `booked`, and one log line names the failed audit insert

8. A visit type that is not offered is refused
   Given the supplied database
   When I book a north-zone `estimate` slot for MHC-10004
   Then `NotEligible` is raised with reason `wrong_service_type`

9. Nothing before the reference date
   Given the reference date set to 2026-10-19
   When I book member-only slot 1 (2026-10-16) for member MHC-10001
   Then `NotEligible` is raised with reason `before_reference_date`

#### Not in this story
- Moving and cancelling — picked up by S08
- Booking from the chat — picked up by S33

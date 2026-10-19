### S06 — Find open windows and the visits on file

**Kind:** module
**Blocked by:** S01
**Review gate:** agents
**Size:** M — four read operations and the reference clock
**Builds:** Scheduling → `findOpenWindows`, `listAppointments`, `getAppointment`, `schedulingStatus`, the Reference clock rule, and Failure behaviour for an unreadable file
**Extends:** none
**Stubs:** none
**Requirements:** CT-3, GC-8
**Guards:** VR-7

#### Why
Callers are offered only windows they can really book: their zone, their visit type, member-only slots for members, and nothing before "today".

#### How it's checked
Tests against a temporary copy of the supplied scheduling database, with the reference date changed in one, and with an unreadable copy in another.

#### Acceptance criteria
1. A non-member's first window
   Given the supplied database and the reference date 2026-10-16
   When I find HVAC repair windows for MHC-10004 (Georgetown, no membership)
   Then the first window is slot 56, 2026-10-19 08:00-12:00 with Marta Kowalski, and member-only slot 1 is not in the list

2. A member sees member-only slots
   Given the same database
   When I find HVAC repair windows for MHC-10001 (Round Rock, standard)
   Then the first window is slot 1, 2026-10-16 08:00-12:00 with Ray Mendoza, marked member-only

3. No plumber in the north zone
   Given the same database
   When I find plumbing windows for MHC-10004
   Then the list is empty with reason `no_plumber_in_zone`

4. A city with no zone
   Given a test copy with a customer in Manor
   When I find HVAC repair windows for that customer
   Then the list is empty with reason `city_not_in_zone_map`

5. Nothing before the reference date
   Given the reference date set to 2026-10-18
   When I find HVAC repair windows for MHC-10001
   Then no window is dated before 2026-10-18 (CT-3: "no slot before it is offered")

6. A visit on file
   Given the same database
   When I list visits for MHC-10001
   Then the list holds appointment 159, 2026-10-22 08:00-12:00 with Marta Kowalski, HVAC repair

7. Another customer's visit is not found
   Given the same database
   When I read appointment 159 for MHC-10002
   Then `AppointmentNotFound` is raised

8. An unreadable file is reported
   Given the scheduling file made unreadable
   When I find windows for MHC-10001
   Then `SchedulingUnavailable` is raised and `schedulingStatus` reports `error`

9. A day with no window gets the nearest ones
   Given the same database
   When I find HVAC repair windows for MHC-10004 with preferred date 2026-10-18
   Then `matchedRequest` is false and the first alternative is slot 56, 2026-10-19 08:00-12:00 with Marta Kowalski

#### Not in this story
- Booking, moving and cancelling — picked up by S07 and S08

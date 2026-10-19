### S09 — Restore the bookings to the supplied seed, with a backup first

**Kind:** module
**Blocked by:** S03
**Review gate:** agents
**Size:** M — one job with five cases on tables that already exist
**Builds:** Scheduling → `resetScheduling` (command and `POST /admin/reset-scheduling`); System-wide → Backup (the copy before every reset)
**Extends:** Admin routes (S03 owns the token check)
**Stubs:** none
**Requirements:** DP-4
**Guards:** DP-4, CT-1

#### Why
The reviewer and the eval both write real bookings. One command puts the scheduling data back as supplied, and leaves conversations, handoffs and the waitlist alone.

#### How it's checked
Run the reset command on a copy after a test booking, then compare slot counts and table contents with the seed.

#### Acceptance criteria
1. The seed comes back
   Given a copy with one extra booking on slot 56
   When I run the reset command
   Then the slot counts are 323 open, 159 booked, 42 reserved for members and 4 blocked, as in the seed

2. App data is left alone
   Given one conversation, one handoff and one waitlist entry in the app database
   When I run the reset command
   Then all three are still there

3. The audit rows are retired
   Given one `book` row in `visit_changes`
   When I run the reset command
   Then that row has `retired_at` set

4. A backup is taken first
   Given the reset command is run
   When I list the backup folder
   Then it holds a copy of the scheduling file and of the app database made just before the reset

5. A reset waits for a booking
   Given a booking transaction holding the write lock past the lock-wait limit
   When I call the reset route with the admin token
   Then the answer is 409 `busy` and the file is unchanged

#### Not in this story
- Running the reset on the deployed app — picked up by S40

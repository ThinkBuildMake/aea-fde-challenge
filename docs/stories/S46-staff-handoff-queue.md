### S46 — Let staff list open handoffs and mark them followed up

**Kind:** module
**Blocked by:** S10
**Review gate:** agents
**Size:** M — two routes on S10's table, six cases
**Builds:** Follow-ups → `listHandoffs` (`GET /handoffs`), `markHandoffFollowedUp` (`POST /handoffs/:id/followed-up`), the "followed up is reached from open, open again only by the undo" Must hold
**Extends:** the `handoffs` write path S10 owns (status and `followed_up_at`)
**Stubs:** none
**Requirements:** none of its own — these routes sit behind FR-5.5 and FR-5.8, which S31 and S32 deliver
**Guards:** none

#### Why
Staff need the list of people waiting for a call, oldest first, and a way to tick each one off, with an undo for a slip.

#### How it's checked
Route tests against a temporary app database seeded with handoffs.

#### Acceptance criteria
1. The open queue, oldest first
   Given two open handoffs and one followed up
   When I call `GET /handoffs`
   Then two handoffs are listed, oldest first, with no conversation's secret id in the body

2. The followed-up list
   Given the same handoffs
   When I call `GET /handoffs?status=followed_up`
   Then one handoff is listed

3. A bad status is refused
   Given the app running
   When I call `GET /handoffs?status=done`
   Then the answer is 422 `invalid_status`

4. Marking followed up
   Given an open handoff
   When I post to its followed-up route with no body
   Then its status is `followed_up` and `followed_up_at` is set

5. Marking twice changes nothing
   Given a handoff already followed up
   When I post to its followed-up route again
   Then its `followed_up_at` is unchanged

6. Undo
   Given a handoff followed up
   When I post `{"followedUp": false}`
   Then its status is `open` again and `followed_up_at` is cleared

#### Not in this story
- The Handoffs tab — picked up by S23
- The queue on real handoffs — picked up by S31 and S32

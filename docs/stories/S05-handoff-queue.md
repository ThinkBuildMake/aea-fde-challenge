### S05 — Staff work the handoff queue

**Blocked by:** S03, S04
**Review gate:** blocking — first slice of the staff side; what the follow-up person needs to see is a UX decision
**Requirements:** FR-4.2, FR-5.5, FR-5.8 (proposed)

#### Why
The person who calls back sees who called, why, what the agent already said, and when to call, so the caller never repeats their story. Staff mark each one done.

#### What you'll see
1. Create a dispute handoff (S04 criteria 1 and 2) and a gas safety stop (S03 criterion 1).
2. Open `/business` and click the Handoffs tab.
3. Click "Mark followed up" on one row, then undo it.

#### Acceptance criteria
1. `wireframe` A row holds the whole record
   Given the dispute handoff with "Afternoon" chosen
   When I open the Handoffs tab
   Then its row shows the caller, a summary saying they were charged twice and were told a supervisor calls within 1 business day, and "Prefers afternoon"

2. `wireframe` Mark followed up
   Given the "Handoffs waiting for follow-up" tile shows 2
   When I click "Mark followed up" on the dispute row
   Then the button reads "Followed up (undo)" and the tile shows 1

3. Undo
   Given a row marked followed up
   When I click "Followed up (undo)"
   Then the button reads "Mark followed up" again and the tile shows 2

4. Safety stops are in the queue
   Given the gas conversation from S03
   When I open the Handoffs tab
   Then a row marks it as a safety stop and says the caller was told to leave and call 911

5. No preference shown honestly
   Given a handoff where no call-back time was picked
   When I open the Handoffs tab
   Then that row shows "No preference"

6. Oldest first
   Given the safety stop was created before the dispute
   When I open the Handoffs tab
   Then the safety stop row is above the dispute row

#### Not in this story
- Rows for an unmatched caller, which show the name they gave as unverified — appear once S06 hands off a failed match
- Handoff counts on the Overview — picked up by S11

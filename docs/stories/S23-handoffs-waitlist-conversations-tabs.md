### S23 — The business view's Handoffs, Waitlist and Conversations tabs

**Kind:** module
**Blocked by:** S22
**Review gate:** agents
**Size:** M — three tabs on S22's page, against stubbed lists
**Builds:** the client's business view tabs Handoffs (with "Mark followed up" and undo), Waitlist, and Conversations (list, detail panel, "Flag as wrong" with a note, "Turn into a test scenario", and the "Open trace" link per turn, an addition to the wireframe)
**Extends:** the business view page S22 owns
**Stubs:** `listHandoffs`, `markHandoffFollowedUp`, `listWaitlist`, `listConversations`, `getConversation`, `flagConversation`, `createEvalCandidate` contract stubs (removed by S31, S32, S34 and S38)
**Requirements:** none of its own — these tabs show FR-5.4, FR-5.5, FR-5.7 and FR-5.8, which S31, S32, S34 and S38 deliver
**Guards:** none

#### Why
Staff work the people-queues and read conversations here. The handoff row must say enough that nobody asks the caller to repeat the story.

#### How it's checked
Browser tests (Playwright) of each tab against stubbed lists.

#### Acceptance criteria
1. `wireframe` A handoff row
   Given one open handoff for Omar Patel, charged twice, told a supervisor calls within 1 business day, preferring afternoon
   When I open the Handoffs tab
   Then the tab is headed "Handoffs and callback requests"
   And its row shows the caller, a summary with the reason and what he was told, and "Prefers afternoon"

2. `wireframe` Mark followed up
   Given that row
   When I click "Mark followed up"
   Then the button reads "Followed up (undo)"

3. A safety stop in the queue
   Given one open handoff of kind `safety_stop`
   When I open the Handoffs tab
   Then its row is marked as a safety stop (a wireframe addition approved on 2026-10-19) and can be marked followed up

4. `wireframe` A waitlist row
   Given one entry for Omar Patel, Kyle, HVAC repair, holding 2026-10-21 08:00-12:00
   When I open the Waitlist tab
   Then the tab is headed "Waitlist for earlier windows"
   And a row shows Omar Patel, Kyle, south, "HVAC repair, earlier than Wednesday 2026-10-21 8 to 12", and how long ago he joined (the zone is a wireframe addition approved on 2026-10-19)

5. `wireframe` Conversation list and detail
   Given three conversations
   When I click the first one in the Conversations tab
   Then the list shows how long ago, what it was about and its outcome, and the right panel shows the transcript, the number of turns, the first-reply time, the cost and "Tools called:" with the tools

6. Flag with a note
   Given the "Flag as wrong" box, labelled "What was wrong? (note saved with the flag)", open with the note "quoted the wrong window"
   When I save
   Then the button reads "Flagged as wrong (undo)"

7. `wireframe` Turn into a test scenario
   Given an ended conversation's detail
   When I click "Turn into a test scenario"
   Then the panel shows "Saved as a candidate test scenario" with its CAND- name and "Review it, then add it to the eval set."

8. Open trace
   Given a turn with a trace id
   When I read its row in the detail panel
   Then an "Open trace" link after "Tools called:" points at that trace in Langfuse; a turn without a trace id has no link

9. A failure-driven handoff is marked
   Given one open handoff with `byError` true and reason `provider_failure`
   When I open the Handoffs tab
   Then its row shows "after an error" beside the reason (a wireframe addition approved on 2026-10-19)

#### Not in this story
- These tabs on real data — picked up by S31, S32, S34 and S38

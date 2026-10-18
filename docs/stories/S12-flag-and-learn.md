### S12 — Flag a bad conversation and turn it into a test

**Blocked by:** S11
**Review gate:** async — a later slice of the business view; the wireframe fixes the layout and rework is cheap
**Requirements:** FR-5.4, OB-1, OB-4, CP-1

#### Why
Staff can read any conversation, flag a wrong answer with a note, and turn it into a draft test scenario. This is the first step of the learning loop the PRD asks for (goal 7). The rest of the loop is described in the README.

#### What you'll see
1. Open `/business` → Conversations and click a conversation.
2. Click "Flag as wrong", type a note, then click "Turn into a test scenario".
3. Run the export command and open the new file under `eval/candidates/`.

#### Acceptance criteria
1. `wireframe` Conversation list
   Given conversations from earlier demos
   When I open the Conversations tab
   Then they are listed newest first, each with how long ago it was, what it was about, and its outcome

2. `wireframe` Conversation detail
   Given the list
   When I click the booking conversation
   Then the right panel shows the transcript, the number of turns, the first-reply time, the cost, and "Tools called:" with the tools used

3. A flag needs a note
   Given the detail panel is open
   When I click "Flag as wrong" and save with the note box empty
   Then no flag is saved and the page asks for a note

4. A flag is counted
   Given the "Flagged wrong" tile on the Overview reads 0%
   When I flag a contained conversation with the note "quoted the wrong window"
   Then the button reads "Flagged as wrong (undo)" and the Overview's "Flagged wrong" tile is above 0%

5. `wireframe` Turn into a test scenario
   Given a conversation that has ended
   When I click "Turn into a test scenario"
   Then the panel shows "Saved as a candidate test scenario" with its CAND- name and "Review it, then add it to the eval set."

6. Export to the repository
   Given one saved candidate
   When I run the documented export command against the deployed URL
   Then a file `eval/candidates/CAND-xxxxxxxx.json` appears with the caller's messages and empty expected fields

7. `invariant` No card numbers in drafts
   Given a conversation in which "4111 1111 1111 1111" was sent
   When it is turned into a test scenario and exported
   Then the exported file contains no run of 13 to 19 digits

#### Not in this story
- Filling in the expected outcome and adding the draft to the eval set: a person's work (`ARCHITECTURE.md` → Feedback loop, step 5)

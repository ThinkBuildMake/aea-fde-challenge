### S38 — Read a conversation, flag it, and turn it into a test

**Kind:** wiring
**Blocked by:** S30, S19, S23
**Review gate:** human demo
**Size:** M — three seams: the Conversations tab to Monitoring, Monitoring to Conversation's idle close, and the export command to the admin route
**Wires:** `listConversations` (with `closeIdleConversations`), `getConversation`, `flagConversation`, `createEvalCandidate` from the Conversations tab, and `exportEvalCandidates` through `GET /admin/eval-candidates`; removes the Conversations stubs in S23 and the idle-close stub in S19
**Extends:** none
**Requirements:** FR-5.4, OB-4, OB-1 (live)
**Guards:** CP-1, AZ-1

#### Why
This is the first step of the learning loop the PRD asks for: staff read what the agent did, flag a wrong answer with a note, and turn it into a draft test that lands in the repository.

#### How it's checked
Demo on the deployed URL:
1. Open `/business` → Conversations and click S29's "$79" conversation.
2. Flag a conversation, then turn one into a test scenario.
3. Send a card number in a new chat, turn that conversation into a test, and run the export command against the deployed URL.

#### Acceptance criteria
1. `wireframe` The real list
   Given the conversations from earlier demos
   When I open the Conversations tab
   Then they are listed newest first, each with how long ago, what it was about and its outcome

2. `wireframe` The real detail
   Given the list
   When I click S29's "Is the diagnostic fee $79?" conversation
   Then the right panel shows the transcript, the number of turns, the first-reply time, the cost, and "Tools called:" listing `search_knowledge`

3. A flag needs a note
   Given the "Flag as wrong" box open with no note
   When I save
   Then no flag is saved and the page asks for a note

4. The flag metric moves
   Given the "Flagged wrong" tile reads 0% and the box open on a contained conversation with the note "quoted the wrong window"
   When I save
   Then the button reads "Flagged as wrong (undo)" and "Flagged wrong" is above 0%

5. `wireframe` A draft test
   Given an ended conversation
   When I click "Turn into a test scenario"
   Then the panel shows "Saved as a candidate test scenario" with its CAND- name and "Review it, then add it to the eval set."

6. The draft lands in the repository
   Given that draft
   When I run the documented export command against the deployed URL
   Then `eval/candidates/CAND-xxxxxxxx.json` appears with the caller's messages and empty expected fields (OB-4: "one documented command")

7. No card number in a draft
   Given an ended conversation in which I sent "My card is 4111 1111 1111 1111"
   When it is turned into a test and exported
   Then the file holds no run of 13 to 19 digits

8. The gate checks the seams for real
   Given the regression gate with the real Monitoring and Conversation modules
   When it lists conversations with one idle past the limit
   Then that conversation is listed with its outcome set, and no listed or detailed conversation carries a secret id
   And a flag on an unknown public id gets 404 `conversation_not_found`

#### Not in this story
- Filling in the expected outcome and adding the draft to the eval set: a person's work (`ARCHITECTURE.md` → Feedback loop, step 5)

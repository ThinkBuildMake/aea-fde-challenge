### S42 — Write the README and record the walkthrough video

**Kind:** module
**Blocked by:** S41
**Review gate:** agents
**Size:** M — a document and a recorded video, from S41's numbers
**Builds:** the README (run steps, eval numbers, service inventory, learning loop, reference-clock note, the label agreement sample) and the 3 to 4 minute walkthrough video
**Extends:** none
**Stubs:** none
**Requirements:** GC-2, GC-4, GC-8 (README note), EV-3 (README), EV-6, DP-5, OB-4 (loop described)
**Guards:** GC-2

#### Why
The PRD's deliverables are the URL, the video and the repository with its numbers. These turn the built product into something a reviewer can judge in a few minutes.

#### How it's checked
A README check against a list of required sections, a timed clone-to-run on a clean machine, and the video's length read from its file. The builder watches the video before it is submitted.

#### Acceptance criteria
1. The numbers are in the README
   Given S41's run record
   When I read the README
   Then it lists each of the 31 results, projected containment with its weighting, accuracy on the 10 handled-driver scenarios and the escalation result on the 14 must-escalate scenarios, and says 31 scenarios give a coarse projection with no confidence interval

2. Clone to running in 15 minutes
   Given a clean machine and only the README
   When a person follows it
   Then the app runs locally within 15 minutes (DP-5: "≤ 15 minutes")

3. Every paid service is approved
   Given the README's service inventory
   When I compare it with the approved list
   Then 0 paid services are off the list (GC-4: "0 off-list paid services")

4. The video's length and topics
   Given the recorded video file
   When I read its length and check it against the four topics
   Then it runs 3:00 to 4:00 and covers how the drivers were found, chunking and retrieval choices, how escalation works, and what the eval numbers say

5. The labels were checked by a person
   Given the builder's read of 20 random calls
   When I read the audit's agreement line
   Then at least 17 of 20 agree with the labels (EV-6: "agrees with the labels on ≥ 17")

6. The learning loop is described
   Given the README
   When I read its learning-loop section
   Then it walks the six steps from logging to rerunning the eval, saying which are software and which are a person's work

7. The fixed clock is explained
   Given the README
   When I read the scheduling note
   Then it says "today" is fixed at 2026-10-16 until 2026-11-05 and why

#### Not in this story
- Nothing further; this is the last story

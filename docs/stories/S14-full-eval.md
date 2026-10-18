### S14 — Run the 31 scenarios and print the containment numbers

**Blocked by:** S07, S08, S09, S10, S13
**Review gate:** blocking — these are the numbers in the README and the video; reading them right is the builder's call
**Requirements:** EV-1, EV-2, EV-3, EV-7, VR-1, VR-2, VR-3, VR-4, VR-5, VR-6, VR-7, VR-9, AZ-1, AZ-3, RL-3, CT-2, SC-2

#### Why
The PRD's question is "is the containment number real?" One command plays all 31 key scenarios against a private copy of the data and prints the numbers the README reports.

#### What you'll see
1. From a clean checkout, run the eval command as the README says.
2. Read the printed summary: per-scenario results, projected containment with its weighting, accuracy, escalation and the Gate counters.
3. Open the run record file it wrote.
4. Check the record's environment fields (DE-3), judge agreement (EV-5), median booking turns (PF-3), and that the README's numbers match.
5. Run the compare command on this run and the previous one (CH-2).

#### Acceptance criteria
1. Every scenario reported
   Given the 31 scenario files listed in EV-1
   When I run the eval command
   Then the output lists 31 results, each with its observed outcome and pass or fail

2. Fast enough to rerun
   Given a clean checkout and 4 parallel workers
   When I time the eval command
   Then it finishes within 15 minutes (EV-7: "≤ 15 minutes")

3. Projected containment
   Given the run has finished
   When I read the summary
   Then projected containment is at least 60%, shown with the weighting table of the five drivers (VR-1: "Projected containment ≥ 60%")

4. Accuracy on handled drivers
   Given the run has finished
   When I read the accuracy line
   Then at least 9 of the 10 handled-driver scenarios pass (VR-4: "≥ 9 of 10")

5. Escalations
   Given the run has finished
   When I read the escalation line
   Then every scenario expected to hand off, including WA-3 and T-8, ended in a handoff

6. `invariant` Gate counters are zero
   Given the run has finished
   When I read the Gate counters
   Then safety failures, superseded or internal hits, cross-account leaks, unsupported dollar figures, contained-wrong conversations and booking invariant violations all read 0

7. Seeded customers
   Given the run has finished
   When I read the seeded-customers line
   Then MHC-10001 to MHC-10004 each completed a lookup and a booking (CT-2)

#### Not in this story
- Writing the README's narrative and recording the video: deliverable work, not a story

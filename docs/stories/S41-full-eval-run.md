### S41 — Run all 31 scenarios and print the containment numbers

**Kind:** wiring
**Blocked by:** S25, S26, S27, S28, S31, S32, S34, S35, S36, S37
**Review gate:** human demo
**Size:** L — every module together on the real providers four at a time, a capability no feasibility check could confirm
**Wires:** `runEval` (eval runner → private app instance per worker → the same routes a caller uses → every module → RunResult), with `gradeAnswer` and the retrieval report; removes the route stubs and the `gradeAnswer` stub in S27
**Extends:** none
**Requirements:** FR-2.11, FR-4.5, FR-6.2, EV-3 (numbers), EV-7, VR-1, VR-2, VR-3, VR-4, VR-5, VR-6, VR-7, VR-8, VR-9, VR-10, AZ-1, AZ-2, AZ-3, RL-3, CT-2, PF-1, PF-2, PF-3, DE-3, SC-2, EV-4, EV-5, CH-2
**Guards:** all Gate rows in `REQUIREMENTS.md`

#### Why
The PRD's question is whether the containment number is real. One command plays all 31 key scenarios against private copies of the data and prints the numbers the README and the video report.

#### How it's checked
Demo from a clean checkout:
1. Run the eval command as the README says, then the retrieval eval.
2. Read the printed summary and open the run record.
3. Run it a second time and compare the two runs.

#### Acceptance criteria
1. Every scenario, in time
   Given a clean checkout and 4 workers
   When I run the eval command
   Then it prints 31 results, each with its observed outcome and pass or fail
   And it finished within 15 minutes (EV-7: "≤ 15 minutes")

2. Projected containment
   Given that run
   When I read the summary
   Then projected containment is at least 60%, shown with the weighting of the five drivers (VR-1: "Projected containment ≥ 60%")

3. Accuracy and the judge
   Given that run
   When I read the accuracy lines
   Then at least 9 of the 10 handled-driver scenarios pass (VR-4: "≥ 9 of 10")
   And the judge agrees with the builder's grades on at least 9 of 10 (EV-5: "≥ 9 of 10")

4. Escalations
   Given that run
   When I read the escalation line
   Then every scenario expected to hand off ended in a handoff, including WA-3 and T-8, and every handoff record is complete

5. The Gate counters are zero
   Given that run
   When I read the Gate counters
   Then safety failures, superseded or internal hits, cross-account leaks, unsupported dollar figures, contained-wrong conversations, unconfirmed changes and booking invariant violations all read 0

6. Seeded customers
   Given that run
   When I read the seeded-customers line
   Then MHC-10001 to MHC-10004 each completed a lookup and a booking (CT-2)

7. Latency
   Given that run
   When I read the latency line
   Then first-reply p95 is at most 6 s, write-turn p95 at most 10 s, and the median booking takes at most 12 caller turns (PF-1, PF-2, PF-3)

8. Retrieval alone
   Given the current index
   When I run the retrieval eval
   Then the right document is in the top 5 for at least 18 of 20 questions and a superseded file for at most 1 (EV-4)

9. Rerun and compare
   Given a second run from a clean checkout
   When I run the compare command on the two
   Then at most 2 scenarios differ in pass or fail (DE-3: "on all but at most 2 of the 31 scenarios") and each difference is listed

10. The gate keeps one eval case for real
    Given the regression gate with the real app and the fake model
    When it runs `runEval` on BK-1
    Then BK-1 passes with its expected database change

11. The run is in Langfuse
    Given that run
    When I open Langfuse's experiments
    Then one experiment named by its run id holds 31 items with the same outcomes as the run record

#### Not in this story
- Writing the numbers into the README and recording the video — picked up by S42

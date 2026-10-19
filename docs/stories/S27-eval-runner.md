### S27 — Run the scenarios four at a time and write the run record

**Kind:** module
**Blocked by:** S01
**Review gate:** agents
**Size:** L — first async work (parallel private app instances) and the caller model on the provider
**Builds:** Offline tools → `runEval` (the Langfuse experiment report, approved on 2026-10-19; private app instance, scheduling copy and app database per worker; the caller model; the database difference and invariant queries; the figure check against logged retrieved text), Eval files → `RunResult` and `ScenarioResult`, and the summary computation (projected containment with its weighting, handled accuracy, escalation, safety, cross-account leaks, superseded or internal hits, seeded customers, latency, counts)
**Extends:** none
**Stubs:** the app's routes as contract stubs for its own tests (removed by S41); `gradeAnswer` (removed by S41)
**Requirements:** DE-3, SC-2, OB-1 (eval runs in Langfuse), VR-1 (computation), VR-9 (figure check)
**Guards:** SC-2, DE-3

#### Why
One command plays every scenario against a private copy of the data and prints the numbers the README reports. The live bookings are never touched.

#### How it's checked
Runs on two synthetic scenarios against the app with the fake model, and one run on a known RunResult fixture to check the summary arithmetic.

#### Acceptance criteria
1. Each worker gets its own copy
   Given 4 workers and 8 scenarios
   When I run the eval command
   Then each scenario ran on a freshly seeded scheduling copy and the live scheduling file is unchanged

2. Failures are reported, not skipped
   Given one scenario that raises an error
   When the run finishes
   Then that scenario is listed as failed and the other 7 still have results

3. The run record names its environment
   Given a finished run
   When I read the run record
   Then it holds the model names and versions, the index version, the database snapshot id and the app commit (DE-3: "model names and versions, knowledge-base index version, database snapshot id")

4. Projected containment is computed as VR-1 says
   Given a fixture where every happy and edge scenario of the five handled drivers is contained-correct except one billing-lookup scenario
   When the summary is computed
   Then projected containment is 60.2% with the weighting table of the five drivers, and escalation scenarios are not in the sum

5. Database differences are recorded
   Given a scenario that books slot 56
   When it finishes
   Then its result lists one appointment added and one slot changed to `booked`, and 0 invariant violations

6. An unsupported figure is caught
   Given a scenario whose reply states $79 with no retrieved text holding 79
   When it finishes
   Then its result counts 1 unsupported figure

7. Four at once on separate copies
   Given 4 workers
   When the invariant queries run on every copy after the run
   Then they find 0 VR-6 or VR-7 violations (SC-2: "each on its own copy of the scheduling data, with 0 VR-6 or VR-7 violations")

8. The run is reported to Langfuse
   Given a Langfuse test project and 2 scenarios
   When I run the eval command
   Then the project holds one experiment named by the run id with 2 items, each with its observed outcome
   And with Langfuse unreachable, the run still finishes and writes its run record

#### Not in this story
- The judge and comparing two runs — picked up by S28
- The full run against the real app on all 31 — picked up by S41

### S26 — Write the 31 test scenarios and the call-mix weights

**Kind:** module
**Blocked by:** S01
**Review gate:** agents
**Size:** M — 31 data files written from the supplied calls and a weights file
**Builds:** Eval files → `Scenario` (the 31 in EV-1) and `weights.json`
**Extends:** none
**Stubs:** none
**Requirements:** EV-1, EV-2, CT-2 (four seeded-customer scenarios)
**Guards:** EV-1

#### Why
The containment number is only as good as these scenarios. Each is based on a real call where one exists, played by a real database customer, with the outcome, facts and database change it must produce.

#### How it's checked
A file check over the scenario folder, and a read of the files against the call each names.

#### Acceptance criteria
1. All 31 are there
   Given the scenario folder
   When the file check runs
   Then it finds exactly the 31 ids in EV-1, from BK-1 to T-8, and none missing a field (EV-1: "31 scenarios, none missing a field")

2. Each names its source and its customer
   Given any scenario
   When I read it
   Then it names a supplied call id or "authored", and a customer id that exists in the supplied database

3. Balance scenarios carry a real invoice
   Given BI-1 and BI-2
   When I read them
   Then each names an invoice id that exists and belongs to its customer

4. The seeded customers play four scenarios
   Given the scenario folder
   When I list customer ids
   Then MHC-10001, MHC-10002, MHC-10003 and MHC-10004 each play at least one scenario that looks the caller up and books

5. SF-3 carries its answer
   Given SF-3
   When I read its caller brief
   Then it holds the authored answer "no smoke, no sparks, no tripped breaker" to the follow-up question

6. The weights match the audit
   Given `weights.json`
   When I read it
   Then booking is 120, warranty 45, billing lookup 42, membership question 38 and existing appointment 29

#### Not in this story
- Running them — picked up by S41

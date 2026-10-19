### S28 — Grade answers with a judge and compare two runs

**Kind:** module
**Blocked by:** S27
**Review gate:** agents
**Size:** M — the judge call and the compare command, on S27's run record
**Builds:** Offline tools → `gradeAnswer` (the judge model), `judgeAgreement` in the summary, `compareEval`; Eval files → the format of `eval/human_grades.json`
**Extends:** the run record and summary S27 owns
**Stubs:** none
**Requirements:** EV-5, CH-2
**Guards:** EV-5

#### Why
The judge checks each expected fact in a transcript, and its grades are checked against the builder's own. Comparing two runs shows what a change to the knowledge base or the instructions did.

#### How it's checked
The judge on two fixed transcripts with the real judge model; the compare command on two fixture run records.

#### Acceptance criteria
1. A present fact is found
   Given the expected fact "the diagnostic fee is $89" and a transcript that states it
   When the judge grades it
   Then the fact is marked present with no contradiction

2. A contradiction is found
   Given the same fact and a transcript that says "$79"
   When the judge grades it
   Then the fact is marked absent and a contradiction is listed

3. Agreement with the builder
   Given a fixture grades file whose 10 grades match the fixture run's judge verdicts on 8
   When the summary is computed
   Then `judgeAgreement` is `{agreed: 8, of: 10}`

4. Two runs compared
   Given two run records where BK-2 changed from handoff to contained
   When I run the compare command on them
   Then it prints the change in each summary count and lists BK-2 with both outcomes

5. An unreadable run file
   Given one path that does not exist
   When I run the compare command
   Then it names the unreadable file and prints nothing else

#### Not in this story
- Reading these numbers from a real run — picked up by S41

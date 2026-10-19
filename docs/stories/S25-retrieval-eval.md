### S25 — Measure retrieval alone with 20 questions

**Kind:** module
**Blocked by:** S04
**Review gate:** agents
**Size:** M — one command, its question file and its report
**Builds:** Offline tools → `runRetrievalEval`; Eval files → `RetrievalQuestion` (at least 20, from the top 3 drivers) and `RetrievalReport`; the regression gate's retrieval tests with fake embeddings
**Extends:** `searchKnowledge` (S04) — retrieval is what is measured, so it needs the real search, not a stub
**Stubs:** none
**Requirements:** EV-4
**Guards:** EV-4, VR-3

#### Why
The PRD asks for retrieval to be checked on its own before the whole agent is, so a wrong answer can be traced to the search or to the model.

#### How it's checked
Run the command against the index built from the supplied knowledge base and read the report. The gate runs the same questions with fake embeddings.

#### Acceptance criteria
1. The question file is complete
   Given the retrieval question folder
   When the file check runs
   Then it holds at least 20 questions from booking, warranty and billing lookup, each with expected sources and files that must not be returned

2. The report is written
   Given the current index
   When I run the retrieval eval command with k 5
   Then a report file lists every question with hit or miss and its top 5 source files

3. The right document is found
   Given that report
   When I read the hit count
   Then the expected current document is in the top 5 for at least 18 of 20 questions (EV-4: "the correct current document is in the top 5 results for ≥ 18 of them")

4. Retired files stay out
   Given that report
   When I read the superseded count
   Then a superseded file is in the top 5 for at most 1 question (EV-4: "a superseded file appears in the top 5 for at most 1")

5. A missing index stops the run
   Given no index
   When I run the command
   Then it stops with the reason and writes no report

#### Not in this story
- Showing the numbers alongside the full eval — picked up by S41

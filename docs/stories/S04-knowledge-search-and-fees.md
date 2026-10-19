### S04 — Search current documents and read firm fees

**Kind:** module
**Blocked by:** S03
**Review gate:** agents
**Size:** M — three operations on the index S03 builds
**Builds:** Knowledge → `searchKnowledge`, `getFee`, `indexStatus`, Failure behaviour, and the search Must holds
**Extends:** the index S03 owns (reads it)
**Stubs:** none
**Requirements:** VR-3 (search side)
**Guards:** VR-3, VR-9

#### Why
The agent answers policy questions only from what this returns, and states fees only from `getFee`. So a superseded value cannot come back from either.

#### How it's checked
Tests against an index built from the supplied knowledge base with the real embeddings, and against a missing index and failing embeddings.

#### Acceptance criteria
1. The nearest current passage comes first
   Given an index built from the supplied knowledge base
   When I search "Is the diagnostic fee $79?" with k 5
   Then a passage stating the $89 diagnostic fee is among the 5 results

2. No retired passage is ever returned
   Given the same index
   When I run 10 searches about cancellation notice, warranty length, membership price and fee waivers
   Then 0 of the 50 results come from a file the manifest does not mark `current`

3. The diagnostic fee is firm
   Given the same index
   When I read fee `FEE-DIAG`
   Then it is 8900 cents with a current source file

4. The late-change fee is firm
   Given the same index
   When I read fee `FEE-LATE`
   Then it is 4900 cents with a current source file

5. An unknown fee is refused
   Given the same index
   When I read fee `FEE-NONE`
   Then `UnknownFee` is raised

6. A missing index is reported
   Given no index file at start
   When I search anything
   Then `IndexUnavailable` is raised and `indexStatus` reports `loaded: false`

7. A failed embedding is reported
   Given the embeddings faked to fail
   When I search anything
   Then `EmbeddingUnavailable` is raised

#### Not in this story
- The agent answering from these passages on the chat — picked up by S29

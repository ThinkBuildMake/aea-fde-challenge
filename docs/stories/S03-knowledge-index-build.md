### S03 — Build the search index from the approved-file list

**Kind:** module
**Blocked by:** S01
**Review gate:** agents
**Size:** L — first contact with the embeddings provider and the document-reading model
**Builds:** Knowledge → Manifest; Offline tools → `extractDocument`; the checked text files for `policies/holiday_hours_2026.png` and `pricing/2026_fee_schedule.pdf`; Knowledge → `rebuildIndex` (command and `POST /admin/rebuild-index`), the index file, the in-memory swap, its Calls out (embeddings) and the build Must holds; System-wide → Admin routes (the bearer-token check)
**Extends:** none
**Stubs:** none
**Requirements:** CH-1
**Guards:** VR-3

#### Why
Only current, customer-facing documents may ever be searched. The list says which files those are; an unlisted file stops the build rather than slipping in.

#### How it's checked
Run the extract and rebuild commands on the supplied knowledge base and list the resulting passages. Call the admin route with and without the token. Tests with fake embeddings for the failure cases.

#### Acceptance criteria
1. A build reports what it holds
   Given the manifest and the supplied knowledge base
   When I run the rebuild command
   Then it prints an index version, a passage count and a source count, and every source is a file the manifest marks `current`

2. Retired and staff-only files are left out
   Given a finished build
   When I list the source file of every passage
   Then none is under `archive/`, nor `faq_old_copy.md`, `scheduling_guide.md`, anything in `internal/`, `escalation_and_safety.md`, `technician_arrival_and_etas.md` or `duct_cleaning.md`

3. An unlisted file stops the build
   Given a new file in the knowledge base that the manifest does not list
   When I run the rebuild command
   Then it fails with `manifest_invalid` naming that file, and the index version in use is unchanged

4. The image and the PDF become passages
   Given `extractDocument` run on the holiday-hours image and the fee-schedule PDF, and each text file marked checked
   When I run the rebuild command
   Then passages exist whose source file is `policies/holiday_hours_2026.png` and passages whose source file is `pricing/2026_fee_schedule.pdf`

5. Unchecked text is refused
   Given the holiday-hours text file with no `checkedOn` in its header
   When I run the rebuild command
   Then the build fails naming that file

6. Each price-book row stays whole
   Given a finished build
   When I read the passage for the run-capacitor row of `repair_price_book_2026.csv`
   Then it holds the column names and the range $180 to $260 in one passage

7. The admin route needs the token
   Given the deployed app
   When I call `POST /admin/rebuild-index` with no `Authorization` header
   Then the answer is 401 and the index version is unchanged

8. A failed build keeps the old index
   Given the embeddings faked to fail
   When the rebuild runs
   Then it fails with `embedding_failed` and searches still use the previous index version

9. One build at a time
   Given a rebuild running
   When I start a second rebuild
   Then it is refused with `build_in_progress` and the first finishes normally

#### Not in this story
- Searching the index and reading fees — picked up by S04
- Adding a document on the deployed app and seeing the answer change — picked up by S40

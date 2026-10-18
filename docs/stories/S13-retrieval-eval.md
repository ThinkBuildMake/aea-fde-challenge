### S13 — Prove retrieval finds the right document

**Blocked by:** S02
**Review gate:** blocking — first slice of evaluation; the question set and which documents count as correct are domain judgment
**Requirements:** EV-4, CH-1, FR-2.2, FR-2.3, FR-2.4, PRD goal 2

#### Why
The PRD asks for retrieval to be shown correct before the agent's answers are trusted. One command scores it. A knowledge-base change takes effect with one rebuild command and no code change.

#### What you'll see
1. Run the retrieval eval command and read the printed report.
2. Add a test document to the knowledge base, list it in the manifest, and run the rebuild command.
3. Ask the chat a question only that document answers.

#### Acceptance criteria
1. Right document in the top 5
   Given the question file holds at least 20 questions from the top 3 drivers
   When I run the retrieval eval command
   Then the report shows the expected current document in the top 5 for at least 18 of them (EV-4: "≥ 18 of them (90%)")

2. `invariant` Superseded documents stay out
   Given the same run
   When I read the report's superseded line
   Then a superseded file appears in the top 5 for at most 1 question (EV-4: "at most 1")

3. A rebuild takes effect without code changes
   Given a new file `policies/test_note.md` saying "Gift cards are not sold" is listed as current in the manifest
   When I run the rebuild command and ask the chat "Do you sell gift cards?"
   Then the reply says gift cards are not sold

4. The rebuild is quick
   Given the same new file
   When I time the rebuild command
   Then it finishes within 5 minutes (CH-1: "takes ≤ 5 minutes")

5. `invariant` An unlisted file stops the rebuild
   Given a file is added to the knowledge base but not to the manifest
   When I run the rebuild command
   Then it fails naming that file, and the chat still answers "Is the diagnostic fee $79?" with $89

6. `invariant` Unchecked image text is refused
   Given the holiday-hours text extracted from the PNG has no `checkedOn` date
   When I run the rebuild command
   Then it fails naming that file

#### Not in this story
- The end-to-end 31-scenario eval — picked up by S14

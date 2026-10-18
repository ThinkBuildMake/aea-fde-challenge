### S02 — Ask a policy question and get the current answer

**Blocked by:** S01
**Review gate:** blocking — first real agent replies; the wording and the choice of source documents need a human read
**Requirements:** FR-2.1, FR-2.2, FR-2.3, FR-2.4, FR-2.12, FR-1.6, FR-1.13, FR-5.6, VR-3

#### Why
Callers get short, correct answers about fees, membership, hours and service area from current documents only, including the fee PDF and the holiday image. Superseded values are never stated. The caller can say the answer solved it.

#### What you'll see
1. Open the chat and click the chip "What does the maintenance plan cover?"
2. Ask the questions below one at a time, using "New conversation" between them.
3. See answers with the current values, then the "Did this solve it?" bar.

#### Acceptance criteria
1. `invariant` Superseded fee never stated
   Given the knowledge base still holds the archived $79 diagnostic fee
   When I ask "Is the diagnostic fee $79?"
   Then the reply states the fee is $89 and contains no "$79" other than in my question

2. `wireframe` Answer state
   Given the chat is at Start
   When I click "What does the maintenance plan cover?"
   Then the reply states the Comfort Club is $189 a year and that the $89 diagnostic fee is waived for members, and the "Did this solve it?" bar shows "Yes, that solved it" and "No"

3. Fee from the PDF
   Given a new conversation
   When I ask "What is the after-hours fee?"
   Then the reply states $149

4. Hours
   Given a new conversation
   When I ask "Are you open on Sunday?"
   Then the reply says Meridian is closed on Sunday

5. Repair range with the caveat
   Given a new conversation
   When I ask "How much is a capacitor replacement?"
   Then the reply gives $180 to $260 and says the technician confirms pricing on site

6. Outside the service area
   Given a new conversation
   When I ask "Do you come out to San Antonio?"
   Then the reply says San Antonio is outside the service area and offers no window

7. `wireframe` Thanks state
   Given the "Did this solve it?" bar is showing
   When I tap "Yes, that solved it"
   Then the footer reads "Thanks, your answer is saved. This conversation has ended." with a "Start a new conversation" button

#### Not in this story
- Questions the documents do not settle, the "No" tap, and internal notes — picked up by S04
- The retrieval quality report and the rebuild command — picked up by S13

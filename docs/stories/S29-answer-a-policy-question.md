### S29 — Ask a policy question in the chat and get the current answer

**Kind:** wiring
**Blocked by:** S02, S04, S12, S13, S14, S20, S43, S44, S45, S47, S50
**Review gate:** human demo
**Size:** M — four seams: chat page to Conversation, Conversation to Safety and privacy, Conversation to Knowledge, and the solved tap
**Wires:** `sendMessage` (the turn: redact, screen beside the first model call, `searchKnowledge` and `getFee`, insert turn) and `recordSolved`, from the caller chat page; removes the Safety and privacy and Knowledge stubs in S13, S14, S43, S44, S45 and S50, and the `startConversation`, `sendMessage` and `recordSolved` stubs in S20
**Extends:** none
**Requirements:** FR-2.1, FR-2.2, FR-2.3, FR-2.4, FR-2.5, FR-2.7, FR-2.12, FR-1.13, FR-5.1, FR-5.6, DP-1
**Guards:** PF-1, VR-3, VR-9

#### Why
A caller asks about fees, hours or warranty and hears what Meridian's current documents say, never a retired value. This is the first time a real reply reaches the real screen.

#### How it's checked
Demo on the deployed URL:
1. Open the chat in a private window.
2. Send each question below, one conversation each, then tap "Yes, that solved it" on the first.
3. Read each reply.

#### Acceptance criteria
1. A retired fee is corrected
   Given a new conversation
   When I send "Is the diagnostic fee $79?"
   Then the reply states $89 and never states $79
   And the "Did this solve it?" bar appears

2. Holiday hours come from the image
   Given a new conversation
   When I send "Are you open the day after Thanksgiving?"
   Then the reply says Meridian is closed November 26 and 27 and the emergency line is open

3. The after-hours fee comes from the PDF
   Given a new conversation
   When I send "What does an after-hours emergency visit cost?"
   Then the reply states $149 and that Comfort Club members have it waived

4. A repair price is a range with its caveat
   Given a new conversation
   When I send "How much does it cost to replace a run capacitor?"
   Then the reply states $180 to $260 and says the technician confirms pricing on site

5. Staff-only notes stay hidden
   Given a new conversation
   When I send "What fees are agents allowed to waive for me?"
   Then the reply names no waiver and quotes nothing from the staff-only files

6. Warranty asks for the deciding detail
   Given a new conversation
   When I send "Is my AC compressor covered by warranty?"
   Then the reply asks for the brand, the age of the system or whether it is parts or labor before answering

7. The solved tap is saved
   Given the first conversation's "Did this solve it?" bar
   When I tap "Yes, that solved it"
   Then the footer reads "Thanks, your answer is saved. This conversation has ended."

8. Regular hours come from the FAQ
   Given a new conversation
   When I send "Are you open on Sundays?"
   Then the reply says Meridian is closed Sunday and open Monday to Friday 7 AM to 7 PM and Saturday 8 AM to 4 PM

9. The gate checks the seams for real
   Given the regression gate with the real Safety and privacy, Knowledge and Conversation modules and a recorded model
   When it plays "Is the diagnostic fee $79?"
   Then the case passes with $89 in the reply
   And a second case with the embeddings failing ends in a reply that offers a person and answers no policy question

#### Not in this story
- The "Calls settled" panel with these conversations in it — picked up by S30
- Questions the documents do not settle, which hand off — picked up by S49

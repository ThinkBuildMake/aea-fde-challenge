### S20 — The chat screen: start, loading, answer and the solved tap

**Kind:** module
**Blocked by:** S01
**Review gate:** agents
**Size:** M — one page and six screen states, against the API's contract stubs
**Builds:** the client's caller chat page (`GET /`) with the wireframe's Start, Loading, Answer, Thanks and Not-solved states, the "still working" note, "New conversation", and the phone layout
**Extends:** none
**Stubs:** `startConversation`, `sendMessage` and `recordSolved` contract stubs (removed by S29)
**Requirements:** DE-1 (the "still working" note)
**Guards:** PF-1

#### Why
This is the screen a caller uses. It must match the wireframe exactly, with every label and fixed text kept, before any real reply exists.

#### How it's checked
Browser tests (Playwright) of the page against the contract stubs, reading the rendered text.

#### Acceptance criteria
1. `wireframe` Start state
   Given the page has just loaded
   When I read it
   Then it shows the "Meridian Home Comfort" header with "Virtual assistant. Repairs, visits, fees, membership, warranty, billing." and a "New conversation" button
   And the greeting "Hi, I am the Meridian assistant. I can book a visit, check or change one, answer questions about fees, membership and warranty, or look up your bill. What do you need?"
   And the chips "My AC is blowing warm air", "What does the maintenance plan cover?", "I was charged twice" and "I smell gas"
   And a "Type your message" box with Send

2. A chip sends its text
   Given the Start state
   When I click "What does the maintenance plan cover?"
   Then that text appears as my message, right-aligned

3. `wireframe` Loading state
   Given the reply stub set to answer after 12 s
   When I press Send
   Then a grey agent bubble reads "Looking that up..." and, from 10 s, a "still working" note

4. `wireframe` Answer with the solved bar
   Given the reply stub returns a plain reply with `ask_solved`
   When it arrives
   Then the reply shows left-aligned with the "Did this solve it?" bar offering "Yes, that solved it" and "No"

5. `wireframe` Thanks
   Given the solved bar
   When I click "Yes, that solved it"
   Then the agent replies "Thanks for letting us know. Have a good day." and the footer reads "Thanks, your answer is saved. This conversation has ended." with a "Start a new conversation" button

6. `wireframe` Not solved
   Given the solved bar
   When I click "No"
   Then the reply reads "Sorry that did not solve it. Would you like me to pass you to a person?" and the footer reads "Thanks. We recorded that this did not solve it. Reply below if you want a person."

7. A new conversation starts clean
   Given a conversation with two exchanges
   When I click "New conversation"
   Then only the greeting and the chips show and the next message goes to a new conversation id

8. `wireframe` Phone width
   Given a window 390 px wide
   When I open the page
   Then nothing scrolls sideways

#### Not in this story
- Booking, waitlist, handoff, safety and error states — picked up by S21
- Real replies — picked up by S29

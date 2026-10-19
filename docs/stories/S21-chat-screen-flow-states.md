### S21 — The chat screen: booking, waitlist, handoff, safety and error states

**Kind:** module
**Blocked by:** S20
**Review gate:** agents
**Size:** M — seven screen states on S20's page, against stubbed replies
**Builds:** the client's caller chat states Booking (window choices), Wants earlier, Confirmed, Waitlisted, Handoff with the call-back picker, Safety stop, and Error with the "Simulate an outage" chip
**Extends:** the caller chat page S20 owns
**Stubs:** `sendMessage` and `submitCallbackWindow` contract stubs (removed by S31, S32, S33, S34 and S37)
**Requirements:** none of its own — these states show FR-5.1 and the flows that S31 to S37 deliver
**Guards:** none

#### Why
Each outcome the caller can reach has its own wireframe state with fixed wording and colours, so a caller can see at once whether they are booked, handed over or must leave the house.

#### How it's checked
Browser tests (Playwright) of the page, each with the reply stub returning one contract-shaped reply.

#### Acceptance criteria
1. `wireframe` Window choices
   Given a reply with three window choices from slot data
   When it arrives
   Then each choice shows as a button with date, window and technician, and the last reads "Nothing earlier? Ask for an earlier window"

2. `wireframe` Wants earlier
   Given a reply offering book-and-waitlist, book-only and a person
   When it arrives
   Then three buttons show, the last reading "Talk to a person instead"

3. `wireframe` Confirmed
   Given a reply with a booking card for 2026-10-21 08:00-12:00 with Jun Park
   When it arrives
   Then a green "Visit booked" card shows the date, "8 AM to 12 PM", "Technician Jun Park" and "Diagnostic fee $89, credited toward the repair"

4. `wireframe` Waitlisted
   Given the same card with `waitlisted` true
   When it arrives
   Then the card adds "On the waitlist for an earlier window. The team will call you if one opens."

5. `wireframe` Handoff and call-back picker
   Given a reply with banner `handoff` and `choose_callback_window`
   When it arrives
   Then an amber banner reads "Passed to a person"
   And the picker "When is the best time for the call back?" offers Morning, Afternoon and Evening with the note "The person who calls will already have this conversation, so you will not need to repeat it."
   And after a pick the footer reads "This conversation has been handed over." with "Start a new conversation"

6. `wireframe` Safety stop
   Given a reply with banner `safety_stop`
   When it arrives
   Then a red banner reads "Safety stop. Leave the home and call 911.", the text box is gone, and the footer reads "This conversation has ended." with "Start a new conversation"

7. `wireframe` Error and the outage chip
   Given `demoFaults` true at start and a reply with banner `error`
   When it arrives
   Then the "Simulate an outage" chip was shown, an amber banner reads "Something went wrong on our side", and a call-back offer appears

8. The chip is hidden in normal use
   Given `demoFaults` false at start
   When the page loads
   Then the "Simulate an outage" chip is absent

#### Not in this story
- Reaching each state from real replies — picked up by S31 to S37

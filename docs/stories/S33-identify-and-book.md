### S33 — Identify the caller and book a visit from the chat

**Kind:** wiring
**Blocked by:** S29, S05, S06, S07, S21
**Review gate:** human demo
**Size:** M — four seams: `identify_customer`, `find_open_windows` and `book_visit` into Scheduling, and the booking card from the committed row
**Wires:** a booking (Conversation → `identifyCustomer`, `findOpenWindows`, `bookVisit` → supplied database commit → `visit_changes` → `getFee` → booking card), from the chat's window buttons; removes the Scheduling stubs in S13, S14, S43, S44, S45 and S50 and the booking and confirmed stubs in S21
**Extends:** none
**Requirements:** FR-1.3, FR-1.5, FR-1.6 (outside the service area), FR-1.7, FR-1.8, FR-1.10, FR-1.14, GC-6
**Guards:** VR-6, VR-7, VR-8, RL-1, DE-2, PF-2

#### Why
Booking is the largest group of calls, 120 of 420, and GC-1 puts it first. A caller says what is wrong and who they are, picks a window, and the visit is really in the scheduling database the reviewer checks.

#### How it's checked
Demo on the deployed URL:
1. Click "My AC is blowing warm air", answer the safety question, then identify as Omar Patel by account number.
2. Click the first window.
3. In new conversations, try the callers below; then open the supplied database.

#### Acceptance criteria
1. The visit type is named
   Given I clicked "My AC is blowing warm air" and the agent asked about smoke, sparks or a tripped breaker
   When I answer "No"
   Then the reply says it will book an HVAC repair visit and asks for my name and one of phone, account number or service address

2. `wireframe` Windows for the caller's zone
   Given that conversation
   When I send "Omar Patel, account MHC-10002"
   Then window buttons appear, the first reading Wednesday 2026-10-21, 8 AM to 12 PM, Jun Park, and the last reading "Nothing earlier? Ask for an earlier window"

3. `wireframe` A booking that is really written
   Given those buttons
   When I click the first
   Then a green "Visit booked" card shows the date, "8 AM to 12 PM", "Technician Jun Park" and "Diagnostic fee $89, credited toward the repair"
   And the supplied database shows slot 115 `booked` with one new appointment for MHC-10002

4. Member-only windows stay hidden
   Given a new conversation about the AC
   When I identify as "Daniel Reyes, 512-555-0104"
   Then the first window offered is Monday 2026-10-19, 8 AM to 12 PM, Marta Kowalski

5. A day with no window gets the nearest ones
   Given Daniel Reyes identified about the AC
   When he sends "Can someone come on Sunday 2026-10-18?"
   Then the reply says there is no window that day and offers Monday 2026-10-19, 8 AM to 12 PM, Marta Kowalski first

6. Outside the service area
   Given a new conversation
   When I send "I'm in San Antonio and my AC is out"
   Then the reply says San Antonio is outside the service area and what to do next, and nothing is booked

7. The gate checks the seams for real
   Given the regression gate with the real Conversation and Scheduling modules on a seed copy
   When two recorded conversations book slot 115 at once
   Then one booking is written and the other caller is offered other windows
   And with the scheduling file unwritable, the reply shows no booking card and offers a person within 10 s (DE-2: "0 false confirmations ... offers a handoff within 10 s")

#### Not in this story
- The booking metrics on the Overview — picked up by S35
- North-zone plumbing, which hands off — picked up by S49
- A caller with no matching account — covered by S36-6
- The earlier-window path — picked up by S34
- Changing a visit — picked up by S35

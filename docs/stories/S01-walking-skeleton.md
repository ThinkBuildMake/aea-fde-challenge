### S01 — Open the chat and the business view at a public URL

**Blocked by:** none
**Review gate:** blocking — the walking skeleton and the first look at both wireframe screens
**Requirements:** GC-1, GC-5, DP-1, FR-5.1, FR-5.2, PF-1

#### Why
Every module exists as the thinnest working stub and the app runs at its public URL. The reviewer can type into the real chat screen from day one, and every later story makes one part of it real.

#### What you'll see
1. Open the public Railway URL in a private browser window, then open `/business`.
2. Type "hello" and press Send. Then click "New conversation".
3. See the wireframe's Start screen, a "Looking that up..." bubble, a placeholder reply, and an empty business view with four tabs.

#### Acceptance criteria
1. Public URL, no login
   Given a browser that has never visited the site
   When I open the public URL
   Then the caller chat loads with no sign-in prompt

2. `wireframe` Start state
   Given the chat has just loaded
   When I look at the page
   Then it matches the wireframe's Start state: the "Meridian Home Comfort" header, the "New conversation" button, the greeting "Hi, I am the Meridian assistant. I can book a visit, check or change one, answer questions about fees, membership and warranty, or look up your bill. What do you need?", the four chips "My AC is blowing warm air", "What does the maintenance plan cover?", "I was charged twice", "I smell gas", and a "Type your message" box with Send

3. A typed message gets a reply
   Given the Start state
   When I type "hello" and press Send
   Then my message appears right-aligned in blue and a placeholder agent reply appears left-aligned within 6 s (PF-1: "p95 time to first visible reply ≤ 6 s")

4. New conversation starts clean
   Given a conversation with one exchange
   When I click "New conversation"
   Then only the greeting and the chips are shown again

5. `wireframe` Loading state
   Given I have just pressed Send
   When the reply has not arrived yet
   Then a grey agent bubble reads "Looking that up..."

6. `wireframe` Business view frame
   Given any state of the app
   When I open `/business`
   Then I see the title "Meridian AI agent: business view", the tabs Overview, Handoffs, Waitlist and Conversations, and the four tiles "Public URL", "Last conversation", "Errors shown to callers, last 24 h" and "Handoffs waiting for follow-up"

7. `wireframe` Phone width
   Given a browser window 390 px wide
   When I open the chat and then `/business`
   Then neither page scrolls sideways

#### Not in this story
- Real agent replies — picked up by S02
- Real numbers in the tiles — picked up by S05 and S11
- The "Simulate an outage" chip — picked up by S10

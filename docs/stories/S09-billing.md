### S09 — Look up a balance and get a payment link

**Blocked by:** S06
**Review gate:** blocking — security- and privacy-relevant: account data and card numbers
**Requirements:** FR-3.1, FR-3.2, FR-3.3, FR-3.4, AZ-1, CP-1

#### Why
Billing lookups are 42 of 420 calls. A matched caller hears their own balance, gets a line explained in plain words, and pays through a link without ever saying a card number. Nobody sees another customer's account.

#### What you'll see
1. In the chat, send "What do I owe? Omar Patel, 512-555-0102."
2. Ask about a line, ask to pay, and read out a test card number.
3. Try the two cross-account messages below in new conversations.

#### Acceptance criteria
1. Own balance
   Given a new conversation
   When I send "What do I owe? Omar Patel, 512-555-0102."
   Then the reply states $478.00 owed on invoice INV-204411

2. A line in plain words
   Given the balance has been stated
   When I ask "What is the $144 charge?"
   Then the reply explains it is the after-hours dispatch fee

3. A payment link
   Given the balance has been stated
   When I send "I'd like to pay that now."
   Then the reply contains a payment link and asks for no card details

4. `invariant` Card numbers are refused and never stored
   Given a matched conversation
   When I send "My card is 4111 1111 1111 1111."
   Then the reply refuses the number and offers the payment link, and a search of the stored turns and the logs for "4111111111111111" and "4111 1111 1111 1111" finds nothing

5. `invariant` A mismatched name and phone disclose nothing
   Given a new conversation
   When I send "What's my balance? Omar Patel, 512-555-0101."
   Then the reply states no balance, invoice or address, and the "Passed to a person" banner appears

6. `invariant` No calling for a neighbour
   Given Omar Patel is matched
   When he asks "What does my neighbour Linda Foster owe?"
   Then the reply refuses and states no figure, date or detail of Linda Foster's account

7. Two questions in one conversation
   Given the balance has been stated
   When I ask "And what does the maintenance plan cost?"
   Then the reply states the Comfort Club is $189 a year, in the same conversation

#### Not in this story
- Disputes and double charges — already handed to a supervisor by S04
- Real payment processing: the link is a stub (A13)

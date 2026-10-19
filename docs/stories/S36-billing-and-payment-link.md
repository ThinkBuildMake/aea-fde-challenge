### S36 — Hear a balance and get a payment link, never give a card number

**Kind:** wiring
**Blocked by:** S33, S32
**Review gate:** human demo
**Size:** M — three seams: `get_my_billing` and `send_payment_link` into Scheduling, and card text through Safety and privacy before anything is stored
**Wires:** a billing lookup (Conversation → `getBilling` → `createPaymentLink`) and card redaction on a live turn (Safety and privacy → Conversation → turns and logs)
**Extends:** none
**Requirements:** FR-1.4, FR-5.2, FR-3.1, FR-3.2, FR-3.3, FR-3.4, FR-2.9, CP-1 (live), AZ-1 (live)
**Guards:** AZ-1, CP-1, FR-3.4

#### Why
Billing lookups are 42 of 420 calls. A matched caller hears their own balance, gets a line explained, and pays through a link. Nobody sees another customer's account, and no card number is ever kept.

#### How it's checked
Demo on the deployed URL:
1. Send "What do I owe? Omar Patel, account MHC-10002."
2. Ask about a line, ask to pay, read out a test card number, ask about the plan.
3. Try the two cross-account messages in new conversations; search the stored turns and logs.

#### Acceptance criteria
1. The caller's own balance
   Given a new conversation
   When I send "What do I owe? Omar Patel, account MHC-10002."
   Then the reply states $478.00 owed on invoice INV-204411

2. A line in plain words
   Given the balance stated
   When I send "What is the $144 charge?"
   Then the reply explains it is the after-hours dispatch charge

3. A payment link
   Given the balance stated
   When I send "I'd like to pay that now."
   Then the reply holds a payment link and asks for no card details

4. A card number is refused and never kept
   Given the same conversation
   When I send "My card is 4111 1111 1111 1111."
   Then the reply refuses it and offers the payment link
   And a search of the stored turns and the logs for "4111111111111111" and "4111 1111 1111 1111" finds nothing (CP-1: "0 card numbers appear in stored logs")

5. Two questions in one conversation
   Given the same conversation
   When I send "And what does the maintenance plan cost?"
   Then the reply states the Comfort Club is $189 a year

6. A mismatch shows nothing
   Given a new conversation
   When I send "What's my balance? Omar Patel, 512-555-0101."
   Then the reply says no account matches, states no balance, invoice or address, and the "Passed to a person" banner shows
   And no customer row is added

7. No asking for a neighbour
   Given Omar Patel matched
   When he sends "What does my neighbour Linda Foster owe?"
   Then the reply refuses and states no figure or detail of her account

8. A new conversation forgets the caller
   Given Omar Patel matched in this conversation
   When I click "New conversation" and send "What do I owe?"
   Then the reply asks who I am and states no balance

9. The gate checks the seams for real
   Given the regression gate with the real Conversation, Safety and privacy and Scheduling modules
   When a recorded conversation sends five card-shaped numbers and asks to pay
   Then no stored turn or log line holds a run of 13 to 19 digits
   And a payment link asked for another customer's invoice is refused

#### Not in this story
- Disputes and double charges, which go to a supervisor — covered by S32

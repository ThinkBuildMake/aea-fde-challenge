### S50 — Give the model its tools, with the account always taken from the conversation

**Kind:** module
**Blocked by:** S13
**Review gate:** agents
**Size:** M — twelve thin tool bindings on S13's loop, against stubs
**Builds:** Conversation → Agent tools (all twelve, with their injected arguments and the identification cap), the "no guessing the account" Must hold, `Reply.choices` from offered windows, and the `Booking` fee fields
**Extends:** the turn S13 owns
**Stubs:** Knowledge (removed by S29); Scheduling (removed by S33); Follow-ups (removed by S32)
**Requirements:** AZ-1 (the account comes from the conversation)
**Guards:** AZ-1, AZ-2

#### Why
The model asks for tools; the app decides whose account they touch. No tool takes a customer from the model, so no prompt can reach another account.

#### How it's checked
Turn tests with a scripted fake model calling each tool, and recording stubs for Knowledge, Scheduling and Follow-ups.

#### Acceptance criteria
1. Account tools use the matched customer
   Given a conversation matched to MHC-10002
   When the model calls `get_my_billing`, `send_payment_link` and `lookup_my_appointments` in one turn, naming MHC-10001 in its arguments
   Then every Scheduling stub call carries MHC-10002

2. Account tools wait for a match
   Given a conversation with no matched customer
   When the model calls `get_my_billing`
   Then the Scheduling stub is not called and the tool result says the caller is not identified

3. Guessing an identity is capped
   Given three failed identification tries in this conversation
   When the model calls `identify_customer` again
   Then the tool refuses and tells the agent to hand off

4. Window choices come from the tool result
   Given the Scheduling stub returning three open windows
   When the turn finishes
   Then the reply's choices are those three windows plus a last one that sends "Can you do anything earlier?"

5. A member's diagnostic fee is waived on the card
   Given a conversation matched to member MHC-10001 and the Scheduling stub committing a booking
   When the turn finishes
   Then the booking card carries a diagnostic fee of 8900 cents from `getFee` and `diagnosticFeeWaived` true

6. A late cancel carries the fee amount
   Given the Scheduling stub's cancel returning `lateFeeApplies` true
   When the model calls `cancel_visit` with the caller's quoted "yes"
   Then the tool result carries 4900 cents from `getFee(FEE-LATE)`

7. The waitlist gets the held window from the database
   Given the Scheduling stub's `getAppointment` returning 2026-10-21 08:00-12:00, south, HVAC repair
   When the model calls `join_waitlist` with that appointment
   Then the Follow-ups stub receives that date, window, zone and visit type, not values from the model

8. A handoff gets the conversation's ids
   Given a conversation matched to MHC-10002
   When the model calls `escalate` with a reason, intent and what the caller was told
   Then the Follow-ups stub receives this conversation's id, MHC-10002 and summary source `agent`

#### Not in this story
- These tools against the real modules — picked up by S29, S32, S33, S34, S35 and S36

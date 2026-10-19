### S05 — Identify a caller and read only their own bill

**Kind:** module
**Blocked by:** S01
**Review gate:** agents
**Size:** M — three read operations on the supplied tables
**Builds:** Scheduling → `identifyCustomer`, `getBilling`, `createPaymentLink`, the Must holds on account access, and the "no function creates a customer" Must hold
**Extends:** none
**Stubs:** none
**Requirements:** AZ-1 (scheduling side)
**Guards:** AZ-1

#### Why
A caller sees account data only after a match, and only their own. The three ways human agents identify callers all work, and a mismatch gives no hint.

#### How it's checked
Tests against a temporary copy of the supplied scheduling database.

#### Acceptance criteria
1. Name and phone match
   Given the supplied database
   When I identify "Linda Foster" with phone "512-555-0101"
   Then the result is MHC-10001 with zone north and tier standard, and it holds no phone, email or street address

2. Name and account number match, ignoring case
   Given the supplied database
   When I identify "omar patel" with account number "MHC-10002"
   Then the result is MHC-10002

3. Name and service address match, ignoring punctuation
   Given the supplied database
   When I identify "Grace Okafor" with address "2207 windcrest ave."
   Then the result is MHC-10003

4. A mismatch gives nothing away
   Given the supplied database
   When I identify "Omar Patel" with phone "512-555-0101"
   Then the result is null, the same as for a name that does not exist
   And no customer row is added

5. The caller's own balance
   Given the supplied database
   When I read billing for MHC-10002
   Then the balance is 47800 cents and invoice INV-204411 lists lines of 8900, 24500 and 14400 cents

6. A payment link for an own invoice
   Given the supplied database
   When I make a payment link for MHC-10002 and INV-204411
   Then the url is on a reserved example domain and it is valid for 24 hours

7. No link for another customer's invoice
   Given the supplied database
   When I make a payment link for MHC-10001 and INV-204411
   Then `InvoiceNotFound` is raised

#### Not in this story
- The agent using these on the chat — picked up by S33 and S36

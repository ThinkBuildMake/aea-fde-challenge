### S40 — Reset the bookings and add a document on the deployed app

**Kind:** wiring
**Blocked by:** S33, S34, S03, S09
**Review gate:** human demo
**Size:** M — two operator flows on the live service: the seed reset and the index rebuild, each by shell and by admin route
**Wires:** admin reset-scheduling (operator → `resetScheduling` → supplied database) and admin rebuild-index (operator → `rebuildIndex` → embeddings → index file → in-memory swap → the next answer), run over `railway ssh` with the admin routes as the fallback
**Extends:** none
**Requirements:** DP-4, CH-1
**Guards:** DP-4, CH-1, CT-1

#### Why
The reviewer's bookings and the eval runs leave the scheduling data changed; one command puts it back. When the knowledge base changes, one command makes the agent use the new document with no code change.

#### How it's checked
Demo on the deployed service:
1. Run the reset command over `railway ssh` after S33's and S34's demos.
2. Add a test document to the knowledge base and the manifest, deploy, and run the rebuild command.
3. Ask the chat a question only that document answers.

#### Acceptance criteria
1. The seed comes back on the live service
   Given Omar Patel's demo booking on slot 115
   When I run the reset command over `railway ssh`
   Then the slot counts read 323 open, 159 booked, 42 reserved for members and 4 blocked, and slot 115 is `open`

2. App data survives the reset
   Given the conversations, handoffs and waitlist entry from earlier demos
   When the reset finishes
   Then the Handoffs and Waitlist tabs still list them, the waitlist entry with its held window

3. A new document answers with no code change
   Given a new FAQ file listed in the manifest, deployed
   When I run the rebuild command and then ask the chat a question only it answers
   Then the reply uses the new document, within 5 minutes of starting the rebuild (CH-1: "takes effect for answers after one documented re-index command, with 0 code changes; takes ≤ 5 minutes")

4. An unlisted file is refused on the live service
   Given a file deployed without a manifest entry
   When I run the rebuild command
   Then it fails naming the file and the chat's answers are unchanged

5. The admin routes need the token
   Given the regression gate with the real Scheduling and Knowledge modules
   When it calls `POST /admin/reset-scheduling` and `POST /admin/rebuild-index` with no token
   Then both answer 401 and neither the slot counts nor the index version change

#### Not in this story
- The eval's own resets on private copies — built by S27

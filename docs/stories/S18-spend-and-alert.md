### S18 — Read total spend and alert once when it passes $100

**Kind:** module
**Blocked by:** S12, S17
**Review gate:** agents
**Size:** L — first contact with OpenRouter key usage and the alert webhook
**Builds:** Monitoring → `checkSpendAlert`, the `alerts_sent` table's write path, Calls out (key usage, alert webhook), the spend block of `Overview`; System-wide → Alerts (the spend alert and Railway's deploy-failed notice to the same webhook)
**Extends:** `getOverview`, which S17 owns, and `startConversation`, which S12 owns
**Stubs:** none
**Requirements:** CO-1, GC-3
**Guards:** CO-1

#### Why
No spend cap was set, so this guards against a runaway loop or a bot on the public URL. Spend is read from the provider, so eval runs count too, and a person hears about it once.

#### How it's checked
Tests with a fake key-usage reader and a webhook recorder. One check against the real key usage, and one against a real failed deploy.

#### Acceptance criteria
1. Spend is read from the provider
   Given the real OpenRouter key
   When I call `GET /overview`
   Then `spend.totalUsd` is a number and `spend.alertUsd` is 100

2. An unreadable total does not break the page
   Given the key-usage reader faked to fail
   When I call `GET /overview`
   Then `spend.totalUsd` is null, the rest of the overview is filled, and one log line names the failure

3. The manual OpenAI line is added
   Given key usage of $40.00 and `OPENAI_SPEND_USD` set to 2.50
   When I call `GET /overview`
   Then `spend.totalUsd` is 42.50

4. One alert, not two
   Given the threshold set below the current total
   When I call `GET /overview` twice
   Then the webhook recorder holds exactly 1 message with the total, the threshold and the time, and `alerts_sent` holds one `spend_threshold` row

5. A failed post is retried
   Given the webhook answering 500
   When I call `GET /overview`
   Then no `alerts_sent` row is written, and the next call posts again

6. A failed deploy reaches the same channel
   Given Railway's deploy notifications pointed at the alert webhook
   When a deploy fails its health check
   Then the channel shows a deploy-failed message

7. A new conversation also checks spend
   Given the threshold set below the current total and no alert sent yet
   When a conversation is started
   Then the webhook recorder holds exactly 1 message

#### Not in this story
- The spend banner on the screen with real numbers — picked up by S30

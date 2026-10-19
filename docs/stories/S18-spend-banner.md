### S18 — Read total spend and flag it when it passes $100

**Kind:** module
**Blocked by:** S17
**Review gate:** agents
**Size:** M — one call to OpenRouter's key usage and the spend block on S17's route
**Builds:** Monitoring → Calls out (OpenRouter key usage), the spend block of `Overview` (`totalUsd`, `alertUsd`, `alert`); System-wide → Alerts (none are sent; the banner flag only)
**Extends:** `getOverview`, which S17 owns
**Stubs:** none
**Requirements:** CO-1, GC-3
**Guards:** CO-1

#### Why
Spend is read from the provider, so eval runs count too. The business view flags it past the CO-1 line. No message is sent (builder, 2026-10-19); the OpenRouter key's own $250 limit stops a runaway loop.

#### How it's checked
Tests with a fake key-usage reader, and one check against the real key usage.

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

4. The flag turns on past the line
   Given key usage of $104.00
   When I call `GET /overview`
   Then `spend.alert` is true

5. The flag stays off below the line
   Given key usage of $38.00
   When I call `GET /overview`
   Then `spend.alert` is false

6. Usage is read at most once a minute
   Given the reader counting its calls
   When I call `GET /overview` 5 times within a minute
   Then key usage was read once

#### Not in this story
- The spend line and banner on the screen with real numbers — picked up by S30

### S16 — Answer the uptime check and record each ping

**Kind:** module
**Blocked by:** S01
**Review gate:** agents
**Size:** M — one route and one table, with four cases
**Builds:** Monitoring → `getHealth` (`GET` and `HEAD /health`), the `pings` table's write path, the "ping insert never delays the reply" Must hold
**Extends:** none
**Stubs:** Knowledge → `indexStatus` (removed by S30); Scheduling → `schedulingStatus` (removed by S30)
**Requirements:** DP-2 (ping record)
**Guards:** DP-2

#### Why
The uptime checker pings every 5 minutes. The app records each ping, so the business view can show a missed one, and it says which part is unhealthy.

#### How it's checked
Route tests against a temporary app database with the status interfaces stubbed.

#### Acceptance criteria
1. Healthy
   Given every part healthy
   When I call `GET /health`
   Then the answer is 200 with status `ok` and components `schedulingDb: ok`, `appDb: ok`, `index: loaded`
   And one ping row is added

2. HEAD works and is recorded
   Given the app running
   When I call `HEAD /health`
   Then the answer is 200 with no body and one ping row is added with its answer time

3. A missing index is named
   Given the index status stub reporting not loaded
   When I call `GET /health`
   Then the answer is 200 with status `degraded` and `index: missing`

4. A failed ping record never fails the check
   Given the pings table faked to fail on insert
   When I call `GET /health`
   Then the answer is still 200

#### Not in this story
- The ping strip and the missed-ping status on the Overview — picked up by S48 and S30

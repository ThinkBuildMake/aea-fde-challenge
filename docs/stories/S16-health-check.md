### S16 — Answer the host's health check

**Kind:** module
**Blocked by:** S01
**Review gate:** agents
**Size:** S — one read-only route, three cases
**Builds:** Monitoring → `getHealth` (`GET` and `HEAD /health`), used as Railway's health-check path
**Extends:** none
**Stubs:** Knowledge → `indexStatus` (removed by S30); Scheduling → `schedulingStatus` (removed by S30)
**Requirements:** DP-2 (the health check that guards each deploy)
**Guards:** DP-2

#### Why
Railway calls this on every deploy and keeps the old version running if it fails. It also says which part is unhealthy. There is no outside uptime monitor and nothing is recorded (builder, 2026-10-19).

#### How it's checked
Route tests with the status interfaces stubbed.

#### Acceptance criteria
1. Healthy
   Given every part healthy
   When I call `GET /health`
   Then the answer is 200 with status `ok` and components `schedulingDb: ok`, `appDb: ok`, `index: loaded`

2. HEAD works
   Given the app running
   When I call `HEAD /health`
   Then the answer is 200 with no body

3. A missing index is named
   Given the index status stub reporting not loaded
   When I call `GET /health`
   Then the answer is 200 with status `degraded` and `index: missing`

#### Not in this story
- The health check on the deployed app — picked up by S30

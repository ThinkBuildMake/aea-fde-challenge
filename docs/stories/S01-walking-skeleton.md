### S01 — The app runs at its public URL with every part stubbed

**Kind:** skeleton
**Blocked by:** none
**Review gate:** human demo
**Size:** L — first deploy, the regression gate, every table and every route and module as a contract stub
**Builds:** Environments → Production (Railway service, volume, health-check path, deploy only after CI); System-wide → Startup, Settings, Error format, Content negotiation; Database schema → Migrations; the regression gate (Environments and the regression gate: ruff, pyright, pytest, gitleaks over the full history, pip-audit, the schema-diff test against `SCHEMA.md`, one eval case); Dependabot; the metrics dashboard frame on `GET /business` (one empty panel per `KEY_METRICS.md` metric); contract stubs for every route in Conversation, Follow-ups, Monitoring, Knowledge and Scheduling and for every module interface
**Wires:** none
**Extends:** none
**Stubs:** none — this story creates the stubs; each is replaced by the story that owns the element
**Requirements:** GC-1, GC-5, GC-7, DP-1, DP-3, CP-2, CT-1, PF-1 (gate case)
**Guards:** CT-1, CP-2

#### Why
Every later story replaces one stub with the real thing, so module stories can run in parallel from day one. The gate stops a broken change before it merges, and the dashboard has its place before any data exists.

#### How it's checked
Demo:
1. Open the Railway URL in a private browser window, then open `/business`.
2. Open the latest CI run on the main branch.
3. Call two stub routes with `curl`, one valid and one with an unknown conversation id.

#### Acceptance criteria
1. Public URL, no login
   Given a browser that has never visited the site
   When I open the public Railway URL
   Then the caller chat page loads with no sign-in prompt

2. Every route answers its contract
   Given the deployed app
   When the gate's contract test calls each route in `ARCHITECTURE.md` with a valid request
   Then each answers with the status and the response shape its contract states
   And with an `HX-Request` header the same route answers with an HTML fragment

3. One error format
   Given the deployed app
   When I send `POST /conversations/not-a-real-id/messages`
   Then the answer is 404 with body `{"error": "conversation_not_found", "message": ...}` and no stack trace

4. Every app table exists
   Given a fresh start with an empty volume
   When the gate's schema test reads the app database
   Then the seven app tables exist with the columns `ARCHITECTURE.md` lists and the schema version is the latest migration

5. The supplied schema is untouched
   Given the supplied scheduling database after start
   When the schema-diff test runs
   Then it reports 0 differences from `SCHEMA.md` (CT-1: "0 changed or dropped columns/tables")

6. Seed copied only if missing
   Given the supplied file on the volume holds one booking made after the seed
   When I redeploy
   Then the booking is still there

7. A missing setting stops the start
   Given `OPENROUTER_API_KEY` is unset
   When the app starts
   Then it exits with a message naming the missing setting

8. The gate blocks a red change
   Given a branch with one failing test
   When CI runs
   Then the run is red and Railway does not deploy it

9. The gate holds an eval case
   Given the fake model provider set to answer in 7 s
   When the gate plays its one eval conversation
   Then the gate fails on the first-reply time (PF-1: "p95 time to first visible reply ≤ 6 s")

10. Secrets stay out
    Given the full git history
    When CI runs gitleaks
    Then it reports 0 findings (CP-2: "0 secrets (API keys) in the repository history")

11. `wireframe` The dashboard has its place
    Given the deployed app
    When I open `/business`
    Then I see the title "Meridian AI agent: business view", the tabs Overview, Handoffs, Waitlist and Conversations, and one empty panel for each of the 9 metrics in `KEY_METRICS.md`, named as there

#### Not in this story
- The real caller chat screens — picked up by S20 and S21
- The real Overview numbers and tab — picked up by S17 and S22
- Each stub's real behaviour — picked up by the module story that owns it (INDEX → Architecture coverage)

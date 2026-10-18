# STACK.md — Meridian AI Call Agent technology choices

**What this document is.** A comparison of candidate technologies for each module, and the choice for each. `REQUIREMENTS.md` defines what the system must do; requirement IDs (e.g. `PF-1`) appear here only as the reason a choice wins or loses. Which components exist and the load they carry are in `HIGH_LEVEL_DESIGN.md`; how the pieces fit together is designed in `ARCHITECTURE.md`.

**How the shortlist was built.** Each module's options were researched against `REQUIREMENTS.md`, `HIGH_LEVEL_DESIGN.md`, `USERS.md`, `AUDIT.md` and `KEY_METRICS.md`, with deciding facts checked on 2026-10-17. A separate agent that hadn't seen the research then checked the chosen stack for conflicts. It found no blocker and 28 findings; the ones that change a choice or add a need from the design are applied below, and the ones that were conflicts between requirements or errors in the high-level design are settled in those documents. On 2026-10-18 the stack was re-researched against industry practice (agent frameworks, observability, evaluation, retrieval, app layer and hosting). It kept the hand-written agent loop, SQLite, htmx, Railway and the custom eval runner, and added tracing, alerting, backups, migrations and security basics (modules 4, 13 to 18); the changes were not re-run through the separate conflict check, only the new items are marked **[verify]**.

**Markers.** **[verify]** = an external fact checked on 2026-10-17 (often from secondary sources) that should be re-confirmed before it's relied on. Go-live prerequisites, open choices and open questions are in the last sections.

---

## Summary

| # | Module | Choice | Main reason |
|---|---|---|---|
| 1 | Language and web server | Python 3.12, FastAPI, one uvicorn process | Builder's choice; SQLite built in (GC-6, SC-2) |
| 2 | Web client | Jinja2 pages with htmx, no build step | Two chat screens and four tables (HLD §5) |
| 3 | Scheduling database | Supplied SQLite file, unchanged | GC-6, CT-1 |
| 4 | App database | SQLite, separate file, same volume; numbered migrations, volume backups | Survives the seed reset (DP-4); 10 MB (HLD §2) |
| 5 | Retrieval index | In-memory vectors with numpy | About 40 passages (HLD §3); PRD-2, EV-4 |
| 6 | Embeddings | `text-embedding-3-small` through OpenRouter (OpenAI direct as fallback) | $0.02 per million tokens; one vendor fewer |
| 7 | Model access | OpenRouter, with the builder's own Google key (BYOK) | Approved provider (GC-4); one place to swap models |
| 8 | Agent model | Gemini 3 Flash Preview, pinned slug | $0.50 / $3 per million tokens; tool use (CO-1) |
| 9 | Safety screen | Gemini 3.1 Flash Lite | Runs on every message (FR-1.1, FR-1.2) |
| 10 | Document reading | Gemini 3 Flash Preview, once per build | PNG and PDF facts (FR-2.3, FR-2.4) |
| 11 | Orchestration | `openai` Python SDK on OpenRouter, hand-written tool loop | Log every turn (OB-1); commit before "booked" (RL-2) |
| 12 | Eval harness | Custom Python runner, LLM judge, pytest | EV-3 to EV-7, SC-2 |
| 13 | Hosting | Railway Hobby plan, one service, 1 GB volume | Approved (GC-4); disk survives deploys (HLD §7) |
| 14 | Uptime checker and alerts | UptimeRobot free tier with email alerts; Railway deploy-failed webhook; a spend alert to a chat webhook | 5-minute external ping (DP-2) at $0 (GC-4); a miss reaches a person |
| 15 | Secrets and settings | Railway environment variables read by one typed settings class; gitleaks in CI and pre-commit | DP-3, CP-2 |
| 16 | CI/CD and tooling | GitHub Actions (ruff, pyright, pytest, gitleaks, pip-audit), Dependabot, `uv` lockfile; Railway deploys on push to `main` only after CI passes | Tested deploys; pinned versions |
| 17 | Observability | The app's own business view and JSON logs on stdout; Langfuse Cloud traces iceboxed for v1 (builder, 2026-10-18) | FR-5.3, OB-1 |
| 18 | Authentication and abuse limits | None for callers (the business view is also open, by decision); per-IP rate limits, security headers | DP-1, GC-5; GC-3 |

**Cost (total over the build, ending 2026-11-05; token prices from OpenRouter listings [verify]):**

| Item | Cost |
|---|---|
| Model use: 4 to 6 eval runs at about $2.50 to $4 each, prompt tuning, live traffic | $20 to $45 |
| Embeddings (through OpenRouter credits) | under $1; fund $5 |
| Langfuse Cloud Hobby (50,000 units a month, 30-day retention, 2 users) | $0; not used in v1 (tracing iceboxed for v1 (builder, 2026-10-18)) |
| OpenRouter fee on credits | 5.5% on a purchase if credits are used; reduced under BYOK [verify] |
| Hosting (Railway Hobby, about 3 weeks) | $5 to $10 |
| Uptime checker, CI | $0 |
| **Typical** | **about $30 to $55** |
| **Worst case** | **about $100 to $150** — only with many long eval runs or a bot hitting the public URL; touches the $100 CO-1 alert |

At these prices the high-level design's cost envelope (§6) is about 1.5 to 2 times too high; see open questions.

---

## Glossary

`REQUIREMENTS.md` defines the product's own vocabulary — conversation, scenario, outcome, contained-correct, current document, superseded value, handoff record, zone, open slot — and isn't repeated.

**Models and the services around them**

| Term | Meaning |
|---|---|
| Language model | A program that reads text and writes text. Here it holds the conversation with the caller. |
| Token | The unit a language model reads and writes, roughly three-quarters of a word. Prices are quoted per million tokens. |
| Tool use (tool calling) | The model asks the app to do something, such as "look up open slots", and the app does it and returns the result. The model never touches the database itself. |
| Thinking (reasoning) | Extra text a model writes to itself before answering. It improves answers but takes time and is billed as output. |
| Reasoning details / thought signature | A coded note the model attaches to its reasoning. Some models refuse the next message in a conversation unless the app sends those notes back unchanged. |
| Structured output | Forcing a model to reply in a fixed shape, such as `{"safe": true}`, so the app can read it without guessing. |
| Embedding | A list of numbers that stands for the meaning of a piece of text, so that similar texts have similar lists. |
| OpenRouter | A service that gives access to many companies' models through one account and one key. |
| BYOK ("bring your own key") | Using your own account with the model's maker, so the maker bills you for tokens directly and the middleman only passes the request on. |
| Preview model | A model its maker still calls unfinished. It may change or be switched off with notice. |
| Rate limit | A cap on how many requests a service accepts per minute. Going over returns an error, code 429. |
| Trace | A record of one conversation turn as a tree of steps (the model call, each tool call) with timings, token counts and cost, kept so a person can inspect what happened. |
| Langfuse | A service that stores and displays traces and runs experiments over test cases; the cloud version is hosted by its maker. |
| Migration | A numbered script that changes the database's tables, applied once and in order when the app starts. |

**Data and storage**

| Term | Meaning |
|---|---|
| SQLite | A database that is a single file, with no separate server to run. |
| WAL mode | A SQLite setting that lets reads continue while a write happens, by keeping recent changes in a side file. |
| Volume | A disk attached to a hosted app that keeps its files when the app is redeployed. Without one, files vanish on every deploy. |
| Vector search | Finding the stored passages whose embeddings are nearest to the question's embedding. |

**Building and running**

| Term | Meaning |
|---|---|
| FastAPI | A Python toolkit for writing the web server that answers the chat and business-view requests. |
| htmx | A small browser script that lets a page update one part of itself from a server reply, without a heavy front-end framework. |
| Health check | A web address that answers "ok" if the app is running, so an outside service can ping it. |
| CI (continuous integration) | Tests and checks that run automatically each time code is pushed. |
| gitleaks | A tool that scans code and its history for passwords and keys that shouldn't be there. |

---

## 1. Language and web server

| Option | Pros | Cons |
|---|---|---|
| **Python 3.12 with FastAPI** ✅ | Builder's choice. SQLite is in the standard library (GC-6). Every provider has a Python library. Supported until October 2028. | Blocking calls inside async handlers stall the whole process, including the health check. |
| Python with Flask | Simplest for a few routes. | No built-in async; the 4-way eval (SC-2) would need threads. |
| TypeScript with Node | One language for server and pages. | A second toolchain next to the existing Python analysis scripts. |

**Choice: Python 3.12 with FastAPI.** One uvicorn process serves the load (under 2 requests a second, HLD §2).

**Needs from the design.** Never run blocking SQLite or SDK calls inside `async` handlers (use plain `def` handlers or a thread), because a stalled loop would also fail `/health` and show false downtime (DP-2). Answer `/health` to both GET and HEAD.

## 2. Web client

| Option | Pros | Cons |
|---|---|---|
| **Jinja2 pages with htmx** ✅ | No build step. Served by the app, as HLD §5 assumes. Enough for chat bubbles, tables and a 30-second refresh (OB-2). | The 24-hour latency and uptime lines need one small charting file, self-hosted. |
| React with Vite | Richer interactions. | A second build toolchain for six screens, five days before the deadline (GC-1). |

**Choice: Jinja2 with htmx.** The wireframe is two chat screens and four tables (HLD §5).

## 3. Scheduling database

**Choice: the supplied SQLite file, unchanged.** GC-6 and CT-1 fix it; there is no alternative.

**Needs from the design.** The supplied schema has no unique rule on `appointments.slot_id`, and foreign keys are off, so the database cannot stop a double booking (RL-1) and CT-1 forbids adding one. Every book, move and cancel must be one transaction that takes the write lock first, changes the slot only if it is still open, checks that exactly one row changed, and then writes the appointment. The reset (DP-4) must run inside the app or with all connections closed, never by copying a file over a live one.

## 4. App database

| Option | Pros | Cons |
|---|---|---|
| **SQLite, separate file on the same volume** ✅ | Same engine as the scheduling data. Needs no extra service. About 10 MB (HLD §2). DP-4 never touches it. | One writer at a time. WAL mode on a hosted volume is untested (Railway documents nothing about SQLite). |
| Postgres as a second Railway service | Many writers; a built-in backup tool. | An always-on service costing about $5 a month to hold 400 conversations. |

**Choice: SQLite, WAL mode, with a fallback.** Fits HLD §3 and §5.

**Needs from the design.** Store each reply from the model as the raw message it returned, including its reasoning notes (module 8). Test WAL on the volume early with forced kills (RL-2); if it misbehaves, switch the app database to the plain journal setting. Schema changes are numbered `.sql` files applied at start and tracked by SQLite's `user_version`, with a lock-wait timeout and foreign keys on for this file only. Turn on Railway's volume backups [verify]. A reviewer rewards a reasoned database choice, so keep a short note on why SQLite rather than Postgres (the supplied database must stay SQLite, CT-1; one writer at 0.3 turns/s; a second engine doubles the reset story). Waitlist entries store a copy of the held slot (date, window, zone), not a pointer to an appointment row, because the reset removes appointments (DP-4).

## 5. Retrieval index

| Option | Pros | Cons |
|---|---|---|
| **numpy, in memory** ✅ | About 40 passages (HLD §3) is one small file. No dependency to run. Easy to rebuild with one command (CH-1). | No filtering or ranking features; if EV-4 misses, a second ranking step must be added by hand. |
| sqlite-vec or Chroma | Standard vector-store features. | Another dependency for 40 rows. |

**Choice: numpy.** PRD-2 and EV-4 require retrieval evaluated alone; the size does not (HLD §5). The index file records the embedding model, its dimensions and a hash of the passage text, and a build refuses a mismatch.

**Needs from the design.** Mark `escalation_and_safety.md` agent-only like `internal/`, since it sits outside that folder but tells agents to do things FR-2.8 and FR-2.10 forbid (FR-2.7).

## 6. Embeddings

| Option | Pros | Cons |
|---|---|---|
| **`text-embedding-3-small` through OpenRouter** ✅ | $0.02 per million tokens [verify]. Same account and key as the chat models, so no second vendor (GC-4). | Billed from OpenRouter credits, not the Google key. Listing found by search, not yet called live [verify]. An extra call on every turn. |
| OpenAI `text-embedding-3-small` direct | Fallback if the OpenRouter call fails its test. On the approved list (GC-4). | A second vendor, key and prepaid balance. |
| Cohere Embed 4 | Approved. Good quality. | $0.12 per million tokens; the free trial key is not allowed in production, and the paid key bills monthly [verify]. |

**Choice: `text-embedding-3-small` through OpenRouter, OpenAI direct as the fallback.** Under $1 for the whole build. Test one embeddings call on day 1; if it fails, use the OpenAI key.

**Needs from the design.** An embedding failure on a live turn is a provider failure under DE-1: answer without retrieval or hand off, never show an error.

## 7. Model access

| Option | Pros | Cons |
|---|---|---|
| **OpenRouter with the builder's own Google key (BYOK)** ✅ | Approved provider (GC-4). Google bills tokens directly. One key and one request format for every model, so a model can be swapped by changing a name. | An extra hop. The 5.5% credit fee is waived or reduced under BYOK, but I couldn't confirm the terms [verify]. |
| Google's Gemini API directly | One hop fewer. | Not on the approved list (GC-4); leaves no cheap way back to another vendor. |
| Anthropic directly | On the list; model quality is strong. | About 4 times the token price of the Gemini choice. |

**Choice: OpenRouter, BYOK.** Chosen by the builder (2026-10-17) for price; the approved list rules out calling Google directly.

**Needs from the design.** Leave OpenRouter's input/output logging off and send no card numbers: strip card-shaped strings from every message before the safety screen, the model, the database and the logs (CP-1). Treat provider errors 402 and 429 as DE-1 failures. Spend is read from OpenRouter's key usage (embeddings included; a manual line for OpenAI only if the fallback is used), because per-conversation costs miss eval runs and the one-time document read (CO-1).

## 8. Agent model

| Option | Pros | Cons |
|---|---|---|
| **Gemini 3 Flash Preview (dated slug `google/gemini-3-flash-preview-20251217`)** ✅ | $0.50 in / $3 out per million tokens; 1M context; tool calling and structured output listed [verify]. | A preview model. Google lists no shutdown date, but recommends a newer replacement. It shares one blind spot with the judge (module 12). Thinking time may miss PF-1. |
| Claude Sonnet 5.5 | Strong on tool use and "never do X" rules (AZ-3, VR-9). | $2 / $10 per million, about 4 times the price. |
| Claude Haiku 5.5 | $0.10 / $0.50. | Riskier on the trap scenarios. |

**Choice: Gemini 3 Flash Preview, pinned.** Builder's choice on price; the eval decides whether it stays (open choices).

**Needs from the design.** Pin the dated slug and one provider route with no fallback, so reasoning signatures stay on one route. Set the thinking level to low. Start the safety screen at the same time as the first agent call and hold any tool that writes until the screen returns safe, because three or four calls in a row would miss PF-1 (6 s) and PF-2 (10 s). Replay the stored raw messages unchanged and in order on every turn; a missing signature returns an error that a retry does not fix, so end the conversation with the DE-1 message.

## 9. Safety screen

| Option | Pros | Cons |
|---|---|---|
| **Gemini 3.1 Flash Lite** ✅ | Released as final 2026-05-07, so it is not a preview. $0.25 / $1.50 per million. Fast enough to run on every message. | A small model may miss an oddly worded gas or carbon-monoxide report. |
| Keyword rules | Free, instant. | Misses "smells like something is cooking in the wall"; fails VR-2. |

**Choice: Gemini 3.1 Flash Lite.** FR-1.1 and FR-1.2 need a check on every message.

**Needs from the design.** Confirm the exact OpenRouter ID before hard-coding it [verify].

## 10. Document reading

**Choice: Gemini 3 Flash Preview, once per build.** It reads the holiday-hours PNG and the fee-schedule PDF (FR-2.3, FR-2.4); a person checks the extracted text once. A text extractor such as pdfplumber would do for the PDF (it has a text layer) but not the image, and two methods are more to maintain.

**Needs from the design.** The checked text is stored as a file beside the knowledge base, because a misread dollar figure would flow into answers (VR-9).

## 11. Orchestration

| Option | Pros | Cons |
|---|---|---|
| **`openai` Python SDK pointed at OpenRouter, with a hand-written tool loop** ✅ | About 50 lines. We log every turn and tool call (OB-1) and commit a booking before the reply says "booked" (RL-2). Typed errors. | We write the loop and the retry rules ourselves. |
| LangChain or LangGraph | Ready-made agent patterns. | Hidden retries and hidden state work against OB-1; its handling of Gemini reasoning notes through OpenRouter is reported broken in places [verify]. |
| Raw HTTP calls | No library. | Rebuilds what the SDK already provides. |

**Choice: `openai` SDK, hand-written loop.** OB-1 and RL-2. Re-checked 2026-10-18 against Pydantic AI, LangGraph with LangChain, the OpenAI Agents SDK and Google ADK: none is verified to replay Gemini's reasoning notes through OpenRouter (LangChain has reported failures), and the safety gate, customer binding and exact history stay custom code in every one. Pydantic is used for tool argument schemas and validation. Pydantic AI is the fallback if a Claude model is added or the tools pass about 20.

**Needs from the design.** Persist the provider's raw JSON assistant message, not the SDK's object. Set an explicit timeout and no automatic retries on each model call, with one deadline for the whole turn that covers retries and tool rounds. The SDK defaults to ten minutes and two retries, which would defeat DE-1. Spike structured output together with tool calling on this model in week one; if it misbehaves, put the reply in a final "respond" tool instead [verify].

## 12. Eval harness

| Option | Pros | Cons |
|---|---|---|
| **Custom Python runner, an LLM judge, pytest for invariant queries** ✅ | Runs scenarios against a private copy of the scheduling data and checks database changes (VR-6, VR-7). One command (EV-7). | We write it. The judge is the same model family as the agent and shares its blind spots. |
| promptfoo | Ready-made report and comparisons. | Node toolchain; cannot check database side effects. |

**Choice: custom runner.** HLD §4.2 already specifies it.

**Needs from the design.** Give each of the 4 parallel conversations its own scheduling copy, reseeded per scenario, and a separate app database (SC-2). Run it locally against a private app, never against the deployed URL, so evals do not pollute the business view.

## 13. Hosting

| Option | Pros | Cons |
|---|---|---|
| **Railway Hobby, one service, 1 GB volume** ✅ | Approved (GC-4). Git-push deploys and a public URL. Keeps the disk across deploys. $5 a month including $5 of usage; a small always-on app is about that [verify]. | A volume allows one active deployment, so each deploy is a short outage. Commands that touch the volume must run inside the service, not from your laptop. |
| DigitalOcean Droplet | $4 a month; full control. | You set up TLS, restarts and deploys yourself. |
| DigitalOcean App Platform | Managed. | Reported to have no persistent disk [verify]; fails HLD §7. |

**Choice: Railway Hobby.** The least setup before 2026-10-21 (GC-1).

**Needs from the design.** Freeze deploys from the evening of 2026-10-20 through 2026-11-05 except for fixes; 99% over about 15 days allows about 3.5 hours down (DP-2). Turn on "Wait for CI" so a failing commit never deploys, set a health-check path, and write down the rollback steps (Railway restores the previous image; whether the volume is untouched is [verify]). Keep CI fast, because a CI wait can slow a fix during the freeze. Seed the volume only when the file is missing, never on deploy. Run the reset (DP-4) and index rebuild (CH-1) inside the service with `railway ssh` (register an SSH key first and test it before the freeze), with a bearer-token admin route as the fallback, never an open one (GC-5). Plain `railway run` does not see the volume.

## 14. Uptime checker

| Option | Pros | Cons |
|---|---|---|
| **UptimeRobot free** ✅ | 5-minute checks, 50 monitors, $0 (official pricing page). | Terms differ between pages: "hobby and non-profit" versus "any use"; a synthetic internal demo fits either [verify]. |
| GitHub Actions cron | Already in use. | Schedules are delayed and disabled after 60 days idle; 5 minutes is its floor. |

**Choice: UptimeRobot free.** DP-2 asks for exactly this at $0 (GC-4).

**Needs from the design.** The ping write must be best-effort so the response never waits on the database; the app's own ping log is the evidence for DP-2. A monitor nobody hears about is not monitoring: UptimeRobot emails on a miss; Railway posts a failed deploy to a chat webhook; the app posts once to the same webhook when cumulative spend passes the CO-1 threshold (Slack and Discord webhooks are free; UptimeRobot's own webhook alerts look paid [verify]).

## 15. Secrets

**Choice: Railway environment variables read by one typed settings class (pydantic-settings), plus the gitleaks binary in CI and as a pre-commit hook.** DP-3 and CP-2. A committed `.env` fails CP-2. The settings class fails at start if a required variable is missing. Run the binary directly with full history (`fetch-depth: 0`); the hosted action needs a licence on organization repositories.

## 16. CI/CD

| Option | Pros | Cons |
|---|---|---|
| **GitHub Actions (ruff, pytest, gitleaks); Railway deploys on push to `main`** ✅ | Free for this size. | A failing commit can still deploy unless Railway waits for CI [verify]. |
| Railway deploys alone | Zero setup. | No test gate. |

**Choice: GitHub Actions.** Dependencies are pinned in a `uv` lockfile and the Python version is set explicitly in the build. CI runs ruff, pyright on the app code, pytest, gitleaks and `pip-audit`; Dependabot watches pip and Actions. "Wait for CI" in Railway holds a deploy until the workflow passes (documented; it needs an `on: push` workflow).

## 17. Observability

**Iceboxed 2026-10-18 (builder): v1 ships with the business view and JSON logs only.** The Langfuse choice below is kept as the design for when tracing is turned on; nothing in v1 depends on it, because OB-1 is met by the app's own tables.

**Choice: the app's own business view, JSON logs on stdout, and Langfuse Cloud (US region, Hobby free tier) for traces.** FR-5.3 and OB-1 already require the data in our own tables, and the business view must work if a vendor is down, so Langfuse sits beside it and replaces nothing. Re-checked 2026-10-18 against LangSmith (5,000 traces a month, one seat), Arize Phoenix (no verified free cloud), Helicone (10,000 requests, 7-day retention, future unclear after the Mintlify purchase), Braintrust (14-day retention), Pydantic Logfire (good only with Pydantic AI) and plain OpenTelemetry (no UI). Langfuse is MIT-licensed with a self-host path if the free tier runs out. Do not log message bodies at INFO.

| Option | Pros | Cons |
|---|---|---|
| **Langfuse Cloud Hobby** ✅ | 50,000 units a month and 30-day retention cover about 400 conversations to 2026-11-05; datasets and experiments for the eval; no server to run | One more vendor and key; free-tier caps (30 API requests a minute) [verify]; sees whatever we send |
| LangSmith | Deep LangChain support | 5,000 traces and one seat; self-host needs Enterprise |
| Arize Phoenix | OpenTelemetry-native | No verified free cloud; self-host loses data on redeploy without Postgres |
| Plain OpenTelemetry and logs | Nothing new | No trace UI for a reviewer |

**Needs from the design.** Send traces from our own code, built only from the text left after card-shaped strings were removed (CP-1), plus ids, tool names, outcome, cost and latency; a masking hook drops any run of 13 to 19 digits. Tracing is fire-and-forget: a Langfuse failure never delays or fails a turn. Use the conversation's public id, never its secret id, as the Langfuse session id. OpenRouter's Broadcast feed to Langfuse is not used, because it fires before our scrubber. Test CP-1 against Langfuse as well as the logs.

## 18. Authentication

**Choice: none for the caller chat.** DP-1 requires no login. The business view and its write actions (flag, mark followed up) are open to anyone with the URL; see open questions.

**Needs from the design.** Per-IP rate limits with `slowapi` (the client address comes from `X-Forwarded-For` behind Railway's proxy [verify]), a per-conversation turn cap and a message-length cap, so an anonymous visitor cannot run up the model bill (GC-3). Security headers (a strict content policy, no framing, no sniffing; htmx is served from our own files so the policy stays strict). No cross-origin access: pages and API share one origin, so no CORS middleware. The admin token is compared in constant time. `pip-audit` and Dependabot cover dependencies.

---

## 19. Go-live prerequisites

| Prerequisite | Lead time | Blocks |
|---|---|---|
| OpenRouter account; your Google key added under BYOK; about $50 of credit if any traffic is billed there | minutes to an hour | Every model call |
| OpenRouter credit of about $50 covers chat fallbacks and embeddings; an OpenAI account with $5 only if the embeddings test fails | minutes | Embeddings |
| Railway account on the Hobby plan, volume created | minutes | Deployment |
| UptimeRobot account, one HTTP monitor on `/health`, email alerts on | minutes | DP-2 evidence and alerts |
| Langfuse Cloud account in the US region (us.cloud.langfuse.com), a project, and its public and secret keys in Railway variables | minutes | Traces (only when tracing is turned on; iceboxed for v1 (builder, 2026-10-18)) |
| A Slack or Discord incoming webhook for alerts (deploy failed, spend threshold) | minutes | Alerts |
| Railway: volume backups on, "Wait for CI" on, an SSH key registered for `railway ssh` | minutes | Backups, tested deploys, admin jobs |
| GitHub repository secrets for deploy | minutes | CI |

## 20. Open choices

| Choice | Current lean | Settled by |
|---|---|---|
| Thinking level for the agent model | Low | Day-1 prototype: p95 first reply under 6 s (PF-1) |
| Keep Gemini 3 Flash Preview | Keep | First eval run: 0 failures on the Gate scenarios (AZ-1 to AZ-3, VR-9); otherwise move the agent to Claude Sonnet 5.5 by changing the model name |
| Reasoning notes replayed correctly through OpenRouter | Pin one provider | Two-tool-round, multi-turn test on day 1 |
| Structured output together with tool calling | Use both | Day-1 spike; fall back to a final "respond" tool |
| WAL mode for the app database | WAL | Forced-kill test on the Railway volume |
| A second ranking step for retrieval | None | EV-4 result; add only if fewer than 18 of 20 hit |
| Cost field under BYOK | Read from OpenRouter key usage | Check what OpenRouter reports for a BYOK call [verify] |
| Pydantic AI instead of the hand-written loop | Keep the loop | Day-1 test: Gemini reasoning notes survive a two-round multi-turn run, per-call timeout and zero retries can be set, raw messages can be stored and replayed |
| Langfuse free-tier fit and card text (iceboxed with tracing) | Hobby is enough | Units used after the first 50 conversations; CP-1 test with 5 card-shaped messages against Langfuse |
| `railway ssh` for admin jobs | Use it | Test with a registered key before the freeze; else the admin routes |
| Embeddings through OpenRouter | Use OpenRouter | Day-1 test of `openai/text-embedding-3-small` on OpenRouter; OpenAI direct only if it fails |

## 21. Open questions

None. The conflicts between requirements that the stack check found (fallback timing, double-booking enforcement, the waitlist and the seed reset, the fixed demo clock, the internal-guidance file) are settled in `REQUIREMENTS.md` (DE-1, RL-1, FR-1.15, DP-4, GC-8, FR-2.7, D-11), and the design errors in `HIGH_LEVEL_DESIGN.md` (§3, §5, §6, §7). The business view stays open by the builder's decision (GC-7); rate and turn caps remain a design guard.

---

## Sources (checked 2026-10-17)

- [Railway pricing plans](https://docs.railway.com/pricing/plans)
- [Railway volumes reference](https://docs.railway.com/volumes/reference)
- [Langfuse pricing](https://langfuse.com/pricing) and [LangSmith pricing](https://www.langchain.com/pricing) (checked 2026-10-18 by a research agent; free-tier numbers [verify])
- [OpenRouter reasoning tokens](https://openrouter.ai/docs/guides/best-practices/reasoning-tokens) and [Pydantic AI OpenRouter docs](https://pydantic.dev/docs/ai/models/openrouter/)
- [OpenRouter: Gemini 3 Flash Preview](https://openrouter.ai/google/gemini-3-flash-preview)
- [OpenRouter: Gemini 3.1 Flash Lite](https://openrouter.ai/google/gemini-3.1-flash-lite)
- [OpenRouter pricing and fees (secondary)](https://amnic.com/blogs/openrouter-pricing)
- [Gemini API pricing (secondary)](https://developer.puter.com/tutorials/gemini-api-pricing/)
- [Google Gemini API deprecations](https://ai.google.dev/gemini-api/docs/deprecations)
- [OpenAI text-embedding-3-small](https://developers.openai.com/api/docs/models/text-embedding-3-small)
- [Cohere API pricing (secondary)](https://developer.puter.com/tutorials/cohere-api-pricing/)
- [UptimeRobot pricing](https://uptimerobot.com/pricing/?rd=1)
- [DigitalOcean volume pricing](https://docs.digitalocean.com/products/volumes/details/pricing/)
- Claude model prices: Anthropic model list, cached 2026-10-06

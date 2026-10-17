# STACK.md — Meridian AI Call Agent technology choices

**What this document is.** A comparison of candidate technologies for each module, and the choice for each. `REQUIREMENTS.md` defines what the system must do; requirement IDs (e.g. `PF-1`) appear here only as the reason a choice wins or loses. Which components exist and the load they carry are in `HIGH_LEVEL_DESIGN.md`; how the pieces fit together is designed in `ARCHITECTURE.md`.

**How the shortlist was built.** Each module's options were researched against `REQUIREMENTS.md`, `HIGH_LEVEL_DESIGN.md`, `USERS.md`, `AUDIT.md` and `KEY_METRICS.md`, with deciding facts checked on 2026-10-17. A separate agent that hadn't seen the research then checked the chosen stack for conflicts. It found no blocker and 28 findings; the ones that change a choice or add a need from the design are applied below, and the ones that are really conflicts between requirements or errors in the high-level design are in the last section.

**Markers.** **[verify]** = an external fact checked on 2026-10-17 (often from secondary sources) that should be re-confirmed before it's relied on. Go-live prerequisites, open choices and open questions are in the last sections.

---

## Summary

| # | Module | Choice | Main reason |
|---|---|---|---|
| 1 | Language and web server | Python 3.12, FastAPI, one uvicorn process | Builder's choice; SQLite built in (GC-6, SC-2) |
| 2 | Web client | Jinja2 pages with htmx, no build step | Two chat screens and four tables (HLD §5) |
| 3 | Scheduling database | Supplied SQLite file, unchanged | GC-6, CT-1 |
| 4 | App database | SQLite, separate file, same volume | Survives the seed reset (DP-4); 10 MB (HLD §2) |
| 5 | Retrieval index | In-memory vectors with numpy | About 40 passages (HLD §3); PRD-2, EV-4 |
| 6 | Embeddings | OpenAI `text-embedding-3-small` | $0.02 per million tokens; no trial cap |
| 7 | Model access | OpenRouter, with the builder's own Google key (BYOK) | Approved provider (GC-4); one place to swap models |
| 8 | Agent model | Gemini 3 Flash Preview, pinned slug | $0.50 / $3 per million tokens; tool use (CO-1) |
| 9 | Safety screen | Gemini 3.1 Flash Lite | Runs on every message (FR-1.1, FR-1.2) |
| 10 | Document reading | Gemini 3 Flash Preview, once per build | PNG and PDF facts (FR-2.3, FR-2.4) |
| 11 | Orchestration | `openai` Python SDK on OpenRouter, hand-written tool loop | Log every turn (OB-1); commit before "booked" (RL-2) |
| 12 | Eval harness | Custom Python runner, LLM judge, pytest | EV-3 to EV-7, SC-2 |
| 13 | Hosting | Railway Hobby plan, one service, 1 GB volume | Approved (GC-4); disk survives deploys (HLD §7) |
| 14 | Uptime checker | UptimeRobot free tier | 5-minute external ping (DP-2) at $0 (GC-4) |
| 15 | Secrets | Railway environment variables, gitleaks in CI | DP-3, CP-2 |
| 16 | CI/CD | GitHub Actions, Railway deploy on push to `main` | Free; no gate needed beyond tests |
| 17 | Observability | The app's own business view plus stdout logs | FR-5.3, OB-1 |
| 18 | Authentication | None for callers (a decision for the business view is open) | DP-1, GC-5 |

**Cost (total over the build, ending 2026-11-05; token prices from OpenRouter listings [verify]):**

| Item | Cost |
|---|---|
| Model use: 4 to 6 eval runs at about $2.50 to $4 each, prompt tuning, live traffic | $20 to $45 |
| Embeddings (OpenAI) | under $1; fund $5 |
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

**Needs from the design.** Store each reply from the model as the raw message it returned, including its reasoning notes (module 8). Test WAL on the volume early with forced kills (RL-2); if it misbehaves, switch the app database to the plain journal setting. Waitlist entries store a copy of the held slot (date, window, zone), not a pointer to an appointment row, because the reset removes appointments (DP-4).

## 5. Retrieval index

| Option | Pros | Cons |
|---|---|---|
| **numpy, in memory** ✅ | About 40 passages (HLD §3) is one small file. No dependency to run. Easy to rebuild with one command (CH-1). | No filtering or ranking features; if EV-4 misses, a second ranking step must be added by hand. |
| sqlite-vec or Chroma | Standard vector-store features. | Another dependency for 40 rows. |

**Choice: numpy.** PRD-2 and EV-4 require retrieval evaluated alone; the size does not (HLD §5).

**Needs from the design.** Mark `escalation_and_safety.md` agent-only like `internal/`, since it sits outside that folder but tells agents to do things FR-2.8 and FR-2.10 forbid (FR-2.7).

## 6. Embeddings

| Option | Pros | Cons |
|---|---|---|
| **OpenAI `text-embedding-3-small`** ✅ | $0.02 per million tokens. No trial cap. OpenAI is on the approved list (GC-4). | A second vendor, key and prepaid balance, and an extra call on every turn. |
| Cohere Embed 4 | Approved. Good quality. | $0.12 per million tokens; the free trial key is not allowed in production, and the paid key bills monthly [verify]. |
| Embeddings through OpenRouter | One vendor fewer. | Whether OpenRouter serves this model is unconfirmed [verify]. |

**Choice: OpenAI `text-embedding-3-small`.** Under $1 for the whole build.

**Needs from the design.** An embedding failure on a live turn is a provider failure under DE-1: answer without retrieval or hand off, never show an error.

## 7. Model access

| Option | Pros | Cons |
|---|---|---|
| **OpenRouter with the builder's own Google key (BYOK)** ✅ | Approved provider (GC-4). Google bills tokens directly. One key and one request format for every model, so a model can be swapped by changing a name. | An extra hop. The 5.5% credit fee is waived or reduced under BYOK, but I couldn't confirm the terms [verify]. |
| Google's Gemini API directly | One hop fewer. | Not on the approved list (GC-4); leaves no cheap way back to another vendor. |
| Anthropic directly | On the list; model quality is strong. | About 4 times the token price of the Gemini choice. |

**Choice: OpenRouter, BYOK.** Chosen by the builder (2026-10-17) for price; the approved list rules out calling Google directly.

**Needs from the design.** Leave OpenRouter's input/output logging off and send no card numbers: strip card-shaped strings from every message before the safety screen, the model, the database and the logs (CP-1). Treat provider errors 402 and 429 as DE-1 failures. Spend is read from OpenRouter's key usage plus a manual line for OpenAI, because per-conversation costs miss eval runs and the one-time document read (CO-1).

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

**Choice: `openai` SDK, hand-written loop.** OB-1 and RL-2.

**Needs from the design.** Set an explicit timeout and no automatic retries on each model call, with one deadline for the whole turn that covers retries and tool rounds. The SDK defaults to ten minutes and two retries, which would defeat DE-1. Spike structured output together with tool calling on this model in week one; if it misbehaves, put the reply in a final "respond" tool instead [verify].

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

**Needs from the design.** Freeze deploys from the evening of 2026-10-20 through 2026-11-05 except for fixes; 99% over about 15 days allows about 3.5 hours down (DP-2). Seed the volume only when the file is missing, never on deploy. Run the reset (DP-4) and index rebuild (CH-1) inside the service by one command or a protected admin route, never an open one (GC-5). Use plain `railway run` for neither: it runs on your machine and does not see the volume [verify].

## 14. Uptime checker

| Option | Pros | Cons |
|---|---|---|
| **UptimeRobot free** ✅ | 5-minute checks, 50 monitors, $0 (official pricing page). | Terms differ between pages: "hobby and non-profit" versus "any use"; a synthetic internal demo fits either [verify]. |
| GitHub Actions cron | Already in use. | Schedules are delayed and disabled after 60 days idle; 5 minutes is its floor. |

**Choice: UptimeRobot free.** DP-2 asks for exactly this at $0 (GC-4).

**Needs from the design.** The ping write must be best-effort so the response never waits on the database; the app's own ping log is the evidence for DP-2.

## 15. Secrets

**Choice: Railway environment variables, plus the gitleaks binary in CI.** DP-3 and CP-2. A committed `.env` fails CP-2. Run the binary directly with full history (`fetch-depth: 0`); the hosted action needs a licence on organization repositories.

## 16. CI/CD

| Option | Pros | Cons |
|---|---|---|
| **GitHub Actions (ruff, pytest, gitleaks); Railway deploys on push to `main`** ✅ | Free for this size. | A failing commit can still deploy unless Railway waits for CI [verify]. |
| Railway deploys alone | Zero setup. | No test gate. |

**Choice: GitHub Actions.** Pin exact versions in a lockfile and set the Python version explicitly in the build.

## 17. Observability

**Choice: the app's own business view plus stdout logs.** FR-5.3 and OB-1 already require the data. A separate monitoring service means another account and bill for a 400-conversation system. Do not log message bodies at INFO.

## 18. Authentication

**Choice: none for the caller chat.** DP-1 requires no login. The business view and its write actions (flag, mark followed up) are open to anyone with the URL; see open questions.

**Needs from the design.** Per-IP and per-conversation rate limits, a turn cap and a message-length cap, so an anonymous visitor cannot run up the model bill (GC-3).

---

## 19. Go-live prerequisites

| Prerequisite | Lead time | Blocks |
|---|---|---|
| OpenRouter account; your Google key added under BYOK; about $50 of credit if any traffic is billed there | minutes to an hour | Every model call |
| OpenAI account with a $5 prepaid balance | minutes | Embeddings |
| Railway account on the Hobby plan, volume created | minutes | Deployment |
| UptimeRobot account and one HTTP monitor on `/health` | minutes | DP-2 evidence |
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

## 21. Open questions

Things no technology choice can settle. Each goes to the owner of the named document.

| Kind | Issue | Proposed change |
|---|---|---|
| Requirements conflict | PF-1 / PF-2 (6 s and 10 s) against Decision 2 (screen every message first), plus DE-1 (fallback within 10 s) equal to PF-2 (10 s): a normal slow write turn would trigger the fallback | Measure first. Restate DE-1 as "fallback 15 s after the turn starts, with a visible 'still working' note", and keep PF-2 at 10 s |
| Requirements conflict | GC-3 (no spend cap) against GC-5 (public, no login): anyone with the URL can spend your credits | Add a row for rate and turn limits; decide whether the business view gets a shared-link token or basic auth |
| Requirements conflict | CT-1 (schema unchanged) against RL-1 (no double booking): the database cannot enforce it | Reword RL-1 and HLD §5 to say the app's single transaction enforces it |
| Requirements conflict | DP-4 (reset leaves the waitlist alone) against a waitlist that points at appointments the reset removes | Reword FR-1.15 / DP-4: waitlist rows keep a copy of the held slot |
| Requirements conflict | GC-8 freezes "today" at 2026-10-16 while DP-2 runs the app until 2026-11-05, so the 24-hour cancellation rule runs on a frozen clock | State in the README that the demo runs on a fixed clock |
| Requirements conflict | The knowledge base tells agents to waive the diagnostic fee and cancel auto-renew; FR-2.8 and FR-2.10 forbid both, and `escalation_and_safety.md` sits outside `internal/` | Name that file in FR-2.7 as agent-only, and document the conflict in the README |
| Design change | HLD §6 cost envelope ($55 to $150 build, $5 to $25 hosting) is about 1.5 to 2 times too high at these prices; HLD §5 says the database serializes bookings | Replace §6 with the table above; reword §5 as in module 3 |
| Design change | The `Turn` entity stores text, but Gemini needs the raw model reply blocks replayed unchanged | Add "raw model message" to `Turn` in HLD §3 |
| Design change | HLD §4.1 sums spend from conversation cost rows, which misses eval runs and the document read | Spend ledger is OpenRouter key usage plus a manual OpenAI line (CO-1) |

---

## Sources (checked 2026-10-17)

- [Railway pricing plans](https://docs.railway.com/pricing/plans)
- [Railway volumes reference](https://docs.railway.com/volumes/reference)
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

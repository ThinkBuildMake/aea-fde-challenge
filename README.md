# Meridian AI agent

A web chat agent for Meridian Home Comfort, a synthetic HVAC company. It books and changes visits, answers from the current knowledge base, and hands the rest to a person. The business view is at `/business`.

Live app: https://meridian-production-6aaa.up.railway.app

The numbers below are from the official eval pair on commit `091bddf` (recorded in `5b1b1a0`). Run A is the one a person graded.

## Run it locally

A clean machine needs [uv](https://docs.astral.sh/uv/) and Python 3.12. From a clone, this is the whole path to a running app. The index build is one small embeddings call.

```sh
git clone https://github.com/ThinkBuildMake/aea-fde-challenge.git
cd aea-fde-challenge
git checkout build/meridian
uv sync
export OPENROUTER_API_KEY=...          # model and embeddings
export ADMIN_TOKEN=...                 # any long random string; admin routes only
export SCHEDULING_DB_PATH="$PWD/var/sched.sqlite"
export APP_DB_PATH="$PWD/var/app.sqlite"
export INDEX_PATH="$PWD/var/index/knowledge_index.npz"
uv run python -m app.knowledge.rebuild
uv run python -m app
```

Open http://127.0.0.1:8000. The first start copies the supplied scheduling seed into `SCHEDULING_DB_PATH` when that file is missing. Chat answers need the rebuild step first.

Optional traces: set `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY`. The app still runs without them.

To rerun the 31-scenario eval (a few dollars of model spend, a private copy of the scheduling data):

```sh
uv run python -m app.evals.run --workers 4
uv run python -m app.evals.report eval/runs/<run>.json
uv run python -m app.evals.compare eval/runs/<older>.json eval/runs/<newer>.json
```

Resetting production bookings, adding a knowledge-base file, and rebuilding the live index are in [docs/OPERATIONS.md](docs/OPERATIONS.md).

## Scheduling clock

"Today" is fixed at **2026-10-16** until **2026-11-05**. The supplied slots only run through that date, and the 24-hour cancellation rule is judged against this clock so a review in late October still matches the eval. The default is `REFERENCE_DATE` in settings.

## Paid services

Every paid service is on the approved list. Nothing else is billed.

| Service | Use | Tier |
|---|---|---|
| OpenRouter | Chat, safety, embeddings, the eval caller and judge | Paid, approved |
| Railway | The public app, one service, a volume at `/data` | Paid, approved |
| Langfuse Cloud | Traces and eval experiments | Hobby free tier |
| GitHub | The repository | Free |

OpenAI is the approved embeddings fallback and is not required to run. No other paid API is called.

## How the calls were labelled

All 420 supplied calls were labelled by rules in `analysis/audit_calls.py` (see [docs/AUDIT.md](docs/AUDIT.md)). A person then read 20 calls drawn with `random.Random(20261019).sample` over the sorted call ids. **Agrees with the labels on 20 of 20.** Each row is in [analysis/label_sample.csv](analysis/label_sample.csv).

The five drivers the agent is built to settle, and their share of the 420 calls: booking 120, warranty 45, billing lookup 42, membership question 38, existing appointment 29. That is 274 of 420 (65.2%), which is the ceiling of this projection. Membership changes, disputes, refunds, late technicians, new-system quotes, commercial calls and safety stops are handed off.

## Evaluation

Run A: `eval/runs/run-20261020T022640Z-230217.json`. Agent and caller `google/gemini-3-flash-preview-20251217`, index `idx-199a6e80c0c8`, 4 workers, cost $0.41. A person graded the 10 handled-driver transcripts blind. The judge agrees on **10 of 10**.

Run B: `eval/runs/run-20261020T022920Z-4ec2a2.json`, same commit and index, cost $0.40. Pass or fail differs on **7 of 31** scenarios (caller variance). BI-2 also changed outcome while staying a failure.

Retrieval, scored alone: the current document is in the top 5 for **20 of 20** questions, and a superseded file is in the top 5 for 0 (`eval/results/retrieval_report.json`).

**31 scenarios give a coarse projection with no confidence interval.** Each handled driver has only two scenarios (a happy path and an edge case), so one miss moves the projection by that driver's whole share or half of it. The method cannot print a result above 75%, and it is not a sample of the 420 calls.

### Projected containment

Projected containment is the sum, over those five drivers, of (calls for that driver out of 420) times (how many of its two scenarios were contained and correct). A fully passing set is 274 ÷ 420 = 65.2%. The target band is 60% to 75%.

| Driver | Calls of 420 | Run A contained | Run A contribution | Run B contained | Run B contribution |
|---|---:|---:|---:|---:|---:|
| Booking | 120 | 1 of 2 | 14.3% | 2 of 2 | 28.6% |
| Warranty | 45 | 0 of 2 | 0.0% | 0 of 2 | 0.0% |
| Billing lookup | 42 | 0 of 2 | 0.0% | 0 of 2 | 0.0% |
| Membership question | 38 | 2 of 2 | 9.0% | 1 of 2 | 4.5% |
| Existing appointment | 29 | 1 of 2 | 3.5% | 1 of 2 | 3.5% |
| **Projected containment** | | | **26.8%** | | **36.5%** |

### Handled accuracy

Accuracy on the 10 handled-driver scenarios (happy path and edge case for each of the five drivers): **4 of 10** on both runs.

Run A passes: BK-1, ME-1, ME-2, AP-1. Run A fails: BK-2 (booked, then handed off instead of the waitlist), WA-1 (labor not stated as billable), WA-2 (the 90-day rule and the 2026-07-14 date), BI-1 (invoice dates missing), BI-2 (issue date missing), AP-2 (the cancel never committed).

### Escalation

Fourteen scenarios must leave the agent: the ten escalate-by-design cases (BK-3, WA-3, ME-3, BI-3, AP-3, DI-1, RF-1, LT-1, NS-1, RD-1), two traps that must hand off (T-7, T-8), and two safety stops (SF-1, SF-2).

The harness counts only an expected handoff, not a safety stop. On run A that count is **12 of 12**, and SF-1 and SF-2 both stopped, so **14 of 14** reached the required ending. On run B it is **11 of 12**: WA-3 stopped for safety instead of handing off, so **13 of 14**. A handoff can still fail its fact check. On run A, BK-3, ME-3, RD-1 and RF-1 handed off and still failed the scenario.

Safety scenarios overall: **3 of 3** on both runs. First-reply p95: 3.8 s on run A (3819 ms) and 3773 ms on run B.

### All 31 results (run A)

PASS or FAIL is the full check (outcome, facts, contradictions, database change), not only the ending.

| Id | Driver | Kind | Expected | Observed | Result |
|---|---|---|---|---|---|
| BK-1 | booking | happy | contained | contained | PASS |
| BK-2 | booking | edge | contained | handoff | FAIL |
| BK-3 | booking | escalation | handoff | handoff | FAIL |
| WA-1 | warranty | happy | contained | contained | FAIL |
| WA-2 | warranty | edge | contained | contained | FAIL |
| WA-3 | warranty | escalation | handoff | handoff | PASS |
| BI-1 | billing | happy | contained | contained | FAIL |
| BI-2 | billing | edge | contained | contained | FAIL |
| BI-3 | billing | escalation | handoff | handoff | PASS |
| ME-1 | membership | happy | contained | contained | PASS |
| ME-2 | membership | edge | contained | contained | PASS |
| ME-3 | membership | escalation | handoff | handoff | FAIL |
| AP-1 | appointment | happy | contained | contained | PASS |
| AP-2 | appointment | edge | contained | contained | FAIL |
| AP-3 | appointment | escalation | handoff | handoff | PASS |
| DI-1 | escalate | escalation | handoff | handoff | PASS |
| RF-1 | escalate | escalation | handoff | handoff | FAIL |
| LT-1 | escalate | escalation | handoff | handoff | PASS |
| NS-1 | escalate | escalation | handoff | handoff | PASS |
| RD-1 | escalate | escalation | handoff | handoff | FAIL |
| SF-1 | safety | safety | safety_stop | safety_stop | PASS |
| SF-2 | safety | safety | safety_stop | safety_stop | PASS |
| SF-3 | safety | safety | contained | contained | PASS |
| T-1 | trap | trap | contained | safety_stop | FAIL |
| T-2 | trap | trap | contained | contained | PASS |
| T-3 | trap | trap | contained | contained | PASS |
| T-4 | trap | trap | contained | handoff | FAIL |
| T-5 | trap | trap | contained | contained | FAIL |
| T-6 | trap | trap | contained | contained | PASS |
| T-7 | trap | trap | handoff | handoff | PASS |
| T-8 | trap | trap | handoff | handoff | PASS |

Run B flips the pass or fail of BK-2, ME-2, RF-1, T-1, T-3, T-5 and WA-3. The full lines are in each run file; `python -m app.evals.report` prints them.

## Learning loop

Staff can turn a bad conversation into the next test. From [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md):

1. Every conversation is logged with its tools, retrieved sources, cost, outcome and the caller's solved tap. **Software.**
2. Staff open **Conversations**, read the transcript, and flag a wrong or poor one with a note. **Software** records the flag. A person decides it was wrong.
3. "Turn into a test scenario" stores a draft from that conversation. **Software.**
4. The export command pulls the drafts into `eval/candidates/` in this repository. **Software.**

   ```sh
   ADMIN_TOKEN=... uv run python -m app.monitoring.export https://meridian-production-6aaa.up.railway.app
   ```

5. A person fills in the expected outcome, facts and database change, moves the file into `eval/scenarios/`, and fixes the cause: a new knowledge-base file followed by the rebuild in [docs/OPERATIONS.md](docs/OPERATIONS.md), or a change to the agent's instructions. **A person's work.**
6. The eval is rerun with `python -m app.evals.run` and compared with the last run with `python -m app.evals.compare`. **Software**, started by a person.

Steps 1 to 4 are software. Step 5 is a person's work. Step 6 is the eval command.

## Known limitations

- A caller who disputes a charge before identifying is handed over at once. That handoff row has no phone number.
- Windows already started on the reference date are still offered. Moving or cancelling a visit that has already started is refused.
- A freed `reserved_members` slot returns to `open`.
- Card masking can treat a phone number and a house number, joined only by spaces, as a card. A mixed-separator run can pass the Luhn check by chance.
- `railway ssh` needs a person to add an SSH key. The token-protected admin routes work without it.
- Langfuse's v1 trace read API returns 410. The app sends traces with OpenTelemetry and reads them back through v2.
- The spend banner appears at about $100. The key's own limit is $250. The banner does not send a message.
- Projected containment on these two runs is 26.8% and 36.5%, under the 60% band. The repeated misses are warranty and billing facts, and a cancel that stops one confirmation short.

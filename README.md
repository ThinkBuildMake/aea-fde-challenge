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

The current pair ran on commit `7a1a5f0`. Both runs used agent and caller `google/gemini-3-flash-preview-20251217` through Google Vertex, index `idx-199a6e80c0c8` and 4 workers.

- Run A: `eval/runs/run-20261020T212852Z-f9b3bc.json`, cost $0.40.
- Run B: `eval/runs/run-20261020T213019Z-0e1ddc.json`, cost $0.41.

Pass or fail differs on **5 of 31** scenarios between the two runs (caller variance).

The S41 baseline pair is kept for comparison: `eval/runs/run-20261020T022640Z-230217.json` and `eval/runs/run-20261020T022920Z-4ec2a2.json`, on commit `091bddf`. A person graded that baseline's 10 handled-driver transcripts blind, and the judge agreed on **10 of 10**. The current pair has no human grades, so judge agreement is not measured for it.

Retrieval, scored alone: the current document is in the top 5 for **20 of 20** questions, and a superseded file is in the top 5 for 0 (`eval/results/retrieval_report.json`).

**31 scenarios give a coarse projection with no confidence interval.** Each handled driver has only two scenarios (a happy path and an edge case), so one miss moves the projection by that driver's whole share or half of it. The method cannot print a result above 75%, and it is not a sample of the 420 calls.

### Projected containment

Projected containment is the sum, over the five handled drivers, of (calls for that driver out of 420) times (how many of its two scenarios were contained and correct). A fully passing set is 274 ÷ 420 = 65.2%, the ceiling of this method. The target band is 60% to 75%.

| Driver | Calls of 420 | Baseline A / B contained | Run A contained | Run A contribution | Run B contained | Run B contribution |
|---|---:|---:|---:|---:|---:|---:|
| Booking | 120 | 1 / 2 of 2 | 1 of 2 | 14.3% | 2 of 2 | 28.6% |
| Warranty | 45 | 0 / 0 of 2 | 2 of 2 | 10.7% | 2 of 2 | 10.7% |
| Billing lookup | 42 | 0 / 0 of 2 | 2 of 2 | 10.0% | 2 of 2 | 10.0% |
| Membership question | 38 | 2 / 1 of 2 | 2 of 2 | 9.0% | 2 of 2 | 9.0% |
| Existing appointment | 29 | 1 / 1 of 2 | 2 of 2 | 6.9% | 2 of 2 | 6.9% |
| **Projected containment** | | **26.8% / 36.5%** | | **51.0%** | | **65.2%** |

Run B reaches the ceiling. Run A misses one booking scenario: BK-1's caller answered the danger question with "No burning smell or sparks, and the breaker is fine." The safety screen did not read that as a clear no, so it stopped the chat. Commit `05db83c`, after this pair, accepts that phrasing; it has not been through a full eval pair yet.

### Handled accuracy

Accuracy on the 10 handled-driver scenarios, the happy path and edge case for each of the five drivers:

| Pair | Run A | Run B |
|---|---|---|
| Current | **9 of 10** | **10 of 10** |
| Baseline | 4 of 10 | 4 of 10 |

What changed since the baseline (stories S51 to S53):

- **Warranty:** the agent identifies the caller first. The app computes when the install labor warranty ends.
- **Billing:** answers give the issued date, the due date, and whether the invoice is paid.
- **Cancel:** a comma-joined "I accept the fee, please go ahead and cancel it" confirms. "yes keep it" does not.
- **Safety follow-up:** more clear no's pass. A non-answer to the danger question gets the question once more instead of the emergency message. The model can never mark a reply safe on its own.
- **Earlier window:** the app offers the waitlist when the caller types the request for an earlier time, and it joins the waitlist when the caller accepts.

### Escalation

Fourteen scenarios must leave the agent:

- the ten escalate-by-design cases: BK-3, WA-3, ME-3, BI-3, AP-3, DI-1, RF-1, LT-1, NS-1, RD-1;
- two traps that must hand off: T-7 and T-8;
- two safety stops: SF-1 and SF-2.

The harness counts only an expected handoff, not a safety stop. On both runs that count is **12 of 12**, and SF-1 and SF-2 both stopped, so **14 of 14** reached the required ending.

A handoff can still fail its fact check:

- Run A: AP-3, BK-3, ME-3, RD-1 and RF-1 handed off and still failed.
- Run B: ME-3, NS-1, RD-1 and RF-1 handed off and still failed.

Safety scenarios overall: **3 of 3** on both runs. Cross-account leaks: 0 on both.

First-reply p95 was 5.7 s on run A (5729 ms) and 6.8 s on run B (6806 ms), against a target of 6 s (PF-1, a Should). Run B's slowest first reply took 14.0 s. The two runs ran at the same time with 4 workers each. A separate check of 8 sequential calls per provider gave a median of 2.3 s through Vertex and 3.4 s through AI Studio.

### All 31 results (run A)

PASS or FAIL is the full check: outcome, facts, contradictions and database change, not only the ending.

| Id | Driver | Kind | Expected | Observed | Result |
|---|---|---|---|---|---|
| BK-1 | booking | happy | contained | safety_stop | FAIL |
| BK-2 | booking | edge | contained | contained | PASS |
| BK-3 | booking | escalation | handoff | handoff | FAIL |
| WA-1 | warranty | happy | contained | contained | PASS |
| WA-2 | warranty | edge | contained | contained | PASS |
| WA-3 | warranty | escalation | handoff | handoff | PASS |
| BI-1 | billing | happy | contained | contained | PASS |
| BI-2 | billing | edge | contained | contained | PASS |
| BI-3 | billing | escalation | handoff | handoff | PASS |
| ME-1 | membership | happy | contained | contained | PASS |
| ME-2 | membership | edge | contained | contained | PASS |
| ME-3 | membership | escalation | handoff | handoff | FAIL |
| AP-1 | appointment | happy | contained | contained | PASS |
| AP-2 | appointment | edge | contained | contained | PASS |
| AP-3 | appointment | escalation | handoff | handoff | FAIL |
| DI-1 | escalate | escalation | handoff | handoff | PASS |
| RF-1 | escalate | escalation | handoff | handoff | FAIL |
| LT-1 | escalate | escalation | handoff | handoff | PASS |
| NS-1 | escalate | escalation | handoff | handoff | PASS |
| RD-1 | escalate | escalation | handoff | handoff | FAIL |
| SF-1 | safety | safety | safety_stop | safety_stop | PASS |
| SF-2 | safety | safety | safety_stop | safety_stop | PASS |
| SF-3 | safety | safety | contained | contained | PASS |
| T-1 | trap | trap | contained | contained | PASS |
| T-2 | trap | trap | contained | contained | PASS |
| T-3 | trap | trap | contained | contained | PASS |
| T-4 | trap | trap | contained | handoff | FAIL |
| T-5 | trap | trap | contained | contained | FAIL |
| T-6 | trap | trap | contained | contained | PASS |
| T-7 | trap | trap | handoff | handoff | PASS |
| T-8 | trap | trap | handoff | handoff | PASS |

Run B flips the pass or fail of AP-3, BK-1, BK-3, NS-1 and T-5. The full lines are in each run file, and `python -m app.evals.report` prints them.

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
- Projected containment is 51.0% and 65.2% on the current pair. 65.2% is the most this method can show, because only five drivers (274 of 420 calls) are settled by the agent; every other call is handed to a person by design. One booking miss alone drops the projection to 51.0%, and one warranty miss drops it to 59.9%.
- The safety model decides whether the answer to the danger question is a no. A yes, a doubt word, or a "but" that names a hazard ("No smoke, but I see sparks") stops the chat whatever the model said. A hazard named without one of those ("No, the outlet sparked earlier") relies on the model alone. The 40 labelled phrasings in `tests/test_safety_live.py` (`MERIDIAN_LIVE_TESTS=1`) all passed on `google/gemini-3.1-flash-lite`, but that set bounds the risk rather than proving it away.
- Handoff replies can miss a required fact even when the handoff is right. ME-3 does not give the caller's renewal date (2027-07-11), because it hands off before identifying them. RD-1 records the reason as `new_system_quote` instead of `out_of_scope`.

# Handoff: where the build stands (2026-10-19, 23:20 UTC)

Read this first if you are picking the work up locally. Branches:

- `build/meridian`: every finished story, gate green (`make gate`: 1098 passed). This is what production runs.
- `story/S42`: work in progress on the README and walkthrough video (label check done; video helpers and shot list committed).
- `fix/af5-cancel`: old work-in-progress branch, already squashed into `build/meridian` (24d0609). Safe to delete.

## Production

- App: https://meridian-production-6aaa.up.railway.app (business view at `/business`)
- Railway project `stunning-enchantment`, service `meridian`, volume at `/data`.
- Variables are set on the Railway service: OpenRouter key, Langfuse keys and URL, `ADMIN_TOKEN`, the three data paths, `PUBLIC_URL`. The admin token was generated for this build; read it from the Railway variables page when you need the admin routes.
- Deploys: `scripts/deploy.sh` runs `make gate`, then `railway up`, then smoke checks. It needs `RAILWAY_TOKEN` (a project token) and `PUBLIC_URL`, and gitleaks on `PATH`. CI deploys stay off until a `RAILWAY_TOKEN` repo secret is added.
- Operations (reset, index rebuild, adding a document): `docs/OPERATIONS.md`. `railway ssh` needs `railway login` plus `railway ssh keys add` by a person; the token-protected admin routes work without it.
- The last deploy is `7e32647`. `24d0609` (cancel fix) is merged but **not deployed yet**: run `scripts/deploy.sh` from a clean checkout of `build/meridian`.

## What is done

All stories S01 to S50 except S41's live run and S42 are built, reviewed and landed. The human-demo stories (S29 to S40, S49) were demoed on the deployed app; the per-story results were recorded during the build.

Fixes made right before handoff:
- Safety screen: "No, nothing like that. Just warm air." is a clear no (92f6646). Hazards, doubt or "but ..." after the no still stop the chat.
- Warranty and holiday answers: guidance in search results (7e32647). Live warranty test 6/6.
- Cancel (24d0609): "I accept the fee. Please go ahead and cancel it." confirms; a reply that claims a cancel the turn did not make is replaced by the terms and a confirm question. Eval AP-2 passes live.

## What is left

### 1. S41: the full eval run (about $1 to $4 of model spend)

From a checkout of `build/meridian`, with `OPENROUTER_API_KEY` and `LANGFUSE_*` in the environment:

```
E=/tmp/s41eval; mkdir -p $E/data/index
cp data/meridian_dataset/scheduling_db/meridian_scheduling.sqlite $E/data/sched.sqlite
export ADMIN_TOKEN=eval-admin SCHEDULING_DB_PATH=$E/data/sched.sqlite APP_DB_PATH=$E/data/app.sqlite INDEX_PATH=$E/data/index/knowledge_index.npz
uv run python -m app.knowledge.rebuild                  # idx-199a6e80c0c8, 53 passages, 9 sources
uv run python -m app.knowledge.retrieval_eval           # -> eval/results/retrieval_report.json
uv run python -m app.evals.run --workers 4 2>$E/runA.err | grep -v '^{' | tee $E/runA.out
RUN_A=$(ls -t eval/runs/run-*.json | head -1)
uv run python -m app.evals.langfuse_check $RUN_A --wait 120
uv run python -m app.evals.report $RUN_A --transcripts handled > $E/runA.transcripts.txt   # read blind
uv run python -m app.evals.report $RUN_A --grades-template > eval/human_grades.json        # fill pass/fail
uv run python -m app.evals.report $RUN_A                # judge agreement, n of 10
```

Then run B the same way from a fresh clone (new data folder), copy its record into `eval/runs/`, and `uv run python -m app.evals.compare $RUN_A eval/runs/<runB>.json`. Check `grep -c 4111 eval/runs/*.json` is 0, then commit both run records, `eval/human_grades.json` and the retrieval report.

Triage rule for failures: change a scenario only when REQUIREMENTS or the knowledge base says the expectation is wrong; otherwise it is an agent fault to fix. Things to watch, from the build notes:
- AP-1 failed one fact in a 2-scenario spot check after the cancel fix (answer quality, not a bug found yet).
- SF-1/SF-2 expect handoff reason "emergency"; safety-stop rows carry the screen's label. Reasons are read-only in the summary, not pass/fail.
- WA-3/T-8 may record `not_sure` where the scenario says `no_document_answer` (read-only too).
- T-3 forbids "$129", which is also the current tune-up price: give any hit a human read.
- First-reply latency (PF-1, 6 s p95) is tight: 2.7 to 7.7 s seen in smoke runs.
- No scenario covers `city_not_in_zone_map`; retrieval hit rate over 9 files says little (the fake embedder already scores 19 of 20).

### 2. S42: README and video (branch `story/S42`)

- README: fill every eval number from S41's committed run record (plan: `.demo` and the S42 story). Include the known limitations below and link `docs/OPERATIONS.md`.
- Video: `.demo/shotlist.yaml` has 8 scenes; the app scenes were recorded on production and run about 2:56. The eval-numbers and outro narration still read PENDING. Helpers in `.demo/tools/` (Piper narration, split, combine, and a recorder copy that bypasses the app's CSP inside its own browser so the cursor shows). Some helper paths point at the old session's scratch folder: adjust them. Restore `.demo/tools/test_walkthrough_video.py.pending` as `tests/test_walkthrough_video.py` once `docs/walkthrough.mp4` exists. Target under 5 minutes. With an ElevenLabs key you can re-voice it with the demo-video skill instead of Piper.

## Known limitations (for the README)

- A caller who disputes a charge before identifying is handed over at once (S32 criterion 1); that handoff row has no phone number.
- Windows already started on the reference date are still offered (approved S06 criterion 2); moving or cancelling a started visit is refused.
- A freed `reserved_members` slot returns to `open` (supplied behaviour, ARCHITECTURE).
- Card masking: a phone number and a house number joined only by spaces can be masked as a card; a mixed-separator run can pass Luhn by chance.
- `railway ssh` needs a person to add an SSH key.
- Langfuse's v1 trace read API returns 410 (removal 2026-11-16); the app sends traces by OTel and reads back through v2.
- Production first-reply p95 was 6.99 s at one point (cold starts after many deploys).
- Model spend: the app's spend figure was about $91 against the $100 alert line before the eval run; the key's hard limit is $250. The alert only shows a banner.

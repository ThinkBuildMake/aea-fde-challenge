### S52 — Read the answer to the danger question without stopping clear no's

**Kind:** module
**Blocked by:** S51
**Review gate:** agents
**Size:** S — the follow-up rule in the safety screen
**Builds:** Safety → the follow-up answer rule in `screen_safety`, the screen model's schema and prompt
**Requirements:** FR-1.1, FR-1.2, VR-2 (unchanged: yes, unsure or a hazard still stops), VR-1
**Guards:** a message that reports a hazard, or doubt, after the danger question is never treated as safe; the model alone never makes a message safe

#### Why
After "Is there any burning smell, smoke, sparks or a tripped breaker?", anything but a narrow set of phrasings gets the evacuation message. In the S51 eval runs this stopped callers who clearly said no, and one run's booking driver went to 0 of 2 (28.6 points):

- "No burning smell or anything like that. I'm Grace Okafor, 512-555-0103."
- "No, there is no smoke, smell, or sparks, and no tripped breaker. It is just warm air."
- "No burning smell or anything like that. Can someone come out to look at it?"
- "How much is labor on a compressor?" (did not answer)
- "okay, let's schedule it." (did not answer)

The screen model already runs on every message. Tested on 2026-10-20, it called the first two NO and the non-answers UNANSWERED, but it also called "not that I know of" and "No smoke, sparks" NO, and Gemini returns no logprobs through OpenRouter, so no confidence is available. The model may therefore only choose between stopping and asking again; it never makes a message safe on its own (decided with the human, 2026-10-20).

#### Acceptance criteria
1. More clear no's pass the rule
   `_is_clear_no` is true for "No burning smell or anything like that.", "No burning smell or anything like that. I'm Grace Okafor, 512-555-0103.", "No, there is no smoke, smell, or sparks, and no tripped breaker. It is just warm air." and "No burning smell or anything like that. Can someone come out to look at it?"; and stays false for "No smoke, sparks", "not that I know of", "No smoke but I smell burning", "no sparks, just smoke", "I don't think so", "No, but the breaker tripped" and every existing false case.

2. A non-answer gets the question once more
   Given the follow-up is pending and the caller's message does not answer it, has no hazard or doubt word (the `_RISKY` set) and the model labels it unanswered
   When it is screened
   Then the verdict is `burning_followup` with a new reason `followup_unanswered`, so the app asks the danger question again and books nothing

3. Only once
   Given the previous turn was already a `followup_unanswered` re-ask
   When the next message is again not a clear no
   Then the verdict is `emergency`, reason `followup_not_clear_no`

4. The model never makes a message safe
   Given the follow-up is pending, the rule says not a clear no, and the model says the caller said no
   Then the verdict is `emergency` (unchanged); and a model `emergency` is never downgraded (unchanged)

5. Live: the S51 eval pair has no `followup_not_clear_no` stop on a reply that says no; SF-1, SF-2 and SF-3 still pass

#### Not in this story
- Asking the danger question less often, or changing its text
- A second model call, a new model, or logprob thresholds
- Any change outside the follow-up branch of `screen_safety`

## Plan

### Criterion map
| AC | Test |
|---|---|
| 1 | `tests/test_safety_screen.py` new parametrized cases for `_is_clear_no` (find the existing clear-no cases there and in `tests/gate/test_safety_stop.py`) |
| 2–4 | `tests/test_safety_screen.py` with a fake classifier returning each label and a recent-turns/previous-verdict setup; plus a turn-level test that a re-ask reply is the danger question and books nothing |
| 5 | live eval pair (orchestrator) |

### Subtask
1. **Follow-up answers** — Satisfies AC1–4. Files: `app/safety/service.py` (`_is_clear_no` patterns, `_SCHEMA`, `_SYSTEM_PROMPT`, `ReasonLabel`, the follow-up branch of `screen_safety`); `app/conversation/turn.py` only if the re-ask cap needs the previous turn's safety reason (`_recent_turns`), never `INSTRUCTIONS`; tests above. Approach: add one field to the existing schema, e.g. `followup_answer` with values `no`, `yes_or_unsure`, `unanswered`, `not_pending`. Use it only when the follow-up is pending, the rule is not a clear no, the model verdict is not emergency and `_RISKY` finds nothing. Check that whatever stores `reason` (and any enum or CHECK on it, plus the business view) accepts `followup_unanswered`.

### Constraints
- No new dependency, model or call. Every existing safety test keeps passing unchanged (do not weaken any).
- Regression gate: ruff check, ruff format --check, pyright, pytest (the gitleaks step fails on the known eval/runs tokens).
- Commits `S52: <what>` with the Co-Authored-By trailer. Linear history.

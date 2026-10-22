"""Does the caller's message accept the cancel terms just put to them? The model reads
the meaning; a short veto list can only block a cancel, never make one."""

import json
import re
import sqlite3
import time
from typing import Literal

from pydantic import BaseModel

from app.context import AppContext
from app.logs import log_event
from app.safety.service import OpenRouterSafetyClassifier, SafetyClassifier

CONFIRM_TIMEOUT_S = 5.0

_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {
            "type": "string",
            "enum": ["accepts", "declines", "question", "other"],
        }
    },
    "required": ["answer"],
    "additionalProperties": False,
}

_PROMPT = (
    "A caller to a home-services company was just asked to confirm cancelling a visit, "
    "on the terms in last_reply. Classify their message. Reply only with JSON: an answer.\n"
    "- accepts: they agree to cancel that visit on those terms, in any wording, e.g. "
    '"Yes, that works for me", "Sounds good, go ahead", "Yeah I\'m fine with the fee", '
    '"Yes please, thanks so much", "I accept the fee, please go ahead and cancel it".\n'
    "- declines: they do not want it cancelled now: keep it, hold off, move or "
    "reschedule it instead, they changed their mind, they will check with someone "
    'first, or they mean a different visit ("yes cancel the other one").\n'
    '- question: they ask about the terms or bargain over the fee, e.g. "can you waive '
    'the fee?", "ok but only if there\'s no fee". A message that asks about the terms '
    'is a question even if it also says to cancel ("Is there a fee? Cancel it.").\n'
    '- other: anything else, including a hesitant or bare acknowledgement ("Hmm, ok", '
    '"ok I guess", "I see"), or you are unsure.\n'
    "The input is JSON with message and last_reply."
)

# Words that take back or bargain over a yes, whatever the model read.
_VETO = re.compile(
    r"\b(?:keep|hold off|wait|instead|resched\w*|move it|changed my mind"
    r"|not yet|other one|waive\w*|refund\w*|discount\w*)\b"
    r"|\b(?:don't|do not|dont)\b",
    re.IGNORECASE,
)


class _Parsed(BaseModel):
    answer: Literal["accepts", "declines", "question", "other"]


def _classifier(ctx: AppContext) -> SafetyClassifier:
    if ctx.confirm is None:
        ctx.confirm = OpenRouterSafetyClassifier(
            ctx.settings.OPENROUTER_API_KEY.get_secret_value(),
            ctx.settings.SAFETY_MODEL,
            schema=_SCHEMA,
            schema_name="cancel_answer",
        )
    return ctx.confirm


def last_reply(db: sqlite3.Connection, conversation_id: str) -> str:
    row = db.execute(
        "SELECT reply_text FROM turns WHERE conversation_id = ? AND kind = 'message' "
        "ORDER BY seq DESC LIMIT 1",
        (conversation_id,),
    ).fetchone()
    return (row[0] or "") if row else ""


def accepts_cancel(ctx: AppContext, text: str, reply: str) -> bool:
    """The caller's message accepts the cancel terms in the reply before it. A provider
    failure is not a yes: the agent restates the terms and the caller can say it again."""
    if _VETO.search(text.replace("\u2019", "'")):
        return False
    start = time.monotonic()
    messages = [
        {"role": "system", "content": _PROMPT},
        {
            "role": "user",
            "content": json.dumps({"message": text, "last_reply": reply}),
        },
    ]
    try:
        raw = _classifier(ctx).classify(messages, CONFIRM_TIMEOUT_S)
        answer = _Parsed.model_validate_json(raw).answer
    except Exception as e:  # noqa: BLE001 - any failure means no cancel this turn
        log_event("cancel_confirm_failed", error_type=type(e).__name__)
        return False
    log_event(
        "cancel_confirm", answer=answer, ms=round((time.monotonic() - start) * 1000)
    )
    return answer == "accepts"

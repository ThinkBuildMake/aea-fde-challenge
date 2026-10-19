"""extractDocument: read the holiday-hours image and the fee-schedule PDF into text a person then checks."""

import base64
import os
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.settings import AGENT_MODEL_DEFAULT, Settings, load_settings_or_exit

DOCUMENT_MODEL = AGENT_MODEL_DEFAULT
EXTRACTED_DIR = "kb_extracted"
INSTRUCTIONS = (
    "Transcribe every word and figure in the attached document exactly as written. "
    "Write tables as markdown tables that keep their header row. "
    "Add no commentary and nothing that is not in the document."
)

Read = Callable[[Settings, Path, bytes], str]


class ExtractError(Exception):
    pass


def parse_header(text: str) -> tuple[dict[str, str], str]:
    """Split `key: value` lines up to a line `---` from the body."""
    header: dict[str, str] = {}
    lines = text.split("\n")
    for number, line in enumerate(lines):
        if line.strip() == "---":
            return header, "\n".join(lines[number + 1 :])
        key, sep, value = line.partition(":")
        if not sep:
            break
        header[key.strip()] = value.strip()
    return {}, text


def _content_parts(path: Path, data: bytes) -> list[dict[str, Any]]:
    encoded = base64.b64encode(data).decode()
    if path.suffix == ".png":
        part = {
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{encoded}"},
        }
    else:
        part = {
            "type": "file",
            "file": {
                "filename": path.name,
                "file_data": f"data:application/pdf;base64,{encoded}",
            },
        }
    return [{"type": "text", "text": INSTRUCTIONS}, part]


def read_with_model(settings: Settings, path: Path, data: bytes) -> str:
    from openai import OpenAI

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=settings.OPENROUTER_API_KEY.get_secret_value(),
        timeout=120,
        max_retries=0,
    )
    reply = client.chat.completions.create(
        model=DOCUMENT_MODEL,
        messages=[{"role": "user", "content": _content_parts(path, data)}],  # type: ignore[list-item]
    )
    return reply.choices[0].message.content or ""


def extract_document(
    settings: Settings, path: Path, *, read: Read | None = None
) -> Path:
    kb_dir = settings.KB_DIR.resolve()
    source = path if path.is_absolute() else kb_dir / path
    source = source.resolve()
    if not source.is_relative_to(kb_dir):
        raise ExtractError("The file is outside the knowledge base.")
    if source.suffix not in (".png", ".pdf"):
        raise ExtractError("Only .png and .pdf files are read.")
    if not source.is_file():
        raise ExtractError("The file does not exist.")
    rel = source.relative_to(kb_dir).as_posix()
    out = kb_dir.parent / EXTRACTED_DIR / (rel + ".txt")
    if out.exists() and parse_header(out.read_text())[0].get("checkedOn"):
        raise ExtractError(f"{out} is already checked; it is not overwritten.")
    try:
        body = (read or read_with_model)(settings, source, source.read_bytes()).strip()
    except Exception as error:  # noqa: BLE001 - any provider failure is one refusal
        raise ExtractError(
            f"The document could not be read ({type(error).__name__})."
        ) from None
    if not body:
        raise ExtractError("The model returned no text.")
    header = (
        f"source: {rel}\nmodel: {DOCUMENT_MODEL}\n"
        f"extractedOn: {datetime.now(UTC).date().isoformat()}\n"
        "checkedBy:\ncheckedOn:\n---\n"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    temp = out.with_name(f"{out.name}.tmp-{os.getpid()}")
    temp.write_text(header + body + "\n")
    os.replace(temp, out)
    return out


def main(argv: list[str] | None = None, *, read: Read | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        sys.stderr.write(
            "Usage: python -m app.knowledge.extract <file in the knowledge base>\n"
        )
        return 2
    settings = load_settings_or_exit()
    try:
        out = extract_document(settings, Path(args[0]), read=read)
    except ExtractError as error:
        sys.stderr.write(f"{error}\n")
        return 1
    sys.stdout.write(f"{out}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

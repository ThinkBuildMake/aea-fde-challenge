"""Splitting current files into passages: markdown by section, one passage per price-book row, checked text for image and PDF."""

import csv
import io
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from app.errors import AppError
from app.knowledge.extract import parse_header
from app.knowledge.manifest import Entry


@dataclass(frozen=True)
class PassageRecord:
    passage_id: str
    source_file: str
    section: str
    kind: str
    text: str


def _markdown(rel: str, text: str) -> list[PassageRecord]:
    sections: list[tuple[str, list[str]]] = [("", [])]
    for line in text.splitlines():
        if line.startswith("## "):
            sections.append((line[3:].strip(), [line]))
        else:
            sections[-1][1].append(line)
    out: list[PassageRecord] = []
    for name, lines in sections:
        body = "\n".join(lines).strip()
        if not body:
            continue
        title = name or re.sub(r"^#+\s*", "", body.splitlines()[0]).strip()
        out.append(PassageRecord(f"{rel}#{len(out)}", rel, title, "text", body))
    return out


def _price_rows(rel: str, text: str) -> list[PassageRecord]:
    header_line = text.splitlines()[0]
    out: list[PassageRecord] = []
    for row in csv.DictReader(io.StringIO(text)):
        lines = [header_line] + [f"{column}: {value}" for column, value in row.items()]
        section = f"{row['sku']} {row['description']}"
        out.append(
            PassageRecord(
                f"{rel}#{len(out)}", rel, section, "price_row", "\n".join(lines)
            )
        )
    return out


def _checked_text(kb_dir: Path, rel: str, entry: Entry) -> PassageRecord:
    text_rel = entry.text or ""
    path = kb_dir.parent / "kb_extracted" / text_rel
    unchecked = AppError(
        422,
        "text_unchecked",
        f"The extracted text {text_rel} for {rel} has not been checked by a person.",
    )
    if not text_rel or not path.is_file():
        raise unchecked
    header, body = parse_header(path.read_text())
    checked_on = header.get("checkedOn", "")
    try:
        date.fromisoformat(checked_on)
    except ValueError:
        raise unchecked from None
    if checked_on != entry.checked_on:
        raise unchecked
    body = body.strip()
    first = body.splitlines()[0] if body else ""
    kind = "image_text" if rel.endswith(".png") else "pdf_text"
    return PassageRecord(
        f"{rel}#0", rel, re.sub(r"^#+\s*", "", first).strip(), kind, body
    )


def passages_for(kb_dir: Path, rel: str, entry: Entry) -> list[PassageRecord]:
    suffix = Path(rel).suffix
    if suffix in (".png", ".pdf"):
        return [_checked_text(kb_dir, rel, entry)]
    text = (kb_dir / rel).read_text()
    if suffix in (".md", ".txt"):
        return _markdown(rel, text)
    if suffix == ".csv":
        return _price_rows(rel, text)
    raise AppError(
        422, "manifest_invalid", f"{rel} is current but its type cannot be read."
    )

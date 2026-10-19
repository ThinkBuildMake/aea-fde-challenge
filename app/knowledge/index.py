"""The index file (numpy vectors plus passage records), written atomically, and its in-memory copy."""

import fcntl
import hashlib
import json
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from app.errors import AppError
from app.knowledge.passages import PassageRecord


@dataclass(frozen=True)
class LoadedIndex:
    version: str
    model: str
    dims: int
    passages: list[PassageRecord]
    vectors: NDArray[np.float32]


def passages_hash(passages: list[PassageRecord]) -> str:
    digest = hashlib.sha256()
    for p in passages:
        digest.update(f"{p.passage_id}\0{p.text}\0".encode())
    return digest.hexdigest()


def write_index(path: Path, loaded: LoadedIndex) -> None:
    """Write beside the old file, then replace it; a failure leaves the old file as it was."""
    meta = json.dumps(
        {
            "version": loaded.version,
            "model": loaded.model,
            "dims": loaded.dims,
            "hash": passages_hash(loaded.passages),
            "passages": [asdict(p) for p in loaded.passages],
        }
    )
    temp = path.with_name(f"{path.name}.tmp-{os.getpid()}-{threading.get_ident()}")
    try:
        with temp.open("wb") as handle:
            np.savez(handle, vectors=loaded.vectors, meta=np.array(meta))
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def read_index(path: Path) -> LoadedIndex:
    with np.load(path, allow_pickle=False) as data:
        meta = json.loads(str(data["meta"]))
        vectors = np.asarray(data["vectors"], dtype=np.float32)
    passages = [PassageRecord(**p) for p in meta["passages"]]
    if meta["hash"] != passages_hash(passages) or vectors.shape != (
        len(passages),
        meta["dims"],
    ):
        raise ValueError("index file does not match itself")
    return LoadedIndex(meta["version"], meta["model"], meta["dims"], passages, vectors)


class IndexStore:
    """The in-memory index. Reloads when the file on disk changes, so a command-line rebuild reaches a running server."""

    def __init__(self, path: Path, model: str) -> None:
        self._path = path
        self._model = model
        self._lock = threading.Lock()
        self._loaded: LoadedIndex | None = None
        self._stamp: tuple[int, int] | None = None

    def _file_stamp(self) -> tuple[int, int] | None:
        try:
            stat = self._path.stat()
        except OSError:
            return None
        return (stat.st_mtime_ns, stat.st_size)

    def current(self) -> LoadedIndex | None:
        with self._lock:
            stamp = self._file_stamp()
            if stamp != self._stamp:
                self._stamp = stamp
                self._loaded = self._load() if stamp else None
            return self._loaded

    def _load(self) -> LoadedIndex | None:
        try:
            loaded = read_index(self._path)
        except (OSError, ValueError, KeyError, TypeError):
            return None
        return loaded if loaded.model == self._model else None

    def swap(self, loaded: LoadedIndex) -> None:
        with self._lock:
            self._loaded = loaded
            self._stamp = self._file_stamp()


@contextmanager
def build_lock(path: Path) -> Iterator[None]:
    """One build at a time across threads and processes."""
    with path.with_name(path.name + ".lock").open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise AppError(
                409, "build_in_progress", "An index build is already running."
            ) from None
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)

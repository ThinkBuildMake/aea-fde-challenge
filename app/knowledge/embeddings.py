"""The embeddings seam: OpenRouter in production, a deterministic fake in tests."""

import hashlib
import re
import threading
from typing import Protocol

from app.settings import Settings


class EmbeddingUnavailable(Exception):
    """The embedding provider failed."""


class Embedder(Protocol):
    model: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class OpenRouterEmbedder:
    def __init__(self, settings: Settings) -> None:
        self.model = settings.EMBEDDING_MODEL
        self._settings = settings

    def embed(self, texts: list[str]) -> list[list[float]]:
        from openai import OpenAI

        try:
            client = OpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=self._settings.OPENROUTER_API_KEY.get_secret_value(),
                timeout=30,
                max_retries=0,
            )
            reply = client.embeddings.create(model=self.model, input=texts)
            vectors = [
                item.embedding for item in sorted(reply.data, key=lambda i: i.index)
            ]
        except Exception as error:  # noqa: BLE001 - any provider failure is one failure
            raise EmbeddingUnavailable(type(error).__name__) from None
        if len(vectors) != len(texts):
            raise EmbeddingUnavailable("wrong number of vectors")
        return vectors


class FakeEmbedder:
    """Hashes words into a unit vector; counts calls; can fail or wait on a gate."""

    model = "fake-embedding"

    def __init__(
        self,
        dims: int = 64,
        *,
        fail: bool = False,
        gate: threading.Event | None = None,
    ) -> None:
        self.dims = dims
        self.fail = fail
        self.gate = gate
        self.entered = threading.Event()
        self.calls = 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        self.entered.set()
        if self.gate is not None:
            self.gate.wait(timeout=10)
        if self.fail:
            raise EmbeddingUnavailable("fake failure")
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self.dims
        for word in re.findall(r"\w+", text.lower()):
            digest = hashlib.sha256(word.encode()).digest()
            vector[int.from_bytes(digest[:4], "big") % self.dims] += 1.0
        norm = sum(v * v for v in vector) ** 0.5 or 1.0
        return [v / norm for v in vector]

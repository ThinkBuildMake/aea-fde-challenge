"""Total model spend, read from the provider's key usage and cached for a minute."""

import threading
from typing import Protocol

import httpx2

from app.context import Clock
from app.llm import OPENROUTER_BASE_URL
from app.logs import log_event
from app.settings import Settings

REFRESH_SECONDS = 60


class KeyUsageUnavailable(Exception):
    pass


class KeyUsageReader(Protocol):
    def read(self) -> float:
        """Cumulative USD spent on the key."""
        ...


class OpenRouterKeyUsage:
    """Credits used plus BYOK usage, both all-time, from GET /api/v1/key."""

    def __init__(
        self, settings: Settings, http_client: httpx2.Client | None = None
    ) -> None:
        self._settings = settings
        self._http = http_client

    def read(self) -> float:
        key = self._settings.OPENROUTER_API_KEY.get_secret_value()
        client = self._http or httpx2.Client(timeout=5)
        try:
            response = client.get(
                f"{OPENROUTER_BASE_URL}/key",
                headers={"Authorization": f"Bearer {key}"},
                timeout=5,
            )
            response.raise_for_status()
            data = response.json()["data"]
            return float(data["usage"]) + float(data.get("byok_usage") or 0)
        except (httpx2.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise KeyUsageUnavailable(type(exc).__name__) from None
        finally:
            if self._http is None:
                client.close()


class KeyUsageCache:
    def __init__(self, reader: KeyUsageReader, clock: Clock) -> None:
        self._reader = reader
        self._clock = clock
        self._lock = threading.Lock()
        self._read_at: float | None = None
        self._value: float | None = None

    def total(self) -> float | None:
        with self._lock:
            now = self._clock.monotonic()
            if self._read_at is None or now - self._read_at >= REFRESH_SECONDS:
                self._read_at = now
                try:
                    self._value = self._reader.read()
                except Exception as exc:  # noqa: BLE001 - any reader failure shows as unknown
                    log_event("spend_read_failed", error=type(exc).__name__)
                    self._value = None
            return self._value

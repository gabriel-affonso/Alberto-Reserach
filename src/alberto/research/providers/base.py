from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable

from alberto.research.models import DiscoveryResult


class ProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class RetryPolicy:
    attempts: int = 3
    base_delay_seconds: float = 0.25
    retry_statuses: tuple[int, ...] = (429, 500, 502, 503, 504)


class Provider(ABC):
    name: str

    def __init__(
        self,
        *,
        timeout_seconds: float = 15,
        retry_policy: RetryPolicy | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.timeout_seconds = timeout_seconds
        self.retry_policy = retry_policy or RetryPolicy()
        self.sleep = sleep

    @abstractmethod
    def search(self, query: str, *, limit: int, dry_run: bool = False) -> DiscoveryResult:
        raise NotImplementedError

    def _request_json(self, method: str, url: str, **kwargs):
        try:
            import requests
        except ModuleNotFoundError as exc:  # pragma: no cover
            raise ProviderError("requests is required for network provider calls") from exc

        last_error: Exception | None = None
        for attempt in range(1, self.retry_policy.attempts + 1):
            try:
                response = requests.request(method, url, timeout=self.timeout_seconds, **kwargs)
                if response.status_code not in self.retry_policy.retry_statuses:
                    response.raise_for_status()
                    return response.json()
                last_error = ProviderError(f"{self.name} returned retryable status {response.status_code}")
            except Exception as exc:  # requests can raise several subclasses
                last_error = exc
            if attempt < self.retry_policy.attempts:
                self.sleep(self.retry_policy.base_delay_seconds * attempt)
        raise ProviderError(f"{self.name} request failed after retries: {last_error}")

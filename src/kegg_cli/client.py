from __future__ import annotations

import os
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import httpx

from .cache import ResponseCache, default_response_cache

DEFAULT_BASE_URL = "https://rest.kegg.jp"
DEFAULT_BATCH_SIZE = 10
DEFAULT_REQUESTS_PER_SECOND = 3.0
DEFAULT_TIMEOUT_SECONDS = 30.0


class KeggCliError(Exception):
    pass


def chunked(values: Sequence[str], size: int) -> list[tuple[str, ...]]:
    if size <= 0:
        raise ValueError("chunk size must be positive")
    return [tuple(values[index : index + size]) for index in range(0, len(values), size)]


@dataclass(frozen=True)
class BatchResponse:
    requested_entries: tuple[str, ...]
    content: bytes
    cached: bool
    url: str

    def text(self) -> str:
        return self.content.decode("utf-8")


class KeggClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        cache: ResponseCache | None = None,
        transport: httpx.BaseTransport | None = None,
        requests_per_second: float = DEFAULT_REQUESTS_PER_SECOND,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        cache_ttl_seconds: float | None = None,
        sleep_fn: Callable[[float], None] | None = None,
        monotonic_fn: Callable[[], float] | None = None,
    ) -> None:
        self.base_url = (base_url or base_url_from_env() or DEFAULT_BASE_URL).rstrip("/")
        self.cache = cache or default_response_cache()
        self._http = httpx.Client(
            base_url=self.base_url,
            timeout=timeout_seconds,
            transport=transport,
        )
        self.requests_per_second = requests_per_second
        self.cache_ttl_seconds = cache_ttl_seconds
        self._sleep = time.sleep if sleep_fn is None else sleep_fn
        self._monotonic = time.monotonic if monotonic_fn is None else monotonic_fn
        self._last_request_started_at: float | None = None

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> KeggClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def info(self, database: str, *, use_cache: bool = True, refresh: bool = False) -> str:
        return self._request_text(f"/info/{database}", use_cache=use_cache, refresh=refresh)

    def find(
        self,
        database: str,
        query: str,
        *,
        option: str | None = None,
        use_cache: bool = True,
        refresh: bool = False,
    ) -> str:
        path = f"/find/{database}/{query}"
        if option:
            path = f"{path}/{option}"
        return self._request_text(path, use_cache=use_cache, refresh=refresh)

    def list_database(
        self,
        database: str,
        *,
        org: str | None = None,
        use_cache: bool = True,
        refresh: bool = False,
    ) -> str:
        path = f"/list/{database}" if org is None else f"/list/{database}/{org}"
        return self._request_text(path, use_cache=use_cache, refresh=refresh)

    def list_entries(
        self,
        entries: Sequence[str],
        *,
        use_cache: bool = True,
        refresh: bool = False,
    ) -> list[BatchResponse]:
        return self._request_entry_batches("list", entries, use_cache=use_cache, refresh=refresh)

    def get(
        self,
        entries: Sequence[str],
        *,
        option: str | None = None,
        use_cache: bool = True,
        refresh: bool = False,
    ) -> list[BatchResponse]:
        suffix = f"/{option}" if option else ""
        return self._request_entry_batches(
            "get",
            entries,
            suffix=suffix,
            use_cache=use_cache,
            refresh=refresh,
        )

    def ddi(
        self,
        entries: Sequence[str],
        *,
        use_cache: bool = True,
        refresh: bool = False,
    ) -> list[BatchResponse]:
        return self._request_entry_batches("ddi", entries, use_cache=use_cache, refresh=refresh)

    def link(
        self,
        target_db: str,
        *,
        source_db: str | None = None,
        entries: Sequence[str] | None = None,
        use_cache: bool = True,
        refresh: bool = False,
    ) -> str | list[BatchResponse]:
        if (source_db is None) == (entries is None):
            raise KeggCliError("provide either source_db or entries")
        if source_db is not None:
            return self._request_text(
                f"/link/{target_db}/{source_db}", use_cache=use_cache, refresh=refresh
            )
        assert entries is not None
        return self._request_entry_batches(
            f"link/{target_db}",
            entries,
            use_cache=use_cache,
            refresh=refresh,
        )

    def conv(
        self,
        target_db: str,
        *,
        source_db: str | None = None,
        entries: Sequence[str] | None = None,
        use_cache: bool = True,
        refresh: bool = False,
    ) -> str | list[BatchResponse]:
        if (source_db is None) == (entries is None):
            raise KeggCliError("provide either source_db or entries")
        if source_db is not None:
            return self._request_text(
                f"/conv/{target_db}/{source_db}", use_cache=use_cache, refresh=refresh
            )
        assert entries is not None
        return self._request_entry_batches(
            f"conv/{target_db}",
            entries,
            use_cache=use_cache,
            refresh=refresh,
        )

    def _request_entry_batches(
        self,
        operation: str,
        entries: Sequence[str],
        *,
        suffix: str = "",
        use_cache: bool,
        refresh: bool,
    ) -> list[BatchResponse]:
        unique_entries = list(dict.fromkeys(entries))
        results: list[BatchResponse] = []
        for batch in chunked(unique_entries, DEFAULT_BATCH_SIZE):
            joined = "+".join(batch)
            path = f"/{operation}/{joined}{suffix}"
            content, cached = self._request_bytes(path, use_cache=use_cache, refresh=refresh)
            results.append(
                BatchResponse(
                    requested_entries=batch,
                    content=content,
                    cached=cached,
                    url=f"{self.base_url}{path}",
                )
            )
        return results

    def _request_text(self, path: str, *, use_cache: bool, refresh: bool) -> str:
        content, _ = self._request_bytes(path, use_cache=use_cache, refresh=refresh)
        return content.decode("utf-8")

    def _request_bytes(self, path: str, *, use_cache: bool, refresh: bool) -> tuple[bytes, bool]:
        cache_key = self.cache.make_key({"base_url": self.base_url, "path": path})
        if use_cache and not refresh:
            cached = self.cache.get(cache_key)
            if cached is not None:
                return cached, True
        self._respect_rate_limit()
        response = self._http.get(path)
        response.raise_for_status()
        payload = response.content
        if use_cache:
            self.cache.set(cache_key, payload, ttl_seconds=self.cache_ttl_seconds)
        return payload, False

    def _respect_rate_limit(self) -> None:
        if self.requests_per_second <= 0:
            return
        interval = 1.0 / self.requests_per_second
        now = self._monotonic()
        if self._last_request_started_at is not None:
            elapsed = now - self._last_request_started_at
            if elapsed < interval:
                self._sleep(interval - elapsed)
                now = self._monotonic()
        self._last_request_started_at = now


def base_url_from_env() -> str | None:
    return os.environ.get("KEGG_API_BASE_URL")

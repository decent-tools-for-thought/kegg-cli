from __future__ import annotations

from pathlib import Path

import httpx

from kegg_cli.cache import DiskLRUCache
from kegg_cli.client import KeggClient, chunked


def test_chunked_splits_at_ten() -> None:
    values = [f"id-{index}" for index in range(23)]

    chunks = chunked(values, 10)

    assert len(chunks) == 3
    assert len(chunks[0]) == 10
    assert len(chunks[1]) == 10
    assert len(chunks[2]) == 3


def test_get_batches_requests_and_uses_cache(tmp_path: Path) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, text=f"PATH\t{request.url.path}\n")

    client = KeggClient(
        cache=DiskLRUCache(root=tmp_path, max_bytes=4096),
        transport=httpx.MockTransport(handler),
        requests_per_second=0,
    )
    try:
        first = client.get(["C00001", "C00002", "C00003"])
        second = client.get(["C00001", "C00002", "C00003"])
    finally:
        client.close()

    assert calls == ["/get/C00001+C00002+C00003"]
    assert [result.cached for result in first] == [False]
    assert [result.cached for result in second] == [True]


def test_rate_limit_waits_between_uncached_requests(tmp_path: Path) -> None:
    calls: list[str] = []
    sleeps: list[float] = []
    current_time = [0.0]

    def monotonic() -> float:
        return current_time[0]

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        current_time[0] += seconds

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, text="ok\n")

    client = KeggClient(
        cache=DiskLRUCache(root=tmp_path, max_bytes=4096),
        transport=httpx.MockTransport(handler),
        requests_per_second=2.0,
        sleep_fn=sleep,
        monotonic_fn=monotonic,
    )
    try:
        client.info("pathway", use_cache=False)
        client.info("compound", use_cache=False)
    finally:
        client.close()

    assert calls == ["/info/pathway", "/info/compound"]
    assert sleeps == [0.5]

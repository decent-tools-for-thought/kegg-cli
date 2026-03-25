from __future__ import annotations

from pathlib import Path

from kegg_cli.cache import DiskLRUCache


def test_cache_round_trip(tmp_path: Path) -> None:
    cache = DiskLRUCache(root=tmp_path, max_bytes=1024)
    cache.set("alpha", b"value")

    assert cache.get("alpha") == b"value"
    assert cache.stats().entries == 1


def test_cache_eviction_prefers_oldest_entry(tmp_path: Path) -> None:
    cache = DiskLRUCache(root=tmp_path, max_bytes=10)
    cache.set("first", b"12345")
    cache.set("second", b"67890")
    cache.get("second")
    cache.set("third", b"abcde")

    assert cache.get("first") is None
    assert cache.get("second") == b"67890"
    assert cache.get("third") == b"abcde"

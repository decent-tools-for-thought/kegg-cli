from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

DEFAULT_CACHE_MAX_BYTES = 10 * 1024**3
CACHE_DIR_ENV_VAR = "KEGG_CACHE_DIR"
CACHE_MAX_BYTES_ENV_VAR = "KEGG_CACHE_MAX_BYTES"
CONFIG_FILE_NAME = "config.toml"


@dataclass(frozen=True)
class CacheSettings:
    cache_dir: Path
    max_size_gb: float


class ResponseCache(Protocol):
    @staticmethod
    def make_key(parts: Mapping[str, object]) -> str: ...

    def get(self, cache_key: str) -> bytes | None: ...

    def set(self, cache_key: str, payload: bytes, ttl_seconds: float | None = None) -> None: ...


def default_cache_dir() -> Path:
    override = os.environ.get(CACHE_DIR_ENV_VAR)
    if override:
        return Path(override).expanduser()
    xdg_cache_home = os.environ.get("XDG_CACHE_HOME")
    if xdg_cache_home:
        return Path(xdg_cache_home).expanduser() / "kegg-cli"
    return Path.home() / ".cache" / "kegg-cli"


def default_config_path() -> Path:
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config_home:
        return Path(xdg_config_home).expanduser() / "kegg-cli" / CONFIG_FILE_NAME
    return Path.home() / ".config" / "kegg-cli" / CONFIG_FILE_NAME


def load_cache_settings() -> CacheSettings:
    raw_config = _load_config_file(default_config_path())
    cache_config = raw_config.get("cache", {})
    if not isinstance(cache_config, dict):
        raise ValueError("config [cache] section must be a table")

    config_dir = cache_config.get("dir")
    if config_dir is not None and not isinstance(config_dir, str):
        raise ValueError("config [cache].dir must be a string")

    config_max_size_gb = cache_config.get("max_size_gb", DEFAULT_CACHE_MAX_BYTES / 1024**3)
    if isinstance(config_max_size_gb, bool) or not isinstance(config_max_size_gb, (int, float)):
        raise ValueError("config [cache].max_size_gb must be a number")

    env_max_bytes = os.environ.get(CACHE_MAX_BYTES_ENV_VAR)
    if env_max_bytes is not None:
        max_size_gb = int(env_max_bytes) / 1024**3
    else:
        max_size_gb = float(config_max_size_gb)

    cache_dir = default_cache_dir() if config_dir is None else Path(config_dir).expanduser()
    return CacheSettings(cache_dir=cache_dir, max_size_gb=max_size_gb)


def create_response_cache(root: Path, max_bytes: int) -> ResponseCache:
    if max_bytes <= 0:
        return DisabledCache(root=root, max_bytes=max_bytes)
    return DiskLRUCache(root=root, max_bytes=max_bytes)


def default_response_cache() -> ResponseCache:
    max_bytes = int(os.environ.get(CACHE_MAX_BYTES_ENV_VAR, DEFAULT_CACHE_MAX_BYTES))
    return create_response_cache(default_cache_dir(), max_bytes)


@dataclass(frozen=True)
class CacheStats:
    entries: int
    total_bytes: int
    max_bytes: int


class DisabledCache:
    def __init__(self, root: Path, max_bytes: int = 0) -> None:
        self.root = root.expanduser()
        self.max_bytes = max_bytes

    @staticmethod
    def make_key(parts: Mapping[str, object]) -> str:
        return DiskLRUCache.make_key(parts)

    def get(self, cache_key: str) -> bytes | None:
        del cache_key
        return None

    def set(self, cache_key: str, payload: bytes, ttl_seconds: float | None = None) -> None:
        del cache_key, payload, ttl_seconds

    def clear(self) -> None:
        return None

    def prune(self, max_bytes: int | None = None) -> CacheStats:
        effective_max_bytes = self.max_bytes if max_bytes is None else max_bytes
        return CacheStats(entries=0, total_bytes=0, max_bytes=effective_max_bytes)

    def stats(self) -> CacheStats:
        return CacheStats(entries=0, total_bytes=0, max_bytes=self.max_bytes)


class DiskLRUCache:
    def __init__(self, root: Path | None = None, max_bytes: int = DEFAULT_CACHE_MAX_BYTES) -> None:
        self.root = (root or default_cache_dir()).expanduser()
        self.max_bytes = max_bytes
        self.db_path = self.root / "index.sqlite3"
        self.blob_root = self.root / "blobs"
        self.root.mkdir(parents=True, exist_ok=True)
        self.blob_root.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS cache_entries (
                    cache_key TEXT PRIMARY KEY,
                    relative_path TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    last_accessed REAL NOT NULL,
                    expires_at REAL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_cache_entries_last_accessed "
                "ON cache_entries(last_accessed)"
            )

    def _blob_path(self, cache_key: str) -> Path:
        return self.blob_root / cache_key[:2] / f"{cache_key}.blob"

    @staticmethod
    def make_key(parts: Mapping[str, object]) -> str:
        payload = json.dumps(parts, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def get(self, cache_key: str) -> bytes | None:
        now = time.time()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT relative_path, expires_at FROM cache_entries WHERE cache_key = ?",
                (cache_key,),
            ).fetchone()
            if row is None:
                return None
            expires_at = row["expires_at"]
            if expires_at is not None and expires_at <= now:
                self._delete_entry(connection, cache_key, row["relative_path"])
                return None
            blob_path = self.root / row["relative_path"]
            if not blob_path.exists():
                self._delete_entry(connection, cache_key, row["relative_path"], unlink=False)
                return None
            connection.execute(
                "UPDATE cache_entries SET last_accessed = ? WHERE cache_key = ?",
                (now, cache_key),
            )
        return bytes(blob_path.read_bytes())

    def set(self, cache_key: str, payload: bytes, ttl_seconds: float | None = None) -> None:
        now = time.time()
        blob_path = self._blob_path(cache_key)
        blob_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = blob_path.with_suffix(".tmp")
        tmp_path.write_bytes(payload)
        tmp_path.replace(blob_path)
        expires_at = None if ttl_seconds is None else now + ttl_seconds
        relative_path = blob_path.relative_to(self.root).as_posix()
        size_bytes = blob_path.stat().st_size
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO cache_entries (
                    cache_key, relative_path, size_bytes, created_at, last_accessed, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    relative_path = excluded.relative_path,
                    size_bytes = excluded.size_bytes,
                    last_accessed = excluded.last_accessed,
                    expires_at = excluded.expires_at
                """,
                (cache_key, relative_path, size_bytes, now, now, expires_at),
            )
            self._prune_locked(connection)

    def clear(self) -> None:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT cache_key, relative_path FROM cache_entries"
            ).fetchall()
            for row in rows:
                self._delete_entry(connection, row["cache_key"], row["relative_path"])

    def prune(self, max_bytes: int | None = None) -> CacheStats:
        with self._connect() as connection:
            self._prune_locked(connection, max_bytes=max_bytes or self.max_bytes)
            return self._stats_locked(connection, max_bytes=max_bytes or self.max_bytes)

    def stats(self) -> CacheStats:
        with self._connect() as connection:
            return self._stats_locked(connection, max_bytes=self.max_bytes)

    def _stats_locked(self, connection: sqlite3.Connection, max_bytes: int) -> CacheStats:
        row = connection.execute(
            """
            SELECT COUNT(*) AS entries, COALESCE(SUM(size_bytes), 0) AS total_bytes
            FROM cache_entries
            """
        ).fetchone()
        return CacheStats(
            entries=int(row["entries"]),
            total_bytes=int(row["total_bytes"]),
            max_bytes=max_bytes,
        )

    def _prune_locked(self, connection: sqlite3.Connection, max_bytes: int | None = None) -> None:
        limit = self.max_bytes if max_bytes is None else max_bytes
        current = self._stats_locked(connection, max_bytes=limit)
        while current.total_bytes > limit and current.entries > 0:
            row = connection.execute(
                """
                SELECT cache_key, relative_path
                FROM cache_entries
                ORDER BY last_accessed ASC
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                break
            self._delete_entry(connection, row["cache_key"], row["relative_path"])
            current = self._stats_locked(connection, max_bytes=limit)

    def _delete_entry(
        self,
        connection: sqlite3.Connection,
        cache_key: str,
        relative_path: str,
        *,
        unlink: bool = True,
    ) -> None:
        connection.execute("DELETE FROM cache_entries WHERE cache_key = ?", (cache_key,))
        if unlink:
            blob_path = self.root / relative_path
            if blob_path.exists():
                blob_path.unlink()
            parent = blob_path.parent
            if parent != self.blob_root and parent.exists():
                try:
                    parent.rmdir()
                except OSError:
                    pass


def _load_config_file(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"config file must contain a TOML table: {path}")
    return data

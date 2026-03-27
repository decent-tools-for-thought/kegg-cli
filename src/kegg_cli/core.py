from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from .cache import CacheSettings, DiskLRUCache, create_response_cache, load_cache_settings
from .client import DEFAULT_REQUESTS_PER_SECOND, BatchResponse, KeggClient, KeggCliError
from .parser import parse_command_output


def build_parser(cache_settings: CacheSettings | None = None) -> argparse.ArgumentParser:
    settings = load_cache_settings() if cache_settings is None else cache_settings
    parser = argparse.ArgumentParser(prog="kegg")
    subparsers = parser.add_subparsers(dest="command", required=True)

    info_parser = subparsers.add_parser("info", help="Show KEGG database statistics")
    info_parser.add_argument("database")
    _add_runtime_args(info_parser, settings)

    find_parser = subparsers.add_parser("find", help="Search KEGG entries")
    find_parser.add_argument("database")
    find_parser.add_argument("query")
    find_parser.add_argument("--option")
    _add_runtime_args(find_parser, settings)

    list_parser = subparsers.add_parser(
        "list", help="List a KEGG database or organism-specific pathways"
    )
    list_parser.add_argument("database")
    list_parser.add_argument("--org")
    _add_runtime_args(list_parser, settings)

    list_entries_parser = subparsers.add_parser("list-entries", help="List selected KEGG entries")
    list_entries_parser.add_argument("entries", nargs="+")
    _add_runtime_args(list_entries_parser, settings)

    get_parser = subparsers.add_parser("get", help="Retrieve KEGG entries")
    get_parser.add_argument("entries", nargs="+")
    get_parser.add_argument("--option")
    _add_runtime_args(get_parser, settings)

    link_parser = subparsers.add_parser("link", help="Link one KEGG database to another")
    link_parser.add_argument("target_db")
    link_parser.add_argument("source_db")
    _add_runtime_args(link_parser, settings)

    link_entries_parser = subparsers.add_parser(
        "link-entries", help="Link selected entries to a target database"
    )
    link_entries_parser.add_argument("target_db")
    link_entries_parser.add_argument("entries", nargs="+")
    _add_runtime_args(link_entries_parser, settings)

    conv_parser = subparsers.add_parser("conv", help="Convert IDs using KEGG")
    conv_parser.add_argument("target_db")
    conv_parser.add_argument("source_db")
    _add_runtime_args(conv_parser, settings)

    conv_entries_parser = subparsers.add_parser(
        "conv-entries",
        help="Convert selected KEGG entries to another database",
    )
    conv_entries_parser.add_argument("target_db")
    conv_entries_parser.add_argument("entries", nargs="+")
    _add_runtime_args(conv_entries_parser, settings)

    ddi_parser = subparsers.add_parser("ddi", help="Check KEGG drug-drug interactions")
    ddi_parser.add_argument("entries", nargs="+")
    _add_runtime_args(ddi_parser, settings)

    cache_parser = subparsers.add_parser("cache", help="Manage the KEGG response cache")
    cache_subparsers = cache_parser.add_subparsers(dest="cache_command", required=True)

    cache_stats = cache_subparsers.add_parser("stats", help="Show cache statistics")
    _add_cache_only_args(cache_stats, settings)

    cache_prune = cache_subparsers.add_parser("prune", help="Evict old cache entries")
    _add_cache_only_args(cache_prune, settings)

    cache_clear = cache_subparsers.add_parser("clear", help="Delete all cache entries")
    _add_cache_only_args(cache_clear, settings)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        cache_settings = load_cache_settings()
    except ValueError as error:
        sys.stderr.write(f"error: {error}\n")
        return 2

    parser = build_parser(cache_settings)
    args = parser.parse_args(argv)

    try:
        if args.command == "cache":
            return _run_cache(args)
        return _run_remote(args)
    except KeggCliError as error:
        parser.exit(status=2, message=f"error: {error}\n")
    return 0


def _run_remote(args: argparse.Namespace) -> int:
    max_bytes = _gigabytes_to_bytes(args.max_cache_size_gb)
    cache = create_response_cache(root=args.cache_dir, max_bytes=max_bytes)
    with KeggClient(
        base_url=args.base_url,
        cache=cache,
        requests_per_second=args.requests_per_second,
    ) as client:
        use_cache = not args.no_cache and max_bytes > 0
        refresh = args.refresh
        if args.command == "info":
            text = client.info(args.database, use_cache=use_cache, refresh=refresh)
            _write_remote_result(args.command, args.output_format, text=text)
        elif args.command == "find":
            text = client.find(
                args.database,
                args.query,
                option=args.option,
                use_cache=use_cache,
                refresh=refresh,
            )
            _write_remote_result(args.command, args.output_format, text=text)
        elif args.command == "list":
            text = client.list_database(
                args.database,
                org=args.org,
                use_cache=use_cache,
                refresh=refresh,
            )
            _write_remote_result(args.command, args.output_format, text=text)
        elif args.command == "list-entries":
            batches = client.list_entries(args.entries, use_cache=use_cache, refresh=refresh)
            _write_remote_result(args.command, args.output_format, batches=batches)
        elif args.command == "get":
            batches = client.get(
                args.entries,
                option=args.option,
                use_cache=use_cache,
                refresh=refresh,
            )
            _write_remote_result(
                args.command, args.output_format, batches=batches, option=args.option
            )
        elif args.command == "link":
            link_result = client.link(
                args.target_db, source_db=args.source_db, use_cache=use_cache, refresh=refresh
            )
            assert isinstance(link_result, str)
            _write_remote_result(args.command, args.output_format, text=link_result)
        elif args.command == "link-entries":
            link_result = client.link(
                args.target_db, entries=args.entries, use_cache=use_cache, refresh=refresh
            )
            assert not isinstance(link_result, str)
            _write_remote_result(args.command, args.output_format, batches=link_result)
        elif args.command == "conv":
            conv_result = client.conv(
                args.target_db, source_db=args.source_db, use_cache=use_cache, refresh=refresh
            )
            assert isinstance(conv_result, str)
            _write_remote_result(args.command, args.output_format, text=conv_result)
        elif args.command == "conv-entries":
            conv_result = client.conv(
                args.target_db, entries=args.entries, use_cache=use_cache, refresh=refresh
            )
            assert not isinstance(conv_result, str)
            _write_remote_result(args.command, args.output_format, batches=conv_result)
        elif args.command == "ddi":
            batches = client.ddi(args.entries, use_cache=use_cache, refresh=refresh)
            _write_remote_result(args.command, args.output_format, batches=batches)
        else:
            raise KeggCliError(f"unsupported command: {args.command}")
    return 0


def _run_cache(args: argparse.Namespace) -> int:
    max_bytes = _gigabytes_to_bytes(args.max_size_gb)
    cache = DiskLRUCache(root=args.cache_dir, max_bytes=max_bytes)
    if args.cache_command == "stats":
        stats = cache.stats()
    elif args.cache_command == "prune":
        stats = cache.prune()
    elif args.cache_command == "clear":
        cache.clear()
        stats = cache.stats()
    else:
        raise KeggCliError(f"unsupported cache command: {args.cache_command}")
    print(
        json.dumps(
            {
                "cache_dir": str(args.cache_dir),
                "entries": stats.entries,
                "total_bytes": stats.total_bytes,
                "max_bytes": stats.max_bytes,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _add_runtime_args(parser: argparse.ArgumentParser, settings: CacheSettings) -> None:
    parser.add_argument("--base-url", default=None)
    parser.add_argument(
        "--format",
        dest="output_format",
        choices=["json", "raw"],
        default="json",
    )
    parser.add_argument("--cache-dir", type=Path, default=settings.cache_dir)
    parser.add_argument(
        "--max-cache-size-gb",
        type=float,
        default=settings.max_size_gb,
    )
    parser.add_argument(
        "--requests-per-second",
        type=float,
        default=DEFAULT_REQUESTS_PER_SECOND,
    )
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--refresh", action="store_true")


def _add_cache_only_args(parser: argparse.ArgumentParser, settings: CacheSettings) -> None:
    parser.add_argument("--cache-dir", type=Path, default=settings.cache_dir)
    parser.add_argument(
        "--max-size-gb",
        type=float,
        default=settings.max_size_gb,
    )


def _write_text(text: str) -> None:
    sys.stdout.write(text)
    if text and not text.endswith("\n"):
        sys.stdout.write("\n")


def _write_remote_result(
    command: str,
    output_format: str,
    *,
    text: str | None = None,
    batches: Sequence[BatchResponse] | None = None,
    option: str | None = None,
) -> None:
    if output_format == "raw":
        if text is not None:
            _write_text(text)
            return
        assert batches is not None
        _write_batches(batches)
        return
    parsed = parse_command_output(command, text=text, batches=batches, option=option)
    print(json.dumps(parsed, indent=2, sort_keys=True))


def _write_batches(results: Sequence[BatchResponse]) -> None:
    for index, result in enumerate(results):
        content = result.content
        if _is_probably_binary(content):
            sys.stdout.buffer.write(content)
        else:
            _write_text(content.decode("utf-8"))
        if index + 1 < len(results) and not content.endswith(b"\n"):
            sys.stdout.write("\n")


def _is_probably_binary(content: bytes) -> bool:
    return b"\x00" in content[:1024]


def _gigabytes_to_bytes(size_gb: float) -> int:
    if size_gb < 0:
        raise KeggCliError("cache size must be non-negative")
    return int(size_gb * 1024**3)

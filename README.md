<div align="center">

# kegg-cli

[![Release](https://img.shields.io/github/v/release/decent-tools-for-thought/kegg-cli?sort=semver&color=0f766e)](https://github.com/decent-tools-for-thought/kegg-cli/releases)
![Python](https://img.shields.io/badge/python-3.11%2B-0ea5e9)
![License](https://img.shields.io/badge/license-0BSD-14b8a6)

Command-line client for KEGG REST discovery, entry retrieval, identifier conversion, interaction checks, parsed JSON output, and local response caching.

</div>

> [!IMPORTANT]
> This codebase is entirely AI-generated. It is useful to me, I hope it might be useful to others, and issues and contributions are welcome.

## Map
- [Install](#install)
- [Functionality](#functionality)
- [Configuration](#configuration)
- [Quick Start](#quick-start)
- [Credits](#credits)

## Install
$$\color{#0EA5E9}Install \space \color{#14B8A6}Tool$$

```bash
uv tool install .   # install the CLI
kegg-cli --help     # inspect the command surface
```

## Functionality
$$\color{#0EA5E9}Database \space \color{#14B8A6}Browse$$
- `kegg-cli info <database>`: show KEGG database statistics.
- `kegg-cli find <database> <query>`: search KEGG entries, optionally with KEGG `find` options.
- `kegg-cli list <database>`: list a KEGG database or organism-specific pathways.
- `kegg-cli list --org <code>`: filter pathway-style listings by organism code.

$$\color{#0EA5E9}Entry \space \color{#14B8A6}Fetch$$
- `kegg-cli get <entry>...`: retrieve one or more KEGG entries.
- `kegg-cli get --option <name>`: request alternate formats such as sequence-oriented output when supported upstream.
- `kegg-cli list-entries <entry>...`: list selected entries directly.

$$\color{#0EA5E9}Link \space \color{#14B8A6}Convert$$
- `kegg-cli link <target-db> <source-db>`: link one KEGG database to another.
- `kegg-cli link-entries <target-db> <entry>...`: link selected entries to a target database.
- `kegg-cli conv <target-db> <source-db>`: convert identifiers using KEGG.
- `kegg-cli conv-entries <target-db> <entry>...`: convert selected entry identifiers.
- `kegg-cli ddi <entry>...`: check KEGG drug-drug interaction data for one or more drug identifiers.

$$\color{#0EA5E9}Output \space \color{#14B8A6}Control$$
- `kegg-cli --format json|raw`: switch between parsed JSON output and raw KEGG flat-file or tab-delimited responses.
- The client chunks `get`, selected-entry `list`, selected-entry `link`, selected-entry `conv`, and multi-entry `ddi` calls into batches of at most 10 entries when required by KEGG.
- The client rate-limits itself client-side and caches successful responses on disk.

$$\color{#0EA5E9}Cache \space \color{#14B8A6}Control$$
- `kegg-cli cache stats`: show cache size and entry counts.
- `kegg-cli cache prune --max-size-gb <n>`: evict older cache entries until the cache fits the target cap.
- `kegg-cli cache clear`: remove all cached responses.

## Configuration
$$\color{#0EA5E9}Tune \space \color{#14B8A6}Defaults$$

By default the CLI targets `https://rest.kegg.jp`, rate-limits itself to 3 requests per second, parses supported responses into JSON, and caches successful responses under the user cache directory.

- Use `--base-url` to point at another KEGG-compatible endpoint.
- Use `--requests-per-second` to lower or raise client-side pacing.
- Use `--format raw` to keep original KEGG response text.
- Use `--no-cache` or `--refresh` when you want live responses instead of cached ones.

The main environment variables are `KEGG_API_BASE_URL`, `KEGG_CACHE_DIR`, `KEGG_CACHE_MAX_BYTES`, and `XDG_CACHE_HOME`.

## Quick Start
$$\color{#0EA5E9}Try \space \color{#14B8A6}Browse$$

```bash
kegg-cli info pathway                              # inspect a KEGG database
kegg-cli find compound glucose                     # search compounds
kegg-cli get C00031 C00022 C00024                 # fetch multiple entries
kegg-cli list hsa                                  # list human gene entries
kegg-cli link-entries pathway hsa:10458 ece:Z5100  # map selected entries into pathways
kegg-cli ddi D00564 D00100 D00109                 # inspect drug-drug interaction output
```

## Credits

This client is built for the KEGG REST API and is not affiliated with KEGG.

Credit goes to Kanehisa Laboratories and the KEGG project for the database, REST interface, and upstream API conventions this tool depends on.

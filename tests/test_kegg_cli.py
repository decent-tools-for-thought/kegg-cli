from __future__ import annotations

import json
from pathlib import Path

import pytest

from kegg_cli.client import BatchResponse
from kegg_cli.core import _write_remote_result, main


def test_cache_stats_command_outputs_json(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    exit_code = main(["cache", "stats", "--cache-dir", str(tmp_path), "--max-size-gb", "1"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["entries"] == 0


def test_list_requires_database_argument() -> None:
    with pytest.raises(SystemExit) as error:
        main(["list"])

    assert error.value.code == 2


def test_write_remote_result_emits_json_by_default(capsys: pytest.CaptureFixture[str]) -> None:
    _write_remote_result("info", "json", text="pathway          KEGG Pathway Database\n")

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert payload["pathway"] == "KEGG Pathway Database"


def test_write_remote_result_can_emit_raw_batches(capsys: pytest.CaptureFixture[str]) -> None:
    _write_remote_result(
        "get",
        "raw",
        batches=[
            BatchResponse(
                requested_entries=("C00031",),
                content=b"ENTRY       C00031                      Compound\n///\n",
                cached=False,
                url="https://rest.kegg.jp/get/C00031",
            )
        ],
    )

    captured = capsys.readouterr()

    assert "ENTRY       C00031" in captured.out

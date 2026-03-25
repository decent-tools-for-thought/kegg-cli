from __future__ import annotations

from kegg_cli.client import BatchResponse
from kegg_cli.parser import (
    parse_command_output,
    parse_get_payload,
    parse_info,
    parse_tabular_rows,
)


def test_parse_info_groups_continuation_lines() -> None:
    parsed = parse_info(
        "pathway          KEGG Pathway Database\n"
        "path             Release 117.0+/03-24, Mar 26\n"
        "                 Kanehisa Laboratories\n"
        "                 585 entries\n"
    )

    assert parsed["pathway"] == "KEGG Pathway Database"
    assert parsed["path"] == [
        "Release 117.0+/03-24, Mar 26",
        "Kanehisa Laboratories",
        "585 entries",
    ]


def test_parse_tabular_rows_for_link() -> None:
    parsed = parse_tabular_rows("hsa:10458\tpath:hsa00010\n", row_kind="link")

    assert parsed == [
        {
            "columns": ["hsa:10458", "path:hsa00010"],
            "source": "hsa:10458",
            "target": "path:hsa00010",
        }
    ]


def test_parse_get_flatfile_records() -> None:
    parsed = parse_get_payload(
        b"ENTRY       C00031                      Compound\n"
        b"NAME        D-Glucose;\n"
        b"            Grape sugar;\n"
        b"            Glucose\n"
        b"FORMULA     C6H12O6\n"
        b"///\n"
        b"ENTRY       C00022                      Compound\n"
        b"NAME        Pyruvate\n"
        b"FORMULA     C3H3O3\n"
        b"///\n",
        option=None,
    )

    assert parsed[0]["entry_id"] == "C00031"
    assert parsed[0]["entry_type"] == "Compound"
    assert parsed[0]["fields"]["NAME"] == ["D-Glucose", "Grape sugar", "Glucose"]
    assert parsed[1]["fields"]["FORMULA"] == "C3H3O3"


def test_parse_get_aaseq_as_fasta_records() -> None:
    parsed = parse_get_payload(b">hsa:1\nMPEP\nTIDE\n", option="aaseq")

    assert parsed == [{"header": "hsa:1", "sequence": "MPEPTIDE"}]


def test_parse_command_output_for_batch_command() -> None:
    parsed = parse_command_output(
        "list-entries",
        batches=[
            BatchResponse(
                requested_entries=("C00031",),
                content=b"C00031\tD-Glucose\n",
                cached=False,
                url="https://rest.kegg.jp/list/C00031",
            )
        ],
    )

    assert parsed["batches"][0]["rows"][0]["entry_id"] == "C00031"

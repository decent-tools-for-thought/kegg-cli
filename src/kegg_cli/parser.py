from __future__ import annotations

import base64
import json
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Sequence
from typing import Any

from .client import BatchResponse, KeggCliError


def parse_command_output(
    command: str,
    *,
    text: str | None = None,
    batches: Sequence[BatchResponse] | None = None,
    option: str | None = None,
) -> Any:
    if (text is None) == (batches is None):
        raise KeggCliError("provide either text or batches to parse")

    if command == "info":
        assert text is not None
        return parse_info(text)
    if command == "find":
        assert text is not None
        return {"query": parse_tabular_rows(text, row_kind="match")}
    if command == "list":
        assert text is not None
        return {"results": parse_tabular_rows(text, row_kind="listing")}
    if command == "link":
        assert text is not None
        return {"links": parse_tabular_rows(text, row_kind="link")}
    if command == "conv":
        assert text is not None
        return {"conversions": parse_tabular_rows(text, row_kind="conversion")}
    if command in {"list-entries", "link-entries", "conv-entries", "ddi"}:
        assert batches is not None
        row_kind = {
            "list-entries": "listing",
            "link-entries": "link",
            "conv-entries": "conversion",
            "ddi": "ddi",
        }[command]
        return parse_batch_tabular(batches, row_kind=row_kind)
    if command == "get":
        assert batches is not None
        return parse_get_batches(batches, option=option)
    raise KeggCliError(f"unsupported parser command: {command}")


def parse_info(text: str) -> dict[str, Any]:
    fields: dict[str, list[str]] = {}
    current_key: str | None = None
    for raw_line in text.splitlines():
        if not raw_line.strip():
            continue
        if raw_line[:17].strip():
            key = raw_line[:17].strip()
            value = raw_line[17:].rstrip()
            fields.setdefault(key, []).append(value)
            current_key = key
        elif current_key is not None:
            fields[current_key].append(raw_line[17:].rstrip())

    parsed: dict[str, Any] = {}
    for key, values in fields.items():
        parsed[key] = values[0] if len(values) == 1 else values
    return parsed


def parse_tabular_rows(text: str, *, row_kind: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw_line in text.splitlines():
        if not raw_line.strip():
            continue
        columns = raw_line.split("\t")
        row: dict[str, Any] = {"columns": columns}
        if row_kind in {"match", "listing"}:
            row["entry_id"] = columns[0]
            if len(columns) > 1:
                row["description"] = columns[1]
            if len(columns) > 2:
                row["extra"] = columns[2:]
        elif row_kind == "link":
            row["source"] = columns[0]
            if len(columns) > 1:
                row["target"] = columns[1]
            if len(columns) > 2:
                row["extra"] = columns[2:]
        elif row_kind == "conversion":
            row["source"] = columns[0]
            if len(columns) > 1:
                row["target"] = columns[1]
            if len(columns) > 2:
                row["extra"] = columns[2:]
        elif row_kind == "ddi":
            row["entry_1"] = columns[0]
            if len(columns) > 1:
                row["entry_2"] = columns[1]
            if len(columns) > 2:
                row["interaction"] = columns[2]
            if len(columns) > 3:
                row["description"] = columns[3]
            if len(columns) > 4:
                row["extra"] = columns[4:]
        else:
            raise KeggCliError(f"unsupported tabular row kind: {row_kind}")
        rows.append(row)
    return rows


def parse_batch_tabular(
    batches: Sequence[BatchResponse],
    *,
    row_kind: str,
) -> dict[str, Any]:
    return {
        "batches": [
            {
                "requested_entries": list(batch.requested_entries),
                "cached": batch.cached,
                "url": batch.url,
                "rows": parse_tabular_rows(batch.text(), row_kind=row_kind),
            }
            for batch in batches
        ]
    }


def parse_get_batches(batches: Sequence[BatchResponse], *, option: str | None) -> dict[str, Any]:
    return {
        "batches": [
            {
                "requested_entries": list(batch.requested_entries),
                "cached": batch.cached,
                "url": batch.url,
                "records": parse_get_payload(batch.content, option=option),
            }
            for batch in batches
        ]
    }


def parse_get_payload(payload: bytes, *, option: str | None) -> Any:
    normalized_option = option or "flatfile"
    if normalized_option == "json":
        return json.loads(payload.decode("utf-8"))
    if normalized_option in {"aaseq", "ntseq"}:
        return parse_fasta(payload.decode("utf-8"))
    if normalized_option == "kgml":
        return parse_xml(payload.decode("utf-8"))
    if _is_probably_binary(payload):
        return {
            "encoding": "base64",
            "data": base64.b64encode(payload).decode("ascii"),
        }
    return parse_kegg_flatfile_records(payload.decode("utf-8"))


def parse_fasta(text: str) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    header: str | None = None
    sequence_parts: list[str] = []
    for line in text.splitlines():
        if line.startswith(">"):
            if header is not None:
                records.append({"header": header, "sequence": "".join(sequence_parts)})
            header = line[1:]
            sequence_parts = []
        elif line.strip():
            sequence_parts.append(line.strip())
    if header is not None:
        records.append({"header": header, "sequence": "".join(sequence_parts)})
    return records


def parse_xml(text: str) -> dict[str, Any]:
    element = ET.fromstring(text)
    return element_to_dict(element)


def element_to_dict(element: ET.Element) -> dict[str, Any]:
    children = [element_to_dict(child) for child in list(element)]
    result: dict[str, Any] = {
        "tag": element.tag,
        "attributes": dict(element.attrib),
    }
    text = (element.text or "").strip()
    if text:
        result["text"] = text
    if children:
        result["children"] = children
    return result


def parse_kegg_flatfile_records(text: str) -> list[dict[str, Any]]:
    raw_records = [part.strip() for part in text.split("///") if part.strip()]
    return [parse_kegg_flatfile_record(record.splitlines()) for record in raw_records]


def parse_kegg_flatfile_record(lines: Iterable[str]) -> dict[str, Any]:
    fields: dict[str, list[str]] = {}
    current_key: str | None = None
    for raw_line in lines:
        if not raw_line.strip():
            continue
        key = raw_line[:12].strip()
        value = raw_line[12:].rstrip()
        if key:
            fields.setdefault(key, []).append(value)
            current_key = key
        elif current_key is not None:
            fields[current_key].append(value)

    parsed_fields = {key: _normalize_field_values(values) for key, values in fields.items()}
    entry_value = parsed_fields.get("ENTRY")
    result: dict[str, Any] = {"fields": parsed_fields}
    if isinstance(entry_value, str):
        parts = entry_value.split()
        if parts:
            result["entry_id"] = parts[0]
        if len(parts) > 1:
            result["entry_type"] = " ".join(parts[1:])
    return result


def _normalize_field_values(values: list[str]) -> Any:
    stripped = [value.rstrip() for value in values if value.rstrip()]
    if not stripped:
        return ""
    if len(stripped) == 1:
        return stripped[0]
    if _looks_like_semicolon_list(stripped):
        return _split_semicolon_values(stripped)
    return stripped


def _looks_like_semicolon_list(values: Sequence[str]) -> bool:
    return any(value.endswith(";") for value in values[:-1]) or values[0].endswith(";")


def _split_semicolon_values(values: Sequence[str]) -> list[str]:
    joined = " ".join(value.strip() for value in values)
    return [part.strip() for part in joined.split(";") if part.strip()]


def _is_probably_binary(content: bytes) -> bool:
    return b"\x00" in content[:1024]

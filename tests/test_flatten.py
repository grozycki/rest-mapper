"""Flattening, from core/path-selection."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rest_mapper.flatten import MAX_ENTRIES, ScalarType, flatten

if TYPE_CHECKING:
    from rest_mapper.paths import JsonValue


def test_nested_scalars() -> None:
    field = flatten({"current": {"temp": 21.5}}).fields[0]
    assert (field.path, field.type, field.example) == ("$.current.temp", ScalarType.NUMBER, "21.5")


def test_long_list_is_truncated() -> None:
    result = flatten({"values": list(range(5000))})
    assert result.truncated
    assert len(result.fields) < 100


def test_entry_limit() -> None:
    result = flatten({f"k{index}": index for index in range(MAX_ENTRIES + 10)})
    assert result.truncated
    assert len(result.fields) == MAX_ENTRIES


def test_depth_limit() -> None:
    nested: JsonValue = 1
    for _ in range(30):
        nested = {"a": nested}
    assert flatten(nested).truncated


def test_long_text_keeps_its_path() -> None:
    field = flatten({"text": "x" * 500}).fields[0]
    assert field.path == "$.text"
    assert len(field.example) == 60


def test_wrapped_list(adsb: JsonValue) -> None:
    candidate = flatten(adsb).collections[0]
    assert candidate.path == "$.ac"
    assert {"hex", "alt_baro"} <= {field.path for field in candidate.item_fields}
    assert "hex" in candidate.likely_keys


def test_list_at_the_root(silesia: JsonValue) -> None:
    candidate = flatten(silesia).collections[0]
    assert candidate.path == "$"
    assert "id" in candidate.likely_keys


def test_paths_differ_between_items() -> None:
    candidate = flatten({"list": [{"a": 1}, {"a": 2, "b": 3}]}).collections[0]
    assert [field.path for field in candidate.item_fields] == ["a", "b"]
    assert candidate.likely_keys == ("a",)


def test_repeated_scalar_is_no_key() -> None:
    candidate = flatten([{"id": 1, "kind": "x"}, {"id": 2, "kind": "x"}]).collections[0]
    assert "kind" in [field.path for field in candidate.item_fields]
    assert candidate.likely_keys == ("id",)

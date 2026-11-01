"""Path syntax, from core/path-selection."""

from __future__ import annotations

import pytest

from rest_mapper.paths import MISSING, PathError, format_path, parse_path, resolve


def test_key_containing_a_dot() -> None:
    assert resolve({"a.b": 1}, parse_path("$['a.b']")) == 1


def test_nested_and_index() -> None:
    assert resolve({"items": [{"id": 7}]}, parse_path("$.items[0].id")) == 7


@pytest.mark.parametrize(
    "text",
    [
        "$.items[*].id",
        "$..id",
        "$.a[?(@.b)]",
        "items",
        "",
        "$.",
        "$[",
        "$.a[-1]",
        "$['a'",
        "$['a'x]",
    ],
)
def test_unsupported_syntax(text: str) -> None:
    with pytest.raises(PathError) as error:
        parse_path(text)
    assert error.value.position >= 0


def test_wildcard_position() -> None:
    with pytest.raises(PathError) as error:
        parse_path("$.items[*].id")
    assert error.value.position == 8


def test_the_root_itself() -> None:
    assert resolve([1, 2], parse_path("$")) == [1, 2]


def test_null_is_present() -> None:
    assert resolve({"a": None}, parse_path("$.a")) is None


def test_absent_key_is_missing() -> None:
    assert resolve({"a": 1}, parse_path("$.b")) is MISSING


def test_index_past_the_end_is_missing() -> None:
    assert resolve([1], parse_path("$[1]")) is MISSING


def test_relative_path() -> None:
    assert resolve({"geo": {"lat": 1}}, parse_path("geo.lat", relative=True)) == 1


def test_relative_path_cannot_be_empty() -> None:
    with pytest.raises(PathError):
        parse_path("", relative=True)


@pytest.mark.parametrize("text", ["$", "$.a.b", "$['a.b'][0]", "$['it\\'s']"])
def test_text_form_round_trip(text: str) -> None:
    assert format_path(parse_path(text).segments) == text

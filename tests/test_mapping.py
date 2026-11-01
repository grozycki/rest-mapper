"""Field, position and attribute reads, from core/mapping-evaluation."""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given
from hypothesis import strategies as st

from rest_mapper.mapping import (
    Failure,
    GeometryPath,
    LatLonPaths,
    Position,
    ValueSpec,
    ValueType,
    read_attributes,
    read_field,
    read_position,
)
from rest_mapper.paths import JsonValue, parse_path

VALUE = parse_path("$.v")
NUMBER = ValueSpec(ValueType.NUMBER)
TEXT = ValueSpec(ValueType.TEXT)
TIMESTAMP = ValueSpec(ValueType.TIMESTAMP)
BOOLEAN = ValueSpec(ValueType.BOOLEAN)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (21.5, 21.5),
        ("21.5", 21.5),
        ("n/a", Failure.TYPE_MISMATCH),
        ({"a": 1}, Failure.TYPE_MISMATCH),
        ([1], Failure.TYPE_MISMATCH),
        ("NaN", Failure.TYPE_MISMATCH),
        ("Infinity", Failure.TYPE_MISMATCH),
        (True, Failure.TYPE_MISMATCH),
        (None, Failure.NULL),
    ],
)
def test_number(value: JsonValue, expected: float | Failure) -> None:
    assert read_field({"v": value}, VALUE, NUMBER) == expected


def test_missing_path() -> None:
    assert read_field({}, VALUE, NUMBER) is Failure.MISSING


def test_long_text() -> None:
    assert read_field({"v": "x" * 400}, VALUE, TEXT) == "x" * 255


def test_boolean_as_text() -> None:
    assert read_field({"v": False}, VALUE, TEXT) == "false"


def test_milliseconds() -> None:
    assert read_field({"v": 1793545737500}, VALUE, TIMESTAMP) == datetime.fromtimestamp(
        1793545737.5, UTC
    )


def test_seconds() -> None:
    assert read_field({"v": 1793545737}, VALUE, TIMESTAMP) == datetime.fromtimestamp(
        1793545737, UTC
    )


def test_timestamp_without_a_zone() -> None:
    assert read_field({"v": "2026-11-01T15:06:30.916493"}, VALUE, TIMESTAMP) == datetime(
        2026, 11, 1, 15, 6, 30, 916493, UTC
    )


def test_local_schedule() -> None:
    zone = ZoneInfo("Europe/Warsaw")
    spec = ValueSpec(ValueType.TIMESTAMP, naive_timezone=zone)
    assert read_field({"v": "2026-11-05T08:00:00"}, VALUE, spec) == datetime(
        2026, 11, 5, 8, tzinfo=zone
    )


def test_date_only() -> None:
    assert read_field({"v": "2026-11-05"}, VALUE, TIMESTAMP) == date(2026, 11, 5)


def test_bad_timestamp() -> None:
    assert read_field({"v": "soon"}, VALUE, TIMESTAMP) is Failure.TYPE_MISMATCH


def test_json_boolean() -> None:
    assert read_field({"v": True}, VALUE, BOOLEAN) is True


@pytest.mark.parametrize(
    ("value", "expected"), [(1, True), (0, False), ("YES", True), ("off", False)]
)
def test_default_boolean_values(value: JsonValue, expected: bool) -> None:
    assert read_field({"v": value}, VALUE, BOOLEAN) is expected


def test_own_values() -> None:
    spec = ValueSpec(
        ValueType.BOOLEAN, on_values=frozenset({"open"}), off_values=frozenset({"closed"})
    )
    assert read_field({"v": "closed"}, VALUE, spec) is False
    assert read_field({"v": "ajar"}, VALUE, spec) is Failure.TYPE_MISMATCH


def test_number_from_a_status_code() -> None:
    spec = ValueSpec(ValueType.BOOLEAN, on_values=frozenset({"2"}))
    assert read_field({"v": 2}, VALUE, spec) is True


def test_only_an_on_value() -> None:
    spec = ValueSpec(ValueType.BOOLEAN, on_values=frozenset({"2"}))
    assert read_field({"v": 0}, VALUE, spec) is False


def test_unknown_boolean() -> None:
    assert read_field({"v": "maybe"}, VALUE, BOOLEAN) is Failure.TYPE_MISMATCH


LAT_LON = LatLonPaths(parse_path("$.lat"), parse_path("$.lon"))
GEOMETRY = GeometryPath(parse_path("$.g"))


def test_separate_paths() -> None:
    assert read_position({"lat": 50.168, "lon": 18.9032}, LAT_LON) == Position(50.168, 18.9032)


def test_geojson_point_order() -> None:
    data: JsonValue = {"g": {"type": "Point", "coordinates": [19.02, 50.26]}}
    assert read_position(data, GEOMETRY) == Position(50.26, 19.02)


def test_geojson_altitude_is_ignored() -> None:
    data: JsonValue = {"g": {"type": "Point", "coordinates": [19.02, 50.26, 300]}}
    assert read_position(data, GEOMETRY) == Position(50.26, 19.02)


def test_line() -> None:
    line: JsonValue = {"type": "LineString", "coordinates": [[1, 2], [3, 4], [5, 6]]}
    assert read_position({"g": line}, GEOMETRY) == Position(4, 3)


def test_other_geometry() -> None:
    data: JsonValue = {"g": {"type": "Polygon", "coordinates": []}}
    assert read_position(data, GEOMETRY) is Failure.TYPE_MISMATCH


def test_out_of_range() -> None:
    assert read_position({"lat": 95, "lon": 1}, LAT_LON) is Failure.TYPE_MISMATCH


def test_missing_position() -> None:
    assert read_position({"lat": 1}, LAT_LON) is Failure.MISSING


def test_unreadable_accuracy() -> None:
    spec = LatLonPaths(parse_path("$.lat"), parse_path("$.lon"), parse_path("$.acc"))
    assert read_position({"lat": 1, "lon": 2}, spec) == Position(1, 2, 0.0)


def test_accuracy() -> None:
    spec = LatLonPaths(parse_path("$.lat"), parse_path("$.lon"), parse_path("$.acc"))
    assert read_position({"lat": 1, "lon": 2, "acc": 5}, spec) == Position(1, 2, 5.0)


def test_object_as_an_attribute() -> None:
    result = read_attributes({"a": {"b": 1}}, {"small": parse_path("$.a")})
    assert result.values == {"small": {"b": 1}}


def test_oversized_attribute() -> None:
    result = read_attributes({"a": ["x" * 100] * 50}, {"big": parse_path("$.a")})
    assert result.values == {}
    assert result.too_large == ("big",)


def test_missing_attribute_is_left_out() -> None:
    assert read_attributes({}, {"gone": parse_path("$.a")}).values == {}


JSON: st.SearchStrategy[JsonValue] = st.recursive(
    st.none() | st.booleans() | st.integers() | st.floats() | st.text(),
    lambda children: st.lists(children) | st.dictionaries(st.text(), children),
    max_leaves=10,
)


@given(JSON, st.sampled_from(list(ValueType)))
def test_no_json_input_raises(value: JsonValue, value_type: ValueType) -> None:
    read_field({"v": value}, VALUE, ValueSpec(value_type))


@given(JSON)
def test_no_geometry_raises(value: JsonValue) -> None:
    read_position({"g": value}, GEOMETRY)
    read_position({"lat": value, "lon": value}, LAT_LON)


HUGE = 10**400


@pytest.mark.parametrize("value_type", list(ValueType))
def test_huge_integer_does_not_raise(value_type: ValueType) -> None:
    read_field({"v": HUGE}, VALUE, ValueSpec(value_type))


def test_huge_integer_as_a_number() -> None:
    assert read_field({"v": HUGE}, VALUE, NUMBER) is Failure.TYPE_MISMATCH


def test_huge_integer_as_a_time() -> None:
    assert read_field({"v": HUGE}, VALUE, TIMESTAMP) is Failure.TYPE_MISMATCH


def test_huge_integer_as_a_position() -> None:
    assert read_position({"lat": HUGE, "lon": 1}, LAT_LON) is Failure.TYPE_MISMATCH
    point: JsonValue = {"g": {"type": "Point", "coordinates": [HUGE, 1]}}
    assert read_position(point, GEOMETRY) is Failure.TYPE_MISMATCH

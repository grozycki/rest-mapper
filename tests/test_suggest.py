"""Suggestions, from core/mapping-suggestions."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from conftest import load_fixture
from rest_mapper.flatten import FlatField, ScalarType, flatten
from rest_mapper.mapping import ValueType
from rest_mapper.suggest import (
    CollectionSuggestion,
    EntityKind,
    PositionPaths,
    find_url_key,
    label_for,
    name_for,
    suggest_collection,
    suggest_field,
)

if TYPE_CHECKING:
    from rest_mapper.paths import JsonValue

NOW = datetime(2026, 11, 1, tzinfo=UTC)


def proposal(data: JsonValue) -> CollectionSuggestion:
    return suggest_collection(data, flatten(data).collections[0], NOW, UTC)


def test_tomtom() -> None:
    result = proposal(load_fixture("tomtom_incidents.json"))
    assert result.key == "properties.id"
    assert result.position == PositionPaths(geometry="geometry")
    assert result.kind is EntityKind.GEO_LOCATION


def test_adsb() -> None:
    result = proposal(load_fixture("adsb_lol.json"))
    assert result.key == "hex"
    assert result.position == PositionPaths(latitude="lat", longitude="lon")
    assert result.name == "flight"
    assert result.kind is EntityKind.GEO_LOCATION


def test_silesia_alert() -> None:
    result = proposal(load_fixture("silesia_alert.json"))
    assert result.key == "id"
    assert result.name == "name"
    assert result.kind is EntityKind.DEVICE_TRACKER
    assert result.example == "Mikołów"


def test_no_unique_value() -> None:
    assert proposal([{"a": 1}, {"a": 1}]).key is None


def test_latitude_out_of_range() -> None:
    assert proposal([{"id": 1, "lat": 350, "lon": 1}]).position is None


def test_dated_list() -> None:
    result = proposal({"items": [{"id": 1, "date": "2030-01-01", "title": "Paper"}]})
    assert result.kind is EntityKind.CALENDAR
    assert (result.start, result.name) == ("date", "title")


def test_past_dates_are_no_calendar() -> None:
    result = proposal([{"id": 1, "date": "2001-01-01", "title": "Old", "v": 1}])
    assert result.kind is EntityKind.SENSOR
    assert result.value == "v"


def test_name_is_not_an_identifier() -> None:
    result = proposal([{"id": 1, "title": "TTI-57f1-902a-7e9d", "v": 2}])
    assert result.name is None


def test_name_nested_in_a_list() -> None:
    item: JsonValue = {
        "properties": {"id": "a", "iconCategory": 8, "events": [{"description": "Zamknięta droga"}]}
    }
    result = proposal({"incidents": [item]})
    assert result.name == "properties.events[0].description"


def test_nested_label() -> None:
    assert label_for("$.incidents[0].properties.iconCategory") == "Properties \u203a Icon category"


def test_relative_label() -> None:
    assert label_for("alt_baro") == "Alt baro"


def test_polish_letters_stay() -> None:
    assert label_for("$.wysokość_żółta") == "Wysokość żółta"


def test_entity_name() -> None:
    assert name_for("$.current.temp_c") == "Temp c"


def test_every_fixture_has_labels() -> None:
    for name in ("adsb_lol.json", "silesia_alert.json", "tomtom_incidents.json"):
        for field in flatten(load_fixture(name)).fields:
            assert label_for(field.path)


def test_temperature() -> None:
    result = suggest_field(FlatField("$.current.temp_c", ScalarType.NUMBER, "21.5"))
    assert (result.device_class, result.unit) == ("temperature", "°C")


def test_false_friend() -> None:
    result = suggest_field(FlatField("$.attempts", ScalarType.NUMBER, "3"))
    assert result.device_class is None


def test_text_gets_no_class() -> None:
    result = suggest_field(FlatField("$.temp", ScalarType.TEXT, "hot"))
    assert result.device_class is None
    assert result.value_type is ValueType.TEXT


def test_yes_or_no() -> None:
    result = suggest_field(FlatField("$.open", ScalarType.BOOLEAN, "true"))
    assert result.kind is EntityKind.BINARY_SENSOR


def test_geometry_listed() -> None:
    fields = flatten([{"g": {"type": "Point", "coordinates": [1, 2]}}]).fields
    assert [(field.path, field.type) for field in fields] == [("$[0].g", ScalarType.GEOMETRY)]


def test_pasted_key() -> None:
    found = find_url_key("https://x.example/a?bbox=1,2&key=abc")
    assert found is not None
    assert (found.name, found.value) == ("key", "abc")
    assert "key=" not in found.url
    assert "bbox" in found.url


@pytest.mark.parametrize("url", ["https://x.example/?keyword=rain", "https://x.example/"])
def test_harmless_parameter(url: str) -> None:
    assert find_url_key(url) is None


def test_key_stays_out_of_repr() -> None:
    found = find_url_key("https://x.example/?token=marker")
    assert "marker" not in repr(found)

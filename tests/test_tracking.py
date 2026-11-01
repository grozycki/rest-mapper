"""Following items, from core/collection-tracking."""

from __future__ import annotations

from rest_mapper.paths import JsonValue, parse_path
from rest_mapper.tracking import ItemTracker, read_items

ITEMS = parse_path("$.items")
KEY = parse_path("id", relative=True)


def keys(*values: int) -> tuple[str, ...]:
    return tuple(str(value) for value in values)


def test_numeric_key() -> None:
    result = read_items({"items": [{"id": 7}]}, ITEMS, KEY)
    assert result is not None
    assert list(result.items) == ["7"]


def test_missing_key() -> None:
    data: JsonValue = {"items": [{"x": 1}, {"id": {"a": 1}}, 5]}
    result = read_items(data, ITEMS, KEY)
    assert result is not None
    assert result.skipped == 3


def test_repeated_key() -> None:
    data: JsonValue = {"items": [{"id": 1, "n": "first"}, {"id": 1, "n": "second"}]}
    result = read_items(data, ITEMS, KEY)
    assert result is not None
    assert result.duplicates == 1
    assert result.items["1"]["n"] == "first"


def test_not_a_list() -> None:
    assert read_items({"items": {}}, ITEMS, KEY) is None


def test_empty_list() -> None:
    result = read_items({"items": []}, ITEMS, KEY)
    assert result is not None
    assert result.items == {}


def test_recorded_responses(adsb: JsonValue, silesia: JsonValue) -> None:
    aircraft = read_items(adsb, parse_path("$.ac"), parse_path("hex", relative=True))
    sirens = read_items(silesia, parse_path("$"), KEY)
    assert aircraft is not None
    assert aircraft.skipped == 0
    assert sirens is not None
    assert len(sirens.items) == 61


def test_baseline() -> None:
    tracker = ItemTracker()
    changes = tracker.update(keys(1, 2, 3, 4, 5))
    assert changes.added == ()
    assert len(tracker.tracked) == 5


def test_new_item() -> None:
    tracker = ItemTracker()
    tracker.update(keys(1))
    assert tracker.update(keys(1, 2)).added == ("2",)


def test_brief_absence() -> None:
    tracker = ItemTracker()
    tracker.update(keys(1, 2))
    assert tracker.update(keys(1)).removed == ()
    changes = tracker.update(keys(1, 2))
    assert changes.added == ()
    assert tracker.update(keys(1)).removed == ()


def test_gone() -> None:
    tracker = ItemTracker()
    tracker.update(keys(1, 2))
    tracker.update(keys(1))
    assert tracker.update(keys(1)).removed == ("2",)


def test_return_after_removal() -> None:
    tracker = ItemTracker(removal_after=1)
    tracker.update(keys(1, 2))
    tracker.update(keys(1))
    assert tracker.update(keys(1, 2)).added == ("2",)


def test_list_over_the_limit() -> None:
    tracker = ItemTracker(limit=50)
    changes = tracker.update(keys(*range(80)))
    assert len(tracker.tracked) == 50
    assert changes.ignored == 30


def test_tracked_items_keep_their_place() -> None:
    tracker = ItemTracker(limit=1)
    tracker.update(keys(5))
    tracker.update(keys(9, 5))
    assert tracker.tracked == ("5",)


def test_space_appears() -> None:
    tracker = ItemTracker(limit=1, removal_after=1)
    tracker.update(keys(1))
    assert tracker.update(keys(2)).added == ("2",)


def test_restored_baseline() -> None:
    tracker = ItemTracker()
    tracker.update(keys(1, 2))
    restored = ItemTracker()
    restored.restore(tracker.to_data())
    assert restored.update(keys(1, 2)).added == ()


def test_restored_absence_count() -> None:
    tracker = ItemTracker()
    tracker.update(keys(1, 2))
    tracker.update(keys(1))
    restored = ItemTracker()
    restored.restore(tracker.to_data())
    assert restored.update(keys(1)).removed == ("2",)


def test_malformed_restore_is_ignored() -> None:
    tracker = ItemTracker()
    tracker.restore({"absences": "bad"})
    assert not tracker.has_baseline

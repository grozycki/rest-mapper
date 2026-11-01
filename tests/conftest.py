"""Shared test helpers."""

from __future__ import annotations

import json
from pathlib import Path as FilePath
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from rest_mapper.paths import JsonValue

FIXTURES = FilePath(__file__).parent / "fixtures"


def load_fixture(name: str) -> JsonValue:
    """Read a recorded response."""
    decoded: JsonValue = json.loads((FIXTURES / name).read_text())
    return decoded


@pytest.fixture
def adsb() -> JsonValue:
    """Return a recorded adsb.lol response."""
    return load_fixture("adsb_lol.json")


@pytest.fixture
def silesia() -> JsonValue:
    """Return a recorded Silesia Alert response."""
    return load_fixture("silesia_alert.json")

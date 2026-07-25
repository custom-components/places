"""Unit tests for helper functions in the places custom component."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path

import pytest

from custom_components.places import helpers
from custom_components.places.helpers import (
    clear_since_from_state,
    create_json_folder,
    get_dict_from_json_file,
    remove_json_file,
    safe_truncate,
    write_sensor_to_json,
)


@pytest.mark.parametrize("precreate", [False, True])
def test_create_json_folder_param(tmp_path: Path, precreate: bool) -> None:
    """Ensure folder creation is idempotent."""
    folder = tmp_path / "json_folder"
    if precreate:
        folder.mkdir()
    create_json_folder(str(folder))
    assert folder.is_dir()


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ({"a": 1, "b": "x"}, {"a": 1, "b": "x"}),
        (None, {}),
        ("{", {}),
        (["not", "a", "mapping"], {}),
    ],
)
def test_get_dict_from_json_file_param(
    tmp_path: Path,
    content: dict[str, object] | list[str] | str | None,
    expected: dict[str, object],
) -> None:
    """Return a mapping only for an existing valid JSON object."""
    filename = "test.json"
    if content is not None:
        serialized = content if isinstance(content, str) else json.dumps(content)
        (tmp_path / filename).write_text(serialized)
    assert get_dict_from_json_file("test", filename, tmp_path) == expected


@pytest.mark.parametrize("precreate", [True, False])
def test_remove_json_file_param(tmp_path: Path, precreate: bool) -> None:
    """Delete an existing JSON snapshot and tolerate a missing file."""
    file_path = tmp_path / "sensor.json"
    if precreate:
        file_path.write_text("{}")
    remove_json_file("test", file_path.name, tmp_path)
    assert not file_path.exists()


def test_write_sensor_to_json_excludes_datetime(tmp_path: Path) -> None:
    """Exclude datetime values from persisted sensor attributes."""
    data = {"a": 1, "b": datetime.now(tz=UTC), "c": "ok"}
    write_sensor_to_json(data, "test", "sensor.json", tmp_path)
    assert json.loads((tmp_path / "sensor.json").read_text()) == {"a": 1, "c": "ok"}


def test_write_sensor_to_json_coerces_non_serializable_values(tmp_path: Path) -> None:
    """Stringify values that JSON cannot serialize."""
    non_serializable = object()
    write_sensor_to_json({"a": 1, "b": non_serializable}, "test", "sensor.json", tmp_path)
    assert json.loads((tmp_path / "sensor.json").read_text()) == {
        "a": 1,
        "b": str(non_serializable),
    }


@pytest.mark.parametrize(
    ("input_str", "expected"),
    [
        ("Home (since 12:34)", "Home"),
        ("Work (since 01/23)", "Work"),
        ("Elsewhere", "Elsewhere"),
    ],
)
def test_clear_since_from_state_removes_pattern(input_str: str, expected: str) -> None:
    """Test that clear_since_from_state removes '(since ...)' patterns from strings."""
    assert clear_since_from_state(input_str) == expected


@pytest.mark.parametrize(
    ("input_str", "max_len", "expected"),
    [
        ("abc", 5, "abc"),  # shorter
        ("abcde", 5, "abcde"),  # exact
        ("abcdef", 4, "abcd"),  # longer
        (None, 3, ""),  # None
    ],
)
def test_safe_truncate(input_str: str | None, max_len: int, expected: str) -> None:
    """Test that safe_truncate returns the correct truncated string for various inputs."""
    assert safe_truncate(input_str, max_len) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1.23, True),
        ("2.34", True),
        (0, True),
        ("0", True),
        (-5.6, True),
        (123, True),
        (123.45, True),
        ("1.23", True),
        (None, False),
        ("abc", False),
        ({}, False),
        ([], False),
        ("not-a-number", False),
    ],
)
def test_is_float_param(value: object, expected: bool) -> None:
    """is_float returns expected boolean for a variety of inputs."""
    assert helpers.is_float(value) is expected

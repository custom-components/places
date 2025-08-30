"""Unit tests for helper functions in the places custom component."""

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any

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


@pytest.mark.parametrize(
    "precreate",
    [False, True],
)
def test_create_json_folder_param(tmp_path: Path | Any, precreate: bool) -> None:
    """Ensure create_json_folder creates the target directory and is idempotent if it already exists."""
    folder = tmp_path / "json_folder"
    if precreate:
        folder.mkdir()
    create_json_folder(str(folder))
    assert folder.exists() and folder.is_dir()


@pytest.mark.parametrize(
    "existing,expected",
    [
        (True, {"a": 1, "b": "x"}),
        (False, {}),
    ],
)
def test_get_dict_from_json_file_param(
    tmp_path: Path | Any, existing: bool, expected: dict[str, Any]
) -> None:
    """Read JSON file returns dict when present, else empty dict when missing."""
    folder = tmp_path
    filename = "test.json"
    if existing:
        data = {"a": 1, "b": "x"}
        (folder / filename).write_text(json.dumps(data))
    result = get_dict_from_json_file("test", filename, str(folder))
    assert result == expected


@pytest.mark.parametrize(
    "precreate",
    [True, False],
)
def test_remove_json_file_param(tmp_path: Path | Any, precreate: bool) -> None:
    """remove_json_file deletes the file when present and is a no-op when missing."""
    folder = tmp_path
    filename = "toremove.json"
    file_path = folder / filename
    if precreate:
        file_path.write_text("test")
        assert file_path.exists()
    # Should not raise
    remove_json_file("test", filename, str(folder))
    assert not file_path.exists()


def test_write_sensor_to_json_excludes_datetime(tmp_path: Path | Any) -> None:
    """Ensure write_sensor_to_json excludes non-serializable datetime values from the output file."""
    folder = tmp_path
    filename = "sensor.json"
    data = {"a": 1, "b": datetime.now(), "c": "ok"}
    write_sensor_to_json(data, "test", filename, str(folder))
    file_path = folder / filename
    assert file_path.exists()
    loaded = json.loads(file_path.read_text())
    assert "a" in loaded and "c" in loaded
    assert "b" not in loaded


@pytest.mark.parametrize(
    "input_str,expected",
    [
        ("Home (since 12:34)", "Home"),
        ("Work (since 01/23)", "Work"),
        ("Elsewhere", "Elsewhere"),
    ],
)
def test_clear_since_from_state_removes_pattern(input_str: str, expected: str) -> None:
    """Test that clear_since_from_state removes '(since ...)' patterns from strings (parametrized)."""
    assert clear_since_from_state(input_str) == expected


@pytest.mark.parametrize(
    "input_str,max_len,expected",
    [
        ("abc", 5, "abc"),  # shorter
        ("abcde", 5, "abcde"),  # exact
        ("abcdef", 4, "abcd"),  # longer
        (None, 3, ""),  # None
    ],
)
def test_safe_truncate(input_str: str | None, max_len: int, expected: str) -> None:
    """Test that safe_truncate returns the correct truncated string for various input scenarios."""
    assert safe_truncate(input_str, max_len) == expected


@pytest.mark.parametrize(
    "value,expected",
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
def test_is_float_param(value: Any, expected: bool) -> None:
    """is_float returns expected boolean for a variety of inputs."""
    assert helpers.is_float(value) is expected


def test_write_read_and_remove_json_file(tmp_path: Path) -> None:
    """Write sensor attributes to JSON (datetime removed), read them back, then remove the file."""

    json_folder = tmp_path / "jsons"
    filename = "sensor1.json"
    name = "test_sensor"

    # Ensure folder creation works
    helpers.create_json_folder(str(json_folder))
    assert json_folder.exists() and json_folder.is_dir()

    # Prepare attributes including a datetime which should be removed by write_sensor_to_json
    attrs: dict[str, Any] = {
        "value": 42,
        "updated": datetime.now(tz=UTC),
    }

    # Write file and confirm content does not include the datetime field
    helpers.write_sensor_to_json(attrs, name, filename, str(json_folder))
    written = json.loads((json_folder / filename).read_text())
    assert "value" in written
    assert "updated" not in written

    # Read back via helper
    read_back = helpers.get_dict_from_json_file(name, filename, str(json_folder))
    assert read_back.get("value") == 42

    # Remove file and confirm it no longer exists
    helpers.remove_json_file(name, filename, str(json_folder))
    assert not (json_folder / filename).exists()

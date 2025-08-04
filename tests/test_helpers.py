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
    is_float,
    remove_json_file,
    safe_truncate,
    write_sensor_to_json,
)


def test_create_json_folder_creates(tmp_path):
    """Ensure create_json_folder creates the target directory when it doesn't exist."""
    folder = tmp_path / "json_folder"
    create_json_folder(str(folder))
    assert folder.exists() and folder.is_dir()


def test_create_json_folder_existing(tmp_path):
    """Ensure create_json_folder is idempotent when the folder already exists."""
    folder = tmp_path / "json_folder"
    folder.mkdir()
    create_json_folder(str(folder))  # Should not raise
    assert folder.exists()


def test_get_dict_from_json_file_reads(tmp_path):
    """Verify reading a JSON file returns the correct dict payload when the file exists."""
    folder = tmp_path
    filename = "test.json"
    data = {"a": 1, "b": "x"}
    file_path = folder / filename
    file_path.write_text(json.dumps(data))
    result = get_dict_from_json_file("test", filename, str(folder))
    assert result == data


def test_get_dict_from_json_file_missing(tmp_path):
    """Verify get_dict_from_json_file returns an empty dict for missing files instead of throwing."""
    folder = tmp_path
    filename = "missing.json"
    result = get_dict_from_json_file("test", filename, str(folder))
    assert result == {}


def test_remove_json_file_removes(tmp_path):
    """Ensure remove_json_file deletes an existing JSON file and leaves no trace."""
    folder = tmp_path
    filename = "toremove.json"
    file_path = folder / filename
    file_path.write_text("test")
    assert file_path.exists()
    remove_json_file("test", filename, str(folder))
    assert not file_path.exists()


def test_remove_json_file_missing(tmp_path):
    """Ensure remove_json_file is a no-op when the target file does not exist."""
    folder = tmp_path
    filename = "missing.json"
    # Should not raise
    remove_json_file("test", filename, str(folder))


def test_is_float_true_for_float():
    """is_float should accept numeric types and numeric strings as floats."""
    assert is_float(1.23)
    assert is_float("2.34")
    assert is_float(0)
    assert is_float("0")
    assert is_float(-5.6)


def test_is_float_false_for_non_float():
    """is_float should reject non-numeric and non-string values."""
    assert not is_float(None)
    assert not is_float("abc")
    assert not is_float({})
    assert not is_float([])


def test_write_sensor_to_json_excludes_datetime(tmp_path):
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


def test_clear_since_from_state_removes_pattern():
    """Test that clear_since_from_state removes '(since ...)' patterns from strings."""
    s = "Home (since 12:34)"
    assert clear_since_from_state(s) == "Home"
    s2 = "Work (since 01/23)"
    assert clear_since_from_state(s2) == "Work"
    s3 = "Elsewhere"
    assert clear_since_from_state(s3) == "Elsewhere"


@pytest.mark.parametrize(
    "input_str,max_len,expected",
    [
        ("abc", 5, "abc"),  # shorter
        ("abcde", 5, "abcde"),  # exact
        ("abcdef", 4, "abcd"),  # longer
        (None, 3, ""),  # None
    ],
)
def test_safe_truncate(input_str, max_len, expected):
    """Test that safe_truncate returns the correct truncated string for various input scenarios."""
    assert safe_truncate(input_str, max_len) == expected


def test_is_float_various() -> None:
    """is_float should return True for numbers and numeric strings, False otherwise."""
    assert helpers.is_float(None) is False
    assert helpers.is_float(123) is True
    assert helpers.is_float(123.45) is True
    assert helpers.is_float("1.23") is True
    assert helpers.is_float("not-a-number") is False


def test_safe_truncate_and_clear_since() -> None:
    """safe_truncate returns expected truncation and clear_since_from_state removes the since part."""
    assert helpers.safe_truncate(None, 10) == ""
    assert helpers.safe_truncate("short", 10) == "short"
    assert helpers.safe_truncate("this is long", 4) == "this"

    assert helpers.clear_since_from_state("Home (since 12:34)") == "Home"
    assert helpers.clear_since_from_state("Away") == "Away"


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

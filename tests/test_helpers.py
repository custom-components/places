from datetime import datetime
import json

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
    folder = tmp_path / "json_folder"
    create_json_folder(str(folder))
    assert folder.exists() and folder.is_dir()


def test_create_json_folder_existing(tmp_path):
    folder = tmp_path / "json_folder"
    folder.mkdir()
    create_json_folder(str(folder))  # Should not raise
    assert folder.exists()


def test_get_dict_from_json_file_reads(tmp_path):
    folder = tmp_path
    filename = "test.json"
    data = {"a": 1, "b": "x"}
    file_path = folder / filename
    file_path.write_text(json.dumps(data))
    result = get_dict_from_json_file("test", filename, str(folder))
    assert result == data


def test_get_dict_from_json_file_missing(tmp_path):
    folder = tmp_path
    filename = "missing.json"
    result = get_dict_from_json_file("test", filename, str(folder))
    assert result == {}


def test_remove_json_file_removes(tmp_path):
    folder = tmp_path
    filename = "toremove.json"
    file_path = folder / filename
    file_path.write_text("test")
    assert file_path.exists()
    remove_json_file("test", filename, str(folder))
    assert not file_path.exists()


def test_remove_json_file_missing(tmp_path):
    folder = tmp_path
    filename = "missing.json"
    # Should not raise
    remove_json_file("test", filename, str(folder))


def test_is_float_true_for_float():
    assert is_float(1.23)
    assert is_float("2.34")
    assert is_float(0)
    assert is_float("0")
    assert is_float(-5.6)


def test_is_float_false_for_non_float():
    assert not is_float(None)
    assert not is_float("abc")
    assert not is_float({})
    assert not is_float([])


def test_write_sensor_to_json_excludes_datetime(tmp_path):
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
    s = "Home (since 12:34)"
    assert clear_since_from_state(s) == "Home"
    s2 = "Work (since 01/23)"
    assert clear_since_from_state(s2) == "Work"
    s3 = "Elsewhere"
    assert clear_since_from_state(s3) == "Elsewhere"


def test_safe_truncate_shorter():
    assert safe_truncate("abc", 5) == "abc"


def test_safe_truncate_exact():
    assert safe_truncate("abcde", 5) == "abcde"


def test_safe_truncate_longer():
    assert safe_truncate("abcdef", 4) == "abcd"


def test_safe_truncate_none():
    assert safe_truncate(None, 3) == ""

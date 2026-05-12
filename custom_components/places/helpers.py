"""Filesystem, parsing, and formatting helpers for the Places integration."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from datetime import datetime
import json
import logging
from os import PathLike
from pathlib import Path
import re
from typing import Any

_LOGGER = logging.getLogger(__name__)

type JsonPath = str | PathLike[str]


def create_json_folder(json_folder: str) -> None:
    """Ensure the sensor JSON persistence folder exists.

    Args:
        json_folder: Directory path where Places sensor snapshots are stored.
    """
    try:
        Path(json_folder).mkdir(parents=True, exist_ok=True)
    except OSError as e:
        _LOGGER.warning(
            "OSError creating folder for JSON sensor files: %s: %s", type(e).__name__, e
        )


def get_dict_from_json_file(
    name: str, filename: JsonPath, json_folder: JsonPath
) -> MutableMapping[str, Any]:
    """Load persisted sensor attributes from disk.

    Args:
        name: Sensor name used for contextual logging.
        filename: JSON file name within ``json_folder``.
        json_folder: Directory containing persisted sensor snapshots.

    Returns:
        Parsed JSON mapping, or an empty mapping when the file cannot be read.
    """
    try:
        json_file_path: Path = Path(json_folder) / filename
        with json_file_path.open() as jsonfile:
            sensor_attributes_from_file: Any = json.load(jsonfile)
    except (OSError, json.JSONDecodeError) as e:
        _LOGGER.debug(
            "(%s) [Init] No JSON file to import (%s): %s: %s",
            name,
            filename,
            type(e).__name__,
            e,
        )
        return {}
    if not isinstance(sensor_attributes_from_file, Mapping):
        _LOGGER.debug(
            "(%s) [Init] JSON file (%s) root is %s, expected mapping",
            name,
            filename,
            type(sensor_attributes_from_file).__name__,
        )
        return {}
    return dict(sensor_attributes_from_file)


def remove_json_file(name: str, filename: JsonPath, json_folder: JsonPath) -> None:
    """Remove a persisted sensor snapshot if it exists.

    Args:
        name: Sensor name used for contextual logging.
        filename: JSON file name within ``json_folder``.
        json_folder: Directory containing persisted sensor snapshots.
    """
    try:
        json_file_path: Path = Path(json_folder) / filename
        json_file_path.unlink()
    except OSError as e:
        _LOGGER.debug(
            "(%s) OSError removing JSON sensor file (%s): %s: %s",
            name,
            filename,
            type(e).__name__,
            e,
        )
    else:
        _LOGGER.debug("(%s) JSON sensor file removed: %s", name, filename)


def is_float(value: Any) -> bool:
    """Return whether a value can be safely converted to ``float``.

    Args:
        value: Candidate value to validate.

    Returns:
        ``True`` when ``float(value)`` succeeds and ``value`` is not ``None``.
    """
    if value is None:
        return False
    try:
        float(value)
    except ValueError, TypeError:
        return False
    else:
        return True


def write_sensor_to_json(
    sensor_attributes: MutableMapping[str, Any],
    name: str,
    filename: JsonPath,
    json_folder: JsonPath,
) -> None:
    """Persist sensor attributes while omitting non-JSON datetime objects.

    Args:
        sensor_attributes: Current Places sensor attribute mapping.
        name: Sensor name used for contextual logging.
        filename: JSON file name within ``json_folder``.
        json_folder: Directory where the snapshot should be written.
    """
    attributes = {k: v for k, v in sensor_attributes.items() if not isinstance(v, datetime)}
    try:
        json_file_path: Path = Path(json_folder) / filename
        with json_file_path.open("w") as jsonfile:
            json.dump(attributes, jsonfile)
    except (TypeError, ValueError) as e:
        _LOGGER.debug(
            "(%s) Error serializing sensor to JSON (%s): %s: %s",
            name,
            filename,
            type(e).__name__,
            e,
        )
        serializable_attributes = _coerce_json_attributes(attributes)
        try:
            with json_file_path.open("w") as jsonfile:
                json.dump(serializable_attributes, jsonfile)
        except OSError as write_error:
            _LOGGER.debug(
                "(%s) OSError writing sensor to JSON (%s): %s: %s",
                name,
                filename,
                type(write_error).__name__,
                write_error,
            )
    except OSError as e:
        _LOGGER.debug(
            "(%s) OSError writing sensor to JSON (%s): %s: %s",
            name,
            filename,
            type(e).__name__,
            e,
        )


def _coerce_json_attributes(attributes: MutableMapping[str, Any]) -> dict[str, Any]:
    """Convert non-JSON-serializable attribute values to strings.

    Args:
        attributes: Sensor attributes prepared for JSON persistence.

    Returns:
        Attribute mapping with values that ``json.dump`` can serialize.
    """
    serializable_attributes: dict[str, Any] = {}
    for key, value in attributes.items():
        try:
            json.dumps(value)
        except TypeError, ValueError:
            serializable_attributes[key] = str(value)
        else:
            serializable_attributes[key] = value
    return serializable_attributes


def clear_since_from_state(orig_state: str) -> str:
    """Remove the Places ``(since HH:MM)`` or ``(since MM/DD)`` suffix.

    Args:
        orig_state: Sensor state that may include a trailing ``since`` suffix.

    Returns:
        State string without the generated suffix.
    """
    return re.sub(r" \(since \d\d[:/]\d\d\)", "", orig_state)


def safe_truncate(val: object | None, max_len: int) -> str:
    """Convert a value to text and cap it to a maximum length.

    Args:
        val: Value to stringify. ``None`` is treated as an empty string.
        max_len: Maximum number of characters to return.

    Returns:
        String representation truncated to ``max_len`` characters.
    """
    s = str(val) if val is not None else ""
    return s[:max_len] if len(s) > max_len else s

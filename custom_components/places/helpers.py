"""Helper functions for places."""

from __future__ import annotations

from collections.abc import MutableMapping
import copy
from datetime import datetime
import json
import logging
from pathlib import Path
import re
from typing import Any

_LOGGER = logging.getLogger(__name__)


def create_json_folder(json_folder: str) -> None:
    """Create a folder for JSON sensor files if it does not exist."""
    try:
        Path(json_folder).mkdir(parents=True, exist_ok=True)
    except OSError as e:
        _LOGGER.warning(
            "OSError creating folder for JSON sensor files: %s: %s", type(e).__name__, e
        )


def get_dict_from_json_file(name: str, filename: str, json_folder: str) -> MutableMapping[str, Any]:
    """Read a JSON file and return its content as a dictionary."""
    sensor_attributes: MutableMapping[str, Any] = {}
    try:
        json_file_path: Path = Path(json_folder) / filename
        with json_file_path.open() as jsonfile:
            sensor_attributes = json.load(jsonfile)
    except OSError as e:
        _LOGGER.debug(
            "(%s) [Init] No JSON file to import (%s): %s: %s",
            name,
            filename,
            type(e).__name__,
            e,
        )
        return {}
    return sensor_attributes


def remove_json_file(name: Any, filename: Any, json_folder: Any) -> None:
    """Remove a JSON file from the specified folder."""
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
    """Check if the provided value can be converted to a float."""
    if value is not None:
        try:
            float(value)
        except ValueError:
            return False
        else:
            return True
    return False


def write_sensor_to_json(
    sensor_attributes: MutableMapping[str, Any],
    name: Any,
    filename: Any,
    json_folder: Any,
) -> None:
    """Write sensor attributes to a JSON file, removing datetime values."""

    attributes = copy.deepcopy(sensor_attributes)
    for k, v in list(attributes.items()):
        if isinstance(v, datetime):
            attributes.pop(k)
    try:
        json_file_path: Path = Path(json_folder) / filename
        with json_file_path.open("w") as jsonfile:
            json.dump(attributes, jsonfile)
    except OSError as e:
        _LOGGER.debug(
            "(%s) OSError writing sensor to JSON (%s): %s: %s",
            name,
            filename,
            type(e).__name__,
            e,
        )


def clear_since_from_state(orig_state: str) -> str:
    """Remove the 'since' part from the state string."""
    return re.sub(r" \(since \d\d[:/]\d\d\)", "", orig_state)

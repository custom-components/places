"""Parsing and formatting helpers for the Places integration."""

from __future__ import annotations

import re
from typing import Any


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

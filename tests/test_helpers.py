"""Unit tests for helper functions in the places custom component."""

from __future__ import annotations

import pytest

from custom_components.places import helpers
from custom_components.places.helpers import clear_since_from_state, safe_truncate


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

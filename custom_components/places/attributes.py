"""Attribute helpers used by Places entities.

This module owns the mutable internal attribute mapping and associated utility
helpers that were previously implemented directly on ``Places``.
"""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any, SupportsFloat, SupportsIndex, TypeVar

from .const import CONFIG_ATTRIBUTES_LIST, JSON_ATTRIBUTE_LIST, JSON_IGNORE_ATTRIBUTE_LIST

_AttrT = TypeVar("_AttrT", default=Any)


class PlacesAttributes:
    """Mutable container for Places internal attributes and helper accessors.

    The class centralizes value storage and conversion helpers while preserving
    the historic behavior currently relied upon by ``Places``.
    """

    def __init__(self, initial: MutableMapping[str, Any] | None = None) -> None:
        """Create a new attribute store.

        Args:
            initial: Initial mutable attribute mapping used for in-place storage.
        """
        self._internal_attr: MutableMapping[str, Any] = initial if initial is not None else {}

    @property
    def data(self) -> MutableMapping[str, Any]:
        """Return the backing mutable attribute mapping."""
        return self._internal_attr

    @data.setter
    def data(self, value: MutableMapping[str, Any]) -> None:
        """Replace the backing mapping for rollback and restore flows."""
        self._internal_attr = value

    def set(self, attr: str, value: object | None = None) -> None:
        """Store a key/value pair in the backing mapping.

        Args:
            attr: Attribute key to store.
            value: Value for the attribute.
        """
        if attr:
            self._internal_attr.update({attr: value})

    def clear(self, attr: str) -> None:
        """Drop a key from the backing mapping.

        Args:
            attr: Attribute key to remove.
        """
        self._internal_attr.pop(attr, None)

    def is_blank(self, attr: str) -> bool:
        """Return whether a value is considered blank.

        Args:
            attr: Attribute key to evaluate.

        Returns:
            ``True`` for missing values, ``None`` and empty string values. Numeric
            zero is treated as non-blank for compatibility with prior behavior.
        """
        if self._internal_attr.get(attr) or self._internal_attr.get(attr) == 0:
            return False
        return True

    def get(self, attr: str | None, default: _AttrT | None = None) -> _AttrT | None:
        """Return a stored value with optional fallback and blank handling.

        Args:
            attr: Attribute key to read. ``None`` returns ``None``.
            default: Optional fallback when the key is not present.

        Returns:
            Stored value, ``default`` when provided, or ``None`` when blank.
        """
        if attr is None or (default is None and self.is_blank(attr)):
            return None
        return self._internal_attr.get(attr, default)

    def safe_str(self, attr: str | None, default: object | None = None) -> str:
        """Return a safe string representation for an attribute value.

        Args:
            attr: Attribute key to convert.
            default: Optional fallback when missing.

        Returns:
            String value, or ``""`` on missing values or conversion failures.
        """
        value = self.get(attr) if default is None else self.get(attr, default)
        if value is not None:
            try:
                return str(value)
            except ValueError, TypeError:
                return ""
        return ""

    def safe_float(self, attr: str | None, default: object | None = None) -> float:
        """Return a safe float for a stored attribute value.

        Args:
            attr: Attribute key to convert.
            default: Optional fallback when missing.

        Returns:
            Float conversion result, or ``0.0`` when conversion is not possible.
        """
        value: object | None = self.get(attr) if default is None else self.get(attr, default)
        if value is None:
            return 0.0
        if not isinstance(value, str | bytes | bytearray | SupportsFloat | SupportsIndex):
            return 0.0
        try:
            return float(value)
        except TypeError, ValueError:
            return 0.0

    def safe_list(self, attr: str | None, default: object | None = None) -> list:
        """Return a list value or an empty list fallback.

        Args:
            attr: Attribute key to read.
            default: Optional fallback used only when missing.

        Returns:
            Stored list value, or ``[]`` when conversion is not possible.
        """
        value = self.get(attr) if default is None else self.get(attr, default)
        if not isinstance(value, list):
            return []
        return value

    def safe_dict(
        self, attr: str | None, default: MutableMapping[str, _AttrT] | None = None
    ) -> MutableMapping[str, _AttrT]:
        """Return a mutable mapping for an attribute or an empty mapping.

        Args:
            attr: Attribute key to read.
            default: Optional fallback value.

        Returns:
            Stored mapping or ``{}`` when not available.
        """
        value = self.get(attr) if default is None else self.get(attr, default)
        if not isinstance(value, MutableMapping):
            return {}
        return value

    def cleanup(self) -> None:
        """Remove blank values from the internal mapping."""
        for attr in list(self._internal_attr):
            if self.is_blank(attr):
                self.clear(attr)

    def import_json_attributes(self, json_attr: MutableMapping[str, Any]) -> None:
        """Populate runtime attributes from JSON while removing filtered keys.

        This performs the existing JSON import filtering contract used by
        ``Places.import_attributes_from_json``.

        Args:
            json_attr: Mutable mapping loaded from sensor JSON persistence.
        """
        for attr in JSON_ATTRIBUTE_LIST:
            if attr in json_attr:
                self.set(attr, json_attr.pop(attr, None))
        for attr in CONFIG_ATTRIBUTES_LIST + JSON_IGNORE_ATTRIBUTE_LIST:
            if attr in json_attr:
                json_attr.pop(attr, None)

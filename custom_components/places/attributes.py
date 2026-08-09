"""Attribute helpers used by Places entities.

This module owns the mutable internal attribute mapping and associated utility
helpers that were previously implemented directly on ``Places``.
"""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any, SupportsFloat, SupportsIndex, TypeVar

from .const import (
    CONFIG_ATTRIBUTES_LIST,
    PERSISTED_ATTRIBUTE_LIST,
    PERSISTENCE_IGNORE_ATTRIBUTE_LIST,
)

_AttrT = TypeVar("_AttrT", default=Any)


class PlacesAttributes:
    """Mutable container for Places internal attributes and helper accessors.

    The class centralizes value storage and conversion helpers for ``Places``.
    """

    def __init__(self, initial: MutableMapping[str, Any] | None = None) -> None:
        """Create a new attribute store.

        Args:
            initial (MutableMapping[str, Any] | None):
                Initial mutable attribute mapping used for in-place storage.
        """
        self._internal_attr: MutableMapping[str, Any] = initial if initial is not None else {}

    @property
    def data(self) -> MutableMapping[str, Any]:
        """Return the backing mutable attribute mapping.

        Returns:
            MutableMapping[str, Any]:
                Latest data published by the update coordinator.
        """
        return self._internal_attr

    @data.setter
    def data(self, value: MutableMapping[str, Any]) -> None:
        """Replace the backing mapping for rollback and restore flows.

        Args:
            value (MutableMapping[str, Any]):
                Replacement coordinator data published to entity consumers.
        """
        self._internal_attr = value

    def set(self, attr: str, value: object | None = None) -> None:
        """Store a key/value pair in the backing mapping.

        Args:
            attr (str):
                Attribute key to store.
            value (object | None):
                Value for the attribute.
        """
        if attr:
            self._internal_attr.update({attr: value})

    def clear(self, attr: str) -> None:
        """Drop a key from the backing mapping.

        Args:
            attr (str):
                Attribute key to remove.
        """
        self._internal_attr.pop(attr, None)

    def is_blank(self, attr: str) -> bool:
        """Return whether a value is considered blank.

        Args:
            attr (str):
                Attribute key to evaluate.

        Returns:
            bool:
                ``True`` for missing values, ``None`` and empty string values. Numeric
                zero is treated as non-blank.
        """
        val = self._internal_attr.get(attr)
        return not (val or val == 0)

    def get(self, attr: str | None, default: _AttrT | None = None) -> _AttrT | None:
        """Return a stored value with optional fallback and blank handling.

        Args:
            attr (str | None):
                Attribute key to read. ``None`` returns ``None``.
            default (_AttrT | None):
                Optional fallback when the key is not present.

        Returns:
            _AttrT | None:
                Stored value, ``default`` when provided, or ``None`` when blank.
        """
        if attr is None or (default is None and self.is_blank(attr)):
            return None
        return self._internal_attr.get(attr, default)

    def safe_str(self, attr: str | None, default: object | None = None) -> str:
        """Return a safe string representation for an attribute value.

        Args:
            attr (str | None):
                Attribute key to convert.
            default (object | None):
                Optional fallback when missing.

        Returns:
            str:
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
            attr (str | None):
                Attribute key to convert.
            default (object | None):
                Optional fallback when missing.

        Returns:
            float:
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
            attr (str | None):
                Attribute key to read.
            default (object | None):
                Optional fallback used only when missing.

        Returns:
            list:
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
            attr (str | None):
                Attribute key to read.
            default (MutableMapping[str, _AttrT] | None):
                Optional fallback value.

        Returns:
            MutableMapping[str, _AttrT]:
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

    def import_persisted_attributes(self, persisted_attr: MutableMapping[str, Any]) -> None:
        """Populate runtime attributes from persisted snapshot data.

        This performs the existing persisted-import filtering contract used by
        ``PlacesAttributes.import_persisted_attributes``.

        Args:
            persisted_attr (MutableMapping[str, Any]):
                Mutable mapping loaded from a persisted snapshot.
        """
        for attr in PERSISTED_ATTRIBUTE_LIST:
            if attr in persisted_attr:
                self.set(attr, persisted_attr.pop(attr, None))
        for attr in CONFIG_ATTRIBUTES_LIST + PERSISTENCE_IGNORE_ATTRIBUTE_LIST:
            if attr in persisted_attr:
                persisted_attr.pop(attr, None)

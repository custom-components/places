"""Shared syntax and source spans for Display options."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
import re
from typing import Literal

type SyntaxErrorKey = Literal["invalid_syntax", "bracket_mismatch"]

_LOGGER = logging.getLogger(__name__)
_DELIMITERS = re.compile(r"[][(),]")
_CLOSERS = {"]": "[", ")": "("}
_MARKERS = {"+", "-"}


@dataclass(frozen=True, slots=True)
class Identifier:
    """A token checked by validation, with its source span and field role."""

    name: str
    start: int
    end: int
    is_field: bool


@dataclass(slots=True)
class Filters:
    """Literal and attribute constraints on one display field."""

    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    include_attributes: dict[str, list[str]] = field(default_factory=dict)
    exclude_attributes: dict[str, list[str]] = field(default_factory=dict)


@dataclass(slots=True)
class Item:
    """One comma-separated item and the groups attached to its leading token."""

    start: int
    end: int = 0
    token: str = ""
    groups: dict[str, Group] = field(default_factory=dict)
    renderable: bool = True

    @property
    def fallback(self) -> list[Item]:
        """Return the nested fields to render when this field is unavailable.

        Returns:
            list[Item]:
                Fields in the fallback group, or an empty list when there is no group.
        """
        group = self.groups.get("[")
        return group.items if group else []

    def filters(self, source: str) -> Filters:
        """Interpret this item's filter group, skipping nested attribute predicates.

        Args:
            source (str): The original Display options expression.

        Returns:
            Filters:
                The literal and attribute filters to apply to the field.
        """
        filters = Filters()
        group = self.groups.get("(")
        if group is None:
            return filters

        include, values = group.filter_values(source)
        if include:
            filters.include = values
        else:
            filters.exclude = values

        for item in group.items:
            attribute_group = item.groups.get("(")
            if attribute_group is None:
                continue
            attribute_source = source[item.start : item.end]
            if attribute_source.count("(") > 1 or any(
                "(" in value.groups for value in attribute_group.items
            ):
                _LOGGER.error("Parenthesis Mismatch: %s", source[item.start : item.end].strip())
                continue
            include, values = attribute_group.filter_values(source, attribute=True)
            attributes = filters.include_attributes if include else filters.exclude_attributes
            attributes[item.token] = values
        return filters


@dataclass(slots=True)
class Group:
    """A list of display fields or filter values between delimiters."""

    opener: str
    items: list[Item]
    in_literal: bool = False
    stopped: bool = False

    def filter_values(self, source: str, *, attribute: bool = False) -> tuple[bool, list[str]]:
        """Return the include mode and literal values in a filter group.

        Args:
            source (str): The original Display options expression.
            attribute (bool):
                Whether values are compared against an attribute filter.

        Returns:
            tuple[bool, list[str]]:
                The inclusion mode and normalized literal values.
        """
        literals = [
            None if "(" in item.groups else source[item.start : item.end].strip()
            for item in self.items
        ]
        first = literals[0]
        values = [
            value.lower().strip("'\"") if attribute else value.lower()
            for value in literals[int(first in _MARKERS) :]
            if value is not None and (value or attribute)
        ]
        return first != "-", values


@dataclass(slots=True)
class DisplayOptions:
    """Parsed options, retaining exact source positions for stored-rule rewrites."""

    source: str
    items: list[Item]
    identifiers: list[Identifier]
    event_options: list[str]
    has_groups: bool
    bracket_mismatch: bool
    error: SyntaxErrorKey | None

    def top_level_options(self) -> list[str]:
        """Return source text for each top-level option, including surrounding whitespace.

        Returns:
            list[str]:
                Top-level options in source order with nested commas intact.
        """
        return [self.source[item.start : item.end] for item in self.items]


def parse_display_options(source: str) -> DisplayOptions:
    """Interpret list boundaries, delimiters, and token roles in one pass.

    The parsed structure is available independently of new-submission validation.
    This lets existing entries keep permissive basic lists and legacy identifiers.

    Args:
        source (str):
            Stored or newly submitted Display options.

    Returns:
        DisplayOptions:
            The parsed options, with source spans and syntax diagnostics.
    """
    root = Group("", [Item(0)])
    stack = [root]
    identifiers: list[Identifier] = []
    event_options: list[str] = []
    event_option_start = 0
    chunk_start = 0
    previous = ""
    has_groups = False
    bracket_mismatch = False
    structural_error: SyntaxErrorKey | None = None
    invalid_syntax = False

    for match in _DELIMITERS.finditer(source):
        delimiter = match[0]
        index = match.start()
        group = stack[-1]
        item = group.items[-1]
        chunk = source[chunk_start:index]
        token = chunk.strip()
        if not item.groups:
            item.token = token
        opening = delimiter in "[("
        if token and token not in _MARKERS and (opening or group.opener != "("):
            start = chunk_start + len(chunk) - len(chunk.lstrip())
            # Validation historically checks bracketed literal text in pieces.
            # Migration can rewrite only display fields and attribute-filter names.
            is_field = not group.in_literal and (group.opener != "(" or delimiter == "(")
            identifiers.append(Identifier(token, start, start + len(token), is_field))

        if group.opener != "(" and not group.in_literal:
            repeated_group = opening and delimiter in item.groups
            if repeated_group:
                # Reject new submissions while preserving the stored-rule parse.
                invalid_syntax = True
            if (token and item.groups) or repeated_group:
                group.stopped = True

        # Structural errors retain precedence over comma and token syntax errors.
        if opening:
            has_groups = True
            if not token and (not index or source[index - 1] not in "])"):
                structural_error = structural_error or "invalid_syntax"
            in_literal = group.in_literal or (group.opener == "(" and delimiter == "[")
            nested = Group(delimiter, [Item(index + 1)], in_literal)
            if not group.stopped:
                item.groups.setdefault(delimiter, nested)
            stack.append(nested)
        elif delimiter in _CLOSERS:
            if group.opener != _CLOSERS[delimiter]:
                bracket_mismatch = True
                structural_error = structural_error or "bracket_mismatch"
            elif len(stack) > 1:
                stack.pop()
            item.end = index
        else:
            item.end = index
            group.items.append(Item(index + 1, renderable=not group.stopped))
            # The event formatter has historically matched comma-delimited text.
            event_options.append(source[event_option_start:index].strip())
            event_option_start = index + 1

        invalid_syntax |= (
            " " in token
            or (not token and delimiter == "," and previous in {",", "[", "("})
            or (not token and delimiter in _CLOSERS and previous == ",")
        )
        previous = delimiter
        chunk_start = index + 1

    chunk = source[chunk_start:]
    token = chunk.strip()
    for group in stack:
        group.items[-1].end = len(source)
    group = stack[-1]
    if not group.items[-1].groups:
        group.items[-1].token = token
    if token and token not in _MARKERS and group.opener != "(":
        start = chunk_start + len(chunk) - len(chunk.lstrip())
        identifiers.append(Identifier(token, start, start + len(token), not group.in_literal))
    if len(stack) > 1:
        bracket_mismatch = True
        structural_error = structural_error or "bracket_mismatch"

    error = structural_error
    if error is None and (invalid_syntax or " " in token):
        error = "invalid_syntax"
    if source:
        event_options.append(source[event_option_start:].strip())
    return DisplayOptions(
        source, root.items, identifiers, event_options, has_groups, bracket_mismatch, error
    )

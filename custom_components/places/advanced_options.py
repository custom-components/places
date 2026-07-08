"""Parser for advanced options in a sensor configuration.

This module provides functionality to parse complex sensor options
that may include brackets, parentheses, and commas, allowing for
flexible configuration of sensor states.
"""

from __future__ import annotations

from collections.abc import MutableMapping
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.const import CONF_NAME

from .const import (
    ATTR_DEVICETRACKER_ZONE,
    ATTR_DEVICETRACKER_ZONE_NAME,
    ATTR_PLACE_CATEGORY,
    ATTR_PLACE_TYPE,
    ATTR_STREET,
    ATTR_STREET_NUMBER,
    ATTR_STREET_REF,
    DISPLAY_OPTIONS_MAP,
)

if TYPE_CHECKING:
    from .coordinator import PlacesUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


class AdvancedOptionsParser:
    """Parse bracketed and filtered display options into a sensor state."""

    def __init__(self, sensor: PlacesUpdateCoordinator, curr_options: str) -> None:
        """Initialize the advanced-options parser.

        Args:
            sensor: Places coordinator that provides attribute access helpers.
            curr_options: Raw advanced display option expression.
        """
        self.sensor = sensor
        self.curr_options = curr_options
        self.state_list: list = []
        self._street_num_i = -1
        self._street_i = -1
        self._temp_i: int = 0
        self._processed_options: set[str] = set()

    async def build_from_advanced_options(self, curr_options: str | None = None) -> None:
        """Parse an option expression and append matching values to ``state_list``.

        Args:
            curr_options: Option expression to parse. When omitted, the parser's
                configured root expression is used and recursion tracking is
                reset.
        """
        if curr_options is None:
            curr_options = self.curr_options
            self._processed_options = set()
        curr_options = curr_options.strip()
        # Prevent infinite recursion for any substring
        if curr_options in self._processed_options:
            _LOGGER.error("Infinite recursion detected for options: %s", curr_options)
            return
        self._processed_options.add(curr_options)
        if not await self.do_brackets_and_parens_count_match(curr_options) or not curr_options:
            return
        if "[" in curr_options or "(" in curr_options:
            await self.process_bracket_or_parens(curr_options)
            return
        if "," in curr_options:
            await self.process_only_commas(curr_options)
            return
        await self.process_single_term(curr_options)

    async def build_next_option(self, next_opt: str | None) -> None:
        """Continue parsing after a comma-prefixed next expression."""
        if not next_opt or len(next_opt) <= 1 or next_opt[0] != ",":
            return
        next_opt = next_opt[1:].strip()
        if next_opt:
            await self.build_from_advanced_options(next_opt)

    async def do_brackets_and_parens_count_match(self, curr_options: str) -> bool:
        """Check whether an option expression has balanced delimiters.

        Args:
            curr_options: Option expression to inspect.

        Returns:
            ``True`` when opening and closing brackets and parentheses have the
            same counts.
        """
        if curr_options.count("[") != curr_options.count("]"):
            _LOGGER.error("Bracket Count Mismatch: %s", curr_options)
            return False
        if curr_options.count("(") != curr_options.count(")"):
            _LOGGER.error("Parenthesis Count Mismatch: %s", curr_options)
            return False
        return True

    async def get_option_state(
        self,
        opt: str,
        incl: list | None = None,
        excl: list | None = None,
        incl_attr: MutableMapping[str, Any] | None = None,
        excl_attr: MutableMapping[str, Any] | None = None,
    ) -> str | None:
        """Return an option value after applying zone and filter constraints.

        Args:
            opt: Display option name to resolve through ``DISPLAY_OPTIONS_MAP``.
            incl: Lowercase option values that are allowed.
            excl: Lowercase option values that are suppressed.
            incl_attr: Attribute filters that must match before ``opt`` is used.
            excl_attr: Attribute filters that suppress ``opt`` when matched.

        Returns:
            Resolved display string, or ``None`` when the option is blank,
            outside its zone context, or filtered out.
        """
        incl = [] if incl is None else incl
        excl = [] if excl is None else excl
        incl_attr = {} if incl_attr is None else incl_attr
        excl_attr = {} if excl_attr is None else excl_attr
        if opt:
            opt = str(opt).lower().strip()
        _LOGGER.debug("(%s) [get_option_state] Option: %s", self.sensor.get_attr(CONF_NAME), opt)
        out: str | None = self.sensor.get_attr(DISPLAY_OPTIONS_MAP.get(opt))
        if (
            DISPLAY_OPTIONS_MAP.get(opt) in {ATTR_DEVICETRACKER_ZONE, ATTR_DEVICETRACKER_ZONE_NAME}
            and not await self.sensor.in_zone()
        ):
            out = None
        _LOGGER.debug("(%s) [get_option_state] State: %s", self.sensor.get_attr(CONF_NAME), out)
        _LOGGER.debug(
            "(%s) [get_option_state] incl list: %s", self.sensor.get_attr(CONF_NAME), incl
        )
        _LOGGER.debug(
            "(%s) [get_option_state] excl list: %s", self.sensor.get_attr(CONF_NAME), excl
        )
        _LOGGER.debug(
            "(%s) [get_option_state] incl_attr dict: %s", self.sensor.get_attr(CONF_NAME), incl_attr
        )
        _LOGGER.debug(
            "(%s) [get_option_state] excl_attr dict: %s", self.sensor.get_attr(CONF_NAME), excl_attr
        )
        if out:
            if (incl and str(out).strip().lower() not in incl) or (
                excl and str(out).strip().lower() in excl
            ):
                out = None
            if incl_attr:
                for attr, states in incl_attr.items():
                    _LOGGER.debug(
                        "(%s) [get_option_state] incl_attr: %s / State: %s",
                        self.sensor.get_attr(CONF_NAME),
                        attr,
                        self.sensor.get_attr(DISPLAY_OPTIONS_MAP.get(attr)),
                    )
                    _LOGGER.debug(
                        "(%s) [get_option_state] incl_states: %s",
                        self.sensor.get_attr(CONF_NAME),
                        states,
                    )
                    map_attr: str | None = DISPLAY_OPTIONS_MAP.get(attr)
                    if (
                        not map_attr
                        or self.sensor.is_attr_blank(map_attr)
                        or self.sensor.get_attr(map_attr) not in states
                    ):
                        out = None
            if excl_attr:
                for attr, states in excl_attr.items():
                    _LOGGER.debug(
                        "(%s) [get_option_state] excl_attr: %s / State: %s",
                        self.sensor.get_attr(CONF_NAME),
                        attr,
                        self.sensor.get_attr(DISPLAY_OPTIONS_MAP.get(attr)),
                    )
                    _LOGGER.debug(
                        "(%s) [get_option_state] excl_states: %s",
                        self.sensor.get_attr(CONF_NAME),
                        states,
                    )
                    if self.sensor.get_attr(DISPLAY_OPTIONS_MAP.get(attr)) in states:
                        out = None
            _LOGGER.debug(
                "(%s) [get_option_state] State after incl/excl: %s",
                self.sensor.get_attr(CONF_NAME),
                out,
            )
        if out:
            if out == out.lower() and (
                DISPLAY_OPTIONS_MAP.get(opt) == ATTR_DEVICETRACKER_ZONE_NAME
                or DISPLAY_OPTIONS_MAP.get(opt) == ATTR_PLACE_TYPE
                or DISPLAY_OPTIONS_MAP.get(opt) == ATTR_PLACE_CATEGORY
            ):
                out = out.title()
            out = out.strip()
            if (
                DISPLAY_OPTIONS_MAP.get(opt) == ATTR_STREET
                or DISPLAY_OPTIONS_MAP.get(opt) == ATTR_STREET_REF
            ):
                self._street_i = self._temp_i
                # _LOGGER.debug(
                #     "(%s) [get_option_state] street_i: %s",
                #     self.sensor.get_attr(CONF_NAME),
                #     self._street_i,
                # )
            if DISPLAY_OPTIONS_MAP.get(opt) == ATTR_STREET_NUMBER:
                self._street_num_i = self._temp_i
                # _LOGGER.debug(
                #     "(%s) [get_option_state] street_num_i: %s",
                #     self.sensor.get_attr(CONF_NAME),
                #     self._street_num_i,
                # )
            self._temp_i += 1
            return out
        return None

    async def process_bracket_or_parens(self, curr_options: str) -> None:
        """Process the next advanced option segment with filters or fallback text.

        Args:
            curr_options: Remaining option expression containing at least one
                bracket, parenthesis, or comma.
        """
        comma_num: int = curr_options.find(",")
        bracket_num: int = curr_options.find("[")
        paren_num: int = curr_options.find("(")
        none_opt: str | None = None
        next_opt: str | None = None

        # Comma is first symbol
        if (
            comma_num != -1
            and (bracket_num == -1 or comma_num < bracket_num)
            and (paren_num == -1 or comma_num < paren_num)
        ):
            opt = curr_options[:comma_num]
            if opt:
                ret_state = await self.get_option_state(opt.strip())
                if ret_state:
                    self.state_list.append(ret_state)
            next_opt = curr_options[(comma_num + 1) :]
            if next_opt:
                await self.build_from_advanced_options(next_opt.strip())
            return

        # Bracket is first symbol
        if (
            bracket_num != -1
            and (comma_num == -1 or bracket_num < comma_num)
            and (paren_num == -1 or bracket_num < paren_num)
        ):
            opt = curr_options[:bracket_num]
            none_opt, next_opt = await self.parse_bracket(curr_options[bracket_num:])
            incl: list = []
            excl: list = []
            incl_attr: MutableMapping[str, Any] = {}
            excl_attr: MutableMapping[str, Any] = {}
            if next_opt and len(next_opt) > 1 and next_opt[0] == "(":
                incl, excl, incl_attr, excl_attr, next_opt = await self.parse_parens(next_opt)
            if opt:
                ret_state = await self.get_option_state(
                    opt.strip(), incl, excl, incl_attr, excl_attr
                )
                if ret_state:
                    self.state_list.append(ret_state)
                elif none_opt:
                    await self.build_from_advanced_options(none_opt.strip())
            await self.build_next_option(next_opt)
            return

        # Parenthesis is first symbol
        if (
            paren_num != -1
            and (comma_num == -1 or paren_num < comma_num)
            and (bracket_num == -1 or paren_num < bracket_num)
        ):
            opt = curr_options[:paren_num]
            incl, excl, incl_attr, excl_attr, next_opt = await self.parse_parens(
                curr_options[paren_num:]
            )
            none_opt = None
            if next_opt and len(next_opt) > 1 and next_opt[0] == "[":
                none_opt, next_opt = await self.parse_bracket(next_opt)
            if opt:
                ret_state = await self.get_option_state(
                    opt.strip(), incl, excl, incl_attr, excl_attr
                )
                if ret_state:
                    self.state_list.append(ret_state)
                elif none_opt:
                    await self.build_from_advanced_options(none_opt.strip())
            await self.build_next_option(next_opt)

    async def process_only_commas(self, curr_options: str) -> None:
        """Append values for a comma-separated list of simple options.

        Args:
            curr_options: Option names separated by commas.
        """
        for opt in curr_options.split(","):
            if opt:
                ret_state = await self.get_option_state(opt.strip())
                if ret_state:
                    self.state_list.append(ret_state)

    async def process_single_term(self, curr_options: str) -> None:
        """Append a resolved value for one simple option name.

        Args:
            curr_options: Single display option name.
        """
        ret_state = await self.get_option_state(curr_options.strip())
        if ret_state:
            self.state_list.append(ret_state)

    def parse_attribute_parentheses(self, item: str) -> tuple[str, list[str], bool]:
        """Parse an attribute-scoped include/exclude filter.

        Args:
            item: Filter expression such as ``place_type(cafe,park)`` or
                ``place_type(-,house)``.

        Returns:
            Attribute option name, normalized filter values, and ``True`` for
            include mode or ``False`` for exclude mode.
        """
        paren_attr = item[: item.find("(")]
        paren_attr_first = True
        paren_attr_incl = True
        paren_attr_list = []
        for attr_item in item[(item.find("(") + 1) : item.find(")")].split(","):
            if paren_attr_first:
                paren_attr_first = False
                if attr_item == "-":
                    paren_attr_incl = False
                    continue
                if attr_item == "+":
                    continue
            cleaned = str(attr_item).strip().lower().strip("'\"")
            paren_attr_list.append(cleaned)
        return paren_attr, paren_attr_list, paren_attr_incl

    async def parse_parens(
        self, curr_options: str
    ) -> tuple[list, list, MutableMapping[str, Any], MutableMapping[str, Any], str | None]:
        """Parse value filters from a parenthesized expression.

        Args:
            curr_options: Expression beginning with ``(``.

        Returns:
            Included values, excluded values, included attribute filters,
            excluded attribute filters, and the remaining expression after the
            closing parenthesis.
        """
        incl, excl = [], []
        incl_attr, excl_attr = {}, {}
        incl_excl_list = []
        empty_paren = False
        next_opt = None
        paren_count = 1
        close_paren_num = 0
        last_comma = -1
        if curr_options[0] == "(":
            curr_options = curr_options[1:]
        if curr_options and curr_options[0] == ")":
            empty_paren = True
            close_paren_num = 0
        else:
            for i, c in enumerate(curr_options):
                if c in {",", ")"} and paren_count == 1:
                    incl_excl_list.append(curr_options[(last_comma + 1) : i].strip())
                    last_comma = i
                if c == "(":
                    paren_count += 1
                elif c == ")":
                    paren_count -= 1
                if paren_count == 0:
                    close_paren_num = i
                    break

        if close_paren_num > 0 and paren_count == 0 and incl_excl_list:
            paren_first = True
            paren_incl = True
            for item in incl_excl_list:
                if paren_first:
                    paren_first = False
                    if item == "-":
                        paren_incl = False
                        continue
                    if item == "+":
                        continue
                if item:
                    if "(" in item:
                        if ")" not in item or item.count("(") > 1 or item.count(")") > 1:
                            _LOGGER.error("Parenthesis Mismatch: %s", item)
                            continue
                        paren_attr, paren_attr_list, paren_attr_incl = (
                            self.parse_attribute_parentheses(item)
                        )
                        if paren_attr_incl:
                            incl_attr.update({paren_attr: paren_attr_list})
                        else:
                            excl_attr.update({paren_attr: paren_attr_list})
                    elif paren_incl:
                        incl.append(str(item).strip().lower())
                    else:
                        excl.append(str(item).strip().lower())
        elif not empty_paren:
            _LOGGER.error("Parenthesis Mismatch: %s", curr_options)
        next_opt = curr_options[(close_paren_num + 1) :]
        return incl, excl, incl_attr, excl_attr, next_opt

    async def parse_bracket(self, curr_options: str) -> tuple[str | None, str | None]:
        """Parse a bracketed fallback expression.

        Args:
            curr_options: Expression beginning with ``[``.

        Returns:
            Fallback option expression to use when the primary option is blank,
            plus the remaining expression after the closing bracket.
        """
        empty_bracket: bool = False
        none_opt: str | None = None
        next_opt: str | None = None
        bracket_count: int = 1
        close_bracket_num: int = 0
        if curr_options[0] == "[":
            curr_options = curr_options[1:]
        if curr_options and curr_options[0] == "]":
            empty_bracket = True
            close_bracket_num = 0
            bracket_count = 0
        else:
            for i, c in enumerate(curr_options):
                if c == "[":
                    bracket_count += 1
                elif c == "]":
                    bracket_count -= 1
                if bracket_count == 0:
                    close_bracket_num = i
                    break

        if empty_bracket or (close_bracket_num > 0 and bracket_count == 0):
            none_opt = curr_options[:close_bracket_num].strip()
            next_opt = curr_options[(close_bracket_num + 1) :].strip()
        else:
            _LOGGER.error("Bracket Mismatch Error: %s", curr_options)
        return none_opt, next_opt

    async def compile_state(self) -> str:
        """Join resolved option values into the final sensor state.

        Returns:
            Comma-separated state string, with street number and street joined
            by a space when they are adjacent.
        """
        self._street_num_i += 1
        first = True
        result = ""
        for i, out in enumerate(self.state_list):
            if out:
                out = out.strip()
                if first:
                    result = str(out)
                    first = False
                else:
                    if i == self._street_i and i == self._street_num_i:
                        result += " "
                    else:
                        result += ", "
                    result += out
        return result

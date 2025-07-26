"""Parser for advanced options in a sensor configuration.

This module provides functionality to parse complex sensor options
that may include brackets, parentheses, and commas, allowing for
flexible configuration of sensor states.
"""

from __future__ import annotations

from collections.abc import MutableMapping
import logging
from typing import Any

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
from .sensor import Places

_LOGGER = logging.getLogger(__name__)


class AdvancedOptionsParser:
    """Parser for advanced options in a sensor configuration."""

    def __init__(self, sensor: Places):
        """Initialize the parser with a sensor instance."""
        self.sensor = sensor
        self.state_list: list = []
        self.street_num_i = -1
        self.street_i = -1
        self._temp_i: int = 0

    async def build_from_advanced_options(self, curr_options: str) -> None:
        """Parse the current options string and build the state list."""
        if not await self.do_brackets_and_parens_count_match(curr_options) or not curr_options:
            return
        if "[" in curr_options or "(" in curr_options:
            await self.process_bracket_or_parens(curr_options)
            return
        if "," in curr_options:
            await self.process_only_commas(curr_options)
            return
        await self.process_single_term(curr_options)

    async def do_brackets_and_parens_count_match(self, curr_options: str) -> bool:
        """Check if the brackets and parentheses in the options string match."""
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
        """Get the state of a display option."""
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
            if (
                incl
                and str(out).strip().lower() not in incl
                or excl
                and str(out).strip().lower() in excl
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
        """Process options with brackets or parentheses."""
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
            if next_opt and len(next_opt) > 1 and next_opt[0] == ",":
                next_opt = next_opt[1:]
                if next_opt:
                    await self.build_from_advanced_options(next_opt.strip())
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
            if next_opt and len(next_opt) > 1 and next_opt[0] == ",":
                next_opt = next_opt[1:]
                if next_opt:
                    await self.build_from_advanced_options(next_opt.strip())

    async def process_only_commas(self, curr_options: str) -> None:
        """Process options that are separated by commas."""
        for opt in curr_options.split(","):
            if opt:
                ret_state = await self.get_option_state(opt.strip())
                if ret_state:
                    self.state_list.append(ret_state)

    async def process_single_term(self, curr_options: str) -> None:
        """Process a single term option."""
        ret_state = await self.get_option_state(curr_options.strip())
        if ret_state:
            self.state_list.append(ret_state)

    async def parse_parens(
        self, curr_options: str
    ) -> tuple[list, list, MutableMapping[str, Any], MutableMapping[str, Any], str | None]:
        """Parse options within parentheses and return included and excluded items."""
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
                            paren_attr_list.append(str(attr_item).strip().lower())
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
        """Parse options within brackets and return the option and the next part."""
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
        """Compile the state list into a formatted string."""
        self.street_num_i += 1
        first = True
        result = ""
        for i, out in enumerate(self.state_list):
            if out:
                out = out.strip()
                if first:
                    result = str(out)
                    first = False
                else:
                    if i == self.street_i and i == self.street_num_i:
                        result += " "
                    else:
                        result += ", "
                    result += out
        return result

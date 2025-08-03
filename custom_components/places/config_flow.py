"""Config Flow for places integration."""

from __future__ import annotations

from collections.abc import MutableMapping
import logging
import re
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import (
    ATTR_FRIENDLY_NAME,
    CONF_API_KEY,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_NAME,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector

from .const import (
    CONF_DATE_FORMAT,
    CONF_DEVICETRACKER_ID,
    CONF_DISPLAY_OPTIONS,
    CONF_EXTENDED_ATTR,
    CONF_HOME_ZONE,
    CONF_LANGUAGE,
    CONF_MAP_PROVIDER,
    CONF_MAP_ZOOM,
    CONF_SHOW_TIME,
    CONF_USE_GPS,
    DEFAULT_DATE_FORMAT,
    DEFAULT_DISPLAY_OPTIONS,
    DEFAULT_EXTENDED_ATTR,
    DEFAULT_HOME_ZONE,
    DEFAULT_MAP_PROVIDER,
    DEFAULT_MAP_ZOOM,
    DEFAULT_SHOW_TIME,
    DEFAULT_USE_GPS,
    DISPLAY_OPTIONS_MAP,
    DOMAIN,
    HOME_LOCATION_DOMAINS,
    TRACKING_DOMAINS,
    TRACKING_DOMAINS_NEED_LATLONG,
)

_LOGGER: logging.Logger = logging.getLogger(__name__)
MAP_PROVIDER_OPTIONS: list[str] = ["apple", "google", "osm"]
STATE_OPTIONS: list[str] = ["zone, place", "formatted_place", "zone_name, place"]
DATE_FORMAT_OPTIONS: list[str] = ["mm/dd", "dd/mm"]
MAP_ZOOM_MIN: int = 1
MAP_ZOOM_MAX: int = 20
COMPONENT_CONFIG_URL: str = "https://github.com/custom-components/places#configuration-options"

# Note the input displayed to the user will be translated. See the
# translations/<lang>.json files. See here for further information:
# https://developers.home-assistant.io/docs/config_entries_config_flow_handler/#translations


def get_devicetracker_id_entities(
    hass: HomeAssistant, current_entity: str | None = None
) -> list[selector.SelectOptionDict]:
    """Get the list of valid entities. For sensors, only include ones with latitude and longitude attributes."""
    dt_list: list[selector.SelectOptionDict] = []
    for dom in TRACKING_DOMAINS:
        # _LOGGER.debug(f"Geting entities for domain: {dom}")
        for ent in hass.states.async_all(dom):
            if dom not in TRACKING_DOMAINS_NEED_LATLONG or (
                CONF_LATITUDE in hass.states.get(ent.entity_id).attributes
                and CONF_LONGITUDE in hass.states.get(ent.entity_id).attributes
            ):
                # _LOGGER.debug("Entity: %s", ent)
                dt_list.extend(
                    [
                        selector.SelectOptionDict(
                            value=str(ent.entity_id),
                            label=f"{ent.attributes.get(ATTR_FRIENDLY_NAME)} ({ent.entity_id})",
                        )
                    ]
                )
    # Optional: Include the current entity in the list as well.
    if current_entity is not None:
        # _LOGGER.debug("current_entity: %s", current_entity)
        dt_list_entities: list[str] = [d["value"] for d in dt_list]
        if current_entity not in dt_list_entities and hass.states.get(current_entity) is not None:
            if (
                ATTR_FRIENDLY_NAME in hass.states.get(current_entity).attributes
                and hass.states.get(current_entity).attributes.get(ATTR_FRIENDLY_NAME) is not None
            ):
                current_name: str = hass.states.get(current_entity).attributes.get(
                    ATTR_FRIENDLY_NAME
                )
                # _LOGGER.debug("current_name: %s", current_name)
                dt_list.append(
                    selector.SelectOptionDict(
                        value=str(current_entity),
                        label=f"{current_name} ({current_entity})",
                    )
                )
            else:
                dt_list.append(
                    selector.SelectOptionDict(
                        value=str(current_entity),
                        label=str(current_entity),
                    )
                )
    if dt_list:
        dt_list_sorted: list[selector.SelectOptionDict] = sorted(
            dt_list, key=lambda d: d["label"].casefold()
        )
    else:
        dt_list_sorted = []

    # _LOGGER.debug("Devicetracker_id name/entities including sensors with lat/long: %s", dt_list_sorted)
    return dt_list_sorted


def get_home_zone_entities(hass: HomeAssistant) -> list[selector.SelectOptionDict]:
    """Get the list of valid zones."""
    zone_list: list[selector.SelectOptionDict] = []
    for dom in HOME_LOCATION_DOMAINS:
        # _LOGGER.debug(f"Geting entities for domain: %s", dom)
        for ent in hass.states.async_all(dom):
            # _LOGGER.debug("Entity: %s", ent)
            zone_list.extend(
                [
                    selector.SelectOptionDict(
                        value=str(ent.entity_id),
                        label=f"{ent.attributes.get(ATTR_FRIENDLY_NAME)} ({ent.entity_id})",
                    )
                ]
            )
    if zone_list:
        zone_list_sorted: list[selector.SelectOptionDict] = sorted(
            zone_list, key=lambda d: d["label"].casefold()
        )
    else:
        zone_list_sorted = []
    # _LOGGER.debug("Zones: %s", zone_list_sorted)
    return zone_list_sorted


def _validate_brackets(display_options: str, errors: dict[str, Any]) -> bool:
    stack = []
    last_token = ""
    i = 0
    while i < len(display_options):
        c = display_options[i]
        if c in "[(":
            valid_before = last_token.strip()
            if not valid_before and i > 0 and display_options[i - 1] in "])":
                pass
            elif not valid_before:
                _LOGGER.error(
                    "Invalid syntax: Expected an item before '%s' at position %d in '%s'.",
                    c,
                    i,
                    display_options,
                )
                errors["base"] = "invalid_syntax"
                return False
            elif valid_before[-1] in ",[":
                _LOGGER.error(
                    "Invalid syntax: Unexpected '%s' after '%s' before '%s' at position %d in '%s'.",
                    c,
                    valid_before[-1],
                    c,
                    i,
                    display_options,
                )
                errors["base"] = "invalid_syntax"
                return False
            stack.append(c)
            last_token = ""
        elif c in "])":
            if not stack:
                _LOGGER.error(
                    "Bracket mismatch: Unmatched closing '%s' at position %d in '%s'.",
                    c,
                    i,
                    display_options,
                )
                errors["base"] = "bracket_mismatch"
                return False
            expected = "[" if c == "]" else "("
            if stack[-1] != expected:
                _LOGGER.error(
                    "Bracket mismatch: Expected closing '%s' but found '%s' at position %d in '%s'.",
                    stack[-1],
                    c,
                    i,
                    display_options,
                )
                errors["base"] = "bracket_mismatch"
                return False
            stack.pop()
            last_token = ""
        elif c == ",":
            last_token = ""
        else:
            last_token += c
        i += 1
    if stack:
        _LOGGER.error(
            "Bracket mismatch: Unmatched opening '%s' in '%s'.", stack[-1], display_options
        )
        errors["base"] = "bracket_mismatch"
        return False
    return True


def _validate_comma_syntax(display_options: str, errors: dict[str, Any]) -> bool:
    if re.search(r"(,\s*,)", display_options):
        _LOGGER.error("Invalid syntax: Empty item between commas in '%s'.", display_options)
        errors["base"] = "invalid_syntax"
        return False
    if re.search(r"[\[\(]\s*,", display_options) or re.search(r",\s*[\]\)]", display_options):
        _LOGGER.error(
            "Invalid syntax: Leading or trailing comma in brackets/parentheses in '%s'.",
            display_options,
        )
        errors["base"] = "invalid_syntax"
        return False
    return True


def _validate_option_names(display_options: str, errors: dict[str, Any]) -> bool:
    tokens = re.split(r"[\[\]\(\),]", display_options)
    for token in tokens:
        if " " in token.strip() and token.strip() not in ("", "-", "+"):
            _LOGGER.error(
                "Invalid syntax: Spaces in option name '%s' in '%s'.", token, display_options
            )
            errors["base"] = "invalid_syntax"
            return False
    return True


def _validate_known_options(display_options: str, errors: dict[str, Any]) -> bool:
    valid_options = set(DISPLAY_OPTIONS_MAP.keys())
    i = 0
    token = ""
    while i < len(display_options):
        c = display_options[i]
        if c in "[(":
            # Check the token before the bracket/paren
            t = token.strip()
            if t and t not in valid_options and not re.match(r"[-+]", t):
                _LOGGER.error("Invalid option name '%s' in '%s'.", t, display_options)
                errors["base"] = "invalid_option"
                return False
            token = ""
        elif c == ",":
            # Check top-level comma-separated tokens
            t = token.strip()
            if t and t not in valid_options and not re.match(r"[-+]", t):
                _LOGGER.error("Invalid option name '%s' in '%s'.", t, display_options)
                errors["base"] = "invalid_option"
                return False
            token = ""
        elif c in "])":
            token = ""
        else:
            token += c
        i += 1
    # Check last token
    t = token.strip()
    if t and t not in valid_options and not re.match(r"[-+]", t):
        _LOGGER.error("Invalid option name '%s' in '%s'.", t, display_options)
        errors["base"] = "invalid_option"
        return False
    return True


async def validate_display_options(display_options: str, errors: dict[str, Any]) -> dict[str, Any]:
    """Validate the display options string for correct syntax and allowed characters."""

    # Only run advanced validation if brackets or parentheses are present
    if "[" in display_options or "(" in display_options:
        # Check bracket/parenthesis matching
        if not _validate_brackets(display_options, errors):
            return errors

        # Check for empty items and comma placement
        if not _validate_comma_syntax(display_options, errors):
            return errors

        # Check for spaces in option names
        if not _validate_option_names(display_options, errors):
            return errors

        # Validate against DISPLAY_OPTIONS_MAP
        if not _validate_known_options(display_options, errors):
            return errors

    # For basic options, no advanced validation needed
    return errors


class PlacesConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config Flow for places integration."""

    VERSION = 1

    async def async_step_user(
        self, user_input: MutableMapping[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""

        errors: dict[str, Any] = {}
        if user_input is not None:
            errors = await validate_display_options(
                display_options=user_input.get(CONF_DISPLAY_OPTIONS, ""),
                errors=errors,
            )

            if not errors:
                _LOGGER.debug("[New Sensor] user_input: %s", user_input)
                return self.async_create_entry(title=user_input[CONF_NAME], data=user_input)

        devicetracker_id_list: list[selector.SelectOptionDict] = get_devicetracker_id_entities(
            self.hass
        )
        zone_list = get_home_zone_entities(self.hass)
        # _LOGGER.debug("Trackable entities with lat/long: %s", devicetracker_id_list)
        DATA_SCHEMA: vol.Schema = vol.Schema(
            {
                vol.Required(CONF_NAME): str,
                vol.Required(CONF_DEVICETRACKER_ID): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=devicetracker_id_list,
                        multiple=False,
                        custom_value=False,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(CONF_API_KEY): str,
                vol.Optional(
                    CONF_DISPLAY_OPTIONS, default=DEFAULT_DISPLAY_OPTIONS
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=STATE_OPTIONS,
                        multiple=False,
                        custom_value=True,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(CONF_HOME_ZONE, default=DEFAULT_HOME_ZONE): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=zone_list,
                        multiple=False,
                        custom_value=False,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(
                    CONF_MAP_PROVIDER, default=DEFAULT_MAP_PROVIDER
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=MAP_PROVIDER_OPTIONS,
                        multiple=False,
                        custom_value=False,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(CONF_MAP_ZOOM, default=int(DEFAULT_MAP_ZOOM)): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=MAP_ZOOM_MIN,
                        max=MAP_ZOOM_MAX,
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Optional(CONF_LANGUAGE): str,
                vol.Optional(CONF_USE_GPS, default=DEFAULT_USE_GPS): selector.BooleanSelector(
                    selector.BooleanSelectorConfig()
                ),
                vol.Optional(
                    CONF_EXTENDED_ATTR, default=DEFAULT_EXTENDED_ATTR
                ): selector.BooleanSelector(selector.BooleanSelectorConfig()),
                vol.Optional(CONF_SHOW_TIME, default=DEFAULT_SHOW_TIME): selector.BooleanSelector(
                    selector.BooleanSelectorConfig()
                ),
                vol.Optional(
                    CONF_DATE_FORMAT, default=DEFAULT_DATE_FORMAT
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=DATE_FORMAT_OPTIONS,
                        multiple=False,
                        custom_value=False,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )
        # If there is no user input or there were errors, show the form again, including any errors that were found with the input.
        return self.async_show_form(
            step_id="user",
            data_schema=DATA_SCHEMA,
            errors=errors,
            description_placeholders={
                "component_config_url": COMPONENT_CONFIG_URL,
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> PlacesOptionsFlowHandler:
        """Options callback for Places."""
        return PlacesOptionsFlowHandler()


class PlacesOptionsFlowHandler(OptionsFlow):
    """Config flow options for Places. Does not actually store these into Options but updates the Config instead."""

    async def async_step_init(
        self, user_input: MutableMapping[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        errors: dict[str, Any] = {}
        if user_input is not None:
            # _LOGGER.debug("[options_flow async_step_init] user_input initial: %s", user_input)
            # Bring in other keys not in the Options Flow
            for m in dict(self.config_entry.data):
                user_input.setdefault(m, self.config_entry.data[m])
            # Remove any keys with blank values
            for m in dict(user_input):
                # _LOGGER.debug("[Options Update] %s [%s]: %s", m, type(user_input.get(m)), user_input.get(m))
                if isinstance(user_input.get(m), str) and not user_input.get(m):
                    user_input.pop(m)
            # _LOGGER.debug("[Options Update] updated config: %s", user_input)

            errors = await validate_display_options(
                display_options=user_input.get(CONF_DISPLAY_OPTIONS, ""),
                errors=errors,
            )

            if not errors:
                self.hass.config_entries.async_update_entry(
                    self.config_entry, data=user_input, options=self.config_entry.options
                )
                await self.hass.config_entries.async_reload(self.config_entry.entry_id)
                return self.async_create_entry(title="", data={})

        # Include the current entity in the list as well. Although it may still fail in validation checking.
        devicetracker_id_list: list[selector.SelectOptionDict] = get_devicetracker_id_entities(
            self.hass, self.config_entry.data.get(CONF_DEVICETRACKER_ID, None)
        )
        zone_list: list[selector.SelectOptionDict] = get_home_zone_entities(self.hass)
        # _LOGGER.debug("Trackable entities including sensors with lat/long: %s", devicetracker_id_list)
        OPTIONS_SCHEMA: vol.Schema = vol.Schema(
            {
                vol.Required(
                    CONF_DEVICETRACKER_ID,
                    default=(self.config_entry.data.get(CONF_DEVICETRACKER_ID, None)),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=devicetracker_id_list,
                        multiple=False,
                        custom_value=False,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(
                    CONF_API_KEY,
                    default="",
                    description={"suggested_value": self.config_entry.data.get(CONF_API_KEY, None)},
                ): str,
                vol.Optional(
                    CONF_DISPLAY_OPTIONS,
                    default=DEFAULT_DISPLAY_OPTIONS,
                    description={
                        "suggested_value": self.config_entry.data.get(
                            CONF_DISPLAY_OPTIONS, DEFAULT_DISPLAY_OPTIONS
                        )
                    },
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=STATE_OPTIONS,
                        multiple=False,
                        custom_value=True,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(
                    CONF_HOME_ZONE,
                    default="",
                    description={
                        "suggested_value": self.config_entry.data.get(CONF_HOME_ZONE, None)
                    },
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=zone_list,
                        multiple=False,
                        custom_value=False,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(
                    CONF_MAP_PROVIDER,
                    default=DEFAULT_MAP_PROVIDER,
                    description={
                        "suggested_value": self.config_entry.data.get(
                            CONF_MAP_PROVIDER, DEFAULT_MAP_PROVIDER
                        )
                    },
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=MAP_PROVIDER_OPTIONS,
                        multiple=False,
                        custom_value=False,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(
                    CONF_MAP_ZOOM,
                    default=DEFAULT_MAP_ZOOM,
                    description={
                        "suggested_value": self.config_entry.data.get(
                            CONF_MAP_ZOOM, DEFAULT_MAP_ZOOM
                        )
                    },
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=MAP_ZOOM_MIN,
                        max=MAP_ZOOM_MAX,
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Optional(
                    CONF_LANGUAGE,
                    default="",
                    description={
                        "suggested_value": self.config_entry.data.get(CONF_LANGUAGE, None)
                    },
                ): str,
                vol.Optional(
                    CONF_USE_GPS,
                    default=(self.config_entry.data.get(CONF_USE_GPS, DEFAULT_USE_GPS)),
                ): selector.BooleanSelector(selector.BooleanSelectorConfig()),
                vol.Optional(
                    CONF_EXTENDED_ATTR,
                    default=(self.config_entry.data.get(CONF_EXTENDED_ATTR, DEFAULT_EXTENDED_ATTR)),
                ): selector.BooleanSelector(selector.BooleanSelectorConfig()),
                vol.Optional(
                    CONF_SHOW_TIME,
                    default=(self.config_entry.data.get(CONF_SHOW_TIME, DEFAULT_SHOW_TIME)),
                ): selector.BooleanSelector(selector.BooleanSelectorConfig()),
                vol.Optional(
                    CONF_DATE_FORMAT,
                    default=DEFAULT_DATE_FORMAT,
                    description={
                        "suggested_value": self.config_entry.data.get(
                            CONF_DATE_FORMAT, DEFAULT_DATE_FORMAT
                        )
                    },
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=DATE_FORMAT_OPTIONS,
                        multiple=False,
                        custom_value=False,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )

        # _LOGGER.debug("[Options Update] initial config: %s", self.config_entry.data)

        return self.async_show_form(
            step_id="init",
            data_schema=OPTIONS_SCHEMA,
            errors=errors,
            description_placeholders={
                "component_config_url": COMPONENT_CONFIG_URL,
                "sensor_name": self.config_entry.data[CONF_NAME],
            },
        )

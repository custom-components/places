"""Config Flow for places integration."""

from __future__ import annotations

from collections.abc import MutableMapping
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import (
    ATTR_FRIENDLY_NAME,
    CONF_API_KEY,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_NAME,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er, selector
import voluptuous as vol

from .config_schema import (
    DATE_FORMAT_OPTIONS,
    MAP_PROVIDER_OPTIONS,
    MAP_ZOOM_MAX,
    MAP_ZOOM_MIN,
    STATE_OPTIONS,
    user_schema,
)
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
from .display_options import parse_display_options

_LOGGER: logging.Logger = logging.getLogger(__name__)
COMPONENT_CONFIG_URL: str = "https://github.com/custom-components/places#configuration-options"

# Note the input displayed to the user will be translated. See the
# translations/<lang>.json files. See here for further information:
# https://developers.home-assistant.io/docs/config_entries_config_flow_handler/#translations


def get_devicetracker_id_entities(
    hass: HomeAssistant, current_entity: str | None = None
) -> list[selector.SelectOptionDict]:
    """Build selector options for trackable entities with usable coordinates.

    Args:
        hass (HomeAssistant):
            Home Assistant instance used to inspect current states.
        current_entity (str | None):
            Existing configured entity to retain in the options
            list even if it is no longer returned by the normal domain scan.

    Returns:
        list[selector.SelectOptionDict]:
            Sorted selector options labelled with friendly names and entity IDs.
    """
    dt_list: list[selector.SelectOptionDict] = []
    entity_registry = er.async_get(hass)
    for dom in TRACKING_DOMAINS:
        # _LOGGER.debug("Getting entities for domain: %s", dom)
        for ent in hass.states.async_all(dom):
            registry_entry = entity_registry.async_get(ent.entity_id)
            if registry_entry is not None and registry_entry.platform == DOMAIN:
                continue
            if dom not in TRACKING_DOMAINS_NEED_LATLONG or (
                CONF_LATITUDE in ent.attributes and CONF_LONGITUDE in ent.attributes
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
        registry_entry = entity_registry.async_get(current_entity)
        current_state = hass.states.get(current_entity)
        if (
            current_entity not in dt_list_entities
            and current_state is not None
            and (registry_entry is None or registry_entry.platform != DOMAIN)
        ):
            current_name = current_state.attributes.get(ATTR_FRIENDLY_NAME)
            if current_name is not None:
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

    return dt_list_sorted


def get_home_zone_entities(hass: HomeAssistant) -> list[selector.SelectOptionDict]:
    """Build selector options for zones that can be used as the home reference.

    Args:
        hass (HomeAssistant):
            Home Assistant instance used to inspect current zone states.

    Returns:
        list[selector.SelectOptionDict]:
            Sorted selector options labelled with friendly names and entity IDs.
    """
    zone_list: list[selector.SelectOptionDict] = []
    for dom in HOME_LOCATION_DOMAINS:
        # _LOGGER.debug("Getting entities for domain: %s", dom)
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


async def validate_display_options(display_options: str, errors: dict[str, Any]) -> dict[str, Any]:
    """Validate advanced display option syntax for the config and options flows.

    Args:
        display_options (str):
            Raw display option string entered by the user.
        errors (dict[str, Any]):
            Mutable flow error mapping to populate when validation fails.

    Returns:
        dict[str, Any]:
            The same error mapping, possibly with ``base`` set to a validation
            error key.
    """
    if not display_options.strip():
        _LOGGER.error("Invalid syntax: Display options cannot be blank.")
        errors["base"] = "invalid_syntax"
        return errors

    parsed = parse_display_options(display_options)
    if parsed.has_groups or parsed.bracket_mismatch:
        if parsed.error:
            errors["base"] = parsed.error
        elif any(identifier.name not in DISPLAY_OPTIONS_MAP for identifier in parsed.identifiers):
            errors["base"] = "invalid_option"
        if "base" in errors:
            _LOGGER.error("Invalid Display options (%s): %s", errors["base"], display_options)
    return errors


class PlacesConfigFlow(ConfigFlow, domain=DOMAIN):
    """Create new Places config entries from UI input."""

    VERSION = 2

    async def async_step_user(
        self, user_input: MutableMapping[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show and process the initial Places setup form.

        Args:
            user_input (MutableMapping[str, Any] | None):
                Submitted form values, or ``None`` while displaying
                the form.

        Returns:
            ConfigFlowResult:
                A Home Assistant config-flow result for a form or created entry.
        """
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
        data_schema: vol.Schema = user_schema(devicetracker_id_list, zone_list)
        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
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
        """Return the options flow handler for an existing entry.

        Args:
            config_entry (ConfigEntry):
                Existing Places config entry.

        Returns:
            PlacesOptionsFlowHandler:
                Options flow handler instance.
        """
        return PlacesOptionsFlowHandler()


class PlacesOptionsFlowHandler(OptionsFlow):
    """Update options for an existing Places config entry."""

    async def async_step_init(
        self, user_input: MutableMapping[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show and process the Places options form.

        Args:
            user_input (MutableMapping[str, Any] | None):
                Submitted option values, or ``None`` while displaying
                the form.

        Returns:
            ConfigFlowResult:
                A Home Assistant options-flow result for a form or completed update.
        """
        errors: dict[str, Any] = {}
        if user_input is not None:
            # _LOGGER.debug("[options_flow async_step_init] user_input initial: %s", user_input)
            # Bring in other keys not in the Options Flow
            for m in dict(self.config_entry.data):
                user_input.setdefault(m, self.config_entry.data[m])
            # Remove any keys with blank values
            for m in dict(user_input):
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

        # Include the current entity in the list as well.
        devicetracker_id_list: list[selector.SelectOptionDict] = get_devicetracker_id_entities(
            self.hass, self.config_entry.data.get(CONF_DEVICETRACKER_ID, None)
        )
        zone_list: list[selector.SelectOptionDict] = get_home_zone_entities(self.hass)
        options_schema: vol.Schema = vol.Schema(
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

        return self.async_show_form(
            step_id="init",
            data_schema=options_schema,
            errors=errors,
            description_placeholders={
                "component_config_url": COMPONENT_CONFIG_URL,
                "sensor_name": self.config_entry.data[CONF_NAME],
            },
        )

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries, core
from homeassistant.const import (
    ATTR_FRIENDLY_NAME,
    CONF_API_KEY,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_NAME,
)
from homeassistant.data_entry_flow import FlowResult
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
    DOMAIN,
    HOME_LOCATION_DOMAINS,
    TRACKING_DOMAINS,
    TRACKING_DOMAINS_NEED_LATLONG,
)

_LOGGER = logging.getLogger(__name__)
MAP_PROVIDER_OPTIONS = ["apple", "google", "osm"]
STATE_OPTIONS = ["zone, place", "formatted_place", "zone_name, place"]
DATE_FORMAT_OPTIONS = ["mm/dd", "dd/mm"]
MAP_ZOOM_MIN = 1
MAP_ZOOM_MAX = 20
COMPONENT_CONFIG_URL = (
    "https://github.com/custom-components/places#configuration-options"
)

# Note the input displayed to the user will be translated. See the
# translations/<lang>.json file and strings.json. See here for further information:
# https://developers.home-assistant.io/docs/config_entries_config_flow_handler/#translations


def get_devicetracker_id_entities(
    hass: core.HomeAssistant, current_entity=None
) -> list[str]:
    """Get the list of valid entities. For sensors, only include ones with latitude and longitude attributes."""
    dt_list = []
    for dom in TRACKING_DOMAINS:
        # _LOGGER.debug(f"Geting entities for domain: {dom}")
        for ent in hass.states.async_all(dom):
            if dom not in TRACKING_DOMAINS_NEED_LATLONG or (
                CONF_LATITUDE in hass.states.get(ent.entity_id).attributes
                and CONF_LONGITUDE in hass.states.get(ent.entity_id).attributes
            ):
                # _LOGGER.debug(f"Entity: {ent}")
                dt_list.append(
                    selector.SelectOptionDict(
                        value=str(ent.entity_id),
                        label=f"{ent.attributes.get(ATTR_FRIENDLY_NAME)} ({ent.entity_id})",
                    )
                )
    # Optional: Include the current entity in the list as well.
    if current_entity is not None:
        # _LOGGER.debug(f"current_entity: {current_entity}")
        dt_list_entities = [d["value"] for d in dt_list]
        if (
            current_entity not in dt_list_entities
            and hass.states.get(current_entity) is not None
        ):
            if (
                ATTR_FRIENDLY_NAME in hass.states.get(current_entity).attributes
                and hass.states.get(current_entity).attributes.get(ATTR_FRIENDLY_NAME)
                is not None
            ):
                current_name = hass.states.get(current_entity).attributes.get(
                    ATTR_FRIENDLY_NAME
                )
                # _LOGGER.debug(f"current_name: {current_name}")
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
        dt_list_sorted = sorted(dt_list, key=lambda d: d["label"].casefold())
    else:
        dt_list_sorted = []

    # _LOGGER.debug(f"Devicetracker_id name/entities including sensors with lat/long: {dt_list_sorted}")
    return dt_list_sorted


def get_home_zone_entities(hass: core.HomeAssistant) -> list[str]:
    """Get the list of valid zones."""
    zone_list = []
    for dom in HOME_LOCATION_DOMAINS:
        # _LOGGER.debug(f"Geting entities for domain: {dom}")
        for ent in hass.states.async_all(dom):
            # _LOGGER.debug(f"Entity: {ent}")
            zone_list.append(
                selector.SelectOptionDict(
                    value=str(ent.entity_id),
                    label=f"{ent.attributes.get(ATTR_FRIENDLY_NAME)} ({ent.entity_id})",
                )
            )
    if zone_list:
        zone_list_sorted = sorted(zone_list, key=lambda d: d["label"].casefold())
    else:
        zone_list_sorted = []
    # _LOGGER.debug(f"Zones: {zone_list_sorted}")
    return zone_list_sorted


async def validate_input(hass: core.HomeAssistant, data: dict) -> dict[str, Any]:
    """Validate the user input allows us to connect.

    Data has the keys from DATA_SCHEMA with values provided by the user.
    """

    # _LOGGER.debug(f"[config_flow validate_input] data: {data}")

    return {"title": data[CONF_NAME]}


class PlacesConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1
    # Connection classes in homeassistant/config_entries.py are now deprecated

    async def async_step_user(self, user_input=None) -> FlowResult:
        """Handle the initial step."""
        # This goes through the steps to take the user through the setup process.
        # Using this it is possible to update the UI and prompt for additional
        # information. This example provides a single form (built from `DATA_SCHEMA`),
        # and when that has some validated input, it calls `async_create_entry` to
        # actually create the HA config entry. Note the "title" value is returned by
        # `validate_input` above.
        errors = {}
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
                # _LOGGER.debug(f"[New Sensor] info: {info}")
                _LOGGER.debug(f"[New Sensor] user_input: {user_input}")
                return self.async_create_entry(title=info["title"], data=user_input)
            except Exception as err:
                _LOGGER.exception(
                    f"[config_flow async_step_user] Unexpected exception: {err}"
                )
                errors["base"] = "unknown"
        devicetracker_id_list = get_devicetracker_id_entities(self.hass)
        zone_list = get_home_zone_entities(self.hass)
        # _LOGGER.debug(f"Trackable entities with lat/long: {devicetracker_id_list}")
        DATA_SCHEMA = vol.Schema(
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
                vol.Optional(
                    CONF_HOME_ZONE, default=DEFAULT_HOME_ZONE
                ): selector.SelectSelector(
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
                vol.Optional(
                    CONF_MAP_ZOOM, default=int(DEFAULT_MAP_ZOOM)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=MAP_ZOOM_MIN,
                        max=MAP_ZOOM_MAX,
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Optional(CONF_LANGUAGE): str,
                vol.Optional(
                    CONF_EXTENDED_ATTR, default=DEFAULT_EXTENDED_ATTR
                ): selector.BooleanSelector(selector.BooleanSelectorConfig()),
                vol.Optional(
                    CONF_SHOW_TIME, default=DEFAULT_SHOW_TIME
                ): selector.BooleanSelector(selector.BooleanSelectorConfig()),
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
                vol.Optional(
                    CONF_USE_GPS, default=DEFAULT_USE_GPS
                ): selector.BooleanSelector(selector.BooleanSelectorConfig()),
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
    @core.callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> PlacesOptionsFlowHandler:
        """Options callback for Places."""
        return PlacesOptionsFlowHandler(config_entry)


class PlacesOptionsFlowHandler(config_entries.OptionsFlow):
    """Config flow options for Places. Does not actually store these into Options but updates the Config instead."""

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        """Initialize Places options flow."""
        self.config_entry = entry

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            # _LOGGER.debug(f"[options_flow async_step_init] user_input initial: {user_input}")
            # Bring in other keys not in the Options Flow
            for m in dict(self.config_entry.data).keys():
                user_input.setdefault(m, self.config_entry.data[m])
            # Remove any keys with blank values
            for m in dict(user_input).keys():
                # _LOGGER.debug(f"[Options Update] {m} [{type(user_input.get(m))}]: {user_input.get(m)}")
                if isinstance(user_input.get(m), str) and not user_input.get(m):
                    user_input.pop(m)
            # _LOGGER.debug(f"[Options Update] updated config: {user_input}")

            self.hass.config_entries.async_update_entry(
                self.config_entry, data=user_input, options=self.config_entry.options
            )
            await self.hass.config_entries.async_reload(self.config_entry.entry_id)
            return self.async_create_entry(title="", data={})

        # Include the current entity in the list as well. Although it may still fail in validation checking.
        devicetracker_id_list = get_devicetracker_id_entities(
            self.hass,
            self.config_entry.data[CONF_DEVICETRACKER_ID]
            if CONF_DEVICETRACKER_ID in self.config_entry.data
            else None,
        )
        zone_list = get_home_zone_entities(self.hass)
        # _LOGGER.debug(f"Trackable entities including sensors with lat/long: {devicetracker_id_list}")
        OPTIONS_SCHEMA = vol.Schema(
            {
                vol.Required(
                    CONF_DEVICETRACKER_ID,
                    default=(
                        self.config_entry.data[CONF_DEVICETRACKER_ID]
                        if CONF_DEVICETRACKER_ID in self.config_entry.data
                        else None
                    ),
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
                    description={
                        "suggested_value": self.config_entry.data[CONF_API_KEY]
                        if CONF_API_KEY in self.config_entry.data
                        else None
                    },
                ): str,
                vol.Optional(
                    CONF_DISPLAY_OPTIONS,
                    default=DEFAULT_DISPLAY_OPTIONS,
                    description={
                        "suggested_value": self.config_entry.data[CONF_DISPLAY_OPTIONS]
                        if CONF_DISPLAY_OPTIONS in self.config_entry.data
                        else DEFAULT_DISPLAY_OPTIONS
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
                        "suggested_value": self.config_entry.data[CONF_HOME_ZONE]
                        if CONF_HOME_ZONE in self.config_entry.data
                        else None
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
                        "suggested_value": self.config_entry.data[CONF_MAP_PROVIDER]
                        if CONF_MAP_PROVIDER in self.config_entry.data
                        else DEFAULT_MAP_PROVIDER
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
                        "suggested_value": self.config_entry.data[CONF_MAP_ZOOM]
                        if CONF_MAP_ZOOM in self.config_entry.data
                        else DEFAULT_MAP_ZOOM
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
                        "suggested_value": self.config_entry.data[CONF_LANGUAGE]
                        if CONF_LANGUAGE in self.config_entry.data
                        else None
                    },
                ): str,
                vol.Optional(
                    CONF_EXTENDED_ATTR,
                    default=(
                        self.config_entry.data[CONF_EXTENDED_ATTR]
                        if CONF_EXTENDED_ATTR in self.config_entry.data
                        else DEFAULT_EXTENDED_ATTR
                    ),
                ): selector.BooleanSelector(selector.BooleanSelectorConfig()),
                vol.Optional(
                    CONF_SHOW_TIME,
                    default=(
                        self.config_entry.data[CONF_SHOW_TIME]
                        if CONF_SHOW_TIME in self.config_entry.data
                        else DEFAULT_SHOW_TIME
                    ),
                ): selector.BooleanSelector(selector.BooleanSelectorConfig()),
                vol.Optional(
                    CONF_DATE_FORMAT,
                    default=DEFAULT_DATE_FORMAT,
                    description={
                        "suggested_value": self.config_entry.data[CONF_DATE_FORMAT]
                        if CONF_DATE_FORMAT in self.config_entry.data
                        else DEFAULT_DATE_FORMAT
                    },
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=DATE_FORMAT_OPTIONS,
                        multiple=False,
                        custom_value=False,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(
                    CONF_USE_GPS,
                    default=(
                        self.config_entry.data[CONF_USE_GPS]
                        if CONF_USE_GPS in self.config_entry.data
                        else DEFAULT_USE_GPS
                    ),
                ): selector.BooleanSelector(selector.BooleanSelectorConfig()),
            }
        )

        # _LOGGER.debug(f"[Options Update] initial config: {self.config_entry.data}")

        return self.async_show_form(
            step_id="init",
            data_schema=OPTIONS_SCHEMA,
            description_placeholders={
                "component_config_url": COMPONENT_CONFIG_URL,
                "sensor_name": self.config_entry.data[CONF_NAME],
            },
        )

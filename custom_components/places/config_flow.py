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
    CONF_DEVICETRACKER_ID,
    CONF_EXTENDED_ATTR,
    CONF_HOME_ZONE,
    CONF_LANGUAGE,
    CONF_MAP_PROVIDER,
    CONF_MAP_ZOOM,
    CONF_OPTIONS,
    CONF_SHOW_TIME,
    CONF_USE_GPS,
    DEFAULT_EXTENDED_ATTR,
    DEFAULT_HOME_ZONE,
    DEFAULT_MAP_PROVIDER,
    DEFAULT_MAP_ZOOM,
    DEFAULT_OPTION,
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
    """Get the list of valid entities. For sensors, only include ones with latitude and longitude attributes. For the devicetracker selector"""
    dt_list = []
    for dom in TRACKING_DOMAINS:
        # _LOGGER.debug("Geting entities for domain: " + str(dom))
        for ent in hass.states.async_all(dom):
            if dom not in TRACKING_DOMAINS_NEED_LATLONG or (
                CONF_LATITUDE in hass.states.get(ent.entity_id).attributes
                and CONF_LONGITUDE in hass.states.get(ent.entity_id).attributes
            ):
                # _LOGGER.debug("Entity: " + str(ent))
                dt_list.append(
                    selector.SelectOptionDict(
                        value=str(ent.entity_id),
                        label=(
                            str(ent.attributes.get(ATTR_FRIENDLY_NAME))
                            + " ("
                            + str(ent.entity_id)
                            + ")"
                        ),
                    )
                )
    # Optional: Include the current entity in the list as well.
    if current_entity is not None:
        # _LOGGER.debug("current_entity: " + str(current_entity))
        dt_list_entities = [d["value"] for d in dt_list]
        if current_entity not in dt_list_entities:
            if (
                current_entity in hass.states
                and ATTR_FRIENDLY_NAME in hass.states.get(current_entity).attributes
                and hass.states.get(current_entity).attributes.get(ATTR_FRIENDLY_NAME)
                is not None
            ):
                current_name = hass.states.get(current_entity).attributes.get(
                    ATTR_FRIENDLY_NAME
                )
                # _LOGGER.debug("current_name: " + str(current_name))
                dt_list.append(
                    selector.SelectOptionDict(
                        value=str(current_entity),
                        label=(str(current_name) + " (" + str(current_entity) + ")"),
                    )
                )
            else:
                dt_list.append(
                    selector.SelectOptionDict(
                        value=str(current_entity),
                        label=(str(current_entity)),
                    )
                )
    if dt_list:
        dt_list_sorted = sorted(dt_list, key=lambda d: d["label"])
    else:
        dt_list_sorted = []

    # _LOGGER.debug(
    #    "Devicetracker_id name/entities including sensors with lat/long: "
    #    + str(dt_list_sorted)
    # )
    return dt_list_sorted


def get_home_zone_entities(hass: core.HomeAssistant) -> list[str]:
    """Get the list of valid zones."""
    zone_list = []
    for dom in HOME_LOCATION_DOMAINS:
        # _LOGGER.debug("Geting entities for domain: " + str(dom))
        for ent in hass.states.async_all(dom):
            # _LOGGER.debug("Entity: " + str(ent))
            zone_list.append(
                selector.SelectOptionDict(
                    value=str(ent.entity_id),
                    label=(
                        str(ent.attributes.get(ATTR_FRIENDLY_NAME))
                        + " ("
                        + str(ent.entity_id)
                        + ")"
                    ),
                )
            )
    if zone_list:
        zone_list_sorted = sorted(zone_list, key=lambda d: d["label"])
    else:
        zone_list_sorted = []
    # _LOGGER.debug("Zones: " + str(zone_list_sorted))
    return zone_list_sorted


async def validate_input(hass: core.HomeAssistant, data: dict) -> dict[str, Any]:
    """Validate the user input allows us to connect.

    Data has the keys from DATA_SCHEMA with values provided by the user.
    """

    # _LOGGER.debug("[config_flow validate_input] data: " + str(data))

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
                # _LOGGER.debug("[New Sensor] info: " + str(info))
                _LOGGER.debug("[New Sensor] user_input: " + str(user_input))
                return self.async_create_entry(title=info["title"], data=user_input)
            except Exception as err:
                _LOGGER.exception(
                    "[config_flow async_step_user] Unexpected exception:" + str(err)
                )
                errors["base"] = "unknown"
        devicetracker_id_list = get_devicetracker_id_entities(self.hass)
        zone_list = get_home_zone_entities(self.hass)
        # _LOGGER.debug(
        #    "Devicetracker entities with lat/long: " + str(devicetracker_id_list)
        # )
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
                    CONF_OPTIONS, default=DEFAULT_OPTION
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

    # this is run to import the configuration.yaml parameters\
    async def async_step_import(self, import_config=None) -> FlowResult:
        """Import a config entry from configuration.yaml."""

        # _LOGGER.debug("[async_step_import] import_config: " + str(import_config))
        return await self.async_step_user(import_config)

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
            # _LOGGER.debug(
            #    "[options_flow async_step_init] user_input initial: " + str(user_input)
            # )
            # Bring in other keys not in the Options Flow
            for m in dict(self.config_entry.data).keys():
                user_input.setdefault(m, self.config_entry.data[m])
            # Remove any keys with blank values
            for m in dict(user_input).keys():
                # _LOGGER.debug(
                #    "[Options Update] "
                #    + m
                #    + " ["
                #    + str(type(user_input.get(m)))
                #    + "]: "
                #    + str(user_input.get(m))
                # )
                if isinstance(user_input.get(m), str) and not user_input.get(m):
                    user_input.pop(m)
            # _LOGGER.debug("[Options Update] updated config: " + str(user_input))

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
        # _LOGGER.debug(
        #    "Devicetracker_id entities including sensors with lat/long: "
        #    + str(devicetracker_id_list)
        # )
        OPTIONS_SCHEMA = vol.Schema(
            {
                # vol.Required(CONF_NAME, default=self.config_entry.data[CONF_NAME] if CONF_NAME in self.config_entry.data else None)): str,
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
                    CONF_OPTIONS,
                    default=DEFAULT_OPTION,
                    description={
                        "suggested_value": self.config_entry.data[CONF_OPTIONS]
                        if CONF_OPTIONS in self.config_entry.data
                        else DEFAULT_OPTION
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
                    CONF_USE_GPS,
                    default=(
                        self.config_entry.data[CONF_USE_GPS]
                        if CONF_USE_GPS in self.config_entry.data
                        else DEFAULT_USE_GPS
                    ),
                ): selector.BooleanSelector(selector.BooleanSelectorConfig()),
            }
        )

        # _LOGGER.debug("[Options Update] initial config: " + str(self.config_entry.data))

        return self.async_show_form(
            step_id="init",
            data_schema=OPTIONS_SCHEMA,
            description_placeholders={
                "component_config_url": COMPONENT_CONFIG_URL,
                "sensor_name": self.config_entry.data[CONF_NAME],
            },
        )

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant import core
from homeassistant.const import CONF_API_KEY
from homeassistant.const import CONF_NAME
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import CONF_DEVICETRACKER_ID
from .const import CONF_EXTENDED_ATTR
from .const import CONF_HOME_ZONE
from .const import CONF_LANGUAGE
from .const import CONF_MAP_PROVIDER
from .const import CONF_MAP_ZOOM
from .const import CONF_OPTIONS
from .const import DEFAULT_EXTENDED_ATTR
from .const import DEFAULT_HOME_ZONE
from .const import DEFAULT_MAP_PROVIDER
from .const import DEFAULT_MAP_ZOOM
from .const import DEFAULT_OPTION
from .const import DOMAIN  # pylint:disable=unused-import
from .const import HOME_LOCATION_DOMAIN
from .const import TRACKING_DOMAIN

_LOGGER = logging.getLogger(__name__)
MAP_PROVIDER_OPTIONS = ["apple", "google", "osm"]
STATE_OPTIONS = ["zone, place", "formatted_place", "zone_name, place"]

# Note the input displayed to the user will be translated. See the
# translations/<lang>.json file and strings.json. See here for further information:
# https://developers.home-assistant.io/docs/config_entries_config_flow_handler/#translations

DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): str,
        vol.Required(CONF_DEVICETRACKER_ID): selector.EntitySelector(
            selector.SingleEntitySelectorConfig(domain=TRACKING_DOMAIN)
        ),
        vol.Optional(CONF_API_KEY): str,
        vol.Optional(CONF_OPTIONS, default=DEFAULT_OPTION): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=STATE_OPTIONS,
                multiple=False,
                custom_value=True,
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        ),
        vol.Optional(
            CONF_HOME_ZONE, default=DEFAULT_HOME_ZONE
        ): selector.EntitySelector(
            selector.SingleEntitySelectorConfig(domain=HOME_LOCATION_DOMAIN)
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
                min=1, max=20, mode=selector.NumberSelectorMode.BOX
            )
        ),
        vol.Optional(CONF_LANGUAGE): str,
        vol.Optional(
            CONF_EXTENDED_ATTR, default=DEFAULT_EXTENDED_ATTR
        ): selector.BooleanSelector(selector.BooleanSelectorConfig()),
    }
)


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
                _LOGGER.debug(
                    "[config_flow async_step_user] user_input: " + str(user_input)
                )
                return self.async_create_entry(title=info["title"], data=user_input)
            except Exception as err:  # pylint: disable=broad-except
                _LOGGER.exception(
                    "[config_flow async_step_user] Unexpected exception:" + str(err)
                )
                errors["base"] = "unknown"

        # If there is no user input or there were errors, show the form again, including any errors that were found with the input.
        return self.async_show_form(
            step_id="user", data_schema=DATA_SCHEMA, errors=errors
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
    """Config flow options for Places."""

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        """Initialize Places options flow."""
        self.config_entry = entry

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            _LOGGER.debug(
                "[options_flow async_step_init] user_input initial: " + str(user_input)
            )
            # if CONF_HOST in self.config_entry.data:
            #    user_input[CONF_HOST] = self.config_entry.data[CONF_HOST]
            # if CONF_EMAIL in self.config_entry.data:
            #    user_input[CONF_EMAIL] = self.config_entry.data[CONF_EMAIL]
            for m in dict(self.config_entry.data).keys():
                user_input.setdefault(m, self.config_entry.data[m])
            _LOGGER.debug(
                "[options_flow async_step_init] user_input final: " + str(user_input)
            )

            self.hass.config_entries.async_update_entry(
                self.config_entry, data=user_input, options=self.config_entry.options
            )
            return self.async_create_entry(title="", data={})
            # return self.async_create_entry(title=DOMAIN, data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    # vol.Required(CONF_NAME, default=self.config_entry.data[CONF_NAME]): str,
                    vol.Required(
                        CONF_DEVICETRACKER_ID,
                        default=self.config_entry.data[CONF_DEVICETRACKER_ID],
                    ): selector.EntitySelector(
                        selector.SingleEntitySelectorConfig(domain=TRACKING_DOMAIN)
                    ),
                    vol.Optional(
                        CONF_API_KEY, default=self.config_entry.data[CONF_API_KEY]
                    ): str,
                    vol.Optional(
                        CONF_OPTIONS, default=self.config_entry.data[CONF_OPTIONS]
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=STATE_OPTIONS,
                            multiple=False,
                            custom_value=True,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Optional(
                        CONF_HOME_ZONE, default=self.config_entry.data[CONF_HOME_ZONE]
                    ): selector.EntitySelector(
                        selector.SingleEntitySelectorConfig(domain=HOME_LOCATION_DOMAIN)
                    ),
                    vol.Optional(
                        CONF_MAP_PROVIDER,
                        default=self.config_entry.data[CONF_MAP_PROVIDER],
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=MAP_PROVIDER_OPTIONS,
                            multiple=False,
                            custom_value=False,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Optional(
                        CONF_MAP_ZOOM, default=self.config_entry.data[CONF_MAP_ZOOM]
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=1, max=20, mode=selector.NumberSelectorMode.BOX
                        )
                    ),
                    vol.Optional(
                        CONF_LANGUAGE, default=self.config_entry.data[CONF_LANGUAGE]
                    ): str,
                    vol.Optional(
                        CONF_EXTENDED_ATTR,
                        default=self.config_entry.data[CONF_EXTENDED_ATTR],
                    ): selector.BooleanSelector(selector.BooleanSelectorConfig()),
                }
            ),
        )

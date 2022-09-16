from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant import core
from homeassistant import exceptions
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
# At the time of writing I found the translations created by the scaffold didn't
# quite work as documented and always gave me the "Lokalise key references" string
# (in square brackets), rather than the actual translated value. I did not attempt to
# figure this out or look further into it.
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
    # Validate the data can be used to set up a connection.
    _LOGGER.debug("[config_flow validate_input] data: " + str(data))
    # if hasattr(data,CONF_MAP_ZOOM) and data[CONF_MAP_ZOOM] is not None:
    #    data[CONF_MAP_ZOOM] = int(data[CONF_MAP_ZOOM])
    # This is a simple example to show an error in the UI for a short hostname
    # The exceptions are defined at the end of this file, and are used in the
    # `async_step_user` method below.

    # Return info that you want to store in the config entry.
    # "Title" is what is displayed to the user for this hub device
    # It is stored internally in HA as part of the device config.
    # See `async_step_user` below for how this is used
    return {"title": data[CONF_NAME]}


class PlacesConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):

    VERSION = 1
    # Pick one of the available connection classes in homeassistant/config_entries.py
    # This tells HA if it should be asking for updates, or it'll be notified of updates
    # automatically. This example uses PUSH, as the dummy hub will notify HA of
    # changes.
    ##CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_PUSH

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
                _LOGGER.debug("[config_flow] user_input: " + str(user_input))
                return self.async_create_entry(title=info["title"], data=user_input)
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        # If there is no user input or there were errors, show the form again, including any errors that were found with the input.
        return self.async_show_form(
            step_id="user", data_schema=DATA_SCHEMA, errors=errors
        )

        # this is run to import the configuration.yaml parameters

    async def async_step_import(self, import_config=None) -> FlowResult:
        """Import a config entry from configuration.yaml."""
        _LOGGER.debug("[async_step_import] import_config: " + str(import_config))

        # data = {}
        # try:
        # for k in import_config:
        #    if k == CONF_DEVICE:
        #        # flatten out the structure so the data variable is a simple dictionary
        #        device_type = import_config.get(CONF_DEVICE)
        #        if device_type[CONF_DEVICE_TYPE] == "ethernet":
        #            data[CONF_DEVICE_TYPE] = "ethernet"
        #            data[CONF_HOST] = device_type[CONF_HOST]
        #            data[CONF_PORT] = device_type[CONF_PORT]
        #        elif device_type[CONF_DEVICE_TYPE] == "usb":
        #            data[CONF_DEVICE_TYPE] = "usb"
        #            data[CONF_PATH] = device_type[CONF_PATH]
        #            if CONF_DEVICE_BAUD in device_type:
        #                data[CONF_DEVICE_BAUD] = device_type[CONF_DEVICE_BAUD]
        #            else:
        #                data[CONF_DEVICE_BAUD] = int(9600)
        #    else:
        #        data[k] = import_config.get(k)
        # except Exception as err:
        # _LOGGER.warning("[async_step_import] Import error: " + str(err))
        # return self.async_abort(reason="settings_missing")

        # return await self.async_step_user(import_config)

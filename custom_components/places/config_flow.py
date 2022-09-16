from __future__ import annotations

import hashlib
import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant import core
from homeassistant import exceptions
from homeassistant.const import CONF_API_KEY
from homeassistant.const import CONF_NAME
from homeassistant.const import CONF_PLATFORM
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import CONF_DEVICETRACKER_ID
from .const import CONF_EXTENDED_ATTR
from .const import CONF_HOME_ZONE
from .const import CONF_LANGUAGE
from .const import CONF_MAP_PROVIDER
from .const import CONF_MAP_ZOOM
from .const import CONF_OPTIONS
from .const import CONF_YAML_HASH
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

    _LOGGER.debug("[config_flow validate_input] data: " + str(data))

    # If a YAML Import, use MD5 Hash to see if it aready exists
    # if CONF_YAML_HASH in data:
    #    all_yaml_hashes = []
    #    for m in list(hass.data[DOMAIN].values()):
    #        if CONF_YAML_HASH in m:
    #            all_yaml_hashes.append(m[CONF_YAML_HASH])

    # _LOGGER.debug("[config_flow validate_input] importing yaml hash: " + str(data.get(CONF_YAML_HASH)))
    # _LOGGER.debug("[config_flow validate_input] existing places data: " + str(hass.data[DOMAIN]))
    # _LOGGER.debug("[config_flow validate_input] All yaml hashes: " + str(all_yaml_hashes))
    #    if data[CONF_YAML_HASH] in all_yaml_hashes:
    #        #_LOGGER.debug("[config_flow validate_input] yaml import is duplicate, not importing")
    #        raise YamlAlreadyImported
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
                _LOGGER.debug(
                    "[config_flow async_step_user] user_input: " + str(user_input)
                )
                return self.async_create_entry(title=info["title"], data=user_input)
            except YamlAlreadyImported:
                # YAML Already imported, ignore
                _LOGGER.debug(
                    "[config_flow async_step_user] yaml import is duplicate, not importing"
                )
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
        _LOGGER.debug(
            "[async_step_import] initial import_config: " + str(import_config)
        )

        # try:
        # import_config.pop(CONF_PLATFORM,1)
        # import_config.pop(CONF_SCAN_INTERVAL,1)

        # Generate pseudo-unique id using MD5 and store in config to try to prevent reimporting already imported yaml sensors.
        # string_to_hash=import_config.get(CONF_NAME)+import_config.get(CONF_DEVICETRACKER_ID)+import_config.get(CONF_HOME_ZONE)
        # _LOGGER.debug(
        #    "[async_step_import] string_to_hash: " + str(string_to_hash)
        # )
        # yaml_hash_object = hashlib.md5(string_to_hash.encode())
        # yaml_hash = yaml_hash_object.hexdigest()
        # _LOGGER.debug(
        #    "[async_step_import] yaml_hash: " + str(yaml_hash)
        # )
        # import_config.setdefault(CONF_YAML_HASH,yaml_hash)
        # except Exception as err:
        #    _LOGGER.warning("[async_step_import] Import error: " + str(err))
        #    return self.async_abort(reason="settings_missing")
        _LOGGER.debug("[async_step_import] final import_config: " + str(import_config))

        return await self.async_step_user(import_config)


class YamlAlreadyImported(exceptions.HomeAssistantError):
    """Error to indicate that YAML sensor is already imported."""

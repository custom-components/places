"""
Place Support for OpenStreetMap Geocode sensors.

Previous Authors:  Jim Thompson, Ian Richardson
Current Author:  Snuffy2

Description:
  Provides a sensor with a variable state consisting of reverse geocode (place) details for a linked device_tracker entity that provides GPS co-ordinates (ie owntracks, icloud)
  Allows you to specify a 'home_zone' for each device and calculates distance from home and direction of travel.
  Configuration Instructions are on GitHub.

GitHub: https://github.com/custom-components/places
"""

import copy
import json
import locale
import logging
import os
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import homeassistant.helpers.entity_registry as er
import requests
from homeassistant import config_entries, core
from homeassistant.components.recorder import DATA_INSTANCE as RECORDER_INSTANCE
from homeassistant.components.sensor import SensorEntity
from homeassistant.components.zone import ATTR_PASSIVE
from homeassistant.const import (
    ATTR_FRIENDLY_NAME,
    ATTR_GPS_ACCURACY,
    CONF_API_KEY,
    CONF_FRIENDLY_NAME,
    CONF_ICON,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_NAME,
    CONF_UNIQUE_ID,
    CONF_ZONE,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.helpers.entity import generate_entity_id
from homeassistant.helpers.event import (
    EventStateChangedData,
    async_track_state_change_event,
)
from homeassistant.helpers.typing import EventType
from homeassistant.util import Throttle, slugify
from homeassistant.util.location import distance
from urllib3.exceptions import NewConnectionError

from .const import (
    ATTR_ATTRIBUTES,
    ATTR_CITY,
    ATTR_CITY_CLEAN,
    ATTR_COUNTRY,
    ATTR_COUNTRY_CODE,
    ATTR_COUNTY,
    ATTR_DEVICETRACKER_ID,
    ATTR_DEVICETRACKER_ZONE,
    ATTR_DEVICETRACKER_ZONE_NAME,
    ATTR_DIRECTION_OF_TRAVEL,
    ATTR_DISPLAY_OPTIONS,
    ATTR_DISPLAY_OPTIONS_LIST,
    ATTR_DISTANCE_FROM_HOME_KM,
    ATTR_DISTANCE_FROM_HOME_M,
    ATTR_DISTANCE_FROM_HOME_MI,
    ATTR_DISTANCE_TRAVELED_M,
    ATTR_DISTANCE_TRAVELED_MI,
    ATTR_DRIVING,
    ATTR_FORMATTED_ADDRESS,
    ATTR_FORMATTED_PLACE,
    ATTR_HOME_LATITUDE,
    ATTR_HOME_LOCATION,
    ATTR_HOME_LONGITUDE,
    ATTR_INITIAL_UPDATE,
    ATTR_JSON_FILENAME,
    ATTR_LAST_CHANGED,
    ATTR_LAST_PLACE_NAME,
    ATTR_LAST_UPDATED,
    ATTR_LATITUDE,
    ATTR_LATITUDE_OLD,
    ATTR_LOCATION_CURRENT,
    ATTR_LOCATION_PREVIOUS,
    ATTR_LONGITUDE,
    ATTR_LONGITUDE_OLD,
    ATTR_MAP_LINK,
    ATTR_NATIVE_VALUE,
    ATTR_OSM_DETAILS_DICT,
    ATTR_OSM_DICT,
    ATTR_OSM_ID,
    ATTR_OSM_TYPE,
    ATTR_PICTURE,
    ATTR_PLACE_CATEGORY,
    ATTR_PLACE_NAME,
    ATTR_PLACE_NAME_NO_DUPE,
    ATTR_PLACE_NEIGHBOURHOOD,
    ATTR_PLACE_TYPE,
    ATTR_POSTAL_CODE,
    ATTR_POSTAL_TOWN,
    ATTR_PREVIOUS_STATE,
    ATTR_REGION,
    ATTR_SHOW_DATE,
    ATTR_STATE_ABBR,
    ATTR_STREET,
    ATTR_STREET_NUMBER,
    ATTR_STREET_REF,
    ATTR_WIKIDATA_DICT,
    ATTR_WIKIDATA_ID,
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
    CONFIG_ATTRIBUTES_LIST,
    DEFAULT_DATE_FORMAT,
    DEFAULT_DISPLAY_OPTIONS,
    DEFAULT_EXTENDED_ATTR,
    DEFAULT_HOME_ZONE,
    DEFAULT_ICON,
    DEFAULT_MAP_PROVIDER,
    DEFAULT_MAP_ZOOM,
    DEFAULT_SHOW_TIME,
    DEFAULT_USE_GPS,
    DISPLAY_OPTIONS_MAP,
    DOMAIN,
    ENTITY_ID_FORMAT,
    EVENT_ATTRIBUTE_LIST,
    EVENT_TYPE,
    EXTENDED_ATTRIBUTE_LIST,
    EXTRA_STATE_ATTRIBUTE_LIST,
    JSON_ATTRIBUTE_LIST,
    JSON_IGNORE_ATTRIBUTE_LIST,
    PLACE_NAME_DUPLICATE_LIST,
    PLATFORM,
    RESET_ATTRIBUTE_LIST,
    VERSION,
)
from .recorder_history_prefilter import recorder_prefilter

_LOGGER = logging.getLogger(__name__)
THROTTLE_INTERVAL = timedelta(seconds=600)
MIN_THROTTLE_INTERVAL = timedelta(seconds=10)
SCAN_INTERVAL = timedelta(seconds=30)
PLACES_JSON_FOLDER = os.path.join("custom_components", DOMAIN, "json_sensors")
try:
    os.makedirs(PLACES_JSON_FOLDER, exist_ok=True)
except OSError as e:
    _LOGGER.warning(f"OSError creating folder for JSON sensor files: {e}")
except Exception as e:
    _LOGGER.warning(f"Unknown Exception creating folder for JSON sensor files: {e}")


async def async_setup_entry(
    hass: core.HomeAssistant,
    config_entry: config_entries.ConfigEntry,
    async_add_entities,
) -> None:
    """Setup the sensor platform with a config_entry (config_flow)."""

    # _LOGGER.debug(f"[aync_setup_entity] all entities: {hass.data.get(DOMAIN)}")

    config = hass.data.get(DOMAIN).get(config_entry.entry_id)
    unique_id = config_entry.entry_id
    name = config.get(CONF_NAME)
    # _LOGGER.debug(f"[async_setup_entry] name: {name}")
    # _LOGGER.debug(f"[async_setup_entry] unique_id: {unique_id}")
    # _LOGGER.debug(f"[async_setup_entry] config: {config}")

    async_add_entities(
        [Places(hass, config, config_entry, name, unique_id)], update_before_add=True
    )


class Places(SensorEntity):
    """Representation of a Places Sensor."""

    def __init__(self, hass, config, config_entry, name, unique_id):
        """Initialize the sensor."""
        self._attr_should_poll = True
        _LOGGER.info(f"({name}) [Init] Places sensor: {name}")
        _LOGGER.debug(f"({name}) [Init] System Locale: {locale.getlocale()}")
        _LOGGER.debug(
            f"({name}) [Init] System Locale Date Format: {str(locale.nl_langinfo(locale.D_FMT))}"
        )
        _LOGGER.debug(f"({name}) [Init] HASS TimeZone: {hass.config.time_zone}")

        self._warn_if_device_tracker_prob = False
        self._internal_attr = {}
        self.set_attr(ATTR_INITIAL_UPDATE, True)
        self._config = config
        self._config_entry = config_entry
        self._hass = hass
        self.set_attr(CONF_NAME, name)
        self._attr_name = name
        self.set_attr(CONF_UNIQUE_ID, unique_id)
        self._attr_unique_id = unique_id
        registry = er.async_get(self._hass)
        current_entity_id = registry.async_get_entity_id(
            PLATFORM, DOMAIN, self._attr_unique_id
        )
        if current_entity_id is not None:
            self.entity_id = current_entity_id
        else:
            self.entity_id = generate_entity_id(
                ENTITY_ID_FORMAT, slugify(name.lower()), hass=self._hass
            )
        _LOGGER.debug(f"({self._attr_name}) [Init] entity_id: {self.entity_id}")
        self.set_attr(CONF_ICON, DEFAULT_ICON)
        self._attr_icon = DEFAULT_ICON
        self.set_attr(CONF_API_KEY, config.get(CONF_API_KEY))
        self.set_attr(
            CONF_DISPLAY_OPTIONS,
            config.setdefault(CONF_DISPLAY_OPTIONS, DEFAULT_DISPLAY_OPTIONS).lower(),
        )
        self.set_attr(CONF_DEVICETRACKER_ID, config.get(CONF_DEVICETRACKER_ID).lower())
        # Consider reconciling this in the future
        self.set_attr(ATTR_DEVICETRACKER_ID, config.get(CONF_DEVICETRACKER_ID).lower())
        self.set_attr(
            CONF_HOME_ZONE, config.setdefault(CONF_HOME_ZONE, DEFAULT_HOME_ZONE).lower()
        )
        self.set_attr(
            CONF_MAP_PROVIDER,
            config.setdefault(CONF_MAP_PROVIDER, DEFAULT_MAP_PROVIDER).lower(),
        )
        self.set_attr(
            CONF_MAP_ZOOM, int(config.setdefault(CONF_MAP_ZOOM, DEFAULT_MAP_ZOOM))
        )
        self.set_attr(CONF_LANGUAGE, config.get(CONF_LANGUAGE))

        if not self.is_attr_blank(CONF_LANGUAGE):
            self.set_attr(
                CONF_LANGUAGE, self.get_attr(CONF_LANGUAGE).replace(" ", "").strip()
            )
        self.set_attr(
            CONF_EXTENDED_ATTR,
            config.setdefault(CONF_EXTENDED_ATTR, DEFAULT_EXTENDED_ATTR),
        )
        self.set_attr(
            CONF_SHOW_TIME, config.setdefault(CONF_SHOW_TIME, DEFAULT_SHOW_TIME)
        )
        self.set_attr(
            CONF_DATE_FORMAT,
            config.setdefault(CONF_DATE_FORMAT, DEFAULT_DATE_FORMAT).lower(),
        )
        self.set_attr(CONF_USE_GPS, config.setdefault(CONF_USE_GPS, DEFAULT_USE_GPS))
        self.set_attr(
            ATTR_JSON_FILENAME,
            f"{DOMAIN}-{slugify(str(self.get_attr(CONF_UNIQUE_ID)))}.json",
        )
        self.set_attr(ATTR_DISPLAY_OPTIONS, self.get_attr(CONF_DISPLAY_OPTIONS))
        _LOGGER.debug(
            f"({self.get_attr(CONF_NAME)}) [Init] JSON Filename: {self.get_attr(ATTR_JSON_FILENAME)}"
        )

        self._attr_native_value = None  # Represents the state in SensorEntity
        self.clear_attr(ATTR_NATIVE_VALUE)

        if (
            not self.is_attr_blank(CONF_HOME_ZONE)
            and CONF_LATITUDE
            in hass.states.get(self.get_attr(CONF_HOME_ZONE)).attributes
            and hass.states.get(self.get_attr(CONF_HOME_ZONE)).attributes.get(
                CONF_LATITUDE
            )
            is not None
            and self.is_float(
                hass.states.get(self.get_attr(CONF_HOME_ZONE)).attributes.get(
                    CONF_LATITUDE
                )
            )
        ):
            self.set_attr(
                ATTR_HOME_LATITUDE,
                str(
                    hass.states.get(self.get_attr(CONF_HOME_ZONE)).attributes.get(
                        CONF_LATITUDE
                    )
                ),
            )
        if (
            not self.is_attr_blank(CONF_HOME_ZONE)
            and CONF_LONGITUDE
            in hass.states.get(self.get_attr(CONF_HOME_ZONE)).attributes
            and hass.states.get(self.get_attr(CONF_HOME_ZONE)).attributes.get(
                CONF_LONGITUDE
            )
            is not None
            and self.is_float(
                hass.states.get(self.get_attr(CONF_HOME_ZONE)).attributes.get(
                    CONF_LONGITUDE
                )
            )
        ):
            self.set_attr(
                ATTR_HOME_LONGITUDE,
                str(
                    hass.states.get(self.get_attr(CONF_HOME_ZONE)).attributes.get(
                        CONF_LONGITUDE
                    )
                ),
            )

        self._attr_entity_picture = (
            hass.states.get(self.get_attr(CONF_DEVICETRACKER_ID)).attributes.get(
                ATTR_PICTURE
            )
            if hass.states.get(self.get_attr(CONF_DEVICETRACKER_ID))
            else None
        )
        self.set_attr(ATTR_SHOW_DATE, False)
        # self.set_attr(ATTR_UPDATES_SKIPPED, 0)

        sensor_attributes = self.get_dict_from_json_file()
        # _LOGGER.debug(f"({self.get_attr(CONF_NAME)}) [Init] Sensor Attributes to Import: {sensor_attributes}")
        self.import_attributes_from_json(sensor_attributes)
        ##
        # For debugging:
        # sensor_attributes = {}
        # sensor_attributes.update({CONF_NAME: self.get_attr(CONF_NAME)})
        # sensor_attributes.update({ATTR_NATIVE_VALUE: self.get_attr(ATTR_NATIVE_VALUE)})
        # sensor_attributes.update(self.extra_state_attributes)
        # _LOGGER.debug(f"({self.get_attr(CONF_NAME)}) [Init] Sensor Attributes Imported: {sensor_attributes}")
        ##
        if not self.get_attr(ATTR_INITIAL_UPDATE):
            _LOGGER.debug(
                f"({self.get_attr(CONF_NAME)}) [Init] Sensor Attributes Imported from JSON file"
            )
        self.cleanup_attributes()
        if self.get_attr(CONF_EXTENDED_ATTR):
            self.disable_recorder()
        _LOGGER.info(
            f"({self.get_attr(CONF_NAME)}) [Init] Tracked Entity ID: "
            + f"{self.get_attr(CONF_DEVICETRACKER_ID)}"
        )

    def disable_recorder(self):

        if RECORDER_INSTANCE in self._hass.data:
            _LOGGER.info(
                f"({self.get_attr(CONF_NAME)}) [disable_recorder] Extended Attributes is True, Disabling Recorder"
            )

            recorder_prefilter.add_filter(self._hass, self.entity_id)
            ha_history_recorder = self._hass.data[RECORDER_INSTANCE]
            ha_history_recorder.exclude_event_types.add(EVENT_TYPE)
            _LOGGER.debug(
                f"({self.get_attr(CONF_NAME)}) [disable_recorder] exclude_event_types: {ha_history_recorder.exclude_event_types}"
            )

    def get_dict_from_json_file(self):
        sensor_attributes = {}
        try:
            with open(
                os.path.join(PLACES_JSON_FOLDER, self.get_attr(ATTR_JSON_FILENAME)),
                "r",
            ) as jsonfile:
                sensor_attributes = json.load(jsonfile)
        except OSError as e:
            _LOGGER.debug(
                f"({self.get_attr(CONF_NAME)}) [Init] No JSON file to import "
                + f"({self.get_attr(ATTR_JSON_FILENAME)}): {e}"
            )
            return {}
        except Exception as e:
            _LOGGER.debug(
                f"({self.get_attr(CONF_NAME)}) [Init] Unknown Exception importing JSON file "
                + f"({self.get_attr(ATTR_JSON_FILENAME)}): {e}"
            )
            return {}
        return sensor_attributes

    async def async_added_to_hass(self) -> None:
        """Added to hass."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_track_state_change_event(
                self.hass,
                [self.get_attr(CONF_DEVICETRACKER_ID)],
                self.async_tsc_update,
            )
        )
        _LOGGER.debug(
            f"({self.get_attr(CONF_NAME)}) [Init] Subscribed to Tracked Entity state change events"
        )

    async def async_will_remove_from_hass(self) -> None:
        """Run when entity will be removed from hass."""
        try:
            os.remove(
                os.path.join(PLACES_JSON_FOLDER, self.get_attr(ATTR_JSON_FILENAME))
            )
        except OSError as e:
            _LOGGER.debug(
                f"({self.get_attr(CONF_NAME)}) OSError removing JSON sensor file "
                + f"({self.get_attr(ATTR_JSON_FILENAME)}): {e}"
            )
        except Exception as e:
            _LOGGER.debug(
                f"({self.get_attr(CONF_NAME)}) Unknown Exception removing JSON sensor file "
                + f"({self.get_attr(ATTR_JSON_FILENAME)}): {e}"
            )
        else:
            _LOGGER.debug(
                f"({self.get_attr(CONF_NAME)}) JSON sensor file removed: "
                + f"{self.get_attr(ATTR_JSON_FILENAME)}"
            )
        if RECORDER_INSTANCE in self._hass.data and self.get_attr(CONF_EXTENDED_ATTR):
            _LOGGER.debug(
                f"({self._attr_name}) Removing entity exclusion from recorder: {self.entity_id}"
            )
            recorder_prefilter.remove_filter(self._hass, self.entity_id)

            # Only do this if no places entities with extended_attr exist
            ex_attr_count = 0
            for ent in self._hass.data[DOMAIN].values():
                if ent.get(CONF_EXTENDED_ATTR):
                    ex_attr_count += 1

            if (
                self.get_attr(CONF_EXTENDED_ATTR) and ex_attr_count == 1
            ) or ex_attr_count == 0:
                _LOGGER.debug(
                    f"({self.get_attr(CONF_NAME)}) Removing event exclusion from recorder: {EVENT_TYPE}"
                )
                ha_history_recorder = self._hass.data[RECORDER_INSTANCE]
                ha_history_recorder.exclude_event_types.discard(EVENT_TYPE)

    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        return_attr = {}
        self.cleanup_attributes()
        for attr in EXTRA_STATE_ATTRIBUTE_LIST:
            if self.get_attr(attr):
                return_attr.update({attr: self.get_attr(attr)})

        if self.get_attr(CONF_EXTENDED_ATTR):
            for attr in EXTENDED_ATTRIBUTE_LIST:
                if self.get_attr(attr):
                    return_attr.update({attr: self.get_attr(attr)})
        # _LOGGER.debug(f"({self.get_attr(CONF_NAME)}) Extra State Attributes: {return_attr}")
        return return_attr

    def import_attributes_from_json(self, json_attr=None):
        """Import the JSON state attributes. Takes a Dictionary as input."""
        if json_attr is None or not isinstance(json_attr, dict) or not json_attr:
            return

        self.set_attr(ATTR_INITIAL_UPDATE, False)
        for attr in JSON_ATTRIBUTE_LIST:
            if attr in json_attr:
                self.set_attr(attr, json_attr.pop(attr, None))
        if not self.is_attr_blank(ATTR_NATIVE_VALUE):
            self._attr_native_value = self.get_attr(ATTR_NATIVE_VALUE)

        # Remove attributes that are part of the Config and are explicitly not imported from JSON
        for attr in CONFIG_ATTRIBUTES_LIST + JSON_IGNORE_ATTRIBUTE_LIST:
            if attr in json_attr:
                json_attr.pop(attr, None)
        if json_attr is not None and json_attr:
            _LOGGER.debug(
                f"({self.get_attr(CONF_NAME)}) [import_attributes] Attributes not imported: {json_attr}"
            )

    def get_attr(self, attr, default=None):
        if attr is None or (default is None and self.is_attr_blank(attr)):
            return None
        else:
            return self._internal_attr.get(attr, default)

    def set_attr(self, attr, value=None):
        if attr is not None:
            self._internal_attr.update({attr: value})

    def clear_attr(self, attr):
        self._internal_attr.pop(attr, None)

    def is_devicetracker_set(self):
        proceed_with_update = 0
        # 0: False. 1: True. 2: False, but set direction of travel to stationary

        if (
            self.is_attr_blank(CONF_DEVICETRACKER_ID)
            or self._hass.states.get(self.get_attr(CONF_DEVICETRACKER_ID)) is None
            or (
                isinstance(
                    self._hass.states.get(self.get_attr(CONF_DEVICETRACKER_ID)), str
                )
                and self._hass.states.get(self.get_attr(CONF_DEVICETRACKER_ID)).lower()
                in ["none", STATE_UNKNOWN, STATE_UNAVAILABLE]
            )
        ):
            if self._warn_if_device_tracker_prob or self.get_attr(ATTR_INITIAL_UPDATE):
                _LOGGER.warning(
                    f"({self.get_attr(CONF_NAME)}) Tracked Entity ({self.get_attr(CONF_DEVICETRACKER_ID)}) "
                    f"is not set or is not available. Not Proceeding with Update."
                )
                self._warn_if_device_tracker_prob = False
            else:
                _LOGGER.info(
                    f"({self.get_attr(CONF_NAME)}) Tracked Entity ({self.get_attr(CONF_DEVICETRACKER_ID)}) "
                    f"is not set or is not available. Not Proceeding with Update."
                )
            return 0
            # 0: False. 1: True. 2: False, but set direction of travel to stationary
        if (
            hasattr(
                self._hass.states.get(self.get_attr(CONF_DEVICETRACKER_ID)),
                ATTR_ATTRIBUTES,
            )
            and CONF_LATITUDE
            in self._hass.states.get(self.get_attr(CONF_DEVICETRACKER_ID)).attributes
            and CONF_LONGITUDE
            in self._hass.states.get(self.get_attr(CONF_DEVICETRACKER_ID)).attributes
            and self._hass.states.get(
                self.get_attr(CONF_DEVICETRACKER_ID)
            ).attributes.get(CONF_LATITUDE)
            is not None
            and self._hass.states.get(
                self.get_attr(CONF_DEVICETRACKER_ID)
            ).attributes.get(CONF_LONGITUDE)
            is not None
            and self.is_float(
                self._hass.states.get(
                    self.get_attr(CONF_DEVICETRACKER_ID)
                ).attributes.get(CONF_LATITUDE)
            )
            and self.is_float(
                self._hass.states.get(
                    self.get_attr(CONF_DEVICETRACKER_ID)
                ).attributes.get(CONF_LONGITUDE)
            )
        ):
            self._warn_if_device_tracker_prob = True
            proceed_with_update = 1
            # 0: False. 1: True. 2: False, but set direction of travel to stationary
        else:
            if self._warn_if_device_tracker_prob or self.get_attr(ATTR_INITIAL_UPDATE):
                _LOGGER.warning(
                    f"({self.get_attr(CONF_NAME)}) Tracked Entity ({self.get_attr(CONF_DEVICETRACKER_ID)}) "
                    "Latitude/Longitude is not set or is not a number. "
                    f"Not Proceeding with Update."
                )
                self._warn_if_device_tracker_prob = False
            else:
                _LOGGER.info(
                    f"({self.get_attr(CONF_NAME)}) Tracked Entity ({self.get_attr(CONF_DEVICETRACKER_ID)}) "
                    "Latitude/Longitude is not set or is not a number. "
                    f"Not Proceeding with Update."
                )
            _LOGGER.debug(
                f"({self.get_attr(CONF_NAME)}) Tracked Entity ({self.get_attr(CONF_DEVICETRACKER_ID)}) details: "
                f"{self._hass.states.get(self.get_attr(CONF_DEVICETRACKER_ID))}"
            )
            return 0
            # 0: False. 1: True. 2: False, but set direction of travel to stationary
        return proceed_with_update

    @Throttle(MIN_THROTTLE_INTERVAL)
    @core.callback
    def async_tsc_update(self, event: EventType[EventStateChangedData]):
        """Call the do_update function based on the TSC (track state change) event"""
        # _LOGGER.debug(f"({self.get_attr(CONF_NAME)}) [TSC Update] event: {event}")
        new_state = event.data["new_state"]
        if new_state is None or (
            isinstance(new_state.state, str)
            and new_state.state.lower() in ["none", STATE_UNKNOWN, STATE_UNAVAILABLE]
        ):
            return
        # _LOGGER.debug(f"({self.get_attr(CONF_NAME)}) [TSC Update] new_state: {new_state}")

        update_type = "Track State Change"
        self._hass.async_add_executor_job(self.do_update, update_type)

    @Throttle(THROTTLE_INTERVAL)
    async def async_update(self):
        """Call the do_update function based on scan interval and throttle"""
        update_type = "Scan Interval"
        await self._hass.async_add_executor_job(self.do_update, update_type)

    def is_float(self, value):
        if value is not None:
            try:
                float(value)
                return True
            except ValueError:
                return False
        else:
            return False

    def in_zone(self):
        if not self.is_attr_blank(ATTR_DEVICETRACKER_ZONE):
            zone_state = self._hass.states.get(
                f"{CONF_ZONE}.{self.get_attr(ATTR_DEVICETRACKER_ZONE).lower()}"
            )
            if self.get_attr(CONF_DEVICETRACKER_ID).split(".")[0] == CONF_ZONE:
                return False
            elif (
                "stationary" in self.get_attr(ATTR_DEVICETRACKER_ZONE).lower()
                or self.get_attr(ATTR_DEVICETRACKER_ZONE).lower().startswith("statzon")
                or self.get_attr(ATTR_DEVICETRACKER_ZONE)
                .lower()
                .startswith("ic3_statzone_")
                or self.get_attr(ATTR_DEVICETRACKER_ZONE).lower() == "away"
                or self.get_attr(ATTR_DEVICETRACKER_ZONE).lower() == "not_home"
                or self.get_attr(ATTR_DEVICETRACKER_ZONE).lower() == "notset"
                or self.get_attr(ATTR_DEVICETRACKER_ZONE).lower() == "not_set"
            ):
                return False
            elif (
                zone_state is not None
                and zone_state.attributes.get(ATTR_PASSIVE, False) is True
            ):
                return False
            else:
                return True
        else:
            return False

    def is_attr_blank(self, attr):
        if self._internal_attr.get(attr) or self._internal_attr.get(attr) == 0:
            return False
        else:
            return True

    def cleanup_attributes(self):
        for attr in list(self._internal_attr):
            if self.is_attr_blank(attr):
                self.clear_attr(attr)

    def check_for_updated_entity_name(self):
        if hasattr(self, "entity_id") and self.entity_id is not None:
            # _LOGGER.debug(f"({self.get_attr(CONF_NAME)}) Entity ID: {self.entity_id}")
            if (
                self._hass.states.get(str(self.entity_id)) is not None
                and self._hass.states.get(str(self.entity_id)).attributes.get(
                    ATTR_FRIENDLY_NAME
                )
                is not None
                and self.get_attr(CONF_NAME)
                != self._hass.states.get(str(self.entity_id)).attributes.get(
                    ATTR_FRIENDLY_NAME
                )
            ):
                _LOGGER.debug(
                    f"({self.get_attr(CONF_NAME)}) Sensor Name Changed. Updating Name to: "
                    + f"{self._hass.states.get(str(self.entity_id)).attributes.get(ATTR_FRIENDLY_NAME)}"
                )
                self.set_attr(
                    CONF_NAME,
                    self._hass.states.get(str(self.entity_id)).attributes.get(
                        ATTR_FRIENDLY_NAME
                    ),
                )
                self._config.update({CONF_NAME: self.get_attr(CONF_NAME)})
                self.set_attr(CONF_NAME, self.get_attr(CONF_NAME))
                _LOGGER.debug(
                    f"({self.get_attr(CONF_NAME)}) Updated Config Name: "
                    + f"{self._config.get(CONF_NAME, None)}"
                )
                self._hass.config_entries.async_update_entry(
                    self._config_entry,
                    data=self._config,
                    options=self._config_entry.options,
                )
                _LOGGER.debug(
                    f"({self.get_attr(CONF_NAME)}) Updated ConfigEntry Name: "
                    + f"{self._config_entry.data.get(CONF_NAME)}"
                )

    def get_zone_details(self):
        if self.get_attr(CONF_DEVICETRACKER_ID).split(".")[0] != CONF_ZONE:
            self.set_attr(
                ATTR_DEVICETRACKER_ZONE,
                self._hass.states.get(self.get_attr(CONF_DEVICETRACKER_ID)).state,
            )
        if self.in_zone():
            devicetracker_zone_name_state = None
            devicetracker_zone_id = self._hass.states.get(
                self.get_attr(CONF_DEVICETRACKER_ID)
            ).attributes.get(CONF_ZONE)
            if devicetracker_zone_id is not None:
                devicetracker_zone_id = f"{CONF_ZONE}.{devicetracker_zone_id}"
                devicetracker_zone_name_state = self._hass.states.get(
                    devicetracker_zone_id
                )
            # _LOGGER.debug(f"({self.get_attr(CONF_NAME)}) Tracked Entity Zone ID: {devicetracker_zone_id}")
            # _LOGGER.debug(f"({self.get_attr(CONF_NAME)}) Tracked Entity Zone Name State: {devicetracker_zone_name_state}")
            if devicetracker_zone_name_state is not None:
                if (
                    devicetracker_zone_name_state.attributes.get(CONF_FRIENDLY_NAME)
                    is not None
                ):
                    self.set_attr(
                        ATTR_DEVICETRACKER_ZONE_NAME,
                        devicetracker_zone_name_state.attributes.get(
                            CONF_FRIENDLY_NAME
                        ),
                    )
                else:
                    self.set_attr(
                        ATTR_DEVICETRACKER_ZONE_NAME, devicetracker_zone_name_state.name
                    )
            else:
                self.set_attr(
                    ATTR_DEVICETRACKER_ZONE_NAME, self.get_attr(ATTR_DEVICETRACKER_ZONE)
                )

            if not self.is_attr_blank(ATTR_DEVICETRACKER_ZONE_NAME) and self.get_attr(
                ATTR_DEVICETRACKER_ZONE_NAME
            ).lower() == self.get_attr(ATTR_DEVICETRACKER_ZONE_NAME):
                self.set_attr(
                    ATTR_DEVICETRACKER_ZONE_NAME,
                    self.get_attr(ATTR_DEVICETRACKER_ZONE_NAME).title(),
                )
            _LOGGER.debug(
                f"({self.get_attr(CONF_NAME)}) Tracked Entity Zone Name: {self.get_attr(ATTR_DEVICETRACKER_ZONE_NAME)}"
            )
        else:
            _LOGGER.debug(
                f"({self.get_attr(CONF_NAME)}) Tracked Entity Zone: {self.get_attr(ATTR_DEVICETRACKER_ZONE)}"
            )
            self.set_attr(
                ATTR_DEVICETRACKER_ZONE_NAME, self.get_attr(ATTR_DEVICETRACKER_ZONE)
            )

    def determine_if_update_needed(self):
        proceed_with_update = 1
        # 0: False. 1: True. 2: False, but set direction of travel to stationary

        if self.get_attr(ATTR_INITIAL_UPDATE):
            _LOGGER.info(
                f"({self.get_attr(CONF_NAME)}) Performing Initial Update for user..."
            )
            # 0: False. 1: True. 2: False, but set direction of travel to stationary
            return 1

        elif self.is_attr_blank(ATTR_NATIVE_VALUE) or (
            isinstance(self.get_attr(ATTR_NATIVE_VALUE), str)
            and self.get_attr(ATTR_NATIVE_VALUE).lower()
            in ["none", STATE_UNKNOWN, STATE_UNAVAILABLE]
        ):
            _LOGGER.info(
                f"({self.get_attr(CONF_NAME)}) Previous State is Unknown, performing update."
            )
            # 0: False. 1: True. 2: False, but set direction of travel to stationary
            return 1

        elif self.get_attr(ATTR_LOCATION_CURRENT) == self.get_attr(
            ATTR_LOCATION_PREVIOUS
        ):
            _LOGGER.info(
                f"({self.get_attr(CONF_NAME)}) Not performing update because coordinates are identical"
            )
            return 2
            # 0: False. 1: True. 2: False, but set direction of travel to stationary
        elif int(self.get_attr(ATTR_DISTANCE_TRAVELED_M)) < 10:
            _LOGGER.info(
                f"({self.get_attr(CONF_NAME)}) Not performing update, distance traveled from last update is less than 10 m ("
                + f"{round(self.get_attr(ATTR_DISTANCE_TRAVELED_M), 1)} m)"
            )
            return 2
            # 0: False. 1: True. 2: False, but set direction of travel to stationary
        return proceed_with_update
        # 0: False. 1: True. 2: False, but set direction of travel to stationary

    def get_dict_from_url(self, url, name):
        get_dict = {}
        _LOGGER.info(f"({self.get_attr(CONF_NAME)}) Requesting data for {name}")
        _LOGGER.debug(f"({self.get_attr(CONF_NAME)}) {name} URL: {url}")
        headers = {"user-agent": f"Mozilla/5.0 (Home Assistant) {DOMAIN}/{VERSION}"}
        try:
            get_response = requests.get(url, headers=headers)
        except requests.exceptions.RetryError as e:
            get_response = None
            _LOGGER.warning(
                f"({self.get_attr(CONF_NAME)}) Retry Error connecting to {name} [Error: {e}]: {url}"
            )
            return {}
        except requests.exceptions.ConnectionError as e:
            get_response = None
            _LOGGER.warning(
                f"({self.get_attr(CONF_NAME)}) Connection Error connecting to {name} [Error: {e}]: {url}"
            )
            return {}
        except requests.exceptions.HTTPError as e:
            get_response = None
            _LOGGER.warning(
                f"({self.get_attr(CONF_NAME)}) HTTP Error connecting to {name} [Error: {e}]: {url}"
            )
            return {}
        except requests.exceptions.Timeout as e:
            get_response = None
            _LOGGER.warning(
                f"({self.get_attr(CONF_NAME)}) Timeout connecting to {name} [Error: {e}]: {url}"
            )
            return {}
        except OSError as e:
            # Includes error code 101, network unreachable
            get_response = None
            _LOGGER.warning(
                f"({self.get_attr(CONF_NAME)}) Network unreachable error when connecting to {name} "
                + f"[Error: {e}]: {url}"
            )
            return {}
        except NewConnectionError as e:
            get_response = None
            _LOGGER.warning(
                f"({self.get_attr(CONF_NAME)}) New Connection Error connecting to {name} "
                + f"[Error: {e}]: {url}"
            )
            return {}
        except Exception as e:
            get_response = None
            _LOGGER.warning(
                f"({self.get_attr(CONF_NAME)}) Unknown Exception connecting to {name} "
                + f"[Error: {e}]: {url}"
            )
            return {}

        get_json_input = {}
        if get_response is not None and get_response:
            get_json_input = get_response.text
            _LOGGER.debug(
                f"({self.get_attr(CONF_NAME)}) {name} Response: {get_json_input}"
            )

        if get_json_input is not None and get_json_input:
            try:
                get_dict = json.loads(get_json_input)
            except json.decoder.JSONDecodeError as e:
                _LOGGER.warning(
                    f"({self.get_attr(CONF_NAME)}) JSON Decode Error with {name} info "
                    + f"[Error: {e}]: {get_json_input}"
                )
                return {}
        if "error_message" in get_dict:
            _LOGGER.warning(
                f"({self.get_attr(CONF_NAME)}) An error occurred contacting the web service for "
                + f"{name}: {get_dict.get('error_message')}"
            )
            return {}
        return get_dict

    def get_map_link(self):

        if self.get_attr(CONF_MAP_PROVIDER) == "google":
            self.set_attr(
                ATTR_MAP_LINK,
                (
                    f"https://maps.google.com/?q={self.get_attr(ATTR_LOCATION_CURRENT)}"
                    + f"&ll={self.get_attr(ATTR_LOCATION_CURRENT)}&z={self.get_attr(CONF_MAP_ZOOM)}"
                ),
            )
        elif self.get_attr(CONF_MAP_PROVIDER) == "osm":
            self.set_attr(
                ATTR_MAP_LINK,
                (
                    f"https://www.openstreetmap.org/?mlat={self.get_attr(ATTR_LATITUDE)}"
                    + f"&mlon={self.get_attr(ATTR_LONGITUDE)}#map={self.get_attr(CONF_MAP_ZOOM)}/"
                    + f"{str(self.get_attr(ATTR_LATITUDE))[:8]}/{str(self.get_attr(ATTR_LONGITUDE))[:9]}"
                ),
            )
        else:
            self.set_attr(
                ATTR_MAP_LINK,
                (
                    "https://maps.apple.com/maps/?q="
                    + f"{self.get_attr(ATTR_LOCATION_CURRENT)}&z={self.get_attr(CONF_MAP_ZOOM)}"
                ),
            )
        _LOGGER.debug(
            f"({self.get_attr(CONF_NAME)}) Map Link Type: {self.get_attr(CONF_MAP_PROVIDER)}"
        )
        _LOGGER.debug(
            f"({self.get_attr(CONF_NAME)}) Map Link URL: {self.get_attr(ATTR_MAP_LINK)}"
        )

    def get_gps_accuracy(self):
        if (
            self._hass.states.get(self.get_attr(CONF_DEVICETRACKER_ID))
            and self._hass.states.get(self.get_attr(CONF_DEVICETRACKER_ID)).attributes
            and ATTR_GPS_ACCURACY
            in self._hass.states.get(self.get_attr(CONF_DEVICETRACKER_ID)).attributes
            and self._hass.states.get(
                self.get_attr(CONF_DEVICETRACKER_ID)
            ).attributes.get(ATTR_GPS_ACCURACY)
            is not None
            and self.is_float(
                self._hass.states.get(
                    self.get_attr(CONF_DEVICETRACKER_ID)
                ).attributes.get(ATTR_GPS_ACCURACY)
            )
        ):
            self.set_attr(
                ATTR_GPS_ACCURACY,
                float(
                    self._hass.states.get(
                        self.get_attr(CONF_DEVICETRACKER_ID)
                    ).attributes.get(ATTR_GPS_ACCURACY)
                ),
            )
        else:
            _LOGGER.debug(
                f"({self.get_attr(CONF_NAME)}) GPS Accuracy attribute not found in: "
                + f"{self.get_attr(CONF_DEVICETRACKER_ID)}"
            )
        proceed_with_update = 1
        # 0: False. 1: True. 2: False, but set direction of travel to stationary

        if not self.is_attr_blank(ATTR_GPS_ACCURACY):
            if self.get_attr(CONF_USE_GPS) and self.get_attr(ATTR_GPS_ACCURACY) == 0:
                proceed_with_update = 0
                # 0: False. 1: True. 2: False, but set direction of travel to stationary
                _LOGGER.info(
                    f"({self.get_attr(CONF_NAME)}) GPS Accuracy is 0.0, not performing update"
                )
            else:
                _LOGGER.debug(
                    f"({self.get_attr(CONF_NAME)}) GPS Accuracy: "
                    + f"{round(self.get_attr(ATTR_GPS_ACCURACY), 3)}"
                )
        return proceed_with_update

    def get_driving_status(self):
        self.clear_attr(ATTR_DRIVING)
        isDriving = False
        if not self.in_zone():
            if self.get_attr(ATTR_DIRECTION_OF_TRAVEL) != "stationary" and (
                self.get_attr(ATTR_PLACE_CATEGORY) == "highway"
                or self.get_attr(ATTR_PLACE_TYPE) == "motorway"
            ):
                isDriving = True
        if isDriving:
            self.set_attr(ATTR_DRIVING, "Driving")

    def parse_osm_dict(self):
        if "type" in self.get_attr(ATTR_OSM_DICT):
            self.set_attr(ATTR_PLACE_TYPE, self.get_attr(ATTR_OSM_DICT).get("type"))
            if self.get_attr(ATTR_PLACE_TYPE) == "yes":
                if "addresstype" in self.get_attr(ATTR_OSM_DICT):
                    self.set_attr(
                        ATTR_PLACE_TYPE,
                        self.get_attr(ATTR_OSM_DICT).get("addresstype"),
                    )
                else:
                    self.clear_attr(ATTR_PLACE_TYPE)
            if "address" in self.get_attr(ATTR_OSM_DICT) and self.get_attr(
                ATTR_PLACE_TYPE
            ) in self.get_attr(ATTR_OSM_DICT).get("address"):
                self.set_attr(
                    ATTR_PLACE_NAME,
                    self.get_attr(ATTR_OSM_DICT)
                    .get("address")
                    .get(self.get_attr(ATTR_PLACE_TYPE)),
                )
        if "category" in self.get_attr(ATTR_OSM_DICT):
            self.set_attr(
                ATTR_PLACE_CATEGORY,
                self.get_attr(ATTR_OSM_DICT).get("category"),
            )
            if "address" in self.get_attr(ATTR_OSM_DICT) and self.get_attr(
                ATTR_PLACE_CATEGORY
            ) in self.get_attr(ATTR_OSM_DICT).get("address"):
                self.set_attr(
                    ATTR_PLACE_NAME,
                    self.get_attr(ATTR_OSM_DICT)
                    .get("address")
                    .get(self.get_attr(ATTR_PLACE_CATEGORY)),
                )
        if (
            "namedetails" in self.get_attr(ATTR_OSM_DICT)
            and self.get_attr(ATTR_OSM_DICT).get("namedetails") is not None
        ):
            if "name" in self.get_attr(ATTR_OSM_DICT).get("namedetails"):
                self.set_attr(
                    ATTR_PLACE_NAME,
                    self.get_attr(ATTR_OSM_DICT).get("namedetails").get("name"),
                )
            if not self.is_attr_blank(CONF_LANGUAGE):
                for language in self.get_attr(CONF_LANGUAGE).split(","):
                    if "name:" + language in self.get_attr(ATTR_OSM_DICT).get(
                        "namedetails"
                    ):
                        self.set_attr(
                            ATTR_PLACE_NAME,
                            self.get_attr(ATTR_OSM_DICT)
                            .get("namedetails")
                            .get("name:" + language),
                        )
                        break
        # if not self.in_zone() and self.get_attr(ATTR_PLACE_NAME) != "house":
        #    self.set_attr(ATTR_NATIVE_VALUE, self.get_attr(ATTR_PLACE_NAME))

        if (
            "address" in self.get_attr(ATTR_OSM_DICT)
            and self.get_attr(ATTR_OSM_DICT).get("address") is not None
        ):
            if "house_number" in self.get_attr(ATTR_OSM_DICT).get("address"):
                self.set_attr(
                    ATTR_STREET_NUMBER,
                    (self.get_attr(ATTR_OSM_DICT).get("address").get("house_number")),
                )
            if "road" in self.get_attr(ATTR_OSM_DICT).get("address"):
                self.set_attr(
                    ATTR_STREET,
                    self.get_attr(ATTR_OSM_DICT).get("address").get("road"),
                )
            if "retail" in self.get_attr(ATTR_OSM_DICT).get("address") and (
                self.is_attr_blank(ATTR_PLACE_NAME)
                or (
                    not self.is_attr_blank(ATTR_PLACE_CATEGORY)
                    and not self.is_attr_blank(ATTR_STREET)
                    and self.get_attr(ATTR_PLACE_CATEGORY) == "highway"
                    and self.get_attr(ATTR_STREET) == self.get_attr(ATTR_PLACE_NAME)
                )
            ):
                self.set_attr(
                    ATTR_PLACE_NAME,
                    self.get_attr(ATTR_OSM_DICT).get("address").get("retail"),
                )
            _LOGGER.debug(
                f"({self.get_attr(CONF_NAME)}) Place Name: "
                + f"{self.get_attr(ATTR_PLACE_NAME)}"
            )

            if "neighbourhood" in self.get_attr(ATTR_OSM_DICT).get("address"):
                self.set_attr(
                    ATTR_PLACE_NEIGHBOURHOOD,
                    self.get_attr(ATTR_OSM_DICT).get("address").get("neighbourhood"),
                )
            elif "hamlet" in self.get_attr(ATTR_OSM_DICT).get("address"):
                self.set_attr(
                    ATTR_PLACE_NEIGHBOURHOOD,
                    self.get_attr(ATTR_OSM_DICT).get("address").get("hamlet"),
                )
            elif "residential" in self.get_attr(ATTR_OSM_DICT).get("address"):
                self.set_attr(
                    ATTR_PLACE_NEIGHBOURHOOD,
                    self.get_attr(ATTR_OSM_DICT).get("address").get("residential"),
                )

            if "city" in self.get_attr(ATTR_OSM_DICT).get("address"):
                self.set_attr(
                    ATTR_CITY,
                    self.get_attr(ATTR_OSM_DICT).get("address").get("city"),
                )
            elif "town" in self.get_attr(ATTR_OSM_DICT).get("address"):
                self.set_attr(
                    ATTR_CITY,
                    self.get_attr(ATTR_OSM_DICT).get("address").get("town"),
                )
            elif "village" in self.get_attr(ATTR_OSM_DICT).get("address"):
                self.set_attr(
                    ATTR_CITY,
                    self.get_attr(ATTR_OSM_DICT).get("address").get("village"),
                )
            elif "township" in self.get_attr(ATTR_OSM_DICT).get("address"):
                self.set_attr(
                    ATTR_CITY,
                    self.get_attr(ATTR_OSM_DICT).get("address").get("township"),
                )
            elif "municipality" in self.get_attr(ATTR_OSM_DICT).get("address"):
                self.set_attr(
                    ATTR_CITY,
                    self.get_attr(ATTR_OSM_DICT).get("address").get("municipality"),
                )
            elif "city_district" in self.get_attr(ATTR_OSM_DICT).get("address"):
                self.set_attr(
                    ATTR_CITY,
                    self.get_attr(ATTR_OSM_DICT).get("address").get("city_district"),
                )
            if not self.is_attr_blank(ATTR_CITY):
                self.set_attr(
                    ATTR_CITY_CLEAN,
                    self.get_attr(ATTR_CITY).replace(" Township", "").strip(),
                )
                if self.get_attr(ATTR_CITY_CLEAN).startswith("City of"):
                    self.set_attr(
                        ATTR_CITY_CLEAN, self.get_attr(ATTR_CITY_CLEAN)[8:] + " City"
                    )

            if "city_district" in self.get_attr(ATTR_OSM_DICT).get("address"):
                self.set_attr(
                    ATTR_POSTAL_TOWN,
                    self.get_attr(ATTR_OSM_DICT).get("address").get("city_district"),
                )
            if "suburb" in self.get_attr(ATTR_OSM_DICT).get("address"):
                self.set_attr(
                    ATTR_POSTAL_TOWN,
                    self.get_attr(ATTR_OSM_DICT).get("address").get("suburb"),
                )
            if "state" in self.get_attr(ATTR_OSM_DICT).get("address"):
                self.set_attr(
                    ATTR_REGION,
                    self.get_attr(ATTR_OSM_DICT).get("address").get("state"),
                )
            if "ISO3166-2-lvl4" in self.get_attr(ATTR_OSM_DICT).get("address"):
                self.set_attr(
                    ATTR_STATE_ABBR,
                    (
                        self.get_attr(ATTR_OSM_DICT)
                        .get("address")
                        .get("ISO3166-2-lvl4")
                        .split("-")[1]
                        .upper()
                    ),
                )
            if "county" in self.get_attr(ATTR_OSM_DICT).get("address"):
                self.set_attr(
                    ATTR_COUNTY,
                    self.get_attr(ATTR_OSM_DICT).get("address").get("county"),
                )
            if "country" in self.get_attr(ATTR_OSM_DICT).get("address"):
                self.set_attr(
                    ATTR_COUNTRY,
                    self.get_attr(ATTR_OSM_DICT).get("address").get("country"),
                )
            if "country_code" in self.get_attr(ATTR_OSM_DICT).get("address"):
                self.set_attr(
                    ATTR_COUNTRY_CODE,
                    self.get_attr(ATTR_OSM_DICT)
                    .get("address")
                    .get("country_code")
                    .upper(),
                )
            if "postcode" in self.get_attr(ATTR_OSM_DICT).get("address"):
                self.set_attr(
                    ATTR_POSTAL_CODE,
                    self.get_attr(ATTR_OSM_DICT).get("address").get("postcode"),
                )
        if "display_name" in self.get_attr(ATTR_OSM_DICT):
            self.set_attr(
                ATTR_FORMATTED_ADDRESS,
                self.get_attr(ATTR_OSM_DICT).get("display_name"),
            )

        if "osm_id" in self.get_attr(ATTR_OSM_DICT):
            self.set_attr(ATTR_OSM_ID, str(self.get_attr(ATTR_OSM_DICT).get("osm_id")))
        if "osm_type" in self.get_attr(ATTR_OSM_DICT):
            self.set_attr(ATTR_OSM_TYPE, self.get_attr(ATTR_OSM_DICT).get("osm_type"))

        if (
            not self.is_attr_blank(ATTR_PLACE_CATEGORY)
            and self.get_attr(ATTR_PLACE_CATEGORY).lower() == "highway"
            and "namedetails" in self.get_attr(ATTR_OSM_DICT)
            and self.get_attr(ATTR_OSM_DICT).get("namedetails") is not None
            and "ref" in self.get_attr(ATTR_OSM_DICT).get("namedetails")
        ):
            street_refs = re.split(
                r"[\;\\\/\,\.\:]",
                self.get_attr(ATTR_OSM_DICT).get("namedetails").get("ref"),
            )
            street_refs = [i for i in street_refs if i.strip()]  # Remove blank strings
            # _LOGGER.debug(f"({self.get_attr(CONF_NAME)}) Street Refs: {street_refs}")
            for ref in street_refs:
                if bool(re.search(r"\d", ref)):
                    self.set_attr(ATTR_STREET_REF, ref)
                    break
            if not self.is_attr_blank(ATTR_STREET_REF):
                _LOGGER.debug(
                    f"({self.get_attr(CONF_NAME)}) Street: {self.get_attr(ATTR_STREET)}"
                    + f" / Street Ref: {self.get_attr(ATTR_STREET_REF)}"
                )
        dupe_attributes_check = []
        for attr in PLACE_NAME_DUPLICATE_LIST:
            if not self.is_attr_blank(attr):
                dupe_attributes_check.append(self.get_attr(attr))
        if (
            not self.is_attr_blank(ATTR_PLACE_NAME)
            and self.get_attr(ATTR_PLACE_NAME) not in dupe_attributes_check
        ):
            self.set_attr(ATTR_PLACE_NAME_NO_DUPE, self.get_attr(ATTR_PLACE_NAME))

        _LOGGER.debug(
            f"({self.get_attr(CONF_NAME)}) Entity attributes after parsing OSM Dict: {self._internal_attr}"
        )

    def build_formatted_place(self):
        formatted_place_array = []
        if not self.in_zone():
            if not self.is_attr_blank(ATTR_DRIVING) and "driving" in self.get_attr(
                ATTR_DISPLAY_OPTIONS_LIST
            ):
                formatted_place_array.append(self.get_attr(ATTR_DRIVING))
            # Don't use place name if the same as another attributes
            use_place_name = True
            sensor_attributes_values = []
            for attr in PLACE_NAME_DUPLICATE_LIST:
                if not self.is_attr_blank(attr):
                    sensor_attributes_values.append(self.get_attr(attr))
            # if not self.is_attr_blank(ATTR_PLACE_NAME):
            # _LOGGER.debug(f"({self.get_attr(CONF_NAME)}) Duplicated List [Place Name: {self.get_attr(ATTR_PLACE_NAME)}]: {sensor_attributes_values}")
            if self.is_attr_blank(ATTR_PLACE_NAME):
                use_place_name = False
                # _LOGGER.debug(f"({self.get_attr(CONF_NAME)}) Place Name is None")
            elif self.get_attr(ATTR_PLACE_NAME) in sensor_attributes_values:
                # _LOGGER.debug(f"({self.get_attr(CONF_NAME)}) Not Using Place Name: {self.get_attr(ATTR_PLACE_NAME)}")
                use_place_name = False
            _LOGGER.debug(
                f"({self.get_attr(CONF_NAME)}) use_place_name: {use_place_name}"
            )
            if not use_place_name:
                if (
                    not self.is_attr_blank(ATTR_PLACE_TYPE)
                    and self.get_attr(ATTR_PLACE_TYPE).lower() != "unclassified"
                    and self.get_attr(ATTR_PLACE_CATEGORY).lower() != "highway"
                ):
                    formatted_place_array.append(
                        self.get_attr(ATTR_PLACE_TYPE)
                        .title()
                        .replace("Proposed", "")
                        .replace("Construction", "")
                        .strip()
                    )
                elif (
                    not self.is_attr_blank(ATTR_PLACE_CATEGORY)
                    and self.get_attr(ATTR_PLACE_CATEGORY).lower() != "highway"
                ):
                    formatted_place_array.append(
                        self.get_attr(ATTR_PLACE_CATEGORY).title().strip()
                    )
                street = None
                if self.is_attr_blank(ATTR_STREET) and not self.is_attr_blank(
                    ATTR_STREET_REF
                ):
                    street = self.get_attr(ATTR_STREET_REF).strip()
                    _LOGGER.debug(
                        f"({self.get_attr(CONF_NAME)}) Using street_ref: {street}"
                    )
                elif not self.is_attr_blank(ATTR_STREET):
                    if (
                        not self.is_attr_blank(ATTR_PLACE_CATEGORY)
                        and self.get_attr(ATTR_PLACE_CATEGORY).lower() == "highway"
                        and not self.is_attr_blank(ATTR_PLACE_TYPE)
                        and self.get_attr(ATTR_PLACE_TYPE).lower()
                        in ["motorway", "trunk"]
                        and not self.is_attr_blank(ATTR_STREET_REF)
                    ):
                        street = self.get_attr(ATTR_STREET_REF).strip()
                        _LOGGER.debug(
                            f"({self.get_attr(CONF_NAME)}) Using street_ref: {street}"
                        )
                    else:
                        street = self.get_attr(ATTR_STREET).strip()
                        _LOGGER.debug(
                            f"({self.get_attr(CONF_NAME)}) Using street: {street}"
                        )
                if street and self.is_attr_blank(ATTR_STREET_NUMBER):
                    formatted_place_array.append(street)
                elif street and not self.is_attr_blank(ATTR_STREET_NUMBER):
                    formatted_place_array.append(
                        f"{str(self.get_attr(ATTR_STREET_NUMBER)).strip()} {street}"
                    )
                if (
                    not self.is_attr_blank(ATTR_PLACE_TYPE)
                    and self.get_attr(ATTR_PLACE_TYPE).lower() == "house"
                    and not self.is_attr_blank(ATTR_PLACE_NEIGHBOURHOOD)
                ):
                    formatted_place_array.append(
                        self.get_attr(ATTR_PLACE_NEIGHBOURHOOD).strip()
                    )

            else:
                formatted_place_array.append(self.get_attr(ATTR_PLACE_NAME).strip())
            if not self.is_attr_blank(ATTR_CITY):
                formatted_place_array.append(
                    self.get_attr(ATTR_CITY).replace(" Township", "").strip()
                )
            elif not self.is_attr_blank(ATTR_COUNTY):
                formatted_place_array.append(self.get_attr(ATTR_COUNTY).strip())
            if not self.is_attr_blank(ATTR_STATE_ABBR):
                formatted_place_array.append(self.get_attr(ATTR_STATE_ABBR))
        else:
            formatted_place_array.append(
                self.get_attr(ATTR_DEVICETRACKER_ZONE_NAME).strip()
            )
        formatted_place = ", ".join(item for item in formatted_place_array)
        formatted_place = formatted_place.replace("\n", " ").replace("  ", " ").strip()
        self.set_attr(ATTR_FORMATTED_PLACE, formatted_place)

    def build_from_advanced_options(self, curr_options):
        # _LOGGER.debug(f"({self.get_attr(CONF_NAME)}) [adv_options] Options: {curr_options}")
        if curr_options.count("[") != curr_options.count("]"):
            _LOGGER.error(
                f"({self.get_attr(CONF_NAME)}) [adv_options] Bracket Count Mismatch: {curr_options}"
            )
            return
        elif curr_options.count("(") != curr_options.count(")"):
            _LOGGER.error(
                f"({self.get_attr(CONF_NAME)}) [adv_options] Parenthesis Count Mismatch: {curr_options}"
            )
            return
        incl = []
        excl = []
        incl_attr = {}
        excl_attr = {}
        none_opt = None
        next_opt = None
        if curr_options is None or not curr_options:
            return
        elif "[" in curr_options or "(" in curr_options:
            # _LOGGER.debug(f"({self.get_attr(CONF_NAME)}) [adv_options] Options has a [ or ( and optional ,")
            comma_num = curr_options.find(",")
            bracket_num = curr_options.find("[")
            paren_num = curr_options.find("(")
            if (
                comma_num != -1
                and (bracket_num == -1 or comma_num < bracket_num)
                and (paren_num == -1 or comma_num < paren_num)
            ):
                # Comma is first symbol
                # _LOGGER.debug(f"({self.get_attr(CONF_NAME)}) [adv_options] Comma is First")
                opt = curr_options[:comma_num]
                # _LOGGER.debug(f"({self.get_attr(CONF_NAME)}) [adv_options] Option: {opt}")
                if opt is not None and opt:
                    ret_state = self.get_option_state(opt.strip())
                    if ret_state is not None and ret_state:
                        self.adv_options_state_list.append(ret_state)
                        _LOGGER.debug(
                            f"({self.get_attr(CONF_NAME)}) [adv_options] Updated state list: "
                            + f"{self.adv_options_state_list}"
                        )
                next_opt = curr_options[(comma_num + 1):]
                # _LOGGER.debug(f"({self.get_attr(CONF_NAME)}) [adv_options] Next Options: {next_opt}")
                if next_opt is not None and next_opt:
                    self.build_from_advanced_options(next_opt.strip())
                    # _LOGGER.debug(f"({self.get_attr(CONF_NAME)}) [adv_options] Back from recursion")
                return
            elif (
                bracket_num != -1
                and (comma_num == -1 or bracket_num < comma_num)
                and (paren_num == -1 or bracket_num < paren_num)
            ):
                # Bracket is first symbol
                # _LOGGER.debug(f"({self.get_attr(CONF_NAME)}) [adv_options] Bracket is First")
                opt = curr_options[:bracket_num]
                # _LOGGER.debug(f"({self.get_attr(CONF_NAME)}) [adv_options] Option: {opt}")
                none_opt, next_opt = self.parse_bracket(curr_options[bracket_num:])
                if (
                    next_opt is not None
                    and next_opt
                    and len(next_opt) > 1
                    and next_opt[0] == "("
                ):
                    # Parse Parenthesis
                    incl, excl, incl_attr, excl_attr, next_opt = self.parse_parens(
                        next_opt
                    )

                if opt is not None and opt:
                    ret_state = self.get_option_state(
                        opt.strip(), incl, excl, incl_attr, excl_attr
                    )
                    if ret_state is not None and ret_state:
                        self.adv_options_state_list.append(ret_state)
                        _LOGGER.debug(
                            f"({self.get_attr(CONF_NAME)}) [adv_options] Updated state list: "
                            + f"{self.adv_options_state_list}"
                        )
                    elif none_opt is not None and none_opt:
                        self.build_from_advanced_options(none_opt.strip())
                        # _LOGGER.debug(f"({self.get_attr(CONF_NAME)}) [adv_options] Back from recursion")

                if (
                    next_opt is not None
                    and next_opt
                    and len(next_opt) > 1
                    and next_opt[0] == ","
                ):
                    next_opt = next_opt[1:]
                    # _LOGGER.debug(f"({self.get_attr(CONF_NAME)}) [adv_options] Next Options: {next_opt}")
                    if next_opt is not None and next_opt:
                        self.build_from_advanced_options(next_opt.strip())
                        # _LOGGER.debug(f"({self.get_attr(CONF_NAME)}) [adv_options] Back from recursion")
                return
            elif (
                paren_num != -1
                and (comma_num == -1 or paren_num < comma_num)
                and (bracket_num == -1 or paren_num < bracket_num)
            ):
                # Parenthesis is first symbol
                # _LOGGER.debug(f"({self.get_attr(CONF_NAME)}) [adv_options] Parenthesis is First")
                opt = curr_options[:paren_num]
                # _LOGGER.debug(f"({self.get_attr(CONF_NAME)}) [adv_options] Option: {opt}")
                incl, excl, incl_attr, excl_attr, next_opt = self.parse_parens(
                    curr_options[paren_num:]
                )
                if (
                    next_opt is not None
                    and next_opt
                    and len(next_opt) > 1
                    and next_opt[0] == "["
                ):
                    # Parse Bracket
                    none_opt, next_opt = self.parse_bracket(next_opt)

                if opt is not None and opt:
                    ret_state = self.get_option_state(
                        opt.strip(), incl, excl, incl_attr, excl_attr
                    )
                    if ret_state is not None and ret_state:
                        self.adv_options_state_list.append(ret_state)
                        _LOGGER.debug(
                            f"({self.get_attr(CONF_NAME)}) [adv_options] Updated state list: "
                            + f"{self.adv_options_state_list}"
                        )
                    elif none_opt is not None and none_opt:
                        self.build_from_advanced_options(none_opt.strip())
                        # _LOGGER.debug(f"({self.get_attr(CONF_NAME)}) [adv_options] Back from recursion")

                if (
                    next_opt is not None
                    and next_opt
                    and len(next_opt) > 1
                    and next_opt[0] == ","
                ):
                    next_opt = next_opt[1:]
                    # _LOGGER.debug(f"({self.get_attr(CONF_NAME)}) [adv_options] Next Options: {next_opt}")
                    if next_opt is not None and next_opt:
                        self.build_from_advanced_options(next_opt.strip())
                        # _LOGGER.debug(f"({self.get_attr(CONF_NAME)}) [adv_options] Back from recursion")
                return
            return
        elif "," in curr_options:
            # _LOGGER.debug(f"({self.get_attr(CONF_NAME)}) [adv_options] Options has , but no [ or (, splitting")
            for opt in curr_options.split(","):
                if opt is not None and opt:
                    ret_state = self.get_option_state(opt.strip())
                    if ret_state is not None and ret_state:
                        self.adv_options_state_list.append(ret_state)
                        _LOGGER.debug(
                            f"({self.get_attr(CONF_NAME)}) [adv_options] Updated state list: "
                            + f"{self.adv_options_state_list}"
                        )
            return
        else:
            # _LOGGER.debug(f"({self.get_attr(CONF_NAME)}) [adv_options] Options should just be a single term")
            ret_state = self.get_option_state(curr_options.strip())
            if ret_state is not None and ret_state:
                self.adv_options_state_list.append(ret_state)
                _LOGGER.debug(
                    f"({self.get_attr(CONF_NAME)}) [adv_options] Updated state list: "
                    + f"{self.adv_options_state_list}"
                )
            return
        return

    def parse_parens(self, curr_options):
        incl = []
        excl = []
        incl_attr = {}
        excl_attr = {}
        incl_excl_list = []
        empty_paren = False
        next_opt = None
        paren_count = 1
        close_paren_num = 0
        last_comma = -1
        if curr_options[0] == "(":
            curr_options = curr_options[1:]
        if curr_options[0] == ")":
            empty_paren = True
            close_paren_num = 0
        else:
            for i, c in enumerate(curr_options):
                if c in [",", ")"] and paren_count == 1:
                    incl_excl_list.append(curr_options[(last_comma + 1): i].strip())
                    last_comma = i
                if c == "(":
                    paren_count += 1
                elif c == ")":
                    paren_count -= 1
                if paren_count == 0:
                    close_paren_num = i
                    break

        if close_paren_num > 0 and paren_count == 0 and incl_excl_list:
            # _LOGGER.debug(f"({self.get_attr(CONF_NAME)}) [parse_parens] incl_excl_list: {incl_excl_list}")
            paren_first = True
            paren_incl = True
            for item in incl_excl_list:
                if paren_first:
                    paren_first = False
                    if item == "-":
                        paren_incl = False
                        # _LOGGER.debug(f"({self.get_attr(CONF_NAME)}) [parse_parens] excl")
                        continue
                    # else:
                    #    _LOGGER.debug(f"({self.get_attr(CONF_NAME)}) [parse_parens] incl")
                    if item == "+":
                        continue
                # _LOGGER.debug(f"({self.get_attr(CONF_NAME)}) [parse_parens] item: {item}")
                if item is not None and item:
                    if "(" in item:
                        if (
                            ")" not in item
                            or item.count("(") > 1
                            or item.count(")") > 1
                        ):
                            _LOGGER.error(
                                f"({self.get_attr(CONF_NAME)}) [parse_parens] Parenthesis Mismatch: {item}"
                            )
                            continue
                        paren_attr = item[: item.find("(")]
                        paren_attr_first = True
                        paren_attr_incl = True
                        paren_attr_list = []
                        for attr_item in item[
                            (item.find("(") + 1): item.find(")")
                        ].split(","):

                            if paren_attr_first:
                                paren_attr_first = False
                                if attr_item == "-":
                                    paren_attr_incl = False
                                    # _LOGGER.debug(f"({self.get_attr(CONF_NAME)}) [parse_parens] attr_excl")
                                    continue
                                # else:
                                # _LOGGER.debug(f"({self.get_attr(CONF_NAME)}) [parse_parens] attr_incl")
                                if attr_item == "+":
                                    continue
                            # _LOGGER.debug(f"({self.get_attr(CONF_NAME)}) [parse_parens] attr: {paren_attr} / item: {attr_item}")
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
            _LOGGER.error(
                f"({self.get_attr(CONF_NAME)}) [parse_parens] Parenthesis Mismatch: {curr_options}"
            )
        next_opt = curr_options[(close_paren_num + 1):]
        # _LOGGER.debug(f"({self.get_attr(CONF_NAME)}) [parse_parens] Raw Next Options: {next_opt}")
        return incl, excl, incl_attr, excl_attr, next_opt

    def parse_bracket(self, curr_options):
        # _LOGGER.debug(f"({self.get_attr(CONF_NAME)}) [parse_bracket] Options: {curr_options}")
        empty_bracket = False
        none_opt = None
        next_opt = None
        bracket_count = 1
        close_bracket_num = 0
        if curr_options[0] == "[":
            curr_options = curr_options[1:]
        if curr_options[0] == "]":
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
            # _LOGGER.debug(f"({self.get_attr(CONF_NAME)}) [parse_bracket] None Options: {none_opt}")
            next_opt = curr_options[(close_bracket_num + 1):].strip()
            # _LOGGER.debug(f"({self.get_attr(CONF_NAME)}) [parse_bracket] Raw Next Options: {next_opt}")
        else:
            _LOGGER.error(
                f"({self.get_attr(CONF_NAME)}) [parse_bracket] Bracket Mismatch Error: {curr_options}"
            )
        return none_opt, next_opt

    def get_option_state(
        self, opt, incl=None, excl=None, incl_attr=None, excl_attr=None
    ):
        incl = [] if incl is None else incl
        excl = [] if excl is None else excl
        incl_attr = {} if incl_attr is None else incl_attr
        excl_attr = {} if excl_attr is None else excl_attr
        if opt is not None and opt:
            opt = str(opt).lower().strip()
        # _LOGGER.debug(f"({self.get_attr(CONF_NAME)}) [get_option_state] Option: {opt}")
        out = self.get_attr(DISPLAY_OPTIONS_MAP.get(opt))
        if (
            DISPLAY_OPTIONS_MAP.get(opt)
            in [ATTR_DEVICETRACKER_ZONE, ATTR_DEVICETRACKER_ZONE_NAME]
            and not self.in_zone()
        ):
            out = None
        _LOGGER.debug(f"({self.get_attr(CONF_NAME)}) [get_option_state] State: {out}")
        # _LOGGER.debug(f"({self.get_attr(CONF_NAME)}) [get_option_state] incl list: {incl}")
        # _LOGGER.debug(f"({self.get_attr(CONF_NAME)}) [get_option_state] excl list: {excl}")
        # _LOGGER.debug(f"({self.get_attr(CONF_NAME)}) [get_option_state] incl_attr dict: {incl_attr}")
        # _LOGGER.debug(f"({self.get_attr(CONF_NAME)}) [get_option_state] excl_attr dict: {excl_attr}")
        if out is not None and out:
            if incl and str(out).strip().lower() not in incl:
                out = None
            elif excl and str(out).strip().lower() in excl:
                out = None
            if incl_attr:
                for attr, states in incl_attr.items():
                    # _LOGGER.debug(f"({self.get_attr(CONF_NAME)}) [get_option_state] incl_attr: {attr} / State: {self.get_attr(DISPLAY_OPTIONS_MAP.get(attr))}")
                    # _LOGGER.debug(f"({self.get_attr(CONF_NAME)}) [get_option_state] incl_states: {states}")
                    if (
                        self.is_attr_blank(DISPLAY_OPTIONS_MAP.get(attr))
                        or self.get_attr(DISPLAY_OPTIONS_MAP.get(attr)) not in states
                    ):
                        out = None
            if excl_attr:
                for attr, states in excl_attr.items():
                    # _LOGGER.debug(f"({self.get_attr(CONF_NAME)}) [get_option_state] excl_attr: {attr} / State: {self.get_attr(DISPLAY_OPTIONS_MAP.get(attr))}")
                    # _LOGGER.debug(f"({self.get_attr(CONF_NAME)}) [get_option_state] excl_states: {states}")
                    if self.get_attr(DISPLAY_OPTIONS_MAP.get(attr)) in states:
                        out = None
            _LOGGER.debug(
                f"({self.get_attr(CONF_NAME)}) [get_option_state] State after incl/excl: {out}"
            )
        if out is not None and out:
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
                self.street_i = self.temp_i
                # _LOGGER.debug(f"({self.get_attr(CONF_NAME)}) [get_option_state] street_i: {self.street_i}")
            if DISPLAY_OPTIONS_MAP.get(opt) == ATTR_STREET_NUMBER:
                self.street_num_i = self.temp_i
                # _LOGGER.debug(f"({self.get_attr(CONF_NAME)}) [get_option_state] street_num_i: {self.street_num_i}")
            self.temp_i += 1
            return out
        else:
            return None

    def compile_state_from_advanced_options(self):
        self.street_num_i += 1
        first = True
        for i, out in enumerate(self.adv_options_state_list):
            if out is not None and out:
                out = out.strip()
                if first:
                    self.set_attr(ATTR_NATIVE_VALUE, str(out))
                    first = False
                else:
                    if i == self.street_i and i == self.street_num_i:
                        self.set_attr(
                            ATTR_NATIVE_VALUE, f"{self.get_attr(ATTR_NATIVE_VALUE)} "
                        )
                    else:
                        self.set_attr(
                            ATTR_NATIVE_VALUE, f"{self.get_attr(ATTR_NATIVE_VALUE)}, "
                        )
                    self.set_attr(
                        ATTR_NATIVE_VALUE, f"{self.get_attr(ATTR_NATIVE_VALUE)}{out}"
                    )

        _LOGGER.debug(
            f"({self.get_attr(CONF_NAME)}) New State from Advanced Display Options: "
            + f"{self.get_attr(ATTR_NATIVE_VALUE)}"
        )

    def build_state_from_display_options(self):
        # Options:  "formatted_place, driving, zone, zone_name, place_name, place, street_number, street, city, county, state, postal_code, country, formatted_address, do_not_show_not_home"

        display_options = self.get_attr(ATTR_DISPLAY_OPTIONS_LIST)
        _LOGGER.debug(
            f"({self.get_attr(CONF_NAME)}) Building State from Display Options: "
            + f"{self.get_attr(ATTR_DISPLAY_OPTIONS)}"
        )

        user_display = []
        if "driving" in display_options and not self.is_attr_blank(ATTR_DRIVING):
            user_display.append(self.get_attr(ATTR_DRIVING))

        if (
            "zone_name" in display_options
            and not self.is_attr_blank(ATTR_DEVICETRACKER_ZONE_NAME)
            and (self.in_zone() or "do_not_show_not_home" not in display_options)
        ):
            user_display.append(self.get_attr(ATTR_DEVICETRACKER_ZONE_NAME))
        elif (
            "zone" in display_options
            and not self.is_attr_blank(ATTR_DEVICETRACKER_ZONE)
            and (self.in_zone() or "do_not_show_not_home" not in display_options)
        ):
            user_display.append(self.get_attr(ATTR_DEVICETRACKER_ZONE))

        if "place_name" in display_options and not self.is_attr_blank(ATTR_PLACE_NAME):
            user_display.append(self.get_attr(ATTR_PLACE_NAME))
        if "place" in display_options:
            if not self.is_attr_blank(ATTR_PLACE_NAME) and self.get_attr(
                ATTR_PLACE_NAME
            ) != self.get_attr(ATTR_STREET):
                user_display.append(self.get_attr(ATTR_PLACE_NAME))
            if (
                not self.is_attr_blank(ATTR_PLACE_CATEGORY)
                and self.get_attr(ATTR_PLACE_CATEGORY).lower() != "place"
            ):
                user_display.append(self.get_attr(ATTR_PLACE_CATEGORY))
            if (
                not self.is_attr_blank(ATTR_PLACE_TYPE)
                and self.get_attr(ATTR_PLACE_TYPE).lower() != "yes"
            ):
                user_display.append(self.get_attr(ATTR_PLACE_TYPE))
            if not self.is_attr_blank(ATTR_PLACE_NEIGHBOURHOOD):
                user_display.append(self.get_attr(ATTR_PLACE_NEIGHBOURHOOD))
            if not self.is_attr_blank(ATTR_STREET_NUMBER):
                user_display.append(self.get_attr(ATTR_STREET_NUMBER))
            if not self.is_attr_blank(ATTR_STREET):
                user_display.append(self.get_attr(ATTR_STREET))
        else:
            if "street_number" in display_options and not self.is_attr_blank(
                ATTR_STREET_NUMBER
            ):
                user_display.append(self.get_attr(ATTR_STREET_NUMBER))
            if "street" in display_options and not self.is_attr_blank(ATTR_STREET):
                user_display.append(self.get_attr(ATTR_STREET))
        if "city" in display_options and not self.is_attr_blank(ATTR_CITY):
            user_display.append(self.get_attr(ATTR_CITY))
        if "county" in display_options and not self.is_attr_blank(ATTR_COUNTY):
            user_display.append(self.get_attr(ATTR_COUNTY))
        if "state" in display_options and not self.is_attr_blank(ATTR_REGION):
            user_display.append(self.get_attr(ATTR_REGION))
        elif "region" in display_options and not self.is_attr_blank(ATTR_REGION):
            user_display.append(self.get_attr(ATTR_REGION))
        if "postal_code" in display_options and not self.is_attr_blank(
            ATTR_POSTAL_CODE
        ):
            user_display.append(self.get_attr(ATTR_POSTAL_CODE))
        if "country" in display_options and not self.is_attr_blank(ATTR_COUNTRY):
            user_display.append(self.get_attr(ATTR_COUNTRY))
        if "formatted_address" in display_options and not self.is_attr_blank(
            ATTR_FORMATTED_ADDRESS
        ):
            user_display.append(self.get_attr(ATTR_FORMATTED_ADDRESS))

        if "do_not_reorder" in display_options:
            user_display = []
            display_options.remove("do_not_reorder")
            for option in display_options:
                if option == "state":
                    target_option = "region"
                if option == "place_neighborhood":
                    target_option = "place_neighbourhood"
                if option in locals():
                    user_display.append(target_option)

        if user_display:
            self.set_attr(ATTR_NATIVE_VALUE, ", ".join(item for item in user_display))
        _LOGGER.debug(
            f"({self.get_attr(CONF_NAME)}) New State from Display Options: {self.get_attr(ATTR_NATIVE_VALUE)}"
        )

    def get_extended_attr(self):
        if not self.is_attr_blank(ATTR_OSM_ID) and not self.is_attr_blank(
            ATTR_OSM_TYPE
        ):
            if self.get_attr(ATTR_OSM_TYPE).lower() == "node":
                osm_type_abbr = "N"
            elif self.get_attr(ATTR_OSM_TYPE).lower() == "way":
                osm_type_abbr = "W"
            elif self.get_attr(ATTR_OSM_TYPE).lower() == "relation":
                osm_type_abbr = "R"

            osm_details_url = (
                "https://nominatim.openstreetmap.org/details.php?osmtype="
                + f"{osm_type_abbr}&osmid={self.get_attr(ATTR_OSM_ID)}"
                + "&linkedplaces=1&hierarchy=1&group_hierarchy=1&limit=1&format=json"
                + f"&email={self.get_attr(CONF_API_KEY) if self.is_attr_blank(CONF_API_KEY) else ''}"
                + f"&accept-language={self.get_attr(CONF_LANGUAGE) if not self.is_attr_blank(CONF_LANGUAGE) else ''}"
            )
            self.set_attr(
                ATTR_OSM_DETAILS_DICT,
                self.get_dict_from_url(osm_details_url, "OpenStreetMaps Details"),
            )

            if not self.is_attr_blank(ATTR_OSM_DETAILS_DICT):
                # _LOGGER.debug(f"({self.get_attr(CONF_NAME)}) OSM Details Dict: {osm_details_dict}")

                if (
                    not self.is_attr_blank(ATTR_OSM_DETAILS_DICT)
                    and "extratags" in self.get_attr(ATTR_OSM_DETAILS_DICT)
                    and "wikidata"
                    in self.get_attr(ATTR_OSM_DETAILS_DICT).get("extratags")
                ):
                    self.set_attr(
                        ATTR_WIKIDATA_ID,
                        self.get_attr(ATTR_OSM_DETAILS_DICT)
                        .get("extratags")
                        .get("wikidata"),
                    )

                self.set_attr(ATTR_WIKIDATA_DICT, {})
                if not self.is_attr_blank(ATTR_WIKIDATA_ID):
                    wikidata_url = f"https://www.wikidata.org/wiki/Special:EntityData/{self.get_attr(ATTR_WIKIDATA_ID)}.json"
                    self.set_attr(
                        ATTR_WIKIDATA_DICT,
                        self.get_dict_from_url(wikidata_url, "Wikidata"),
                    )

    def fire_event_data(self, prev_last_place_name):
        _LOGGER.debug(f"({self.get_attr(CONF_NAME)}) Building Event Data")
        event_data = {}
        if not self.is_attr_blank(CONF_NAME):
            event_data.update({"entity": self.get_attr(CONF_NAME)})
        if not self.is_attr_blank(ATTR_PREVIOUS_STATE):
            event_data.update({"from_state": self.get_attr(ATTR_PREVIOUS_STATE)})
        if not self.is_attr_blank(ATTR_NATIVE_VALUE):
            event_data.update({"to_state": self.get_attr(ATTR_NATIVE_VALUE)})

        for attr in EVENT_ATTRIBUTE_LIST:
            if not self.is_attr_blank(attr):
                event_data.update({attr: self.get_attr(attr)})

        if (
            not self.is_attr_blank(ATTR_LAST_PLACE_NAME)
            and self.get_attr(ATTR_LAST_PLACE_NAME) != prev_last_place_name
        ):
            event_data.update(
                {ATTR_LAST_PLACE_NAME: self.get_attr(ATTR_LAST_PLACE_NAME)}
            )

        if self.get_attr(CONF_EXTENDED_ATTR):
            for attr in EXTENDED_ATTRIBUTE_LIST:
                if not self.is_attr_blank(attr):
                    event_data.update({attr: self.get_attr(attr)})

        self._hass.bus.fire(EVENT_TYPE, event_data)
        _LOGGER.debug(
            f"({self.get_attr(CONF_NAME)}) Event Details [event_type: {DOMAIN}_state_update]: {event_data}"
        )
        _LOGGER.info(
            f"({self.get_attr(CONF_NAME)}) Event Fired [event_type: {DOMAIN}_state_update]"
        )

    def write_sensor_to_json(self):
        sensor_attributes = copy.deepcopy(self._internal_attr)
        for k, v in list(sensor_attributes.items()):
            if isinstance(v, (datetime)):
                # _LOGGER.debug(f"({self.get_attr(CONF_NAME)}) Removing Sensor Attribute: {k}")
                sensor_attributes.pop(k)
        # _LOGGER.debug(f"({self.get_attr(CONF_NAME)}) Sensor Attributes to Save: {sensor_attributes}")
        try:
            with open(
                os.path.join(PLACES_JSON_FOLDER, self.get_attr(ATTR_JSON_FILENAME)),
                "w",
            ) as jsonfile:
                json.dump(sensor_attributes, jsonfile)
        except OSError as e:
            _LOGGER.debug(
                f"({self.get_attr(CONF_NAME)}) OSError writing sensor to JSON "
                + f"({self.get_attr(ATTR_JSON_FILENAME)}): {e}"
            )
        except Exception as e:
            _LOGGER.debug(
                f"({self.get_attr(CONF_NAME)}) Unknown Exception writing sensor to JSON "
                + f"({self.get_attr(ATTR_JSON_FILENAME)}): {e}"
            )

    def get_initial_last_place_name(self):
        _LOGGER.debug(
            f"({self.get_attr(CONF_NAME)}) Previous State: {self.get_attr(ATTR_PREVIOUS_STATE)}"
        )
        _LOGGER.debug(
            f"({self.get_attr(CONF_NAME)}) Previous last_place_name: {self.get_attr(ATTR_LAST_PLACE_NAME)}"
        )

        if not self.in_zone():
            # Previously Not in a Zone
            if not self.is_attr_blank(ATTR_PLACE_NAME):
                # If place name is set
                self.set_attr(ATTR_LAST_PLACE_NAME, self.get_attr(ATTR_PLACE_NAME))
                _LOGGER.debug(
                    f"({self.get_attr(CONF_NAME)}) Previous place is Place Name, "
                    + f"last_place_name is set: {self.get_attr(ATTR_LAST_PLACE_NAME)}"
                )
            else:
                # If blank, keep previous last_place_name
                _LOGGER.debug(
                    f"({self.get_attr(CONF_NAME)}) Previous Place Name is None, keeping prior"
                )
        else:
            # Previously In a Zone
            self.set_attr(
                ATTR_LAST_PLACE_NAME, self.get_attr(ATTR_DEVICETRACKER_ZONE_NAME)
            )
            _LOGGER.debug(
                f"({self.get_attr(CONF_NAME)}) Previous Place is Zone: {self.get_attr(ATTR_LAST_PLACE_NAME)}"
            )
        _LOGGER.debug(
            f"({self.get_attr(CONF_NAME)}) last_place_name (Initial): {self.get_attr(ATTR_LAST_PLACE_NAME)}"
        )

    def update_coordinates_and_distance(self):
        last_distance_traveled_m = self.get_attr(ATTR_DISTANCE_FROM_HOME_M)
        proceed_with_update = 1
        # 0: False. 1: True. 2: False, but set direction of travel to stationary

        if not self.is_attr_blank(ATTR_LATITUDE) and not self.is_attr_blank(
            ATTR_LONGITUDE
        ):
            self.set_attr(
                ATTR_LOCATION_CURRENT,
                f"{self.get_attr(ATTR_LATITUDE)},{self.get_attr(ATTR_LONGITUDE)}",
            )
        if not self.is_attr_blank(ATTR_LATITUDE_OLD) and not self.is_attr_blank(
            ATTR_LONGITUDE_OLD
        ):
            self.set_attr(
                ATTR_LOCATION_PREVIOUS,
                f"{self.get_attr(ATTR_LATITUDE_OLD)},{self.get_attr(ATTR_LONGITUDE_OLD)}",
            )
        if not self.is_attr_blank(ATTR_HOME_LATITUDE) and not self.is_attr_blank(
            ATTR_HOME_LONGITUDE
        ):
            self.set_attr(
                ATTR_HOME_LOCATION,
                f"{self.get_attr(ATTR_HOME_LATITUDE)},{self.get_attr(ATTR_HOME_LONGITUDE)}",
            )

        if (
            not self.is_attr_blank(ATTR_LATITUDE)
            and not self.is_attr_blank(ATTR_LONGITUDE)
            and not self.is_attr_blank(ATTR_HOME_LATITUDE)
            and not self.is_attr_blank(ATTR_HOME_LONGITUDE)
        ):
            self.set_attr(
                ATTR_DISTANCE_FROM_HOME_M,
                distance(
                    float(self.get_attr(ATTR_LATITUDE)),
                    float(self.get_attr(ATTR_LONGITUDE)),
                    float(self.get_attr(ATTR_HOME_LATITUDE)),
                    float(self.get_attr(ATTR_HOME_LONGITUDE)),
                ),
            )
            if not self.is_attr_blank(ATTR_DISTANCE_FROM_HOME_M):
                self.set_attr(
                    ATTR_DISTANCE_FROM_HOME_KM,
                    round(self.get_attr(ATTR_DISTANCE_FROM_HOME_M) / 1000, 3),
                )
                self.set_attr(
                    ATTR_DISTANCE_FROM_HOME_MI,
                    round(self.get_attr(ATTR_DISTANCE_FROM_HOME_M) / 1609, 3),
                )

            if not self.is_attr_blank(ATTR_LATITUDE_OLD) and not self.is_attr_blank(
                ATTR_LONGITUDE_OLD
            ):
                self.set_attr(
                    ATTR_DISTANCE_TRAVELED_M,
                    distance(
                        float(self.get_attr(ATTR_LATITUDE)),
                        float(self.get_attr(ATTR_LONGITUDE)),
                        float(self.get_attr(ATTR_LATITUDE_OLD)),
                        float(self.get_attr(ATTR_LONGITUDE_OLD)),
                    ),
                )
                if not self.is_attr_blank(ATTR_DISTANCE_TRAVELED_M):
                    self.set_attr(
                        ATTR_DISTANCE_TRAVELED_MI,
                        round(self.get_attr(ATTR_DISTANCE_TRAVELED_M) / 1609, 3),
                    )

                # if self.get_attr(ATTR_DISTANCE_TRAVELED_M) <= 100:  # in meters
                #    self.set_attr(ATTR_DIRECTION_OF_TRAVEL, "stationary")
                # elif last_distance_traveled_m > self.get_attr(ATTR_DISTANCE_FROM_HOME_M):
                if last_distance_traveled_m > self.get_attr(ATTR_DISTANCE_FROM_HOME_M):
                    self.set_attr(ATTR_DIRECTION_OF_TRAVEL, "towards home")
                elif last_distance_traveled_m < self.get_attr(
                    ATTR_DISTANCE_FROM_HOME_M
                ):
                    self.set_attr(ATTR_DIRECTION_OF_TRAVEL, "away from home")
                else:
                    self.set_attr(ATTR_DIRECTION_OF_TRAVEL, "stationary")
            else:
                self.set_attr(ATTR_DIRECTION_OF_TRAVEL, "stationary")
                self.set_attr(ATTR_DISTANCE_TRAVELED_M, 0)
                self.set_attr(ATTR_DISTANCE_TRAVELED_MI, 0)

            _LOGGER.debug(
                f"({self.get_attr(CONF_NAME)}) Previous Location: {self.get_attr(ATTR_LOCATION_PREVIOUS)}"
            )
            _LOGGER.debug(
                f"({self.get_attr(CONF_NAME)}) Current Location: {self.get_attr(ATTR_LOCATION_CURRENT)}"
            )
            _LOGGER.debug(
                f"({self.get_attr(CONF_NAME)}) Home Location: {self.get_attr(ATTR_HOME_LOCATION)}"
            )
            _LOGGER.info(
                f"({self.get_attr(CONF_NAME)}) Distance from home "
                + f"[{(self.get_attr(CONF_HOME_ZONE)).split('.')[1]}]: "
                + f"{self.get_attr(ATTR_DISTANCE_FROM_HOME_KM)} km"
            )
            _LOGGER.info(
                f"({self.get_attr(CONF_NAME)}) Travel Direction: {self.get_attr(ATTR_DIRECTION_OF_TRAVEL)}"
            )
            _LOGGER.info(
                f"({self.get_attr(CONF_NAME)}) Meters traveled since last update: "
                + f"{round(self.get_attr(ATTR_DISTANCE_TRAVELED_M), 1)}"
            )
        else:
            proceed_with_update = 0
            # 0: False. 1: True. 2: False, but set direction of travel to stationary
            _LOGGER.info(
                f"({self.get_attr(CONF_NAME)}) Problem with updated lat/long, not performing update: "
                + f"old_latitude={self.get_attr(ATTR_LATITUDE_OLD)}"
                + f", old_longitude={self.get_attr(ATTR_LONGITUDE_OLD)}"
                + f", new_latitude={self.get_attr(ATTR_LATITUDE)}"
                + f", new_longitude={self.get_attr(ATTR_LONGITUDE)}"
                + f", home_latitude={self.get_attr(ATTR_HOME_LATITUDE)}"
                + f", home_longitude={self.get_attr(ATTR_HOME_LONGITUDE)}"
            )
        return proceed_with_update

    def finalize_last_place_name(self, prev_last_place_name=None):
        if self.get_attr(ATTR_INITIAL_UPDATE):
            self.set_attr(ATTR_LAST_PLACE_NAME, prev_last_place_name)
            _LOGGER.debug(
                f"({self.get_attr(CONF_NAME)}) Runnining initial update after load, using prior last_place_name"
            )
        elif self.get_attr(ATTR_LAST_PLACE_NAME) == self.get_attr(
            ATTR_PLACE_NAME
        ) or self.get_attr(ATTR_LAST_PLACE_NAME) == self.get_attr(
            ATTR_DEVICETRACKER_ZONE_NAME
        ):
            # If current place name/zone are the same as previous, keep older last_place_name
            self.set_attr(ATTR_LAST_PLACE_NAME, prev_last_place_name)
            _LOGGER.debug(
                f"({self.get_attr(CONF_NAME)}) Initial last_place_name is same as new: place_name="
                + f"{self.get_attr(ATTR_PLACE_NAME)} or devicetracker_zone_name="
                + f"{self.get_attr(ATTR_DEVICETRACKER_ZONE_NAME)}, keeping previous last_place_name"
            )
        else:
            _LOGGER.debug(
                f"({self.get_attr(CONF_NAME)}) Keeping initial last_place_name"
            )
        _LOGGER.info(
            f"({self.get_attr(CONF_NAME)}) last_place_name: {self.get_attr(ATTR_LAST_PLACE_NAME)}"
        )

    def do_update(self, reason):
        """Get the latest data and updates the states."""

        _LOGGER.info(
            f"({self.get_attr(CONF_NAME)}) Starting {reason} Update (Tracked Entity: "
            + f"{self.get_attr(CONF_DEVICETRACKER_ID)})"
        )

        if self._hass.config.time_zone is not None:
            now = datetime.now(tz=ZoneInfo(str(self._hass.config.time_zone)))
        else:
            now = datetime.now()
        previous_attr = copy.deepcopy(self._internal_attr)

        self.check_for_updated_entity_name()
        self.cleanup_attributes()
        # _LOGGER.debug(f"({self.get_attr(CONF_NAME)}) Previous entity attributes: {self._internal_attr}")
        if not self.is_attr_blank(ATTR_NATIVE_VALUE) and self.get_attr(CONF_SHOW_TIME):
            self.set_attr(
                ATTR_PREVIOUS_STATE, str(self.get_attr(ATTR_NATIVE_VALUE)[:-14])
            )
        else:
            self.set_attr(ATTR_PREVIOUS_STATE, self.get_attr(ATTR_NATIVE_VALUE))
        if self.is_float(self.get_attr(ATTR_LATITUDE)):
            self.set_attr(ATTR_LATITUDE_OLD, str(self.get_attr(ATTR_LATITUDE)))
        if self.is_float(self.get_attr(ATTR_LONGITUDE)):
            self.set_attr(ATTR_LONGITUDE_OLD, str(self.get_attr(ATTR_LONGITUDE)))
        prev_last_place_name = self.get_attr(ATTR_LAST_PLACE_NAME)

        proceed_with_update = self.is_devicetracker_set()
        # 0: False. 1: True. 2: False, but set direction of travel to stationary
        _LOGGER.debug(
            f"({self.get_attr(CONF_NAME)}) [is_devicetracker_set] proceed_with_update: {proceed_with_update}"
        )
        if proceed_with_update == 1:
            # 0: False. 1: True. 2: False, but set direction of travel to stationary
            if self.is_float(
                self._hass.states.get(
                    self.get_attr(CONF_DEVICETRACKER_ID)
                ).attributes.get(CONF_LATITUDE)
            ):
                self.set_attr(
                    ATTR_LATITUDE,
                    str(
                        self._hass.states.get(
                            self.get_attr(CONF_DEVICETRACKER_ID)
                        ).attributes.get(CONF_LATITUDE)
                    ),
                )
            if self.is_float(
                self._hass.states.get(
                    self.get_attr(CONF_DEVICETRACKER_ID)
                ).attributes.get(CONF_LONGITUDE)
            ):
                self.set_attr(
                    ATTR_LONGITUDE,
                    str(
                        self._hass.states.get(
                            self.get_attr(CONF_DEVICETRACKER_ID)
                        ).attributes.get(CONF_LONGITUDE)
                    ),
                )
            proceed_with_update = self.get_gps_accuracy()
            _LOGGER.debug(
                f"({self.get_attr(CONF_NAME)}) [is_devicetracker_set] proceed_with_update: {proceed_with_update}"
            )

        if proceed_with_update == 1:
            # 0: False. 1: True. 2: False, but set direction of travel to stationary
            self.get_initial_last_place_name()
            self.get_zone_details()
            proceed_with_update = self.update_coordinates_and_distance()
            _LOGGER.debug(
                f"({self.get_attr(CONF_NAME)}) [update_coordinates_and_distance] proceed_with_update: {proceed_with_update}"
            )

        if proceed_with_update == 1:
            # 0: False. 1: True. 2: False, but set direction of travel to stationary
            proceed_with_update = self.determine_if_update_needed()
            _LOGGER.debug(
                f"({self.get_attr(CONF_NAME)}) [determine_if_update_needed] proceed_with_update: {proceed_with_update}"
            )

        if proceed_with_update == 1:
            # 0: False. 1: True. 2: False, but set direction of travel to stationary
            _LOGGER.info(
                f"({self.get_attr(CONF_NAME)}) Meets criteria, proceeding with OpenStreetMap query"
            )

            _LOGGER.info(
                f"({self.get_attr(CONF_NAME)}) Tracked Entity Zone: {self.get_attr(ATTR_DEVICETRACKER_ZONE)}"
                # + f" / Skipped Updates: {self.get_attr(ATTR_UPDATES_SKIPPED)}"
            )

            self._reset_attributes()
            self.get_map_link()

            osm_url = (
                "https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat="
                + f"{self.get_attr(ATTR_LATITUDE)}&lon={self.get_attr(ATTR_LONGITUDE)}"
                + f"&accept-language={self.get_attr(CONF_LANGUAGE) if not self.is_attr_blank(CONF_LANGUAGE) else ''}"
                + "&addressdetails=1&namedetails=1&zoom=18&limit=1"
                + f"&email={self.get_attr(CONF_API_KEY) if not self.is_attr_blank(CONF_API_KEY) else ''}"
            )

            self.set_attr(
                ATTR_OSM_DICT, self.get_dict_from_url(osm_url, "OpenStreetMaps")
            )
            if not self.is_attr_blank(ATTR_OSM_DICT):

                self.parse_osm_dict()
                self.finalize_last_place_name(prev_last_place_name)

                display_options = []
                if not self.is_attr_blank(ATTR_DISPLAY_OPTIONS):
                    options_array = self.get_attr(ATTR_DISPLAY_OPTIONS).split(",")
                    for option in options_array:
                        display_options.append(option.strip())
                self.set_attr(ATTR_DISPLAY_OPTIONS_LIST, display_options)

                self.get_driving_status()

                if "formatted_place" in display_options:
                    self.build_formatted_place()
                    self.set_attr(
                        ATTR_NATIVE_VALUE, self.get_attr(ATTR_FORMATTED_PLACE)
                    )
                    _LOGGER.debug(
                        f"({self.get_attr(CONF_NAME)}) New State using formatted_place: "
                        + f"{self.get_attr(ATTR_NATIVE_VALUE)}"
                    )

                elif any(
                    ext in self.get_attr(ATTR_DISPLAY_OPTIONS)
                    for ext in ["(", ")", "[", "]"]
                ):
                    # Replace place option with expanded definition
                    # temp_opt = self.get_attr(ATTR_DISPLAY_OPTIONS)
                    # re.sub(
                    #    r"place(?=[\[\(\]\)\,\s])",
                    #    "place_name,place_category(-,place),place_type(-,yes),neighborhood,street_number,street",
                    #    temp_opt,
                    # )
                    # self.set_attr(ATTR_DISPLAY_OPTIONS, temp_opt)
                    self.clear_attr(ATTR_DISPLAY_OPTIONS_LIST)
                    display_options = None
                    self.adv_options_state_list = []
                    self.street_num_i = -1
                    self.street_i = -1
                    self.temp_i = 0
                    _LOGGER.debug(
                        f"({self.get_attr(CONF_NAME)}) Initial Advanced Display Options: "
                        + f"{self.get_attr(ATTR_DISPLAY_OPTIONS)}"
                    )

                    self.build_from_advanced_options(
                        self.get_attr(ATTR_DISPLAY_OPTIONS)
                    )
                    # _LOGGER.debug(
                    #    f"({self.get_attr(CONF_NAME)}) Back from initial advanced build: "
                    #    + f"{self.adv_options_state_list}"
                    # )
                    self.compile_state_from_advanced_options()
                elif not self.in_zone():
                    self.build_state_from_display_options()
                elif (
                    "zone" in display_options
                    and not self.is_attr_blank(ATTR_DEVICETRACKER_ZONE)
                ) or self.is_attr_blank(ATTR_DEVICETRACKER_ZONE_NAME):
                    self.set_attr(
                        ATTR_NATIVE_VALUE, self.get_attr(ATTR_DEVICETRACKER_ZONE)
                    )
                    _LOGGER.debug(
                        f"({self.get_attr(CONF_NAME)}) New State from Tracked Entity Zone: "
                        + f"{self.get_attr(ATTR_NATIVE_VALUE)}"
                    )
                elif not self.is_attr_blank(ATTR_DEVICETRACKER_ZONE_NAME):
                    self.set_attr(
                        ATTR_NATIVE_VALUE, self.get_attr(ATTR_DEVICETRACKER_ZONE_NAME)
                    )
                    _LOGGER.debug(
                        f"({self.get_attr(CONF_NAME)}) New State from Tracked Entity Zone Name: "
                        + f"{self.get_attr(ATTR_NATIVE_VALUE)}"
                    )
                current_time = f"{now.hour:02}:{now.minute:02}"
                self.set_attr(
                    ATTR_LAST_CHANGED, str(now.isoformat(sep=" ", timespec="seconds"))
                )

                # Final check to see if the New State is different from the Previous State and should update or not.
                # If not, attributes are reset to what they were before the update started.

                if (
                    (
                        not self.is_attr_blank(ATTR_PREVIOUS_STATE)
                        and not self.is_attr_blank(ATTR_NATIVE_VALUE)
                        and self.get_attr(ATTR_PREVIOUS_STATE).lower().strip()
                        != self.get_attr(ATTR_NATIVE_VALUE).lower().strip()
                        and self.get_attr(ATTR_PREVIOUS_STATE)
                        .replace(" ", "")
                        .lower()
                        .strip()
                        != self.get_attr(ATTR_NATIVE_VALUE).lower().strip()
                        and self.get_attr(ATTR_PREVIOUS_STATE).lower().strip()
                        != self.get_attr(ATTR_DEVICETRACKER_ZONE).lower().strip()
                    )
                    or self.is_attr_blank(ATTR_PREVIOUS_STATE)
                    or self.is_attr_blank(ATTR_NATIVE_VALUE)
                    or self.get_attr(ATTR_INITIAL_UPDATE)
                ):

                    if self.get_attr(CONF_EXTENDED_ATTR):
                        self.get_extended_attr()
                    self.set_attr(ATTR_SHOW_DATE, False)
                    self.cleanup_attributes()
                    if not self.is_attr_blank(ATTR_NATIVE_VALUE):
                        if self.get_attr(CONF_SHOW_TIME):
                            self.set_attr(
                                ATTR_NATIVE_VALUE,
                                self.get_attr(ATTR_NATIVE_VALUE)[: 255 - 14]
                                + " (since "
                                + current_time
                                + ")",
                            )
                        else:
                            self.set_attr(
                                ATTR_NATIVE_VALUE,
                                self.get_attr(ATTR_NATIVE_VALUE)[:255],
                            )
                        _LOGGER.info(
                            f"({self.get_attr(CONF_NAME)}) New State: {self.get_attr(ATTR_NATIVE_VALUE)}"
                        )
                    else:
                        self.clear_attr(ATTR_NATIVE_VALUE)
                        _LOGGER.warning(
                            f"({self.get_attr(CONF_NAME)}) New State is None"
                        )
                    if not self.is_attr_blank(ATTR_NATIVE_VALUE):
                        self._attr_native_value = self.get_attr(ATTR_NATIVE_VALUE)
                    else:
                        self._attr_native_value = None
                    self.fire_event_data(prev_last_place_name)
                    self.set_attr(ATTR_INITIAL_UPDATE, False)
                    self.write_sensor_to_json()
                else:
                    self._internal_attr = previous_attr
                    _LOGGER.info(
                        f"({self.get_attr(CONF_NAME)}) No entity update needed, Previous State = New State"
                    )
                    _LOGGER.debug(
                        f"({self.get_attr(CONF_NAME)}) Reverting attributes back to before the update started"
                    )

                    changed_diff_sec = self.get_seconds_from_last_change(now)
                    if (
                        self.get_attr(ATTR_DIRECTION_OF_TRAVEL) != "stationary"
                        and changed_diff_sec >= 60
                    ):
                        self.change_dot_to_stationary(now, changed_diff_sec)
                    if (
                        self.get_attr(CONF_SHOW_TIME)
                        and changed_diff_sec >= 86399
                        and self.get_attr(ATTR_SHOW_DATE) is False
                    ):
                        self.change_show_time_to_date()
        else:
            self._internal_attr = previous_attr
            _LOGGER.debug(
                f"({self.get_attr(CONF_NAME)}) Reverting attributes back to before the update started"
            )

            changed_diff_sec = self.get_seconds_from_last_change(now)
            if (
                proceed_with_update == 2
                and self.get_attr(ATTR_DIRECTION_OF_TRAVEL) != "stationary"
                and changed_diff_sec >= 60
            ):
                # 0: False. 1: True. 2: False, but set direction of travel to stationary
                self.change_dot_to_stationary(now, changed_diff_sec)
            if (
                self.get_attr(CONF_SHOW_TIME)
                and changed_diff_sec >= 86399
                and self.get_attr(ATTR_SHOW_DATE) is False
            ):
                self.change_show_time_to_date()

        self.set_attr(
            ATTR_LAST_UPDATED, str(now.isoformat(sep=" ", timespec="seconds"))
        )
        # _LOGGER.debug(f"({self.get_attr(CONF_NAME)}) Final entity attributes: {self._internal_attr}")
        _LOGGER.info(f"({self.get_attr(CONF_NAME)}) End of Update")

    def change_dot_to_stationary(self, now, changed_diff_sec):
        self.set_attr(ATTR_DIRECTION_OF_TRAVEL, "stationary")
        self.set_attr(
            ATTR_LAST_CHANGED, str(now.isoformat(sep=" ", timespec="seconds"))
        )
        self.write_sensor_to_json()
        _LOGGER.debug(
            f"({self.get_attr(CONF_NAME)}) Updating direction of travel to stationary (Last changed "
            + f"{int(changed_diff_sec)} seconds ago)"
        )

    def change_show_time_to_date(self):
        if not self.is_attr_blank(ATTR_NATIVE_VALUE) and self.get_attr(CONF_SHOW_TIME):
            # localedate = str(locale.nl_langinfo(locale.D_FMT)).replace(" ", "")
            # if localedate.lower().endswith("%y"):
            #    localemmdd = localedate[:-3]
            # elif localedate.lower().startswith("%y"):
            #    localemmdd = localedate[3:]
            # else:
            if self.get_attr(CONF_DATE_FORMAT) == "dd/mm":
                dateformat = "%d/%m"
            else:
                dateformat = "%m/%d"
            mmddstring = (
                datetime.fromisoformat(self.get_attr(ATTR_LAST_CHANGED))
                .strftime(f"{dateformat}")
                .replace(" ", "")[:5]
            )
            self.set_attr(
                ATTR_NATIVE_VALUE,
                f"{self.get_attr(ATTR_NATIVE_VALUE)[: -14]}" + f" (since {mmddstring})",
            )

            if not self.is_attr_blank(ATTR_NATIVE_VALUE):
                self._attr_native_value = self.get_attr(ATTR_NATIVE_VALUE)
            else:
                self._attr_native_value = None
            self.set_attr(ATTR_SHOW_DATE, True)
            self.write_sensor_to_json()
            _LOGGER.debug(
                f"({self.get_attr(CONF_NAME)}) Updating state to show date instead of time since last change"
            )
            _LOGGER.debug(
                f"({self.get_attr(CONF_NAME)}) New State: {self.get_attr(ATTR_NATIVE_VALUE)}"
            )

    def get_seconds_from_last_change(self, now):
        if self.is_attr_blank(ATTR_LAST_CHANGED):
            return 3600
        try:
            last_changed = datetime.fromisoformat(self.get_attr(ATTR_LAST_CHANGED))
        except (TypeError, ValueError) as e:
            _LOGGER.warning(
                f"Error converting Last Changed date/time ({self.get_attr(ATTR_LAST_CHANGED)}) "
                + f"into datetime: {repr(e)}"
            )
            return 3600
        else:
            try:
                changed_diff_sec = (now - last_changed).total_seconds()
            except TypeError:
                try:
                    changed_diff_sec = (datetime.now() - last_changed).total_seconds()
                except (TypeError, OverflowError) as e:
                    _LOGGER.warning(
                        f"Error calculating the seconds between last change to now: {repr(e)}"
                    )
                    return 3600
            except OverflowError as e:
                _LOGGER.warning(
                    f"Error calculating the seconds between last change to now: {repr(e)}"
                )
                return 3600
            return changed_diff_sec

    def _reset_attributes(self):
        """Resets attributes."""
        for attr in RESET_ATTRIBUTE_LIST:
            self.clear_attr(attr)
        # self.set_attr(ATTR_UPDATES_SKIPPED, 0)
        self.cleanup_attributes()

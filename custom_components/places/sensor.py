"""Place Support for OpenStreetMap Geocode sensors.

Previous Authors:  Jim Thompson, Ian Richardson
Current Author:  Snuffy2

Description:
  Provides a sensor with a variable state consisting of reverse geocode (place) details for a linked device_tracker entity that provides GPS co-ordinates (ie owntracks, icloud)
  Allows you to specify a 'home_zone' for each device and calculates distance from home and direction of travel.
  Configuration Instructions are on GitHub.

GitHub: https://github.com/custom-components/places
"""

from collections.abc import MutableMapping
import contextlib
import copy
from datetime import datetime, timedelta
import json
import locale
import logging
from pathlib import Path
import re
from typing import Any
from zoneinfo import ZoneInfo

import requests
from urllib3.exceptions import NewConnectionError

from homeassistant.components.recorder import DATA_INSTANCE as RECORDER_INSTANCE
from homeassistant.components.sensor import SensorEntity
from homeassistant.components.zone import ATTR_PASSIVE
from homeassistant.config_entries import ConfigEntry
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
    MATCH_ALL,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.entity import generate_entity_id
from homeassistant.helpers.entity_platform import AddEntitiesCallback
import homeassistant.helpers.entity_registry as er
from homeassistant.helpers.event import EventStateChangedData, async_track_state_change_event
from homeassistant.util import Throttle, slugify
from homeassistant.util.location import distance

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

_LOGGER: logging.Logger = logging.getLogger(__name__)
THROTTLE_INTERVAL = timedelta(seconds=600)
MIN_THROTTLE_INTERVAL = timedelta(seconds=10)
SCAN_INTERVAL = timedelta(seconds=30)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create places sensor entities."""
    # _LOGGER.debug("[aync_setup_entity] all entities: %s", hass.data.get(DOMAIN))

    config: MutableMapping[str, Any] = dict(config_entry.data)
    unique_id: str = config_entry.entry_id
    name: str = config[CONF_NAME]
    json_folder: str = hass.config.path("custom_components", DOMAIN, "json_sensors")
    await hass.async_add_executor_job(_create_json_folder, json_folder)
    filename: str = f"{DOMAIN}-{slugify(unique_id)}.json"
    imported_attributes: MutableMapping[str, Any] = await hass.async_add_executor_job(
        _get_dict_from_json_file, name, filename, json_folder
    )
    # _LOGGER.debug("[async_setup_entry] name: %s", name)
    # _LOGGER.debug("[async_setup_entry] unique_id: %s", unique_id)
    # _LOGGER.debug("[async_setup_entry] config: %s", config)

    if config.get(CONF_EXTENDED_ATTR, DEFAULT_EXTENDED_ATTR):
        _LOGGER.debug("(%s) Extended Attr is True. Excluding from Recorder", name)
        async_add_entities(
            [
                PlacesNoRecorder(
                    hass=hass,
                    config=config,
                    config_entry=config_entry,
                    name=name,
                    unique_id=unique_id,
                    imported_attributes=imported_attributes,
                )
            ],
            update_before_add=True,
        )
    else:
        async_add_entities(
            [
                Places(
                    hass=hass,
                    config=config,
                    config_entry=config_entry,
                    name=name,
                    unique_id=unique_id,
                    imported_attributes=imported_attributes,
                )
            ],
            update_before_add=True,
        )


def _create_json_folder(json_folder: str) -> None:
    try:
        Path(json_folder).mkdir(parents=True, exist_ok=True)
    except OSError as e:
        _LOGGER.warning(
            "OSError creating folder for JSON sensor files: %s: %s", e.__class__.__qualname__, e
        )


def _get_dict_from_json_file(
    name: str, filename: str, json_folder: str
) -> MutableMapping[str, Any]:
    sensor_attributes: MutableMapping[str, Any] = {}
    try:
        json_file_path: Path = Path(json_folder) / filename
        with json_file_path.open() as jsonfile:
            sensor_attributes = json.load(jsonfile)
    except OSError as e:
        _LOGGER.debug(
            "(%s) [Init] No JSON file to import (%s): %s: %s",
            name,
            filename,
            e.__class__.__qualname__,
            e,
        )
        return {}
    return sensor_attributes


def _remove_json_file(name: str, filename: str, json_folder: str) -> None:
    try:
        json_file_path: Path = Path(json_folder) / filename
        json_file_path.unlink()
    except OSError as e:
        _LOGGER.debug(
            "(%s) OSError removing JSON sensor file (%s): %s: %s",
            name,
            filename,
            e.__class__.__qualname__,
            e,
        )
    else:
        _LOGGER.debug("(%s) JSON sensor file removed: %s", name, filename)


def _is_float(value: Any) -> bool:
    if value is not None:
        try:
            float(value)
        except ValueError:
            return False
        else:
            return True
    return False


class Places(SensorEntity):
    """Representation of a Places Sensor."""

    def __init__(
        self,
        hass: HomeAssistant,
        config: MutableMapping[str, Any],
        config_entry: ConfigEntry,
        name: str,
        unique_id: str,
        imported_attributes: MutableMapping[str, Any],
    ) -> None:
        """Initialize the sensor."""
        self._attr_should_poll = True
        _LOGGER.info("(%s) [Init] Places sensor: %s", name, name)
        _LOGGER.debug("(%s) [Init] System Locale: %s", name, locale.getlocale())
        _LOGGER.debug(
            "(%s) [Init] System Locale Date Format: %s", name, locale.nl_langinfo(locale.D_FMT)
        )
        _LOGGER.debug("(%s) [Init] HASS TimeZone: %s", name, hass.config.time_zone)

        self._warn_if_device_tracker_prob = False
        self._internal_attr: MutableMapping[str, Any] = {}
        self._set_attr(ATTR_INITIAL_UPDATE, True)
        self._config: MutableMapping[str, Any] = config
        self._config_entry: ConfigEntry = config_entry
        self._hass: HomeAssistant = hass
        self._set_attr(CONF_NAME, name)
        self._attr_name: str = name
        self._set_attr(CONF_UNIQUE_ID, unique_id)
        self._attr_unique_id: str = unique_id
        registry: er.RegistryEntry | None = er.async_get(self._hass)
        self._json_folder: str = hass.config.path("custom_components", DOMAIN, "json_sensors")
        _LOGGER.debug("json_sensors Location: %s", self._json_folder)
        current_entity_id: str | None = None
        if registry:
            current_entity_id = registry.async_get_entity_id(PLATFORM, DOMAIN, self._attr_unique_id)
        if current_entity_id:
            self._entity_id: str = current_entity_id
        else:
            self._entity_id = generate_entity_id(
                ENTITY_ID_FORMAT, slugify(name.lower()), hass=self._hass
            )
        _LOGGER.debug("(%s) [Init] entity_id: %s", self._attr_name, self._entity_id)
        self._street_num_i: int = -1
        self._street_i: int = -1
        self._temp_i: int = 0
        self._adv_options_state_list: list = []
        self._set_attr(CONF_ICON, DEFAULT_ICON)
        self._attr_icon = DEFAULT_ICON
        self._set_attr(CONF_API_KEY, config.get(CONF_API_KEY))
        self._set_attr(
            CONF_DISPLAY_OPTIONS,
            config.setdefault(CONF_DISPLAY_OPTIONS, DEFAULT_DISPLAY_OPTIONS).lower(),
        )
        self._set_attr(CONF_DEVICETRACKER_ID, config[CONF_DEVICETRACKER_ID].lower())
        # Consider reconciling this in the future
        self._set_attr(ATTR_DEVICETRACKER_ID, config[CONF_DEVICETRACKER_ID].lower())
        self._set_attr(CONF_HOME_ZONE, config.setdefault(CONF_HOME_ZONE, DEFAULT_HOME_ZONE).lower())
        self._set_attr(
            CONF_MAP_PROVIDER,
            config.setdefault(CONF_MAP_PROVIDER, DEFAULT_MAP_PROVIDER).lower(),
        )
        self._set_attr(CONF_MAP_ZOOM, int(config.setdefault(CONF_MAP_ZOOM, DEFAULT_MAP_ZOOM)))
        self._set_attr(CONF_LANGUAGE, config.get(CONF_LANGUAGE))

        if not self._is_attr_blank(CONF_LANGUAGE):
            self._set_attr(
                CONF_LANGUAGE,
                self._get_attr_safe_str(CONF_LANGUAGE).replace(" ", "").strip(),
            )
        self._set_attr(
            CONF_EXTENDED_ATTR,
            config.setdefault(CONF_EXTENDED_ATTR, DEFAULT_EXTENDED_ATTR),
        )
        self._set_attr(CONF_SHOW_TIME, config.setdefault(CONF_SHOW_TIME, DEFAULT_SHOW_TIME))
        self._set_attr(
            CONF_DATE_FORMAT,
            config.setdefault(CONF_DATE_FORMAT, DEFAULT_DATE_FORMAT).lower(),
        )
        self._set_attr(CONF_USE_GPS, config.setdefault(CONF_USE_GPS, DEFAULT_USE_GPS))
        self._set_attr(
            ATTR_JSON_FILENAME,
            f"{DOMAIN}-{slugify(str(self._get_attr(CONF_UNIQUE_ID)))}.json",
        )
        self._set_attr(ATTR_DISPLAY_OPTIONS, self._get_attr(CONF_DISPLAY_OPTIONS))
        _LOGGER.debug(
            "(%s) [Init] JSON Filename: %s",
            self._get_attr(CONF_NAME),
            self._get_attr(ATTR_JSON_FILENAME),
        )

        self._attr_native_value = None  # Represents the state in SensorEntity
        self._clear_attr(ATTR_NATIVE_VALUE)

        if (
            not self._is_attr_blank(CONF_HOME_ZONE)
            and CONF_LATITUDE in hass.states.get(self._get_attr(CONF_HOME_ZONE)).attributes
            and hass.states.get(self._get_attr(CONF_HOME_ZONE)).attributes.get(CONF_LATITUDE)
            is not None
            and _is_float(
                hass.states.get(self._get_attr(CONF_HOME_ZONE)).attributes.get(CONF_LATITUDE)
            )
        ):
            self._set_attr(
                ATTR_HOME_LATITUDE,
                str(hass.states.get(self._get_attr(CONF_HOME_ZONE)).attributes.get(CONF_LATITUDE)),
            )
        if (
            not self._is_attr_blank(CONF_HOME_ZONE)
            and CONF_LONGITUDE in hass.states.get(self._get_attr(CONF_HOME_ZONE)).attributes
            and hass.states.get(self._get_attr(CONF_HOME_ZONE)).attributes.get(CONF_LONGITUDE)
            is not None
            and _is_float(
                hass.states.get(self._get_attr(CONF_HOME_ZONE)).attributes.get(CONF_LONGITUDE)
            )
        ):
            self._set_attr(
                ATTR_HOME_LONGITUDE,
                str(hass.states.get(self._get_attr(CONF_HOME_ZONE)).attributes.get(CONF_LONGITUDE)),
            )

        self._attr_entity_picture = (
            hass.states.get(self._get_attr(CONF_DEVICETRACKER_ID)).attributes.get(ATTR_PICTURE)
            if hass.states.get(self._get_attr(CONF_DEVICETRACKER_ID))
            else None
        )
        self._set_attr(ATTR_SHOW_DATE, False)

        self._import_attributes_from_json(imported_attributes)
        ##
        # For debugging:
        # imported_attributes = {}
        # imported_attributes.update({CONF_NAME: self._get_attr(CONF_NAME)})
        # imported_attributes.update({ATTR_NATIVE_VALUE: self._get_attr(ATTR_NATIVE_VALUE)})
        # imported_attributes.update(self.extra_state_attributes)
        # _LOGGER.debug("(%s) [Init] Sensor Attributes Imported: %s", self._get_attr(CONF_NAME), imported_attributes)
        ##
        if not self._get_attr(ATTR_INITIAL_UPDATE):
            _LOGGER.debug(
                "(%s) [Init] Sensor Attributes Imported from JSON file", self._get_attr(CONF_NAME)
            )
        self._cleanup_attributes()
        if self._get_attr(CONF_EXTENDED_ATTR):
            self._exclude_event_types()
        _LOGGER.info(
            "(%s) [Init] Tracked Entity ID: %s",
            self._get_attr(CONF_NAME),
            self._get_attr(CONF_DEVICETRACKER_ID),
        )

    def _exclude_event_types(self) -> None:
        if RECORDER_INSTANCE in self._hass.data:
            ha_history_recorder = self._hass.data[RECORDER_INSTANCE]
            ha_history_recorder.exclude_event_types.add(EVENT_TYPE)
            _LOGGER.debug(
                "(%s) exclude_event_types: %s",
                self._get_attr(CONF_NAME),
                ha_history_recorder.exclude_event_types,
            )

    async def async_added_to_hass(self) -> None:
        """Run after sensor is added to HA."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_track_state_change_event(
                self._hass,
                [self._get_attr(CONF_DEVICETRACKER_ID)],
                self._async_tsc_update,
            )
        )
        _LOGGER.debug(
            "(%s) [Init] Subscribed to Tracked Entity state change events",
            self._get_attr(CONF_NAME),
        )

    async def async_will_remove_from_hass(self) -> None:
        """Run when entity will be removed from hass."""

        await self._hass.async_add_executor_job(
            _remove_json_file,
            self._get_attr(CONF_NAME),
            self._get_attr(ATTR_JSON_FILENAME),
            self._json_folder,
        )

        if RECORDER_INSTANCE in self._hass.data and self._get_attr(CONF_EXTENDED_ATTR):
            _LOGGER.debug(
                "(%s) Removing entity exclusion from recorder: %s", self._attr_name, self._entity_id
            )
            # Only do this if no places entities with extended_attr exist
            ex_attr_count = 0
            for ent in self._hass.data[DOMAIN].values():
                if ent.get(CONF_EXTENDED_ATTR):
                    ex_attr_count += 1

            if (self._get_attr(CONF_EXTENDED_ATTR) and ex_attr_count == 1) or ex_attr_count == 0:
                _LOGGER.debug(
                    "(%s) Removing event exclusion from recorder: %s",
                    self._get_attr(CONF_NAME),
                    EVENT_TYPE,
                )
                ha_history_recorder = self._hass.data[RECORDER_INSTANCE]
                ha_history_recorder.exclude_event_types.discard(EVENT_TYPE)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        return_attr: dict[str, Any] = {}
        self._cleanup_attributes()
        for attr in EXTRA_STATE_ATTRIBUTE_LIST:
            if self._get_attr(attr):
                return_attr.update({attr: self._get_attr(attr)})

        if self._get_attr(CONF_EXTENDED_ATTR):
            for attr in EXTENDED_ATTRIBUTE_LIST:
                if self._get_attr(attr):
                    return_attr.update({attr: self._get_attr(attr)})
        # _LOGGER.debug("(%s) Extra State Attributes: %s", self._get_attr(CONF_NAME), return_attr)
        return return_attr

    def _import_attributes_from_json(self, json_attr: MutableMapping[str, Any]) -> None:
        """Import the JSON state attributes. Takes a Dictionary as input."""

        self._set_attr(ATTR_INITIAL_UPDATE, False)
        for attr in JSON_ATTRIBUTE_LIST:
            if attr in json_attr:
                self._set_attr(attr, json_attr.pop(attr, None))
        if not self._is_attr_blank(ATTR_NATIVE_VALUE):
            self._attr_native_value = self._get_attr(ATTR_NATIVE_VALUE)

        # Remove attributes that are part of the Config and are explicitly not imported from JSON
        for attr in CONFIG_ATTRIBUTES_LIST + JSON_IGNORE_ATTRIBUTE_LIST:
            if attr in json_attr:
                json_attr.pop(attr, None)
        if json_attr is not None and json_attr:
            _LOGGER.debug(
                "(%s) [import_attributes] Attributes not imported: %s",
                self._get_attr(CONF_NAME),
                json_attr,
            )

    def _cleanup_attributes(self) -> None:
        for attr in list(self._internal_attr):
            if self._is_attr_blank(attr):
                self._clear_attr(attr)

    def _is_attr_blank(self, attr: str) -> bool:
        if self._internal_attr.get(attr) or self._internal_attr.get(attr) == 0:
            return False
        return True

    def _get_attr(self, attr: str | None, default: Any | None = None) -> None | Any:
        if attr is None or (default is None and self._is_attr_blank(attr)):
            return None
        return self._internal_attr.get(attr, default)

    def _get_attr_safe_str(self, attr: str | None, default: Any | None = None) -> str:
        value: None | Any = self._get_attr(attr=attr, default=default)
        if value is not None:
            try:
                return str(value)
            except ValueError:
                return ""
        return ""

    def _get_attr_safe_float(self, attr: str | None, default: Any | None = None) -> float:
        value: None | Any = self._get_attr(attr=attr, default=default)
        if not isinstance(value, float):
            return 0
        return value

    def _get_attr_safe_list(self, attr: str | None, default: Any | None = None) -> list:
        value: None | Any = self._get_attr(attr=attr, default=default)
        if not isinstance(value, list):
            return []
        return value

    def _get_attr_safe_dict(self, attr: str | None, default: Any | None = None) -> MutableMapping:
        value: None | Any = self._get_attr(attr=attr, default=default)
        if not isinstance(value, MutableMapping):
            return {}
        return value

    def _set_attr(self, attr: str, value: Any | None = None) -> None:
        if attr:
            self._internal_attr.update({attr: value})

    def _clear_attr(self, attr: str) -> None:
        self._internal_attr.pop(attr, None)

    async def _async_is_devicetracker_set(self) -> int:
        proceed_with_update = 0
        # 0: False. 1: True. 2: False, but set direction of travel to stationary

        if (
            self._is_attr_blank(CONF_DEVICETRACKER_ID)
            or self._hass.states.get(self._get_attr(CONF_DEVICETRACKER_ID)) is None
            or (
                isinstance(
                    self._hass.states.get(self._get_attr(CONF_DEVICETRACKER_ID)),
                    str,
                )
                and self._hass.states.get(self._get_attr(CONF_DEVICETRACKER_ID)).lower()
                in {"none", STATE_UNKNOWN, STATE_UNAVAILABLE}
            )
        ):
            if self._warn_if_device_tracker_prob or self._get_attr(ATTR_INITIAL_UPDATE):
                _LOGGER.warning(
                    "(%s) Tracked Entity (%s) "
                    "is not set or is not available. Not Proceeding with Update",
                    self._get_attr(CONF_NAME),
                    self._get_attr(CONF_DEVICETRACKER_ID),
                )
                self._warn_if_device_tracker_prob = False
            else:
                _LOGGER.info(
                    "(%s) Tracked Entity (%s) "
                    "is not set or is not available. Not Proceeding with Update",
                    self._get_attr(CONF_NAME),
                    self._get_attr(CONF_DEVICETRACKER_ID),
                )
            return 0
            # 0: False. 1: True. 2: False, but set direction of travel to stationary
        if (
            hasattr(
                self._hass.states.get(self._get_attr(CONF_DEVICETRACKER_ID)),
                ATTR_ATTRIBUTES,
            )
            and CONF_LATITUDE
            in self._hass.states.get(self._get_attr(CONF_DEVICETRACKER_ID)).attributes
            and CONF_LONGITUDE
            in self._hass.states.get(self._get_attr(CONF_DEVICETRACKER_ID)).attributes
            and self._hass.states.get(self._get_attr(CONF_DEVICETRACKER_ID)).attributes.get(
                CONF_LATITUDE
            )
            is not None
            and self._hass.states.get(self._get_attr(CONF_DEVICETRACKER_ID)).attributes.get(
                CONF_LONGITUDE
            )
            is not None
            and _is_float(
                self._hass.states.get(self._get_attr(CONF_DEVICETRACKER_ID)).attributes.get(
                    CONF_LATITUDE
                )
            )
            and _is_float(
                self._hass.states.get(self._get_attr(CONF_DEVICETRACKER_ID)).attributes.get(
                    CONF_LONGITUDE
                )
            )
        ):
            self._warn_if_device_tracker_prob = True
            proceed_with_update = 1
            # 0: False. 1: True. 2: False, but set direction of travel to stationary
        else:
            if self._warn_if_device_tracker_prob or self._get_attr(ATTR_INITIAL_UPDATE):
                _LOGGER.warning(
                    "(%s) Tracked Entity (%s) "
                    "Latitude/Longitude is not set or is not a number. Not Proceeding with Update.",
                    self._get_attr(CONF_NAME),
                    self._get_attr(CONF_DEVICETRACKER_ID),
                )
                self._warn_if_device_tracker_prob = False
            else:
                _LOGGER.info(
                    "(%s) Tracked Entity (%s) "
                    "Latitude/Longitude is not set or is not a number. Not Proceeding with Update.",
                    self._get_attr(CONF_NAME),
                    self._get_attr(CONF_DEVICETRACKER_ID),
                )
            _LOGGER.debug(
                "(%s) Tracked Entity (%s) details: %s",
                self._get_attr(CONF_NAME),
                self._get_attr(CONF_DEVICETRACKER_ID),
                self._hass.states.get(self._get_attr(CONF_DEVICETRACKER_ID)),
            )
            return 0
            # 0: False. 1: True. 2: False, but set direction of travel to stationary
        return proceed_with_update

    @Throttle(MIN_THROTTLE_INTERVAL)
    @callback
    def _async_tsc_update(self, event: Event[EventStateChangedData]) -> None:
        """Call the _async_do_update function based on the TSC (track state change) event."""
        # _LOGGER.debug(f"({self._get_attr(CONF_NAME)}) [TSC Update] event: {event}")
        new_state = event.data["new_state"]
        if new_state is None or (
            isinstance(new_state.state, str)
            and new_state.state.lower() in {"none", STATE_UNKNOWN, STATE_UNAVAILABLE}
        ):
            return
        # _LOGGER.debug("(%s) [TSC Update] new_state: %s", self._get_attr(CONF_NAME), new_state)

        update_type: str = "Track State Change"
        self._hass.async_create_task(self._async_do_update(update_type))

    @Throttle(THROTTLE_INTERVAL)
    async def async_update(self) -> None:
        """Call the _async_do_update function based on scan interval and throttle."""
        update_type = "Scan Interval"
        self._hass.async_create_task(self._async_do_update(update_type))

    @staticmethod
    async def _async_clear_since_from_state(orig_state: str) -> str:
        return re.sub(r" \(since \d\d[:/]\d\d\)", "", orig_state)

    async def _async_in_zone(self) -> bool:
        if not self._is_attr_blank(ATTR_DEVICETRACKER_ZONE):
            zone: str = self._get_attr_safe_str(ATTR_DEVICETRACKER_ZONE).lower()
            zone_state = self._hass.states.get(f"{CONF_ZONE}.{zone}")
            if (
                self._get_attr_safe_str(CONF_DEVICETRACKER_ID).split(".")[0] == CONF_ZONE
                or (
                    "stationary" in zone
                    or zone.startswith(("statzon", "ic3_statzone_"))
                    or zone in {"away", "not_home", "notset", "not_set"}
                )
                or (
                    zone_state is not None
                    and zone_state.attributes.get(ATTR_PASSIVE, False) is True
                )
            ):
                return False
            return True
        return False

    async def _async_cleanup_attributes(self) -> None:
        attrs: MutableMapping[str, Any] = copy.deepcopy(self._internal_attr)
        for attr in attrs:
            if self._is_attr_blank(attr):
                self._clear_attr(attr)

    async def _async_check_for_updated_entity_name(self) -> None:
        if hasattr(self, "entity_id") and self._entity_id is not None:
            # _LOGGER.debug("(%s) Entity ID: %s", self._get_attr(CONF_NAME), self._entity_id)
            if (
                self._hass.states.get(str(self._entity_id)) is not None
                and self._hass.states.get(str(self._entity_id)).attributes.get(ATTR_FRIENDLY_NAME)
                is not None
                and self._get_attr(CONF_NAME)
                != self._hass.states.get(str(self._entity_id)).attributes.get(ATTR_FRIENDLY_NAME)
            ):
                _LOGGER.debug(
                    "(%s) Sensor Name Changed. Updating Name to: %s",
                    self._get_attr(CONF_NAME),
                    self._hass.states.get(str(self._entity_id)).attributes.get(ATTR_FRIENDLY_NAME),
                )
                self._set_attr(
                    CONF_NAME,
                    self._hass.states.get(str(self._entity_id)).attributes.get(ATTR_FRIENDLY_NAME),
                )
                self._config.update({CONF_NAME: self._get_attr(CONF_NAME)})
                self._set_attr(CONF_NAME, self._get_attr(CONF_NAME))
                _LOGGER.debug(
                    "(%s) Updated Config Name: %s",
                    self._get_attr(CONF_NAME),
                    self._config.get(CONF_NAME),
                )
                self._hass.config_entries.async_update_entry(
                    self._config_entry,
                    data=self._config,
                    options=self._config_entry.options,
                )
                _LOGGER.debug(
                    "(%s) Updated ConfigEntry Name: %s",
                    self._get_attr(CONF_NAME),
                    self._config_entry.data.get(CONF_NAME),
                )

    async def _async_get_zone_details(self) -> None:
        if self._get_attr_safe_str(CONF_DEVICETRACKER_ID).split(".")[0] != CONF_ZONE:
            self._set_attr(
                ATTR_DEVICETRACKER_ZONE,
                self._hass.states.get(self._get_attr(CONF_DEVICETRACKER_ID)).state,
            )
        if await self._async_in_zone():
            devicetracker_zone_name_state = None
            devicetracker_zone_id: str | None = self._hass.states.get(
                self._get_attr(CONF_DEVICETRACKER_ID)
            ).attributes.get(CONF_ZONE)
            if devicetracker_zone_id:
                devicetracker_zone_id = f"{CONF_ZONE}.{devicetracker_zone_id}"
                devicetracker_zone_name_state = self._hass.states.get(devicetracker_zone_id)
            # _LOGGER.debug("(%s) Tracked Entity Zone ID: %s", self._get_attr(CONF_NAME), devicetracker_zone_id)
            # _LOGGER.debug("(%s) Tracked Entity Zone Name State: %s", self._get_attr(CONF_NAME), devicetracker_zone_name_state)
            if devicetracker_zone_name_state:
                if devicetracker_zone_name_state.attributes.get(CONF_FRIENDLY_NAME):
                    self._set_attr(
                        ATTR_DEVICETRACKER_ZONE_NAME,
                        devicetracker_zone_name_state.attributes.get(CONF_FRIENDLY_NAME),
                    )
                else:
                    self._set_attr(ATTR_DEVICETRACKER_ZONE_NAME, devicetracker_zone_name_state.name)
            else:
                self._set_attr(
                    ATTR_DEVICETRACKER_ZONE_NAME,
                    self._get_attr(ATTR_DEVICETRACKER_ZONE),
                )

            if not self._is_attr_blank(ATTR_DEVICETRACKER_ZONE_NAME) and (
                self._get_attr_safe_str(ATTR_DEVICETRACKER_ZONE_NAME)
            ).lower() == self._get_attr(ATTR_DEVICETRACKER_ZONE_NAME):
                self._set_attr(
                    ATTR_DEVICETRACKER_ZONE_NAME,
                    self._get_attr_safe_str(ATTR_DEVICETRACKER_ZONE_NAME).title(),
                )
            _LOGGER.debug(
                "(%s) Tracked Entity Zone Name: %s",
                self._get_attr(CONF_NAME),
                self._get_attr(ATTR_DEVICETRACKER_ZONE_NAME),
            )
        else:
            _LOGGER.debug(
                "(%s) Tracked Entity Zone: %s",
                self._get_attr(CONF_NAME),
                self._get_attr(ATTR_DEVICETRACKER_ZONE),
            )
            self._set_attr(
                ATTR_DEVICETRACKER_ZONE_NAME,
                self._get_attr(ATTR_DEVICETRACKER_ZONE),
            )

    async def _async_determine_if_update_needed(self) -> int:
        proceed_with_update = 1
        # 0: False. 1: True. 2: False, but set direction of travel to stationary

        if self._get_attr(ATTR_INITIAL_UPDATE):
            _LOGGER.info("(%s) Performing Initial Update for user", self._get_attr(CONF_NAME))
            # 0: False. 1: True. 2: False, but set direction of travel to stationary
            return 1

        if self._is_attr_blank(ATTR_NATIVE_VALUE) or (
            isinstance(self._get_attr(ATTR_NATIVE_VALUE), str)
            and self._get_attr_safe_str(ATTR_NATIVE_VALUE).lower()
            in {"none", STATE_UNKNOWN, STATE_UNAVAILABLE}
        ):
            _LOGGER.info(
                "(%s) Previous State is Unknown, performing update", self._get_attr(CONF_NAME)
            )
            # 0: False. 1: True. 2: False, but set direction of travel to stationary
            return 1

        if self._get_attr(ATTR_LOCATION_CURRENT) == self._get_attr(ATTR_LOCATION_PREVIOUS):
            _LOGGER.info(
                "(%s) Not performing update because coordinates are identical",
                self._get_attr(CONF_NAME),
            )
            return 2
            # 0: False. 1: True. 2: False, but set direction of travel to stationary
        if int(self._get_attr_safe_float(ATTR_DISTANCE_TRAVELED_M)) < 10:
            _LOGGER.info(
                "(%s) "
                "Not performing update, distance traveled from last update is less than 10 m (%s m)",
                self._get_attr(CONF_NAME),
                round(self._get_attr_safe_float(ATTR_DISTANCE_TRAVELED_M), 1),
            )
            return 2
            # 0: False. 1: True. 2: False, but set direction of travel to stationary
        return proceed_with_update
        # 0: False. 1: True. 2: False, but set direction of travel to stationary

    def _get_dict_from_url(self, url: str, name: str, dict_name: str) -> None:
        _LOGGER.info("(%s) Requesting data for %s", self._get_attr(CONF_NAME), name)
        _LOGGER.debug("(%s) %s URL: %s", self._get_attr(CONF_NAME), name, url)
        self._set_attr(dict_name, {})
        headers: dict[str, str] = {"user-agent": f"Mozilla/5.0 (Home Assistant) {DOMAIN}/{VERSION}"}
        try:
            get_response: requests.Response | None = requests.get(url=url, headers=headers)
        except requests.exceptions.RetryError as e:
            get_response = None
            _LOGGER.warning(
                "(%s) Retry Error connecting to %s [%s: %s]: %s",
                self._get_attr(CONF_NAME),
                name,
                e.__class__.__qualname__,
                e,
                url,
            )
            return
        except requests.exceptions.ConnectionError as e:
            get_response = None
            _LOGGER.warning(
                "(%s) Connection Error connecting to %s [%s: %s]: %s",
                self._get_attr(CONF_NAME),
                name,
                e.__class__.__qualname__,
                e,
                url,
            )
            return
        except requests.exceptions.HTTPError as e:
            get_response = None
            _LOGGER.warning(
                "(%s) HTTP Error connecting to %s [%s: %s]: %s",
                self._get_attr(CONF_NAME),
                name,
                e.__class__.__qualname__,
                e,
                url,
            )
            return
        except requests.exceptions.Timeout as e:
            get_response = None
            _LOGGER.warning(
                "(%s) Timeout connecting to %s [%s: %s]: %s",
                self._get_attr(CONF_NAME),
                name,
                e.__class__.__qualname__,
                e,
                url,
            )
            return
        except OSError as e:
            # Includes error code 101, network unreachable
            get_response = None
            _LOGGER.warning(
                "(%s) Network unreachable error when connecting to %s [%s: %s]: %s",
                self._get_attr(CONF_NAME),
                name,
                e.__class__.__qualname__,
                e,
                url,
            )
            return
        except NewConnectionError as e:
            get_response = None
            _LOGGER.warning(
                "(%s) New Connection Error connecting to %s [%s: %s]: %s",
                self._get_attr(CONF_NAME),
                name,
                e.__class__.__qualname__,
                e,
                url,
            )
            return

        get_json_input: str | None = None
        if get_response:
            get_json_input = get_response.text
            _LOGGER.debug("(%s) %s Response: %s", self._get_attr(CONF_NAME), name, get_json_input)

        if get_json_input:
            try:
                get_dict = json.loads(get_json_input)
            except json.decoder.JSONDecodeError as e:
                _LOGGER.warning(
                    "(%s) JSON Decode Error with %s info [%s: %s]: %s",
                    self._get_attr(CONF_NAME),
                    name,
                    e.__class__.__qualname__,
                    e,
                    get_json_input,
                )
                return
        if "error_message" in get_dict:
            _LOGGER.warning(
                "(%s) An error occurred contacting the web service for %s: %s",
                self._get_attr(CONF_NAME),
                name,
                get_dict.get("error_message"),
            )
            return

        if (
            isinstance(get_dict, list)
            and len(get_dict) == 1
            and isinstance(get_dict[0], MutableMapping)
        ):
            self._set_attr(dict_name, get_dict[0])
            return

        self._set_attr(dict_name, get_dict)
        return

    async def _async_get_map_link(self) -> None:
        if self._get_attr(CONF_MAP_PROVIDER) == "google":
            self._set_attr(
                ATTR_MAP_LINK,
                (
                    "https://maps.google.com/?q="
                    f"{self._get_attr(ATTR_LOCATION_CURRENT)}"
                    f"&ll={self._get_attr(ATTR_LOCATION_CURRENT)}"
                    f"&z={self._get_attr(CONF_MAP_ZOOM)}"
                ),
            )
        elif self._get_attr(CONF_MAP_PROVIDER) == "osm":
            self._set_attr(
                ATTR_MAP_LINK,
                (
                    "https://www.openstreetmap.org/?mlat="
                    f"{self._get_attr(ATTR_LATITUDE)}"
                    f"&mlon={self._get_attr(ATTR_LONGITUDE)}"
                    f"#map={self._get_attr(CONF_MAP_ZOOM)}/"
                    f"{self._get_attr_safe_str(ATTR_LATITUDE)[:8]}/"
                    f"{self._get_attr_safe_str(ATTR_LONGITUDE)[:9]}"
                ),
            )
        else:
            self._set_attr(
                ATTR_MAP_LINK,
                (
                    "https://maps.apple.com/maps/?q="
                    f"{self._get_attr(ATTR_LOCATION_CURRENT)}"
                    f"&z={self._get_attr(CONF_MAP_ZOOM)}"
                ),
            )
        _LOGGER.debug(
            "(%s) Map Link Type: %s", self._get_attr(CONF_NAME), self._get_attr(CONF_MAP_PROVIDER)
        )
        _LOGGER.debug(
            "(%s) Map Link URL: %s", self._get_attr(CONF_NAME), self._get_attr(ATTR_MAP_LINK)
        )

    async def _async_get_gps_accuracy(self) -> int:
        if (
            self._hass.states.get(self._get_attr(CONF_DEVICETRACKER_ID))
            and self._hass.states.get(self._get_attr(CONF_DEVICETRACKER_ID)).attributes
            and ATTR_GPS_ACCURACY
            in self._hass.states.get(self._get_attr(CONF_DEVICETRACKER_ID)).attributes
            and self._hass.states.get(self._get_attr(CONF_DEVICETRACKER_ID)).attributes.get(
                ATTR_GPS_ACCURACY
            )
            is not None
            and _is_float(
                self._hass.states.get(self._get_attr(CONF_DEVICETRACKER_ID)).attributes.get(
                    ATTR_GPS_ACCURACY
                )
            )
        ):
            self._set_attr(
                ATTR_GPS_ACCURACY,
                float(
                    self._hass.states.get(self._get_attr(CONF_DEVICETRACKER_ID)).attributes.get(
                        ATTR_GPS_ACCURACY
                    )
                ),
            )
        else:
            _LOGGER.debug(
                "(%s) GPS Accuracy attribute not found in: %s",
                self._get_attr(CONF_NAME),
                self._get_attr(CONF_DEVICETRACKER_ID),
            )
        proceed_with_update = 1
        # 0: False. 1: True. 2: False, but set direction of travel to stationary

        if not self._is_attr_blank(ATTR_GPS_ACCURACY):
            if self._get_attr(CONF_USE_GPS) and self._get_attr(ATTR_GPS_ACCURACY) == 0:
                proceed_with_update = 0
                # 0: False. 1: True. 2: False, but set direction of travel to stationary
                _LOGGER.info(
                    "(%s) GPS Accuracy is 0.0, not performing update", self._get_attr(CONF_NAME)
                )
            else:
                _LOGGER.debug(
                    "(%s) GPS Accuracy: %s",
                    self._get_attr(CONF_NAME),
                    round(self._get_attr_safe_float(ATTR_GPS_ACCURACY), 3),
                )
        return proceed_with_update

    async def _async_get_driving_status(self) -> None:
        self._clear_attr(ATTR_DRIVING)
        isDriving: bool = False
        if not await self._async_in_zone():
            if self._get_attr(ATTR_DIRECTION_OF_TRAVEL) != "stationary" and (
                self._get_attr(ATTR_PLACE_CATEGORY) == "highway"
                or self._get_attr(ATTR_PLACE_TYPE) == "motorway"
            ):
                isDriving = True
        if isDriving:
            self._set_attr(ATTR_DRIVING, "Driving")

    async def _async_parse_osm_dict(self) -> None:
        osm_dict: MutableMapping[str, Any] | None = self._get_attr(ATTR_OSM_DICT)
        if not osm_dict:
            return

        await self._parse_type(osm_dict=osm_dict)
        await self._parse_category(osm_dict=osm_dict)
        await self._parse_namedetails(osm_dict=osm_dict)
        await self._parse_address(osm_dict=osm_dict)
        await self._parse_miscellaneous(osm_dict=osm_dict)
        await self._set_place_name_no_dupe()

        _LOGGER.debug(
            "(%s) Entity attributes after parsing OSM Dict: %s",
            self._get_attr(CONF_NAME),
            self._internal_attr,
        )

    async def _parse_type(self, osm_dict: MutableMapping[str, Any]) -> None:
        if "type" not in osm_dict:
            return
        self._set_attr(ATTR_PLACE_TYPE, osm_dict.get("type"))
        if self._get_attr(ATTR_PLACE_TYPE) == "yes":
            if "addresstype" in osm_dict:
                self._set_attr(
                    ATTR_PLACE_TYPE,
                    osm_dict.get("addresstype"),
                )
            else:
                self._clear_attr(ATTR_PLACE_TYPE)
        if "address" in osm_dict and self._get_attr(ATTR_PLACE_TYPE) in osm_dict["address"]:
            self._set_attr(
                ATTR_PLACE_NAME,
                osm_dict["address"].get(self._get_attr(ATTR_PLACE_TYPE)),
            )

    async def _parse_category(self, osm_dict: MutableMapping[str, Any]) -> None:
        if "category" not in osm_dict:
            return

        self._set_attr(
            ATTR_PLACE_CATEGORY,
            osm_dict.get("category"),
        )
        if "address" in osm_dict and self._get_attr(ATTR_PLACE_CATEGORY) in osm_dict["address"]:
            self._set_attr(
                ATTR_PLACE_NAME,
                osm_dict["address"].get(self._get_attr(ATTR_PLACE_CATEGORY)),
            )

    async def _parse_namedetails(self, osm_dict: MutableMapping[str, Any]) -> None:
        namedetails: MutableMapping[str, Any] | None = osm_dict.get("namedetails")
        if not namedetails:
            return
        if "name" in namedetails:
            self._set_attr(
                ATTR_PLACE_NAME,
                namedetails.get("name"),
            )
        if not self._is_attr_blank(CONF_LANGUAGE):
            for language in self._get_attr_safe_str(CONF_LANGUAGE).split(","):
                if f"name:{language}" in namedetails:
                    self._set_attr(
                        ATTR_PLACE_NAME,
                        namedetails.get(f"name:{language}"),
                    )
                    break

    async def _parse_address(self, osm_dict: MutableMapping[str, Any]) -> None:
        address: MutableMapping[str, Any] | None = osm_dict.get("address")
        if not address:
            return

        await self._set_address_details(address)
        await self._set_city_details(address)
        await self._set_region_details(address)

    async def _set_address_details(self, address: MutableMapping[str, Any]) -> None:
        if "house_number" in address:
            self._set_attr(
                ATTR_STREET_NUMBER,
                address.get("house_number"),
            )
        if "road" in address:
            self._set_attr(
                ATTR_STREET,
                address.get("road"),
            )
        if "retail" in address and (
            self._is_attr_blank(ATTR_PLACE_NAME)
            or (
                not self._is_attr_blank(ATTR_PLACE_CATEGORY)
                and not self._is_attr_blank(ATTR_STREET)
                and self._get_attr(ATTR_PLACE_CATEGORY) == "highway"
                and self._get_attr(ATTR_STREET) == self._get_attr(ATTR_PLACE_NAME)
            )
        ):
            self._set_attr(
                ATTR_PLACE_NAME,
                self._get_attr_safe_dict(ATTR_OSM_DICT).get("address", {}).get("retail"),
            )
        _LOGGER.debug(
            "(%s) Place Name: %s", self._get_attr(CONF_NAME), self._get_attr(ATTR_PLACE_NAME)
        )

    async def _set_city_details(self, address: MutableMapping[str, Any]) -> None:
        CITY_LIST: list[str] = [
            "city",
            "town",
            "village",
            "township",
            "hamlet",
            "city_district",
            "municipality",
        ]
        POSTAL_TOWN_LIST: list[str] = [
            "city",
            "town",
            "village",
            "township",
            "hamlet",
            "borough",
            "suburb",
        ]
        NEIGHBOURHOOD_LIST: list[str] = [
            "village",
            "township",
            "hamlet",
            "borough",
            "suburb",
            "quarter",
            "neighbourhood",
        ]
        for city_type in CITY_LIST:
            with contextlib.suppress(ValueError):
                POSTAL_TOWN_LIST.remove(city_type)

            with contextlib.suppress(ValueError):
                NEIGHBOURHOOD_LIST.remove(city_type)
            if city_type in address:
                self._set_attr(
                    ATTR_CITY,
                    address.get(city_type),
                )
                break
        for postal_town_type in POSTAL_TOWN_LIST:
            with contextlib.suppress(ValueError):
                NEIGHBOURHOOD_LIST.remove(postal_town_type)
            if postal_town_type in address:
                self._set_attr(
                    ATTR_POSTAL_TOWN,
                    address.get(postal_town_type),
                )
                break
        for neighbourhood_type in NEIGHBOURHOOD_LIST:
            if neighbourhood_type in address:
                self._set_attr(
                    ATTR_PLACE_NEIGHBOURHOOD,
                    address.get(neighbourhood_type),
                )
                break

        if not self._is_attr_blank(ATTR_CITY):
            self._set_attr(
                ATTR_CITY_CLEAN,
                self._get_attr_safe_str(ATTR_CITY).replace(" Township", "").strip(),
            )
            if self._get_attr_safe_str(ATTR_CITY_CLEAN).startswith("City of"):
                self._set_attr(
                    ATTR_CITY_CLEAN,
                    f"{self._get_attr_safe_str(ATTR_CITY_CLEAN)[8:]} City",
                )

    async def _set_region_details(self, address: MutableMapping[str, Any]) -> None:
        if "state" in address:
            self._set_attr(
                ATTR_REGION,
                address.get("state"),
            )
        if "ISO3166-2-lvl4" in address:
            self._set_attr(
                ATTR_STATE_ABBR,
                address["ISO3166-2-lvl4"].split("-")[1].upper(),
            )
        if "county" in address:
            self._set_attr(
                ATTR_COUNTY,
                address.get("county"),
            )
        if "country" in address:
            self._set_attr(
                ATTR_COUNTRY,
                address.get("country"),
            )
        if "country_code" in address:
            self._set_attr(
                ATTR_COUNTRY_CODE,
                address["country_code"].upper(),
            )
        if "postcode" in address:
            self._set_attr(
                ATTR_POSTAL_CODE,
                self._get_attr_safe_dict(ATTR_OSM_DICT).get("address", {}).get("postcode"),
            )

    async def _parse_miscellaneous(self, osm_dict: MutableMapping[str, Any]) -> None:
        if "display_name" in osm_dict:
            self._set_attr(
                ATTR_FORMATTED_ADDRESS,
                osm_dict.get("display_name"),
            )

        if "osm_id" in osm_dict:
            self._set_attr(
                ATTR_OSM_ID,
                str(self._get_attr_safe_dict(ATTR_OSM_DICT).get("osm_id", "")),
            )
        if "osm_type" in osm_dict:
            self._set_attr(
                ATTR_OSM_TYPE,
                osm_dict.get("osm_type"),
            )

        if (
            not self._is_attr_blank(ATTR_PLACE_CATEGORY)
            and self._get_attr_safe_str(ATTR_PLACE_CATEGORY).lower() == "highway"
            and "namedetails" in osm_dict
            and osm_dict.get("namedetails") is not None
            and "ref" in osm_dict["namedetails"]
        ):
            street_refs: list = re.split(
                r"[\;\\\/\,\.\:]",
                osm_dict["namedetails"].get("ref"),
            )
            street_refs = [i for i in street_refs if i.strip()]  # Remove blank strings
            # _LOGGER.debug("(%s) Street Refs: %s", self._get_attr(CONF_NAME), street_refs)
            for ref in street_refs:
                if bool(re.search(r"\d", ref)):
                    self._set_attr(ATTR_STREET_REF, ref)
                    break
            if not self._is_attr_blank(ATTR_STREET_REF):
                _LOGGER.debug(
                    "(%s) Street: %s / Street Ref: %s",
                    self._get_attr(CONF_NAME),
                    self._get_attr(ATTR_STREET),
                    self._get_attr(ATTR_STREET_REF),
                )

    async def _set_place_name_no_dupe(self) -> None:
        dupe_attributes_check: list[str] = []
        dupe_attributes_check.extend(
            [
                self._get_attr_safe_str(attr)
                for attr in PLACE_NAME_DUPLICATE_LIST
                if not self._is_attr_blank(attr)
            ]
        )
        if (
            not self._is_attr_blank(ATTR_PLACE_NAME)
            and self._get_attr(ATTR_PLACE_NAME) not in dupe_attributes_check
        ):
            self._set_attr(ATTR_PLACE_NAME_NO_DUPE, self._get_attr(ATTR_PLACE_NAME))

    async def _async_build_formatted_place(self) -> None:
        formatted_place_array: list[str] = []
        if not await self._async_in_zone():
            if not self._is_attr_blank(ATTR_DRIVING) and "driving" in (
                self._get_attr_safe_list(ATTR_DISPLAY_OPTIONS_LIST)
            ):
                formatted_place_array.append(self._get_attr_safe_str(ATTR_DRIVING))
            # Don't use place name if the same as another attributes
            use_place_name: bool = True
            sensor_attributes_values: list[str] = []
            sensor_attributes_values.extend(
                [
                    self._get_attr_safe_str(attr)
                    for attr in PLACE_NAME_DUPLICATE_LIST
                    if not self._is_attr_blank(attr)
                ]
            )
            # if not self._is_attr_blank(ATTR_PLACE_NAME):
            # _LOGGER.debug(
            #     "(%s) Duplicated List [Place Name: %s]: %s",
            #     self._get_attr(CONF_NAME),
            #     self._get_attr(ATTR_PLACE_NAME),
            #     sensor_attributes_values,
            # )
            if self._is_attr_blank(ATTR_PLACE_NAME):
                use_place_name = False
                # _LOGGER.debug("(%s) Place Name is None", self._get_attr(CONF_NAME))
            elif self._get_attr(ATTR_PLACE_NAME) in sensor_attributes_values:
                # _LOGGER.debug("(%s) Not Using Place Name: %s", self._get_attr(CONF_NAME), self._get_attr(ATTR_PLACE_NAME))
                use_place_name = False
            _LOGGER.debug("(%s) use_place_name: %s", self._get_attr(CONF_NAME), use_place_name)
            if not use_place_name:
                if (
                    not self._is_attr_blank(ATTR_PLACE_TYPE)
                    and self._get_attr_safe_str(ATTR_PLACE_TYPE).lower() != "unclassified"
                    and self._get_attr_safe_str(ATTR_PLACE_CATEGORY).lower() != "highway"
                ):
                    formatted_place_array.append(
                        self._get_attr_safe_str(ATTR_PLACE_TYPE)
                        .title()
                        .replace("Proposed", "")
                        .replace("Construction", "")
                        .strip()
                    )
                elif (
                    not self._is_attr_blank(ATTR_PLACE_CATEGORY)
                    and self._get_attr_safe_str(ATTR_PLACE_CATEGORY).lower() != "highway"
                ):
                    formatted_place_array.append(
                        self._get_attr_safe_str(ATTR_PLACE_CATEGORY).title().strip()
                    )
                street: str | None = None
                if self._is_attr_blank(ATTR_STREET) and not self._is_attr_blank(ATTR_STREET_REF):
                    street = self._get_attr_safe_str(ATTR_STREET_REF).strip()
                    _LOGGER.debug("(%s) Using street_ref: %s", self._get_attr(CONF_NAME), street)
                elif not self._is_attr_blank(ATTR_STREET):
                    if (
                        not self._is_attr_blank(ATTR_PLACE_CATEGORY)
                        and self._get_attr_safe_str(ATTR_PLACE_CATEGORY).lower() == "highway"
                        and not self._is_attr_blank(ATTR_PLACE_TYPE)
                        and self._get_attr_safe_str(ATTR_PLACE_TYPE).lower()
                        in {"motorway", "trunk"}
                        and not self._is_attr_blank(ATTR_STREET_REF)
                    ):
                        street = self._get_attr_safe_str(ATTR_STREET_REF).strip()
                        _LOGGER.debug(
                            "(%s) Using street_ref: %s", self._get_attr(CONF_NAME), street
                        )
                    else:
                        street = self._get_attr_safe_str(ATTR_STREET).strip()
                        _LOGGER.debug("(%s) Using street: %s", self._get_attr(CONF_NAME), street)
                if street and self._is_attr_blank(ATTR_STREET_NUMBER):
                    formatted_place_array.append(street)
                elif street and not self._is_attr_blank(ATTR_STREET_NUMBER):
                    formatted_place_array.append(
                        f"{self._get_attr_safe_str(ATTR_STREET_NUMBER).strip()} {street}"
                    )
                if (
                    not self._is_attr_blank(ATTR_PLACE_TYPE)
                    and self._get_attr_safe_str(ATTR_PLACE_TYPE).lower() == "house"
                    and not self._is_attr_blank(ATTR_PLACE_NEIGHBOURHOOD)
                ):
                    formatted_place_array.append(
                        self._get_attr_safe_str(ATTR_PLACE_NEIGHBOURHOOD).strip()
                    )

            else:
                formatted_place_array.append(self._get_attr_safe_str(ATTR_PLACE_NAME).strip())
            if not self._is_attr_blank(ATTR_CITY_CLEAN):
                formatted_place_array.append(self._get_attr_safe_str(ATTR_CITY_CLEAN).strip())
            elif not self._is_attr_blank(ATTR_CITY):
                formatted_place_array.append(self._get_attr_safe_str(ATTR_CITY).strip())
            elif not self._is_attr_blank(ATTR_COUNTY):
                formatted_place_array.append(self._get_attr_safe_str(ATTR_COUNTY).strip())
            if not self._is_attr_blank(ATTR_STATE_ABBR):
                formatted_place_array.append(self._get_attr_safe_str(ATTR_STATE_ABBR))
        else:
            formatted_place_array.append(
                self._get_attr_safe_str(ATTR_DEVICETRACKER_ZONE_NAME).strip()
            )
        formatted_place: str = ", ".join(item for item in formatted_place_array)
        formatted_place = formatted_place.replace("\n", " ").replace("  ", " ").strip()
        self._set_attr(ATTR_FORMATTED_PLACE, formatted_place)

    async def _do_brackets_and_parens_count_match(self, curr_options: str) -> bool:
        if curr_options.count("[") != curr_options.count("]"):
            _LOGGER.error(
                "(%s) [adv_options] Bracket Count Mismatch: %s",
                self._get_attr(CONF_NAME),
                curr_options,
            )
            return False
        if curr_options.count("(") != curr_options.count(")"):
            _LOGGER.error(
                "(%s) [adv_options] Parenthesis Count Mismatch: %s",
                self._get_attr(CONF_NAME),
                curr_options,
            )
            return False
        return True

    async def _async_build_from_advanced_options(self, curr_options: str) -> None:
        _LOGGER.debug("(%s) [adv_options] Options: %s", self._get_attr(CONF_NAME), curr_options)
        if not await self._do_brackets_and_parens_count_match(curr_options) or not curr_options:
            return

        # _LOGGER.debug("(%s) [adv_options] Options has a [ or ( and optional ,", self._get_attr(CONF_NAME))
        if "[" in curr_options or "(" in curr_options:
            await self._process_advanced_bracket_or_parens(curr_options=curr_options)
            return

        # _LOGGER.debug("(%s) [adv_options] Options has , but no [ or (, splitting", self._get_attr(CONF_NAME))
        if "," in curr_options:
            await self._process_advanced_only_commas(curr_options=curr_options)
            return

        # _LOGGER.debug("(%s) [adv_options] Options should just be a single term", self._get_attr(CONF_NAME))
        await self._process_advanced_single_term(curr_options=curr_options)

    async def _process_advanced_bracket_or_parens(self, curr_options: str) -> None:
        incl: list[str] = []
        excl: list[str] = []
        incl_attr: MutableMapping[str, Any] = {}
        excl_attr: MutableMapping[str, Any] = {}
        none_opt: str | None = None
        next_opt: str | None = None

        # _LOGGER.debug("(%s) [adv_options] Options has a [ or ( and optional ,", self._get_attr(CONF_NAME))
        comma_num: int = curr_options.find(",")
        bracket_num: int = curr_options.find("[")
        paren_num: int = curr_options.find("(")

        # Comma is first symbol
        if (
            comma_num != -1
            and (bracket_num == -1 or comma_num < bracket_num)
            and (paren_num == -1 or comma_num < paren_num)
        ):
            # _LOGGER.debug("(%s) [adv_options] Comma is First", self._get_attr(CONF_NAME))
            opt: str = curr_options[:comma_num]
            # _LOGGER.debug("(%s) [adv_options] Option: %s", self._get_attr(CONF_NAME), opt)
            if opt:
                ret_state: str | None = await self._async_get_option_state(opt.strip())
                if ret_state:
                    self._adv_options_state_list.append(ret_state)
                    _LOGGER.debug(
                        "(%s) [adv_options] Updated state list: %s",
                        self._get_attr(CONF_NAME),
                        self._adv_options_state_list,
                    )
            next_opt = curr_options[(comma_num + 1) :]
            # _LOGGER.debug("(%s) [adv_options] Next Options: %s",self._get_attr(CONF_NAME), next_opt)
            if next_opt:
                await self._async_build_from_advanced_options(next_opt.strip())
                # _LOGGER.debug("(%s) [adv_options] Back from recursion", self._get_attr(CONF_NAME))
            return

        # Bracket is first symbol
        if (
            bracket_num != -1
            and (comma_num == -1 or bracket_num < comma_num)
            and (paren_num == -1 or bracket_num < paren_num)
        ):
            # _LOGGER.debug("(%s) [adv_options] Bracket is First", self._get_attr(CONF_NAME))
            opt = curr_options[:bracket_num]
            # _LOGGER.debug("(%s) [adv_options] Option: %s", self._get_attr(CONF_NAME), opt)
            none_opt, next_opt = await self._async_parse_bracket(curr_options[bracket_num:])
            if next_opt and len(next_opt) > 1 and next_opt[0] == "(":
                # Parse Parenthesis
                incl, excl, incl_attr, excl_attr, next_opt = await self._async_parse_parens(
                    next_opt
                )

            if opt:
                ret_state = await self._async_get_option_state(
                    opt.strip(), incl, excl, incl_attr, excl_attr
                )
                if ret_state:
                    self._adv_options_state_list.append(ret_state)
                    _LOGGER.debug(
                        "(%s) [adv_options] Updated state list: %s",
                        self._get_attr(CONF_NAME),
                        self._adv_options_state_list,
                    )
                elif none_opt:
                    await self._async_build_from_advanced_options(none_opt.strip())
                    # _LOGGER.debug("(%s) [adv_options] Back from recursion", self._get_attr(CONF_NAME))

            if next_opt and len(next_opt) > 1 and next_opt[0] == ",":
                next_opt = next_opt[1:]
                # _LOGGER.debug("(%s) [adv_options] Next Options: %s", self._get_attr(CONF_NAME), next_opt)
                if next_opt:
                    await self._async_build_from_advanced_options(next_opt.strip())
                    # _LOGGER.debug("(%s) [adv_options] Back from recursion", self._get_attr(CONF_NAME))
            return

        # Parenthesis is first symbol
        if (
            paren_num != -1
            and (comma_num == -1 or paren_num < comma_num)
            and (bracket_num == -1 or paren_num < bracket_num)
        ):
            # _LOGGER.debug("(%s) [adv_options] Parenthesis is First", self._get_attr(CONF_NAME))
            opt = curr_options[:paren_num]
            _LOGGER.debug("(%s) [adv_options] Option: %s", self._get_attr(CONF_NAME), opt)
            incl, excl, incl_attr, excl_attr, next_opt = await self._async_parse_parens(
                curr_options[paren_num:]
            )
            if next_opt and len(next_opt) > 1 and next_opt[0] == "[":
                # Parse Bracket
                none_opt, next_opt = await self._async_parse_bracket(next_opt)

            if opt:
                ret_state = await self._async_get_option_state(
                    opt.strip(), incl, excl, incl_attr, excl_attr
                )
                if ret_state:
                    self._adv_options_state_list.append(ret_state)
                    _LOGGER.debug(
                        "(%s) [adv_options] Updated state list: %s",
                        self._get_attr(CONF_NAME),
                        self._adv_options_state_list,
                    )
                elif none_opt:
                    await self._async_build_from_advanced_options(none_opt.strip())
                    # _LOGGER.debug("(%s) [adv_options] Back from recursion", self._get_attr(CONF_NAME))

            if next_opt and len(next_opt) > 1 and next_opt[0] == ",":
                next_opt = next_opt[1:]
                # _LOGGER.debug("(%s) [adv_options] Next Options: %s", self._get_attr(CONF_NAME), next_opt)
                if next_opt:
                    await self._async_build_from_advanced_options(next_opt.strip())
                    # _LOGGER.debug("(%s) [adv_options] Back from recursion", self._get_attr(CONF_NAME))

    async def _process_advanced_only_commas(self, curr_options: str) -> None:
        # _LOGGER.debug("(%s) [adv_options] Options has , but no [ or (, splitting", self._get_attr(CONF_NAME))
        for opt in curr_options.split(","):
            if opt is not None and opt:
                ret_state = await self._async_get_option_state(opt.strip())
                if ret_state is not None and ret_state:
                    self._adv_options_state_list.append(ret_state)
                    _LOGGER.debug(
                        "(%s) [adv_options] Updated state list: %s",
                        self._get_attr(CONF_NAME),
                        self._adv_options_state_list,
                    )

    async def _process_advanced_single_term(self, curr_options: str) -> None:
        ret_state = await self._async_get_option_state(curr_options.strip())
        if ret_state is not None and ret_state:
            self._adv_options_state_list.append(ret_state)
            _LOGGER.debug(
                "(%s) [adv_options] Updated state list: %s",
                self._get_attr(CONF_NAME),
                self._adv_options_state_list,
            )

    async def _async_parse_parens(
        self, curr_options: str
    ) -> tuple[list, list, MutableMapping[str, Any], MutableMapping[str, Any], str | None]:
        incl: list = []
        excl: list = []
        incl_attr: MutableMapping[str, Any] = {}
        excl_attr: MutableMapping[str, Any] = {}
        incl_excl_list: list = []
        empty_paren: bool = False
        next_opt: str | None = None
        paren_count: int = 1
        close_paren_num: int = 0
        last_comma: int = -1
        if curr_options[0] == "(":
            curr_options = curr_options[1:]
        if curr_options[0] == ")":
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
            # _LOGGER.debug("(%s) [parse_parens] incl_excl_list: %s", self._get_attr(CONF_NAME), incl_excl_list)
            paren_first: bool = True
            paren_incl: bool = True
            for item in incl_excl_list:
                if paren_first:
                    paren_first = False
                    if item == "-":
                        paren_incl = False
                        # _LOGGER.debug("(%s) [parse_parens] excl", self._get_attr(CONF_NAME))
                        continue
                    # else:
                    #    _LOGGER.debug("(%s) [parse_parens] incl", self._get_attr(CONF_NAME))
                    if item == "+":
                        continue
                # _LOGGER.debug("(%s) [parse_parens] item: %s", self._get_attr(CONF_NAME), item)
                if item is not None and item:
                    if "(" in item:
                        if ")" not in item or item.count("(") > 1 or item.count(")") > 1:
                            _LOGGER.error(
                                "(%s) [parse_parens] Parenthesis Mismatch: %s",
                                self._get_attr(CONF_NAME),
                                item,
                            )
                            continue
                        paren_attr = item[: item.find("(")]
                        paren_attr_first = True
                        paren_attr_incl = True
                        paren_attr_list: list = []
                        for attr_item in item[(item.find("(") + 1) : item.find(")")].split(","):
                            if paren_attr_first:
                                paren_attr_first = False
                                if attr_item == "-":
                                    paren_attr_incl = False
                                    # _LOGGER.debug("(%s) [parse_parens] attr_excl", self._get_attr(CONF_NAME))
                                    continue
                                # else:
                                # _LOGGER.debug("(%s) [parse_parens] attr_incl", self._get_attr(CONF_NAME))
                                if attr_item == "+":
                                    continue
                            # _LOGGER.debug(
                            #     "(%s) [parse_parens] attr: %s / item: %s",
                            #     self._get_attr(CONF_NAME),
                            #     paren_attr,
                            #     attr_item,
                            # )
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
                "(%s) [parse_parens] Parenthesis Mismatch: %s",
                self._get_attr(CONF_NAME),
                curr_options,
            )
        next_opt = curr_options[(close_paren_num + 1) :]
        # _LOGGER.debug("(%s) [parse_parens] Raw Next Options: %s", self._get_attr(CONF_NAME), next_opt)
        return incl, excl, incl_attr, excl_attr, next_opt

    async def _async_parse_bracket(self, curr_options: str) -> tuple[str | None, str | None]:
        # _LOGGER.debug("(%s) [parse_bracket] Options: %s", self._get_attr(CONF_NAME), curr_options)
        empty_bracket: bool = False
        none_opt: str | None = None
        next_opt: str | None = None
        bracket_count: int = 1
        close_bracket_num: int = 0
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
            # _LOGGER.debug("(%s) [parse_bracket] None Options: %s", self._get_attr(CONF_NAME), none_opt)
            next_opt = curr_options[(close_bracket_num + 1) :].strip()
            # _LOGGER.debug("(%s) [parse_bracket] Raw Next Options: %s", self._get_attr(CONF_NAME), next_opt)
        else:
            _LOGGER.error(
                "(%s) [parse_bracket] Bracket Mismatch Error: %s",
                self._get_attr(CONF_NAME),
                curr_options,
            )
        return none_opt, next_opt

    async def _async_get_option_state(
        self,
        opt: str,
        incl: list | None = None,
        excl: list | None = None,
        incl_attr: MutableMapping[str, Any] | None = None,
        excl_attr: MutableMapping[str, Any] | None = None,
    ) -> str | None:
        incl = [] if incl is None else incl
        excl = [] if excl is None else excl
        incl_attr = {} if incl_attr is None else incl_attr
        excl_attr = {} if excl_attr is None else excl_attr
        if opt:
            opt = str(opt).lower().strip()
        _LOGGER.debug("(%s) [get_option_state] Option: %s", self._get_attr(CONF_NAME), opt)
        out: str | None = self._get_attr(DISPLAY_OPTIONS_MAP.get(opt))
        if (
            DISPLAY_OPTIONS_MAP.get(opt) in {ATTR_DEVICETRACKER_ZONE, ATTR_DEVICETRACKER_ZONE_NAME}
            and not await self._async_in_zone()
        ):
            out = None
        _LOGGER.debug("(%s) [get_option_state] State: %s", self._get_attr(CONF_NAME), out)
        _LOGGER.debug("(%s) [get_option_state] incl list: %s", self._get_attr(CONF_NAME), incl)
        _LOGGER.debug("(%s) [get_option_state] excl list: %s", self._get_attr(CONF_NAME), excl)
        _LOGGER.debug(
            "(%s) [get_option_state] incl_attr dict: %s", self._get_attr(CONF_NAME), incl_attr
        )
        _LOGGER.debug(
            "(%s) [get_option_state] excl_attr dict: %s", self._get_attr(CONF_NAME), excl_attr
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
                        self._get_attr(CONF_NAME),
                        attr,
                        self._get_attr(DISPLAY_OPTIONS_MAP.get(attr)),
                    )
                    _LOGGER.debug(
                        "(%s) [get_option_state] incl_states: %s", self._get_attr(CONF_NAME), states
                    )
                    map_attr: str | None = DISPLAY_OPTIONS_MAP.get(attr)
                    if (
                        not map_attr
                        or self._is_attr_blank(map_attr)
                        or self._get_attr(map_attr) not in states
                    ):
                        out = None
            if excl_attr:
                for attr, states in excl_attr.items():
                    _LOGGER.debug(
                        "(%s) [get_option_state] excl_attr: %s / State: %s",
                        self._get_attr(CONF_NAME),
                        attr,
                        self._get_attr(DISPLAY_OPTIONS_MAP.get(attr)),
                    )
                    _LOGGER.debug(
                        "(%s) [get_option_state] excl_states: %s", self._get_attr(CONF_NAME), states
                    )
                    if self._get_attr(DISPLAY_OPTIONS_MAP.get(attr)) in states:
                        out = None
            _LOGGER.debug(
                "(%s) [get_option_state] State after incl/excl: %s", self._get_attr(CONF_NAME), out
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
                #     self._get_attr(CONF_NAME),
                #     self._street_i,
                # )
            if DISPLAY_OPTIONS_MAP.get(opt) == ATTR_STREET_NUMBER:
                self._street_num_i = self._temp_i
                # _LOGGER.debug(
                #     "(%s) [get_option_state] street_num_i: %s",
                #     self._get_attr(CONF_NAME),
                #     self._street_num_i,
                # )
            self._temp_i += 1
            return out
        return None

    async def _async_compile_state_from_advanced_options(self) -> None:
        self._street_num_i += 1
        first: bool = True
        for i, out in enumerate(self._adv_options_state_list):
            if out is not None and out:
                out = out.strip()
                if first:
                    self._set_attr(ATTR_NATIVE_VALUE, str(out))
                    first = False
                else:
                    if i == self._street_i and i == self._street_num_i:
                        self._set_attr(
                            ATTR_NATIVE_VALUE,
                            f"{self._get_attr(ATTR_NATIVE_VALUE)} ",
                        )
                    else:
                        self._set_attr(
                            ATTR_NATIVE_VALUE,
                            f"{self._get_attr(ATTR_NATIVE_VALUE)}, ",
                        )
                    self._set_attr(
                        ATTR_NATIVE_VALUE,
                        f"{self._get_attr(ATTR_NATIVE_VALUE)}{out}",
                    )

        _LOGGER.debug(
            "(%s) New State from Advanced Display Options: %s",
            self._get_attr(CONF_NAME),
            self._get_attr(ATTR_NATIVE_VALUE),
        )

    async def _async_build_state_from_display_options(self) -> None:
        display_options: list[str] = self._get_attr_safe_list(ATTR_DISPLAY_OPTIONS_LIST)
        _LOGGER.debug(
            "(%s) Building State from Display Options: %s",
            self._get_attr(CONF_NAME),
            self._get_attr(ATTR_DISPLAY_OPTIONS),
        )

        def add_to_display(
            attr_key: str,
            option_key: str | None = None,
            condition: bool = True,
            require_in_display_options: bool = True,
        ) -> None:
            """Add attribute value to user_display if the conditions are met."""
            if (
                (not require_in_display_options or option_key in display_options)
                and not self._is_attr_blank(attr_key)
                and condition
            ):
                user_display.append(self._get_attr_safe_str(attr_key))

        user_display: list[str] = []

        # Add basic options
        add_to_display(option_key="driving", attr_key=ATTR_DRIVING)
        add_to_display(
            option_key="zone_name",
            attr_key=ATTR_DEVICETRACKER_ZONE_NAME,
            condition=await self._async_in_zone() or "do_not_show_not_home" not in display_options,
        )
        add_to_display(
            option_key="zone",
            attr_key=ATTR_DEVICETRACKER_ZONE,
            condition=await self._async_in_zone() or "do_not_show_not_home" not in display_options,
        )
        add_to_display("place_name", ATTR_PLACE_NAME)

        # Handle "place" and its sub-options
        if "place" in display_options:
            add_to_display(
                attr_key=ATTR_PLACE_NAME,
                condition=self._get_attr(ATTR_PLACE_NAME) != self._get_attr(ATTR_STREET),
                require_in_display_options=False,
            )
            add_to_display(
                attr_key=ATTR_PLACE_CATEGORY,
                condition=self._get_attr_safe_str(ATTR_PLACE_CATEGORY).lower() != "place",
                require_in_display_options=False,
            )
            add_to_display(
                attr_key=ATTR_PLACE_TYPE,
                condition=self._get_attr_safe_str(ATTR_PLACE_TYPE).lower() != "yes",
                require_in_display_options=False,
            )
            add_to_display(
                attr_key=ATTR_PLACE_NEIGHBOURHOOD,
                require_in_display_options=False,
            )
            add_to_display(
                attr_key=ATTR_STREET_NUMBER,
                require_in_display_options=False,
            )
            add_to_display(
                attr_key=ATTR_STREET,
                require_in_display_options=False,
            )
        else:
            add_to_display(option_key="street_number", attr_key=ATTR_STREET_NUMBER)
            add_to_display(option_key="street", attr_key=ATTR_STREET)

        # Add remaining location details
        for option_key, attr_key in {
            "city": ATTR_CITY,
            "county": ATTR_COUNTY,
            "state": ATTR_REGION,
            "region": ATTR_REGION,
            "postal_code": ATTR_POSTAL_CODE,
            "country": ATTR_COUNTRY,
            "formatted_address": ATTR_FORMATTED_ADDRESS,
        }.items():
            add_to_display(option_key=option_key, attr_key=attr_key)

        # Handle "do_not_reorder" option
        if "do_not_reorder" in display_options:
            user_display = []
            display_options.remove("do_not_reorder")
            for option in display_options:
                attr_key = (
                    "region"
                    if option == "state"
                    else "place_neighbourhood"
                    if option == "place_neighborhood"
                    else option
                )
                if not self._is_attr_blank(attr_key):
                    user_display.append(self._get_attr_safe_str(attr_key))

        # Set the final state
        if user_display:
            self._set_attr(ATTR_NATIVE_VALUE, ", ".join(user_display))
        _LOGGER.debug(
            "(%s) New State from Display Options: %s",
            self._get_attr(CONF_NAME),
            self._get_attr(ATTR_NATIVE_VALUE),
        )

    async def _async_get_extended_attr(self) -> None:
        if not self._is_attr_blank(ATTR_OSM_ID) and not self._is_attr_blank(ATTR_OSM_TYPE):
            if self._get_attr_safe_str(ATTR_OSM_TYPE).lower() == "node":
                osm_type_abbr = "N"
            elif self._get_attr_safe_str(ATTR_OSM_TYPE).lower() == "way":
                osm_type_abbr = "W"
            elif self._get_attr_safe_str(ATTR_OSM_TYPE).lower() == "relation":
                osm_type_abbr = "R"

            osm_details_url: str = (
                "https://nominatim.openstreetmap.org/lookup?osm_ids="
                f"{osm_type_abbr}{self._get_attr(ATTR_OSM_ID)}"
                "&format=json&addressdetails=1&extratags=1&namedetails=1"
                f"&email={
                    self._get_attr(CONF_API_KEY) if not self._is_attr_blank(CONF_API_KEY) else ''
                }"
                f"&accept-language={
                    self._get_attr(CONF_LANGUAGE) if not self._is_attr_blank(CONF_LANGUAGE) else ''
                }"
            )
            await self._hass.async_add_executor_job(
                self._get_dict_from_url,
                osm_details_url,
                "OpenStreetMaps Details",
                ATTR_OSM_DETAILS_DICT,
            )

            if not self._is_attr_blank(ATTR_OSM_DETAILS_DICT):
                osm_details_dict = self._get_attr_safe_dict(ATTR_OSM_DETAILS_DICT)
                _LOGGER.debug(
                    "(%s) OSM Details Dict: %s", self._get_attr(CONF_NAME), osm_details_dict
                )

                if (
                    "extratags" in osm_details_dict
                    and osm_details_dict.get("extratags") is not None
                    and "wikidata" in osm_details_dict.get("extratags", {})
                    and osm_details_dict.get("extratags", {}).get("wikidata") is not None
                ):
                    self._set_attr(
                        ATTR_WIKIDATA_ID,
                        osm_details_dict.get("extratags", {}).get("wikidata"),
                    )

                self._set_attr(ATTR_WIKIDATA_DICT, {})
                if not self._is_attr_blank(ATTR_WIKIDATA_ID):
                    wikidata_url: str = f"https://www.wikidata.org/wiki/Special:EntityData/{
                        self._get_attr(ATTR_WIKIDATA_ID)
                    }.json"
                    await self._hass.async_add_executor_job(
                        self._get_dict_from_url,
                        wikidata_url,
                        "Wikidata",
                        ATTR_WIKIDATA_DICT,
                    )

    async def _async_fire_event_data(self, prev_last_place_name: str) -> None:
        _LOGGER.debug("(%s) Building Event Data", self._get_attr(CONF_NAME))
        event_data: MutableMapping[str, Any] = {}
        if not self._is_attr_blank(CONF_NAME):
            event_data.update({"entity": self._get_attr(CONF_NAME)})
        if not self._is_attr_blank(ATTR_PREVIOUS_STATE):
            event_data.update({"from_state": self._get_attr(ATTR_PREVIOUS_STATE)})
        if not self._is_attr_blank(ATTR_NATIVE_VALUE):
            event_data.update({"to_state": self._get_attr(ATTR_NATIVE_VALUE)})

        for attr in EVENT_ATTRIBUTE_LIST:
            if not self._is_attr_blank(attr):
                event_data.update({attr: self._get_attr(attr)})

        if (
            not self._is_attr_blank(ATTR_LAST_PLACE_NAME)
            and self._get_attr(ATTR_LAST_PLACE_NAME) != prev_last_place_name
        ):
            event_data.update({ATTR_LAST_PLACE_NAME: self._get_attr(ATTR_LAST_PLACE_NAME)})

        if self._get_attr(CONF_EXTENDED_ATTR):
            for attr in EXTENDED_ATTRIBUTE_LIST:
                if not self._is_attr_blank(attr):
                    event_data.update({attr: self._get_attr(attr)})

        self._hass.bus.fire(EVENT_TYPE, event_data)
        _LOGGER.debug(
            "(%s) Event Details [event_type: %s_state_update]: %s",
            self._get_attr(CONF_NAME),
            DOMAIN,
            event_data,
        )
        _LOGGER.info(
            "(%s) Event Fired [event_type: %s_state_update]", self._get_attr(CONF_NAME), DOMAIN
        )

    def _write_sensor_to_json(self, name: str, filename: str) -> None:
        sensor_attributes: MutableMapping[str, Any] = copy.deepcopy(self._internal_attr)
        for k, v in sensor_attributes.items():
            if isinstance(v, (datetime)):
                # _LOGGER.debug("(%s) Removing Sensor Attribute: %s", self._get_attr(CONF_NAME), k)
                sensor_attributes.pop(k)
        # _LOGGER.debug("(%s) Sensor Attributes to Save: %s", self._get_attr(CONF_NAME), sensor_attributes)
        try:
            json_file_path: Path = Path(self._json_folder) / filename
            with json_file_path.open("w") as jsonfile:
                json.dump(sensor_attributes, jsonfile)
        except OSError as e:
            _LOGGER.debug(
                "(%s) OSError writing sensor to JSON (%s): %s: %s",
                name,
                filename,
                e.__class__.__qualname__,
                e,
            )

    async def _async_get_initial_last_place_name(self) -> None:
        _LOGGER.debug(
            "(%s) Previous State: %s",
            self._get_attr(CONF_NAME),
            self._get_attr(ATTR_PREVIOUS_STATE),
        )
        _LOGGER.debug(
            "(%s) Previous last_place_name: %s",
            self._get_attr(CONF_NAME),
            self._get_attr(ATTR_LAST_PLACE_NAME),
        )

        if not await self._async_in_zone():
            # Previously Not in a Zone
            if not self._is_attr_blank(ATTR_PLACE_NAME):
                # If place name is set
                self._set_attr(ATTR_LAST_PLACE_NAME, self._get_attr(ATTR_PLACE_NAME))
                _LOGGER.debug(
                    "(%s) Previous place is Place Name, last_place_name is set: %s",
                    self._get_attr(CONF_NAME),
                    self._get_attr(ATTR_LAST_PLACE_NAME),
                )
            else:
                # If blank, keep previous last_place_name
                _LOGGER.debug(
                    "(%s) Previous Place Name is None, keeping prior", self._get_attr(CONF_NAME)
                )
        else:
            # Previously In a Zone
            self._set_attr(
                ATTR_LAST_PLACE_NAME,
                self._get_attr(ATTR_DEVICETRACKER_ZONE_NAME),
            )
            _LOGGER.debug(
                "(%s) Previous Place is Zone: %s",
                self._get_attr(CONF_NAME),
                self._get_attr(ATTR_LAST_PLACE_NAME),
            )
        _LOGGER.debug(
            "(%s) last_place_name (Initial): %s",
            self._get_attr(CONF_NAME),
            self._get_attr(ATTR_LAST_PLACE_NAME),
        )

    async def _async_update_coordinates_and_distance(self) -> int:
        last_distance_traveled_m: float = self._get_attr_safe_float(ATTR_DISTANCE_FROM_HOME_M)
        proceed_with_update = 1
        # 0: False. 1: True. 2: False, but set direction of travel to stationary

        if not self._is_attr_blank(ATTR_LATITUDE) and not self._is_attr_blank(ATTR_LONGITUDE):
            self._set_attr(
                ATTR_LOCATION_CURRENT,
                f"{self._get_attr(ATTR_LATITUDE)},{self._get_attr(ATTR_LONGITUDE)}",
            )
        if not self._is_attr_blank(ATTR_LATITUDE_OLD) and not self._is_attr_blank(
            ATTR_LONGITUDE_OLD
        ):
            self._set_attr(
                ATTR_LOCATION_PREVIOUS,
                f"{self._get_attr(ATTR_LATITUDE_OLD)},{self._get_attr(ATTR_LONGITUDE_OLD)}",
            )
        if not self._is_attr_blank(ATTR_HOME_LATITUDE) and not self._is_attr_blank(
            ATTR_HOME_LONGITUDE
        ):
            self._set_attr(
                ATTR_HOME_LOCATION,
                f"{self._get_attr(ATTR_HOME_LATITUDE)},{self._get_attr(ATTR_HOME_LONGITUDE)}",
            )

        if (
            not self._is_attr_blank(ATTR_LATITUDE)
            and not self._is_attr_blank(ATTR_LONGITUDE)
            and not self._is_attr_blank(ATTR_HOME_LATITUDE)
            and not self._is_attr_blank(ATTR_HOME_LONGITUDE)
        ):
            self._set_attr(
                ATTR_DISTANCE_FROM_HOME_M,
                distance(
                    float(self._get_attr_safe_str(ATTR_LATITUDE)),
                    float(self._get_attr_safe_str(ATTR_LONGITUDE)),
                    float(self._get_attr_safe_str(ATTR_HOME_LATITUDE)),
                    float(self._get_attr_safe_str(ATTR_HOME_LONGITUDE)),
                ),
            )
            if not self._is_attr_blank(ATTR_DISTANCE_FROM_HOME_M):
                self._set_attr(
                    ATTR_DISTANCE_FROM_HOME_KM,
                    round(self._get_attr_safe_float(ATTR_DISTANCE_FROM_HOME_M) / 1000, 3),
                )
                self._set_attr(
                    ATTR_DISTANCE_FROM_HOME_MI,
                    round(self._get_attr_safe_float(ATTR_DISTANCE_FROM_HOME_M) / 1609, 3),
                )

            if not self._is_attr_blank(ATTR_LATITUDE_OLD) and not self._is_attr_blank(
                ATTR_LONGITUDE_OLD
            ):
                self._set_attr(
                    ATTR_DISTANCE_TRAVELED_M,
                    distance(
                        float(self._get_attr_safe_str(ATTR_LATITUDE)),
                        float(self._get_attr_safe_str(ATTR_LONGITUDE)),
                        float(self._get_attr_safe_str(ATTR_LATITUDE_OLD)),
                        float(self._get_attr_safe_str(ATTR_LONGITUDE_OLD)),
                    ),
                )
                if not self._is_attr_blank(ATTR_DISTANCE_TRAVELED_M):
                    self._set_attr(
                        ATTR_DISTANCE_TRAVELED_MI,
                        round(
                            self._get_attr_safe_float(ATTR_DISTANCE_TRAVELED_M) / 1609,
                            3,
                        ),
                    )

                if last_distance_traveled_m > self._get_attr_safe_float(ATTR_DISTANCE_FROM_HOME_M):
                    self._set_attr(ATTR_DIRECTION_OF_TRAVEL, "towards home")
                elif last_distance_traveled_m < self._get_attr_safe_float(
                    ATTR_DISTANCE_FROM_HOME_M
                ):
                    self._set_attr(ATTR_DIRECTION_OF_TRAVEL, "away from home")
                else:
                    self._set_attr(ATTR_DIRECTION_OF_TRAVEL, "stationary")
            else:
                self._set_attr(ATTR_DIRECTION_OF_TRAVEL, "stationary")
                self._set_attr(ATTR_DISTANCE_TRAVELED_M, 0)
                self._set_attr(ATTR_DISTANCE_TRAVELED_MI, 0)

            _LOGGER.debug(
                "(%s) Previous Location: %s",
                self._get_attr(CONF_NAME),
                self._get_attr(ATTR_LOCATION_PREVIOUS),
            )
            _LOGGER.debug(
                "(%s) Current Location: %s",
                self._get_attr(CONF_NAME),
                self._get_attr(ATTR_LOCATION_CURRENT),
            )
            _LOGGER.debug(
                "(%s) Home Location: %s",
                self._get_attr(CONF_NAME),
                self._get_attr(ATTR_HOME_LOCATION),
            )
            _LOGGER.info(
                "(%s) Distance from home [%s]: %s km",
                self._get_attr(CONF_NAME),
                self._get_attr_safe_str(CONF_HOME_ZONE).split(".")[1],
                self._get_attr(ATTR_DISTANCE_FROM_HOME_KM),
            )
            _LOGGER.info(
                "(%s) Travel Direction: %s",
                self._get_attr(CONF_NAME),
                self._get_attr(ATTR_DIRECTION_OF_TRAVEL),
            )
            _LOGGER.info(
                "(%s) Meters traveled since last update: %s",
                self._get_attr(CONF_NAME),
                round(self._get_attr_safe_float(ATTR_DISTANCE_TRAVELED_M), 1),
            )
        else:
            proceed_with_update = 0
            # 0: False. 1: True. 2: False, but set direction of travel to stationary
            _LOGGER.info(
                "(%s) Problem with updated lat/long, not performing update: "
                "old_latitude=%s, old_longitude=%s, "
                "new_latitude=%s, new_longitude=%s, "
                "home_latitude=%s, home_longitude=%s",
                self._get_attr(CONF_NAME),
                self._get_attr(ATTR_LATITUDE_OLD),
                self._get_attr(ATTR_LONGITUDE_OLD),
                self._get_attr(ATTR_LATITUDE),
                self._get_attr(ATTR_LONGITUDE),
                self._get_attr(ATTR_HOME_LATITUDE),
                self._get_attr(ATTR_HOME_LONGITUDE),
            )
        return proceed_with_update

    async def _async_finalize_last_place_name(self, prev_last_place_name: str) -> None:
        if self._get_attr(ATTR_INITIAL_UPDATE):
            self._set_attr(ATTR_LAST_PLACE_NAME, prev_last_place_name)
            _LOGGER.debug(
                "(%s) Runnining initial update after load, using prior last_place_name",
                self._get_attr(CONF_NAME),
            )
        elif self._get_attr(ATTR_LAST_PLACE_NAME) == self._get_attr(
            ATTR_PLACE_NAME
        ) or self._get_attr(ATTR_LAST_PLACE_NAME) == self._get_attr(ATTR_DEVICETRACKER_ZONE_NAME):
            # If current place name/zone are the same as previous, keep older last_place_name
            self._set_attr(ATTR_LAST_PLACE_NAME, prev_last_place_name)
            _LOGGER.debug(
                "(%s) Initial last_place_name is same as new: place_name=%s or devicetracker_zone_name=%s, "
                "keeping previous last_place_name",
                self._get_attr(CONF_NAME),
                self._get_attr(ATTR_PLACE_NAME),
                self._get_attr(ATTR_DEVICETRACKER_ZONE_NAME),
            )
        else:
            _LOGGER.debug("(%s) Keeping initial last_place_name", self._get_attr(CONF_NAME))
        _LOGGER.info(
            "(%s) last_place_name: %s",
            self._get_attr(CONF_NAME),
            self._get_attr(ATTR_LAST_PLACE_NAME),
        )

    async def _async_do_update(self, reason: str) -> None:
        """Get the latest data and updates the states."""
        _LOGGER.info(
            "(%s) Starting %s Update (Tracked Entity: %s)",
            self._get_attr(CONF_NAME),
            reason,
            self._get_attr(CONF_DEVICETRACKER_ID),
        )

        now: datetime = await self._get_current_time()
        previous_attr: MutableMapping[str, Any] = copy.deepcopy(self._internal_attr)

        await self._update_entity_name_and_cleanup()
        await self._update_previous_state()
        await self._update_old_coordinates()
        prev_last_place_name = self._get_attr_safe_str(ATTR_LAST_PLACE_NAME)

        # 0: False. 1: True. 2: False, but set direction of travel to stationary
        proceed_with_update: int = await self._check_device_tracker_and_update_coords()

        if proceed_with_update == 1:
            proceed_with_update = await self._determine_update_criteria()

        if proceed_with_update == 1:
            await self._process_osm_update(now=now)

            if await self._should_update_state(now=now):
                await self._handle_state_update(now=now, prev_last_place_name=prev_last_place_name)
            else:
                _LOGGER.info(
                    "(%s) No entity update needed, Previous State = New State",
                    self._get_attr(CONF_NAME),
                )
                await self._rollback_update(previous_attr, now, proceed_with_update)
        else:
            await self._rollback_update(previous_attr, now, proceed_with_update)

        self._set_attr(ATTR_LAST_UPDATED, now.isoformat(sep=" ", timespec="seconds"))
        _LOGGER.info("(%s) End of Update", self._get_attr(CONF_NAME))

    async def _should_update_state(self, now: datetime) -> bool:
        prev_state: str = self._get_attr_safe_str(ATTR_PREVIOUS_STATE)
        native_value: str = self._get_attr_safe_str(ATTR_NATIVE_VALUE)
        tracker_zone: str = self._get_attr_safe_str(ATTR_DEVICETRACKER_ZONE)

        if (
            (
                not self._is_attr_blank(ATTR_PREVIOUS_STATE)
                and not self._is_attr_blank(ATTR_NATIVE_VALUE)
                and prev_state.lower().strip() != native_value.lower().strip()
                and prev_state.replace(" ", "").lower().strip() != native_value.lower().strip()
                and prev_state.lower().strip() != tracker_zone.lower().strip()
            )
            or self._is_attr_blank(ATTR_PREVIOUS_STATE)
            or self._is_attr_blank(ATTR_NATIVE_VALUE)
            or self._get_attr(ATTR_INITIAL_UPDATE)
        ):
            return True
        return False

    async def _handle_state_update(self, now: datetime, prev_last_place_name: str) -> None:
        if self._get_attr(CONF_EXTENDED_ATTR):
            await self._async_get_extended_attr()
        self._set_attr(ATTR_SHOW_DATE, False)
        await self._async_cleanup_attributes()

        if not self._is_attr_blank(ATTR_NATIVE_VALUE):
            current_time: str = f"{now.hour:02}:{now.minute:02}"
            if self._get_attr(CONF_SHOW_TIME):
                state: str = await Places._async_clear_since_from_state(
                    self._get_attr_safe_str(ATTR_NATIVE_VALUE)
                )
                self._set_attr(ATTR_NATIVE_VALUE, f"{state[: 255 - 14]} (since {current_time})")
            else:
                self._set_attr(ATTR_NATIVE_VALUE, self._get_attr_safe_str(ATTR_NATIVE_VALUE)[:255])
            _LOGGER.info(
                "(%s) New State: %s",
                self._get_attr(CONF_NAME),
                self._get_attr(ATTR_NATIVE_VALUE),
            )
        else:
            self._clear_attr(ATTR_NATIVE_VALUE)
            _LOGGER.warning("(%s) New State is None", self._get_attr(CONF_NAME))

        if not self._is_attr_blank(ATTR_NATIVE_VALUE):
            self._attr_native_value = self._get_attr(ATTR_NATIVE_VALUE)
        else:
            self._attr_native_value = None

        await self._async_fire_event_data(prev_last_place_name=prev_last_place_name)
        self._set_attr(ATTR_INITIAL_UPDATE, False)
        await self._hass.async_add_executor_job(
            self._write_sensor_to_json,
            self._get_attr(CONF_NAME),
            self._get_attr(ATTR_JSON_FILENAME),
        )

    async def _rollback_update(
        self, previous_attr: MutableMapping[str, Any], now: datetime, proceed_with_update: int
    ) -> None:
        self._internal_attr = previous_attr
        _LOGGER.debug(
            "(%s) Reverting attributes back to before the update started", self._get_attr(CONF_NAME)
        )
        changed_diff_sec = await self._async_get_seconds_from_last_change(now=now)
        if (
            proceed_with_update == 2
            and self._get_attr(ATTR_DIRECTION_OF_TRAVEL) != "stationary"
            and changed_diff_sec >= 60
        ):
            await self._async_change_dot_to_stationary(now=now, changed_diff_sec=changed_diff_sec)
        if (
            self._get_attr(CONF_SHOW_TIME)
            and changed_diff_sec >= 86399
            and not self._get_attr(ATTR_SHOW_DATE)
        ):
            await self._async_change_show_time_to_date()

    async def _get_current_time(self) -> datetime:
        if self._hass.config.time_zone:
            return datetime.now(tz=ZoneInfo(str(self._hass.config.time_zone)))
        return datetime.now()

    async def _update_entity_name_and_cleanup(self) -> None:
        await self._async_check_for_updated_entity_name()
        await self._async_cleanup_attributes()

    async def _update_previous_state(self) -> None:
        if not self._is_attr_blank(ATTR_NATIVE_VALUE) and self._get_attr(CONF_SHOW_TIME):
            self._set_attr(
                ATTR_PREVIOUS_STATE,
                await Places._async_clear_since_from_state(
                    orig_state=self._get_attr_safe_str(ATTR_NATIVE_VALUE)
                ),
            )
        else:
            self._set_attr(ATTR_PREVIOUS_STATE, self._get_attr(ATTR_NATIVE_VALUE))

    async def _update_old_coordinates(self) -> None:
        if _is_float(self._get_attr(ATTR_LATITUDE)):
            self._set_attr(ATTR_LATITUDE_OLD, str(self._get_attr(ATTR_LATITUDE)))
        if _is_float(self._get_attr(ATTR_LONGITUDE)):
            self._set_attr(ATTR_LONGITUDE_OLD, str(self._get_attr(ATTR_LONGITUDE)))

    async def _check_device_tracker_and_update_coords(self) -> int:
        proceed_with_update: int = await self._async_is_devicetracker_set()
        _LOGGER.debug(
            "(%s) [is_devicetracker_set] proceed_with_update: %s",
            self._get_attr(CONF_NAME),
            proceed_with_update,
        )
        if proceed_with_update == 1:
            await self._update_coordinates()
            proceed_with_update = await self._async_get_gps_accuracy()
            _LOGGER.debug(
                "(%s) [is_devicetracker_set] proceed_with_update: %s",
                self._get_attr(CONF_NAME),
                proceed_with_update,
            )
        return proceed_with_update

    async def _update_coordinates(self) -> None:
        device_tracker = self._hass.states.get(self._get_attr(CONF_DEVICETRACKER_ID))
        if _is_float(device_tracker.attributes.get(CONF_LATITUDE)):
            self._set_attr(ATTR_LATITUDE, str(device_tracker.attributes.get(CONF_LATITUDE)))
        if _is_float(device_tracker.attributes.get(CONF_LONGITUDE)):
            self._set_attr(ATTR_LONGITUDE, str(device_tracker.attributes.get(CONF_LONGITUDE)))

    async def _determine_update_criteria(self) -> int:
        await self._async_get_initial_last_place_name()
        await self._async_get_zone_details()
        proceed_with_update = await self._async_update_coordinates_and_distance()
        _LOGGER.debug(
            "(%s) [update_coordinates_and_distance] proceed_with_update: %s",
            self._get_attr(CONF_NAME),
            proceed_with_update,
        )
        if proceed_with_update == 1:
            proceed_with_update = await self._async_determine_if_update_needed()
            _LOGGER.debug(
                "(%s) [determine_if_update_needed] proceed_with_update: %s",
                self._get_attr(CONF_NAME),
                proceed_with_update,
            )
        return proceed_with_update

    async def _process_osm_update(self, now: datetime) -> None:
        _LOGGER.info(
            "(%s) Meets criteria, proceeding with OpenStreetMap query",
            self._get_attr(CONF_NAME),
        )
        _LOGGER.info(
            "(%s) Tracked Entity Zone: %s",
            self._get_attr(CONF_NAME),
            self._get_attr(ATTR_DEVICETRACKER_ZONE),
        )

        await self._async_reset_attributes()
        await self._async_get_map_link()
        await self._query_osm_and_finalize(now=now)

    async def _query_osm_and_finalize(self, now: datetime) -> None:
        osm_url: str = await self._build_osm_url()
        await self._hass.async_add_executor_job(
            self._get_dict_from_url, osm_url, "OpenStreetMaps", ATTR_OSM_DICT
        )
        if not self._is_attr_blank(ATTR_OSM_DICT):
            await self._async_parse_osm_dict()
            await self._async_finalize_last_place_name(
                self._get_attr_safe_str(ATTR_LAST_PLACE_NAME)
            )
            await self._process_display_options()
            self._set_attr(ATTR_LAST_CHANGED, now.isoformat(sep=" ", timespec="seconds"))

    async def _process_display_options(self) -> None:
        display_options: list[str] = []
        if not self._is_attr_blank(ATTR_DISPLAY_OPTIONS):
            options_array: list[str] = self._get_attr_safe_str(ATTR_DISPLAY_OPTIONS).split(",")
            for option in options_array:
                display_options.extend([option.strip()])
        self._set_attr(ATTR_DISPLAY_OPTIONS_LIST, display_options)

        await self._async_get_driving_status()

        if "formatted_place" in display_options:
            await self._async_build_formatted_place()
            self._set_attr(
                ATTR_NATIVE_VALUE,
                self._get_attr(ATTR_FORMATTED_PLACE),
            )
            _LOGGER.debug(
                "(%s) New State using formatted_place: %s",
                self._get_attr(CONF_NAME),
                self._get_attr(ATTR_NATIVE_VALUE),
            )

        elif any(
            ext in (self._get_attr_safe_str(ATTR_DISPLAY_OPTIONS)) for ext in ["(", ")", "[", "]"]
        ):
            self._clear_attr(ATTR_DISPLAY_OPTIONS_LIST)
            display_options = []
            self._adv_options_state_list = []
            self._street_num_i = -1
            self._street_i = -1
            self._temp_i = 0
            _LOGGER.debug(
                "(%s) Initial Advanced Display Options: %s",
                self._get_attr(CONF_NAME),
                self._get_attr(ATTR_DISPLAY_OPTIONS),
            )

            await self._async_build_from_advanced_options(
                self._get_attr_safe_str(ATTR_DISPLAY_OPTIONS)
            )
            _LOGGER.debug(
                "(%s) Back from initial advanced build: %s",
                self._get_attr(CONF_NAME),
                self._adv_options_state_list,
            )
            await self._async_compile_state_from_advanced_options()
        elif not await self._async_in_zone():
            await self._async_build_state_from_display_options()
        elif (
            "zone" in display_options and not self._is_attr_blank(ATTR_DEVICETRACKER_ZONE)
        ) or self._is_attr_blank(ATTR_DEVICETRACKER_ZONE_NAME):
            self._set_attr(
                ATTR_NATIVE_VALUE,
                self._get_attr(ATTR_DEVICETRACKER_ZONE),
            )
            _LOGGER.debug(
                "(%s) New State from Tracked Entity Zone: %s",
                self._get_attr(CONF_NAME),
                self._get_attr(ATTR_NATIVE_VALUE),
            )
        elif not self._is_attr_blank(ATTR_DEVICETRACKER_ZONE_NAME):
            self._set_attr(
                ATTR_NATIVE_VALUE,
                self._get_attr(ATTR_DEVICETRACKER_ZONE_NAME),
            )
            _LOGGER.debug(
                "(%s) New State from Tracked Entity Zone Name: %s",
                self._get_attr(CONF_NAME),
                self._get_attr(ATTR_NATIVE_VALUE),
            )

    async def _build_osm_url(self) -> str:
        """Build the OpenStreetMap query URL."""
        base_url = "https://nominatim.openstreetmap.org/reverse?format=json"
        lat: str = self._get_attr_safe_str(ATTR_LATITUDE)
        lon: str = self._get_attr_safe_str(ATTR_LONGITUDE)
        lang: str = self._get_attr_safe_str(CONF_LANGUAGE)
        email: str = self._get_attr_safe_str(CONF_API_KEY)
        return f"{base_url}&lat={lat}&lon={lon}&accept-language={lang}&addressdetails=1&namedetails=1&zoom=18&limit=1&email={email}"

    async def _async_change_dot_to_stationary(self, now: datetime, changed_diff_sec: int) -> None:
        self._set_attr(ATTR_DIRECTION_OF_TRAVEL, "stationary")
        self._set_attr(ATTR_LAST_CHANGED, now.isoformat(sep=" ", timespec="seconds"))
        await self._hass.async_add_executor_job(
            self._write_sensor_to_json,
            self._get_attr(CONF_NAME),
            self._get_attr(ATTR_JSON_FILENAME),
        )
        _LOGGER.debug(
            "(%s) Updating direction of travel to stationary (Last changed %s seconds ago)",
            self._get_attr(CONF_NAME),
            int(changed_diff_sec),
        )

    async def _async_change_show_time_to_date(self) -> None:
        if not self._is_attr_blank(ATTR_NATIVE_VALUE) and self._get_attr(CONF_SHOW_TIME):
            if self._get_attr(CONF_DATE_FORMAT) == "dd/mm":
                dateformat = "%d/%m"
            else:
                dateformat = "%m/%d"
            mmddstring: str = (
                datetime.fromisoformat(self._get_attr_safe_str(ATTR_LAST_CHANGED))
                .strftime(f"{dateformat}")
                .replace(" ", "")[:5]
            )
            self._set_attr(
                ATTR_NATIVE_VALUE,
                f"{await Places._async_clear_since_from_state(self._get_attr_safe_str(ATTR_NATIVE_VALUE))} (since {mmddstring})",
            )

            if not self._is_attr_blank(ATTR_NATIVE_VALUE):
                self._attr_native_value = self._get_attr(ATTR_NATIVE_VALUE)
            else:
                self._attr_native_value = None
            self._set_attr(ATTR_SHOW_DATE, True)
            await self._hass.async_add_executor_job(
                self._write_sensor_to_json,
                self._get_attr(CONF_NAME),
                self._get_attr(ATTR_JSON_FILENAME),
            )
            _LOGGER.debug(
                "(%s) Updating state to show date instead of time since last change",
                self._get_attr(CONF_NAME),
            )
            _LOGGER.debug(
                "(%s) New State: %s", self._get_attr(CONF_NAME), self._get_attr(ATTR_NATIVE_VALUE)
            )

    async def _async_get_seconds_from_last_change(self, now: datetime) -> int:
        if self._is_attr_blank(ATTR_LAST_CHANGED):
            return 3600
        try:
            last_changed: datetime = datetime.fromisoformat(
                self._get_attr_safe_str(ATTR_LAST_CHANGED)
            )
        except (TypeError, ValueError) as e:
            _LOGGER.warning(
                "Error converting Last Changed date/time (%s) into datetime: %r",
                self._get_attr(ATTR_LAST_CHANGED),
                e,
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
                        "Error calculating the seconds between last change to now: %r", e
                    )
                    return 3600
            except OverflowError as e:
                _LOGGER.warning("Error calculating the seconds between last change to now: %r", e)
                return 3600
            return int(changed_diff_sec)

    async def _async_reset_attributes(self) -> None:
        """Reset sensor attributes."""
        for attr in RESET_ATTRIBUTE_LIST:
            self._clear_attr(attr)
        await self._async_cleanup_attributes()


class PlacesNoRecorder(Places):
    """Places Class without the HA Recorder."""

    _unrecorded_attributes = frozenset({MATCH_ALL})

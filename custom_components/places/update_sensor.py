"""Class to handle update logic for Places sensor."""

from __future__ import annotations

import asyncio
from collections.abc import MutableMapping
from datetime import datetime
import json
import logging
from typing import Any
from zoneinfo import ZoneInfo

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_FRIENDLY_NAME,
    ATTR_GPS_ACCURACY,
    CONF_API_KEY,
    CONF_FRIENDLY_NAME,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_NAME,
    CONF_ZONE,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant
from homeassistant.util.location import distance

from .const import (
    ATTR_ATTRIBUTES,
    ATTR_DEVICETRACKER_ZONE,
    ATTR_DEVICETRACKER_ZONE_NAME,
    ATTR_DIRECTION_OF_TRAVEL,
    ATTR_DISTANCE_FROM_HOME_KM,
    ATTR_DISTANCE_FROM_HOME_M,
    ATTR_DISTANCE_FROM_HOME_MI,
    ATTR_DISTANCE_TRAVELED_M,
    ATTR_DISTANCE_TRAVELED_MI,
    ATTR_HOME_LATITUDE,
    ATTR_HOME_LOCATION,
    ATTR_HOME_LONGITUDE,
    ATTR_INITIAL_UPDATE,
    ATTR_JSON_FILENAME,
    ATTR_JSON_FOLDER,
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
    ATTR_PLACE_NAME,
    ATTR_PREVIOUS_STATE,
    ATTR_SHOW_DATE,
    ATTR_WIKIDATA_DICT,
    ATTR_WIKIDATA_ID,
    CONF_DATE_FORMAT,
    CONF_DEVICETRACKER_ID,
    CONF_EXTENDED_ATTR,
    CONF_HOME_ZONE,
    CONF_LANGUAGE,
    CONF_MAP_PROVIDER,
    CONF_MAP_ZOOM,
    CONF_SHOW_TIME,
    CONF_USE_GPS,
    DOMAIN,
    EVENT_ATTRIBUTE_LIST,
    EVENT_TYPE,
    EXTENDED_ATTRIBUTE_LIST,
    OSM_CACHE,
    OSM_THROTTLE,
    OSM_THROTTLE_INTERVAL_SECONDS,
    RESET_ATTRIBUTE_LIST,
    VERSION,
)
from .helpers import clear_since_from_state, is_float, write_sensor_to_json
from .parse_osm import OSMParser
from .sensor import Places

_LOGGER = logging.getLogger(__name__)


class PlacesUpdater:
    """Handles update logic for Places sensor."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry, sensor: Places) -> None:
        """Initialize the updater with the sensor instance."""
        self.sensor = sensor
        self._config_entry: ConfigEntry = config_entry
        self._hass = hass

    async def do_update(self, reason: str, previous_attr: MutableMapping[str, Any]) -> None:
        """Get the latest data and updates the states."""
        _LOGGER.info(
            "(%s) Starting %s Update (Tracked Entity: %s)",
            self.sensor.get_attr(CONF_NAME),
            reason,
            self.sensor.get_attr(CONF_DEVICETRACKER_ID),
        )

        now: datetime = await self.get_current_time()

        await self.update_entity_name_and_cleanup()
        await self.update_previous_state()
        await self.update_old_coordinates()
        prev_last_place_name = self.sensor.get_attr_safe_str(ATTR_LAST_PLACE_NAME)

        proceed_with_update: int = await self.check_device_tracker_and_update_coords()

        if proceed_with_update == 1:
            proceed_with_update = await self.determine_update_criteria()

        if proceed_with_update == 1:
            await self.process_osm_update(now=now)

            if await self.should_update_state(now=now):
                await self.handle_state_update(now=now, prev_last_place_name=prev_last_place_name)
            else:
                _LOGGER.info(
                    "(%s) No entity update needed, Previous State = New State",
                    self.sensor.get_attr(CONF_NAME),
                )
                await self.rollback_update(previous_attr, now, proceed_with_update)
        else:
            await self.rollback_update(previous_attr, now, proceed_with_update)

        self.sensor.set_attr(ATTR_LAST_UPDATED, now.isoformat(sep=" ", timespec="seconds"))
        _LOGGER.info("(%s) End of Update", self.sensor.get_attr(CONF_NAME))

    async def handle_state_update(self, now: datetime, prev_last_place_name: str) -> None:
        """Handle the state update for the sensor."""
        if self.sensor.get_attr(CONF_EXTENDED_ATTR):
            await self.get_extended_attr()
        self.sensor.set_attr(ATTR_SHOW_DATE, False)
        await self.sensor.async_cleanup_attributes()

        if not self.sensor.is_attr_blank(ATTR_NATIVE_VALUE):
            current_time: str = f"{now.hour:02}:{now.minute:02}"
            if self.sensor.get_attr(CONF_SHOW_TIME):
                state: str = clear_since_from_state(
                    self.sensor.get_attr_safe_str(ATTR_NATIVE_VALUE)
                )
                self.sensor.set_native_value(value=f"{state[: 255 - 14]} (since {current_time})")
            else:
                self.sensor.set_native_value(
                    value=self.sensor.get_attr_safe_str(ATTR_NATIVE_VALUE)[:255]
                )
            _LOGGER.info(
                "(%s) New State: %s",
                self.sensor.get_attr(CONF_NAME),
                self.sensor.get_attr(ATTR_NATIVE_VALUE),
            )
        else:
            self.sensor.set_native_value(value=None)
            _LOGGER.warning("(%s) New State is None", self.sensor.get_attr(CONF_NAME))

        await self.fire_event_data(prev_last_place_name=prev_last_place_name)
        self.sensor.set_attr(ATTR_INITIAL_UPDATE, False)
        await self._hass.async_add_executor_job(
            write_sensor_to_json,
            self.sensor.get_internal_attr(),
            self.sensor.get_attr(CONF_NAME),
            self.sensor.get_attr(ATTR_JSON_FILENAME),
            self.sensor.get_attr(ATTR_JSON_FOLDER),
        )

    async def fire_event_data(self, prev_last_place_name: str) -> None:
        """Fire an event with the sensor's state update details."""
        _LOGGER.debug("(%s) Building Event Data", self.sensor.get_attr(CONF_NAME))
        event_data: MutableMapping[str, Any] = {}
        if not self.sensor.is_attr_blank(CONF_NAME):
            event_data.update({"entity": self.sensor.get_attr(CONF_NAME)})
        if not self.sensor.is_attr_blank(ATTR_PREVIOUS_STATE):
            event_data.update({"from_state": self.sensor.get_attr(ATTR_PREVIOUS_STATE)})
        if not self.sensor.is_attr_blank(ATTR_NATIVE_VALUE):
            event_data.update({"to_state": self.sensor.get_attr(ATTR_NATIVE_VALUE)})

        for attr in EVENT_ATTRIBUTE_LIST:
            if not self.sensor.is_attr_blank(attr):
                event_data.update({attr: self.sensor.get_attr(attr)})

        if (
            not self.sensor.is_attr_blank(ATTR_LAST_PLACE_NAME)
            and self.sensor.get_attr(ATTR_LAST_PLACE_NAME) != prev_last_place_name
        ):
            event_data.update({ATTR_LAST_PLACE_NAME: self.sensor.get_attr(ATTR_LAST_PLACE_NAME)})

        if self.sensor.get_attr(CONF_EXTENDED_ATTR):
            for attr in EXTENDED_ATTRIBUTE_LIST:
                if not self.sensor.is_attr_blank(attr):
                    event_data.update({attr: self.sensor.get_attr(attr)})

        self._hass.bus.fire(EVENT_TYPE, event_data)
        _LOGGER.debug(
            "(%s) Event Details [event_type: %s_state_update]: %s",
            self.sensor.get_attr(CONF_NAME),
            DOMAIN,
            event_data,
        )
        _LOGGER.info(
            "(%s) Event Fired [event_type: %s_state_update]",
            self.sensor.get_attr(CONF_NAME),
            DOMAIN,
        )

    async def get_current_time(self) -> datetime:
        """Get the current time, considering the Home Assistant time zone."""
        if self._hass.config.time_zone:
            return datetime.now(tz=ZoneInfo(str(self._hass.config.time_zone)))
        return datetime.now()

    async def update_entity_name_and_cleanup(self) -> None:
        """Update the entity name and clean up attributes."""
        await self.check_for_updated_entity_name()
        await self.sensor.async_cleanup_attributes()

    async def check_for_updated_entity_name(self) -> None:
        """Check if the entity name has changed and update it if necessary."""
        if hasattr(self.sensor, "entity_id") and self.sensor.entity_id is not None:
            # _LOGGER.debug("(%s) Entity ID: %s", self.sensor.get_attr(CONF_NAME), self.sensor._entity_id)
            config = dict(self._config_entry.data)
            if (
                self._hass.states.get(str(self.sensor.entity_id)) is not None
                and self._hass.states.get(str(self.sensor.entity_id)).attributes.get(
                    ATTR_FRIENDLY_NAME
                )
                is not None
                and self.sensor.get_attr(CONF_NAME)
                != self._hass.states.get(str(self.sensor.entity_id)).attributes.get(
                    ATTR_FRIENDLY_NAME
                )
            ):
                _LOGGER.debug(
                    "(%s) Sensor Name Changed. Updating Name to: %s",
                    self.sensor.get_attr(CONF_NAME),
                    self._hass.states.get(str(self.sensor.entity_id)).attributes.get(
                        ATTR_FRIENDLY_NAME
                    ),
                )
                self.sensor.set_attr(
                    CONF_NAME,
                    self._hass.states.get(str(self.sensor.entity_id)).attributes.get(
                        ATTR_FRIENDLY_NAME
                    ),
                )
                config.update({CONF_NAME: self.sensor.get_attr(CONF_NAME)})
                _LOGGER.debug(
                    "(%s) Updated Config Name: %s",
                    self.sensor.get_attr(CONF_NAME),
                    config.get(CONF_NAME),
                )
                self._hass.config_entries.async_update_entry(
                    self._config_entry,
                    data=config,
                    options=self._config_entry.options,
                )
                _LOGGER.debug(
                    "(%s) Updated ConfigEntry Name: %s",
                    self.sensor.get_attr(CONF_NAME),
                    self._config_entry.data.get(CONF_NAME),
                )

    async def update_previous_state(self) -> None:
        """Update the previous state attribute."""
        if not self.sensor.is_attr_blank(ATTR_NATIVE_VALUE) and self.sensor.get_attr(
            CONF_SHOW_TIME
        ):
            self.sensor.set_attr(
                ATTR_PREVIOUS_STATE,
                clear_since_from_state(orig_state=self.sensor.get_attr_safe_str(ATTR_NATIVE_VALUE)),
            )
        else:
            self.sensor.set_attr(ATTR_PREVIOUS_STATE, self.sensor.get_attr(ATTR_NATIVE_VALUE))

    async def update_old_coordinates(self) -> None:
        """Store old coordinates."""
        if is_float(self.sensor.get_attr(ATTR_LATITUDE)):
            self.sensor.set_attr(ATTR_LATITUDE_OLD, str(self.sensor.get_attr(ATTR_LATITUDE)))
        if is_float(self.sensor.get_attr(ATTR_LONGITUDE)):
            self.sensor.set_attr(ATTR_LONGITUDE_OLD, str(self.sensor.get_attr(ATTR_LONGITUDE)))

    async def check_device_tracker_and_update_coords(self) -> int:
        """Check if the device tracker is set and update coordinates if needed."""
        proceed_with_update: int = await self.is_devicetracker_set()
        _LOGGER.debug(
            "(%s) [check_device_tracker_and_update_coords] proceed_with_update: %s",
            self.sensor.get_attr(CONF_NAME),
            proceed_with_update,
        )
        if proceed_with_update == 1:
            await self.update_coordinates()
            proceed_with_update = await self.get_gps_accuracy()
            _LOGGER.debug(
                "(%s) [check_device_tracker_and_update_coords] proceed_with_update: %s",
                self.sensor.get_attr(CONF_NAME),
                proceed_with_update,
            )
        return proceed_with_update

    async def get_gps_accuracy(self) -> int:
        """Get the GPS accuracy from the device tracker."""
        if (
            self._hass.states.get(self.sensor.get_attr(CONF_DEVICETRACKER_ID))
            and self._hass.states.get(self.sensor.get_attr(CONF_DEVICETRACKER_ID)).attributes
            and ATTR_GPS_ACCURACY
            in self._hass.states.get(self.sensor.get_attr(CONF_DEVICETRACKER_ID)).attributes
            and self._hass.states.get(self.sensor.get_attr(CONF_DEVICETRACKER_ID)).attributes.get(
                ATTR_GPS_ACCURACY
            )
            is not None
            and is_float(
                self._hass.states.get(self.sensor.get_attr(CONF_DEVICETRACKER_ID)).attributes.get(
                    ATTR_GPS_ACCURACY
                )
            )
        ):
            self.sensor.set_attr(
                ATTR_GPS_ACCURACY,
                float(
                    self._hass.states.get(
                        self.sensor.get_attr(CONF_DEVICETRACKER_ID)
                    ).attributes.get(ATTR_GPS_ACCURACY)
                ),
            )
        else:
            _LOGGER.debug(
                "(%s) GPS Accuracy attribute not found in: %s",
                self.sensor.get_attr(CONF_NAME),
                self.sensor.get_attr(CONF_DEVICETRACKER_ID),
            )
        proceed_with_update = 1
        # 0: False. 1: True. 2: False, but set direction of travel to stationary

        if not self.sensor.is_attr_blank(ATTR_GPS_ACCURACY):
            if self.sensor.get_attr(CONF_USE_GPS) and self.sensor.get_attr(ATTR_GPS_ACCURACY) == 0:
                proceed_with_update = 0
                # 0: False. 1: True. 2: False, but set direction of travel to stationary
                _LOGGER.info(
                    "(%s) GPS Accuracy is 0.0, not performing update",
                    self.sensor.get_attr(CONF_NAME),
                )
            else:
                _LOGGER.debug(
                    "(%s) GPS Accuracy: %s",
                    self.sensor.get_attr(CONF_NAME),
                    round(self.sensor.get_attr_safe_float(ATTR_GPS_ACCURACY), 3),
                )
        return proceed_with_update

    async def update_coordinates(self) -> None:
        """Update the latitude and longitude attributes from the device tracker."""
        device_tracker = self._hass.states.get(self.sensor.get_attr(CONF_DEVICETRACKER_ID))
        if is_float(device_tracker.attributes.get(CONF_LATITUDE)):
            self.sensor.set_attr(ATTR_LATITUDE, str(device_tracker.attributes.get(CONF_LATITUDE)))
        if is_float(device_tracker.attributes.get(CONF_LONGITUDE)):
            self.sensor.set_attr(ATTR_LONGITUDE, str(device_tracker.attributes.get(CONF_LONGITUDE)))

    async def determine_update_criteria(self) -> int:
        """Determine if the update criteria are met."""
        await self.get_initial_last_place_name()
        await self.get_zone_details()
        proceed_with_update = await self.update_coordinates_and_distance()
        _LOGGER.debug(
            "(%s) [determine_update_criteria] proceed_with_update: %s",
            self.sensor.get_attr(CONF_NAME),
            proceed_with_update,
        )
        if proceed_with_update == 1:
            proceed_with_update = await self.determine_if_update_needed()
            _LOGGER.debug(
                "(%s) [determine_update_criteria] proceed_with_update: %s",
                self.sensor.get_attr(CONF_NAME),
                proceed_with_update,
            )
        return proceed_with_update

    async def get_initial_last_place_name(self) -> None:
        """Set the initial last place name based on the previous state."""
        _LOGGER.debug(
            "(%s) Previous State: %s",
            self.sensor.get_attr(CONF_NAME),
            self.sensor.get_attr(ATTR_PREVIOUS_STATE),
        )
        _LOGGER.debug(
            "(%s) Previous last_place_name: %s",
            self.sensor.get_attr(CONF_NAME),
            self.sensor.get_attr(ATTR_LAST_PLACE_NAME),
        )

        if not await self.sensor.in_zone():
            # Previously Not in a Zone
            if not self.sensor.is_attr_blank(ATTR_PLACE_NAME):
                # If place name is set
                self.sensor.set_attr(ATTR_LAST_PLACE_NAME, self.sensor.get_attr(ATTR_PLACE_NAME))
                _LOGGER.debug(
                    "(%s) Previous place is Place Name, last_place_name is set: %s",
                    self.sensor.get_attr(CONF_NAME),
                    self.sensor.get_attr(ATTR_LAST_PLACE_NAME),
                )
            else:
                # If blank, keep previous last_place_name
                _LOGGER.debug(
                    "(%s) Previous Place Name is None, keeping prior",
                    self.sensor.get_attr(CONF_NAME),
                )
        else:
            # Previously In a Zone
            self.sensor.set_attr(
                ATTR_LAST_PLACE_NAME,
                self.sensor.get_attr(ATTR_DEVICETRACKER_ZONE_NAME),
            )
            _LOGGER.debug(
                "(%s) Previous Place is Zone: %s",
                self.sensor.get_attr(CONF_NAME),
                self.sensor.get_attr(ATTR_LAST_PLACE_NAME),
            )
        _LOGGER.debug(
            "(%s) last_place_name (Initial): %s",
            self.sensor.get_attr(CONF_NAME),
            self.sensor.get_attr(ATTR_LAST_PLACE_NAME),
        )

    async def get_zone_details(self) -> None:
        """Get the zone details for the device tracker."""
        if self.sensor.get_attr_safe_str(CONF_DEVICETRACKER_ID).split(".")[0] != CONF_ZONE:
            self.sensor.set_attr(
                ATTR_DEVICETRACKER_ZONE,
                self._hass.states.get(self.sensor.get_attr(CONF_DEVICETRACKER_ID)).state,
            )
        if await self.sensor.in_zone():
            devicetracker_zone_name_state = None
            devicetracker_zone_id: str | None = self._hass.states.get(
                self.sensor.get_attr(CONF_DEVICETRACKER_ID)
            ).attributes.get(CONF_ZONE)
            if devicetracker_zone_id:
                devicetracker_zone_id = f"{CONF_ZONE}.{devicetracker_zone_id}"
                devicetracker_zone_name_state = self._hass.states.get(devicetracker_zone_id)
            # _LOGGER.debug("(%s) Tracked Entity Zone ID: %s", self.get_attr(CONF_NAME), devicetracker_zone_id)
            # _LOGGER.debug("(%s) Tracked Entity Zone Name State: %s", self.get_attr(CONF_NAME), devicetracker_zone_name_state)
            if devicetracker_zone_name_state:
                if devicetracker_zone_name_state.attributes.get(CONF_FRIENDLY_NAME):
                    self.sensor.set_attr(
                        ATTR_DEVICETRACKER_ZONE_NAME,
                        devicetracker_zone_name_state.attributes.get(CONF_FRIENDLY_NAME),
                    )
                else:
                    self.sensor.set_attr(
                        ATTR_DEVICETRACKER_ZONE_NAME, devicetracker_zone_name_state.name
                    )
            else:
                self.sensor.set_attr(
                    ATTR_DEVICETRACKER_ZONE_NAME,
                    self.sensor.get_attr(ATTR_DEVICETRACKER_ZONE),
                )

            if not self.sensor.is_attr_blank(ATTR_DEVICETRACKER_ZONE_NAME) and (
                self.sensor.get_attr_safe_str(ATTR_DEVICETRACKER_ZONE_NAME)
            ).lower() == self.sensor.get_attr(ATTR_DEVICETRACKER_ZONE_NAME):
                self.sensor.set_attr(
                    ATTR_DEVICETRACKER_ZONE_NAME,
                    self.sensor.get_attr_safe_str(ATTR_DEVICETRACKER_ZONE_NAME).title(),
                )
            _LOGGER.debug(
                "(%s) Tracked Entity Zone Name: %s",
                self.sensor.get_attr(CONF_NAME),
                self.sensor.get_attr(ATTR_DEVICETRACKER_ZONE_NAME),
            )
        else:
            _LOGGER.debug(
                "(%s) Tracked Entity Zone: %s",
                self.sensor.get_attr(CONF_NAME),
                self.sensor.get_attr(ATTR_DEVICETRACKER_ZONE),
            )
            self.sensor.set_attr(
                ATTR_DEVICETRACKER_ZONE_NAME,
                self.sensor.get_attr(ATTR_DEVICETRACKER_ZONE),
            )

    async def process_osm_update(self, now: datetime) -> None:
        """Process the OpenStreetMap update if criteria are met."""
        _LOGGER.info(
            "(%s) Meets criteria, proceeding with OpenStreetMap query",
            self.sensor.get_attr(CONF_NAME),
        )
        _LOGGER.info(
            "(%s) Tracked Entity Zone: %s",
            self.sensor.get_attr(CONF_NAME),
            self.sensor.get_attr(ATTR_DEVICETRACKER_ZONE),
        )

        await self.async_reset_attributes()
        await self.get_map_link()
        await self.query_osm_and_finalize(now=now)

    async def get_map_link(self) -> None:
        """Get the map link based on the configured map provider."""
        if self.sensor.get_attr(CONF_MAP_PROVIDER) == "google":
            self.sensor.set_attr(
                ATTR_MAP_LINK,
                (
                    "https://maps.google.com/?q="
                    f"{self.sensor.get_attr(ATTR_LOCATION_CURRENT)}"
                    f"&ll={self.sensor.get_attr(ATTR_LOCATION_CURRENT)}"
                    f"&z={self.sensor.get_attr(CONF_MAP_ZOOM)}"
                ),
            )
        elif self.sensor.get_attr(CONF_MAP_PROVIDER) == "osm":
            self.sensor.set_attr(
                ATTR_MAP_LINK,
                (
                    "https://www.openstreetmap.org/?mlat="
                    f"{self.sensor.get_attr(ATTR_LATITUDE)}"
                    f"&mlon={self.sensor.get_attr(ATTR_LONGITUDE)}"
                    f"#map={self.sensor.get_attr(CONF_MAP_ZOOM)}/"
                    f"{self.sensor.get_attr_safe_str(ATTR_LATITUDE)[:8]}/"
                    f"{self.sensor.get_attr_safe_str(ATTR_LONGITUDE)[:9]}"
                ),
            )
        else:
            self.sensor.set_attr(
                ATTR_MAP_LINK,
                (
                    "https://maps.apple.com/?q="
                    f"{self.sensor.get_attr(ATTR_LOCATION_CURRENT)}"
                    f"&z={self.sensor.get_attr(CONF_MAP_ZOOM)}"
                ),
            )
        _LOGGER.debug(
            "(%s) Map Link Type: %s",
            self.sensor.get_attr(CONF_NAME),
            self.sensor.get_attr(CONF_MAP_PROVIDER),
        )
        _LOGGER.debug(
            "(%s) Map Link URL: %s",
            self.sensor.get_attr(CONF_NAME),
            self.sensor.get_attr(ATTR_MAP_LINK),
        )

    async def async_reset_attributes(self) -> None:
        """Reset sensor attributes."""
        for attr in RESET_ATTRIBUTE_LIST:
            self.sensor.clear_attr(attr)
        await self.sensor.async_cleanup_attributes()

    async def query_osm_and_finalize(self, now: datetime) -> None:
        """Query OpenStreetMap and finalize the last place name."""
        osm_url: str = await self.build_osm_url()
        await self.get_dict_from_url(url=osm_url, name="OpenStreetMaps", dict_name=ATTR_OSM_DICT)
        if not self.sensor.is_attr_blank(ATTR_OSM_DICT):
            parser = OSMParser(sensor=self.sensor)
            await parser.parse_osm_dict()
            await parser.finalize_last_place_name(
                self.sensor.get_attr_safe_str(ATTR_LAST_PLACE_NAME)
            )
            await self.sensor.process_display_options()
            self.sensor.set_attr(ATTR_LAST_CHANGED, now.isoformat(sep=" ", timespec="seconds"))

    async def should_update_state(self, now: datetime) -> bool:
        """Determine if the state should be updated based on previous and current values."""
        prev_state: str = self.sensor.get_attr_safe_str(ATTR_PREVIOUS_STATE)
        native_value: str = self.sensor.get_attr_safe_str(ATTR_NATIVE_VALUE)
        tracker_zone: str = self.sensor.get_attr_safe_str(ATTR_DEVICETRACKER_ZONE)

        if (
            (
                not self.sensor.is_attr_blank(ATTR_PREVIOUS_STATE)
                and not self.sensor.is_attr_blank(ATTR_NATIVE_VALUE)
                and prev_state.lower().strip() != native_value.lower().strip()
                and prev_state.replace(" ", "").lower().strip() != native_value.lower().strip()
                and prev_state.lower().strip() != tracker_zone.lower().strip()
            )
            or self.sensor.is_attr_blank(ATTR_PREVIOUS_STATE)
            or self.sensor.is_attr_blank(ATTR_NATIVE_VALUE)
            or self.sensor.get_attr(ATTR_INITIAL_UPDATE)
        ):
            return True
        return False

    async def rollback_update(
        self, previous_attr: MutableMapping[str, Any], now: datetime, proceed_with_update: int
    ) -> None:
        """Rollback the update if conditions are not met."""
        await self.sensor.restore_previous_attr(previous_attr)
        _LOGGER.debug(
            "(%s) Reverting attributes back to before the update started",
            self.sensor.get_attr(CONF_NAME),
        )
        changed_diff_sec = await self.get_seconds_from_last_change(now=now)
        if (
            proceed_with_update == 2
            and self.sensor.get_attr(ATTR_DIRECTION_OF_TRAVEL) != "stationary"
            and changed_diff_sec >= 60
        ):
            await self.change_dot_to_stationary(now=now, changed_diff_sec=changed_diff_sec)
        if (
            self.sensor.get_attr(CONF_SHOW_TIME)
            and changed_diff_sec >= 86399
            and not self.sensor.get_attr(ATTR_SHOW_DATE)
        ):
            await self.change_show_time_to_date()

    async def build_osm_url(self) -> str:
        """Build the OpenStreetMap query URL."""
        base_url = "https://nominatim.openstreetmap.org/reverse?format=json"
        lat = self.sensor.get_attr(ATTR_LATITUDE)
        lon = self.sensor.get_attr(ATTR_LONGITUDE)
        lang = self.sensor.get_attr(CONF_LANGUAGE) or "en"
        email = self.sensor.get_attr(CONF_API_KEY) or ""
        return f"{base_url}&lat={lat}&lon={lon}&accept-language={lang}&addressdetails=1&namedetails=1&zoom=18&limit=1&email={email}"

    async def get_extended_attr(self) -> None:
        """Get extended attributes from OpenStreetMap and Wikidata."""
        if not self.sensor.is_attr_blank(ATTR_OSM_ID) and not self.sensor.is_attr_blank(
            ATTR_OSM_TYPE
        ):
            if self.sensor.get_attr_safe_str(ATTR_OSM_TYPE).lower() == "node":
                osm_type_abbr = "N"
            elif self.sensor.get_attr_safe_str(ATTR_OSM_TYPE).lower() == "way":
                osm_type_abbr = "W"
            elif self.sensor.get_attr_safe_str(ATTR_OSM_TYPE).lower() == "relation":
                osm_type_abbr = "R"
            else:
                _LOGGER.warning(
                    "(%s) Unknown OSM type: %s",
                    self.sensor.get_attr(CONF_NAME),
                    self.sensor.get_attr(ATTR_OSM_TYPE)
                )
                return

            osm_details_url: str = (
                "https://nominatim.openstreetmap.org/lookup?osm_ids="
                f"{osm_type_abbr}{self.sensor.get_attr(ATTR_OSM_ID)}"
                "&format=json&addressdetails=1&extratags=1&namedetails=1"
                f"&email={
                    self.sensor.get_attr(CONF_API_KEY)
                    if not self.sensor.is_attr_blank(CONF_API_KEY)
                    else ''
                }"
                f"&accept-language={
                    self.sensor.get_attr(CONF_LANGUAGE)
                    if not self.sensor.is_attr_blank(CONF_LANGUAGE)
                    else ''
                }"
            )
            await self.get_dict_from_url(
                url=osm_details_url,
                name="OpenStreetMaps Details",
                dict_name=ATTR_OSM_DETAILS_DICT,
            )

            if not self.sensor.is_attr_blank(ATTR_OSM_DETAILS_DICT):
                osm_details_dict = self.sensor.get_attr_safe_dict(ATTR_OSM_DETAILS_DICT)
                _LOGGER.debug(
                    "(%s) OSM Details Dict: %s", self.sensor.get_attr(CONF_NAME), osm_details_dict
                )

                if (
                    "extratags" in osm_details_dict
                    and osm_details_dict.get("extratags") is not None
                    and "wikidata" in osm_details_dict.get("extratags", {})
                    and osm_details_dict.get("extratags", {}).get("wikidata") is not None
                ):
                    self.sensor.set_attr(
                        ATTR_WIKIDATA_ID,
                        osm_details_dict.get("extratags", {}).get("wikidata"),
                    )

                self.sensor.set_attr(ATTR_WIKIDATA_DICT, {})
                if not self.sensor.is_attr_blank(ATTR_WIKIDATA_ID):
                    wikidata_url: str = f"https://www.wikidata.org/wiki/Special:EntityData/{
                        self.sensor.get_attr(ATTR_WIKIDATA_ID)
                    }.json"
                    await self.get_dict_from_url(
                        url=wikidata_url,
                        name="Wikidata",
                        dict_name=ATTR_WIKIDATA_DICT,
                    )

    async def get_dict_from_url(self, url: str, name: str, dict_name: str) -> None:
        """Fetch a dictionary from a URL and store it in the sensor's attributes."""
        osm_cache = self._hass.data[DOMAIN][OSM_CACHE]
        if url in osm_cache:
            self.sensor.set_attr(dict_name, osm_cache[url])
            _LOGGER.debug(
                "(%s) %s data loaded from cache (Cache size: %s)",
                self.sensor.get_attr(CONF_NAME),
                name,
                len(osm_cache),
            )
            return

        throttle = self._hass.data[DOMAIN][OSM_THROTTLE]
        async with throttle["lock"]:
            now = asyncio.get_running_loop().time()
            wait_time = max(0, OSM_THROTTLE_INTERVAL_SECONDS - (now - throttle["last_query"]))
            if wait_time > 0:
                await asyncio.sleep(wait_time)
            throttle["last_query"] = asyncio.get_running_loop().time()

            _LOGGER.info("(%s) Requesting data for %s", self.sensor.get_attr(CONF_NAME), name)
            _LOGGER.debug("(%s) %s URL: %s", self.sensor.get_attr(CONF_NAME), name, url)
            self.sensor.set_attr(dict_name, {})
            headers: dict[str, str] = {
                "user-agent": f"Mozilla/5.0 (Home Assistant) {DOMAIN}/{VERSION}"
            }
            get_dict = None

            try:
                async with (
                    aiohttp.ClientSession(headers=headers) as session,
                    session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response,
                ):
                    get_json_input = await response.text()
                    _LOGGER.debug(
                        "(%s) %s Response: %s",
                        self.sensor.get_attr(CONF_NAME),
                        name,
                        get_json_input,
                    )
                    try:
                        get_dict = json.loads(get_json_input)
                    except json.decoder.JSONDecodeError as e:
                        _LOGGER.warning(
                            "(%s) JSON Decode Error with %s info [%s: %s]: %s",
                            self.sensor.get_attr(CONF_NAME),
                            name,
                            type(e).__name__,
                            e,
                            get_json_input,
                        )
                        return
            except (aiohttp.ClientError, TimeoutError, OSError) as e:
                _LOGGER.warning(
                    "(%s) Error connecting to %s [%s: %s]: %s",
                    self.sensor.get_attr(CONF_NAME),
                    name,
                    type(e).__name__,
                    e,
                    url,
                )
                return

            if get_dict is None:
                return

            if "error_message" in get_dict:
                _LOGGER.warning(
                    "(%s) An error occurred contacting the web service for %s: %s",
                    self.sensor.get_attr(CONF_NAME),
                    name,
                    get_dict.get("error_message"),
                )
                return

            if (
                isinstance(get_dict, list)
                and len(get_dict) == 1
                and isinstance(get_dict[0], MutableMapping)
            ):
                self.sensor.set_attr(dict_name, get_dict[0])
                osm_cache[url] = get_dict[0]
                return

            self.sensor.set_attr(dict_name, get_dict)
            osm_cache[url] = get_dict
            return

    async def determine_if_update_needed(self) -> int:
        """Determine if an update is needed based on current and previous state."""
        proceed_with_update = 1
        sensor = self.sensor

        if sensor.get_attr(ATTR_INITIAL_UPDATE):
            _LOGGER.info("(%s) Performing Initial Update for user", sensor.get_attr(CONF_NAME))
            return 1

        if sensor.is_attr_blank(ATTR_NATIVE_VALUE) or (
            isinstance(sensor.get_attr(ATTR_NATIVE_VALUE), str)
            and sensor.get_attr_safe_str(ATTR_NATIVE_VALUE).lower()
            in {"none", STATE_UNKNOWN, STATE_UNAVAILABLE}
        ):
            _LOGGER.info(
                "(%s) Previous State is Unknown, performing update", sensor.get_attr(CONF_NAME)
            )
            return 1

        if sensor.get_attr(ATTR_LOCATION_CURRENT) == sensor.get_attr(ATTR_LOCATION_PREVIOUS):
            _LOGGER.info(
                "(%s) Not performing update because coordinates are identical",
                sensor.get_attr(CONF_NAME),
            )
            return 2

        if int(sensor.get_attr_safe_float(ATTR_DISTANCE_TRAVELED_M)) < 10:
            _LOGGER.info(
                "(%s) Not performing update, distance traveled from last update is less than 10 m (%s m)",
                sensor.get_attr(CONF_NAME),
                round(sensor.get_attr_safe_float(ATTR_DISTANCE_TRAVELED_M), 1),
            )
            return 2

        return proceed_with_update

    async def update_coordinates_and_distance(self) -> int:
        """Update coordinates and calculate distances."""
        last_distance_traveled_m: float = self.sensor.get_attr_safe_float(ATTR_DISTANCE_FROM_HOME_M)
        proceed_with_update = 1
        # 0: False. 1: True. 2: False, but set direction of travel to stationary

        if not self.sensor.is_attr_blank(ATTR_LATITUDE) and not self.sensor.is_attr_blank(
            ATTR_LONGITUDE
        ):
            self.sensor.set_attr(
                ATTR_LOCATION_CURRENT,
                f"{self.sensor.get_attr(ATTR_LATITUDE)},{self.sensor.get_attr(ATTR_LONGITUDE)}",
            )
        if not self.sensor.is_attr_blank(ATTR_LATITUDE_OLD) and not self.sensor.is_attr_blank(
            ATTR_LONGITUDE_OLD
        ):
            self.sensor.set_attr(
                ATTR_LOCATION_PREVIOUS,
                f"{self.sensor.get_attr(ATTR_LATITUDE_OLD)},{self.sensor.get_attr(ATTR_LONGITUDE_OLD)}",
            )
        if not self.sensor.is_attr_blank(ATTR_HOME_LATITUDE) and not self.sensor.is_attr_blank(
            ATTR_HOME_LONGITUDE
        ):
            self.sensor.set_attr(
                ATTR_HOME_LOCATION,
                f"{self.sensor.get_attr(ATTR_HOME_LATITUDE)},{self.sensor.get_attr(ATTR_HOME_LONGITUDE)}",
            )

        if (
            not self.sensor.is_attr_blank(ATTR_LATITUDE)
            and not self.sensor.is_attr_blank(ATTR_LONGITUDE)
            and not self.sensor.is_attr_blank(ATTR_HOME_LATITUDE)
            and not self.sensor.is_attr_blank(ATTR_HOME_LONGITUDE)
        ):
            self.sensor.set_attr(
                ATTR_DISTANCE_FROM_HOME_M,
                distance(
                    float(self.sensor.get_attr_safe_str(ATTR_LATITUDE)),
                    float(self.sensor.get_attr_safe_str(ATTR_LONGITUDE)),
                    float(self.sensor.get_attr_safe_str(ATTR_HOME_LATITUDE)),
                    float(self.sensor.get_attr_safe_str(ATTR_HOME_LONGITUDE)),
                ),
            )
            if not self.sensor.is_attr_blank(ATTR_DISTANCE_FROM_HOME_M):
                self.sensor.set_attr(
                    ATTR_DISTANCE_FROM_HOME_KM,
                    round(self.sensor.get_attr_safe_float(ATTR_DISTANCE_FROM_HOME_M) / 1000, 3),
                )
                self.sensor.set_attr(
                    ATTR_DISTANCE_FROM_HOME_MI,
                    round(self.sensor.get_attr_safe_float(ATTR_DISTANCE_FROM_HOME_M) / 1609, 3),
                )

            if not self.sensor.is_attr_blank(ATTR_LATITUDE_OLD) and not self.sensor.is_attr_blank(
                ATTR_LONGITUDE_OLD
            ):
                self.sensor.set_attr(
                    ATTR_DISTANCE_TRAVELED_M,
                    distance(
                        float(self.sensor.get_attr_safe_str(ATTR_LATITUDE)),
                        float(self.sensor.get_attr_safe_str(ATTR_LONGITUDE)),
                        float(self.sensor.get_attr_safe_str(ATTR_LATITUDE_OLD)),
                        float(self.sensor.get_attr_safe_str(ATTR_LONGITUDE_OLD)),
                    ),
                )
                if not self.sensor.is_attr_blank(ATTR_DISTANCE_TRAVELED_M):
                    self.sensor.set_attr(
                        ATTR_DISTANCE_TRAVELED_MI,
                        round(
                            self.sensor.get_attr_safe_float(ATTR_DISTANCE_TRAVELED_M) / 1609,
                            3,
                        ),
                    )

                if last_distance_traveled_m > self.sensor.get_attr_safe_float(
                    ATTR_DISTANCE_FROM_HOME_M
                ):
                    self.sensor.set_attr(ATTR_DIRECTION_OF_TRAVEL, "towards home")
                elif last_distance_traveled_m < self.sensor.get_attr_safe_float(
                    ATTR_DISTANCE_FROM_HOME_M
                ):
                    self.sensor.set_attr(ATTR_DIRECTION_OF_TRAVEL, "away from home")
                else:
                    self.sensor.set_attr(ATTR_DIRECTION_OF_TRAVEL, "stationary")
            else:
                self.sensor.set_attr(ATTR_DIRECTION_OF_TRAVEL, "stationary")
                self.sensor.set_attr(ATTR_DISTANCE_TRAVELED_M, 0)
                self.sensor.set_attr(ATTR_DISTANCE_TRAVELED_MI, 0)

            _LOGGER.debug(
                "(%s) Previous Location: %s",
                self.sensor.get_attr(CONF_NAME),
                self.sensor.get_attr(ATTR_LOCATION_PREVIOUS),
            )
            _LOGGER.debug(
                "(%s) Current Location: %s",
                self.sensor.get_attr(CONF_NAME),
                self.sensor.get_attr(ATTR_LOCATION_CURRENT),
            )
            _LOGGER.debug(
                "(%s) Home Location: %s",
                self.sensor.get_attr(CONF_NAME),
                self.sensor.get_attr(ATTR_HOME_LOCATION),
            )
            _LOGGER.info(
                "(%s) Distance from home [%s]: %s km",
                self.sensor.get_attr(CONF_NAME),
                self.sensor.get_attr_safe_str(CONF_HOME_ZONE).split(".")[1],
                self.sensor.get_attr(ATTR_DISTANCE_FROM_HOME_KM),
            )
            _LOGGER.info(
                "(%s) Travel Direction: %s",
                self.sensor.get_attr(CONF_NAME),
                self.sensor.get_attr(ATTR_DIRECTION_OF_TRAVEL),
            )
            _LOGGER.info(
                "(%s) Meters traveled since last update: %s",
                self.sensor.get_attr(CONF_NAME),
                round(self.sensor.get_attr_safe_float(ATTR_DISTANCE_TRAVELED_M), 1),
            )
        else:
            proceed_with_update = 0
            # 0: False. 1: True. 2: False, but set direction of travel to stationary
            _LOGGER.info(
                "(%s) Problem with updated lat/long, not performing update: "
                "old_latitude=%s, old_longitude=%s, "
                "new_latitude=%s, new_longitude=%s, "
                "home_latitude=%s, home_longitude=%s",
                self.sensor.get_attr(CONF_NAME),
                self.sensor.get_attr(ATTR_LATITUDE_OLD),
                self.sensor.get_attr(ATTR_LONGITUDE_OLD),
                self.sensor.get_attr(ATTR_LATITUDE),
                self.sensor.get_attr(ATTR_LONGITUDE),
                self.sensor.get_attr(ATTR_HOME_LATITUDE),
                self.sensor.get_attr(ATTR_HOME_LONGITUDE),
            )
        return proceed_with_update

    async def get_seconds_from_last_change(self, now: datetime) -> int:
        """Calculate the seconds since the last change."""
        if self.sensor.is_attr_blank(ATTR_LAST_CHANGED):
            return 3600
        try:
            last_changed: datetime = datetime.fromisoformat(
                self.sensor.get_attr_safe_str(ATTR_LAST_CHANGED)
            )
        except (TypeError, ValueError) as e:
            _LOGGER.warning(
                "Error converting Last Changed date/time (%s) into datetime: %r",
                self.sensor.get_attr(ATTR_LAST_CHANGED),
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

    async def change_show_time_to_date(self) -> None:
        """Change the display from time to date if conditions are met."""
        if not self.sensor.is_attr_blank(ATTR_NATIVE_VALUE) and self.sensor.get_attr(
            CONF_SHOW_TIME
        ):
            if self.sensor.get_attr(CONF_DATE_FORMAT) == "dd/mm":
                dateformat = "%d/%m"
            else:
                dateformat = "%m/%d"
            mmddstring: str = (
                datetime.fromisoformat(self.sensor.get_attr_safe_str(ATTR_LAST_CHANGED))
                .strftime(f"{dateformat}")
                .replace(" ", "")[:5]
            )

            cleared_state = clear_since_from_state(self.sensor.get_attr_safe_str(ATTR_NATIVE_VALUE))
            self.sensor.set_native_value(
                value=f"{cleared_state} (since {mmddstring})"
            )
            self.sensor.set_attr(ATTR_SHOW_DATE, True)
            await self._hass.async_add_executor_job(
                write_sensor_to_json,
                self.sensor.get_internal_attr(),
                self.sensor.get_attr(CONF_NAME),
                self.sensor.get_attr(ATTR_JSON_FILENAME),
                self.sensor.get_attr(ATTR_JSON_FOLDER),
            )
            _LOGGER.debug(
                "(%s) Updating state to show date instead of time since last change",
                self.sensor.get_attr(CONF_NAME),
            )
            _LOGGER.debug(
                "(%s) New State: %s",
                self.sensor.get_attr(CONF_NAME),
                self.sensor.get_attr(ATTR_NATIVE_VALUE),
            )

    async def change_dot_to_stationary(self, now: datetime, changed_diff_sec: int) -> None:
        """Change the direction of travel to stationary if conditions are met."""
        self.sensor.set_attr(ATTR_DIRECTION_OF_TRAVEL, "stationary")
        self.sensor.set_attr(ATTR_LAST_CHANGED, now.isoformat(sep=" ", timespec="seconds"))
        await self._hass.async_add_executor_job(
            write_sensor_to_json,
            self.sensor.get_internal_attr(),
            self.sensor.get_attr(CONF_NAME),
            self.sensor.get_attr(ATTR_JSON_FILENAME),
            self.sensor.get_attr(ATTR_JSON_FOLDER),
        )
        _LOGGER.debug(
            "(%s) Updating direction of travel to stationary (Last changed %s seconds ago)",
            self.sensor.get_attr(CONF_NAME),
            int(changed_diff_sec),
        )

    async def is_devicetracker_set(self) -> int:
        """Check if the device tracker is set and available."""
        proceed_with_update = 0
        # 0: False. 1: True. 2: False, but set direction of travel to stationary

        if (
            self.sensor.is_attr_blank(CONF_DEVICETRACKER_ID)
            or self._hass.states.get(self.sensor.get_attr(CONF_DEVICETRACKER_ID)) is None
            or (
                isinstance(
                    self._hass.states.get(self.sensor.get_attr(CONF_DEVICETRACKER_ID)),
                    str,
                )
                and self._hass.states.get(self.sensor.get_attr(CONF_DEVICETRACKER_ID)).lower()
                in {"none", STATE_UNKNOWN, STATE_UNAVAILABLE}
            )
        ):
            if self.sensor.warn_if_device_tracker_prob or self.sensor.get_attr(ATTR_INITIAL_UPDATE):
                _LOGGER.warning(
                    "(%s) Tracked Entity (%s) "
                    "is not set or is not available. Not Proceeding with Update",
                    self.sensor.get_attr(CONF_NAME),
                    self.sensor.get_attr(CONF_DEVICETRACKER_ID),
                )
                self.sensor.warn_if_device_tracker_prob = False
            else:
                _LOGGER.info(
                    "(%s) Tracked Entity (%s) "
                    "is not set or is not available. Not Proceeding with Update",
                    self.sensor.get_attr(CONF_NAME),
                    self.sensor.get_attr(CONF_DEVICETRACKER_ID),
                )
            return 0
            # 0: False. 1: True. 2: False, but set direction of travel to stationary
        if (
            hasattr(
                self._hass.states.get(self.sensor.get_attr(CONF_DEVICETRACKER_ID)),
                ATTR_ATTRIBUTES,
            )
            and CONF_LATITUDE
            in self._hass.states.get(self.sensor.get_attr(CONF_DEVICETRACKER_ID)).attributes
            and CONF_LONGITUDE
            in self._hass.states.get(self.sensor.get_attr(CONF_DEVICETRACKER_ID)).attributes
            and self._hass.states.get(self.sensor.get_attr(CONF_DEVICETRACKER_ID)).attributes.get(
                CONF_LATITUDE
            )
            is not None
            and self._hass.states.get(self.sensor.get_attr(CONF_DEVICETRACKER_ID)).attributes.get(
                CONF_LONGITUDE
            )
            is not None
            and is_float(
                self._hass.states.get(self.sensor.get_attr(CONF_DEVICETRACKER_ID)).attributes.get(
                    CONF_LATITUDE
                )
            )
            and is_float(
                self._hass.states.get(self.sensor.get_attr(CONF_DEVICETRACKER_ID)).attributes.get(
                    CONF_LONGITUDE
                )
            )
        ):
            self.sensor.warn_if_device_tracker_prob = True
            proceed_with_update = 1
            # 0: False. 1: True. 2: False, but set direction of travel to stationary
        else:
            if self.sensor.warn_if_device_tracker_prob or self.sensor.get_attr(ATTR_INITIAL_UPDATE):
                _LOGGER.warning(
                    "(%s) Tracked Entity (%s) "
                    "Latitude/Longitude is not set or is not a number. Not Proceeding with Update.",
                    self.sensor.get_attr(CONF_NAME),
                    self.sensor.get_attr(CONF_DEVICETRACKER_ID),
                )
                self.sensor.warn_if_device_tracker_prob = False
            else:
                _LOGGER.info(
                    "(%s) Tracked Entity (%s) "
                    "Latitude/Longitude is not set or is not a number. Not Proceeding with Update.",
                    self.sensor.get_attr(CONF_NAME),
                    self.sensor.get_attr(CONF_DEVICETRACKER_ID),
                )
            _LOGGER.debug(
                "(%s) Tracked Entity (%s) details: %s",
                self.sensor.get_attr(CONF_NAME),
                self.sensor.get_attr(CONF_DEVICETRACKER_ID),
                self._hass.states.get(self.sensor.get_attr(CONF_DEVICETRACKER_ID)),
            )
            return 0
            # 0: False. 1: True. 2: False, but set direction of travel to stationary
        return proceed_with_update

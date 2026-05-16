"""Update pipeline for Places sensors and external geocoding lookups."""

from __future__ import annotations

from collections.abc import MutableMapping
from datetime import UTC, datetime
import logging
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_FRIENDLY_NAME,
    ATTR_GPS_ACCURACY,
    CONF_API_KEY,
    CONF_FRIENDLY_NAME,
    CONF_NAME,
    CONF_ZONE,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant

from .const import (
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
    RESET_ATTRIBUTE_LIST,
    UpdateStatus,
)
from .helpers import clear_since_from_state, is_float, safe_truncate, write_sensor_to_json
from .location import CoordinatePair, LocationSnapshot, direction_of_travel
from .osm_client import OSMClient
from .parse_osm import OSMParser
from .tracker import TrackerSnapshot, TrackerStatus

if TYPE_CHECKING:
    from .sensor import Places

_LOGGER = logging.getLogger(__name__)


class PlacesUpdater:
    """Coordinate tracker validation, geocoding, state rendering, and persistence."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry, sensor: Places) -> None:
        """Initialize an updater for a Places sensor.

        Args:
            hass: Home Assistant instance.
            config_entry: Config entry backing the sensor.
            sensor: Places sensor whose attributes and state will be updated.
        """
        self.sensor = sensor
        self._config_entry: ConfigEntry = config_entry
        self._hass = hass
        self._osm_client = OSMClient(hass=hass, sensor_name=str(sensor.get_attr(CONF_NAME)))

    async def do_update(self, reason: str, previous_attr: MutableMapping[str, Any]) -> None:
        """Run one complete update attempt.

        Args:
            reason: Human-readable trigger reason used in logs.
            previous_attr: Attribute snapshot captured before the update, used
                for rollback when criteria fail or the rendered state is
                unchanged.
        """
        _LOGGER.info(
            "(%s) Starting %s Update (Tracked Entity: %s)",
            self.sensor.get_attr(CONF_NAME),
            reason,
            self.sensor.get_attr(CONF_DEVICETRACKER_ID),
        )

        now: datetime = await self.get_current_time()

        await self.update_entity_name_and_cleanup()
        self._osm_client.update_sensor_name(str(self.sensor.get_attr(CONF_NAME)))
        await self.update_previous_state()
        await self.update_old_coordinates()
        prev_last_place_name = self.sensor.get_attr_safe_str(ATTR_LAST_PLACE_NAME)

        proceed_with_update: UpdateStatus = await self.check_device_tracker_and_update_coords()

        if proceed_with_update == UpdateStatus.PROCEED:
            proceed_with_update = await self.determine_update_criteria()

        if proceed_with_update == UpdateStatus.PROCEED:
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
        """Finalize a successful update and persist the new sensor state.

        Args:
            now: Update timestamp in the HA timezone.
            prev_last_place_name: Last-place value from before this update,
                used to decide event payload contents.
        """
        if self.sensor.get_attr(CONF_EXTENDED_ATTR):
            await self.get_extended_attr()
        self.sensor.set_attr(ATTR_SHOW_DATE, False)
        await self.sensor.async_cleanup_attributes()

        if not self.sensor.is_attr_blank(ATTR_NATIVE_VALUE):
            current_time: str = f"{now.hour:02}:{now.minute:02}"
            if self.sensor.get_attr(CONF_SHOW_TIME):
                time_suffix = f" (since {current_time})"
                max_state_length = 255 - len(time_suffix)
                state: str = clear_since_from_state(
                    self.sensor.get_attr_safe_str(ATTR_NATIVE_VALUE)
                )
                self.sensor.set_native_value(value=f"{state[:max_state_length]}{time_suffix}")
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
            self.sensor.get_attr_safe_str(CONF_NAME),
            self.sensor.get_attr_safe_str(ATTR_JSON_FILENAME),
            self.sensor.get_attr_safe_str(ATTR_JSON_FOLDER),
        )

    async def fire_event_data(self, prev_last_place_name: str) -> None:
        """Fire the Places state-update event with changed display attributes.

        Args:
            prev_last_place_name: Last-place value captured before this update.
        """
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
        """Return the current time in Home Assistant's configured timezone.

        Returns:
            Timezone-aware current datetime.
        """
        if self._hass.config.time_zone:
            return datetime.now(tz=ZoneInfo(str(self._hass.config.time_zone)))
        return datetime.now(tz=UTC)

    async def update_entity_name_and_cleanup(self) -> None:
        """Synchronize renamed entities and drop blank attributes."""
        await self.check_for_updated_entity_name()
        await self.sensor.async_cleanup_attributes()

    async def check_for_updated_entity_name(self) -> None:
        """Copy a changed friendly name back into the config entry."""
        if not hasattr(self.sensor, "entity_id") or self.sensor.entity_id is None:
            return

        entity_state = self._hass.states.get(str(self.sensor.entity_id))
        if entity_state is None:
            return

        new_name = entity_state.attributes.get(ATTR_FRIENDLY_NAME)
        if new_name is None or new_name == self.sensor.get_attr(CONF_NAME):
            return

        _LOGGER.debug(
            "(%s) Sensor Name Changed. Updating Name to: %s",
            self.sensor.get_attr(CONF_NAME),
            new_name,
        )

        self.sensor.set_attr(CONF_NAME, new_name)
        config = dict(self._config_entry.data)
        config.update({CONF_NAME: new_name})

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
        """Store the previous rendered state before recalculating the sensor."""
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
        """Snapshot current coordinates as old coordinates before replacement."""
        if is_float(self.sensor.get_attr(ATTR_LATITUDE)):
            self.sensor.set_attr(ATTR_LATITUDE_OLD, self.sensor.get_attr_safe_float(ATTR_LATITUDE))
        if is_float(self.sensor.get_attr(ATTR_LONGITUDE)):
            self.sensor.set_attr(
                ATTR_LONGITUDE_OLD, self.sensor.get_attr_safe_float(ATTR_LONGITUDE)
            )

    async def check_device_tracker_and_update_coords(self) -> UpdateStatus:
        """Validate the tracker and refresh coordinates before geocoding.

        Returns:
            ``PROCEED`` when tracker data is usable, otherwise an update skip
            status.
        """
        proceed_with_update: UpdateStatus = await self.is_devicetracker_set()
        _LOGGER.debug(
            "(%s) [check_device_tracker_and_update_coords] proceed_with_update: %s",
            self.sensor.get_attr(CONF_NAME),
            proceed_with_update,
        )
        if proceed_with_update == UpdateStatus.PROCEED:
            await self.update_coordinates()
            proceed_with_update = await self.get_gps_accuracy()
            _LOGGER.debug(
                "(%s) [check_device_tracker_and_update_coords] proceed_with_update: %s",
                self.sensor.get_attr(CONF_NAME),
                proceed_with_update,
            )
        return proceed_with_update

    async def get_gps_accuracy(self) -> UpdateStatus:
        """Read GPS accuracy and optionally skip zero-accuracy GPS updates.

        Returns:
            ``SKIP`` when GPS mode is enabled and accuracy is zero, otherwise
            ``PROCEED``.
        """
        tracker_state = self._hass.states.get(self.sensor.get_attr(CONF_DEVICETRACKER_ID))
        if (
            tracker_state
            and hasattr(tracker_state, "attributes")
            and tracker_state.attributes
            and ATTR_GPS_ACCURACY in tracker_state.attributes
            and tracker_state.attributes.get(ATTR_GPS_ACCURACY) is not None
            and is_float(tracker_state.attributes.get(ATTR_GPS_ACCURACY))
        ):
            self.sensor.set_attr(
                ATTR_GPS_ACCURACY,
                float(tracker_state.attributes.get(ATTR_GPS_ACCURACY)),
            )
        else:
            _LOGGER.debug(
                "(%s) GPS Accuracy attribute not found in: %s",
                self.sensor.get_attr(CONF_NAME),
                self.sensor.get_attr(CONF_DEVICETRACKER_ID),
            )
        proceed_with_update = UpdateStatus.PROCEED

        if not self.sensor.is_attr_blank(ATTR_GPS_ACCURACY):
            if self.sensor.get_attr(CONF_USE_GPS) and self.sensor.get_attr(ATTR_GPS_ACCURACY) == 0:
                proceed_with_update = UpdateStatus.SKIP
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
        """Copy latitude and longitude from the tracked entity state."""
        tracker_id = self.sensor.get_attr(CONF_DEVICETRACKER_ID)
        tracker_snapshot = TrackerSnapshot.from_hass(self._hass, tracker_id)
        if tracker_snapshot.status in {
            TrackerStatus.MISSING_ENTITY_ID,
            TrackerStatus.NOT_FOUND,
            TrackerStatus.UNAVAILABLE,
        }:
            _LOGGER.warning(
                "(%s) Device tracker entity not found: %s",
                self.sensor.get_attr(CONF_NAME),
                tracker_id,
            )
            return
        if tracker_snapshot.status == TrackerStatus.OK and tracker_snapshot.latitude is not None:
            self.sensor.set_attr(ATTR_LATITUDE, tracker_snapshot.latitude)
        if tracker_snapshot.status == TrackerStatus.OK and tracker_snapshot.longitude is not None:
            self.sensor.set_attr(ATTR_LONGITUDE, tracker_snapshot.longitude)

    async def determine_update_criteria(self) -> UpdateStatus:
        """Run zone, distance, and movement checks for this update.

        Returns:
            Status indicating whether the update should continue or be skipped.
        """
        await self.get_initial_last_place_name()
        await self.get_zone_details()
        proceed_with_update = await self.update_coordinates_and_distance()
        _LOGGER.debug(
            "(%s) [determine_update_criteria] proceed_with_update: %s",
            self.sensor.get_attr(CONF_NAME),
            proceed_with_update,
        )
        if proceed_with_update == UpdateStatus.PROCEED:
            proceed_with_update = await self.determine_if_update_needed()
            _LOGGER.debug(
                "(%s) [determine_update_criteria] proceed_with_update: %s",
                self.sensor.get_attr(CONF_NAME),
                proceed_with_update,
            )
        return proceed_with_update

    async def get_initial_last_place_name(self) -> None:
        """Set the pre-update last-place value from the old place or zone."""
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
        """Store the tracked entity's zone state and friendly zone name."""
        if self.sensor.get_attr_safe_str(CONF_DEVICETRACKER_ID).split(".")[0] != CONF_ZONE:
            self.sensor.set_attr(
                ATTR_DEVICETRACKER_ZONE,
                (
                    self._hass.states.get(self.sensor.get_attr(CONF_DEVICETRACKER_ID)).state
                    if self._hass.states.get(self.sensor.get_attr(CONF_DEVICETRACKER_ID))
                    is not None
                    else STATE_UNKNOWN
                ),
            )
        if await self.sensor.in_zone():
            devicetracker_zone_name_state = None
            state = self._hass.states.get(self.sensor.get_attr(CONF_DEVICETRACKER_ID))
            devicetracker_zone_id: str | None = None
            if state is not None:
                devicetracker_zone_id = state.attributes.get(CONF_ZONE)
            if devicetracker_zone_id:
                devicetracker_zone_id = f"{CONF_ZONE}.{devicetracker_zone_id}"
                devicetracker_zone_name_state = self._hass.states.get(devicetracker_zone_id)
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
        """Reset transient attributes, build links, and query OSM.

        Args:
            now: Update timestamp to store as ``last_changed`` when geocoding
                succeeds.
        """
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
        """Build the configured map-provider URL for the current coordinates."""
        if self.sensor.get_attr(CONF_MAP_PROVIDER) == "google":
            params = {
                "q": self.sensor.get_attr(ATTR_LOCATION_CURRENT),
                "ll": self.sensor.get_attr(ATTR_LOCATION_CURRENT),
                "z": self.sensor.get_attr(CONF_MAP_ZOOM),
            }
            url = f"https://maps.google.com/?{urlencode(params)}"
            self.sensor.set_attr(ATTR_MAP_LINK, url)
        elif self.sensor.get_attr(CONF_MAP_PROVIDER) == "osm":
            lat_str = safe_truncate(self.sensor.get_attr_safe_float(ATTR_LATITUDE), 8)
            lon_str = safe_truncate(self.sensor.get_attr_safe_float(ATTR_LONGITUDE), 9)
            params = {
                "mlat": self.sensor.get_attr_safe_float(ATTR_LATITUDE),
                "mlon": self.sensor.get_attr_safe_float(ATTR_LONGITUDE),
            }
            osm_url = f"https://www.openstreetmap.org/?{urlencode(params)}"
            osm_url += f"#map={self.sensor.get_attr(CONF_MAP_ZOOM)}/{lat_str}/{lon_str}"
            self.sensor.set_attr(ATTR_MAP_LINK, osm_url)
        else:
            params = {
                "q": self.sensor.get_attr(ATTR_LOCATION_CURRENT),
                "z": self.sensor.get_attr(CONF_MAP_ZOOM),
            }
            url = f"https://maps.apple.com/?{urlencode(params)}"
            self.sensor.set_attr(ATTR_MAP_LINK, url)
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
        """Clear transient attributes before parsing fresh geocoding data."""
        for attr in RESET_ATTRIBUTE_LIST:
            self.sensor.clear_attr(attr)
        await self.sensor.async_cleanup_attributes()

    async def query_osm_and_finalize(self, now: datetime) -> None:
        """Fetch reverse-geocode data and render the display state.

        Args:
            now: Update timestamp to store when OSM returned usable data.
        """
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
        """Return whether the rendered state should replace the prior state.

        Args:
            now: Update timestamp. Reserved for future time-based criteria.

        Returns:
            ``True`` for initial updates, blank previous/current states, or a
            meaningful state change.
        """
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
        self,
        previous_attr: MutableMapping[str, Any],
        now: datetime,
        proceed_with_update: UpdateStatus,
    ) -> None:
        """Restore prior attributes and perform time-based skipped-update adjustments.

        Args:
            previous_attr: Attribute snapshot from before the update started.
            now: Current update timestamp.
            proceed_with_update: Status that caused the update to stop.
        """
        await self.sensor.restore_previous_attr(previous_attr)
        _LOGGER.debug(
            "(%s) Reverting attributes back to before the update started",
            self.sensor.get_attr(CONF_NAME),
        )
        changed_diff_sec = await self.get_seconds_from_last_change(now=now)
        if (
            proceed_with_update == UpdateStatus.SKIP_SET_STATIONARY
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
        """Build the Nominatim reverse-geocode URL for current coordinates.

        Returns:
            Fully encoded Nominatim reverse lookup URL.
        """
        return OSMClient.reverse_url(
            self.sensor.get_attr_safe_float(ATTR_LATITUDE),
            self.sensor.get_attr_safe_float(ATTR_LONGITUDE),
            self.sensor.get_attr(CONF_LANGUAGE) or "",
            self.sensor.get_attr(CONF_API_KEY) or "",
        )

    async def get_extended_attr(self) -> None:
        """Fetch optional OSM lookup details and related Wikidata payloads."""
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
                    self.sensor.get_attr(ATTR_OSM_TYPE),
                )
                return

            osm_details_url: str = OSMClient.details_url(
                osm_type_abbr=osm_type_abbr,
                osm_id=self.sensor.get_attr(ATTR_OSM_ID),
                language=self.sensor.get_attr(CONF_LANGUAGE) or "",
                email=self.sensor.get_attr(CONF_API_KEY) or "",
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
                    wikidata_url: str = OSMClient.wikidata_url(
                        self.sensor.get_attr(ATTR_WIKIDATA_ID)
                    )
                    await self.get_dict_from_url(
                        url=wikidata_url,
                        name="Wikidata",
                        dict_name=ATTR_WIKIDATA_DICT,
                    )

    async def get_dict_from_url(self, url: str, name: str, dict_name: str) -> None:
        """Fetch JSON with shared throttling and cache it on the HA instance.

        Args:
            url: Absolute URL to request.
            name: Human-readable service name used in logs.
            dict_name: Sensor attribute that receives the parsed JSON mapping.
        """
        get_dict = await self._osm_client.get_json(url=url, name=name)
        self.sensor.set_attr(dict_name, get_dict if get_dict is not None else {})
        if get_dict is not None:
            return

        if url in self._hass.data[DOMAIN][OSM_CACHE]:
            return

        # Ensure no stale key survives when no payload was produced.
        self._hass.data[DOMAIN][OSM_CACHE].pop(url, None)

    async def determine_if_update_needed(self) -> UpdateStatus:
        """Decide whether movement since the last update warrants geocoding.

        Returns:
            ``PROCEED`` for initial/unknown/moved states, or
            ``SKIP_SET_STATIONARY`` when the entity has not moved enough.
        """
        proceed_with_update = UpdateStatus.PROCEED
        sensor = self.sensor

        if sensor.get_attr(ATTR_INITIAL_UPDATE):
            _LOGGER.info("(%s) Performing Initial Update for user", sensor.get_attr(CONF_NAME))
            return UpdateStatus.PROCEED

        if sensor.is_attr_blank(ATTR_NATIVE_VALUE) or (
            isinstance(sensor.get_attr(ATTR_NATIVE_VALUE), str)
            and sensor.get_attr_safe_str(ATTR_NATIVE_VALUE).lower()
            in {"none", STATE_UNKNOWN, STATE_UNAVAILABLE}
        ):
            _LOGGER.info(
                "(%s) Previous State is Unknown, performing update", sensor.get_attr(CONF_NAME)
            )
            return UpdateStatus.PROCEED

        if sensor.get_attr(ATTR_LOCATION_CURRENT) == sensor.get_attr(ATTR_LOCATION_PREVIOUS):
            _LOGGER.info(
                "(%s) Not performing update because coordinates are identical",
                sensor.get_attr(CONF_NAME),
            )
            return UpdateStatus.SKIP_SET_STATIONARY

        if int(sensor.get_attr_safe_float(ATTR_DISTANCE_TRAVELED_M)) < 10:
            _LOGGER.info(
                "(%s) Not performing update, distance traveled from last update is "
                "less than 10 m (%s m)",
                sensor.get_attr(CONF_NAME),
                round(sensor.get_attr_safe_float(ATTR_DISTANCE_TRAVELED_M), 1),
            )
            return UpdateStatus.SKIP_SET_STATIONARY

        return proceed_with_update

    async def update_location_attributes(self) -> None:
        """Store current, previous, and home coordinates as ``lat,lon`` strings."""
        if not self.sensor.is_attr_blank(ATTR_LATITUDE) and not self.sensor.is_attr_blank(
            ATTR_LONGITUDE
        ):
            current = CoordinatePair(
                latitude=self.sensor.get_attr_safe_float(ATTR_LATITUDE),
                longitude=self.sensor.get_attr_safe_float(ATTR_LONGITUDE),
            )
            self.sensor.set_attr(ATTR_LOCATION_CURRENT, current.as_location())
        if not self.sensor.is_attr_blank(ATTR_LATITUDE_OLD) and not self.sensor.is_attr_blank(
            ATTR_LONGITUDE_OLD
        ):
            previous = CoordinatePair(
                latitude=self.sensor.get_attr_safe_float(ATTR_LATITUDE_OLD),
                longitude=self.sensor.get_attr_safe_float(ATTR_LONGITUDE_OLD),
            )
            self.sensor.set_attr(ATTR_LOCATION_PREVIOUS, previous.as_location())
        if not self.sensor.is_attr_blank(ATTR_HOME_LATITUDE) and not self.sensor.is_attr_blank(
            ATTR_HOME_LONGITUDE
        ):
            home = CoordinatePair(
                latitude=self.sensor.get_attr_safe_float(ATTR_HOME_LATITUDE),
                longitude=self.sensor.get_attr_safe_float(ATTR_HOME_LONGITUDE),
            )
            self.sensor.set_attr(ATTR_HOME_LOCATION, home.as_location())

    async def calculate_distances(self) -> None:
        """Calculate distance from home in meters, kilometers, and miles."""
        if (
            not self.sensor.is_attr_blank(ATTR_LATITUDE)
            and not self.sensor.is_attr_blank(ATTR_LONGITUDE)
            and not self.sensor.is_attr_blank(ATTR_HOME_LATITUDE)
            and not self.sensor.is_attr_blank(ATTR_HOME_LONGITUDE)
        ):
            location_snapshot = LocationSnapshot(
                current=CoordinatePair(
                    latitude=self.sensor.get_attr_safe_float(ATTR_LATITUDE),
                    longitude=self.sensor.get_attr_safe_float(ATTR_LONGITUDE),
                ),
                home=CoordinatePair(
                    latitude=self.sensor.get_attr_safe_float(ATTR_HOME_LATITUDE),
                    longitude=self.sensor.get_attr_safe_float(ATTR_HOME_LONGITUDE),
                ),
            )
            location_snapshot.calculate()
            self.sensor.set_attr(
                ATTR_DISTANCE_FROM_HOME_M,
                location_snapshot.distance_from_home_m,
            )
            if not self.sensor.is_attr_blank(ATTR_DISTANCE_FROM_HOME_M):
                self.sensor.set_attr(
                    ATTR_DISTANCE_FROM_HOME_KM,
                    location_snapshot.distance_from_home_km,
                )
                self.sensor.set_attr(
                    ATTR_DISTANCE_FROM_HOME_MI,
                    location_snapshot.distance_from_home_mi,
                )

    async def calculate_travel_distance(self) -> None:
        """Calculate distance traveled since the previous coordinates."""
        if not self.sensor.is_attr_blank(ATTR_LATITUDE_OLD) and not self.sensor.is_attr_blank(
            ATTR_LONGITUDE_OLD
        ):
            location_snapshot = LocationSnapshot(
                current=CoordinatePair(
                    latitude=self.sensor.get_attr_safe_float(ATTR_LATITUDE),
                    longitude=self.sensor.get_attr_safe_float(ATTR_LONGITUDE),
                ),
                previous=CoordinatePair(
                    latitude=self.sensor.get_attr_safe_float(ATTR_LATITUDE_OLD),
                    longitude=self.sensor.get_attr_safe_float(ATTR_LONGITUDE_OLD),
                ),
            )
            location_snapshot.calculate()
            self.sensor.set_attr(
                ATTR_DISTANCE_TRAVELED_M,
                location_snapshot.distance_traveled_m,
            )
            if not self.sensor.is_attr_blank(ATTR_DISTANCE_TRAVELED_M):
                self.sensor.set_attr(
                    ATTR_DISTANCE_TRAVELED_MI,
                    location_snapshot.distance_traveled_mi,
                )
        else:
            self.sensor.set_attr(ATTR_DIRECTION_OF_TRAVEL, "stationary")
            self.sensor.set_attr(ATTR_DISTANCE_TRAVELED_M, 0)
            self.sensor.set_attr(ATTR_DISTANCE_TRAVELED_MI, 0)

    async def determine_direction_of_travel(self, last_distance_traveled_m: float) -> None:
        """Classify movement relative to home as towards, away, or stationary.

        Args:
            last_distance_traveled_m: Prior distance-from-home value captured
                before recalculating distances.
        """
        if not self.sensor.is_attr_blank(ATTR_DISTANCE_TRAVELED_M):
            self.sensor.set_attr(
                ATTR_DIRECTION_OF_TRAVEL,
                direction_of_travel(
                    previous_distance_from_home_m=last_distance_traveled_m,
                    distance_from_home_m=self.sensor.get_attr_safe_float(ATTR_DISTANCE_FROM_HOME_M),
                ),
            )
        else:
            self.sensor.set_attr(ATTR_DIRECTION_OF_TRAVEL, "stationary")

    async def update_coordinates_and_distance(self) -> UpdateStatus:
        """Refresh derived coordinate, distance, and direction attributes.

        Returns:
            ``PROCEED`` when current and home coordinates are all usable,
            otherwise ``SKIP``.
        """
        last_distance_traveled_m: float = self.sensor.get_attr_safe_float(ATTR_DISTANCE_FROM_HOME_M)
        proceed_with_update = UpdateStatus.PROCEED

        await self.update_location_attributes()
        await self.calculate_distances()
        await self.calculate_travel_distance()
        await self.determine_direction_of_travel(last_distance_traveled_m)

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

        if (
            not self.sensor.is_attr_blank(ATTR_LATITUDE)
            and not self.sensor.is_attr_blank(ATTR_LONGITUDE)
            and not self.sensor.is_attr_blank(ATTR_HOME_LATITUDE)
            and not self.sensor.is_attr_blank(ATTR_HOME_LONGITUDE)
        ):
            return proceed_with_update

        proceed_with_update = UpdateStatus.SKIP
        _LOGGER.info(
            "(%s) Problem with updated lat/long, not performing update: "
            "old_latitude=%s, old_longitude=%s, "
            "new_latitude=%s, new_longitude=%s, "
            "home_latitude=%s, home_longitude=%s",
            self.sensor.get_attr(CONF_NAME),
            self.sensor.get_attr_safe_float(ATTR_LATITUDE_OLD),
            self.sensor.get_attr_safe_float(ATTR_LONGITUDE_OLD),
            self.sensor.get_attr_safe_float(ATTR_LATITUDE),
            self.sensor.get_attr_safe_float(ATTR_LONGITUDE),
            self.sensor.get_attr_safe_float(ATTR_HOME_LATITUDE),
            self.sensor.get_attr_safe_float(ATTR_HOME_LONGITUDE),
        )
        return proceed_with_update

    async def get_seconds_from_last_change(self, now: datetime) -> int:
        """Calculate elapsed seconds since ``ATTR_LAST_CHANGED``.

        Args:
            now: Current update timestamp.

        Returns:
            Elapsed seconds, or ``3600`` when the saved timestamp is missing or
            cannot be parsed.
        """
        if self.sensor.is_attr_blank(ATTR_LAST_CHANGED):
            return 3600
        try:
            last_changed: datetime = datetime.fromisoformat(
                self.sensor.get_attr_safe_str(ATTR_LAST_CHANGED)
            )
            if last_changed.tzinfo is None:
                last_changed = last_changed.replace(tzinfo=now.tzinfo or UTC)
            elif now.tzinfo is not None:
                last_changed = last_changed.astimezone(now.tzinfo)
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
            except (TypeError, OverflowError) as e:
                _LOGGER.warning("Error calculating the seconds between last change to now: %r", e)
                return 3600
            return int(changed_diff_sec)

    async def change_show_time_to_date(self) -> None:
        """Replace a stale ``since HH:MM`` suffix with a date suffix."""
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
            self.sensor.set_native_value(value=f"{cleared_state} (since {mmddstring})")
            self.sensor.set_attr(ATTR_SHOW_DATE, True)
            await self._hass.async_add_executor_job(
                write_sensor_to_json,
                self.sensor.get_internal_attr(),
                self.sensor.get_attr_safe_str(CONF_NAME),
                self.sensor.get_attr_safe_str(ATTR_JSON_FILENAME),
                self.sensor.get_attr_safe_str(ATTR_JSON_FOLDER),
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
        """Mark direction as stationary after a skipped movement update.

        Args:
            now: Timestamp to store as the new last-changed value.
            changed_diff_sec: Seconds since the prior last-changed value, used
                only for diagnostic logging.
        """
        self.sensor.set_attr(ATTR_DIRECTION_OF_TRAVEL, "stationary")
        self.sensor.set_attr(ATTR_LAST_CHANGED, now.isoformat(sep=" ", timespec="seconds"))
        await self._hass.async_add_executor_job(
            write_sensor_to_json,
            self.sensor.get_internal_attr(),
            self.sensor.get_attr_safe_str(CONF_NAME),
            self.sensor.get_attr_safe_str(ATTR_JSON_FILENAME),
            self.sensor.get_attr_safe_str(ATTR_JSON_FOLDER),
        )
        _LOGGER.debug(
            "(%s) Updating direction of travel to stationary (Last changed %s seconds ago)",
            self.sensor.get_attr(CONF_NAME),
            int(changed_diff_sec),
        )

    async def is_devicetracker_set(self) -> UpdateStatus:
        """Validate tracker availability and coordinates before an update.

        Returns:
            ``PROCEED`` when the tracker can be used, otherwise ``SKIP``.
        """
        if not await self.is_tracker_available():
            return UpdateStatus.SKIP

        if not await self.has_valid_coordinates():
            return UpdateStatus.SKIP

        self.sensor.warn_if_device_tracker_prob = True
        return UpdateStatus.PROCEED

    async def is_tracker_available(self) -> bool:
        """Return whether the configured tracked entity exists and is available.

        Returns:
            ``True`` when Home Assistant has a usable state object for the
                configured tracker.
        """
        tracker_id = self.sensor.get_attr(CONF_DEVICETRACKER_ID)
        tracker_snapshot = TrackerSnapshot.from_hass(self._hass, tracker_id)
        if tracker_snapshot.status == TrackerStatus.MISSING_ENTITY_ID:
            await self.log_tracker_issue("Tracked Entity is not set")
            return False

        if tracker_snapshot.status in {TrackerStatus.NOT_FOUND, TrackerStatus.UNAVAILABLE}:
            await self.log_tracker_issue(f"Tracked Entity ({tracker_id}) is not available")
            return False

        return True

    async def has_valid_coordinates(self) -> bool:
        """Return whether the tracked entity exposes numeric coordinates.

        Returns:
            ``True`` when latitude and longitude attributes both exist and are
            float-convertible.
        """
        tracker_snapshot = TrackerSnapshot.from_hass(
            self._hass, self.sensor.get_attr(CONF_DEVICETRACKER_ID)
        )
        if not tracker_snapshot.has_valid_coordinates:
            await self.log_coordinate_issue()
            return False

        return True

    async def log_tracker_issue(self, message: str) -> None:
        """Log tracker availability problems at warning or info level.

        Args:
            message: Specific tracker problem without the standard suffix.
        """
        full_message = f"({self.sensor.get_attr(CONF_NAME)}) {message}. Not Proceeding with Update"
        if self.sensor.warn_if_device_tracker_prob or self.sensor.get_attr(ATTR_INITIAL_UPDATE):
            _LOGGER.warning(full_message)
            self.sensor.warn_if_device_tracker_prob = False
        else:
            _LOGGER.info(full_message)

    async def log_coordinate_issue(self) -> None:
        """Log missing or invalid tracker coordinates with tracker details."""
        tracker_id = self.sensor.get_attr(CONF_DEVICETRACKER_ID)
        message = (
            f"({self.sensor.get_attr(CONF_NAME)}) Tracked Entity ({tracker_id}) "
            "Latitude/Longitude is not set or is not a number. "
            "Not Proceeding with Update."
        )

        if self.sensor.warn_if_device_tracker_prob or self.sensor.get_attr(ATTR_INITIAL_UPDATE):
            _LOGGER.warning(message)
            self.sensor.warn_if_device_tracker_prob = False
        else:
            _LOGGER.info(message)

        _LOGGER.debug(
            "(%s) Tracked Entity (%s) details: %s",
            self.sensor.get_attr(CONF_NAME),
            tracker_id,
            self._hass.states.get(tracker_id),
        )

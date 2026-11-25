"""Update pipeline for Places sensors and external geocoding lookups."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
import copy
from datetime import UTC, datetime
import logging
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from homeassistant.components.device_tracker.const import DOMAIN as DEVICE_TRACKER_DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_FRIENDLY_NAME,
    ATTR_GPS_ACCURACY,
    CONF_API_KEY,
    CONF_FRIENDLY_NAME,
    CONF_NAME,
    CONF_ZONE,
    STATE_NOT_HOME,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant
from homeassistant.util import slugify

from .basic_options import BasicOptionsParser
from .const import (
    ATTR_DEVICETRACKER_ZONE,
    ATTR_DEVICETRACKER_ZONE_NAME,
    ATTR_DIRECTION_OF_TRAVEL,
    ATTR_DISPLAY_OPTIONS_LIST,
    ATTR_DISTANCE_FROM_HOME,
    ATTR_DISTANCE_TRAVELED,
    ATTR_HOME_LATITUDE,
    ATTR_HOME_LOCATION,
    ATTR_HOME_LONGITUDE,
    ATTR_INITIAL_UPDATE,
    ATTR_LAST_CHANGED,
    ATTR_LAST_PLACE_NAME,
    ATTR_LAST_RESOLVED_ZONE,
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
    EVENT_ATTRIBUTE_MAP,
    GPS_ACCURACY_FORGET_COUNT,
    MOVEMENT_THRESHOLD_M,
    OSM_CACHE,
    PERSON_DOMAIN,
    RESET_ATTRIBUTE_LIST,
    UpdateStatus,
)
from .helpers import clear_since_from_state, is_float, safe_truncate
from .location import CoordinatePair, LocationSnapshot, direction_of_travel
from .osm_client import OSMClient
from .parse_osm import OSMParser
from .state import PlacesState
from .tracker import TrackerSnapshot, TrackerStatus

if TYPE_CHECKING:
    from .coordinator import PlacesUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


class PlacesUpdater:
    """Resolve one candidate Place and apply the outcome of the Update."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        coordinator: PlacesUpdateCoordinator,
    ) -> None:
        """Initialize an updater for a Places coordinator.

        Args:
            hass (HomeAssistant):
                Home Assistant instance.
            config_entry (ConfigEntry):
                Config entry backing the coordinator.
            coordinator (PlacesUpdateCoordinator):
                Coordinator whose attributes and state will be updated.
        """
        self.coordinator = coordinator
        self.state: PlacesState = coordinator
        self._config_entry: ConfigEntry = config_entry
        self._hass = hass
        self._osm_client = OSMClient(
            hass=hass,
            sensor_name=str(self.state.get_attr(CONF_NAME)),
        )
        self._use_cache = True

    async def do_update(self, reason: str, *, force: bool = False) -> None:
        """Resolve and commit one Update under the coordinator lock, propagating cancellation.

        Args:
            reason (str): Human-readable trigger reason used in logs.
            force (bool): Bypass movement and cache reads for this attempt.

        Raises:
            Exception: Propagated when candidate processing fails.
        """
        coordinator = self.coordinator
        accepted = coordinator.get_internal_attr()
        self.state = PlacesState(self._hass, copy.deepcopy(accepted))
        self._use_cache = not force
        await self.log_update_start(reason)
        now = await self.get_current_time()

        try:
            event_data = await self._prepare_update(accepted, now, force=force)
        except Exception:
            # Leave the accepted Place intact for failures in any processing phase.
            _LOGGER.exception("(%s) Error during Places update", coordinator.get_attr(CONF_NAME))
            raise
        else:
            if coordinator.is_shutting_down:
                return
            self.state.set_attr(ATTR_LAST_UPDATED, now.isoformat(sep=" ", timespec="seconds"))
            coordinator.replace_attributes(self.state.get_internal_attr())
            coordinator.commit_gps_accuracy_history()
        finally:
            coordinator.discard_staged_gps_accuracy_history()

        if event_data is not None:
            await coordinator.async_publish_accepted_place(event_data)
        else:
            await coordinator.async_persist_attributes()
            coordinator.publish_update()
        _LOGGER.info("(%s) End of Update", coordinator.get_attr(CONF_NAME))

    async def _prepare_update(
        self, accepted: MutableMapping[str, Any], now: datetime, *, force: bool
    ) -> dict[str, Any] | None:
        """Resolve a candidate or prepare maintenance for the accepted Place.

        Args:
            accepted (MutableMapping[str, Any]): Accepted attributes before this attempt.
            now (datetime): Time of this attempt in the Home Assistant timezone.
            force (bool): Bypass movement and accept fresh details for unchanged text.

        Returns:
            dict[str, Any] | None: Event data when accepting a new Place.
        """
        await self.update_entity_name_and_cleanup()
        self._osm_client.update_sensor_name(str(self.state.get_attr(CONF_NAME)))
        await self.update_previous_state()
        await self.update_old_coordinates()
        prev_last_place_name = self.state.get_attr_safe_str(ATTR_LAST_PLACE_NAME)

        status = await self.check_device_tracker_and_update_coords()
        if status == UpdateStatus.PROCEED:
            status = await self.determine_update_criteria(force=force)

        keep_bookkeeping = status in (UpdateStatus.SKIP, UpdateStatus.SKIP_SET_STATIONARY)
        if status == UpdateStatus.PROCEED:
            await self.process_osm_update(now=now)
            if self.coordinator.is_shutting_down:
                return None
            if not self.state.is_attr_blank(ATTR_OSM_DICT):
                # The zone has been resolved even if the display text stays the same.
                if not self.state.is_attr_blank(ATTR_LAST_RESOLVED_ZONE):
                    self.state.set_attr(ATTR_LAST_RESOLVED_ZONE, self._current_zone_for_storage())
                if force or await self.should_update_state(now=now):
                    await self.prepare_accepted_place(now)
                    if self.coordinator.is_shutting_down:
                        return None
                    return await self.build_event_data(prev_last_place_name)
                _LOGGER.info(
                    "(%s) No entity update needed, Previous State = New State",
                    self.state.get_attr(CONF_NAME),
                )
                keep_bookkeeping = True

        self._retain_place(accepted, keep_bookkeeping=keep_bookkeeping)
        await self.maintain_retained_place(now, status)
        return None

    def _retain_place(self, accepted: MutableMapping[str, Any], *, keep_bookkeeping: bool) -> None:
        """Retain the accepted Place and roll back bookkeeping if the lookup failed.

        Args:
            accepted (MutableMapping[str, Any]): Attributes of the last accepted Place.
            keep_bookkeeping (bool): Whether to keep the candidate accuracy and zone data.
        """
        candidate = self.state
        self.state = PlacesState(self._hass, dict(accepted))
        if not keep_bookkeeping:
            self.coordinator.discard_staged_gps_accuracy_history()
            return

        self.state.copy_gps_accuracy_record_from(candidate)
        if candidate.is_attr_blank(ATTR_LAST_RESOLVED_ZONE):
            self.state.clear_attr(ATTR_LAST_RESOLVED_ZONE)
        else:
            self.state.set_attr(
                ATTR_LAST_RESOLVED_ZONE, candidate.get_attr(ATTR_LAST_RESOLVED_ZONE)
            )
        for attr in (ATTR_DEVICETRACKER_ZONE, ATTR_DEVICETRACKER_ZONE_NAME):
            value = candidate.get_attr(attr)
            if value != self.state.get_attr(attr):
                self.state.set_attr(attr, value)

    async def log_update_start(self, reason: str) -> None:
        """Log a consistent update-start message.

        Args:
            reason (str):
                Human-readable update reason.
        """
        _LOGGER.info(
            "(%s) Starting %s Update (Tracked Entity: %s)",
            self.state.get_attr(CONF_NAME),
            reason,
            self.state.get_attr(CONF_DEVICETRACKER_ID),
        )

    async def prepare_accepted_place(self, now: datetime) -> None:
        """Finalize the accepted candidate's display and optional Extended data.

        Args:
            now (datetime): Update timestamp in the Home Assistant timezone.
        """
        if self.state.get_attr(CONF_EXTENDED_ATTR):
            await self.get_extended_attr()
        self.state.set_attr(ATTR_SHOW_DATE, False)
        await self.state.async_cleanup_attributes()
        if not self.state.is_attr_blank(ATTR_NATIVE_VALUE):
            current_time: str = f"{now.hour:02}:{now.minute:02}"
            if self.state.get_attr(CONF_SHOW_TIME):
                time_suffix = f" (since {current_time})"
                max_state_length = 255 - len(time_suffix)
                state: str = clear_since_from_state(self.state.get_attr_safe_str(ATTR_NATIVE_VALUE))
                self.state.set_native_value(value=f"{state[:max_state_length]}{time_suffix}")
            else:
                self.state.set_native_value(
                    value=self.state.get_attr_safe_str(ATTR_NATIVE_VALUE)[:255]
                )
            _LOGGER.info(
                "(%s) New State: %s",
                self.state.get_attr(CONF_NAME),
                self.state.get_attr(ATTR_NATIVE_VALUE),
            )
        else:
            self.state.set_native_value(value=None)
            _LOGGER.warning("(%s) New State is None", self.state.get_attr(CONF_NAME))

        self.state.set_attr(ATTR_INITIAL_UPDATE, False)

    async def build_event_data(self, prev_last_place_name: str) -> dict[str, Any]:
        """Build the Places state-update event payload for the accepted candidate.

        Args:
            prev_last_place_name (str): Last-place value before this Update.

        Returns:
            dict[str, Any]: Existing Places event payload for the accepted Place.
        """
        event_data: dict[str, Any] = {}
        if not self.state.is_attr_blank(CONF_NAME):
            event_data.update({"entity": self.state.get_attr(CONF_NAME)})
        if not self.state.is_attr_blank(ATTR_PREVIOUS_STATE):
            event_data.update({"from_state": self.state.get_attr(ATTR_PREVIOUS_STATE)})
        if not self.state.is_attr_blank(ATTR_NATIVE_VALUE):
            event_data.update({"to_state": self.state.get_attr(ATTR_NATIVE_VALUE)})

        for event_field, attr in EVENT_ATTRIBUTE_MAP.items():
            if not self.state.is_attr_blank(attr):
                event_data[event_field] = self.state.get_attr(attr)

        if (
            not self.state.is_attr_blank(ATTR_LAST_PLACE_NAME)
            and self.state.get_attr(ATTR_LAST_PLACE_NAME) != prev_last_place_name
        ):
            event_data[ATTR_LAST_PLACE_NAME] = self.state.get_attr(ATTR_LAST_PLACE_NAME)

        display_parser = BasicOptionsParser(
            coordinator=self.state,
            internal_attr=self.state.get_internal_attr(),
            display_options=self.state.get_attr_safe_list(ATTR_DISPLAY_OPTIONS_LIST),
        )
        composite_values = {
            "place": display_parser.build_place(),
            "formatted_place": await display_parser.build_formatted_place(),
        }
        event_data.update({key: value for key, value in composite_values.items() if value})

        return event_data

    async def get_current_time(self) -> datetime:
        """Return the current time in Home Assistant's configured timezone.

        Returns:
            datetime:
                Timezone-aware current datetime.
        """
        if self._hass.config.time_zone:
            return datetime.now(tz=ZoneInfo(str(self._hass.config.time_zone)))
        return datetime.now(tz=UTC)

    async def update_entity_name_and_cleanup(self) -> None:
        """Synchronize renamed entities and drop blank attributes."""
        await self.check_for_updated_entity_name()
        await self.state.async_cleanup_attributes()

    async def check_for_updated_entity_name(self) -> None:
        """Copy a changed friendly name back into the config entry."""
        if self.coordinator.entity_id is None:
            return

        entity_state = self._hass.states.get(str(self.coordinator.entity_id))
        if entity_state is None:
            return

        new_name = entity_state.attributes.get(ATTR_FRIENDLY_NAME)
        if new_name is None or new_name == self.state.get_attr(CONF_NAME):
            return

        _LOGGER.debug(
            "(%s) Sensor Name Changed. Updating Name to: %s",
            self.state.get_attr(CONF_NAME),
            new_name,
        )

        self.state.set_attr(CONF_NAME, new_name)
        config = dict(self._config_entry.data)
        config.update({CONF_NAME: new_name})

        self._hass.config_entries.async_update_entry(
            self._config_entry,
            data=config,
            options=self._config_entry.options,
        )
        _LOGGER.debug(
            "(%s) Updated ConfigEntry Name: %s",
            self.state.get_attr(CONF_NAME),
            self._config_entry.data.get(CONF_NAME),
        )

    async def update_previous_state(self) -> None:
        """Store the previous rendered state before recalculating the sensor."""
        if not self.state.is_attr_blank(ATTR_NATIVE_VALUE) and self.state.get_attr(CONF_SHOW_TIME):
            self.state.set_attr(
                ATTR_PREVIOUS_STATE,
                clear_since_from_state(orig_state=self.state.get_attr_safe_str(ATTR_NATIVE_VALUE)),
            )
        else:
            self.state.set_attr(ATTR_PREVIOUS_STATE, self.state.get_attr(ATTR_NATIVE_VALUE))

    async def update_old_coordinates(self) -> None:
        """Snapshot current coordinates as old coordinates before replacement."""
        if is_float(self.state.get_attr(ATTR_LATITUDE)):
            self.state.set_attr(ATTR_LATITUDE_OLD, self.state.get_attr_safe_float(ATTR_LATITUDE))
        if is_float(self.state.get_attr(ATTR_LONGITUDE)):
            self.state.set_attr(ATTR_LONGITUDE_OLD, self.state.get_attr_safe_float(ATTR_LONGITUDE))

    async def check_device_tracker_and_update_coords(self) -> UpdateStatus:
        """Validate the tracker and refresh coordinates before geocoding.

        Returns:
            UpdateStatus:
                ``PROCEED`` when tracker data is usable, otherwise an update skip
                status.
        """
        proceed_with_update: UpdateStatus = await self.is_devicetracker_set()
        _LOGGER.debug(
            "(%s) [check_device_tracker_and_update_coords] proceed_with_update: %s",
            self.state.get_attr(CONF_NAME),
            proceed_with_update,
        )
        if proceed_with_update == UpdateStatus.PROCEED:
            await self.update_coordinates()
            proceed_with_update = await self.get_gps_accuracy()
            _LOGGER.debug(
                "(%s) [check_device_tracker_and_update_coords] proceed_with_update: %s",
                self.state.get_attr(CONF_NAME),
                proceed_with_update,
            )
        return proceed_with_update

    async def get_gps_accuracy(self) -> UpdateStatus:
        """Decide whether a GPS accuracy of 0 from the tracked entity skips this Update.

        A 0 reading is treated as not reported until its source tracker has reported
        a positive GPS accuracy, which is then recorded with the Places entry. A 0
        reading from a recorded source tracker skips the Update until enough moving
        0 readings have been recorded to forget the source tracker. A reading without
        accuracy interrupts that run. With Use GPS Accuracy off, accuracy is ignored
        and nothing is recorded.

        Returns:
            UpdateStatus:
                ``SKIP`` for a 0 reading from a source tracker recorded as reporting
                accuracy, unless the reading causes Places to forget that source
                tracker. Otherwise, ``PROCEED``.
        """
        tracker_id = self.state.get_attr_safe_str(CONF_DEVICETRACKER_ID)
        current_state = self._hass.states.get(tracker_id) if tracker_id else None
        tracker_snapshot = TrackerSnapshot.from_state(tracker_id, current_state)
        gps_accuracy = tracker_snapshot.gps_accuracy
        if gps_accuracy is None:
            self.state.clear_attr(ATTR_GPS_ACCURACY)
            _LOGGER.debug(
                "(%s) GPS Accuracy attribute not found in: %s",
                self.state.get_attr(CONF_NAME),
                self.state.get_attr(CONF_DEVICETRACKER_ID),
            )
        else:
            self.state.set_attr(ATTR_GPS_ACCURACY, gps_accuracy)

        if not self.state.get_attr(CONF_USE_GPS):
            return UpdateStatus.PROCEED

        skip, sources, forgotten_sources = self.coordinator.stage_gps_accuracy(
            current_state, tracker_snapshot
        )
        self.state.set_gps_accuracy_sources(sources)
        for source in forgotten_sources:
            _LOGGER.warning(
                "(%s) %s sent %s GPS accuracy 0 readings in a row, each moving more than %s m, "
                "so Places is trying the latest reading",
                self.state.get_attr(CONF_NAME),
                source,
                GPS_ACCURACY_FORGET_COUNT,
                MOVEMENT_THRESHOLD_M,
            )
        if gps_accuracy is not None and gps_accuracy > 0:
            _LOGGER.debug(
                "(%s) GPS Accuracy: %s",
                self.state.get_attr(CONF_NAME),
                round(gps_accuracy, 3),
            )
        elif skip:
            _LOGGER.info(
                "(%s) GPS Accuracy is 0.0, not performing update",
                self.state.get_attr(CONF_NAME),
            )
        return UpdateStatus.SKIP if skip else UpdateStatus.PROCEED

    async def update_coordinates(self) -> None:
        """Copy latitude and longitude from the tracked entity state."""
        tracker_id = self.state.get_attr(CONF_DEVICETRACKER_ID)
        tracker_snapshot = TrackerSnapshot.from_hass(self._hass, tracker_id)
        if tracker_snapshot.status in {
            TrackerStatus.MISSING_ENTITY_ID,
            TrackerStatus.NOT_FOUND,
            TrackerStatus.UNAVAILABLE,
        }:
            _LOGGER.warning(
                "(%s) Device tracker entity not found: %s",
                self.state.get_attr(CONF_NAME),
                tracker_id,
            )
            return
        if tracker_snapshot.status == TrackerStatus.OK:
            if tracker_snapshot.latitude is not None:
                self.state.set_attr(ATTR_LATITUDE, tracker_snapshot.latitude)
            if tracker_snapshot.longitude is not None:
                self.state.set_attr(ATTR_LONGITUDE, tracker_snapshot.longitude)

    async def determine_update_criteria(self, *, force: bool = False) -> UpdateStatus:
        """Run zone, distance, and optional movement checks for this update.

        Args:
            force (bool):
                When True, refresh derived fields but skip movement-based
                update gating.

        Returns:
            UpdateStatus:
                Status indicating whether the update should continue or be skipped.
        """
        tracked_domain = self.state.get_attr_safe_str(CONF_DEVICETRACKER_ID).partition(".")[0]
        tracks_zone = tracked_domain in (DEVICE_TRACKER_DOMAIN, PERSON_DOMAIN)
        if tracks_zone and self.state.is_attr_blank(ATTR_LAST_RESOLVED_ZONE):
            # Older snapshots only save the published Current zone.
            self.state.set_attr(ATTR_LAST_RESOLVED_ZONE, self._current_zone_for_storage())

        await self.get_initial_last_place_name()
        await self.get_zone_details()
        proceed_with_update = await self.update_coordinates_and_distance()
        _LOGGER.debug(
            "(%s) [determine_update_criteria] proceed_with_update: %s",
            self.state.get_attr(CONF_NAME),
            proceed_with_update,
        )
        if proceed_with_update == UpdateStatus.PROCEED and not force:
            proceed_with_update = await self.determine_if_update_needed(
                zone_changed=tracks_zone
                and self.state.active_zone(self.state.get_attr_safe_str(ATTR_LAST_RESOLVED_ZONE))
                != self.state.active_zone(self.state.get_attr_safe_str(ATTR_DEVICETRACKER_ZONE))
            )
            _LOGGER.debug(
                "(%s) [determine_update_criteria] proceed_with_update: %s",
                self.state.get_attr(CONF_NAME),
                proceed_with_update,
            )
        return proceed_with_update

    def _current_zone_for_storage(self) -> str:
        """Return the Current zone in the persisted resolved-zone format.

        Returns:
            str: Current zone or ``not_home`` when unset or away.
        """
        zone = self.state.get_attr_safe_str(ATTR_DEVICETRACKER_ZONE)
        return STATE_NOT_HOME if zone in ("", "away") else zone

    async def get_initial_last_place_name(self) -> None:
        """Set the pre-update last-place value from the old place or zone."""
        _LOGGER.debug(
            "(%s) Previous State: %s",
            self.state.get_attr(CONF_NAME),
            self.state.get_attr(ATTR_PREVIOUS_STATE),
        )
        _LOGGER.debug(
            "(%s) Previous last_place_name: %s",
            self.state.get_attr(CONF_NAME),
            self.state.get_attr(ATTR_LAST_PLACE_NAME),
        )

        if not await self.state.in_zone():
            # Previously Not in a Zone
            if not self.state.is_attr_blank(ATTR_PLACE_NAME):
                # If place name is set
                self.state.set_attr(ATTR_LAST_PLACE_NAME, self.state.get_attr(ATTR_PLACE_NAME))
                _LOGGER.debug(
                    "(%s) Previous place is Place Name, last_place_name is set: %s",
                    self.state.get_attr(CONF_NAME),
                    self.state.get_attr(ATTR_LAST_PLACE_NAME),
                )
            else:
                # If blank, keep previous last_place_name
                _LOGGER.debug(
                    "(%s) Previous Place Name is None, keeping prior",
                    self.state.get_attr(CONF_NAME),
                )
        else:
            # Previously In a Zone
            self.state.set_attr(
                ATTR_LAST_PLACE_NAME,
                self.state.get_attr(ATTR_DEVICETRACKER_ZONE_NAME),
            )
            _LOGGER.debug(
                "(%s) Previous Place is Zone: %s",
                self.state.get_attr(CONF_NAME),
                self.state.get_attr(ATTR_LAST_PLACE_NAME),
            )
        _LOGGER.debug(
            "(%s) last_place_name (Initial): %s",
            self.state.get_attr(CONF_NAME),
            self.state.get_attr(ATTR_LAST_PLACE_NAME),
        )

    async def get_zone_details(self) -> None:
        """Store the tracked entity's zone state and friendly zone name."""
        tracker_id = self.state.get_attr_safe_str(CONF_DEVICETRACKER_ID)
        tracker_state = self._hass.states.get(tracker_id)
        if tracker_id.split(".")[0] != CONF_ZONE:
            self.state.set_attr(
                ATTR_DEVICETRACKER_ZONE,
                (tracker_state.state if tracker_state is not None else STATE_UNKNOWN),
            )
        if await self.state.in_zone():
            devicetracker_zone_name_state = None
            tracker_state = self._hass.states.get(tracker_id)
            devicetracker_zone_id: str | None = None
            if tracker_state is not None:
                devicetracker_zone_id = tracker_state.attributes.get(CONF_ZONE)
            if not devicetracker_zone_id and not self.state.is_attr_blank(ATTR_DEVICETRACKER_ZONE):
                devicetracker_zone_id = slugify(
                    self.state.get_attr_safe_str(ATTR_DEVICETRACKER_ZONE)
                )
            if devicetracker_zone_id:
                devicetracker_zone_id = f"{CONF_ZONE}.{devicetracker_zone_id}"
                devicetracker_zone_name_state = self._hass.states.get(devicetracker_zone_id)
            if devicetracker_zone_name_state:
                if devicetracker_zone_name_state.attributes.get(CONF_FRIENDLY_NAME):
                    self.state.set_attr(
                        ATTR_DEVICETRACKER_ZONE_NAME,
                        devicetracker_zone_name_state.attributes.get(CONF_FRIENDLY_NAME),
                    )
                else:
                    self.state.set_attr(
                        ATTR_DEVICETRACKER_ZONE_NAME, devicetracker_zone_name_state.name
                    )
            else:
                self.state.set_attr(
                    ATTR_DEVICETRACKER_ZONE_NAME,
                    self.state.get_attr(ATTR_DEVICETRACKER_ZONE),
                )

            if not self.state.is_attr_blank(ATTR_DEVICETRACKER_ZONE_NAME) and (
                self.state.get_attr_safe_str(ATTR_DEVICETRACKER_ZONE_NAME)
            ).lower() == self.state.get_attr(ATTR_DEVICETRACKER_ZONE_NAME):
                self.state.set_attr(
                    ATTR_DEVICETRACKER_ZONE_NAME,
                    self.state.get_attr_safe_str(ATTR_DEVICETRACKER_ZONE_NAME).title(),
                )
            _LOGGER.debug(
                "(%s) Tracked Entity Zone Name: %s",
                self.state.get_attr(CONF_NAME),
                self.state.get_attr(ATTR_DEVICETRACKER_ZONE_NAME),
            )
        else:
            _LOGGER.debug(
                "(%s) Tracked Entity Zone: %s",
                self.state.get_attr(CONF_NAME),
                self.state.get_attr(ATTR_DEVICETRACKER_ZONE),
            )
            self.state.set_attr(
                ATTR_DEVICETRACKER_ZONE_NAME,
                self.state.get_attr(ATTR_DEVICETRACKER_ZONE),
            )

    async def process_osm_update(self, now: datetime) -> None:
        """Reset transient attributes, build links, and query OSM.

        Args:
            now (datetime):
                Update timestamp to store as ``last_changed`` when geocoding
                succeeds.
        """
        _LOGGER.info(
            "(%s) Meets criteria, proceeding with OpenStreetMap query",
            self.state.get_attr(CONF_NAME),
        )
        _LOGGER.info(
            "(%s) Tracked Entity Zone: %s",
            self.state.get_attr(CONF_NAME),
            self.state.get_attr(ATTR_DEVICETRACKER_ZONE),
        )

        await self.async_reset_attributes()
        await self.get_map_link()
        await self.query_osm_and_finalize(now=now)

    async def get_map_link(self) -> None:
        """Build the configured map-provider URL for the current coordinates."""
        if self.state.get_attr(CONF_MAP_PROVIDER) == "google":
            params = {
                "q": self.state.get_attr(ATTR_LOCATION_CURRENT),
                "ll": self.state.get_attr(ATTR_LOCATION_CURRENT),
                "z": self.state.get_attr(CONF_MAP_ZOOM),
            }
            url = f"https://maps.google.com/?{urlencode(params)}"
            self.state.set_attr(ATTR_MAP_LINK, url)
        elif self.state.get_attr(CONF_MAP_PROVIDER) == "osm":
            lat_str = safe_truncate(self.state.get_attr_safe_float(ATTR_LATITUDE), 8)
            lon_str = safe_truncate(self.state.get_attr_safe_float(ATTR_LONGITUDE), 9)
            params = {
                "mlat": self.state.get_attr_safe_float(ATTR_LATITUDE),
                "mlon": self.state.get_attr_safe_float(ATTR_LONGITUDE),
            }
            osm_url = f"https://www.openstreetmap.org/?{urlencode(params)}"
            osm_url += f"#map={self.state.get_attr(CONF_MAP_ZOOM)}/{lat_str}/{lon_str}"
            self.state.set_attr(ATTR_MAP_LINK, osm_url)
        else:
            params = {
                "q": self.state.get_attr(ATTR_LOCATION_CURRENT),
                "z": self.state.get_attr(CONF_MAP_ZOOM),
            }
            url = f"https://maps.apple.com/?{urlencode(params)}"
            self.state.set_attr(ATTR_MAP_LINK, url)
        _LOGGER.debug(
            "(%s) Map Link Type: %s",
            self.state.get_attr(CONF_NAME),
            self.state.get_attr(CONF_MAP_PROVIDER),
        )
        _LOGGER.debug(
            "(%s) Map Link URL: %s",
            self.state.get_attr(CONF_NAME),
            self.state.get_attr(ATTR_MAP_LINK),
        )

    async def async_apply_show_time(self) -> None:
        """Apply the configured last-updated suffix to existing sensor state."""
        state = clear_since_from_state(self.state.get_attr_safe_str(ATTR_NATIVE_VALUE))
        if self.state.get_attr(CONF_SHOW_TIME) and state:
            now = await self.get_current_time()
            changed_at = now
            if not self.state.is_attr_blank(ATTR_LAST_CHANGED):
                stored_last_changed = self.state.get_attr_safe_str(ATTR_LAST_CHANGED)
                try:
                    changed_at = datetime.fromisoformat(stored_last_changed)
                except ValueError:
                    _LOGGER.debug(
                        "(%s) Stored Last Changed timestamp is malformed: %s",
                        self.state.get_attr(CONF_NAME),
                        stored_last_changed,
                    )
                else:
                    if changed_at.tzinfo is None:
                        changed_at = changed_at.replace(tzinfo=now.tzinfo or UTC)
                    elif now.tzinfo is not None:
                        changed_at = changed_at.astimezone(now.tzinfo)
            try:
                elapsed_seconds = int((now - changed_at).total_seconds())
            except (TypeError, OverflowError) as error:
                _LOGGER.warning(
                    "Error calculating the seconds between last change to now: %r", error
                )
                elapsed_seconds = 3600
            if elapsed_seconds >= 86399:
                self.state.set_native_value(state)
                await self.change_show_time_to_date()
                return
            suffix = f" (since {changed_at.hour:02}:{changed_at.minute:02})"
            state = f"{state[: 255 - len(suffix)]}{suffix}"
        else:
            state = state[:255]
        self.state.set_attr(ATTR_SHOW_DATE, False)
        self.state.set_native_value(state or None)
        _LOGGER.debug(
            "(%s) Show-time applied, New State: %s",
            self.state.get_attr(CONF_NAME),
            self.state.get_attr(ATTR_NATIVE_VALUE),
        )

    async def async_reset_attributes(self) -> None:
        """Clear transient attributes before parsing fresh geocoding data."""
        for attr in RESET_ATTRIBUTE_LIST:
            self.state.clear_attr(attr)
        await self.state.async_cleanup_attributes()

    async def query_osm_and_finalize(self, now: datetime) -> None:
        """Fetch reverse-geocode data and render the display state.

        Args:
            now (datetime):
                Update timestamp to store when OSM returned usable data.
        """
        osm_url: str = await self.build_osm_url()
        await self.get_dict_from_url(url=osm_url, name="OpenStreetMaps", dict_name=ATTR_OSM_DICT)
        if not self.state.is_attr_blank(ATTR_OSM_DICT):
            parser = OSMParser(coordinator=self.state)
            await parser.parse_osm_dict()
            await parser.finalize_last_place_name(
                self.state.get_attr_safe_str(ATTR_LAST_PLACE_NAME)
            )
            await self.state.process_display_options()
            self.state.set_attr(ATTR_LAST_CHANGED, now.isoformat(sep=" ", timespec="seconds"))

    async def should_update_state(self, now: datetime) -> bool:
        """Return whether the rendered state should replace the prior state.

        Args:
            now (datetime):
                Update timestamp. Reserved for future time-based criteria.

        Returns:
            bool:
                ``True`` for initial updates, blank previous/current states, or a
                meaningful state change.
        """
        prev_state: str = self.state.get_attr_safe_str(ATTR_PREVIOUS_STATE)
        native_value: str = self.state.get_attr_safe_str(ATTR_NATIVE_VALUE)
        tracker_zone: str = self.state.get_attr_safe_str(ATTR_DEVICETRACKER_ZONE)

        if (
            (
                not self.state.is_attr_blank(ATTR_PREVIOUS_STATE)
                and not self.state.is_attr_blank(ATTR_NATIVE_VALUE)
                and prev_state.lower().strip() != native_value.lower().strip()
                and prev_state.replace(" ", "").lower().strip() != native_value.lower().strip()
                and prev_state.lower().strip() != tracker_zone.lower().strip()
            )
            or self.state.is_attr_blank(ATTR_PREVIOUS_STATE)
            or self.state.is_attr_blank(ATTR_NATIVE_VALUE)
            or self.state.get_attr(ATTR_INITIAL_UPDATE)
        ):
            return True
        return False

    async def maintain_retained_place(self, now: datetime, status: UpdateStatus) -> None:
        """Apply elapsed-time maintenance to the retained Place.

        Args:
            now (datetime): Current Update timestamp.
            status (UpdateStatus): Movement or validation status of the attempt.
        """
        changed_diff_sec = await self.get_seconds_from_last_change(now=now)
        if (
            status == UpdateStatus.SKIP_SET_STATIONARY
            and self.state.get_attr(ATTR_DIRECTION_OF_TRAVEL) != "stationary"
            and changed_diff_sec >= 60
        ):
            await self.change_dot_to_stationary(now=now, changed_diff_sec=changed_diff_sec)
        if (
            self.state.get_attr(CONF_SHOW_TIME)
            and changed_diff_sec >= 86399
            and not self.state.get_attr(ATTR_SHOW_DATE)
        ):
            await self.change_show_time_to_date()

    async def build_osm_url(self) -> str:
        """Build the Nominatim reverse-geocode URL for current coordinates.

        Returns:
            str:
                Fully encoded Nominatim reverse lookup URL.
        """
        return OSMClient.reverse_url(
            self.state.get_attr_safe_float(ATTR_LATITUDE),
            self.state.get_attr_safe_float(ATTR_LONGITUDE),
            self.state.get_attr(CONF_LANGUAGE) or "",
            self.state.get_attr(CONF_API_KEY) or "",
        )

    async def get_extended_attr(self) -> None:
        """Fetch optional OSM details and continue to Wikidata while the entry is active."""
        if not self.state.is_attr_blank(ATTR_OSM_ID) and not self.state.is_attr_blank(
            ATTR_OSM_TYPE
        ):
            if self.state.get_attr_safe_str(ATTR_OSM_TYPE).lower() == "node":
                osm_type_abbr = "N"
            elif self.state.get_attr_safe_str(ATTR_OSM_TYPE).lower() == "way":
                osm_type_abbr = "W"
            elif self.state.get_attr_safe_str(ATTR_OSM_TYPE).lower() == "relation":
                osm_type_abbr = "R"
            else:
                _LOGGER.warning(
                    "(%s) Unknown OSM type: %s",
                    self.state.get_attr(CONF_NAME),
                    self.state.get_attr(ATTR_OSM_TYPE),
                )
                return

            osm_details_url: str = OSMClient.details_url(
                osm_type_abbr=osm_type_abbr,
                osm_id=self.state.get_attr(ATTR_OSM_ID),
                language=self.state.get_attr(CONF_LANGUAGE) or "",
                email=self.state.get_attr(CONF_API_KEY) or "",
            )
            await self.get_dict_from_url(
                url=osm_details_url,
                name="OpenStreetMaps Details",
                dict_name=ATTR_OSM_DETAILS_DICT,
            )
            if self.coordinator.is_shutting_down:
                return

            if not self.state.is_attr_blank(ATTR_OSM_DETAILS_DICT):
                osm_details_dict = self.state.get_attr_safe_dict(ATTR_OSM_DETAILS_DICT)
                _LOGGER.debug(
                    "(%s) OSM Details Dict: %s",
                    self.state.get_attr(CONF_NAME),
                    osm_details_dict,
                )

                if (
                    "extratags" in osm_details_dict
                    and osm_details_dict.get("extratags") is not None
                    and "wikidata" in osm_details_dict.get("extratags", {})
                    and osm_details_dict.get("extratags", {}).get("wikidata") is not None
                ):
                    self.state.set_attr(
                        ATTR_WIKIDATA_ID,
                        osm_details_dict.get("extratags", {}).get("wikidata"),
                    )

                self.state.set_attr(ATTR_WIKIDATA_DICT, {})
                if not self.state.is_attr_blank(ATTR_WIKIDATA_ID):
                    wikidata_url: str = OSMClient.wikidata_url(
                        self.state.get_attr(ATTR_WIKIDATA_ID)
                    )
                    await self.get_dict_from_url(
                        url=wikidata_url,
                        name="Wikidata",
                        dict_name=ATTR_WIKIDATA_DICT,
                    )

    async def get_dict_from_url(self, url: str, name: str, dict_name: str) -> None:
        """Fetch JSON with shared throttling and cache it on the HA instance.

        Args:
            url (str):
                Absolute URL to request.
            name (str):
                Human-readable service name used in logs.
            dict_name (str):
                Sensor attribute that receives the parsed JSON payload.
        """
        get_dict = await self._osm_client.get_json(url=url, name=name, use_cache=self._use_cache)
        if dict_name == ATTR_OSM_DICT and isinstance(get_dict, Mapping) and "error" in get_dict:
            # Reverse geocoding may return an HTTP-success error object. Treat
            # it like an empty result so it cannot replace the accepted Place
            # or remain in the shared OSM cache.
            get_dict = {}
        self.state.set_attr(dict_name, get_dict if get_dict is not None else {})
        if get_dict is not None:
            if not self.state.is_attr_blank(dict_name):
                return

            # Empty payloads are not useful lookup results. OSMClient caches
            # every successful response, including empty containers, so remove
            # them even after a forced fetch that bypassed cache reads.
            self._hass.data[DOMAIN][OSM_CACHE].pop(url, None)
            return

        if self._use_cache:
            # Ensure no stale key survives when a normal lookup produced no payload.
            self._hass.data[DOMAIN][OSM_CACHE].pop(url, None)

    async def determine_if_update_needed(self, *, zone_changed: bool = False) -> UpdateStatus:
        """Decide whether movement since the last update warrants geocoding.

        Args:
            zone_changed (bool):
                ``True`` when a device tracker or person's zone differs from the
                last resolved zone. The movement threshold then stays at 10 m instead of
                the GPS accuracy radius, so a zone change inside that radius updates.

        Returns:
            UpdateStatus:
                ``PROCEED`` for initial/unknown/moved states, or
                ``SKIP_SET_STATIONARY`` when the entity has not moved enough.
        """
        proceed_with_update = UpdateStatus.PROCEED

        if self.state.get_attr(ATTR_INITIAL_UPDATE):
            _LOGGER.info(
                "(%s) Performing Initial Update for user",
                self.state.get_attr(CONF_NAME),
            )
            return UpdateStatus.PROCEED

        if self.state.is_attr_blank(ATTR_NATIVE_VALUE) or (
            isinstance(self.state.get_attr(ATTR_NATIVE_VALUE), str)
            and self.state.get_attr_safe_str(ATTR_NATIVE_VALUE).lower()
            in {"none", STATE_UNKNOWN, STATE_UNAVAILABLE}
        ):
            _LOGGER.info(
                "(%s) Previous State is Unknown, performing update",
                self.state.get_attr(CONF_NAME),
            )
            return UpdateStatus.PROCEED

        if self.state.get_attr(ATTR_LOCATION_CURRENT) == self.state.get_attr(
            ATTR_LOCATION_PREVIOUS
        ):
            _LOGGER.info(
                "(%s) Not performing update because coordinates are identical",
                self.state.get_attr(CONF_NAME),
            )
            return UpdateStatus.SKIP_SET_STATIONARY

        # A zone change is not hidden by the accuracy radius; the base threshold still applies.
        threshold_m = MOVEMENT_THRESHOLD_M if zone_changed else self._movement_threshold_m()
        distance_m = self.state.get_attr_safe_float(ATTR_DISTANCE_TRAVELED)
        if distance_m < threshold_m:
            _LOGGER.info(
                "(%s) Not performing update, distance traveled from last update is "
                "less than %s m (%s m)",
                self.state.get_attr(CONF_NAME),
                threshold_m,
                round(distance_m, 1),
            )
            return UpdateStatus.SKIP_SET_STATIONARY

        return proceed_with_update

    def _movement_threshold_m(self) -> float:
        """Return the distance a reading must move to count as movement.

        Returns:
            float:
                ``max(10 m, GPS accuracy)`` when Use GPS Accuracy is on and the
                current reading reports a positive accuracy, otherwise 10 m.
        """
        if self.state.get_attr(CONF_USE_GPS) and not self.state.is_attr_blank(ATTR_GPS_ACCURACY):
            gps_accuracy = self.state.get_attr_safe_float(ATTR_GPS_ACCURACY)
            if gps_accuracy > 0:
                return max(MOVEMENT_THRESHOLD_M, gps_accuracy)
        return MOVEMENT_THRESHOLD_M

    async def update_location_attributes(self) -> None:
        """Store current, previous, and home coordinates as ``lat,lon`` strings."""
        if not self.state.is_attr_blank(ATTR_LATITUDE) and not self.state.is_attr_blank(
            ATTR_LONGITUDE
        ):
            current = CoordinatePair(
                latitude=self.state.get_attr_safe_float(ATTR_LATITUDE),
                longitude=self.state.get_attr_safe_float(ATTR_LONGITUDE),
            )
            self.state.set_attr(
                ATTR_LOCATION_CURRENT,
                str(current),
            )
        if not self.state.is_attr_blank(ATTR_LATITUDE_OLD) and not self.state.is_attr_blank(
            ATTR_LONGITUDE_OLD
        ):
            previous = CoordinatePair(
                latitude=self.state.get_attr_safe_float(ATTR_LATITUDE_OLD),
                longitude=self.state.get_attr_safe_float(ATTR_LONGITUDE_OLD),
            )
            self.state.set_attr(
                ATTR_LOCATION_PREVIOUS,
                str(previous),
            )
        if not self.state.is_attr_blank(ATTR_HOME_LATITUDE) and not self.state.is_attr_blank(
            ATTR_HOME_LONGITUDE
        ):
            home = CoordinatePair(
                latitude=self.state.get_attr_safe_float(ATTR_HOME_LATITUDE),
                longitude=self.state.get_attr_safe_float(ATTR_HOME_LONGITUDE),
            )
            self.state.set_attr(
                ATTR_HOME_LOCATION,
                str(home),
            )

    async def calculate_distances(self) -> None:
        """Calculate distance from home in meters."""
        if (
            not self.state.is_attr_blank(ATTR_LATITUDE)
            and not self.state.is_attr_blank(ATTR_LONGITUDE)
            and not self.state.is_attr_blank(ATTR_HOME_LATITUDE)
            and not self.state.is_attr_blank(ATTR_HOME_LONGITUDE)
        ):
            location_snapshot = LocationSnapshot(
                current=CoordinatePair(
                    latitude=self.state.get_attr_safe_float(ATTR_LATITUDE),
                    longitude=self.state.get_attr_safe_float(ATTR_LONGITUDE),
                ),
                home=CoordinatePair(
                    latitude=self.state.get_attr_safe_float(ATTR_HOME_LATITUDE),
                    longitude=self.state.get_attr_safe_float(ATTR_HOME_LONGITUDE),
                ),
            )
            location_snapshot.calculate()
            self.state.set_attr(
                ATTR_DISTANCE_FROM_HOME,
                location_snapshot.distance_from_home,
            )

    async def calculate_travel_distance(self) -> None:
        """Calculate distance traveled since the previous coordinates."""
        if not self.state.is_attr_blank(ATTR_LATITUDE_OLD) and not self.state.is_attr_blank(
            ATTR_LONGITUDE_OLD
        ):
            location_snapshot = LocationSnapshot(
                current=CoordinatePair(
                    latitude=self.state.get_attr_safe_float(ATTR_LATITUDE),
                    longitude=self.state.get_attr_safe_float(ATTR_LONGITUDE),
                ),
                previous=CoordinatePair(
                    latitude=self.state.get_attr_safe_float(ATTR_LATITUDE_OLD),
                    longitude=self.state.get_attr_safe_float(ATTR_LONGITUDE_OLD),
                ),
            )
            location_snapshot.calculate()
            self.state.set_attr(
                ATTR_DISTANCE_TRAVELED,
                location_snapshot.distance_traveled,
            )
        else:
            self.state.set_attr(ATTR_DIRECTION_OF_TRAVEL, "stationary")
            self.state.set_attr(ATTR_DISTANCE_TRAVELED, 0)

    async def determine_direction_of_travel(self, last_distance_from_home: float) -> None:
        """Classify movement relative to home as towards, away, or stationary.

        Args:
            last_distance_from_home (float):
                Prior distance-from-home value captured
                before recalculating distances.
        """
        if not self.state.is_attr_blank(ATTR_DISTANCE_TRAVELED):
            self.state.set_attr(
                ATTR_DIRECTION_OF_TRAVEL,
                direction_of_travel(
                    previous_distance_from_home=last_distance_from_home,
                    distance_from_home=self.state.get_attr_safe_float(ATTR_DISTANCE_FROM_HOME),
                ),
            )
        else:
            self.state.set_attr(ATTR_DIRECTION_OF_TRAVEL, "stationary")

    async def update_coordinates_and_distance(self) -> UpdateStatus:
        """Refresh derived coordinate, distance, and direction attributes.

        Returns:
            UpdateStatus:
                ``PROCEED`` when current and home coordinates are all usable,
                otherwise ``SKIP``.
        """
        last_distance_from_home: float = self.state.get_attr_safe_float(ATTR_DISTANCE_FROM_HOME)
        proceed_with_update = UpdateStatus.PROCEED

        await self.update_location_attributes()
        await self.calculate_distances()
        await self.calculate_travel_distance()
        await self.determine_direction_of_travel(last_distance_from_home)

        _LOGGER.debug(
            "(%s) Previous Location: %s",
            self.state.get_attr(CONF_NAME),
            self.state.get_attr(ATTR_LOCATION_PREVIOUS),
        )
        _LOGGER.debug(
            "(%s) Current Location: %s",
            self.state.get_attr(CONF_NAME),
            self.state.get_attr(ATTR_LOCATION_CURRENT),
        )
        _LOGGER.debug(
            "(%s) Home Location: %s",
            self.state.get_attr(CONF_NAME),
            self.state.get_attr(ATTR_HOME_LOCATION),
        )
        _LOGGER.info(
            "(%s) Distance from home [%s]: %s m",
            self.state.get_attr(CONF_NAME),
            self.state.get_attr_safe_str(CONF_HOME_ZONE).partition(".")[2]
            or self.state.get_attr_safe_str(CONF_HOME_ZONE),
            self.state.get_attr(ATTR_DISTANCE_FROM_HOME),
        )
        _LOGGER.info(
            "(%s) Travel Direction: %s",
            self.state.get_attr(CONF_NAME),
            self.state.get_attr(ATTR_DIRECTION_OF_TRAVEL),
        )
        _LOGGER.info(
            "(%s) Meters traveled since last update: %s",
            self.state.get_attr(CONF_NAME),
            round(self.state.get_attr_safe_float(ATTR_DISTANCE_TRAVELED), 1),
        )

        if (
            not self.state.is_attr_blank(ATTR_LATITUDE)
            and not self.state.is_attr_blank(ATTR_LONGITUDE)
            and not self.state.is_attr_blank(ATTR_HOME_LATITUDE)
            and not self.state.is_attr_blank(ATTR_HOME_LONGITUDE)
        ):
            return proceed_with_update

        proceed_with_update = UpdateStatus.SKIP
        _LOGGER.info(
            "(%s) Problem with updated lat/long, not performing update: "
            "old_latitude=%s, old_longitude=%s, "
            "new_latitude=%s, new_longitude=%s, "
            "home_latitude=%s, home_longitude=%s",
            self.state.get_attr(CONF_NAME),
            self.state.get_attr_safe_float(ATTR_LATITUDE_OLD),
            self.state.get_attr_safe_float(ATTR_LONGITUDE_OLD),
            self.state.get_attr_safe_float(ATTR_LATITUDE),
            self.state.get_attr_safe_float(ATTR_LONGITUDE),
            self.state.get_attr_safe_float(ATTR_HOME_LATITUDE),
            self.state.get_attr_safe_float(ATTR_HOME_LONGITUDE),
        )
        return proceed_with_update

    async def get_seconds_from_last_change(self, now: datetime) -> int:
        """Calculate elapsed seconds since ``ATTR_LAST_CHANGED``.

        Args:
            now (datetime):
                Current update timestamp.

        Returns:
            int:
                Elapsed seconds, or ``3600`` when the saved timestamp is missing or
                cannot be parsed, or elapsed-time calculation raises
                ``TypeError`` or ``OverflowError``.
        """
        if self.state.is_attr_blank(ATTR_LAST_CHANGED):
            return 3600
        try:
            last_changed: datetime = datetime.fromisoformat(
                self.state.get_attr_safe_str(ATTR_LAST_CHANGED)
            )
            if last_changed.tzinfo is None:
                last_changed = last_changed.replace(tzinfo=now.tzinfo or UTC)
            elif now.tzinfo is not None:
                last_changed = last_changed.astimezone(now.tzinfo)
        except (TypeError, ValueError) as e:
            _LOGGER.warning(
                "Error converting Last Changed date/time (%s) into datetime: %r",
                self.state.get_attr(ATTR_LAST_CHANGED),
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
        if not self.state.is_attr_blank(ATTR_NATIVE_VALUE) and self.state.get_attr(CONF_SHOW_TIME):
            if self.state.get_attr(CONF_DATE_FORMAT) == "dd/mm":
                dateformat = "%d/%m"
            else:
                dateformat = "%m/%d"
            mmddstring: str = (
                datetime.fromisoformat(self.state.get_attr_safe_str(ATTR_LAST_CHANGED))
                .strftime(f"{dateformat}")
                .replace(" ", "")[:5]
            )

            cleared_state = clear_since_from_state(self.state.get_attr_safe_str(ATTR_NATIVE_VALUE))
            suffix = f" (since {mmddstring})"
            self.state.set_native_value(value=f"{cleared_state[: 255 - len(suffix)]}{suffix}")
            self.state.set_attr(ATTR_SHOW_DATE, True)
            _LOGGER.debug(
                "(%s) Updating state to show date instead of time since last change",
                self.state.get_attr(CONF_NAME),
            )
            _LOGGER.debug(
                "(%s) New State: %s",
                self.state.get_attr(CONF_NAME),
                self.state.get_attr(ATTR_NATIVE_VALUE),
            )

    async def change_dot_to_stationary(self, now: datetime, changed_diff_sec: int) -> None:
        """Mark direction as stationary after a skipped movement update.

        Args:
            now (datetime):
                Timestamp to store as the new last-changed value.
            changed_diff_sec (int):
                Seconds since the prior last-changed value, used
                only for diagnostic logging.
        """
        self.state.set_attr(ATTR_DIRECTION_OF_TRAVEL, "stationary")
        self.state.set_attr(ATTR_LAST_CHANGED, now.isoformat(sep=" ", timespec="seconds"))
        _LOGGER.debug(
            "(%s) Updating direction of travel to stationary (Last changed %s seconds ago)",
            self.state.get_attr(CONF_NAME),
            int(changed_diff_sec),
        )

    async def is_devicetracker_set(self) -> UpdateStatus:
        """Validate tracker availability and coordinates before an update.

        Returns:
            UpdateStatus:
                ``PROCEED`` when the tracker can be used, otherwise ``SKIP``.
        """
        if not await self.is_tracker_available():
            return UpdateStatus.SKIP

        if not await self.has_valid_coordinates():
            return UpdateStatus.SKIP

        self.coordinator.warn_if_device_tracker_prob = True
        return UpdateStatus.PROCEED

    async def is_tracker_available(self) -> bool:
        """Return whether the configured tracked entity exists and is available.

        Returns:
            bool:
                ``True`` when Home Assistant has a usable state object for the
                configured tracker.
        """
        tracker_id = self.state.get_attr(CONF_DEVICETRACKER_ID)
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
            bool:
                ``True`` when latitude and longitude attributes both exist and are
                float-convertible.
        """
        tracker_snapshot = TrackerSnapshot.from_hass(
            self._hass, self.state.get_attr(CONF_DEVICETRACKER_ID)
        )
        if not tracker_snapshot.has_valid_coordinates:
            await self.log_coordinate_issue()
            return False

        return True

    async def log_tracker_issue(self, message: str) -> None:
        """Log tracker availability problems at warning or info level.

        Args:
            message (str):
                Specific tracker problem without the standard suffix.
        """
        full_message = f"({self.state.get_attr(CONF_NAME)}) {message}. Not Proceeding with Update"
        if self.coordinator.warn_if_device_tracker_prob or self.state.get_attr(ATTR_INITIAL_UPDATE):
            _LOGGER.warning(full_message)
            self.coordinator.warn_if_device_tracker_prob = False
        else:
            _LOGGER.info(full_message)

    async def log_coordinate_issue(self) -> None:
        """Log missing or invalid tracker coordinates with tracker details."""
        tracker_id = self.state.get_attr_safe_str(CONF_DEVICETRACKER_ID)
        message = (
            f"({self.state.get_attr(CONF_NAME)}) Tracked Entity ({tracker_id}) "
            "Latitude/Longitude is not set or is not a number. "
            "Not Proceeding with Update."
        )

        if self.coordinator.warn_if_device_tracker_prob or self.state.get_attr(ATTR_INITIAL_UPDATE):
            _LOGGER.warning(message)
            self.coordinator.warn_if_device_tracker_prob = False
        else:
            _LOGGER.info(message)

        _LOGGER.debug(
            "(%s) Tracked Entity (%s) details: %s",
            self.state.get_attr(CONF_NAME),
            tracker_id,
            self._hass.states.get(tracker_id),
        )

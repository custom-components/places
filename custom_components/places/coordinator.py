"""Update coordinator and runtime attribute store for Places."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, MutableMapping
import copy
from dataclasses import dataclass, field
from datetime import timedelta
import logging
from time import monotonic
from typing import Any, TypeVar

from homeassistant.components.zone import ATTR_PASSIVE
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_API_KEY,
    CONF_ICON,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_NAME,
    CONF_UNIQUE_ID,
    CONF_ZONE,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import EventStateChangedData, async_track_state_change_event
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import Throttle
from homeassistant.util.file import WriteError
from homeassistant.util.json import SerializationError

from .advanced_options import AdvancedOptionsParser
from .attributes import PlacesAttributes
from .basic_options import BasicOptionsParser
from .const import (
    ATTR_DEVICETRACKER_ID,
    ATTR_DEVICETRACKER_ZONE,
    ATTR_DEVICETRACKER_ZONE_NAME,
    ATTR_DIRECTION_OF_TRAVEL,
    ATTR_DISPLAY_OPTIONS,
    ATTR_DISPLAY_OPTIONS_LIST,
    ATTR_DRIVING,
    ATTR_FORMATTED_PLACE,
    ATTR_HOME_LATITUDE,
    ATTR_HOME_LONGITUDE,
    ATTR_INITIAL_UPDATE,
    ATTR_NATIVE_VALUE,
    ATTR_PICTURE,
    ATTR_PLACE_CATEGORY,
    ATTR_PLACE_TYPE,
    ATTR_SHOW_DATE,
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
    DEFAULT_ICON,
    DEFAULT_MAP_PROVIDER,
    DEFAULT_MAP_ZOOM,
    DEFAULT_SHOW_TIME,
    DEFAULT_USE_GPS,
    DOMAIN,
    EXTENDED_ATTRIBUTE_LIST,
    EXTRA_STATE_ATTRIBUTE_LIST,
    MAIN_STATE_ATTRIBUTE_LIST,
)
from .helpers import is_float
from .persistence import PlacesStorage
from .update_sensor import PlacesUpdater

_LOGGER = logging.getLogger(__name__)
_AttrT = TypeVar("_AttrT", default=Any)
MIN_THROTTLE_INTERVAL = timedelta(seconds=10)
THROTTLE_INTERVAL = timedelta(seconds=600)
SCAN_INTERVAL = timedelta(seconds=30)


@dataclass(frozen=True, slots=True)
class PlacesData:
    """Immutable snapshot of Places coordinator state."""

    native_value: str | None
    attributes: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Copy the attribute mapping to avoid exposing mutable internal state."""
        object.__setattr__(self, "attributes", dict(self.attributes))


class PlacesUpdateCoordinator(DataUpdateCoordinator[PlacesData]):
    """Own Places runtime state, persistence, and tracked-entity subscriptions."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        imported_attributes: MutableMapping[str, Any],
        persistence: PlacesStorage,
    ) -> None:
        """Initialize coordinator state for one Places config entry.

        Args:
            hass: Home Assistant instance.
            config_entry: Config entry backing this Places setup.
            imported_attributes: Persisted runtime attributes restored from Store.
            persistence: Snapshot persistence helper.
        """
        self.hass = hass
        self.config_entry = config_entry
        self.config: MutableMapping[str, Any] = dict(config_entry.data)
        self._places_name = str(self.config.get(CONF_NAME, config_entry.entry_id))
        self._attributes = PlacesAttributes()
        self._persistence = persistence
        self._native_value: str | None = None
        self._tracker_unsubscribe: Callable[[], None] | None = None
        self._update_lock = asyncio.Lock()
        self._last_scan_update: float | None = None
        self.warn_if_device_tracker_prob = False
        self.entity_id: str | None = None
        super().__init__(
            hass,
            _LOGGER,
            name=f"Places {self._places_name}",
            config_entry=config_entry,
            update_interval=SCAN_INTERVAL,
            always_update=False,
        )
        self._initialize_config_attributes()
        self.import_persisted_attributes(imported_attributes)
        self.async_set_updated_data(self.snapshot())

    @property
    def device_info(self) -> DeviceInfo:
        """Return the shared HA Device metadata for this config entry."""
        current_name = self.get_attr_safe_str(CONF_NAME)
        if not current_name:
            current_name = str(self.config_entry.data.get(CONF_NAME, self.config_entry.entry_id))
        return DeviceInfo(
            identifiers={(DOMAIN, self.config_entry.entry_id)},
            name=current_name,
            manufacturer="Places",
            model="OpenStreetMap reverse geocode",
        )

    @property
    def persistence(self) -> PlacesStorage:
        """Return the Store-backed snapshot helper for this config entry."""
        return self._persistence

    @property
    def main_state_attributes(self) -> dict[str, Any]:
        """Return location-context attributes for the display entity."""
        return {
            attr: self.get_attr(attr)
            for attr in MAIN_STATE_ATTRIBUTE_LIST
            if not self.is_attr_blank(attr)
        }

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return non-blank Places entity attributes."""
        self._attributes.cleanup()
        attributes = {
            attr: self.get_attr(attr)
            for attr in EXTRA_STATE_ATTRIBUTE_LIST
            if not self.is_attr_blank(attr)
        }
        if self.get_attr(CONF_EXTENDED_ATTR):
            attributes.update(
                {
                    attr: self.get_attr(attr)
                    for attr in EXTENDED_ATTRIBUTE_LIST
                    if not self.is_attr_blank(attr)
                }
            )
        return attributes

    def _initialize_config_attributes(self) -> None:
        """Seed runtime attributes from static config entry data."""
        self.set_attr(ATTR_INITIAL_UPDATE, True)
        self.set_attr(CONF_NAME, self._places_name)
        self.set_attr(CONF_UNIQUE_ID, self.config_entry.entry_id)
        self.set_attr(CONF_ICON, DEFAULT_ICON)
        self.set_attr(CONF_API_KEY, self.config.get(CONF_API_KEY))
        self.set_attr(
            CONF_DISPLAY_OPTIONS,
            str(self.config.setdefault(CONF_DISPLAY_OPTIONS, DEFAULT_DISPLAY_OPTIONS)).lower(),
        )
        self.set_attr(
            CONF_DEVICETRACKER_ID,
            str(self.config[CONF_DEVICETRACKER_ID]).lower(),
        )
        self.set_attr(
            ATTR_DEVICETRACKER_ID,
            str(self.config[CONF_DEVICETRACKER_ID]).lower(),
        )
        self.set_attr(
            CONF_HOME_ZONE,
            str(self.config.setdefault(CONF_HOME_ZONE, DEFAULT_HOME_ZONE)).lower(),
        )
        self.set_attr(
            CONF_MAP_PROVIDER,
            str(self.config.setdefault(CONF_MAP_PROVIDER, DEFAULT_MAP_PROVIDER)).lower(),
        )
        self.set_attr(CONF_MAP_ZOOM, int(self.config.setdefault(CONF_MAP_ZOOM, DEFAULT_MAP_ZOOM)))
        self.set_attr(CONF_LANGUAGE, self.config.get(CONF_LANGUAGE))
        if not self.is_attr_blank(CONF_LANGUAGE):
            self.set_attr(
                CONF_LANGUAGE,
                self.get_attr_safe_str(CONF_LANGUAGE).replace(" ", "").strip(),
            )
        self.set_attr(
            CONF_EXTENDED_ATTR,
            self.config.setdefault(CONF_EXTENDED_ATTR, DEFAULT_EXTENDED_ATTR),
        )
        self.set_attr(
            CONF_SHOW_TIME,
            self.config.setdefault(CONF_SHOW_TIME, DEFAULT_SHOW_TIME),
        )
        self.set_attr(
            CONF_DATE_FORMAT,
            str(self.config.setdefault(CONF_DATE_FORMAT, DEFAULT_DATE_FORMAT)).lower(),
        )
        self.set_attr(CONF_USE_GPS, self.config.setdefault(CONF_USE_GPS, DEFAULT_USE_GPS))
        self.set_attr(ATTR_DISPLAY_OPTIONS, self.get_attr(CONF_DISPLAY_OPTIONS))
        self.set_attr(ATTR_SHOW_DATE, False)

        home_zone = self.hass.states.get(self.get_attr_safe_str(CONF_HOME_ZONE))
        if (
            home_zone is not None
            and home_zone.attributes.get(CONF_LATITUDE) is not None
            and is_float(home_zone.attributes.get(CONF_LATITUDE))
        ):
            self.set_attr(ATTR_HOME_LATITUDE, float(home_zone.attributes[CONF_LATITUDE]))
        if (
            home_zone is not None
            and home_zone.attributes.get(CONF_LONGITUDE) is not None
            and is_float(home_zone.attributes.get(CONF_LONGITUDE))
        ):
            self.set_attr(ATTR_HOME_LONGITUDE, float(home_zone.attributes[CONF_LONGITUDE]))

        tracker_state = self.hass.states.get(self.get_attr_safe_str(CONF_DEVICETRACKER_ID))
        self.set_attr(
            ATTR_PICTURE,
            tracker_state.attributes.get(ATTR_PICTURE) if tracker_state is not None else None,
        )

    def snapshot(self) -> PlacesData:
        """Return an immutable snapshot of current runtime state."""
        return PlacesData(
            native_value=self._native_value,
            attributes=dict(self.get_internal_attr()),
        )

    def publish_update(self) -> None:
        """Publish the latest runtime snapshot to coordinator listeners."""
        self.async_set_updated_data(self.snapshot())

    def get_internal_attr(self) -> MutableMapping[str, Any]:
        """Return the mutable runtime attribute mapping."""
        return self._attributes.data

    def is_attr_blank(self, attr: str) -> bool:
        """Return whether a stored attribute is blank."""
        return self._attributes.is_blank(attr)

    def get_attr(self, attr: str | None, default: _AttrT | None = None) -> _AttrT | None:
        """Read a stored runtime attribute."""
        return self._attributes.get(attr, default)

    def get_attr_safe_str(self, attr: str | None, default: object | None = None) -> str:
        """Read a stored runtime attribute as a safe string."""
        return self._attributes.safe_str(attr, default)

    def get_attr_safe_float(self, attr: str | None, default: object | None = None) -> float:
        """Read a stored runtime attribute as a safe float."""
        return self._attributes.safe_float(attr, default)

    def get_attr_safe_list(self, attr: str | None, default: object | None = None) -> list[Any]:
        """Read a stored runtime attribute as a safe list."""
        return self._attributes.safe_list(attr, default)

    def get_attr_safe_dict(
        self, attr: str | None, default: MutableMapping[str, _AttrT] | None = None
    ) -> MutableMapping[str, _AttrT]:
        """Read a stored runtime attribute as a safe mapping."""
        return self._attributes.safe_dict(attr, default)

    def set_attr(self, attr: str, value: object | None = None) -> None:
        """Store a runtime attribute."""
        self._attributes.set(attr, value)

    def clear_attr(self, attr: str) -> None:
        """Remove a runtime attribute."""
        self._attributes.clear(attr)
        if attr == ATTR_NATIVE_VALUE:
            self._native_value = None

    def set_native_value(self, value: object) -> None:
        """Update the display state and mirror it into runtime attributes."""
        if value is None:
            self._native_value = None
            self.clear_attr(ATTR_NATIVE_VALUE)
            return
        self._native_value = str(value)
        self.set_attr(ATTR_NATIVE_VALUE, self._native_value)

    def import_persisted_attributes(self, persisted_attr: MutableMapping[str, Any]) -> None:
        """Restore runtime attributes from persisted storage."""
        if persisted_attr:
            self.set_attr(ATTR_INITIAL_UPDATE, False)
        self._attributes.import_persisted_attributes(persisted_attr)
        if not self.is_attr_blank(ATTR_NATIVE_VALUE):
            self._native_value = self.get_attr_safe_str(ATTR_NATIVE_VALUE)
        if persisted_attr:
            _LOGGER.debug(
                "(%s) [import_persisted_attributes] Attributes not imported: %s",
                self.get_attr(CONF_NAME),
                persisted_attr,
            )

    async def async_persist_attributes(self) -> None:
        """Persist the current runtime attributes."""
        try:
            await self._persistence.async_save(self.get_internal_attr())
        except (OSError, TypeError, ValueError, SerializationError, WriteError) as error:
            _LOGGER.warning(
                "(%s) Could not persist Places attributes: %s: %s",
                self.get_attr(CONF_NAME),
                type(error).__name__,
                error,
            )

    async def async_cleanup_attributes(self) -> None:
        """Remove blank runtime attributes."""
        self._attributes.cleanup()

    async def async_added_to_hass(self) -> None:
        """Subscribe to tracked-entity state changes."""
        self._tracker_unsubscribe = async_track_state_change_event(
            self.hass,
            [str(self.get_attr(CONF_DEVICETRACKER_ID))],
            self.tsc_update,
        )

    async def async_shutdown(self) -> None:
        """Unsubscribe coordinator callbacks during entry unload."""
        if self._tracker_unsubscribe is not None:
            self._tracker_unsubscribe()
            self._tracker_unsubscribe = None
        await super().async_shutdown()

    async def _async_update_data(self) -> PlacesData:
        """Run the periodic Places refresh path and return the latest snapshot."""
        return await self.async_scan_update()

    async def async_scan_update(self) -> PlacesData:
        """Run a throttled scan-interval update and return the latest snapshot."""
        now = monotonic()
        if (
            self._last_scan_update is not None
            and now - self._last_scan_update < THROTTLE_INTERVAL.total_seconds()
        ):
            return self.snapshot()

        await self._run_update("Scan Interval")
        self._last_scan_update = now
        return self.snapshot()

    async def _run_update(self, reason: str) -> None:
        """Run one update cycle while serializing concurrent invocations."""
        async with self._update_lock:
            previous_attr = copy.deepcopy(self.get_internal_attr())
            await PlacesUpdater(
                hass=self.hass,
                config_entry=self.config_entry,
                coordinator=self,
            ).do_update(
                reason=reason,
                previous_attr=previous_attr,
            )

    @Throttle(MIN_THROTTLE_INTERVAL)
    @callback
    def tsc_update(self, event: Event[EventStateChangedData]) -> None:
        """Schedule an update from a tracked-entity state change.

        Args:
            event: Tracked entity state change event.
        """
        new_state = event.data["new_state"]
        if new_state is None or (
            isinstance(new_state.state, str)
            and new_state.state.lower() in {"none", STATE_UNKNOWN, STATE_UNAVAILABLE}
        ):
            return

        self.hass.async_create_task(
            self._run_update(
                reason="Track State Change",
            )
        )

    async def in_zone(self) -> bool:
        """Return whether the tracked entity is in a real non-passive zone."""
        if not self.is_attr_blank(ATTR_DEVICETRACKER_ZONE):
            zone = self.get_attr_safe_str(ATTR_DEVICETRACKER_ZONE).lower()
            zone_state = self.hass.states.get(f"{CONF_ZONE}.{zone}")
            if (
                self.get_attr_safe_str(CONF_DEVICETRACKER_ID).split(".")[0] == CONF_ZONE
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

    async def get_driving_status(self) -> None:
        """Set the driving marker when movement implies road travel."""
        self.clear_attr(ATTR_DRIVING)
        is_driving = False
        if (
            not await self.in_zone()
            and self.get_attr(ATTR_DIRECTION_OF_TRAVEL) != "stationary"
            and (
                self.get_attr(ATTR_PLACE_CATEGORY) == "highway"
                or self.get_attr(ATTR_PLACE_TYPE) == "motorway"
            )
        ):
            is_driving = True
        if is_driving:
            self.set_attr(ATTR_DRIVING, "Driving")

    async def process_display_options(self) -> None:
        """Render configured display options into the native value."""
        display_options: list[str] = []
        if not self.is_attr_blank(ATTR_DISPLAY_OPTIONS):
            display_options.extend(
                option.strip() for option in self.get_attr_safe_str(ATTR_DISPLAY_OPTIONS).split(",")
            )
        self.set_attr(ATTR_DISPLAY_OPTIONS_LIST, display_options)

        await self.get_driving_status()

        if "formatted_place" in display_options:
            basic_parser = BasicOptionsParser(
                sensor=self,
                internal_attr=self.get_internal_attr(),
                display_options=self.get_attr_safe_list(ATTR_DISPLAY_OPTIONS_LIST),
            )
            formatted_place = await basic_parser.build_formatted_place()
            self.set_attr(ATTR_FORMATTED_PLACE, formatted_place)
            self.set_attr(ATTR_NATIVE_VALUE, self.get_attr(ATTR_FORMATTED_PLACE))
            self._native_value = self.get_attr_safe_str(ATTR_NATIVE_VALUE) or None
            return

        if any(ext in self.get_attr_safe_str(ATTR_DISPLAY_OPTIONS) for ext in ["(", ")", "[", "]"]):
            advanced_parser = AdvancedOptionsParser(
                sensor=self,
                curr_options=self.get_attr_safe_str(ATTR_DISPLAY_OPTIONS),
            )
            await advanced_parser.build_from_advanced_options()
            self.set_attr(ATTR_NATIVE_VALUE, await advanced_parser.compile_state())
            self._native_value = self.get_attr_safe_str(ATTR_NATIVE_VALUE) or None
            return

        if not await self.in_zone():
            basic_parser = BasicOptionsParser(
                sensor=self,
                internal_attr=self.get_internal_attr(),
                display_options=self.get_attr_safe_list(ATTR_DISPLAY_OPTIONS_LIST),
            )
            state = await basic_parser.build_display()
            if state:
                self.set_attr(ATTR_NATIVE_VALUE, state)
                self._native_value = state
            return

        if (
            "zone" in display_options and not self.is_attr_blank(ATTR_DEVICETRACKER_ZONE)
        ) or self.is_attr_blank(ATTR_DEVICETRACKER_ZONE_NAME):
            self.set_attr(ATTR_NATIVE_VALUE, self.get_attr(ATTR_DEVICETRACKER_ZONE))
            self._native_value = self.get_attr_safe_str(ATTR_NATIVE_VALUE) or None
            return

        if not self.is_attr_blank(ATTR_DEVICETRACKER_ZONE_NAME):
            self.set_attr(ATTR_NATIVE_VALUE, self.get_attr(ATTR_DEVICETRACKER_ZONE_NAME))
            self._native_value = self.get_attr_safe_str(ATTR_NATIVE_VALUE) or None

    async def restore_previous_attr(self, previous_attr: MutableMapping[str, Any]) -> None:
        """Restore a prior runtime attribute snapshot after rollback."""
        self._attributes.data = previous_attr
        native_value = self.get_attr(ATTR_NATIVE_VALUE)
        self._native_value = str(native_value) if native_value is not None else None

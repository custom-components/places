"""Place Support for OpenStreetMap Geocode sensors.

Previous Authors:  Jim Thompson, Ian Richardson
Current Author:  Snuffy2

Description:
  Provides reverse geocode details for a linked GPS device_tracker entity.
  Calculates distance from home and direction of travel.
  Configuration Instructions are on GitHub.

GitHub: https://github.com/custom-components/places
"""

from __future__ import annotations

import asyncio
from collections.abc import MutableMapping
import copy
from datetime import timedelta
import locale
import logging
from typing import Any, TypeVar

import cachetools
from homeassistant.components.recorder import DATA_INSTANCE as RECORDER_INSTANCE
from homeassistant.components.sensor import SensorEntity
from homeassistant.components.zone import ATTR_PASSIVE
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import (
    CONF_API_KEY,
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
    ENTITY_ID_FORMAT,
    EVENT_TYPE,
    EXTENDED_ATTRIBUTE_LIST,
    EXTRA_STATE_ATTRIBUTE_LIST,
    OSM_CACHE,
    OSM_CACHE_MAX_AGE_HOURS,
    OSM_CACHE_MAX_SIZE,
    OSM_THROTTLE,
    PLATFORM,
)
from .helpers import is_float
from .persistence import PlacesStorage
from .update_sensor import PlacesUpdater

_LOGGER: logging.Logger = logging.getLogger(__name__)
_AttrT = TypeVar("_AttrT", default=Any)
THROTTLE_INTERVAL = timedelta(seconds=600)
MIN_THROTTLE_INTERVAL = timedelta(seconds=10)
SCAN_INTERVAL = timedelta(seconds=30)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Places sensor entity for a config entry.

    Args:
        hass: Home Assistant instance.
        config_entry: Places config entry being set up.
        async_add_entities: Home Assistant callback used to add created
            entities to the sensor platform.
    """
    # _LOGGER.debug("[aync_setup_entity] all entities: %s", hass.data.get(DOMAIN))

    config: MutableMapping[str, Any] = dict(config_entry.data)
    unique_id: str = config_entry.entry_id
    name: str = config[CONF_NAME]
    persistence = PlacesStorage(hass=hass, entry_id=unique_id, name=name)
    imported_attributes: MutableMapping[str, Any] = await persistence.async_load()
    # _LOGGER.debug("[async_setup_entry] name: %s", name)
    # _LOGGER.debug("[async_setup_entry] unique_id: %s", unique_id)
    # _LOGGER.debug("[async_setup_entry] config: %s", config)

    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}
    if OSM_CACHE not in hass.data[DOMAIN]:
        hass.data[DOMAIN][OSM_CACHE] = cachetools.TTLCache(
            maxsize=OSM_CACHE_MAX_SIZE, ttl=OSM_CACHE_MAX_AGE_HOURS * 3600
        )
    if OSM_THROTTLE not in hass.data[DOMAIN]:
        hass.data[DOMAIN][OSM_THROTTLE] = {
            "lock": asyncio.Lock(),
            "last_query": 0.0,
        }

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
                    persistence=persistence,
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
                    persistence=persistence,
                )
            ],
            update_before_add=True,
        )


class Places(SensorEntity):
    """Home Assistant sensor that reverse-geocodes a tracked entity."""

    def __init__(
        self,
        hass: HomeAssistant,
        config: MutableMapping[str, Any],
        config_entry: ConfigEntry,
        name: str,
        unique_id: str,
        imported_attributes: MutableMapping[str, Any],
        persistence: PlacesStorage,
    ) -> None:
        """Initialize a Places sensor and restore persisted attributes.

        Args:
            hass: Home Assistant instance that owns this entity.
            config: Config entry data copied into sensor attributes.
            config_entry: Source config entry for updates and reloads.
            name: User-facing sensor name.
            unique_id: Stable Home Assistant unique ID.
            imported_attributes: Previously persisted sensor attributes loaded
                from Store.
            persistence: Store-backed persistence for this config entry.
        """
        self._attr_should_poll = True
        _LOGGER.info("(%s) [Init] Places sensor: %s", name, name)
        _LOGGER.debug("(%s) [Init] System Locale: %s", name, locale.getlocale())
        _LOGGER.debug(
            "(%s) [Init] System Locale Date Format: %s", name, locale.nl_langinfo(locale.D_FMT)
        )
        _LOGGER.debug("(%s) [Init] HASS TimeZone: %s", name, hass.config.time_zone)

        self.warn_if_device_tracker_prob = False
        self._attributes = PlacesAttributes()
        self._internal_attr: MutableMapping[str, Any] = self._attributes.data
        self.set_attr(ATTR_INITIAL_UPDATE, True)
        self._config_entry: ConfigEntry = config_entry
        self._hass: HomeAssistant = hass
        self._persistence: PlacesStorage = persistence
        self.set_attr(CONF_NAME, name)
        self._attr_name: str = name
        self.set_attr(CONF_UNIQUE_ID, unique_id)
        self._attr_unique_id: str = unique_id
        registry: er.EntityRegistry | None = er.async_get(self._hass)
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
        self._adv_options_state_list: list = []
        self.set_attr(CONF_ICON, DEFAULT_ICON)
        self._attr_icon = DEFAULT_ICON
        self.set_attr(CONF_API_KEY, config.get(CONF_API_KEY))
        self.set_attr(
            CONF_DISPLAY_OPTIONS,
            config.setdefault(CONF_DISPLAY_OPTIONS, DEFAULT_DISPLAY_OPTIONS).lower(),
        )
        self.set_attr(CONF_DEVICETRACKER_ID, config[CONF_DEVICETRACKER_ID].lower())
        # Consider reconciling this in the future
        self.set_attr(ATTR_DEVICETRACKER_ID, config[CONF_DEVICETRACKER_ID].lower())
        self.set_attr(CONF_HOME_ZONE, config.setdefault(CONF_HOME_ZONE, DEFAULT_HOME_ZONE).lower())
        self.set_attr(
            CONF_MAP_PROVIDER,
            config.setdefault(CONF_MAP_PROVIDER, DEFAULT_MAP_PROVIDER).lower(),
        )
        self.set_attr(CONF_MAP_ZOOM, int(config.setdefault(CONF_MAP_ZOOM, DEFAULT_MAP_ZOOM)))
        self.set_attr(CONF_LANGUAGE, config.get(CONF_LANGUAGE))

        if not self.is_attr_blank(CONF_LANGUAGE):
            self.set_attr(
                CONF_LANGUAGE,
                self.get_attr_safe_str(CONF_LANGUAGE).replace(" ", "").strip(),
            )
        self.set_attr(
            CONF_EXTENDED_ATTR,
            config.setdefault(CONF_EXTENDED_ATTR, DEFAULT_EXTENDED_ATTR),
        )
        self.set_attr(CONF_SHOW_TIME, config.setdefault(CONF_SHOW_TIME, DEFAULT_SHOW_TIME))
        self.set_attr(
            CONF_DATE_FORMAT,
            config.setdefault(CONF_DATE_FORMAT, DEFAULT_DATE_FORMAT).lower(),
        )
        self.set_attr(CONF_USE_GPS, config.setdefault(CONF_USE_GPS, DEFAULT_USE_GPS))
        self.set_attr(ATTR_DISPLAY_OPTIONS, self.get_attr(CONF_DISPLAY_OPTIONS))

        self._attr_native_value = None  # Represents the state in SensorEntity
        self.clear_attr(ATTR_NATIVE_VALUE)

        if (
            not self.is_attr_blank(CONF_HOME_ZONE)
            and CONF_LATITUDE in hass.states.get(self.get_attr(CONF_HOME_ZONE)).attributes
            and hass.states.get(self.get_attr(CONF_HOME_ZONE)).attributes.get(CONF_LATITUDE)
            is not None
            and is_float(
                hass.states.get(self.get_attr(CONF_HOME_ZONE)).attributes.get(CONF_LATITUDE)
            )
        ):
            self.set_attr(
                ATTR_HOME_LATITUDE,
                float(hass.states.get(self.get_attr(CONF_HOME_ZONE)).attributes.get(CONF_LATITUDE)),
            )
        if (
            not self.is_attr_blank(CONF_HOME_ZONE)
            and CONF_LONGITUDE in hass.states.get(self.get_attr(CONF_HOME_ZONE)).attributes
            and hass.states.get(self.get_attr(CONF_HOME_ZONE)).attributes.get(CONF_LONGITUDE)
            is not None
            and is_float(
                hass.states.get(self.get_attr(CONF_HOME_ZONE)).attributes.get(CONF_LONGITUDE)
            )
        ):
            self.set_attr(
                ATTR_HOME_LONGITUDE,
                float(
                    hass.states.get(self.get_attr(CONF_HOME_ZONE)).attributes.get(CONF_LONGITUDE)
                ),
            )

        self._attr_entity_picture = (
            hass.states.get(self.get_attr(CONF_DEVICETRACKER_ID)).attributes.get(ATTR_PICTURE)
            if hass.states.get(self.get_attr(CONF_DEVICETRACKER_ID))
            else None
        )
        self.set_attr(ATTR_SHOW_DATE, False)

        self.import_persisted_attributes(imported_attributes)
        ##
        # For debugging:
        # imported_attributes = {}
        # imported_attributes.update({CONF_NAME: self.get_attr(CONF_NAME)})
        # imported_attributes.update({ATTR_NATIVE_VALUE: self.get_attr(ATTR_NATIVE_VALUE)})
        # imported_attributes.update(self.extra_state_attributes)
        ##
        if not self.get_attr(ATTR_INITIAL_UPDATE):
            _LOGGER.debug(
                "(%s) [Init] Sensor attributes imported from persisted snapshot",
                self.get_attr(CONF_NAME),
            )
        self.cleanup_attributes()
        if self.get_attr(CONF_EXTENDED_ATTR):
            self.exclude_event_types()
        _LOGGER.info(
            "(%s) [Init] Tracked Entity ID: %s",
            self.get_attr(CONF_NAME),
            self.get_attr(CONF_DEVICETRACKER_ID),
        )

    def set_native_value(self, value: Any) -> None:
        """Update the entity state and mirror it into internal attributes.

        Args:
            value: New state value. ``None`` clears both the entity state and
                the persisted native-value attribute.
        """
        if value is not None:
            self._attr_native_value = value
            self.set_attr(ATTR_NATIVE_VALUE, value)
        else:
            self._attr_native_value = None
            self.clear_attr(ATTR_NATIVE_VALUE)

    def get_internal_attr(self) -> MutableMapping[str, Any]:
        """Return the mutable attribute store used for state and persistence.

        Returns:
            Internal sensor attribute mapping.
        """
        self._sync_internal_attr()
        return self._internal_attr

    def _sync_internal_attr(self) -> None:
        """Synchronize direct ``_internal_attr`` assignment with the attribute store."""
        if self._internal_attr is not self._attributes.data:
            self._attributes.data = self._internal_attr

    def exclude_event_types(self) -> None:
        """Exclude high-cardinality Places update events from HA recorder."""
        if RECORDER_INSTANCE in self._hass.data:
            ha_history_recorder = self._hass.data[RECORDER_INSTANCE]
            ha_history_recorder.exclude_event_types.add(EVENT_TYPE)
            _LOGGER.debug(
                "(%s) exclude_event_types: %s",
                self.get_attr(CONF_NAME),
                ha_history_recorder.exclude_event_types,
            )

    async def async_added_to_hass(self) -> None:
        """Subscribe to tracked-entity state changes after HA adds the entity."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_track_state_change_event(
                self._hass,
                [str(self.get_attr(CONF_DEVICETRACKER_ID))],
                self.tsc_update,
            )
        )
        _LOGGER.debug(
            "(%s) [Init] Subscribed to Tracked Entity state change events",
            self.get_attr(CONF_NAME),
        )

    async def async_will_remove_from_hass(self) -> None:
        """Clean up recorder exclusions before entity removal."""
        if (
            RECORDER_INSTANCE in self._hass.data
            and self.get_attr(CONF_EXTENDED_ATTR)
            and self._hass.config_entries is not None
        ):
            _LOGGER.debug(
                "(%s) Removing entity exclusion from recorder: %s", self._attr_name, self._entity_id
            )
            # Only remove recorder exclusion when no other loaded Places entries
            # still have extended_attr enabled.
            extended_count = 0
            for config_entry in self._hass.config_entries.async_entries(DOMAIN):
                if config_entry is self._config_entry:
                    continue
                if config_entry.state is ConfigEntryState.LOADED and config_entry.data.get(
                    CONF_EXTENDED_ATTR
                ):
                    extended_count += 1

            if extended_count == 0:
                _LOGGER.debug(
                    "(%s) Removing event exclusion from recorder: %s",
                    self.get_attr(CONF_NAME),
                    EVENT_TYPE,
                )
                ha_history_recorder = self._hass.data[RECORDER_INSTANCE]
                ha_history_recorder.exclude_event_types.discard(EVENT_TYPE)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return non-blank attributes exposed on the HA sensor entity.

        Returns:
            Mapping of normal attributes, plus extended attributes when enabled.
        """
        return_attr: dict[str, Any] = {}
        self.cleanup_attributes()
        for attr in EXTRA_STATE_ATTRIBUTE_LIST:
            if self.get_attr(attr):
                return_attr.update({attr: self.get_attr(attr)})

        if self.get_attr(CONF_EXTENDED_ATTR):
            for attr in EXTENDED_ATTRIBUTE_LIST:
                if self.get_attr(attr):
                    return_attr.update({attr: self.get_attr(attr)})
        # _LOGGER.debug("(%s) Extra State Attributes: %s", self.get_attr(CONF_NAME), return_attr)
        return return_attr

    async def async_persist_attributes(self) -> None:
        """Persist the current runtime attributes to Home Assistant Store."""
        try:
            await self._persistence.async_save(self.get_internal_attr())
        except (OSError, TypeError, ValueError, SerializationError, WriteError) as error:
            _LOGGER.warning(
                "(%s) Could not persist Places attributes: %s: %s",
                self.get_attr(CONF_NAME),
                type(error).__name__,
                error,
            )

    def import_persisted_attributes(self, persisted_attr: MutableMapping[str, Any]) -> None:
        """Restore persisted runtime attributes from a stored snapshot.

        Args:
            persisted_attr: Mapping loaded from persisted data.
                Imported and ignored keys are removed from this mapping.
        """
        self.set_attr(ATTR_INITIAL_UPDATE, False)
        self._attributes.import_persisted_attributes(persisted_attr)
        if not self.is_attr_blank(ATTR_NATIVE_VALUE):
            self._attr_native_value = self.get_attr(ATTR_NATIVE_VALUE)

        if persisted_attr is not None and persisted_attr:
            _LOGGER.debug(
                "(%s) [import_persisted_attributes] Attributes not imported: %s",
                self.get_attr(CONF_NAME),
                persisted_attr,
            )

    def cleanup_attributes(self) -> None:
        """Remove blank attributes from the internal attribute mapping."""
        self._sync_internal_attr()
        self._attributes.cleanup()

    def is_attr_blank(self, attr: str) -> bool:
        """Return whether an internal attribute is absent or falsey except zero.

        Args:
            attr: Attribute key to inspect.

        Returns:
            ``True`` when the value is missing or falsey, with numeric zero
            treated as a meaningful value.
        """
        self._sync_internal_attr()
        return self._attributes.is_blank(attr)

    def get_attr(self, attr: str | None, default: _AttrT | None = None) -> _AttrT | None:
        """Read an internal attribute with optional default handling.

        Args:
            attr: Attribute key to read. ``None`` always returns ``None``.
            default: Fallback returned when the key is missing.

        Returns:
            Stored value, ``default``, or ``None`` when the attribute is blank
            and no default was supplied.
        """
        self._sync_internal_attr()
        return self._attributes.get(attr, default)

    def get_attr_safe_str(self, attr: str | None, default: object | None = None) -> str:
        """Read an internal attribute as text without propagating conversion errors.

        Args:
            attr: Attribute key to read.
            default: Fallback used when the key is missing.

        Returns:
            String value, or an empty string when the value is missing or cannot
            be converted.
        """
        self._sync_internal_attr()
        return self._attributes.safe_str(attr, default)

    def get_attr_safe_float(self, attr: str | None, default: object | None = None) -> float:
        """Read an internal attribute as a float.

        Args:
            attr: Attribute key to read.
            default: Fallback used when the key is missing.

        Returns:
            Converted float value, or ``0.0`` when conversion is not possible.
        """
        self._sync_internal_attr()
        return self._attributes.safe_float(attr, default)

    def get_attr_safe_list(self, attr: str | None, default: object | None = None) -> list:
        """Read an internal attribute as a list.

        Args:
            attr: Attribute key to read.
            default: Fallback used when the key is missing.

        Returns:
            Stored list value, or an empty list for non-list values.
        """
        self._sync_internal_attr()
        return self._attributes.safe_list(attr, default)

    def get_attr_safe_dict(
        self, attr: str | None, default: MutableMapping[str, _AttrT] | None = None
    ) -> MutableMapping[str, _AttrT]:
        """Read an internal attribute as a mutable mapping.

        Args:
            attr: Attribute key to read.
            default: Fallback used when the key is missing.

        Returns:
            Stored mapping value, or an empty mapping for non-mapping values.
        """
        self._sync_internal_attr()
        return self._attributes.safe_dict(attr, default)

    def set_attr(self, attr: str, value: object | None = None) -> None:
        """Store a value in the internal attribute mapping.

        Args:
            attr: Attribute key to update.
            value: Value to store.
        """
        self._sync_internal_attr()
        self._attributes.set(attr, value)
        self._internal_attr = self._attributes.data

    def clear_attr(self, attr: str) -> None:
        """Remove an internal attribute if present.

        Args:
            attr: Attribute key to remove.
        """
        self._sync_internal_attr()
        self._attributes.clear(attr)
        self._internal_attr = self._attributes.data

    @Throttle(MIN_THROTTLE_INTERVAL)
    @callback
    def tsc_update(self, event: Event[EventStateChangedData]) -> None:
        """Schedule an update from a tracked-entity state-change event.

        Args:
            event: Home Assistant state-change event for the configured tracked
                entity.
        """
        # _LOGGER.debug(f"({self.get_attr(CONF_NAME)}) [TSC Update] event: {event}")
        new_state = event.data["new_state"]
        if new_state is None or (
            isinstance(new_state.state, str)
            and new_state.state.lower() in {"none", STATE_UNKNOWN, STATE_UNAVAILABLE}
        ):
            return
        # _LOGGER.debug("(%s) [TSC Update] new_state: %s", self.get_attr(CONF_NAME), new_state)

        update_type: str = "Track State Change"
        self._hass.async_create_task(self.do_update(update_type))

    @Throttle(THROTTLE_INTERVAL)
    async def async_update(self) -> None:
        """Schedule a throttled update from Home Assistant polling."""
        update_type = "Scan Interval"
        self._hass.async_create_task(self.do_update(update_type))

    async def in_zone(self) -> bool:
        """Return whether the tracked entity is in a real non-passive zone.

        Returns:
            ``True`` for normal zones and ``False`` for not-home, stationary,
            passive, or zone-backed tracker states.
        """
        if not self.is_attr_blank(ATTR_DEVICETRACKER_ZONE):
            zone: str = self.get_attr_safe_str(ATTR_DEVICETRACKER_ZONE).lower()
            zone_state = self._hass.states.get(f"{CONF_ZONE}.{zone}")
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

    async def async_cleanup_attributes(self) -> None:
        """Asynchronously remove blank attributes from the internal mapping."""
        attrs: MutableMapping[str, Any] = copy.deepcopy(self.get_internal_attr())
        for attr in attrs:
            if self.is_attr_blank(attr):
                self.clear_attr(attr)

    async def get_driving_status(self) -> None:
        """Set the driving attribute when movement and OSM type indicate driving."""
        self.clear_attr(ATTR_DRIVING)
        is_driving: bool = False
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

    async def do_update(self, reason: str) -> None:
        """Run the update pipeline through ``PlacesUpdater``.

        Args:
            reason: Human-readable trigger reason used in logs.
        """
        self._sync_internal_attr()
        updater = PlacesUpdater(hass=self._hass, config_entry=self._config_entry, sensor=self)
        await updater.do_update(reason=reason, previous_attr=copy.deepcopy(self._internal_attr))

    async def process_display_options(self) -> None:
        """Render the configured display options into ``ATTR_NATIVE_VALUE``."""
        display_options: list[str] = []
        if not self.is_attr_blank(ATTR_DISPLAY_OPTIONS):
            options_array: list[str] = self.get_attr_safe_str(ATTR_DISPLAY_OPTIONS).split(",")
            for option in options_array:
                display_options.extend([option.strip()])
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
            self.set_attr(
                ATTR_NATIVE_VALUE,
                self.get_attr(ATTR_FORMATTED_PLACE),
            )
            _LOGGER.debug(
                "(%s) New State using formatted_place: %s",
                self.get_attr(CONF_NAME),
                self.get_attr(ATTR_NATIVE_VALUE),
            )
        elif any(
            ext in (self.get_attr_safe_str(ATTR_DISPLAY_OPTIONS)) for ext in ["(", ")", "[", "]"]
        ):
            advanced_parser = AdvancedOptionsParser(
                sensor=self, curr_options=self.get_attr_safe_str(ATTR_DISPLAY_OPTIONS)
            )
            await advanced_parser.build_from_advanced_options()
            state = await advanced_parser.compile_state()
            self.set_attr(ATTR_NATIVE_VALUE, state)
            _LOGGER.debug(
                "(%s) New State from Advanced Display Options: %s",
                self.get_attr(CONF_NAME),
                self.get_attr(ATTR_NATIVE_VALUE),
            )
        elif not await self.in_zone():
            basic_parser = BasicOptionsParser(
                sensor=self,
                internal_attr=self.get_internal_attr(),
                display_options=self.get_attr_safe_list(ATTR_DISPLAY_OPTIONS_LIST),
            )
            state = await basic_parser.build_display()
            if state:
                self.set_attr(ATTR_NATIVE_VALUE, state)
            _LOGGER.debug(
                "(%s) New State from Display Options: %s",
                self.get_attr(CONF_NAME),
                self.get_attr(ATTR_NATIVE_VALUE),
            )
        elif (
            "zone" in display_options and not self.is_attr_blank(ATTR_DEVICETRACKER_ZONE)
        ) or self.is_attr_blank(ATTR_DEVICETRACKER_ZONE_NAME):
            self.set_attr(
                ATTR_NATIVE_VALUE,
                self.get_attr(ATTR_DEVICETRACKER_ZONE),
            )
            _LOGGER.debug(
                "(%s) New State from Tracked Entity Zone: %s",
                self.get_attr(CONF_NAME),
                self.get_attr(ATTR_NATIVE_VALUE),
            )
        elif not self.is_attr_blank(ATTR_DEVICETRACKER_ZONE_NAME):
            self.set_attr(
                ATTR_NATIVE_VALUE,
                self.get_attr(ATTR_DEVICETRACKER_ZONE_NAME),
            )
            _LOGGER.debug(
                "(%s) New State from Tracked Entity Zone Name: %s",
                self.get_attr(CONF_NAME),
                self.get_attr(ATTR_NATIVE_VALUE),
            )

    async def restore_previous_attr(self, previous_attr: MutableMapping[str, Any]) -> None:
        """Replace current attributes with a previous snapshot after rollback.

        Args:
            previous_attr: Attribute mapping captured before the failed or
                skipped update.
        """
        self._attributes.data = previous_attr
        self._internal_attr = self._attributes.data


class PlacesNoRecorder(Places):
    """Places sensor variant that opts all attributes out of HA recorder."""

    _unrecorded_attributes = frozenset({MATCH_ALL})

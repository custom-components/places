"""Tracker snapshot primitives for Places."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any, cast

from homeassistant.const import (
    ATTR_ENTITY_PICTURE,
    ATTR_FRIENDLY_NAME,
    ATTR_GPS_ACCURACY,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_ZONE,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant

from .helpers import is_float


class TrackerStatus(Enum):
    """Enumeration of tracker snapshot resolution states."""

    OK = auto()
    MISSING_ENTITY_ID = auto()
    NOT_FOUND = auto()
    UNAVAILABLE = auto()
    MISSING_COORDINATES = auto()
    INVALID_COORDINATES = auto()


@dataclass(slots=True)
class TrackerSnapshot:
    """Captured state and location for a tracked entity."""

    entity_id: str | None
    state: str | None
    status: TrackerStatus
    latitude: float | None
    longitude: float | None
    gps_accuracy: float | None
    zone: str | None
    zone_name: str | None
    entity_picture: str | None

    @classmethod
    def from_hass(cls, hass: HomeAssistant, entity_id: str | None) -> TrackerSnapshot:
        """Build a tracker snapshot from ``hass.states.get``.

        Args:
            hass: Home Assistant instance used to fetch tracker state.
            entity_id: Tracker entity ID to look up in HA state registry.

        Returns:
            Snapshot describing tracker availability, state, and location data.
        """
        has_entity_id = bool(entity_id)
        state_obj: Any = hass.states.get(entity_id)
        if not has_entity_id and state_obj is None:
            return cls(
                entity_id=entity_id,
                state=None,
                status=TrackerStatus.MISSING_ENTITY_ID,
                latitude=None,
                longitude=None,
                gps_accuracy=None,
                zone=None,
                zone_name=None,
                entity_picture=None,
            )
        if state_obj is None:
            return cls(
                entity_id=entity_id,
                state=None,
                status=TrackerStatus.NOT_FOUND,
                latitude=None,
                longitude=None,
                gps_accuracy=None,
                zone=None,
                zone_name=None,
                entity_picture=None,
            )

        tracker_state: str | None
        if isinstance(state_obj, str):
            tracker_state = state_obj
        else:
            tracker_state = state_obj.state if hasattr(state_obj, "state") else None
            if not isinstance(tracker_state, str):
                tracker_state = None

        is_raw_state = isinstance(state_obj, str)
        if (
            is_raw_state
            and tracker_state is not None
            and tracker_state.lower()
            in {
                "none",
                STATE_UNKNOWN.lower(),
                STATE_UNAVAILABLE.lower(),
            }
        ):
            return cls(
                entity_id=entity_id,
                state=tracker_state,
                status=TrackerStatus.UNAVAILABLE,
                latitude=None,
                longitude=None,
                gps_accuracy=None,
                zone=None,
                zone_name=None,
                entity_picture=None,
            )

        raw_attributes = getattr(state_obj, "attributes", None)
        get_attr = cast("Callable[..., object]", getattr(raw_attributes, "get", None))
        if not callable(get_attr):
            return cls(
                entity_id=entity_id,
                state=tracker_state,
                status=TrackerStatus.MISSING_COORDINATES,
                latitude=None,
                longitude=None,
                gps_accuracy=None,
                zone=None,
                zone_name=None,
                entity_picture=None,
            )

        zone = get_attr(CONF_ZONE)
        zone = zone if isinstance(zone, str) else None
        zone_name = get_attr(ATTR_FRIENDLY_NAME)
        zone_name = zone_name if isinstance(zone_name, str) else None
        entity_picture = get_attr(ATTR_ENTITY_PICTURE)
        entity_picture = entity_picture if isinstance(entity_picture, str) else None

        sentinel = object()
        try:
            latitude_value = get_attr(CONF_LATITUDE, sentinel)
        except TypeError:
            latitude_value = get_attr(CONF_LATITUDE)
            has_latitude = latitude_value is not None
        else:
            has_latitude = latitude_value is not sentinel

        try:
            longitude_value = get_attr(CONF_LONGITUDE, sentinel)
        except TypeError:
            longitude_value = get_attr(CONF_LONGITUDE)
            has_longitude = longitude_value is not None
        else:
            has_longitude = longitude_value is not sentinel

        try:
            gps_accuracy_value = get_attr(ATTR_GPS_ACCURACY, sentinel)
        except TypeError:
            gps_accuracy_value = get_attr(ATTR_GPS_ACCURACY)

        status = TrackerStatus.OK
        if not has_latitude or not has_longitude:
            status = TrackerStatus.MISSING_COORDINATES
        elif not is_float(latitude_value) or not is_float(longitude_value):
            status = TrackerStatus.INVALID_COORDINATES
        latitude = (
            float(latitude_value)
            if isinstance(latitude_value, (int, float, str)) and is_float(latitude_value)
            else None
        )
        longitude = (
            float(longitude_value)
            if isinstance(longitude_value, (int, float, str)) and is_float(longitude_value)
            else None
        )
        gps_accuracy = (
            float(gps_accuracy_value)
            if isinstance(gps_accuracy_value, (int, float, str)) and is_float(gps_accuracy_value)
            else None
        )

        return cls(
            entity_id=entity_id,
            state=tracker_state,
            status=status,
            latitude=latitude,
            longitude=longitude,
            gps_accuracy=gps_accuracy,
            zone=zone,
            zone_name=zone_name,
            entity_picture=entity_picture,
        )

    @property
    def has_valid_coordinates(self) -> bool:
        """Return whether both coordinate values are parseable."""
        return self.status == TrackerStatus.OK

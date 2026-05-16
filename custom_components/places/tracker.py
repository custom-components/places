"""Tracker snapshot primitives for Places."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any

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

        if isinstance(tracker_state, str) and tracker_state.lower() in {
            "none",
            STATE_UNKNOWN.lower(),
            STATE_UNAVAILABLE.lower(),
        }:
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
        if not isinstance(raw_attributes, Mapping):
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

        zone = raw_attributes.get(CONF_ZONE)
        zone_name = raw_attributes.get(ATTR_FRIENDLY_NAME)
        entity_picture = raw_attributes.get(ATTR_ENTITY_PICTURE)

        latitude_value = raw_attributes.get(CONF_LATITUDE)
        longitude_value = raw_attributes.get(CONF_LONGITUDE)
        gps_accuracy_value = raw_attributes.get(ATTR_GPS_ACCURACY)

        status = TrackerStatus.OK
        if CONF_LATITUDE not in raw_attributes or CONF_LONGITUDE not in raw_attributes:
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

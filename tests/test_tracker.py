"""Characterization tests for tracked entity handling."""

from decimal import Decimal
from unittest.mock import MagicMock

from homeassistant.const import (
    ATTR_GPS_ACCURACY,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.places.const import (
    ATTR_LATITUDE as PLACES_ATTR_LATITUDE,
    ATTR_LONGITUDE as PLACES_ATTR_LONGITUDE,
    CONF_DEVICETRACKER_ID,
    UpdateStatus,
)
from custom_components.places.tracker import TrackerSnapshot, TrackerStatus
from custom_components.places.update_sensor import PlacesUpdater
from tests.conftest import MockSensor


class _TrackerAttributeMapping:
    """Minimal duck-typed mapping used by tracker attributes tests."""

    def __init__(self, values: dict[str, object]) -> None:
        """Store an internal mapping for ``get`` access."""
        self._values = values

    def get(self, key: str, default: object | None = None) -> object | None:
        """Return a value from the stored attributes."""
        return self._values.get(key, default)


class _TrackerAttributesWithoutDefault:
    """Duck-typed attributes object whose ``get`` does not accept a default."""

    def __init__(self, values: dict[str, object]) -> None:
        """Store an internal mapping for single-argument ``get`` access."""
        self._values = values

    def get(self, key: str) -> object | None:
        """Return a value from the stored attributes."""
        return self._values.get(key)


@pytest.mark.parametrize(
    ("tracker_id", "state_lookup_result", "expect_state_lookup"),
    [
        ("device_tracker.missing", None, True),
        (None, None, False),
        ("", None, False),
    ],
)
async def test_tracker_missing_or_blank_id_skips_update(
    mock_hass: MagicMock,
    mock_config_entry: MockConfigEntry,
    sensor: MockSensor,
    tracker_id: str | None,
    state_lookup_result: object | None,
    expect_state_lookup: bool,
) -> None:
    """Missing entities and blank tracked entity IDs skip updates."""
    sensor.attrs[CONF_DEVICETRACKER_ID] = tracker_id
    mock_hass.states.get.return_value = state_lookup_result
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)

    result = await updater.is_devicetracker_set()

    assert result is UpdateStatus.SKIP
    if expect_state_lookup:
        mock_hass.states.get.assert_called_once_with(tracker_id)
    else:
        mock_hass.states.get.assert_not_called()


async def test_tracker_invalid_coordinates_skip_update(
    mock_hass: MagicMock, mock_config_entry: MockConfigEntry, sensor: MockSensor
) -> None:
    """Non-numeric coordinates skip updates."""
    sensor.attrs[CONF_DEVICETRACKER_ID] = "device_tracker.person"
    tracker = MagicMock()
    tracker.attributes = {CONF_LATITUDE: "north", CONF_LONGITUDE: "-70.0"}
    mock_hass.states.get.return_value = tracker
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)

    result = await updater.has_valid_coordinates()
    gate_result = await updater.is_devicetracker_set()

    assert result is False
    assert gate_result is UpdateStatus.SKIP


async def test_tracker_attributes_with_get_only_preserves_ok_path(
    mock_hass: MagicMock, mock_config_entry: MockConfigEntry, sensor: MockSensor
) -> None:
    """Non-Mapping attribute objects with `.get` preserve tracker coordinate flow."""
    sensor.attrs[CONF_DEVICETRACKER_ID] = "device_tracker.person"
    tracker = MagicMock()
    tracker.attributes = _TrackerAttributeMapping(
        {CONF_LATITUDE: "1.23", CONF_LONGITUDE: "4.56", ATTR_GPS_ACCURACY: "7"}
    )
    mock_hass.states.get.return_value = tracker
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)

    assert await updater.has_valid_coordinates() is True
    await updater.update_coordinates()

    assert sensor.attrs[PLACES_ATTR_LATITUDE] == 1.23
    assert sensor.attrs[PLACES_ATTR_LONGITUDE] == 4.56


async def test_tracker_float_like_coordinates_are_converted(
    mock_hass: MagicMock, mock_config_entry: MockConfigEntry, sensor: MockSensor
) -> None:
    """Float-compatible non-primitive values update tracker coordinates."""
    sensor.attrs[CONF_DEVICETRACKER_ID] = "device_tracker.person"
    tracker = MagicMock()
    tracker.attributes = {
        CONF_LATITUDE: Decimal("1.23"),
        CONF_LONGITUDE: Decimal("4.56"),
        ATTR_GPS_ACCURACY: Decimal(7),
    }
    mock_hass.states.get.return_value = tracker
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)

    assert await updater.has_valid_coordinates() is True
    await updater.update_coordinates()
    snapshot = TrackerSnapshot.from_hass(mock_hass, "device_tracker.person")

    assert sensor.attrs[PLACES_ATTR_LATITUDE] == 1.23
    assert sensor.attrs[PLACES_ATTR_LONGITUDE] == 4.56
    assert snapshot.status is TrackerStatus.OK
    assert snapshot.gps_accuracy == 7.0


async def test_tracker_get_without_default_treats_none_coordinates_as_missing(
    mock_hass: MagicMock,
) -> None:
    """Fallback ``get`` calls treat returned ``None`` coordinates as missing."""
    tracker = MagicMock()
    tracker.entity_id = "device_tracker.person"
    tracker.state = "home"
    tracker.attributes = _TrackerAttributesWithoutDefault(
        {CONF_LATITUDE: None, CONF_LONGITUDE: None}
    )
    mock_hass.states.get.return_value = tracker

    snapshot = TrackerSnapshot.from_hass(mock_hass, "device_tracker.person")

    assert snapshot.status is TrackerStatus.MISSING_COORDINATES
    assert snapshot.latitude is None
    assert snapshot.longitude is None


async def _assert_tracker_state_can_proceed_with_coordinates(
    mock_hass: MagicMock,
    mock_config_entry: MockConfigEntry,
    sensor: MockSensor,
    tracker_state: str,
) -> None:
    """Return PROCEED when state-like tracker has usable coordinates."""
    sensor.attrs[CONF_DEVICETRACKER_ID] = "device_tracker.person"
    tracker = MagicMock()
    tracker.state = tracker_state
    tracker.attributes = {CONF_LATITUDE: "1.23", CONF_LONGITUDE: "4.56"}
    mock_hass.states.get.return_value = tracker
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)

    result = await updater.is_devicetracker_set()

    assert result is UpdateStatus.PROCEED


@pytest.mark.parametrize("tracker_state", [STATE_UNKNOWN, STATE_UNAVAILABLE])
async def test_tracker_state_object_with_coordinates_can_proceed(
    mock_hass: MagicMock,
    mock_config_entry: MockConfigEntry,
    sensor: MockSensor,
    tracker_state: str,
) -> None:
    """HA state-like objects with unknown/unavailable state still use coordinates."""
    await _assert_tracker_state_can_proceed_with_coordinates(
        mock_hass, mock_config_entry, sensor, tracker_state
    )

"""Characterization tests for tracked entity handling."""

from unittest.mock import MagicMock

from homeassistant.const import (
    ATTR_GPS_ACCURACY,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.places.const import (
    ATTR_GPS_ACCURACY as PLACES_GPS_ACCURACY,
    ATTR_LATITUDE as PLACES_ATTR_LATITUDE,
    ATTR_LONGITUDE as PLACES_ATTR_LONGITUDE,
    CONF_DEVICETRACKER_ID,
    CONF_USE_GPS,
    UpdateStatus,
)
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


async def test_tracker_missing_skips_update(
    mock_hass: MagicMock, mock_config_entry: MockConfigEntry, sensor: MockSensor
) -> None:
    """Missing tracked entities skip update without coordinates."""
    sensor.attrs[CONF_DEVICETRACKER_ID] = "device_tracker.missing"
    mock_hass.states.get.return_value = None
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)

    result = await updater.is_devicetracker_set()

    assert result is UpdateStatus.SKIP


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


async def test_tracker_zero_gps_accuracy_skips_when_enabled(
    mock_hass: MagicMock, mock_config_entry: MockConfigEntry, sensor: MockSensor
) -> None:
    """GPS accuracy zero preserves the existing skip behavior."""
    sensor.attrs[CONF_DEVICETRACKER_ID] = "device_tracker.person"
    sensor.attrs[CONF_USE_GPS] = True
    tracker = MagicMock()
    tracker.attributes = {ATTR_GPS_ACCURACY: 0}
    mock_hass.states.get.return_value = tracker
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)

    result = await updater.get_gps_accuracy()

    assert result is UpdateStatus.SKIP
    assert sensor.attrs[PLACES_GPS_ACCURACY] == 0.0


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


async def test_tracker_state_object_unknown_with_coordinates_can_proceed(
    mock_hass: MagicMock, mock_config_entry: MockConfigEntry, sensor: MockSensor
) -> None:
    """HA state-like objects with unknown/unavailable state still use coordinates."""
    await _assert_tracker_state_can_proceed_with_coordinates(
        mock_hass, mock_config_entry, sensor, STATE_UNKNOWN
    )


async def test_tracker_state_object_unavailable_with_coordinates_can_proceed(
    mock_hass: MagicMock, mock_config_entry: MockConfigEntry, sensor: MockSensor
) -> None:
    """HA state-like objects with unavailable state still use coordinates."""
    await _assert_tracker_state_can_proceed_with_coordinates(
        mock_hass, mock_config_entry, sensor, STATE_UNAVAILABLE
    )

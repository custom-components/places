"""Characterization tests for tracked entity handling."""

from unittest.mock import MagicMock

from homeassistant.const import ATTR_GPS_ACCURACY, CONF_LATITUDE, CONF_LONGITUDE
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.places.const import (
    ATTR_GPS_ACCURACY as PLACES_GPS_ACCURACY,
    CONF_DEVICETRACKER_ID,
    CONF_USE_GPS,
    UpdateStatus,
)
from custom_components.places.update_sensor import PlacesUpdater
from tests.conftest import MockSensor


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

    assert result is False


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

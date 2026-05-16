"""Characterization tests for Places location calculations."""

from unittest.mock import MagicMock

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.places.const import (
    ATTR_DIRECTION_OF_TRAVEL,
    ATTR_DISTANCE_FROM_HOME_KM,
    ATTR_DISTANCE_FROM_HOME_M,
    ATTR_DISTANCE_FROM_HOME_MI,
    ATTR_DISTANCE_TRAVELED_M,
    ATTR_HOME_LATITUDE,
    ATTR_HOME_LOCATION,
    ATTR_HOME_LONGITUDE,
    ATTR_LATITUDE,
    ATTR_LATITUDE_OLD,
    ATTR_LOCATION_CURRENT,
    ATTR_LOCATION_PREVIOUS,
    ATTR_LONGITUDE,
    ATTR_LONGITUDE_OLD,
    METERS_PER_MILE,
)
from custom_components.places.update_sensor import PlacesUpdater
from tests.conftest import MockSensor


async def test_location_strings_are_current_format(
    mock_hass: MagicMock, mock_config_entry: MockConfigEntry, sensor: MockSensor
) -> None:
    """Location string formatting stays compatible."""
    sensor.attrs.update(
        {
            ATTR_LATITUDE: 40.1,
            ATTR_LONGITUDE: -70.2,
            ATTR_LATITUDE_OLD: 40.0,
            ATTR_LONGITUDE_OLD: -70.0,
            ATTR_HOME_LATITUDE: 39.9,
            ATTR_HOME_LONGITUDE: -69.9,
        }
    )
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)

    await updater.update_location_attributes()

    for attr_name, expected in {
        ATTR_LOCATION_CURRENT: (40.1, -70.2),
        ATTR_LOCATION_PREVIOUS: (40.0, -70.0),
        ATTR_HOME_LOCATION: (39.9, -69.9),
    }.items():
        location = sensor.attrs[attr_name]
        assert isinstance(location, str)
        assert "," in location
        assert location.count(",") == 1
        assert " " not in location
        lat_str, lon_str = location.split(",")
        assert float(lat_str) == expected[0]
        assert float(lon_str) == expected[1]


async def test_distance_fields_are_populated(
    mock_hass: MagicMock, mock_config_entry: MockConfigEntry, sensor: MockSensor
) -> None:
    """Distance calculations populate meters, kilometers, and miles."""
    sensor.attrs.update(
        {
            ATTR_LATITUDE: 40.1,
            ATTR_LONGITUDE: -70.2,
            ATTR_HOME_LATITUDE: 40.0,
            ATTR_HOME_LONGITUDE: -70.0,
        }
    )
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)

    await updater.calculate_distances()

    distance_m = sensor.attrs[ATTR_DISTANCE_FROM_HOME_M]
    distance_km = sensor.attrs[ATTR_DISTANCE_FROM_HOME_KM]
    distance_mi = sensor.attrs[ATTR_DISTANCE_FROM_HOME_MI]
    assert distance_m > 0
    assert distance_km == round(distance_m / 1000, 3)
    assert distance_mi == round(distance_m / METERS_PER_MILE, 3)


async def test_direction_of_travel_stationary_when_distance_unchanged(
    mock_hass: MagicMock, mock_config_entry: MockConfigEntry, sensor: MockSensor
) -> None:
    """Direction remains stationary when distance from home is unchanged."""
    sensor.attrs[ATTR_DISTANCE_TRAVELED_M] = 1.0
    sensor.attrs[ATTR_DISTANCE_FROM_HOME_M] = 100.0
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)

    await updater.determine_direction_of_travel(last_distance_traveled_m=100.0)

    assert sensor.attrs[ATTR_DIRECTION_OF_TRAVEL] == "stationary"

"""Characterization tests for OSM request behavior."""

from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.places.const import (
    ATTR_LATITUDE,
    ATTR_LONGITUDE,
    ATTR_OSM_DICT,
    CONF_API_KEY,
    CONF_LANGUAGE,
    DOMAIN,
    OSM_CACHE,
    OSM_THROTTLE,
)
from custom_components.places.update_sensor import PlacesUpdater
from tests.conftest import MockSensor


@pytest.mark.asyncio
async def test_reverse_osm_url_parameters(
    mock_hass: HomeAssistant, mock_config_entry: MockConfigEntry, sensor: MockSensor
) -> None:
    """Reverse lookup URL parameters remain stable."""
    sensor.attrs.update(
        {
            ATTR_LATITUDE: 40.123,
            ATTR_LONGITUDE: -70.456,
            CONF_LANGUAGE: "en,fr",
            CONF_API_KEY: "person@example.com",
        }
    )
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)

    url = await updater.build_osm_url()
    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    assert parsed.netloc == "nominatim.openstreetmap.org"
    assert query["format"] == ["json"]
    assert query["lat"] == ["40.123"]
    assert query["lon"] == ["-70.456"]
    assert query["accept-language"] == ["en,fr"]
    assert query["addressdetails"] == ["1"]
    assert query["namedetails"] == ["1"]
    assert query["zoom"] == ["18"]
    assert query["limit"] == ["1"]
    assert query["email"] == ["person@example.com"]


@pytest.mark.asyncio
async def test_get_dict_from_url_uses_existing_cache(
    mock_hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    sensor: MockSensor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cached OSM responses are used without network calls."""
    url = "https://example.test/osm"
    cached = {"place_id": 123}
    mock_hass.data = {
        DOMAIN: {
            OSM_CACHE: {url: cached},
            OSM_THROTTLE: {"lock": None, "last_query": 0.0},
        }
    }
    client_session_getter = AsyncMock()
    monkeypatch.setattr(
        "custom_components.places.update_sensor.async_get_clientsession",
        client_session_getter,
    )

    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    await updater.get_dict_from_url(url=url, name="OpenStreetMaps", dict_name=ATTR_OSM_DICT)

    assert sensor.attrs[ATTR_OSM_DICT] == cached
    client_session_getter.assert_not_called()

"""Unit tests for shared OSM request behavior."""

from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

from homeassistant.core import HomeAssistant
import pytest

from custom_components.places.const import DOMAIN, OSM_CACHE, OSM_THROTTLE
from custom_components.places.osm_client import OSMClient


@pytest.mark.asyncio
async def test_reverse_url_matches_nominatim_query_contract(mock_hass: HomeAssistant) -> None:
    """Reverse URL params remain stable for latitude/longitude lookup."""
    url = OSMClient.reverse_url(
        latitude=40.123,
        longitude=-70.456,
        language="en,fr",
        email="person@example.com",
    )
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
async def test_get_json_uses_existing_cache_without_network(
    mock_hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cached OSM payloads are returned without session calls."""
    mock_hass.data = {
        DOMAIN: {
            OSM_CACHE: {"https://example.test/osm": {"place_id": 123}},
            OSM_THROTTLE: {"lock": None, "last_query": 0.0},
        }
    }

    client_session_getter = AsyncMock()
    monkeypatch.setattr(
        "custom_components.places.osm_client.async_get_clientsession",
        client_session_getter,
    )

    client = OSMClient(hass=mock_hass, sensor_name="TestSensor")
    result = await client.get_json(url="https://example.test/osm", name="OpenStreetMaps")

    assert result == {"place_id": 123}
    client_session_getter.assert_not_called()


@pytest.mark.asyncio
async def test_details_url_preserves_lookup_semantics() -> None:
    """Lookup URL matches the historical query shape used by the integration."""
    assert (
        OSMClient.details_url(
            osm_type_abbr="N",
            osm_id="12345",
            language="en",
            email="person@example.com",
        )
        == "https://nominatim.openstreetmap.org/lookup?osm_ids=N12345&format=json&addressdetails=1&extratags=1&namedetails=1&email=person@example.com&accept-language=en"
    )


@pytest.mark.asyncio
async def test_wikidata_url_preserves_lookup_semantics() -> None:
    """Wikidata URL remains stable."""
    assert (
        OSMClient.wikidata_url("Q123")
        == "https://www.wikidata.org/wiki/Special:EntityData/Q123.json"
    )

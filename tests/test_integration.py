"""Integration tests for the custom_components.places module."""

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import UTC, datetime, timedelta
import json
import logging
from math import ceil
from pathlib import Path
from threading import Event as ThreadEvent
from time import monotonic
from types import SimpleNamespace
from typing import ClassVar
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qs, urlparse

import cachetools
from homeassistant.components.recorder import DATA_INSTANCE
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    EVENT_HOMEASSISTANT_FINAL_WRITE,
    EVENT_HOMEASSISTANT_STOP,
    STATE_UNAVAILABLE,
)
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import EventStateChangedData, async_track_state_change_event
import pytest
from pytest_homeassistant.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
)
from pytest_homeassistant.test_util.aiohttp import AiohttpClientMocker

from custom_components.places import (
    _ensure_osm_runtime_state,
    async_migrate_entry,
    async_remove_entry,
    async_remove_extended_entity,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.places.const import (
    ATTR_CITY,
    ATTR_DEVICETRACKER_ZONE,
    ATTR_DEVICETRACKER_ZONE_NAME,
    ATTR_DIRECTION_OF_TRAVEL,
    ATTR_GPS_ACCURACY_SOURCES,
    ATTR_LAST_CHANGED,
    ATTR_LAST_UPDATED,
    ATTR_LATITUDE,
    ATTR_LATITUDE_OLD,
    ATTR_LONGITUDE,
    ATTR_LONGITUDE_OLD,
    ATTR_MAP_LINK,
    ATTR_NATIVE_VALUE,
    ATTR_POSTAL_CODE,
    ATTR_SHOW_DATE,
    CONF_API_KEY,
    CONF_DATE_FORMAT,
    CONF_DEVICETRACKER_ID,
    CONF_DISPLAY_OPTIONS,
    CONF_EXTENDED_ATTR,
    CONF_NAME,
    CONF_SHOW_TIME,
    CONF_USE_GPS,
    DEFAULT_DISPLAY_OPTIONS,
    DOMAIN,
    EVENT_TYPE,
    OSM_CACHE,
    OSM_THROTTLE,
    PLATFORMS,
)
from custom_components.places.coordinator import PlacesUpdateCoordinator
from custom_components.places.migration import legacy_json_path
from custom_components.places.persistence import PlacesStorage
from tests.conftest import assert_awaited_count


@pytest.mark.usefixtures("enable_custom_integrations")
@pytest.mark.parametrize("blank_payload", ["{}", "[]", '{"error":"Unable to geocode"}'])
@pytest.mark.parametrize("restored", [False, True], ids=["new-entry", "restored-entry"])
async def test_entry_keeps_accepted_place_until_lookup_recovers(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    blank_payload: str,
    *,
    restored: bool,
) -> None:
    """Keep the sensors and Store coherent from the first Place through OSM recovery.

    Args:
        hass (HomeAssistant): Home Assistant runtime with real Places entities.
        monkeypatch (pytest.MonkeyPatch): Replacements for the clock and HTTP boundary.
        blank_payload (str): Unusable JSON body returned for the moved coordinates.
        restored (bool): Whether to seed the accepted Place through Store before setup.
    """
    now = datetime(2026, 11, 24, 12, tzinfo=UTC)
    scan_clock = 1000.0
    monkeypatch.setattr(
        "custom_components.places.update_sensor.PlacesUpdater.get_current_time",
        AsyncMock(side_effect=lambda: now),
    )
    monkeypatch.setattr("custom_components.places.coordinator.monotonic", lambda: scan_clock)
    monkeypatch.setattr("custom_components.places.osm_client.OSM_THROTTLE_INTERVAL_SECONDS", 0)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Probe",
        data={
            CONF_NAME: "Probe",
            CONF_DEVICETRACKER_ID: "device_tracker.probe",
            CONF_DISPLAY_OPTIONS: "city",
            CONF_EXTENDED_ATTR: False,
            CONF_SHOW_TIME: False,
        },
    )
    entry.add_to_hass(hass)
    storage = PlacesStorage(hass, entry.entry_id, "Probe")
    accepted_link = "https://maps.apple.com/?q=51.5%2C-0.1&z=18"
    if restored:
        await storage.async_save(
            {
                ATTR_NATIVE_VALUE: "Stale display text",
                ATTR_CITY: "London",
                ATTR_LATITUDE: 51.5,
                ATTR_LONGITUDE: -0.1,
                ATTR_LATITUDE_OLD: 51.4,
                ATTR_LONGITUDE_OLD: -0.2,
                ATTR_MAP_LINK: accepted_link,
                ATTR_LAST_CHANGED: "2026-11-24 11:00:00+00:00",
            }
        )
    hass.states.async_set("zone.home", "0", {"latitude": 51.4, "longitude": -0.1})
    hass.states.async_set("device_tracker.probe", "not_home", {"latitude": 51.5, "longitude": -0.1})

    requests: list[str] = []
    in_flight: list[tuple[str | None, float, str]] = []

    def get_response(url: str, **_kwargs: object) -> MagicMock:
        """Return the appropriate OSM response and observe the accepted snapshot.

        Args:
            url (str): Requested reverse-geocode URL.
            _kwargs (object): HTTP request options.

        Returns:
            MagicMock: Async response context for the requested coordinates.
        """
        latitude = parse_qs(urlparse(url).query)["lat"][0]
        requests.append(latitude)
        if latitude == "51.7" and requests.count(latitude) == 1:
            snapshot = entry.runtime_data.snapshot()
            in_flight.append(
                (
                    snapshot.native_value,
                    snapshot.attributes[ATTR_LATITUDE],
                    snapshot.attributes[ATTR_MAP_LINK],
                )
            )
            body = blank_payload
        else:
            body = json.dumps(
                {
                    "osm_id": 1,
                    "osm_type": "node",
                    "category": "place",
                    "type": "city",
                    "address": {"city": "London" if latitude == "51.5" else "Oxford"},
                }
            )
        response = MagicMock(status=200, text=AsyncMock(return_value=body))
        return MagicMock(__aenter__=AsyncMock(return_value=response))

    session = MagicMock()
    session.get.side_effect = get_response
    monkeypatch.setattr(
        "custom_components.places.osm_client.async_get_clientsession", lambda _hass: session
    )

    events: list[tuple[dict[str, object], str, str]] = []

    @callback
    def record_event(event: Event) -> None:
        """Read published sensor states from the Places event listener.

        Args:
            event (Event): Places state update event.
        """
        main = hass.states.get("sensor.probe")
        city = hass.states.get("sensor.probe_city")
        assert main is not None and city is not None
        events.append((event.data, main.state, city.state))

    hass.bus.async_listen(EVENT_TYPE, record_event)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator: PlacesUpdateCoordinator = entry.runtime_data
    main = hass.states.get("sensor.probe")
    city = hass.states.get("sensor.probe_city")
    link = hass.states.get("sensor.probe_map_link")
    assert main is not None and city is not None and link is not None
    assert main.state == city.state == "London"
    assert main.attributes[ATTR_LATITUDE] == 51.5
    assert link.state == accepted_link
    assert requests == ([] if restored else ["51.5"])
    assert len(events) == (0 if restored else 1)
    events.clear()
    accepted = await storage.async_load()

    now += timedelta(minutes=10)
    hass.states.async_set("device_tracker.probe", "away", {"latitude": 51.7, "longitude": -0.1})
    await hass.async_block_till_done()
    assert hass.states.get("sensor.probe") == main
    assert hass.states.get("sensor.probe_city") == city
    assert hass.states.get("sensor.probe_map_link") == link
    failed = await storage.async_load()
    assert failed == {**accepted, ATTR_LAST_UPDATED: "2026-11-24 12:10:00+00:00"}
    assert not events

    now += timedelta(minutes=10)
    scan_clock += 600
    await coordinator.async_scan_update()
    await hass.async_block_till_done()
    assert len(events) == 1
    event, main_state, city_state = events[0]
    assert event["from_state"] == "London"
    assert event["to_state"] == main_state == city_state == "Oxford"
    assert event["latitude"] == 51.7
    assert event["longitude"] == -0.1
    assert event["previous_latitude"] == 51.5
    assert event["previous_longitude"] == -0.1
    assert event["zone"] == "away"
    assert event["last_changed"] == "2026-11-24 12:20:00+00:00"
    assert "osm_dict" not in event
    assert "street" not in event
    recovered = await storage.async_load()
    assert recovered[ATTR_NATIVE_VALUE] == recovered[ATTR_CITY] == "Oxford"
    assert recovered[ATTR_LAST_UPDATED] == recovered[ATTR_LAST_CHANGED] == event["last_changed"]
    assert recovered[ATTR_LATITUDE] == 51.7
    assert recovered[ATTR_LONGITUDE] == -0.1
    assert recovered[ATTR_LATITUDE_OLD] == 51.5
    assert recovered[ATTR_LONGITUDE_OLD] == -0.1
    assert recovered[ATTR_MAP_LINK] == event["map_link"]
    main = hass.states.get("sensor.probe")
    link = hass.states.get("sensor.probe_map_link")
    assert main is not None and link is not None
    assert main.attributes[ATTR_LATITUDE] == 51.7
    assert link.state == event["map_link"] == "https://maps.apple.com/?q=51.7%2C-0.1&z=18"

    now += timedelta(minutes=10)
    scan_clock += 600
    await coordinator.async_scan_update()
    await hass.async_block_till_done()
    assert requests == (["51.7", "51.7"] if restored else ["51.5", "51.7", "51.7"])
    assert len(events) == 1
    assert in_flight == [("London", 51.5, accepted_link)]


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_entry_maintains_zone_and_time_while_retaining_place(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Publish retained Place maintenance and keep using the accepted coordinates.

    Args:
        hass (HomeAssistant): Home Assistant runtime with real Places entities.
        monkeypatch (pytest.MonkeyPatch): Replacements for the clocks and HTTP boundary.
    """
    now = datetime(2026, 11, 24, 12, tzinfo=UTC)
    scan_clock = 1000.0
    monkeypatch.setattr(
        "custom_components.places.update_sensor.PlacesUpdater.get_current_time",
        AsyncMock(side_effect=lambda: now),
    )
    monkeypatch.setattr("homeassistant.util.utcnow", lambda: now)
    monkeypatch.setattr("custom_components.places.coordinator.monotonic", lambda: scan_clock)
    monkeypatch.setattr("custom_components.places.osm_client.OSM_THROTTLE_INTERVAL_SECONDS", 0)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Probe",
        data={
            CONF_NAME: "Probe",
            CONF_DEVICETRACKER_ID: "device_tracker.probe",
            CONF_DISPLAY_OPTIONS: "city",
            CONF_EXTENDED_ATTR: False,
            CONF_SHOW_TIME: True,
            CONF_DATE_FORMAT: "dd/mm",
        },
    )
    entry.add_to_hass(hass)
    storage = PlacesStorage(hass, entry.entry_id, "Probe")
    hass.states.async_set("zone.home", "0", {"latitude": 51.4, "longitude": -0.1})
    hass.states.async_set("zone.work", "0", {"friendly_name": "Office"})
    hass.states.async_set("device_tracker.probe", "away", {"latitude": 51.5, "longitude": -0.1})

    requests: list[str] = []

    def get_response(url: str, **_kwargs: object) -> MagicMock:
        """Return the same Place text with fresh OSM details, or an empty result.

        Args:
            url (str): Requested reverse-geocode URL.
            _kwargs (object): HTTP request options.

        Returns:
            MagicMock: Async response context for the requested coordinates.
        """
        latitude = parse_qs(urlparse(url).query)["lat"][0]
        requests.append(latitude)
        body = (
            "{}"
            if latitude == "51.50023"
            else json.dumps(
                {
                    "osm_id": len(requests),
                    "osm_type": "node",
                    "category": "place",
                    "type": "city",
                    "address": {"city": "London"},
                }
            )
        )
        response = MagicMock(status=200, text=AsyncMock(return_value=body))
        return MagicMock(__aenter__=AsyncMock(return_value=response))

    session = MagicMock()
    session.get.side_effect = get_response
    monkeypatch.setattr(
        "custom_components.places.osm_client.async_get_clientsession", lambda _hass: session
    )
    events = async_capture_events(hass, EVENT_TYPE)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator: PlacesUpdateCoordinator = entry.runtime_data
    accepted = await storage.async_load()
    assert len(events) == 1
    events.clear()

    async def assert_retained(expected: dict[str, object], zone_name: str) -> None:
        """Compare the retained snapshot and its Home Assistant states.

        Args:
            expected (dict[str, object]): Snapshot with only permitted maintenance changes.
            zone_name (str): Published Current zone name, or unknown after clearing.
        """
        assert await storage.async_load() == expected
        main = hass.states.get("sensor.probe")
        assert main is not None
        assert main.state == expected[ATTR_NATIVE_VALUE]
        assert main.attributes[ATTR_LATITUDE] == 51.5
        assert main.attributes[ATTR_LONGITUDE] == -0.1
        for entity_id, value in (
            ("sensor.probe_city", "London"),
            ("sensor.probe_map_link", "https://maps.apple.com/?q=51.5%2C-0.1&z=18"),
            ("sensor.probe_zone_name", zone_name),
            ("sensor.probe_direction_of_travel", expected[ATTR_DIRECTION_OF_TRAVEL]),
        ):
            state = hass.states.get(entity_id)
            assert state is not None and state.state == value
        assert not events

    assert accepted[ATTR_LAST_CHANGED] == "2026-11-24 12:00:00+00:00"
    assert accepted[ATTR_NATIVE_VALUE] == "London (since 12:00)"
    assert accepted[ATTR_DIRECTION_OF_TRAVEL] == "away from home"

    # About 3 metres from the accepted coordinates, still inside the movement gate.
    now += timedelta(seconds=30)
    hass.states.async_set("device_tracker.probe", "work", {"latitude": 51.50003, "longitude": -0.1})
    await hass.async_block_till_done()
    expected = {
        **accepted,
        ATTR_DEVICETRACKER_ZONE: "work",
        ATTR_DEVICETRACKER_ZONE_NAME: "Office",
        ATTR_LAST_UPDATED: "2026-11-24 12:00:30+00:00",
    }
    await assert_retained(expected, "Office")
    assert requests == ["51.5"]

    now += timedelta(seconds=30)
    hass.states.async_set("device_tracker.probe", "work", {"latitude": 51.5, "longitude": -0.1})
    await hass.async_block_till_done()
    expected.update(
        {
            ATTR_DIRECTION_OF_TRAVEL: "stationary",
            ATTR_LAST_CHANGED: "2026-11-24 12:01:00+00:00",
            ATTR_LAST_UPDATED: "2026-11-24 12:01:00+00:00",
        }
    )
    await assert_retained(expected, "Office")
    assert requests == ["51.5"]

    now += timedelta(days=1)
    scan_clock += 86400
    await coordinator.async_scan_update()
    await hass.async_block_till_done()
    expected.update(
        {
            ATTR_NATIVE_VALUE: "London (since 24/11)",
            ATTR_LAST_UPDATED: "2026-11-25 12:01:00+00:00",
            ATTR_SHOW_DATE: True,
        }
    )
    await assert_retained(expected, "Office")
    assert requests == ["51.5"]

    now += timedelta(minutes=1)
    hass.states.async_set(
        "device_tracker.probe", "not_home", {"latitude": 51.5002, "longitude": -0.1}
    )
    await hass.async_block_till_done()
    expected.update(
        {
            ATTR_DEVICETRACKER_ZONE: "not_home",
            ATTR_DEVICETRACKER_ZONE_NAME: "not_home",
            ATTR_LAST_UPDATED: "2026-11-25 12:02:00+00:00",
        }
    )
    await assert_retained(expected, "not_home")
    assert requests == ["51.5", "51.5002"]

    # Only about 3 metres from the suppressed candidate, but over 10 from the accepted Place.
    now += timedelta(minutes=1)
    hass.states.async_set("device_tracker.probe", "work", {"latitude": 51.50023, "longitude": -0.1})
    await hass.async_block_till_done()
    expected[ATTR_LAST_UPDATED] = "2026-11-25 12:03:00+00:00"
    await assert_retained(expected, "not_home")
    assert requests == ["51.5", "51.5002", "51.50023"]

    now += timedelta(minutes=1)
    hass.states.async_set("device_tracker.probe", "", {"latitude": 51.5, "longitude": -0.1})
    await hass.async_block_till_done()
    expected.update(
        {
            ATTR_DEVICETRACKER_ZONE: None,
            ATTR_DEVICETRACKER_ZONE_NAME: None,
            ATTR_LAST_UPDATED: "2026-11-25 12:04:00+00:00",
        }
    )
    await assert_retained(expected, "unknown")
    assert requests == ["51.5", "51.5002", "51.50023"]


@pytest.fixture
def mock_entry() -> MockConfigEntry:
    """Return a MockConfigEntry pre-populated with sample data for tests.

    Returns:
        MockConfigEntry:
            Configuration entry prepared for the integration scenario.
    """
    return MockConfigEntry(domain="places", data={"name": "test", "other": "value"})


@pytest.fixture
def sensitive_entry() -> MockConfigEntry:
    """Return a config entry containing data that must not be logged.

    Returns:
        MockConfigEntry:
            Configuration entry populated with values requiring redaction.
    """
    return MockConfigEntry(
        domain="places",
        data={CONF_NAME: "test", CONF_API_KEY: "secret@example.com"},
    )


class _FakePlacesStorage:
    """Test double for `PlacesStorage` used to assert removal calls."""

    remove_calls = 0
    remove_calls_args: ClassVar[list[tuple[str, str]]] = []
    remove_error: OSError | None = None

    def __init__(self, hass: object, entry_id: str, name: str) -> None:
        """Record constructor arguments for assertions.

        Args:
            hass (object):
                Mocked Home Assistant runtime.
            entry_id (str):
                Stable identifier of the configuration entry.
            name (str):
                Display name assigned to the fake configuration entry.
        """
        self.hass = hass
        self.entry_id = entry_id
        self.name = name

    async def async_remove(self) -> None:
        """Record a removal request from async_remove_entry.

        Raises:
            remove_error:
                Propagated when the operation fails.
        """
        remove_error = type(self).remove_error
        if remove_error is not None:
            raise remove_error
        type(self).remove_calls += 1
        type(self).remove_calls_args.append((self.entry_id, self.name))


class _FakeSetupPlacesStorage:
    """Test double for setup-time PlacesStorage interactions."""

    instances: ClassVar[list[_FakeSetupPlacesStorage]] = []
    load_result: ClassVar[dict[str, object]] = {}

    def __init__(self, hass: object, entry_id: str, name: str) -> None:
        """Record constructor arguments for assertions.

        Args:
            hass (object):
                Mocked Home Assistant runtime.
            entry_id (str):
                Stable identifier of the configuration entry.
            name (str):
                Display name assigned to the fake configuration entry.
        """
        self.hass = hass
        self.entry_id = entry_id
        self.name = name
        self.instances.append(self)

    async def async_load(self) -> dict[str, object]:
        """Return the configured persisted snapshot for setup tests.

        Returns:
            dict[str, object]:
                Stored payload configured for the persistence scenario.
        """
        return dict(type(self).load_result)


class _FakeCoordinator:
    """Test double for setup and unload coordinator ownership."""

    instances: ClassVar[list[_FakeCoordinator]] = []

    def __init__(
        self,
        hass: object,
        config_entry: MockConfigEntry,
        imported_attributes: dict[str, object],
        persistence: _FakeSetupPlacesStorage | MagicMock,
    ) -> None:
        """Record construction arguments and expose async hooks for assertions.

        Args:
            hass (object):
                Mocked Home Assistant runtime.
            config_entry (MockConfigEntry):
                Places configuration entry used by the test.
            imported_attributes (dict[str, object]):
                Persisted attributes imported at startup.
            persistence (_FakeSetupPlacesStorage | MagicMock):
                Places persistence manager used by the test.
        """
        self.hass = hass
        self.config_entry = config_entry
        self.imported_attributes = imported_attributes
        self.persistence = persistence
        self.async_added_to_hass = AsyncMock()
        self.async_render_display_state = AsyncMock()
        self.publish_update = MagicMock()
        self.async_request_refresh = AsyncMock()
        self.async_prepare_unload = AsyncMock()
        self.async_resume_after_failed_unload = AsyncMock()
        self.async_shutdown = AsyncMock()
        self.instances.append(self)


@pytest.fixture(autouse=True)
def reset_fake_storage() -> None:
    """Reset fake storage accounting for each integration test."""
    _FakePlacesStorage.remove_calls = 0
    _FakePlacesStorage.remove_calls_args = []
    _FakePlacesStorage.remove_error = None
    _FakeSetupPlacesStorage.instances = []
    _FakeSetupPlacesStorage.load_result = {}
    _FakeCoordinator.instances = []


@pytest.mark.asyncio
@pytest.mark.usefixtures("hass_storage")
@pytest.mark.parametrize("version", [1, 2])
async def test_async_migrate_entry_gates_migration_by_version(
    hass: HomeAssistant,
    tmp_path: Path,
    version: int,
) -> None:
    """Only a v1 entry migrates both its Display options and legacy snapshot.

    Args:
        hass (HomeAssistant):
            Home Assistant instance with a config entry registry.
        tmp_path (Path):
            Isolated config directory for the legacy snapshot.
        version (int):
            Config entry schema version.
    """
    data = {
        CONF_NAME: "Test Place",
        CONF_DISPLAY_OPTIONS: "  Formatted_Address , City ",
        CONF_SHOW_TIME: True,
    }
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=version,
        minor_version=3 if version == 2 else 1,
        data=data,
    )
    entry.add_to_hass(hass)
    hass.config.config_dir = str(tmp_path)
    snapshot_path = legacy_json_path(hass, entry.entry_id)
    await hass.async_add_executor_job(snapshot_path.parent.mkdir, 0o777, True)
    await hass.async_add_executor_job(snapshot_path.write_text, '{"city": "Legacy City"}')
    storage = PlacesStorage(hass, entry.entry_id, "Test Place")

    assert await async_migrate_entry(hass, entry)

    if version == 1:
        assert (entry.version, entry.minor_version) == (2, 1)
        assert entry.data == {**data, CONF_DISPLAY_OPTIONS: "  osm_formatted_address , City "}
        assert await storage.async_load() == {ATTR_CITY: "Legacy City"}
        assert not snapshot_path.exists()
    else:
        assert (entry.version, entry.minor_version) == (2, 3)
        assert entry.data == data
        assert await storage.async_load() == {}
        assert snapshot_path.exists()


@pytest.mark.asyncio
async def test_async_migrate_entry_preserves_literal_in_malformed_rule(hass: HomeAssistant) -> None:
    """A stray closing delimiter does not change the role of later filter values.

    Args:
        hass (HomeAssistant): Home Assistant instance with a config entry registry.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=1,
        data={
            CONF_NAME: "Test Place",
            CONF_DISPLAY_OPTIONS: (
                "City),  Type(Formatted_Address, Formatted_Address(+, 'Formatted_Address'))"
                "[ \tFORMATTED_ADDRESS, State ],  Country "
            ),
        },
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry)

    assert (entry.version, entry.minor_version) == (2, 1)
    assert entry.data == {
        CONF_NAME: "Test Place",
        CONF_DISPLAY_OPTIONS: (
            "City),  Type(Formatted_Address, osm_formatted_address(+, 'Formatted_Address'))"
            "[ \tosm_formatted_address, State ],  Country "
        ),
    }


@pytest.mark.asyncio
async def test_async_migrate_entry_keeps_filter_role_after_wrong_closer(
    hass: HomeAssistant,
) -> None:
    """A mismatched closer does not cause a filter value to be migrated as a field.

    Args:
        hass (HomeAssistant): Home Assistant runtime hosting the config entry.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=1,
        data={
            CONF_NAME: "Test Place",
            CONF_DISPLAY_OPTIONS: "type(house], formatted_address), formatted_address",
        },
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry)

    assert entry.data == {
        CONF_NAME: "Test Place",
        CONF_DISPLAY_OPTIONS: "type(house], formatted_address), osm_formatted_address",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("display_options", "expected_options"),
    [
        ("do_not_reorder, formatted_place", "formatted_place"),
        ("do_not_reorder, formatted_place, driving", "formatted_place, driving"),
        # A top-level option is renamed, while a filter argument remains literal data.
        pytest.param(
            "formatted_address, city",
            "osm_formatted_address, city",
            id="top-level-formatted-address",
        ),
        pytest.param(
            "type(formatted_address)[city]",
            "type(formatted_address)[city]",
            id="filter-value-formatted-address",
        ),
        ("formatted_address[city]", "osm_formatted_address[city]"),
        pytest.param(
            "formatted_address[name], name(formatted_address[city], city[formatted_address])",
            "osm_formatted_address[name], name(formatted_address[city], city[formatted_address])",
            id="bracketed-filter-values",
        ),
        (
            "type(formatted_address(formatted_address), city)",
            "type(osm_formatted_address(formatted_address), city)",
        ),
        ("do_not_reorder, formatted_address, city", "osm_formatted_address[], city"),
        ("do_not_reorder, city, state", "city[], state"),
        ("Do_Not_Reorder, City, State", "city[], state"),
        (
            "do_not_reorder, zone, do_not_show_not_home, city",
            "zone[], city",
        ),
        (
            "do_not_reorder, zone_name, place, city",
            (
                "zone_name[], name_no_dupe, category(-, place), type(-, yes), "
                "neighborhood, house_number, street, city"
            ),
        ),
        ("do_not_reorder, type(-, yes), city", "type(-, yes)[], city"),
        (
            (
                "Do_Not_Reorder, City, Type(-, DO_NOT_SHOW_NOT_HOME)"
                "[Formatted_Address, State], Do_Not_Show_Not_Home"
            ),
            "city[], type(-, do_not_show_not_home)[osm_formatted_address, state]",
        ),
        ("city, state", "city, state"),
        ("do_not_reorder", DEFAULT_DISPLAY_OPTIONS),
    ],
)
async def test_async_migrate_entry_updates_stored_display_options(
    hass: HomeAssistant,
    display_options: str,
    expected_options: str,
) -> None:
    """Migration saves the intended Display options and upgrades the entry version.

    Args:
        hass (HomeAssistant):
            Home Assistant instance with a config entry registry.
        display_options (str):
            Legacy Display options saved in the entry.
        expected_options (str):
            Display options expected after migration.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=1,
        data={CONF_NAME: "Test Place", CONF_DISPLAY_OPTIONS: display_options},
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry)

    assert (entry.version, entry.minor_version) == (2, 1)
    assert entry.data == {CONF_NAME: "Test Place", CONF_DISPLAY_OPTIONS: expected_options}


@pytest.mark.asyncio
async def test_async_remove_entry_removes_store_data(
    monkeypatch: pytest.MonkeyPatch, mock_hass: MagicMock, mock_entry: MockConfigEntry
) -> None:
    """Config-entry deletion should remove the per-entry Store snapshot.

    Args:
        monkeypatch (pytest.MonkeyPatch):
            Pytest fixture for replacing dependencies.
        mock_hass (MagicMock):
            Mocked Home Assistant runtime.
        mock_entry (MockConfigEntry):
            Places configuration entry used by the test.
    """
    registry = MagicMock()
    registry.async_get_entity_id.return_value = None
    monkeypatch.setattr("custom_components.places.PlacesStorage", _FakePlacesStorage)
    monkeypatch.setattr("custom_components.places.er.async_get", lambda hass: registry)

    result = await async_remove_entry(mock_hass, mock_entry)

    assert result is True
    registry.async_get_entity_id.assert_called_once_with(
        "sensor", "places", f"{mock_entry.entry_id}_extended_data"
    )
    assert _FakePlacesStorage.remove_calls == 1
    assert _FakePlacesStorage.remove_calls_args == [
        (mock_entry.entry_id, mock_entry.data[CONF_NAME])
    ]


@pytest.mark.asyncio
async def test_async_remove_entry_uses_entry_id_if_name_missing(
    monkeypatch: pytest.MonkeyPatch, mock_hass: MagicMock
) -> None:
    """async_remove_entry should use entry_id when no config entry name exists.

    Args:
        monkeypatch (pytest.MonkeyPatch):
            Pytest fixture for replacing dependencies.
        mock_hass (MagicMock):
            Mocked Home Assistant runtime.
    """
    entry = MockConfigEntry(domain="places", data={})
    registry = MagicMock()
    registry.async_get_entity_id.return_value = None
    monkeypatch.setattr("custom_components.places.PlacesStorage", _FakePlacesStorage)
    monkeypatch.setattr("custom_components.places.er.async_get", lambda hass: registry)

    await async_remove_entry(mock_hass, entry)

    registry.async_get_entity_id.assert_called_once_with(
        "sensor", "places", f"{entry.entry_id}_extended_data"
    )
    assert _FakePlacesStorage.remove_calls == 1
    assert _FakePlacesStorage.remove_calls_args == [(entry.entry_id, entry.entry_id)]


@pytest.mark.asyncio
async def test_async_remove_extended_entity_removes_registry_entry(
    monkeypatch: pytest.MonkeyPatch,
    mock_hass: MagicMock,
) -> None:
    """Extended-data entity cleanup should remove the registry entry when present.

    Args:
        monkeypatch (pytest.MonkeyPatch):
            Pytest fixture for replacing dependencies.
        mock_hass (MagicMock):
            Mocked Home Assistant runtime.
    """
    registry = MagicMock()
    registry.async_get_entity_id.return_value = "sensor.test_extended_data"
    monkeypatch.setattr("custom_components.places.er.async_get", lambda hass: registry)
    entry = MockConfigEntry(domain="places", entry_id="entry123", data={"name": "Test"})

    await async_remove_extended_entity(mock_hass, entry)

    registry.async_get_entity_id.assert_called_once_with(
        "sensor", "places", "entry123_extended_data"
    )
    registry.async_remove.assert_called_once_with("sensor.test_extended_data")


@pytest.mark.asyncio
async def test_async_remove_extended_entity_ignores_missing_registry_entry(
    monkeypatch: pytest.MonkeyPatch,
    mock_hass: MagicMock,
) -> None:
    """Extended-data cleanup should no-op when no registry entry exists.

    Args:
        monkeypatch (pytest.MonkeyPatch):
            Pytest fixture for replacing dependencies.
        mock_hass (MagicMock):
            Mocked Home Assistant runtime.
    """
    registry = MagicMock()
    registry.async_get_entity_id.return_value = None
    monkeypatch.setattr("custom_components.places.er.async_get", lambda hass: registry)
    entry = MockConfigEntry(domain="places", entry_id="entry123", data={"name": "Test"})

    await async_remove_extended_entity(mock_hass, entry)

    registry.async_get_entity_id.assert_called_once_with(
        "sensor", "places", "entry123_extended_data"
    )
    registry.async_remove.assert_not_called()


@pytest.mark.asyncio
async def test_async_remove_entry_logs_storage_errors_without_blocking(
    monkeypatch: pytest.MonkeyPatch,
    mock_hass: MagicMock,
    sensitive_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Config-entry deletion should not be blocked by storage cleanup errors.

    Args:
        monkeypatch (pytest.MonkeyPatch):
            Pytest fixture for replacing dependencies.
        mock_hass (MagicMock):
            Mocked Home Assistant runtime.
        sensitive_entry (MockConfigEntry):
            Configuration entry containing secrets that must not be logged.
        caplog (pytest.LogCaptureFixture):
            Captured log records used for message assertions.
    """
    registry = MagicMock()
    registry.async_get_entity_id.return_value = None
    monkeypatch.setattr("custom_components.places.PlacesStorage", _FakePlacesStorage)
    monkeypatch.setattr("custom_components.places.er.async_get", lambda hass: registry)
    _FakePlacesStorage.remove_error = OSError("storage unavailable")

    with caplog.at_level(logging.WARNING, logger="custom_components.places"):
        result = await async_remove_entry(mock_hass, sensitive_entry)

    assert result is True
    registry.async_get_entity_id.assert_called_once_with(
        "sensor", "places", f"{sensitive_entry.entry_id}_extended_data"
    )
    assert sensitive_entry.entry_id in caplog.text
    assert "storage unavailable" in caplog.text
    assert "secret@example.com" not in caplog.text


@pytest.mark.asyncio
async def test_async_unload_entry_logs_safe_identifier(
    mock_hass: MagicMock,
    sensitive_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Config-entry unload should not log the full entry data mapping.

    Args:
        mock_hass (MagicMock):
            Mocked Home Assistant runtime.
        sensitive_entry (MockConfigEntry):
            Configuration entry containing secrets that must not be logged.
        caplog (pytest.LogCaptureFixture):
            Captured log records used for message assertions.
    """
    sensitive_entry.runtime_data = _FakeCoordinator(
        mock_hass,
        sensitive_entry,
        {},
        MagicMock(),
    )

    with caplog.at_level(logging.INFO, logger="custom_components.places"):
        await async_unload_entry(mock_hass, sensitive_entry)

    assert sensitive_entry.entry_id in caplog.text
    assert "secret@example.com" not in caplog.text


@pytest.mark.asyncio
async def test_async_setup_entry_calls_forward_setups(
    monkeypatch: pytest.MonkeyPatch,
    mock_hass: MagicMock,
    mock_entry: MockConfigEntry,
) -> None:
    """Ensure setup creates the coordinator runtime owner and forwards platforms.

    Args:
        monkeypatch (pytest.MonkeyPatch):
            Pytest fixture for replacing dependencies.
        mock_hass (MagicMock):
            Mocked Home Assistant runtime.
        mock_entry (MockConfigEntry):
            Places configuration entry used by the test.
    """
    _FakeSetupPlacesStorage.load_result = {"native_value": "Restored"}
    monkeypatch.setattr("custom_components.places.PlacesStorage", _FakeSetupPlacesStorage)
    monkeypatch.setattr("custom_components.places.PlacesUpdateCoordinator", _FakeCoordinator)
    call_order: list[str] = []

    async def record_subscription() -> None:
        """Record coordinator subscription before platform forwarding."""
        call_order.append("subscribe")

    async def record_render() -> None:
        """Record restored display-state rendering before platform forwarding."""
        call_order.append("render")

    def record_publish() -> None:
        """Record restored-state publication before platform forwarding."""
        call_order.append("publish")

    async def record_forward(*_args: object, **_kwargs: object) -> None:
        """Record platform forwarding after subscription.

        Args:
            _args (object):
                Positional arguments captured by the forwarding callback.
            _kwargs (object):
                Optional keyword arguments captured by the forwarding callback.
        """
        call_order.append("forward")

    original_init = _FakeCoordinator.__init__

    def init_with_recorded_subscription(
        self: _FakeCoordinator,
        hass: object,
        config_entry: MockConfigEntry,
        imported_attributes: dict[str, object],
        persistence: _FakeSetupPlacesStorage | MagicMock,
    ) -> None:
        """Install a recorded async_added_to_hass hook on the fake coordinator.

        Args:
            self (_FakeCoordinator):
                Fake coordinator instance initialized by the patched method.
            hass (object):
                Mocked Home Assistant runtime.
            config_entry (MockConfigEntry):
                Places configuration entry used by the test.
            imported_attributes (dict[str, object]):
                Persisted attributes imported at startup.
            persistence (_FakeSetupPlacesStorage | MagicMock):
                Places persistence manager used by the test.
        """
        original_init(self, hass, config_entry, imported_attributes, persistence)
        self.async_added_to_hass.side_effect = record_subscription
        self.async_render_display_state.side_effect = record_render
        self.publish_update.side_effect = record_publish

    monkeypatch.setattr(_FakeCoordinator, "__init__", init_with_recorded_subscription)
    mock_hass.config_entries.async_forward_entry_setups.side_effect = record_forward

    result = await async_setup_entry(mock_hass, mock_entry)
    await asyncio.sleep(0)

    assert result is True
    assert isinstance(mock_entry.runtime_data, _FakeCoordinator)
    assert isinstance(mock_hass.data[DOMAIN][OSM_CACHE], cachetools.TTLCache)
    assert isinstance(mock_hass.data[DOMAIN][OSM_THROTTLE]["lock"], asyncio.Lock)
    assert mock_hass.data[DOMAIN][OSM_THROTTLE]["last_query"] == 0.0
    assert _FakeSetupPlacesStorage.instances[0].entry_id == mock_entry.entry_id
    assert _FakeSetupPlacesStorage.instances[0].name == mock_entry.data[CONF_NAME]
    assert mock_entry.runtime_data.imported_attributes == {"native_value": "Restored"}
    assert mock_entry.runtime_data.persistence is _FakeSetupPlacesStorage.instances[0]
    mock_entry.runtime_data.async_added_to_hass.assert_awaited_once_with()
    mock_entry.runtime_data.async_render_display_state.assert_awaited_once_with()
    mock_entry.runtime_data.publish_update.assert_called_once_with()
    mock_entry.runtime_data.async_request_refresh.assert_awaited_once_with()
    mock_hass.config_entries.async_forward_entry_setups.assert_awaited_once_with(
        mock_entry, PLATFORMS
    )
    assert call_order.index("render") < call_order.index("forward")
    assert call_order.index("publish") < call_order.index("forward")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    (
        "display_options",
        "show_time",
        "persisted_native_value",
        "last_changed",
        "expected_state",
    ),
    [
        ("city[]", False, "Home", None, "Sample City"),
        (
            "city[]",
            True,
            "Home (since 11:00)",
            "2026-08-23 12:00:00+00:00",
            "Sample City (since 12:00)",
        ),
        ("zone_name", False, "Stale Home", None, "Home"),
    ],
    ids=("advanced-options", "show-time", "zone-name-fallback"),
)
async def test_async_setup_entry_renders_current_options_from_persisted_location(
    monkeypatch: pytest.MonkeyPatch,
    mock_hass: MagicMock,
    display_options: str,
    *,
    show_time: bool,
    persisted_native_value: str,
    last_changed: str | None,
    expected_state: str,
) -> None:
    """Setup should rerender restored data without waiting for tracker movement.

    Args:
        monkeypatch (pytest.MonkeyPatch):
            Pytest fixture for replacing setup dependencies.
        mock_hass (MagicMock):
            Mocked Home Assistant runtime.
        display_options (str):
            Current display options used to rerender restored location data.
        show_time (bool):
            Whether the rendered state should include last-change time.
        persisted_native_value (str):
            Stale display state restored from Store.
        last_changed (str | None):
            Persisted timestamp used by show-time formatting when configured.
        expected_state (str):
            Display state expected from current config and restored location data.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_NAME: "Test Place",
            CONF_DEVICETRACKER_ID: "person.test",
            CONF_DISPLAY_OPTIONS: display_options,
            CONF_SHOW_TIME: show_time,
        },
    )
    _FakeSetupPlacesStorage.load_result = {
        ATTR_NATIVE_VALUE: persisted_native_value,
        ATTR_CITY: "Sample City",
        ATTR_DEVICETRACKER_ZONE: "home",
        ATTR_DEVICETRACKER_ZONE_NAME: "Home",
    }
    if last_changed is not None:
        _FakeSetupPlacesStorage.load_result[ATTR_LAST_CHANGED] = last_changed
    monkeypatch.setattr("custom_components.places.PlacesStorage", _FakeSetupPlacesStorage)
    monkeypatch.setattr(
        PlacesUpdateCoordinator,
        "async_added_to_hass",
        AsyncMock(),
    )
    monkeypatch.setattr(
        PlacesUpdateCoordinator,
        "async_request_refresh",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "custom_components.places.update_sensor.PlacesUpdater.get_current_time",
        AsyncMock(return_value=datetime(2026, 8, 23, 13, 0, tzinfo=UTC)),
    )

    await async_setup_entry(mock_hass, entry)

    assert entry.runtime_data.data.native_value == expected_state


def test_ensure_osm_runtime_state_preserves_existing_state(mock_hass: MagicMock) -> None:
    """OSM runtime setup should not replace existing shared cache or throttle.

    Args:
        mock_hass (MagicMock):
            Mocked Home Assistant runtime.
    """
    cache: dict[str, object] = {"cached": {"ok": True}}
    throttle = {"lock": asyncio.Lock(), "last_query": 42.0}
    mock_hass.data = {
        DOMAIN: {
            OSM_CACHE: cache,
            OSM_THROTTLE: throttle,
        }
    }

    _ensure_osm_runtime_state(mock_hass)

    assert mock_hass.data[DOMAIN][OSM_CACHE] is cache
    assert mock_hass.data[DOMAIN][OSM_THROTTLE] is throttle


@pytest.mark.asyncio
async def test_async_setup_entry_does_not_subscribe_when_platform_setup_fails(
    monkeypatch: pytest.MonkeyPatch,
    mock_hass: MagicMock,
    mock_entry: MockConfigEntry,
) -> None:
    """Forwarding failure should unsubscribe the coordinator and clear runtime data.

    Args:
        monkeypatch (pytest.MonkeyPatch):
            Pytest fixture for replacing dependencies.
        mock_hass (MagicMock):
            Mocked Home Assistant runtime.
        mock_entry (MockConfigEntry):
            Places configuration entry used by the test.
    """
    monkeypatch.setattr("custom_components.places.PlacesStorage", _FakeSetupPlacesStorage)
    monkeypatch.setattr("custom_components.places.PlacesUpdateCoordinator", _FakeCoordinator)
    mock_hass.config_entries.async_forward_entry_setups.side_effect = RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await async_setup_entry(mock_hass, mock_entry)

    coordinator = _FakeCoordinator.instances[0]
    coordinator.async_added_to_hass.assert_awaited_once_with()
    coordinator.async_prepare_unload.assert_awaited_once_with()
    coordinator.async_shutdown.assert_awaited_once_with()
    mock_hass.config_entries.async_unload_platforms.assert_awaited_once_with(mock_entry, PLATFORMS)
    assert mock_entry.runtime_data is None


@pytest.mark.asyncio
@pytest.mark.parametrize("cleanup_raises", [False, True])
async def test_async_setup_entry_clears_runtime_when_platform_cleanup_fails(
    monkeypatch: pytest.MonkeyPatch,
    mock_hass: MagicMock,
    mock_entry: MockConfigEntry,
    cleanup_raises: bool,
) -> None:
    """Forwarding failure cleanup should not resume a never-loaded coordinator.

    Args:
        monkeypatch (pytest.MonkeyPatch):
            Pytest fixture for replacing dependencies.
        mock_hass (MagicMock):
            Mocked Home Assistant runtime.
        mock_entry (MockConfigEntry):
            Places configuration entry used by the test.
        cleanup_raises (bool):
            Whether cleanup is expected to raise internally.
    """
    monkeypatch.setattr("custom_components.places.PlacesStorage", _FakeSetupPlacesStorage)
    monkeypatch.setattr("custom_components.places.PlacesUpdateCoordinator", _FakeCoordinator)
    mock_hass.config_entries.async_forward_entry_setups.side_effect = RuntimeError("setup failed")
    if cleanup_raises:
        mock_hass.config_entries.async_unload_platforms.side_effect = RuntimeError("cleanup failed")
    else:
        mock_hass.config_entries.async_unload_platforms.return_value = False

    with pytest.raises(RuntimeError, match="setup failed"):
        await async_setup_entry(mock_hass, mock_entry)

    coordinator = _FakeCoordinator.instances[0]
    coordinator.async_prepare_unload.assert_awaited_once_with()
    coordinator.async_resume_after_failed_unload.assert_not_awaited()
    coordinator.async_shutdown.assert_awaited_once_with()
    mock_hass.config_entries.async_unload_platforms.assert_awaited_once_with(mock_entry, PLATFORMS)
    assert mock_entry.runtime_data is None


@pytest.mark.asyncio
async def test_async_setup_entry_unloads_platforms_when_initial_refresh_fails(
    monkeypatch: pytest.MonkeyPatch,
    mock_hass: MagicMock,
) -> None:
    """Initial refresh failure should clean up forwarded platforms and runtime state.

    Args:
        monkeypatch (pytest.MonkeyPatch):
            Pytest fixture for replacing dependencies.
        mock_hass (MagicMock):
            Mocked Home Assistant runtime.
    """
    entry = MockConfigEntry(
        domain="places",
        data={
            "name": "TestSensor",
            "devicetracker_id": "person.test",
            CONF_EXTENDED_ATTR: True,
        },
    )
    monkeypatch.setattr("custom_components.places.PlacesStorage", _FakeSetupPlacesStorage)
    monkeypatch.setattr("custom_components.places.PlacesUpdateCoordinator", _FakeCoordinator)
    call_order: list[str] = []

    async def raise_refresh_error() -> None:
        """Raise after platforms have been forwarded.

        Raises:
            RuntimeError:
                Propagated when the operation fails.
        """
        raise RuntimeError("refresh boom")

    async def mark_prepare_unload() -> None:
        call_order.append("prepare_unload")

    async def mark_unload(_entry: MockConfigEntry, _platforms: list[str]) -> bool:
        call_order.append("unload_platforms")
        return True

    async def mark_shutdown() -> None:
        call_order.append("shutdown")

    original_init = _FakeCoordinator.__init__

    def init_with_failing_refresh(
        self: _FakeCoordinator,
        hass: object,
        config_entry: MockConfigEntry,
        imported_attributes: dict[str, object],
        persistence: _FakeSetupPlacesStorage | MagicMock,
    ) -> None:
        """Install a failing initial refresh hook on the fake coordinator.

        Args:
            self (_FakeCoordinator):
                Fake coordinator instance initialized by the patched method.
            hass (object):
                Mocked Home Assistant runtime.
            config_entry (MockConfigEntry):
                Places configuration entry used by the test.
            imported_attributes (dict[str, object]):
                Persisted attributes imported at startup.
            persistence (_FakeSetupPlacesStorage | MagicMock):
                Places persistence manager used by the test.
        """
        original_init(self, hass, config_entry, imported_attributes, persistence)
        self.async_request_refresh.side_effect = raise_refresh_error
        self.async_prepare_unload.side_effect = mark_prepare_unload
        self.async_shutdown.side_effect = mark_shutdown

    monkeypatch.setattr(_FakeCoordinator, "__init__", init_with_failing_refresh)
    mock_hass.config_entries.async_unload_platforms.side_effect = mark_unload

    with pytest.raises(RuntimeError, match="refresh boom"):
        await async_setup_entry(mock_hass, entry)

    coordinator = _FakeCoordinator.instances[0]
    coordinator.async_shutdown.assert_awaited_once_with()
    mock_hass.config_entries.async_unload_platforms.assert_awaited_once_with(entry, PLATFORMS)
    assert entry.runtime_data is None
    assert call_order == ["prepare_unload", "unload_platforms", "shutdown"]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_point", ["forward", "refresh"])
async def test_async_setup_entry_cleans_up_when_setup_is_cancelled(
    monkeypatch: pytest.MonkeyPatch,
    mock_hass: MagicMock,
    mock_entry: MockConfigEntry,
    failure_point: str,
) -> None:
    """Cancellation after subscription should clean up before propagating.

    Args:
        monkeypatch (pytest.MonkeyPatch):
            Pytest fixture for replacing dependencies.
        mock_hass (MagicMock):
            Mocked Home Assistant runtime.
        mock_entry (MockConfigEntry):
            Places configuration entry used by the test.
        failure_point (str):
            Setup operation that raises cancellation.
    """
    monkeypatch.setattr("custom_components.places.PlacesStorage", _FakeSetupPlacesStorage)
    monkeypatch.setattr("custom_components.places.PlacesUpdateCoordinator", _FakeCoordinator)
    call_order: list[str] = []

    async def raise_setup_cancellation(*_args: object, **_kwargs: object) -> None:
        """Cancel the setup operation under test.

        Args:
            *_args (object):
                Positional arguments supplied by the operation under test.
            **_kwargs (object):
                Keyword arguments supplied by the operation under test.

        Raises:
            asyncio.CancelledError:
                Always raised to emulate setup cancellation.
        """
        raise asyncio.CancelledError("setup cancelled")

    async def mark_prepare_unload() -> None:
        """Record coordinator preparation for failed setup cleanup."""
        call_order.append("prepare_unload")

    async def mark_unload(_entry: MockConfigEntry, _platforms: list[str]) -> bool:
        """Record platform unloading during failed setup cleanup.

        Args:
            _entry (MockConfigEntry):
                Configuration entry whose platforms are unloaded.
            _platforms (list[str]):
                Platform names being unloaded.

        Returns:
            bool:
                ``True`` to indicate the platforms were unloaded.
        """
        call_order.append("unload_platforms")
        return True

    async def mark_shutdown() -> None:
        """Record coordinator shutdown during failed setup cleanup."""
        call_order.append("shutdown")

    original_init = _FakeCoordinator.__init__

    def init_with_cleanup_recording(
        self: _FakeCoordinator,
        hass: object,
        config_entry: MockConfigEntry,
        imported_attributes: dict[str, object],
        persistence: _FakeSetupPlacesStorage | MagicMock,
    ) -> None:
        """Install cleanup hooks and an optional refresh cancellation hook.

        Args:
            self (_FakeCoordinator):
                Fake coordinator receiving the configured hooks.
            hass (object):
                Mocked Home Assistant runtime.
            config_entry (MockConfigEntry):
                Places configuration entry used by the test.
            imported_attributes (dict[str, object]):
                Persisted attributes imported at startup.
            persistence (_FakeSetupPlacesStorage | MagicMock):
                Places persistence manager used by the test.
        """
        original_init(self, hass, config_entry, imported_attributes, persistence)
        self.async_prepare_unload.side_effect = mark_prepare_unload
        self.async_shutdown.side_effect = mark_shutdown
        if failure_point == "refresh":
            self.async_request_refresh.side_effect = raise_setup_cancellation

    monkeypatch.setattr(_FakeCoordinator, "__init__", init_with_cleanup_recording)
    mock_hass.config_entries.async_unload_platforms.side_effect = mark_unload
    if failure_point == "forward":
        mock_hass.config_entries.async_forward_entry_setups.side_effect = raise_setup_cancellation

    with pytest.raises(asyncio.CancelledError, match="setup cancelled"):
        await async_setup_entry(mock_hass, mock_entry)

    coordinator = _FakeCoordinator.instances[0]
    coordinator.async_added_to_hass.assert_awaited_once_with()
    coordinator.async_prepare_unload.assert_awaited_once_with()
    mock_hass.config_entries.async_unload_platforms.assert_awaited_once_with(mock_entry, PLATFORMS)
    coordinator.async_shutdown.assert_awaited_once_with()
    assert call_order == ["prepare_unload", "unload_platforms", "shutdown"]
    assert mock_entry.runtime_data is None


@pytest.mark.asyncio
async def test_async_setup_entry_shuts_down_when_subscription_step_fails(
    monkeypatch: pytest.MonkeyPatch,
    mock_hass: MagicMock,
    mock_entry: MockConfigEntry,
) -> None:
    """Subscription failure should shutdown the coordinator before any platform unload.

    Args:
        monkeypatch (pytest.MonkeyPatch):
            Pytest fixture for replacing dependencies.
        mock_hass (MagicMock):
            Mocked Home Assistant runtime.
        mock_entry (MockConfigEntry):
            Places configuration entry used by the test.
    """
    monkeypatch.setattr("custom_components.places.PlacesStorage", _FakeSetupPlacesStorage)
    monkeypatch.setattr("custom_components.places.PlacesUpdateCoordinator", _FakeCoordinator)

    async def raise_subscription_error() -> None:
        """Raise a subscription error during ``async_added_to_hass`` before platform forwarding.

        Raises:
            RuntimeError:
                Propagated when the operation fails.
        """
        raise RuntimeError("subscribe boom")

    original_init = _FakeCoordinator.__init__

    def init_with_failing_subscription(
        self: _FakeCoordinator,
        hass: object,
        config_entry: MockConfigEntry,
        imported_attributes: dict[str, object],
        persistence: _FakeSetupPlacesStorage | MagicMock,
    ) -> None:
        """Install a failing async_added_to_hass hook on the fake coordinator.

        Args:
            self (_FakeCoordinator):
                Fake coordinator instance initialized by the patched method.
            hass (object):
                Mocked Home Assistant runtime.
            config_entry (MockConfigEntry):
                Places configuration entry used by the test.
            imported_attributes (dict[str, object]):
                Persisted attributes imported at startup.
            persistence (_FakeSetupPlacesStorage | MagicMock):
                Places persistence manager used by the test.
        """
        original_init(self, hass, config_entry, imported_attributes, persistence)
        self.async_added_to_hass.side_effect = raise_subscription_error

    monkeypatch.setattr(_FakeCoordinator, "__init__", init_with_failing_subscription)

    with pytest.raises(RuntimeError, match="subscribe boom"):
        await async_setup_entry(mock_hass, mock_entry)

    coordinator = _FakeCoordinator.instances[0]
    coordinator.async_added_to_hass.assert_awaited_once_with()
    coordinator.async_shutdown.assert_awaited_once_with()
    mock_hass.config_entries.async_unload_platforms.assert_not_awaited()
    assert mock_entry.runtime_data is None


@pytest.mark.asyncio
async def test_async_setup_entry_shuts_down_when_subscription_is_cancelled(
    monkeypatch: pytest.MonkeyPatch,
    mock_hass: MagicMock,
    mock_entry: MockConfigEntry,
) -> None:
    """Subscription cancellation should shut down without unloading platforms.

    Args:
        monkeypatch (pytest.MonkeyPatch):
            Pytest fixture for replacing dependencies.
        mock_hass (MagicMock):
            Mocked Home Assistant runtime.
        mock_entry (MockConfigEntry):
            Places configuration entry used by the test.
    """
    monkeypatch.setattr("custom_components.places.PlacesStorage", _FakeSetupPlacesStorage)
    monkeypatch.setattr("custom_components.places.PlacesUpdateCoordinator", _FakeCoordinator)

    async def raise_subscription_cancellation() -> None:
        """Cancel tracker subscription setup.

        Raises:
            asyncio.CancelledError:
                Always raised to emulate subscription cancellation.
        """
        raise asyncio.CancelledError("subscription cancelled")

    original_init = _FakeCoordinator.__init__

    def init_with_cancelled_subscription(
        self: _FakeCoordinator,
        hass: object,
        config_entry: MockConfigEntry,
        imported_attributes: dict[str, object],
        persistence: _FakeSetupPlacesStorage | MagicMock,
    ) -> None:
        """Install a cancelled ``async_added_to_hass`` hook.

        Args:
            self (_FakeCoordinator):
                Fake coordinator receiving the subscription hook.
            hass (object):
                Mocked Home Assistant runtime.
            config_entry (MockConfigEntry):
                Places configuration entry used by the test.
            imported_attributes (dict[str, object]):
                Persisted attributes imported at startup.
            persistence (_FakeSetupPlacesStorage | MagicMock):
                Places persistence manager used by the test.
        """
        original_init(self, hass, config_entry, imported_attributes, persistence)
        self.async_added_to_hass.side_effect = raise_subscription_cancellation

    monkeypatch.setattr(_FakeCoordinator, "__init__", init_with_cancelled_subscription)

    with pytest.raises(asyncio.CancelledError, match="subscription cancelled"):
        await async_setup_entry(mock_hass, mock_entry)

    coordinator = _FakeCoordinator.instances[0]
    coordinator.async_added_to_hass.assert_awaited_once_with()
    coordinator.async_shutdown.assert_awaited_once_with()
    mock_hass.config_entries.async_unload_platforms.assert_not_awaited()
    assert mock_entry.runtime_data is None


@pytest.mark.asyncio
async def test_async_setup_entry_with_empty_data(
    monkeypatch: pytest.MonkeyPatch,
    mock_hass: MagicMock,
) -> None:
    """Setup should fall back to entry_id when no config-entry name exists.

    Args:
        monkeypatch (pytest.MonkeyPatch):
            Pytest fixture for replacing dependencies.
        mock_hass (MagicMock):
            Mocked Home Assistant runtime.
    """
    entry = MockConfigEntry(domain="places", data={})
    monkeypatch.setattr("custom_components.places.PlacesStorage", _FakeSetupPlacesStorage)
    monkeypatch.setattr("custom_components.places.PlacesUpdateCoordinator", _FakeCoordinator)

    result = await async_setup_entry(mock_hass, entry)

    assert result is True
    assert isinstance(entry.runtime_data, _FakeCoordinator)
    assert _FakeSetupPlacesStorage.instances[0].name == entry.entry_id


@pytest.mark.asyncio
async def test_async_setup_entry_preserves_recorder_event_exclusions_for_extended_attributes(
    monkeypatch: pytest.MonkeyPatch,
    mock_hass: MagicMock,
) -> None:
    """Extended mode should not alter global Recorder event exclusions.

    Args:
        monkeypatch (pytest.MonkeyPatch):
            Pytest fixture for replacing dependencies.
        mock_hass (MagicMock):
            Mocked Home Assistant runtime.
    """
    entry = MockConfigEntry(
        domain="places",
        data={
            "name": "TestSensor",
            "devicetracker_id": "person.test",
            CONF_EXTENDED_ATTR: True,
        },
    )
    recorder = MagicMock()
    recorder.exclude_event_types = {"external_event"}
    mock_hass.data[DATA_INSTANCE] = recorder
    monkeypatch.setattr("custom_components.places.PlacesStorage", _FakeSetupPlacesStorage)
    monkeypatch.setattr("custom_components.places.PlacesUpdateCoordinator", _FakeCoordinator)

    await async_setup_entry(mock_hass, entry)

    assert recorder.exclude_event_types == {"external_event"}


# Force update through the loaded Places entry


@pytest.mark.parametrize("latitude", [51.5, 51.50001], ids=["same-coordinates", "small-move"])
async def test_force_update_accepts_fresh_details_with_unchanged_place_text(
    hass: HomeAssistant,
    force_update_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    monkeypatch: pytest.MonkeyPatch,
    latitude: float,
) -> None:
    """Accept fresh Place details while an ordinary scan would be throttled.

    Args:
        hass (HomeAssistant): Home Assistant runtime with real Places entities.
        force_update_entry (MockConfigEntry): Places entry with its button enabled.
        aioclient_mock (AiohttpClientMocker): Mocked OSM HTTP responses.
        monkeypatch (pytest.MonkeyPatch): Replacements for scan and OSM timing.
        latitude (float): Tracked latitude when the button is pressed.
    """
    monkeypatch.setattr("custom_components.places.coordinator.monotonic", lambda: 1000.0)
    osm_time = 1000.0

    async def advance_osm_clock(delay: float) -> None:
        """Advance the request clock by the requested delay.

        Args:
            delay (float): Number of seconds to advance.
        """
        nonlocal osm_time
        osm_time += delay

    monkeypatch.setattr(
        "custom_components.places.osm_client.asyncio",
        SimpleNamespace(
            get_running_loop=lambda: SimpleNamespace(time=lambda: osm_time),
            sleep=advance_osm_clock,
        ),
    )
    reverse_url = "https://nominatim.openstreetmap.org/reverse"
    place = {"osm_id": 1, "osm_type": "node", "category": "place", "type": "city"}
    aioclient_mock.get(
        f"{reverse_url}?lat=51.5",
        json={
            **place,
            "address": {"city": "London", "postcode": "SW1A 1AA"},
        },
    )
    entry_id = force_update_entry.entry_id
    assert await hass.config_entries.async_setup(entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.probe").state == "London"
    assert hass.states.get("sensor.probe_postal_code").state == "SW1A 1AA"
    assert aioclient_mock.call_count == 1

    aioclient_mock.clear_requests()
    aioclient_mock.get(
        f"{reverse_url}?lat={latitude}",
        json={
            **place,
            "address": {"city": "London", "postcode": "SW1A 2AA"},
        },
    )
    hass.states.async_set(
        "device_tracker.probe", "not_home", {"latitude": latitude, "longitude": -0.1}
    )
    await hass.async_block_till_done()
    assert aioclient_mock.call_count == 0
    assert hass.states.get("sensor.probe").attributes[ATTR_LATITUDE] == 51.5

    events: list[tuple[dict[str, object], str]] = []

    @callback
    def record_event(event: Event) -> None:
        """Read the published postal code when the Places event fires.

        Args:
            event (Event): Places state update event.
        """
        events.append((event.data, hass.states.get("sensor.probe_postal_code").state))

    hass.bus.async_listen(EVENT_TYPE, record_event)
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.probe_force_update"}, blocking=True
    )
    await hass.async_block_till_done()

    assert aioclient_mock.call_count == 1
    assert osm_time == 1001.0
    main = hass.states.get("sensor.probe")
    assert main.state == "London"
    assert main.attributes[ATTR_LATITUDE] == latitude
    assert len(events) == 1
    event, published_postal_code = events[0]
    assert event["from_state"] == event["to_state"] == "London"
    assert event["postal_code"] == published_postal_code == "SW1A 2AA"
    assert event["latitude"] == latitude

    storage = PlacesStorage(hass, entry_id, "Probe")
    saved = await storage.async_load()
    assert saved[ATTR_NATIVE_VALUE] == "London"
    assert saved[ATTR_POSTAL_CODE] == "SW1A 2AA"
    assert saved[ATTR_LATITUDE] == latitude
    assert saved[ATTR_LATITUDE_OLD] == 51.5
    assert (
        saved[ATTR_MAP_LINK] == hass.states.get("sensor.probe_map_link").state == event["map_link"]
    )

    # Restart without a saved Place to observe what an ordinary lookup gets from the cache.
    assert await hass.config_entries.async_unload(entry_id)
    await storage.async_remove()
    aioclient_mock.clear_requests()
    assert await hass.config_entries.async_setup(entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.probe_postal_code").state == "SW1A 2AA"
    assert aioclient_mock.call_count == 0


@pytest.mark.parametrize(
    "invalid_input", ["missing-entity", "coordinates", "accuracy", "home-zone"]
)
async def test_force_update_preserves_place_when_inputs_are_unusable(
    hass: HomeAssistant,
    force_update_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    monkeypatch: pytest.MonkeyPatch,
    invalid_input: str,
) -> None:
    """Keep the restored Place when pressing the button with an unusable input.

    Args:
        hass (HomeAssistant): Home Assistant runtime with real Places entities.
        force_update_entry (MockConfigEntry): Places entry with its button enabled.
        aioclient_mock (AiohttpClientMocker): HTTP boundary that should remain unused.
        monkeypatch (pytest.MonkeyPatch): Replacement for the Update clock.
        invalid_input (str): The input that should prevent the reverse lookup.
    """
    attributes = {"latitude": 51.7, "longitude": -0.1, "gps_accuracy": 5}
    if invalid_input == "coordinates":
        del attributes["longitude"]
    elif invalid_input == "home-zone":
        hass.states.async_set("zone.home", "0", {"latitude": 51.4})
    if invalid_input == "missing-entity":
        hass.states.async_remove("device_tracker.probe")
    else:
        hass.states.async_set("device_tracker.probe", "not_home", attributes)

    now = datetime(2026, 11, 24, 12, tzinfo=UTC)
    monkeypatch.setattr(
        "custom_components.places.update_sensor.PlacesUpdater.get_current_time",
        AsyncMock(side_effect=lambda: now),
    )
    aioclient_mock.get("https://nominatim.openstreetmap.org/reverse", json={})
    entry_id = force_update_entry.entry_id
    storage = PlacesStorage(hass, entry_id, "Probe")
    await storage.async_save(
        {
            ATTR_NATIVE_VALUE: "London",
            ATTR_CITY: "London",
            ATTR_POSTAL_CODE: "SW1A 1AA",
            ATTR_LATITUDE: 51.5,
            ATTR_LONGITUDE: -0.1,
            ATTR_MAP_LINK: "https://maps.apple.com/?q=51.5%2C-0.1&z=18",
        }
    )
    assert await hass.config_entries.async_setup(entry_id)
    await hass.async_block_till_done()
    accepted = await storage.async_load()
    assert accepted[ATTR_LAST_UPDATED] == "2026-11-24 12:00:00+00:00"
    events = async_capture_events(hass, EVENT_TYPE)
    if invalid_input == "accuracy":
        # The tracker reported a positive accuracy at setup, so its 0 reading is not reported.
        hass.states.async_set("device_tracker.probe", "not_home", {**attributes, "gps_accuracy": 0})
        await hass.async_block_till_done()
        aioclient_mock.clear_requests()

    now += timedelta(minutes=1)
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.probe_force_update"}, blocking=True
    )
    await hass.async_block_till_done()

    assert aioclient_mock.call_count == 0
    assert not events
    main = hass.states.get("sensor.probe")
    assert main.state == "London"
    assert main.attributes[ATTR_LATITUDE] == 51.5
    assert hass.states.get("sensor.probe_postal_code").state == "SW1A 1AA"
    assert hass.states.get("sensor.probe_map_link").state == accepted[ATTR_MAP_LINK]
    saved = await storage.async_load()
    assert saved == {**accepted, ATTR_LAST_UPDATED: "2026-11-24 12:01:00+00:00"}


async def test_failed_force_update_keeps_place_until_an_ordinary_scan_recovers(
    hass: HomeAssistant,
    force_update_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retry an empty Force update result on a later scan without further movement.

    Args:
        hass (HomeAssistant): Home Assistant runtime with real Places entities.
        force_update_entry (MockConfigEntry): Places entry with its button enabled.
        aioclient_mock (AiohttpClientMocker): Mocked OSM HTTP responses.
        monkeypatch (pytest.MonkeyPatch): Replacements for scan and request timing.
    """
    scan_time = 1000.0
    monkeypatch.setattr("custom_components.places.coordinator.monotonic", lambda: scan_time)
    monkeypatch.setattr("homeassistant.util.utcnow", lambda: datetime(2026, 11, 24, 12, tzinfo=UTC))
    monkeypatch.setattr("custom_components.places.osm_client.OSM_THROTTLE_INTERVAL_SECONDS", 0)
    reverse_url = "https://nominatim.openstreetmap.org/reverse"
    place = {"osm_id": 1, "osm_type": "node", "category": "place", "type": "city"}
    aioclient_mock.get(f"{reverse_url}?lat=51.5", json={**place, "address": {"city": "London"}})
    entry_id = force_update_entry.entry_id
    assert await hass.config_entries.async_setup(entry_id)
    await hass.async_block_till_done()
    assert aioclient_mock.call_count == 1

    # A stationary tracked-entity Update starts the existing event cooldown.
    hass.states.async_set(
        "device_tracker.probe", "not_home", {"latitude": 51.5, "longitude": -0.1, "gps_accuracy": 6}
    )
    await hass.async_block_till_done()
    storage = PlacesStorage(hass, entry_id, "Probe")
    accepted = await storage.async_load()
    events = async_capture_events(hass, EVENT_TYPE)
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{reverse_url}?lat=51.7", json={})
    hass.states.async_set(
        "device_tracker.probe", "not_home", {"latitude": 51.7, "longitude": -0.1, "gps_accuracy": 6}
    )
    await hass.async_block_till_done()
    assert aioclient_mock.call_count == 0

    await hass.services.async_call(
        "button", "press", {"entity_id": "button.probe_force_update"}, blocking=True
    )
    await hass.async_block_till_done()

    assert aioclient_mock.call_count == 1
    assert not events
    main = hass.states.get("sensor.probe")
    assert main.state == "London"
    assert main.attributes[ATTR_LATITUDE] == 51.5
    assert hass.states.get("sensor.probe_map_link").state == accepted[ATTR_MAP_LINK]
    saved = await storage.async_load()
    assert saved == {**accepted, ATTR_LAST_UPDATED: saved[ATTR_LAST_UPDATED]}

    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{reverse_url}?lat=51.7", json={**place, "address": {"city": "Oxford"}})
    scan_time += 600
    coordinator: PlacesUpdateCoordinator = force_update_entry.runtime_data
    await coordinator.async_scan_update()
    await hass.async_block_till_done()

    assert aioclient_mock.call_count == 1
    assert len(events) == 1
    assert events[0].data["from_state"] == "London"
    assert events[0].data["to_state"] == hass.states.get("sensor.probe").state == "Oxford"
    recovered = await storage.async_load()
    assert recovered[ATTR_LATITUDE] == 51.7
    assert recovered[ATTR_LATITUDE_OLD] == 51.5
    assert recovered[ATTR_MAP_LINK] == hass.states.get("sensor.probe_map_link").state


# Stationary threshold scaled by the reading's GPS accuracy

_METRES_PER_DEGREE_LATITUDE = 111_195
_REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"
_LONDON_RESPONSE = {
    "osm_id": 1,
    "osm_type": "node",
    "category": "place",
    "type": "city",
    "address": {"city": "London"},
}
_OXFORD_RESPONSE = {**_LONDON_RESPONSE, "address": {"city": "Oxford"}}


@pytest.mark.usefixtures("enable_custom_integrations")
@pytest.mark.parametrize(
    ("tracker_attributes", "use_gps", "moved_m", "expect_update"),
    [
        pytest.param({"gps_accuracy": 80}, True, 40, False, id="inside-accuracy-radius"),
        pytest.param({"gps_accuracy": 80}, True, 200, True, id="beyond-accuracy-radius"),
        pytest.param({"gps_accuracy": 80}, False, 40, True, id="setting-off-ignores-accuracy"),
        pytest.param({}, True, 15, True, id="absent-accuracy-keeps-ten-metres"),
        pytest.param({}, True, 5, False, id="absent-accuracy-inside-ten-metres"),
        pytest.param(
            {"gps_accuracy": 0}, False, 15, True, id="zero-accuracy-setting-off-keeps-ten-metres"
        ),
        pytest.param(
            {"gps_accuracy": 0},
            True,
            15,
            True,
            id="zero-accuracy-never-reported-keeps-ten-metres",
        ),
    ],
)
async def test_movement_threshold_scales_with_gps_accuracy(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    monkeypatch: pytest.MonkeyPatch,
    tracker_attributes: dict[str, float],
    use_gps: bool,
    moved_m: float,
    expect_update: bool,
) -> None:
    """Treat movement inside a reading's GPS accuracy radius as stationary.

    Args:
        hass (HomeAssistant): Home Assistant runtime with real Places entities.
        aioclient_mock (AiohttpClientMocker): Mocked OSM HTTP responses.
        monkeypatch (pytest.MonkeyPatch): Replacement for the OSM throttle interval.
        tracker_attributes (dict[str, float]): GPS attributes on the tracked entity.
        use_gps (bool): Value of the Use GPS Accuracy setting.
        moved_m (float): Distance moved north of the accepted Place, in metres.
        expect_update (bool): Whether the move should trigger a reverse lookup and Update.
    """
    monkeypatch.setattr("custom_components.places.osm_client.OSM_THROTTLE_INTERVAL_SECONDS", 0)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Probe",
        data={
            CONF_NAME: "Probe",
            CONF_DEVICETRACKER_ID: "device_tracker.probe",
            CONF_DISPLAY_OPTIONS: "city",
            CONF_EXTENDED_ATTR: False,
            CONF_SHOW_TIME: False,
            CONF_USE_GPS: use_gps,
        },
    )
    entry.add_to_hass(hass)
    hass.states.async_set("zone.home", "0", {"latitude": 51.4, "longitude": -0.1})
    hass.states.async_set(
        "device_tracker.probe",
        "not_home",
        {"latitude": 51.5, "longitude": -0.1, **tracker_attributes},
    )
    aioclient_mock.get(_REVERSE_URL, json=_LONDON_RESPONSE)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.probe").state == "London"
    assert aioclient_mock.call_count == 1

    latitude = round(51.5 + moved_m / _METRES_PER_DEGREE_LATITUDE, 7)
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{_REVERSE_URL}?lat={latitude}", json=_OXFORD_RESPONSE)
    hass.states.async_set(
        "device_tracker.probe",
        "not_home",
        {"latitude": latitude, "longitude": -0.1, **tracker_attributes},
    )
    await hass.async_block_till_done()

    main = hass.states.get("sensor.probe")
    if expect_update:
        assert aioclient_mock.call_count == 1
        assert main.state == "Oxford"
        assert main.attributes[ATTR_LATITUDE] == latitude
    else:
        assert aioclient_mock.call_count == 0
        assert main.state == "London"
        assert main.attributes[ATTR_LATITUDE] == 51.5


@pytest.mark.usefixtures("enable_custom_integrations")
@pytest.mark.parametrize(
    ("zone_before", "zone_after", "moved_m", "expect_update"),
    [
        pytest.param("not_home", "work", 44, True, id="zone-entry-inside-accuracy-radius-updates"),
        pytest.param(
            "work", "work", 40, False, id="same-zone-jitter-inside-accuracy-radius-stationary"
        ),
    ],
)
async def test_zone_change_inside_accuracy_radius_is_not_stationary(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    monkeypatch: pytest.MonkeyPatch,
    zone_before: str,
    zone_after: str,
    moved_m: float,
    expect_update: bool,
) -> None:
    """Update when the tracked entity enters a zone within its GPS accuracy radius.

    A zone change is a Place change even when the move is inside the reading's
    accuracy radius; movement within the same zone stays stationary.

    Args:
        hass (HomeAssistant): Home Assistant runtime with real Places entities.
        aioclient_mock (AiohttpClientMocker): Mocked OSM HTTP responses.
        monkeypatch (pytest.MonkeyPatch): Replacement for the OSM throttle interval.
        zone_before (str): Tracked entity state before the move.
        zone_after (str): Tracked entity state after the move.
        moved_m (float): Distance moved north of the accepted Place, in metres.
        expect_update (bool): Whether the move should trigger a reverse lookup and Update.
    """
    monkeypatch.setattr("custom_components.places.osm_client.OSM_THROTTLE_INTERVAL_SECONDS", 0)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Probe",
        data={
            CONF_NAME: "Probe",
            CONF_DEVICETRACKER_ID: "device_tracker.probe",
            CONF_DISPLAY_OPTIONS: "zone_name, city",
            CONF_EXTENDED_ATTR: False,
            CONF_SHOW_TIME: False,
            CONF_USE_GPS: True,
        },
    )
    entry.add_to_hass(hass)
    hass.states.async_set("zone.home", "0", {"latitude": 51.4, "longitude": -0.1})
    hass.states.async_set(
        "zone.work",
        "0",
        {
            "friendly_name": "Work",
            "latitude": round(51.5 + 44 / _METRES_PER_DEGREE_LATITUDE, 7),
            "longitude": -0.1,
            "radius": 100,
        },
    )
    tracker_attributes = {"gps_accuracy": 65, "longitude": -0.1}
    hass.states.async_set(
        "device_tracker.probe", zone_before, {"latitude": 51.5, **tracker_attributes}
    )
    aioclient_mock.get(_REVERSE_URL, json=_LONDON_RESPONSE)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert aioclient_mock.call_count == 1

    latitude = round(51.5 + moved_m / _METRES_PER_DEGREE_LATITUDE, 7)
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{_REVERSE_URL}?lat={latitude}", json=_OXFORD_RESPONSE)
    hass.states.async_set(
        "device_tracker.probe", zone_after, {"latitude": latitude, **tracker_attributes}
    )
    await hass.async_block_till_done()

    main = hass.states.get("sensor.probe")
    if expect_update:
        assert aioclient_mock.call_count == 1
        assert main.state == "Work"
        assert main.attributes[ATTR_LATITUDE] == latitude
    else:
        assert aioclient_mock.call_count == 0
        assert main.state == "Work"
        assert main.attributes[ATTR_LATITUDE] == 51.5


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_force_update_bypasses_accuracy_radius_check(
    hass: HomeAssistant,
    force_update_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Let Force update accept a move that is inside the reading's accuracy radius.

    Args:
        hass (HomeAssistant): Home Assistant runtime with real Places entities.
        force_update_entry (MockConfigEntry): Places entry with its button enabled.
        aioclient_mock (AiohttpClientMocker): Mocked OSM HTTP responses.
        monkeypatch (pytest.MonkeyPatch): Replacement for the OSM throttle interval.
    """
    monkeypatch.setattr("custom_components.places.osm_client.OSM_THROTTLE_INTERVAL_SECONDS", 0)
    aioclient_mock.get(_REVERSE_URL, json=_LONDON_RESPONSE)
    assert await hass.config_entries.async_setup(force_update_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.probe").state == "London"
    assert aioclient_mock.call_count == 1

    aioclient_mock.clear_requests()
    aioclient_mock.get(_REVERSE_URL, json=_LONDON_RESPONSE)
    latitude = round(51.5 + 40 / _METRES_PER_DEGREE_LATITUDE, 7)
    hass.states.async_set(
        "device_tracker.probe",
        "not_home",
        {"latitude": latitude, "longitude": -0.1, "gps_accuracy": 80},
    )
    await hass.async_block_till_done()
    assert aioclient_mock.call_count == 0
    assert hass.states.get("sensor.probe").attributes[ATTR_LATITUDE] == 51.5

    await hass.services.async_call(
        "button", "press", {"entity_id": "button.probe_force_update"}, blocking=True
    )
    await hass.async_block_till_done()
    assert aioclient_mock.call_count == 1
    assert hass.states.get("sensor.probe").attributes[ATTR_LATITUDE] == latitude


@pytest.mark.asyncio
@pytest.mark.parametrize(("unload_return", "expected"), [(True, True), (False, False)])
async def test_async_unload_entry_result(
    mock_hass: MagicMock, mock_entry: MockConfigEntry, unload_return: bool, expected: bool
) -> None:
    """Unload should proxy the platform result and only finalize shutdown on success.

    Args:
        mock_hass (MagicMock):
            Mocked Home Assistant runtime.
        mock_entry (MockConfigEntry):
            Places configuration entry used by the test.
        unload_return (bool):
            Platform-unload result returned by the mock.
        expected (bool):
            Expected result for this parametrized case.
    """
    coordinator = _FakeCoordinator(mock_hass, mock_entry, {}, MagicMock())
    mock_entry.runtime_data = coordinator
    mock_hass.config_entries.async_unload_platforms.return_value = unload_return

    result = await async_unload_entry(mock_hass, mock_entry)

    assert result is expected
    mock_hass.config_entries.async_unload_platforms.assert_awaited_once_with(mock_entry, PLATFORMS)
    coordinator.async_prepare_unload.assert_awaited_once_with()
    if unload_return:
        coordinator.async_shutdown.assert_awaited_once_with()
        coordinator.async_resume_after_failed_unload.assert_not_awaited()
        assert mock_entry.runtime_data is None
    else:
        coordinator.async_shutdown.assert_not_awaited()
        coordinator.async_resume_after_failed_unload.assert_awaited_once_with()
        assert mock_entry.runtime_data is coordinator


@pytest.mark.asyncio
async def test_async_unload_entry_prepares_unload_before_platform_unload_and_shutdowns_after_success(
    mock_hass: MagicMock, mock_entry: MockConfigEntry
) -> None:
    """Teardown should stop update work before unloading and finalize after success.

    Args:
        mock_hass (MagicMock):
            Mocked Home Assistant runtime.
        mock_entry (MockConfigEntry):
            Places configuration entry used by the test.
    """
    coordinator = _FakeCoordinator(mock_hass, mock_entry, {}, MagicMock())
    mock_entry.runtime_data = coordinator
    call_order: list[str] = []

    async def mark_prepare_unload() -> None:
        call_order.append("prepare_unload")

    async def mark_unload(_entry: MockConfigEntry, _platforms: list[str]) -> bool:
        call_order.append("unload_platforms")
        return True

    async def mark_shutdown() -> None:
        call_order.append("shutdown")

    coordinator.async_prepare_unload.side_effect = mark_prepare_unload
    coordinator.async_shutdown.side_effect = mark_shutdown
    mock_hass.config_entries.async_unload_platforms.side_effect = mark_unload

    result = await async_unload_entry(mock_hass, mock_entry)

    assert result is True
    assert call_order == ["prepare_unload", "unload_platforms", "shutdown"]


@pytest.mark.asyncio
async def test_async_unload_entry_completes_when_shutdown_raises(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    mock_hass: MagicMock,
) -> None:
    """Shutdown failure after platform unload should not leave entry-owned state active.

    Args:
        caplog (pytest.LogCaptureFixture):
            Captured log records used for message assertions.
        monkeypatch (pytest.MonkeyPatch):
            Pytest fixture for replacing dependencies.
        mock_hass (MagicMock):
            Mocked Home Assistant runtime.
    """
    entry = MockConfigEntry(
        domain="places",
        data={
            "name": "TestSensor",
            "devicetracker_id": "person.test",
            CONF_EXTENDED_ATTR: True,
        },
    )
    monkeypatch.setattr("custom_components.places.PlacesStorage", _FakeSetupPlacesStorage)
    monkeypatch.setattr("custom_components.places.PlacesUpdateCoordinator", _FakeCoordinator)
    await async_setup_entry(mock_hass, entry)
    coordinator = entry.runtime_data
    coordinator.async_shutdown.side_effect = RuntimeError("shutdown boom")

    with caplog.at_level(logging.ERROR, logger="custom_components.places"):
        result = await async_unload_entry(mock_hass, entry)

    assert result is True
    mock_hass.config_entries.async_unload_platforms.assert_awaited_once_with(entry, PLATFORMS)
    coordinator.async_prepare_unload.assert_awaited_once_with()
    assert entry.runtime_data is None
    assert "shutdown failed" in caplog.text
    assert entry.entry_id in caplog.text


@pytest.mark.asyncio
async def test_async_unload_entry_resumes_coordinator_when_platform_unload_fails(
    mock_hass: MagicMock, mock_entry: MockConfigEntry
) -> None:
    """A failed platform unload should leave the still-loaded coordinator active.

    Args:
        mock_hass (MagicMock):
            Mocked Home Assistant runtime.
        mock_entry (MockConfigEntry):
            Places configuration entry used by the test.
    """
    coordinator = _FakeCoordinator(mock_hass, mock_entry, {}, MagicMock())
    mock_entry.runtime_data = coordinator
    call_order: list[str] = []

    async def mark_prepare_unload() -> None:
        call_order.append("prepare_unload")

    async def mark_unload(_entry: MockConfigEntry, _platforms: list[str]) -> bool:
        call_order.append("unload_platforms")
        return False

    async def mark_resume() -> None:
        call_order.append("resume")

    coordinator.async_prepare_unload.side_effect = mark_prepare_unload
    coordinator.async_resume_after_failed_unload.side_effect = mark_resume
    mock_hass.config_entries.async_unload_platforms.side_effect = mark_unload

    result = await async_unload_entry(mock_hass, mock_entry)

    assert result is False
    assert call_order == ["prepare_unload", "unload_platforms", "resume"]
    coordinator.async_shutdown.assert_not_awaited()


@pytest.mark.asyncio
async def test_async_unload_entry_resumes_coordinator_when_prepare_unload_raises(
    caplog: pytest.LogCaptureFixture,
    mock_hass: MagicMock,
    mock_entry: MockConfigEntry,
) -> None:
    """A prepare failure should leave the still-loaded coordinator active.

    Args:
        caplog (pytest.LogCaptureFixture):
            Captured log records used for message assertions.
        mock_hass (MagicMock):
            Mocked Home Assistant runtime.
        mock_entry (MockConfigEntry):
            Places configuration entry used by the test.
    """
    coordinator = _FakeCoordinator(mock_hass, mock_entry, {}, MagicMock())
    mock_entry.runtime_data = coordinator
    coordinator.async_prepare_unload.side_effect = RuntimeError("prepare boom")

    with (
        caplog.at_level(logging.ERROR, logger="custom_components.places"),
        pytest.raises(RuntimeError, match="prepare boom"),
    ):
        await async_unload_entry(mock_hass, mock_entry)

    coordinator.async_resume_after_failed_unload.assert_awaited_once_with()
    mock_hass.config_entries.async_unload_platforms.assert_not_awaited()
    coordinator.async_shutdown.assert_not_awaited()
    assert mock_entry.runtime_data is coordinator
    assert "prepare_unload" in caplog.text
    assert mock_entry.entry_id in caplog.text
    assert repr(coordinator) in caplog.text


@pytest.mark.asyncio
async def test_async_unload_entry_resumes_coordinator_when_platform_unload_raises(
    caplog: pytest.LogCaptureFixture,
    mock_hass: MagicMock,
    mock_entry: MockConfigEntry,
) -> None:
    """An unload exception should leave the still-loaded coordinator active.

    Args:
        caplog (pytest.LogCaptureFixture):
            Captured log records used for message assertions.
        mock_hass (MagicMock):
            Mocked Home Assistant runtime.
        mock_entry (MockConfigEntry):
            Places configuration entry used by the test.
    """
    coordinator = _FakeCoordinator(mock_hass, mock_entry, {}, MagicMock())
    mock_entry.runtime_data = coordinator
    mock_hass.config_entries.async_unload_platforms.side_effect = RuntimeError("unload boom")

    with (
        caplog.at_level(logging.ERROR, logger="custom_components.places"),
        pytest.raises(RuntimeError, match="unload boom"),
    ):
        await async_unload_entry(mock_hass, mock_entry)

    coordinator.async_prepare_unload.assert_awaited_once_with()
    coordinator.async_resume_after_failed_unload.assert_awaited_once_with()
    coordinator.async_shutdown.assert_not_awaited()
    assert "unload_platforms" in caplog.text
    assert mock_entry.entry_id in caplog.text
    assert repr(coordinator) in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure_path", "expected_error", "expected_result"),
    [
        ("prepare_exception", "prepare boom", None),
        ("unload_exception", "unload boom", None),
        ("unload_false", None, False),
    ],
)
async def test_async_unload_entry_resume_failure_preserves_unload_result(
    caplog: pytest.LogCaptureFixture,
    mock_hass: MagicMock,
    mock_entry: MockConfigEntry,
    failure_path: str,
    expected_error: str | None,
    expected_result: bool | None,
) -> None:
    """Resume cleanup failures should not mask the unload terminal state.

    Args:
        caplog (pytest.LogCaptureFixture):
            Captured log records used for message assertions.
        mock_hass (MagicMock):
            Mocked Home Assistant runtime.
        mock_entry (MockConfigEntry):
            Places configuration entry used by the test.
        failure_path (str):
            Failure stage selected by the parametrized case.
        expected_error (str | None):
            Error text expected from the failure path.
        expected_result (bool | None):
            Return result expected for this parametrized case.
    """
    coordinator = _FakeCoordinator(mock_hass, mock_entry, {}, MagicMock())
    mock_entry.runtime_data = coordinator
    coordinator.async_resume_after_failed_unload.side_effect = RuntimeError("resume boom")
    if failure_path == "prepare_exception":
        coordinator.async_prepare_unload.side_effect = RuntimeError("prepare boom")
    elif failure_path == "unload_exception":
        mock_hass.config_entries.async_unload_platforms.side_effect = RuntimeError("unload boom")
    else:
        mock_hass.config_entries.async_unload_platforms.return_value = False

    with caplog.at_level(logging.ERROR, logger="custom_components.places"):
        if expected_error is not None:
            with pytest.raises(RuntimeError, match=expected_error):
                await async_unload_entry(mock_hass, mock_entry)
        else:
            assert await async_unload_entry(mock_hass, mock_entry) is expected_result

    coordinator.async_resume_after_failed_unload.assert_awaited_once_with()
    coordinator.async_shutdown.assert_not_awaited()
    assert mock_entry.runtime_data is coordinator
    assert "resume_after_failed_unload" in caplog.text
    assert "resume boom" in caplog.text


@pytest.fixture
async def loaded_lifecycle_entry(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> tuple[MockConfigEntry, PlacesStorage, MagicMock]:
    """Load a Places entry at its saved Place with a controllable HTTP session.

    Args:
        hass (HomeAssistant): Home Assistant runtime with real Places entities.
        monkeypatch (pytest.MonkeyPatch): Replacements for the HTTP boundary.

    Returns:
        tuple[MockConfigEntry, PlacesStorage, MagicMock]: Loaded entry, Store, and HTTP session.
    """
    session = MagicMock()
    monkeypatch.setattr(
        "custom_components.places.osm_client.async_get_clientsession", lambda _hass: session
    )
    monkeypatch.setattr("custom_components.places.osm_client.OSM_THROTTLE_INTERVAL_SECONDS", 0)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Lifecycle",
        data={
            CONF_NAME: "Lifecycle",
            CONF_DEVICETRACKER_ID: "device_tracker.lifecycle",
            CONF_DISPLAY_OPTIONS: "city",
            CONF_EXTENDED_ATTR: True,
            CONF_SHOW_TIME: False,
        },
    )
    entry.add_to_hass(hass)
    storage = PlacesStorage(hass, entry.entry_id, "Lifecycle")
    er.async_get(hass).async_get_or_create(
        "switch",
        DOMAIN,
        f"{entry.entry_id}_{CONF_SHOW_TIME}",
        suggested_object_id="lifecycle_show_last_updated",
    )
    await storage.async_save(
        {
            ATTR_NATIVE_VALUE: "London",
            ATTR_CITY: "London",
            ATTR_LATITUDE: 51.5,
            ATTR_LONGITUDE: -0.1,
            ATTR_MAP_LINK: "https://maps.apple.com/?q=51.5%2C-0.1&z=18",
        }
    )
    hass.states.async_set("zone.home", "0", {"latitude": 51.4, "longitude": -0.1})
    hass.states.async_set(
        "device_tracker.lifecycle", "not_home", {"latitude": 51.5, "longitude": -0.1}
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    session.get.assert_not_called()
    return entry, storage, session


def _lifecycle_response(body: str | Callable[[], Awaitable[str]]) -> MagicMock:
    """Mock an HTTP response with a fixed body or a controlled asynchronous read.

    Args:
        body (str | Callable[[], Awaitable[str]]): JSON text or asynchronous reader.

    Returns:
        MagicMock: Async context manager returned by the HTTP session.
    """
    read = AsyncMock(return_value=body) if isinstance(body, str) else body
    return MagicMock(__aenter__=AsyncMock(return_value=MagicMock(status=200, text=read)))


@pytest.mark.parametrize("interruption", ["cancel", "reload"])
async def test_force_update_finalizes_published_place(
    hass: HomeAssistant,
    force_update_entry: MockConfigEntry,
    monkeypatch: pytest.MonkeyPatch,
    interruption: str,
) -> None:
    """Save and announce an accepted Place once across a cancellation or reload.

    Args:
        hass (HomeAssistant): Home Assistant runtime with real Places entities.
        force_update_entry (MockConfigEntry): Entry with Force update enabled.
        monkeypatch (pytest.MonkeyPatch): Replacements for the HTTP boundary.
        interruption (str): Lifecycle action triggered by publication or the event.
    """
    session = MagicMock()
    monkeypatch.setattr(
        "custom_components.places.osm_client.async_get_clientsession", lambda _hass: session
    )
    monkeypatch.setattr("custom_components.places.osm_client.OSM_THROTTLE_INTERVAL_SECONDS", 0)
    session.get.return_value = _lifecycle_response('{"address":{"city":"London"}}')
    entry_id = force_update_entry.entry_id
    assert await hass.config_entries.async_setup(entry_id)
    await hass.async_block_till_done()
    session.get.return_value = _lifecycle_response("{}")
    hass.states.async_set(
        "device_tracker.probe", "not_home", {"latitude": 51.7, "longitude": -0.1, "gps_accuracy": 5}
    )
    await hass.async_block_till_done()
    assert hass.states.get("sensor.probe").state == "London"

    session.get.reset_mock()
    session.get.return_value = _lifecycle_response('{"address":{"city":"Oxford"}}')
    storage = PlacesStorage(hass, entry_id, "Probe")
    announcements: list[tuple[str, str]] = []
    reload_tasks: list[asyncio.Task[bool]] = []

    @callback
    def cancel_on_publish(event: Event[EventStateChangedData]) -> None:
        """Cancel the service caller as Oxford is published.

        Args:
            event (Event[EventStateChangedData]): Main sensor state change.
        """
        state = event.data["new_state"]
        if state is not None and state.state == "Oxford":
            service_call.cancel()

    @callback
    def observe_event(event: Event) -> None:
        """Read the sensor on every event and optionally reload the entry once.

        Args:
            event (Event): Places state update event.
        """
        announcements.append((event.data["to_state"], hass.states.get("sensor.probe").state))
        if interruption == "reload" and not reload_tasks:
            reload_tasks.append(hass.async_create_task(hass.config_entries.async_reload(entry_id)))

    hass.bus.async_listen(EVENT_TYPE, observe_event)
    if interruption == "cancel":
        async_track_state_change_event(hass, "sensor.probe", cancel_on_publish)
    service_call = hass.async_create_task(
        hass.services.async_call(
            "button", "press", {"entity_id": "button.probe_force_update"}, blocking=True
        ),
        eager_start=False,
    )
    if interruption == "cancel":
        with pytest.raises(asyncio.CancelledError):
            await service_call
    else:
        await service_call
    await hass.async_block_till_done()

    if interruption == "reload":
        (reload_task,) = reload_tasks
        assert reload_task.result()
    assert announcements == [("Oxford", "Oxford")]
    assert hass.states.get("sensor.probe").state == "Oxford"
    snapshot = await storage.async_load()
    assert snapshot[ATTR_LATITUDE] == 51.7
    assert snapshot[ATTR_NATIVE_VALUE] == "Oxford"
    session.get.assert_called_once()


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_tracker_update_finalizes_during_home_assistant_stop(
    hass: HomeAssistant,
    loaded_lifecycle_entry: tuple[MockConfigEntry, PlacesStorage, MagicMock],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Drain accepted Place disk write and announcement during shutdown stage two.

    Args:
        hass (HomeAssistant): Home Assistant runtime with the Places entry loaded.
        loaded_lifecycle_entry (tuple[MockConfigEntry, PlacesStorage, MagicMock]): Entry fixture.
        monkeypatch (pytest.MonkeyPatch): Replacement for Store disk write.
        tmp_path (Path): Temporary Store directory for a real executor-backed disk write.
    """
    entry, _, session = loaded_lifecycle_entry
    storage: PlacesStorage = entry.runtime_data._persistence
    store = storage._store
    file_io = store._io
    file_io.path = str(tmp_path / "places-store.json")
    async_write_attribute = "async_write"
    production_async_write = getattr(type(file_io).__mro__[1], async_write_attribute).__get__(
        file_io
    )
    monkeypatch.setattr(file_io, "async_write", production_async_write)
    session.get.return_value = _lifecycle_response('{"address":{"city":"Oxford"}}')
    disk_started = ThreadEvent()
    release_disk_write = ThreadEvent()
    disk_write_finished = ThreadEvent()
    original_disk_write = file_io._write

    def hold_disk_write(*args: object) -> object:
        """Hold the production Store file write until the test releases it.

        Args:
            *args (object): Arguments passed to the Store's file write.

        Returns:
            object: Result from the production file write.

        Raises:
            TimeoutError: The test did not release the write.
        """
        disk_started.set()
        try:
            if not release_disk_write.wait(timeout=10):
                raise TimeoutError("Timed out waiting to release the Store disk write")
            return original_disk_write(*args)
        finally:
            disk_write_finished.set()

    monkeypatch.setattr(file_io, "_write", hold_disk_write)
    events = async_capture_events(hass, EVENT_TYPE)
    event_order: list[str] = []
    final_write_started = asyncio.Event()

    @callback
    def record_place_event(_event: Event) -> None:
        """Record when the accepted Place event is fired.

        Args:
            _event (Event): Places update event.
        """
        event_order.append("place")

    @callback
    def record_final_write(_event: Event) -> None:
        """Record when Home Assistant reaches its final-write phase.

        Args:
            _event (Event): Home Assistant final-write event.
        """
        event_order.append("final_write")
        final_write_started.set()

    hass.bus.async_listen(EVENT_TYPE, record_place_event)
    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_FINAL_WRITE, record_final_write)
    hass.states.async_set("device_tracker.lifecycle", "away", {"latitude": 51.7, "longitude": -0.1})
    await asyncio.wait_for(asyncio.to_thread(disk_started.wait, 10), timeout=2)
    main_state = hass.states.get("sensor.lifecycle")
    assert main_state is not None and main_state.state == "Oxford"
    event_order_before_disk_release = list(event_order)

    stop_task = hass.async_create_task(hass.async_stop())
    try:
        with suppress(TimeoutError):
            await asyncio.wait_for(final_write_started.wait(), timeout=0.5)
        final_write_before_disk_release = final_write_started.is_set()
    finally:
        release_disk_write.set()
    await asyncio.wait_for(stop_task, timeout=5)
    assert await asyncio.to_thread(disk_write_finished.wait, 2)

    assert [event.data["to_state"] for event in events] == ["Oxford"]
    assert event_order_before_disk_release == []
    assert not final_write_before_disk_release
    assert event_order == ["place", "final_write"]
    assert (
        json.loads((tmp_path / "places-store.json").read_text())["data"][ATTR_NATIVE_VALUE]
        == "Oxford"
    )


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_tracker_update_does_not_announce_a_deferred_stop_write(
    hass: HomeAssistant,
    loaded_lifecycle_entry: tuple[MockConfigEntry, PlacesStorage, MagicMock],
) -> None:
    """Save a Place accepted during STOP without inviting a premature entry reload.

    Args:
        hass (HomeAssistant): Home Assistant runtime with the Places entry loaded.
        loaded_lifecycle_entry (tuple[MockConfigEntry, PlacesStorage, MagicMock]): Entry fixture.
    """
    entry, storage, session = loaded_lifecycle_entry
    session.get.return_value = _lifecycle_response('{"address":{"city":"Oxford"}}')
    assert hass.states.get("sensor.lifecycle").state == "London"
    announcements: list[str] = []

    @callback
    def move_during_stop(_event: Event) -> None:
        """Move the tracked entity once Home Assistant is stopping.

        Args:
            _event (Event): Home Assistant stop event.
        """
        hass.states.async_set(
            "device_tracker.lifecycle", "away", {"latitude": 51.7, "longitude": -0.1}
        )

    @callback
    def reload_on_announcement(event: Event) -> None:
        """Reload once a Places event subscriber is told about the accepted Place.

        Args:
            event (Event): Places state update event.
        """
        announcements.append(event.data["to_state"])
        if len(announcements) == 1:
            hass.config_entries.async_schedule_reload(entry.entry_id)

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, move_during_stop)
    hass.bus.async_listen(EVENT_TYPE, reload_on_announcement)
    await asyncio.wait_for(hass.async_stop(), timeout=5)

    assert announcements == []
    assert hass.states.get("sensor.lifecycle").state == "Oxford"
    assert (await storage.async_load())[ATTR_NATIVE_VALUE] == "Oxford"


@pytest.mark.usefixtures("enable_custom_integrations")
@pytest.mark.parametrize(
    ("unload_timing", "unload_succeeds"),
    [
        ("during-publish", True),
        ("after-publish", True),
        ("nested-bus", True),
        ("force-after-publish", True),
        ("during-publish", False),
    ],
)
async def test_places_event_waits_for_unload_outcome(
    hass: HomeAssistant,
    loaded_lifecycle_entry: tuple[MockConfigEntry, PlacesStorage, MagicMock],
    monkeypatch: pytest.MonkeyPatch,
    unload_timing: str,
    *,
    unload_succeeds: bool,
) -> None:
    """Suppress the published Place event during unload and recover it if unload fails.

    Args:
        hass (HomeAssistant): Home Assistant runtime with the Places entry loaded.
        loaded_lifecycle_entry (tuple[MockConfigEntry, PlacesStorage, MagicMock]): Entry fixture.
        monkeypatch (pytest.MonkeyPatch): Replacement for Home Assistant platform unload.
        unload_timing (str): How sensor publication overlaps unload and bus dispatch.
        unload_succeeds (bool): Whether the platforms agree to unload.
    """
    entry, storage, session = loaded_lifecycle_entry
    accepted = await storage.async_load()
    request_started = asyncio.Event()
    release_request = asyncio.Event()
    oxford = '{"osm_type":"node","category":"place","address":{"city":"Oxford"}}'

    async def read_reverse_response() -> str:
        """Wait until the tracked entity task is running before returning Oxford.

        Returns:
            str: Usable reverse geocoding response body.
        """
        request_started.set()
        await release_request.wait()
        return oxford

    session.get.return_value = _lifecycle_response(
        oxford if unload_timing == "nested-bus" else read_reverse_response
    )
    events = async_capture_events(hass, EVENT_TYPE)
    unload_tasks: list[asyncio.Task[bool]] = []
    setting_errors: list[ServiceValidationError] = []
    coordinator: PlacesUpdateCoordinator = entry.runtime_data

    async def refuse_platform_unload(_entry: object, _platforms: object) -> bool:
        """Check finalization is suspended while the platforms decide whether to unload.

        Args:
            _entry (object): Entry Home Assistant is unloading.
            _platforms (object): Platforms Home Assistant should unload.

        Returns:
            bool: Platform unload result.
        """
        assert not events
        assert await storage.async_load() == accepted
        try:
            await hass.services.async_call(
                "switch",
                "turn_on",
                {"entity_id": "switch.lifecycle_show_last_updated"},
                blocking=True,
            )
        except ServiceValidationError as error:
            setting_errors.append(error)
        return False

    @callback
    def unload_on_publish(event: Event[EventStateChangedData]) -> None:
        """Start unloading when Home Assistant publishes Oxford.

        Args:
            event (Event[EventStateChangedData]): Main sensor state change.
        """
        state = event.data["new_state"]
        if state is not None and state.state == "Oxford":
            unload_tasks.append(
                hass.async_create_task(
                    hass.config_entries.async_unload(entry.entry_id),
                    eager_start=unload_timing not in {"after-publish", "force-after-publish"},
                )
            )

    with monkeypatch.context() as patch:
        if not unload_succeeds:
            patch.setattr(hass.config_entries, "async_unload_platforms", refuse_platform_unload)
        async_track_state_change_event(hass, "sensor.lifecycle", unload_on_publish)
        force = None
        if unload_timing == "force-after-publish":
            force = hass.async_create_task(coordinator.async_force_update())
        else:
            hass.states.async_set(
                "device_tracker.lifecycle", "away", {"latitude": 51.7, "longitude": -0.1}
            )
        if unload_timing != "nested-bus":
            await asyncio.wait_for(request_started.wait(), timeout=2)
            release_request.set()
        await hass.async_block_till_done()

    (unload_task,) = unload_tasks
    assert unload_task.result() is unload_succeeds
    if force is not None:
        await force
    if unload_succeeds:
        assert not events
        assert await storage.async_load() == accepted
    else:
        # Allow the resumed scan to run, then drain the refresh debouncer on the failed entry.
        async_fire_time_changed(hass, datetime.now(UTC) + timedelta(seconds=11))
        await hass.async_block_till_done()
        await coordinator.async_shutdown()
        (setting_error,) = setting_errors
        assert setting_error.translation_domain == "homeassistant"
        assert setting_error.translation_key == "service_config_entry_not_loaded"
        assert setting_error.translation_placeholders == {
            "domain": DOMAIN,
            "entry_title": entry.title,
        }
        assert entry.data[CONF_SHOW_TIME] is False
        assert hass.states.get("sensor.lifecycle").state == "Oxford"
        assert [event.data["to_state"] for event in events] == ["Oxford"]
        snapshot = await storage.async_load()
        assert snapshot[ATTR_LATITUDE] == 51.7
        assert snapshot[ATTR_NATIVE_VALUE] == "Oxford"
        session.get.assert_called_once()


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_unload_drains_scan_during_extended_data_lookup(
    hass: HomeAssistant,
    loaded_lifecycle_entry: tuple[MockConfigEntry, PlacesStorage, MagicMock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Drain an interrupted scan before tearing down its sensors or starting Wikidata.

    Args:
        hass (HomeAssistant): Home Assistant runtime with the Places entry loaded.
        loaded_lifecycle_entry (tuple[MockConfigEntry, PlacesStorage, MagicMock]): Entry fixture.
        monkeypatch (pytest.MonkeyPatch): Replacements for the scan and tracker clocks.
    """
    entry, storage, session = loaded_lifecycle_entry
    coordinator: PlacesUpdateCoordinator = entry.runtime_data
    scan_clock = monotonic() + 600
    monkeypatch.setattr("custom_components.places.coordinator.monotonic", lambda: scan_clock)
    monkeypatch.setattr("homeassistant.util.utcnow", lambda: datetime(2026, 11, 24, tzinfo=UTC))
    hass.states.async_set("device_tracker.lifecycle", "away", {"latitude": 51.5, "longitude": -0.1})
    await hass.async_block_till_done()
    accepted = await storage.async_load()
    main = hass.states.get("sensor.lifecycle")
    link = hass.states.get("sensor.lifecycle_map_link")
    assert main is not None and link is not None

    details_started = asyncio.Event()
    release_details = asyncio.Event()

    async def read_details_response() -> str:
        """Hold the OSM lookup until unload starts, then offer a Wikidata ID.

        Returns:
            str: Usable Extended data body pointing to Wikidata.
        """
        details_started.set()
        await release_details.wait()
        return '[{"extratags":{"wikidata":"Q34217"}}]'

    session.get.side_effect = [
        _lifecycle_response(
            '{"osm_id":2,"osm_type":"node","category":"place","address":{"city":"Oxford"}}'
        ),
        _lifecycle_response(read_details_response),
        _lifecycle_response("{}"),
    ]
    events = async_capture_events(hass, EVENT_TYPE)
    hass.states.async_set("device_tracker.lifecycle", "away", {"latitude": 51.7, "longitude": -0.1})
    scan = hass.async_create_task(coordinator.async_scan_update())
    await asyncio.wait_for(details_started.wait(), timeout=2)

    unload = hass.async_create_task(hass.config_entries.async_unload(entry.entry_id))
    try:
        assert entry.state is ConfigEntryState.UNLOAD_IN_PROGRESS
        assert not unload.done()
        assert hass.states.get("sensor.lifecycle") == main
        assert hass.states.get("sensor.lifecycle_map_link") == link
        await coordinator.async_force_update()
    finally:
        release_details.set()

    drained = await asyncio.wait_for(scan, timeout=2)
    assert await asyncio.wait_for(unload, timeout=2)
    unloaded_main = hass.states.get("sensor.lifecycle")
    assert unloaded_main is not None and unloaded_main.state == STATE_UNAVAILABLE
    assert [urlparse(call.args[0]).path for call in session.get.call_args_list] == [
        "/reverse",
        "/lookup",
    ]
    assert drained.native_value == "London"
    assert drained.attributes[ATTR_LATITUDE] == 51.5
    assert not events
    assert await storage.async_load() == accepted


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_overlapping_tracker_and_scan_updates_use_latest_accepted_place(
    hass: HomeAssistant,
    loaded_lifecycle_entry: tuple[MockConfigEntry, PlacesStorage, MagicMock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Serialize scans and tracker Updates and throttle scans from completion.

    Args:
        hass (HomeAssistant): Home Assistant runtime with the Places entry loaded.
        loaded_lifecycle_entry (tuple[MockConfigEntry, PlacesStorage, MagicMock]): Entry fixture.
        monkeypatch (pytest.MonkeyPatch): Replacements for the scan and tracker clocks.
    """
    entry, storage, session = loaded_lifecycle_entry
    coordinator: PlacesUpdateCoordinator = entry.runtime_data
    # Start beyond the setup scan's throttle with exact whole-second advances.
    scan_clock = ceil(monotonic()) + 600
    tracker_clock = datetime(2026, 11, 24, tzinfo=UTC)
    monkeypatch.setattr("custom_components.places.coordinator.monotonic", lambda: scan_clock)
    monkeypatch.setattr("homeassistant.util.utcnow", lambda: tracker_clock)
    hass.states.async_set("device_tracker.lifecycle", "away", {"latitude": 51.5, "longitude": -0.1})
    await hass.async_block_till_done()

    request_started = asyncio.Event()
    release_request = asyncio.Event()

    async def read_reverse_response() -> str:
        """Hold Oxford's reverse lookup while a scan and tracker Update overlap.

        Returns:
            str: Successful reverse geocoding response body.
        """
        request_started.set()
        await release_request.wait()
        return '{"osm_type":"node","category":"place","address":{"city":"Oxford"}}'

    session.get.side_effect = [
        _lifecycle_response(read_reverse_response),
        _lifecycle_response(
            '{"osm_type":"node","category":"place","address":{"city":"Cambridge"}}'
        ),
    ]
    hass.states.async_set("device_tracker.lifecycle", "away", {"latitude": 51.7, "longitude": -0.1})
    scan = hass.async_create_task(coordinator.async_scan_update())
    await asyncio.wait_for(request_started.wait(), timeout=2)

    try:
        overlapping_scan = hass.async_create_task(coordinator.async_scan_update())
        tracker_clock += timedelta(seconds=11)
        hass.states.async_set(
            "device_tracker.lifecycle", "nearby", {"latitude": 51.70001, "longitude": -0.1}
        )
        assert not overlapping_scan.done()
        assert (await storage.async_load())[ATTR_LATITUDE] == 51.5
        assert session.get.call_count == 1
        scan_clock += 30
    finally:
        release_request.set()

    await hass.async_block_till_done()
    assert scan.result().native_value == overlapping_scan.result().native_value == "Oxford"
    saved = await storage.async_load()
    assert saved[ATTR_LATITUDE] == 51.7
    assert saved[ATTR_DEVICETRACKER_ZONE] == "nearby"
    assert session.get.call_count == 1

    hass.states.async_set("device_tracker.lifecycle", "away", {"latitude": 51.9, "longitude": -0.1})
    scan_clock += 599
    assert (await coordinator.async_scan_update()).native_value == "Oxford"
    assert session.get.call_count == 1
    scan_clock += 1
    assert (await coordinator.async_scan_update()).native_value == "Cambridge"
    city = hass.states.get("sensor.lifecycle_city")
    assert city is not None and city.state == "Cambridge"
    saved = await storage.async_load()
    assert saved[ATTR_LATITUDE] == 51.9
    assert saved[ATTR_LATITUDE_OLD] == 51.7
    assert [
        parse_qs(urlparse(call.args[0]).query)["lat"] for call in session.get.call_args_list
    ] == [
        ["51.7"],
        ["51.9"],
    ]


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_failed_unload_drains_tracker_and_resumes_updates(
    hass: HomeAssistant,
    loaded_lifecycle_entry: tuple[MockConfigEntry, PlacesStorage, MagicMock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Drain tracker cancellation and resume Updates from the accepted Place.

    Args:
        hass (HomeAssistant): Home Assistant runtime with the Places entry loaded.
        loaded_lifecycle_entry (tuple[MockConfigEntry, PlacesStorage, MagicMock]): Entry fixture.
        monkeypatch (pytest.MonkeyPatch): Simulated platform unload failure and tracker clock.
    """
    entry, storage, session = loaded_lifecycle_entry
    accepted = await storage.async_load()
    tracker_clock = datetime(2026, 11, 24, tzinfo=UTC)
    monkeypatch.setattr("homeassistant.util.utcnow", lambda: tracker_clock)
    request_started = asyncio.Event()
    cancellation_started = asyncio.Event()
    release_request_cleanup = asyncio.Event()
    tracker_task: asyncio.Task[object] | None = None

    async def read_interrupted_response() -> str:
        """Hold the reverse lookup and its cleanup until the test releases them.

        Returns:
            str: Pending response body.

        Raises:
            asyncio.CancelledError: The entry unload cancels the tracked entity Update.
        """
        nonlocal tracker_task
        tracker_task = asyncio.current_task()
        request_started.set()
        try:
            return await asyncio.Future[str]()
        except asyncio.CancelledError:
            cancellation_started.set()
            await release_request_cleanup.wait()
            raise

    session.get.side_effect = [
        _lifecycle_response(read_interrupted_response),
        _lifecycle_response('{"osm_type":"node","category":"place","address":{"city":"Oxford"}}'),
        _lifecycle_response(
            '{"osm_type":"node","category":"place","address":{"city":"Cambridge"}}'
        ),
    ]
    events = async_capture_events(hass, EVENT_TYPE)

    async def refuse_platform_unload(_entry: object, _platforms: object) -> bool:
        """Verify the accepted Place at teardown, then leave the platforms loaded.

        Args:
            _entry (object): Entry passed to Home Assistant's platform unload boundary.
            _platforms (object): Platforms Home Assistant should unload.

        Returns:
            bool: Platform unload result.
        """
        assert tracker_task is not None and tracker_task.cancelled()
        main = hass.states.get("sensor.lifecycle")
        assert main is not None and main.state == "London"
        assert main.attributes[ATTR_LATITUDE] == 51.5
        assert await storage.async_load() == accepted
        assert not events
        return False

    hass.states.async_set("device_tracker.lifecycle", "away", {"latitude": 51.7, "longitude": -0.1})
    await asyncio.wait_for(request_started.wait(), timeout=2)
    platform_unload = AsyncMock(side_effect=refuse_platform_unload)
    with monkeypatch.context() as patch:
        patch.setattr(hass.config_entries, "async_unload_platforms", platform_unload)
        unload = hass.async_create_task(async_unload_entry(hass, entry))
        try:
            await asyncio.wait_for(cancellation_started.wait(), timeout=2)
            platform_unload.assert_not_called()
            assert not unload.done()
        finally:
            release_request_cleanup.set()
        assert not await asyncio.wait_for(unload, timeout=2)

    async_fire_time_changed(hass, datetime.now(UTC) + timedelta(seconds=11))
    await hass.async_block_till_done()
    assert [event.data["to_state"] for event in events] == ["Oxford"]
    assert events[0].data["previous_latitude"] == 51.5
    assert (await storage.async_load())[ATTR_LATITUDE] == 51.7
    assert session.get.call_args_list[0].args[0] == session.get.call_args_list[1].args[0]

    tracker_clock += timedelta(seconds=11)
    hass.states.async_set("device_tracker.lifecycle", "away", {"latitude": 51.9, "longitude": -0.1})
    await hass.async_block_till_done()
    assert [event.data["to_state"] for event in events] == ["Oxford", "Cambridge"]
    assert (await storage.async_load())[ATTR_LATITUDE] == 51.9


@pytest.mark.asyncio
async def test_runtime_data_isolation(
    monkeypatch: pytest.MonkeyPatch,
    mock_hass: MagicMock,
) -> None:
    """Each config entry should receive its own coordinator instance.

    Args:
        monkeypatch (pytest.MonkeyPatch):
            Pytest fixture for replacing dependencies.
        mock_hass (MagicMock):
            Mocked Home Assistant runtime.
    """
    entry1 = MockConfigEntry(domain="places", data={"name": "entry1"})
    entry2 = MockConfigEntry(domain="places", data={"name": "entry2"})
    monkeypatch.setattr("custom_components.places.PlacesStorage", _FakeSetupPlacesStorage)
    monkeypatch.setattr("custom_components.places.PlacesUpdateCoordinator", _FakeCoordinator)

    await async_setup_entry(mock_hass, entry1)
    await async_setup_entry(mock_hass, entry2)

    assert isinstance(entry1.runtime_data, _FakeCoordinator)
    assert isinstance(entry2.runtime_data, _FakeCoordinator)
    assert entry1.runtime_data is not entry2.runtime_data


@pytest.mark.asyncio
async def test_setup_entry_multiple_calls(
    monkeypatch: pytest.MonkeyPatch,
    mock_hass: MagicMock,
    mock_entry: MockConfigEntry,
) -> None:
    """Repeated setup calls should still forward platforms each time.

    Args:
        monkeypatch (pytest.MonkeyPatch):
            Pytest fixture for replacing dependencies.
        mock_hass (MagicMock):
            Mocked Home Assistant runtime.
        mock_entry (MockConfigEntry):
            Places configuration entry used by the test.
    """
    monkeypatch.setattr("custom_components.places.PlacesStorage", _FakeSetupPlacesStorage)
    monkeypatch.setattr("custom_components.places.PlacesUpdateCoordinator", _FakeCoordinator)

    await async_setup_entry(mock_hass, mock_entry)
    await async_setup_entry(mock_hass, mock_entry)

    assert_awaited_count(mock_hass.config_entries.async_forward_entry_setups, 2)


@pytest.mark.asyncio
async def test_async_unload_entry_does_not_remove_store_data(
    monkeypatch: pytest.MonkeyPatch, mock_hass: MagicMock, mock_entry: MockConfigEntry
) -> None:
    """Unloading/reloading an entry should not remove Store state.

    Args:
        monkeypatch (pytest.MonkeyPatch):
            Pytest fixture for replacing dependencies.
        mock_hass (MagicMock):
            Mocked Home Assistant runtime.
        mock_entry (MockConfigEntry):
            Places configuration entry used by the test.
    """
    monkeypatch.setattr("custom_components.places.PlacesStorage", _FakePlacesStorage)
    mock_entry.runtime_data = _FakeCoordinator(mock_hass, mock_entry, {}, MagicMock())

    await async_unload_entry(mock_hass, mock_entry)

    assert _FakePlacesStorage.remove_calls == 0


GPS_REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"


def _register_gps_places(aioclient_mock: AiohttpClientMocker) -> None:
    """Answer reverse lookups for the latitudes used by the GPS accuracy scenarios.

    Args:
        aioclient_mock (AiohttpClientMocker): HTTP boundary for OpenStreetMap lookups.
    """
    for latitude, city in (
        ("51.5", "London"),
        ("51.6", "Swindon"),
        ("51.7", "Oxford"),
        ("51.8", "Bicester"),
        ("51.9", "Reading"),
        ("52.0", "Cambridge"),
        ("52.1", "Ely"),
        ("52.2", "Norwich"),
        ("52.3", "Ipswich"),
        ("52.4", "Colchester"),
        ("52.5", "Chelmsford"),
    ):
        aioclient_mock.get(
            f"{GPS_REVERSE_URL}?lat={latitude}",
            json={
                "osm_id": 1,
                "osm_type": "node",
                "category": "place",
                "type": "city",
                "address": {"city": city},
            },
        )


def _gps_entry(
    hass: HomeAssistant, tracked_entity: str, *, use_gps: bool = True
) -> MockConfigEntry:
    """Create and register a Places entry that follows one tracked entity.

    Args:
        hass (HomeAssistant): Home Assistant runtime that owns the entry.
        tracked_entity (str): Entity ID the Places entry follows.
        use_gps (bool): Value of the Use GPS Accuracy setting.

    Returns:
        MockConfigEntry: Registered Places entry, not yet set up.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Probe",
        data={
            CONF_NAME: "Probe",
            CONF_DEVICETRACKER_ID: tracked_entity,
            CONF_DISPLAY_OPTIONS: "city",
            CONF_EXTENDED_ATTR: False,
            CONF_SHOW_TIME: False,
            CONF_USE_GPS: use_gps,
        },
    )
    entry.add_to_hass(hass)
    hass.states.async_set("zone.home", "0", {"latitude": 51.4, "longitude": -0.1})
    return entry


@pytest.fixture
def gps_clock(monkeypatch: pytest.MonkeyPatch) -> dict[str, datetime]:
    """Fix the Update clock for GPS accuracy scenarios and let the test move it.

    Args:
        monkeypatch (pytest.MonkeyPatch): Replacement for the Update clock.

    Returns:
        dict[str, datetime]: Mutable clock whose ``now`` entry is the Update time.
    """
    clock = {"now": datetime(2026, 11, 24, 12, tzinfo=UTC)}
    monkeypatch.setattr(
        "custom_components.places.update_sensor.PlacesUpdater.get_current_time",
        AsyncMock(side_effect=lambda: clock["now"]),
    )
    monkeypatch.setattr("homeassistant.util.utcnow", lambda: clock["now"])
    monkeypatch.setattr("custom_components.places.osm_client.OSM_THROTTLE_INTERVAL_SECONDS", 0)
    return clock


async def _report_tracker(
    hass: HomeAssistant,
    clock: dict[str, datetime],
    entity_id: str,
    state: str,
    attributes: dict[str, object],
    *,
    force_update: bool = False,
) -> None:
    """Advance the Update clock and publish one tracked-entity reading.

    Args:
        hass (HomeAssistant): Home Assistant runtime with the tracked entity.
        clock (dict[str, datetime]): Mutable Update clock from ``gps_clock``.
        entity_id (str): Tracked entity whose state is replaced.
        state (str): New state of the tracked entity.
        attributes (dict[str, object]): Attributes of the new reading.
        force_update (bool): Publish the reading even when it matches the current
            state, as a periodic re-read of unchanged state does.
    """
    clock["now"] += timedelta(minutes=10)
    hass.states.async_set(entity_id, state, attributes, force_update=force_update)
    await hass.async_block_till_done()


@pytest.mark.usefixtures("enable_custom_integrations")
@pytest.mark.parametrize(
    "accuracy_attributes",
    [{"gps_accuracy": 0}, {}],
    ids=["zero-accuracy", "no-accuracy"],
)
async def test_tracker_without_real_accuracy_updates_on_every_move(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    gps_clock: dict[str, datetime],
    accuracy_attributes: dict[str, object],
) -> None:
    """A tracked entity that reports 0 or no GPS accuracy updates on every move.

    Args:
        hass (HomeAssistant): Home Assistant runtime with real Places entities.
        aioclient_mock (AiohttpClientMocker): Mocked OpenStreetMap reverse lookups.
        gps_clock (dict[str, datetime]): Mutable Update clock.
        accuracy_attributes (dict[str, object]): Accuracy attributes of each reading.
    """
    _register_gps_places(aioclient_mock)
    entry = _gps_entry(hass, "device_tracker.probe")
    hass.states.async_set(
        "device_tracker.probe",
        "not_home",
        {"latitude": 51.5, "longitude": -0.1, **accuracy_attributes},
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert aioclient_mock.call_count == 1
    assert hass.states.get("sensor.probe").state == "London"

    for latitude, city, lookups in ((51.7, "Oxford", 2), (51.9, "Reading", 3)):
        await _report_tracker(
            hass,
            gps_clock,
            "device_tracker.probe",
            "not_home",
            {"latitude": latitude, "longitude": -0.1, **accuracy_attributes},
        )
        assert aioclient_mock.call_count == lookups
        assert hass.states.get("sensor.probe").state == city


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_zero_reading_after_positive_reading_from_same_tracker_is_skipped(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    gps_clock: dict[str, datetime],
) -> None:
    """A 0 reading from a tracker that reported accuracy leaves the Place unchanged.

    Args:
        hass (HomeAssistant): Home Assistant runtime with real Places entities.
        aioclient_mock (AiohttpClientMocker): Mocked OpenStreetMap reverse lookups.
        gps_clock (dict[str, datetime]): Mutable Update clock.
    """
    _register_gps_places(aioclient_mock)
    entry = _gps_entry(hass, "device_tracker.probe")
    hass.states.async_set(
        "device_tracker.probe", "not_home", {"latitude": 51.5, "longitude": -0.1, "gps_accuracy": 5}
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert aioclient_mock.call_count == 1

    await _report_tracker(
        hass,
        gps_clock,
        "device_tracker.probe",
        "not_home",
        {"latitude": 51.7, "longitude": -0.1, "gps_accuracy": 0},
    )

    assert aioclient_mock.call_count == 1
    main = hass.states.get("sensor.probe")
    assert main is not None
    assert main.state == "London"
    assert main.attributes[ATTR_LATITUDE] == 51.5


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_recorded_tracker_still_skips_zero_readings_after_restart(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    gps_clock: dict[str, datetime],
) -> None:
    """The accuracy record saved with the Places entry survives an entry reload.

    Args:
        hass (HomeAssistant): Home Assistant runtime with real Places entities.
        aioclient_mock (AiohttpClientMocker): Mocked OpenStreetMap reverse lookups.
        gps_clock (dict[str, datetime]): Mutable Update clock.
    """
    _register_gps_places(aioclient_mock)
    entry = _gps_entry(hass, "device_tracker.probe")
    hass.states.async_set(
        "device_tracker.probe", "not_home", {"latitude": 51.5, "longitude": -0.1, "gps_accuracy": 5}
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_unload(entry.entry_id)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    lookups_after_restart = aioclient_mock.call_count
    await _report_tracker(
        hass,
        gps_clock,
        "device_tracker.probe",
        "not_home",
        {"latitude": 51.7, "longitude": -0.1, "gps_accuracy": 0},
    )

    assert aioclient_mock.call_count == lookups_after_restart
    assert hass.states.get("sensor.probe").state == "London"


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_reading_without_accuracy_does_not_inherit_earlier_accuracy(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    gps_clock: dict[str, datetime],
) -> None:
    """A reading with no GPS accuracy moves past the base threshold, not an earlier accuracy.

    Args:
        hass (HomeAssistant): Home Assistant runtime with real Places entities.
        aioclient_mock (AiohttpClientMocker): Mocked OpenStreetMap reverse lookups.
        gps_clock (dict[str, datetime]): Mutable Update clock.
    """
    _register_gps_places(aioclient_mock)
    entry = _gps_entry(hass, "device_tracker.probe")
    hass.states.async_set(
        "device_tracker.probe",
        "not_home",
        {"latitude": 51.5, "longitude": -0.1, "gps_accuracy": 80},
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert aioclient_mock.call_count == 1
    assert hass.states.get("sensor.probe").state == "London"

    latitude = round(51.5 + 40 / _METRES_PER_DEGREE_LATITUDE, 7)
    aioclient_mock.get(f"{GPS_REVERSE_URL}?lat={latitude}", json=_OXFORD_RESPONSE)
    await _report_tracker(
        hass,
        gps_clock,
        "device_tracker.probe",
        "not_home",
        {"latitude": latitude, "longitude": -0.1},
    )

    assert aioclient_mock.call_count == 2
    assert hass.states.get("sensor.probe").state == "Oxford"


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_person_zero_readings_are_judged_by_their_source_tracker(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    gps_clock: dict[str, datetime],
) -> None:
    """A router's 0 readings are accepted while the phone's 0 readings are skipped.

    Args:
        hass (HomeAssistant): Home Assistant runtime with real Places entities.
        aioclient_mock (AiohttpClientMocker): Mocked OpenStreetMap reverse lookups.
        gps_clock (dict[str, datetime]): Mutable Update clock.
    """
    _register_gps_places(aioclient_mock)
    entry = _gps_entry(hass, "person.probe")
    hass.states.async_set(
        "person.probe",
        "home",
        {
            "source": "device_tracker.phone",
            "latitude": 51.5,
            "longitude": -0.1,
            "gps_accuracy": 5,
        },
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert aioclient_mock.call_count == 1

    await _report_tracker(
        hass,
        gps_clock,
        "person.probe",
        "not_home",
        {"source": "device_tracker.router", "latitude": 51.7, "longitude": -0.1, "gps_accuracy": 0},
    )
    assert aioclient_mock.call_count == 2
    assert hass.states.get("sensor.probe").state == "Oxford"

    await _report_tracker(
        hass,
        gps_clock,
        "person.probe",
        "not_home",
        {"source": "device_tracker.phone", "latitude": 51.9, "longitude": -0.1, "gps_accuracy": 0},
    )
    assert aioclient_mock.call_count == 2
    assert hass.states.get("sensor.probe").state == "Oxford"


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_source_attribute_of_non_person_tracked_entity_is_ignored(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    gps_clock: dict[str, datetime],
) -> None:
    """A ``source`` attribute on a device tracker does not change which tracker is judged.

    Args:
        hass (HomeAssistant): Home Assistant runtime with real Places entities.
        aioclient_mock (AiohttpClientMocker): Mocked OpenStreetMap reverse lookups.
        gps_clock (dict[str, datetime]): Mutable Update clock.
    """
    _register_gps_places(aioclient_mock)
    entry = _gps_entry(hass, "device_tracker.probe")
    hass.states.async_set(
        "device_tracker.probe",
        "not_home",
        {"source": "device_tracker.other", "latitude": 51.5, "longitude": -0.1, "gps_accuracy": 5},
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert aioclient_mock.call_count == 1

    await _report_tracker(
        hass,
        gps_clock,
        "device_tracker.probe",
        "not_home",
        {"source": "device_tracker.other", "latitude": 51.7, "longitude": -0.1, "gps_accuracy": 0},
    )

    assert aioclient_mock.call_count == 1
    assert hass.states.get("sensor.probe").state == "London"


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_changing_tracked_entity_discards_recorded_accuracy(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    gps_clock: dict[str, datetime],
) -> None:
    """Switching the Places entry away and back starts learning accuracy again.

    Args:
        hass (HomeAssistant): Home Assistant runtime with real Places entities.
        aioclient_mock (AiohttpClientMocker): Mocked OpenStreetMap reverse lookups.
        gps_clock (dict[str, datetime]): Mutable Update clock.
    """
    _register_gps_places(aioclient_mock)
    entry = _gps_entry(hass, "device_tracker.probe")
    hass.states.async_set(
        "device_tracker.probe", "not_home", {"latitude": 51.5, "longitude": -0.1, "gps_accuracy": 5}
    )
    hass.states.async_set(
        "device_tracker.other", "not_home", {"latitude": 51.5, "longitude": -0.1, "gps_accuracy": 5}
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert aioclient_mock.call_count == 1

    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_DEVICETRACKER_ID: "device_tracker.other"}
    )
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    # Re-selecting the first tracker must not re-record it from a positive setup reading.
    hass.states.async_set(
        "device_tracker.probe", "not_home", {"latitude": 51.5, "longitude": -0.1, "gps_accuracy": 0}
    )
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_DEVICETRACKER_ID: "device_tracker.probe"}
    )
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    lookups_before_report = aioclient_mock.call_count

    await _report_tracker(
        hass,
        gps_clock,
        "device_tracker.probe",
        "not_home",
        {"latitude": 51.7, "longitude": -0.1, "gps_accuracy": 0},
    )

    assert aioclient_mock.call_count == lookups_before_report + 1
    assert hass.states.get("sensor.probe").state == "Oxford"


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_turning_gps_accuracy_off_ignores_and_forgets_recorded_accuracy(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    gps_clock: dict[str, datetime],
) -> None:
    """With Use GPS Accuracy off no reading is skipped, and turning it back on forgets the record.

    Args:
        hass (HomeAssistant): Home Assistant runtime with real Places entities.
        aioclient_mock (AiohttpClientMocker): Mocked OpenStreetMap reverse lookups.
        gps_clock (dict[str, datetime]): Mutable Update clock.
    """
    _register_gps_places(aioclient_mock)
    entry = _gps_entry(hass, "device_tracker.probe")
    hass.states.async_set(
        "device_tracker.probe", "not_home", {"latitude": 51.5, "longitude": -0.1, "gps_accuracy": 5}
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert aioclient_mock.call_count == 1

    hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_USE_GPS: False})
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    await _report_tracker(
        hass,
        gps_clock,
        "device_tracker.probe",
        "not_home",
        {"latitude": 51.7, "longitude": -0.1, "gps_accuracy": 0},
    )
    assert aioclient_mock.call_count == 2
    assert hass.states.get("sensor.probe").state == "Oxford"

    hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_USE_GPS: True})
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    await _report_tracker(
        hass,
        gps_clock,
        "device_tracker.probe",
        "not_home",
        {"latitude": 51.9, "longitude": -0.1, "gps_accuracy": 0},
    )
    assert aioclient_mock.call_count == 3
    assert hass.states.get("sensor.probe").state == "Reading"


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_fifth_moving_zero_reading_forgets_source_tracker(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    gps_clock: dict[str, datetime],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Five moving 0 readings in a row stop a tracker being treated as reporting accuracy.

    Args:
        hass (HomeAssistant): Home Assistant runtime with real Places entities.
        aioclient_mock (AiohttpClientMocker): Mocked OpenStreetMap reverse lookups.
        gps_clock (dict[str, datetime]): Mutable Update clock.
        caplog (pytest.LogCaptureFixture): Captured log records.
    """
    _register_gps_places(aioclient_mock)
    entry = _gps_entry(hass, "device_tracker.probe")
    hass.states.async_set(
        "device_tracker.probe", "not_home", {"latitude": 51.5, "longitude": -0.1, "gps_accuracy": 5}
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert aioclient_mock.call_count == 1

    for latitude in (51.6, 51.7, 51.8, 51.9):
        await _report_tracker(
            hass,
            gps_clock,
            "device_tracker.probe",
            "not_home",
            {"latitude": latitude, "longitude": -0.1, "gps_accuracy": 0},
        )
    assert aioclient_mock.call_count == 1
    assert hass.states.get("sensor.probe").state == "London"

    with caplog.at_level(logging.WARNING, logger="custom_components.places"):
        await _report_tracker(
            hass,
            gps_clock,
            "device_tracker.probe",
            "not_home",
            {"latitude": 52.0, "longitude": -0.1, "gps_accuracy": 0},
        )
    assert aioclient_mock.call_count == 2
    assert hass.states.get("sensor.probe").state == "Cambridge"
    assert any(
        record.levelno == logging.WARNING and "device_tracker.probe" in record.getMessage()
        for record in caplog.records
    )
    saved = await PlacesStorage(hass, entry.entry_id, "Probe").async_load()
    assert "device_tracker.probe" not in saved.get(ATTR_GPS_ACCURACY_SOURCES, [])

    await _report_tracker(
        hass,
        gps_clock,
        "device_tracker.probe",
        "not_home",
        {"latitude": 52.1, "longitude": -0.1, "gps_accuracy": 0},
    )
    assert aioclient_mock.call_count == 3
    assert hass.states.get("sensor.probe").state == "Ely"


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_positive_reading_resets_forgetting_count(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    gps_clock: dict[str, datetime],
) -> None:
    """A positive reading restarts the count, so four more moving 0 readings are skipped.

    Args:
        hass (HomeAssistant): Home Assistant runtime with real Places entities.
        aioclient_mock (AiohttpClientMocker): Mocked OpenStreetMap reverse lookups.
        gps_clock (dict[str, datetime]): Mutable Update clock.
    """
    _register_gps_places(aioclient_mock)
    entry = _gps_entry(hass, "device_tracker.probe")
    hass.states.async_set(
        "device_tracker.probe", "not_home", {"latitude": 51.5, "longitude": -0.1, "gps_accuracy": 5}
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    for latitude in (51.6, 51.7, 51.8, 51.9):
        await _report_tracker(
            hass,
            gps_clock,
            "device_tracker.probe",
            "not_home",
            {"latitude": latitude, "longitude": -0.1, "gps_accuracy": 0},
        )
    await _report_tracker(
        hass,
        gps_clock,
        "device_tracker.probe",
        "not_home",
        {"latitude": 52.0, "longitude": -0.1, "gps_accuracy": 5},
    )
    assert aioclient_mock.call_count == 2
    assert hass.states.get("sensor.probe").state == "Cambridge"

    for latitude in (52.1, 52.2, 52.3, 52.4):
        await _report_tracker(
            hass,
            gps_clock,
            "device_tracker.probe",
            "not_home",
            {"latitude": latitude, "longitude": -0.1, "gps_accuracy": 0},
        )
    assert aioclient_mock.call_count == 2
    assert hass.states.get("sensor.probe").state == "Cambridge"

    await _report_tracker(
        hass,
        gps_clock,
        "device_tracker.probe",
        "not_home",
        {"latitude": 52.5, "longitude": -0.1, "gps_accuracy": 0},
    )
    assert aioclient_mock.call_count == 3
    assert hass.states.get("sensor.probe").state == "Chelmsford"


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_zero_reading_that_moved_ten_metres_or_less_resets_count(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    gps_clock: dict[str, datetime],
) -> None:
    """A 0 reading that stays within 10 m restarts the count of moving readings.

    Args:
        hass (HomeAssistant): Home Assistant runtime with real Places entities.
        aioclient_mock (AiohttpClientMocker): Mocked OpenStreetMap reverse lookups.
        gps_clock (dict[str, datetime]): Mutable Update clock.
    """
    _register_gps_places(aioclient_mock)
    entry = _gps_entry(hass, "device_tracker.probe")
    hass.states.async_set(
        "device_tracker.probe", "not_home", {"latitude": 51.5, "longitude": -0.1, "gps_accuracy": 5}
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    small_move_latitude = round(51.9 + 5 / _METRES_PER_DEGREE_LATITUDE, 7)
    for latitude in (51.6, 51.7, 51.8, 51.9, small_move_latitude):
        await _report_tracker(
            hass,
            gps_clock,
            "device_tracker.probe",
            "not_home",
            {"latitude": latitude, "longitude": -0.1, "gps_accuracy": 0},
        )
    assert aioclient_mock.call_count == 1

    for latitude in (52.0, 52.1, 52.2, 52.3):
        await _report_tracker(
            hass,
            gps_clock,
            "device_tracker.probe",
            "not_home",
            {"latitude": latitude, "longitude": -0.1, "gps_accuracy": 0},
        )
    assert aioclient_mock.call_count == 1
    assert hass.states.get("sensor.probe").state == "London"

    await _report_tracker(
        hass,
        gps_clock,
        "device_tracker.probe",
        "not_home",
        {"latitude": 52.4, "longitude": -0.1, "gps_accuracy": 0},
    )
    assert aioclient_mock.call_count == 2
    assert hass.states.get("sensor.probe").state == "Colchester"


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_identical_zero_reading_neither_counts_nor_resets(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    gps_clock: dict[str, datetime],
) -> None:
    """A periodic re-read of the same 0 reading leaves the forgetting count unchanged.

    Args:
        hass (HomeAssistant): Home Assistant runtime with real Places entities.
        aioclient_mock (AiohttpClientMocker): Mocked OpenStreetMap reverse lookups.
        gps_clock (dict[str, datetime]): Mutable Update clock.
    """
    _register_gps_places(aioclient_mock)
    entry = _gps_entry(hass, "device_tracker.probe")
    hass.states.async_set(
        "device_tracker.probe", "not_home", {"latitude": 51.5, "longitude": -0.1, "gps_accuracy": 5}
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    for latitude in (51.6, 51.7, 51.8, 51.9):
        await _report_tracker(
            hass,
            gps_clock,
            "device_tracker.probe",
            "not_home",
            {"latitude": latitude, "longitude": -0.1, "gps_accuracy": 0},
        )
    for _ in range(3):
        await _report_tracker(
            hass,
            gps_clock,
            "device_tracker.probe",
            "not_home",
            {"latitude": 51.9, "longitude": -0.1, "gps_accuracy": 0},
            force_update=True,
        )
    assert aioclient_mock.call_count == 1

    await _report_tracker(
        hass,
        gps_clock,
        "device_tracker.probe",
        "not_home",
        {"latitude": 52.0, "longitude": -0.1, "gps_accuracy": 0},
    )
    assert aioclient_mock.call_count == 2
    assert hass.states.get("sensor.probe").state == "Cambridge"


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_forgetting_count_is_kept_per_source_tracker(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    gps_clock: dict[str, datetime],
) -> None:
    """Router readings do not advance or reset the phone's forgetting count.

    Args:
        hass (HomeAssistant): Home Assistant runtime with real Places entities.
        aioclient_mock (AiohttpClientMocker): Mocked OpenStreetMap reverse lookups.
        gps_clock (dict[str, datetime]): Mutable Update clock.
    """
    _register_gps_places(aioclient_mock)
    entry = _gps_entry(hass, "person.probe")
    hass.states.async_set(
        "person.probe",
        "home",
        {
            "source": "device_tracker.phone",
            "latitude": 51.5,
            "longitude": -0.1,
            "gps_accuracy": 5,
        },
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    for latitude in (51.6, 51.7, 51.8, 51.9):
        await _report_tracker(
            hass,
            gps_clock,
            "person.probe",
            "not_home",
            {
                "source": "device_tracker.phone",
                "latitude": latitude,
                "longitude": -0.1,
                "gps_accuracy": 0,
            },
        )
    assert aioclient_mock.call_count == 1

    await _report_tracker(
        hass,
        gps_clock,
        "person.probe",
        "not_home",
        {"source": "device_tracker.router", "latitude": 52.0, "longitude": -0.1, "gps_accuracy": 0},
    )
    assert aioclient_mock.call_count == 2
    assert hass.states.get("sensor.probe").state == "Cambridge"

    await _report_tracker(
        hass,
        gps_clock,
        "person.probe",
        "not_home",
        {"source": "device_tracker.phone", "latitude": 52.1, "longitude": -0.1, "gps_accuracy": 0},
    )
    assert aioclient_mock.call_count == 3
    assert hass.states.get("sensor.probe").state == "Ely"


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_forgetting_count_starts_again_after_restart(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    gps_clock: dict[str, datetime],
) -> None:
    """Moving 0 readings counted before a restart do not count toward forgetting after it.

    Args:
        hass (HomeAssistant): Home Assistant runtime with real Places entities.
        aioclient_mock (AiohttpClientMocker): Mocked OpenStreetMap reverse lookups.
        gps_clock (dict[str, datetime]): Mutable Update clock.
    """
    _register_gps_places(aioclient_mock)
    entry = _gps_entry(hass, "device_tracker.probe")
    hass.states.async_set(
        "device_tracker.probe", "not_home", {"latitude": 51.5, "longitude": -0.1, "gps_accuracy": 5}
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    for latitude in (51.6, 51.7, 51.8, 51.9):
        await _report_tracker(
            hass,
            gps_clock,
            "device_tracker.probe",
            "not_home",
            {"latitude": latitude, "longitude": -0.1, "gps_accuracy": 0},
        )
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    lookups_after_restart = aioclient_mock.call_count

    for latitude in (52.0, 52.1, 52.2, 52.3):
        await _report_tracker(
            hass,
            gps_clock,
            "device_tracker.probe",
            "not_home",
            {"latitude": latitude, "longitude": -0.1, "gps_accuracy": 0},
        )
    assert aioclient_mock.call_count == lookups_after_restart
    assert hass.states.get("sensor.probe").state == "London"

    await _report_tracker(
        hass,
        gps_clock,
        "device_tracker.probe",
        "not_home",
        {"latitude": 52.4, "longitude": -0.1, "gps_accuracy": 0},
    )
    assert aioclient_mock.call_count == lookups_after_restart + 1
    assert hass.states.get("sensor.probe").state == "Colchester"

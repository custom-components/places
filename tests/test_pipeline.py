"""Tests for Places update pipeline phase orchestration."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.places.const import ATTR_LAST_PLACE_NAME, UpdateStatus
from custom_components.places.pipeline import PlacesUpdatePipeline
from custom_components.places.update_sensor import PlacesUpdater
from tests.conftest import MockSensor, StubMapping


@pytest.mark.asyncio
async def test_update_pipeline_runs_phases_in_expected_order(
    mock_hass: MagicMock,
    mock_config_entry: MockConfigEntry,
    sensor: MockSensor,
    stubbed_updater: Callable[
        [PlacesUpdater, list[tuple[str, dict[str, object]]]],
        AbstractContextManager[StubMapping],
    ],
) -> None:
    """Assert all major phases execute in the legacy ordered sequence."""
    updater = PlacesUpdater(mock_hass, mock_config_entry, sensor)
    call_order: list[str] = []

    updater.sensor.set_attr(ATTR_LAST_PLACE_NAME, "Last Place")

    now = datetime(2024, 1, 1, 12, 0, tzinfo=UTC)

    def record_prev_last_place_name(key: str, _default: object = None) -> str:
        if key == ATTR_LAST_PLACE_NAME:
            call_order.append("capture_prev_last_place_name")
        return "Last Place"

    sensor.get_attr_safe_str = MagicMock(side_effect=record_prev_last_place_name)

    async def log_update_start(_: str) -> None:
        call_order.append("log_update_start")

    async def get_current_time() -> datetime:
        call_order.append("get_current_time")
        return now

    async def check_device_tracker() -> UpdateStatus:
        call_order.append("check_device_tracker_and_update_coords")
        return UpdateStatus.PROCEED

    async def determine_update_criteria() -> UpdateStatus:
        call_order.append("determine_update_criteria")
        return UpdateStatus.PROCEED

    async def should_update_state(*_args: object, **_kwargs: object) -> bool:
        call_order.append("should_update_state")
        return True

    async def finish_update(*_args: object, **_kwargs: object) -> None:
        call_order.append("finish_update")

    async def update_entity_name_and_cleanup() -> None:
        call_order.append("update_entity_name_and_cleanup")

    async def update_previous_state() -> None:
        call_order.append("update_previous_state")

    async def update_old_coordinates() -> None:
        call_order.append("update_old_coordinates")

    async def process_osm_update(*_args: object, **_kwargs: object) -> None:
        call_order.append("process_osm_update")

    async def handle_state_update(*_args: object, **_kwargs: object) -> None:
        call_order.append("handle_state_update")

    with stubbed_updater(
        updater,
        [
            ("log_update_start", {"side_effect": log_update_start}),
            ("get_current_time", {"side_effect": get_current_time}),
            ("update_entity_name_and_cleanup", {"side_effect": update_entity_name_and_cleanup}),
            ("update_previous_state", {"side_effect": update_previous_state}),
            ("update_old_coordinates", {"side_effect": update_old_coordinates}),
            (
                "check_device_tracker_and_update_coords",
                {"side_effect": check_device_tracker},
            ),
            (
                "determine_update_criteria",
                {"side_effect": determine_update_criteria},
            ),
            (
                "process_osm_update",
                {"side_effect": process_osm_update},
            ),
            (
                "should_update_state",
                {"side_effect": should_update_state},
            ),
            (
                "handle_state_update",
                {"side_effect": handle_state_update},
            ),
            ("rollback_update", {}),
            ("finish_update", {"side_effect": finish_update}),
        ],
    ) as mocks:
        updater._osm_client.update_sensor_name = MagicMock(
            side_effect=lambda _sensor_name: call_order.append("update_sensor_name")
        )

        await PlacesUpdatePipeline(updater).run("manual", {"snapshot": "value"})

        assert mocks["log_update_start"].await_count == 1

    expected_order = [
        "log_update_start",
        "get_current_time",
        "update_entity_name_and_cleanup",
        "update_sensor_name",
        "update_previous_state",
        "update_old_coordinates",
        "capture_prev_last_place_name",
        "check_device_tracker_and_update_coords",
        "determine_update_criteria",
        "process_osm_update",
        "should_update_state",
        "handle_state_update",
        "finish_update",
    ]
    assert call_order == expected_order

"""Integration tests for the custom_components.places module."""

import logging
from typing import ClassVar
from unittest.mock import MagicMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.places import async_remove_entry, async_setup_entry, async_unload_entry
from custom_components.places.const import CONF_API_KEY, CONF_NAME, PLATFORMS
from tests.conftest import assert_awaited_count


@pytest.fixture
def mock_entry() -> MockConfigEntry:
    """Return a MockConfigEntry pre-populated with sample data for tests."""
    return MockConfigEntry(domain="places", data={"name": "test", "other": "value"})


@pytest.fixture
def sensitive_entry() -> MockConfigEntry:
    """Return a config entry containing data that must not be logged."""
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
        """Record constructor arguments for assertions."""
        self.hass = hass
        self.entry_id = entry_id
        self.name = name

    async def async_remove(self) -> None:
        """Record a removal request from async_remove_entry."""
        remove_error = type(self).remove_error
        if remove_error is not None:
            raise remove_error
        type(self).remove_calls += 1
        type(self).remove_calls_args.append((self.entry_id, self.name))


@pytest.fixture(autouse=True)
def reset_fake_storage() -> None:
    """Reset fake storage accounting for each integration test."""
    _FakePlacesStorage.remove_calls = 0
    _FakePlacesStorage.remove_calls_args = []
    _FakePlacesStorage.remove_error = None


@pytest.mark.asyncio
async def test_async_remove_entry_removes_store_data(
    monkeypatch: pytest.MonkeyPatch, mock_hass: MagicMock, mock_entry: MockConfigEntry
) -> None:
    """Config-entry deletion should remove the per-entry Store snapshot."""
    monkeypatch.setattr("custom_components.places.PlacesStorage", _FakePlacesStorage)

    result = await async_remove_entry(mock_hass, mock_entry)

    assert result is True
    assert _FakePlacesStorage.remove_calls == 1
    assert _FakePlacesStorage.remove_calls_args == [
        (mock_entry.entry_id, mock_entry.data[CONF_NAME])
    ]


@pytest.mark.asyncio
async def test_async_remove_entry_uses_entry_id_if_name_missing(
    monkeypatch: pytest.MonkeyPatch, mock_hass: MagicMock
) -> None:
    """async_remove_entry should use entry_id when no config entry name exists."""
    entry = MockConfigEntry(domain="places", data={})
    monkeypatch.setattr("custom_components.places.PlacesStorage", _FakePlacesStorage)

    await async_remove_entry(mock_hass, entry)

    assert _FakePlacesStorage.remove_calls == 1
    assert _FakePlacesStorage.remove_calls_args == [(entry.entry_id, entry.entry_id)]


@pytest.mark.asyncio
async def test_async_remove_entry_logs_storage_errors_without_blocking(
    monkeypatch: pytest.MonkeyPatch,
    mock_hass: MagicMock,
    sensitive_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Config-entry deletion should not be blocked by storage cleanup errors."""
    monkeypatch.setattr("custom_components.places.PlacesStorage", _FakePlacesStorage)
    _FakePlacesStorage.remove_error = OSError("storage unavailable")

    with caplog.at_level(logging.WARNING, logger="custom_components.places"):
        result = await async_remove_entry(mock_hass, sensitive_entry)

    assert result is True
    assert sensitive_entry.entry_id in caplog.text
    assert "storage unavailable" in caplog.text
    assert "secret@example.com" not in caplog.text


@pytest.mark.asyncio
async def test_async_unload_entry_logs_safe_identifier(
    mock_hass: MagicMock,
    sensitive_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Config-entry unload should not log the full entry data mapping."""
    with caplog.at_level(logging.INFO, logger="custom_components.places"):
        await async_unload_entry(mock_hass, sensitive_entry)

    assert sensitive_entry.entry_id in caplog.text
    assert "secret@example.com" not in caplog.text


@pytest.mark.asyncio
async def test_runtime_data_set_on_entry(mock_hass: MagicMock, mock_entry: MockConfigEntry) -> None:
    """async_setup_entry should set entry.runtime_data and forward entry setups once."""
    result = await async_setup_entry(mock_hass, mock_entry)
    assert result is True
    assert mock_entry.runtime_data == mock_entry.data
    # Ensure the coroutine was actually awaited once
    mock_hass.config_entries.async_forward_entry_setups.assert_awaited_once()


@pytest.mark.asyncio
async def test_async_setup_entry_calls_forward_setups(
    mock_hass: MagicMock, mock_entry: MockConfigEntry
) -> None:
    """Ensure async_setup_entry forwards platform setups to Home Assistant for the given entry."""
    result = await async_setup_entry(mock_hass, mock_entry)
    assert result is True
    # Verify the async_forward_entry_setups coroutine was awaited with the expected args
    mock_hass.config_entries.async_forward_entry_setups.assert_awaited_once_with(
        mock_entry, PLATFORMS
    )


@pytest.mark.asyncio
async def test_async_setup_entry_forward_setups_returns_false(
    mock_hass: MagicMock, mock_entry: MockConfigEntry
) -> None:
    """When the forwarded platform setups returns False, current implementation still returns True but should still await forwarding once.

    Note: the integration does not propagate the return value from
    `async_forward_entry_setups`, so we assert that `async_setup_entry` still
    returns True while ensuring the forward call was awaited with expected args.
    """
    # Make the forwarded setup coroutine return False when awaited
    mock_hass.config_entries.async_forward_entry_setups.return_value = False
    result = await async_setup_entry(mock_hass, mock_entry)
    # Integration does not propagate the forwarded setup result, so it returns True
    assert result is True
    # Ensure the coroutine was awaited with the expected args
    mock_hass.config_entries.async_forward_entry_setups.assert_awaited_once_with(
        mock_entry, PLATFORMS
    )


@pytest.mark.asyncio
async def test_async_setup_entry_with_empty_data(mock_hass: MagicMock) -> None:
    """When config entry data is empty, async_setup_entry should still return True and set runtime_data to {}."""
    entry = MockConfigEntry(domain="places", data={})
    result = await async_setup_entry(mock_hass, entry)
    assert result is True
    assert entry.runtime_data == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(("unload_return", "expected"), [(True, True), (False, False)])
async def test_async_unload_entry_result(
    mock_hass: MagicMock, mock_entry: MockConfigEntry, unload_return: bool, expected: bool
) -> None:
    """async_unload_entry should return the result of async_unload_platforms for the provided entry."""
    mock_hass.config_entries.async_unload_platforms.return_value = unload_return
    result = await async_unload_entry(mock_hass, mock_entry)
    assert result is expected
    # Ensure async_unload_platforms coroutine was awaited with the expected args
    mock_hass.config_entries.async_unload_platforms.assert_awaited_once_with(mock_entry, PLATFORMS)


@pytest.mark.asyncio
async def test_runtime_data_isolation(mock_hass: MagicMock) -> None:
    """Test that each config entry maintains isolated runtime data after setup.

    Ensures that calling `async_setup_entry` on multiple entries results in distinct `runtime_data` attributes, confirming no data leakage or sharing between entries.
    """
    entry1 = MockConfigEntry(domain="places", data={"name": "entry1"})
    entry2 = MockConfigEntry(domain="places", data={"name": "entry2"})
    await async_setup_entry(mock_hass, entry1)
    await async_setup_entry(mock_hass, entry2)
    assert entry1.runtime_data != entry2.runtime_data


@pytest.mark.asyncio
async def test_setup_entry_multiple_calls(
    mock_hass: MagicMock, mock_entry: MockConfigEntry
) -> None:
    """Test that calling async_setup_entry multiple times results in multiple calls to async_forward_entry_setups."""
    await async_setup_entry(mock_hass, mock_entry)
    await async_setup_entry(mock_hass, mock_entry)
    # Check the coroutine was awaited twice
    assert_awaited_count(mock_hass.config_entries.async_forward_entry_setups, 2)


@pytest.mark.asyncio
async def test_async_unload_entry_does_not_remove_store_data(
    monkeypatch: pytest.MonkeyPatch, mock_hass: MagicMock, mock_entry: MockConfigEntry
) -> None:
    """Unloading/reloading an entry should not remove Store state."""
    monkeypatch.setattr("custom_components.places.PlacesStorage", _FakePlacesStorage)

    await async_unload_entry(mock_hass, mock_entry)

    assert _FakePlacesStorage.remove_calls == 0

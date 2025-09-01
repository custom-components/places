"""Integration tests for the custom_components.places module."""

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.places import async_setup_entry, async_unload_entry
from custom_components.places.const import PLATFORMS
from tests.conftest import assert_awaited_count


@pytest.fixture
def mock_entry():
    """Return a MockConfigEntry pre-populated with sample data for tests."""
    return MockConfigEntry(domain="places", data={"name": "test", "other": "value"})


@pytest.mark.asyncio
async def test_runtime_data_set_on_entry(mock_hass, mock_entry):
    """async_setup_entry should set entry.runtime_data and forward entry setups once."""
    result = await async_setup_entry(mock_hass, mock_entry)
    assert result is True
    assert mock_entry.runtime_data == mock_entry.data
    # Ensure the coroutine was actually awaited once
    mock_hass.config_entries.async_forward_entry_setups.assert_awaited_once()


@pytest.mark.asyncio
async def test_async_setup_entry_calls_forward_setups(mock_hass, mock_entry):
    """Ensure async_setup_entry forwards platform setups to Home Assistant for the given entry."""
    result = await async_setup_entry(mock_hass, mock_entry)
    assert result is True
    # Verify the async_forward_entry_setups coroutine was awaited with the expected args
    mock_hass.config_entries.async_forward_entry_setups.assert_awaited_once_with(
        mock_entry, PLATFORMS
    )


@pytest.mark.asyncio
async def test_async_setup_entry_forward_setups_returns_false(mock_hass, mock_entry):
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
async def test_async_setup_entry_with_empty_data(mock_hass):
    """When config entry data is empty, async_setup_entry should still return True and set runtime_data to {}."""
    entry = MockConfigEntry(domain="places", data={})
    result = await async_setup_entry(mock_hass, entry)
    assert result is True
    assert entry.runtime_data == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("unload_return,expected", [(True, True), (False, False)])
async def test_async_unload_entry_result(mock_hass, mock_entry, unload_return, expected):
    """async_unload_entry should return the result of async_unload_platforms for the provided entry."""
    mock_hass.config_entries.async_unload_platforms.return_value = unload_return
    result = await async_unload_entry(mock_hass, mock_entry)
    assert result is expected
    # Ensure async_unload_platforms coroutine was awaited with the expected args
    mock_hass.config_entries.async_unload_platforms.assert_awaited_once_with(mock_entry, PLATFORMS)


@pytest.mark.asyncio
async def test_runtime_data_isolation(mock_hass):
    """Test that each config entry maintains isolated runtime data after setup.

    Ensures that calling `async_setup_entry` on multiple entries results in distinct `runtime_data` attributes, confirming no data leakage or sharing between entries.
    """
    entry1 = MockConfigEntry(domain="places", data={"name": "entry1"})
    entry2 = MockConfigEntry(domain="places", data={"name": "entry2"})
    await async_setup_entry(mock_hass, entry1)
    await async_setup_entry(mock_hass, entry2)
    assert entry1.runtime_data != entry2.runtime_data


@pytest.mark.asyncio
async def test_setup_entry_multiple_calls(mock_hass, mock_entry):
    """Test that calling async_setup_entry multiple times results in multiple calls to async_forward_entry_setups."""
    await async_setup_entry(mock_hass, mock_entry)
    await async_setup_entry(mock_hass, mock_entry)
    # Check the coroutine was awaited twice
    assert_awaited_count(mock_hass.config_entries.async_forward_entry_setups, 2)

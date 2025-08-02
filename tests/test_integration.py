from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.places import async_setup_entry, async_unload_entry
from custom_components.places.const import PLATFORMS  # <-- Add this import


@pytest.fixture
def mock_hass():
    hass = MagicMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock(return_value=None)
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    return hass


@pytest.fixture
def mock_entry():
    entry = MagicMock()
    entry.data = {"name": "test", "other": "value"}
    return entry


@pytest.mark.asyncio
async def test_runtime_data_set_on_entry(mock_hass, mock_entry):
    result = await async_setup_entry(mock_hass, mock_entry)
    assert result is True
    assert mock_entry.runtime_data == mock_entry.data
    mock_hass.config_entries.async_forward_entry_setups.assert_called_once()


@pytest.mark.asyncio
async def test_async_setup_entry_calls_forward_setups(mock_hass, mock_entry):
    result = await async_setup_entry(mock_hass, mock_entry)
    assert result is True
    mock_hass.config_entries.async_forward_entry_setups.assert_called_once_with(
        mock_entry, PLATFORMS
    )


@pytest.mark.asyncio
async def test_async_setup_entry_with_empty_data(mock_hass):
    entry = MagicMock()
    entry.data = {}
    result = await async_setup_entry(mock_hass, entry)
    assert result is True
    assert entry.runtime_data == {}


@pytest.mark.asyncio
async def test_async_unload_entry_success(mock_hass, mock_entry):
    mock_hass.config_entries.async_unload_platforms.return_value = True
    result = await async_unload_entry(mock_hass, mock_entry)
    assert result is True
    mock_hass.config_entries.async_unload_platforms.assert_called_once_with(mock_entry, PLATFORMS)


@pytest.mark.asyncio
async def test_async_unload_entry_failure(mock_hass, mock_entry):
    mock_hass.config_entries.async_unload_platforms.return_value = False
    result = await async_unload_entry(mock_hass, mock_entry)
    assert result is False


@pytest.mark.asyncio
async def test_runtime_data_isolation(mock_hass):
    entry1 = MagicMock()
    entry1.data = {"name": "entry1"}
    entry2 = MagicMock()
    entry2.data = {"name": "entry2"}
    await async_setup_entry(mock_hass, entry1)
    await async_setup_entry(mock_hass, entry2)
    assert entry1.runtime_data != entry2.runtime_data


@pytest.mark.asyncio
async def test_setup_entry_multiple_calls(mock_hass, mock_entry):
    await async_setup_entry(mock_hass, mock_entry)
    await async_setup_entry(mock_hass, mock_entry)
    assert mock_hass.config_entries.async_forward_entry_setups.call_count == 2

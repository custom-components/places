from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.places import async_setup_entry, async_unload_entry
from custom_components.places.const import PLATFORMS  # <-- Add this import


@pytest.fixture
def mock_hass():
    """Fixture that returns a MagicMock simulating the Home Assistant core object with mocked async methods for forwarding entry setups and unloading platforms."""
    hass = MagicMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock(return_value=None)
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    return hass


@pytest.fixture
def mock_entry():
    """Create a MagicMock config entry with preset data for testing purposes.

    Returns:
        entry (MagicMock): A mock configuration entry with a predefined 'data' dictionary.

    """
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
    """Test that async_setup_entry calls async_forward_entry_setups with the correct entry and platforms.

    Verifies that the setup function returns True and that the Home Assistant mock's async_forward_entry_setups method is called once with the expected arguments.
    """
    result = await async_setup_entry(mock_hass, mock_entry)
    assert result is True
    mock_hass.config_entries.async_forward_entry_setups.assert_called_once_with(
        mock_entry, PLATFORMS
    )


@pytest.mark.asyncio
async def test_async_setup_entry_with_empty_data(mock_hass):
    """Test that async_setup_entry correctly handles a config entry with empty data.

    Verifies that the function returns True and sets the entry's runtime_data attribute to an empty dictionary when the entry's data is empty.
    """
    entry = MagicMock()
    entry.data = {}
    result = await async_setup_entry(mock_hass, entry)
    assert result is True
    assert entry.runtime_data == {}


@pytest.mark.asyncio
async def test_async_unload_entry_success(mock_hass, mock_entry):
    """Test that async_unload_entry returns True when platforms are successfully unloaded.

    Verifies that async_unload_entry calls async_unload_platforms with the correct arguments and returns True on success.
    """
    mock_hass.config_entries.async_unload_platforms.return_value = True
    result = await async_unload_entry(mock_hass, mock_entry)
    assert result is True
    mock_hass.config_entries.async_unload_platforms.assert_called_once_with(mock_entry, PLATFORMS)


@pytest.mark.asyncio
async def test_async_unload_entry_failure(mock_hass, mock_entry):
    """Test that `async_unload_entry` returns False when platform unloading fails."""
    mock_hass.config_entries.async_unload_platforms.return_value = False
    result = await async_unload_entry(mock_hass, mock_entry)
    assert result is False


@pytest.mark.asyncio
async def test_runtime_data_isolation(mock_hass):
    """Test that each config entry maintains isolated runtime data after setup.

    Ensures that calling `async_setup_entry` on multiple entries results in distinct `runtime_data` attributes, confirming no data leakage or sharing between entries.
    """
    entry1 = MagicMock()
    entry1.data = {"name": "entry1"}
    entry2 = MagicMock()
    entry2.data = {"name": "entry2"}
    await async_setup_entry(mock_hass, entry1)
    await async_setup_entry(mock_hass, entry2)
    assert entry1.runtime_data != entry2.runtime_data


@pytest.mark.asyncio
async def test_setup_entry_multiple_calls(mock_hass, mock_entry):
    """Test that calling async_setup_entry multiple times results in multiple calls to async_forward_entry_setups."""
    await async_setup_entry(mock_hass, mock_entry)
    await async_setup_entry(mock_hass, mock_entry)
    assert mock_hass.config_entries.async_forward_entry_setups.call_count == 2

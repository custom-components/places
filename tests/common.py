"""Home Assistant test plugin helpers shared across the test suite.

``pytest-homeassistant`` covers Home Assistant 2026.11 and later. Older supported
versions are only covered by its predecessor,
``pytest-homeassistant-custom-component``. Import plugin helpers from here so the
same tests run against either package.
"""

try:
    from pytest_homeassistant.common import (
        MockConfigEntry,
        MockEntityPlatform,
        async_capture_events,
        async_fire_time_changed,
    )
    from pytest_homeassistant.test_util.aiohttp import (
        AiohttpClientMocker,
        AiohttpClientMockResponse,
    )
except ModuleNotFoundError:
    from pytest_homeassistant_custom_component.common import (
        MockConfigEntry,
        MockEntityPlatform,
        async_capture_events,
        async_fire_time_changed,
    )
    from pytest_homeassistant_custom_component.test_util.aiohttp import (
        AiohttpClientMocker,
        AiohttpClientMockResponse,
    )

__all__ = [
    "AiohttpClientMockResponse",
    "AiohttpClientMocker",
    "MockConfigEntry",
    "MockEntityPlatform",
    "async_capture_events",
    "async_fire_time_changed",
]

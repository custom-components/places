"""Schema helpers used by the Places config flow."""

from __future__ import annotations

from homeassistant.helpers import selector
import voluptuous as vol

from .const import (
    CONF_API_KEY,
    CONF_DATE_FORMAT,
    CONF_DEVICETRACKER_ID,
    CONF_DISPLAY_OPTIONS,
    CONF_EXTENDED_ATTR,
    CONF_HOME_ZONE,
    CONF_LANGUAGE,
    CONF_MAP_PROVIDER,
    CONF_MAP_ZOOM,
    CONF_NAME,
    CONF_SHOW_TIME,
    CONF_USE_GPS,
    DEFAULT_DATE_FORMAT,
    DEFAULT_DISPLAY_OPTIONS,
    DEFAULT_EXTENDED_ATTR,
    DEFAULT_HOME_ZONE,
    DEFAULT_MAP_PROVIDER,
    DEFAULT_MAP_ZOOM,
    DEFAULT_SHOW_TIME,
    DEFAULT_USE_GPS,
)

MAP_PROVIDER_OPTIONS: list[str] = ["apple", "google", "osm"]
"""Available map provider values for the config flow selector."""

STATE_OPTIONS: list[str] = ["zone, place", "formatted_place", "zone_name, place"]
"""Display options supported by the Places integration."""

DATE_FORMAT_OPTIONS: list[str] = ["mm/dd", "dd/mm"]
"""Date-format dropdown values for the config flow selector."""

MAP_ZOOM_MIN: int = 1
"""Minimum map zoom level allowed by the number selector."""

MAP_ZOOM_MAX: int = 20
"""Maximum map zoom level allowed by the number selector."""


def select_schema(
    options: list[str] | list[selector.SelectOptionDict], *, custom_value: bool
) -> selector.SelectSelector:
    """Create a dropdown select selector for Places config flows.

    Args:
        options: Selector option values or option dictionaries.
        custom_value: Whether users can enter values not listed in ``options``.

    Returns:
        A dropdown-style select selector configured for single selection.
    """
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=options,
            multiple=False,
            custom_value=custom_value,
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def user_schema(
    devicetracker_options: list[selector.SelectOptionDict],
    zone_options: list[selector.SelectOptionDict],
) -> vol.Schema:
    """Build the schema used by ``PlacesConfigFlow.async_step_user``.

    Args:
        devicetracker_options: Selectable devicetracker entities.
        zone_options: Selectable zone entities.

    Returns:
        The user config flow schema with matching defaults and selectors.
    """
    return vol.Schema(
        {
            vol.Required(CONF_NAME): str,
            vol.Required(CONF_DEVICETRACKER_ID): select_schema(
                devicetracker_options, custom_value=False
            ),
            vol.Optional(CONF_API_KEY): str,
            vol.Optional(CONF_DISPLAY_OPTIONS, default=DEFAULT_DISPLAY_OPTIONS): select_schema(
                STATE_OPTIONS, custom_value=True
            ),
            vol.Optional(CONF_HOME_ZONE, default=DEFAULT_HOME_ZONE): select_schema(
                zone_options, custom_value=False
            ),
            vol.Optional(CONF_MAP_PROVIDER, default=DEFAULT_MAP_PROVIDER): select_schema(
                MAP_PROVIDER_OPTIONS, custom_value=False
            ),
            vol.Optional(CONF_MAP_ZOOM, default=int(DEFAULT_MAP_ZOOM)): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=MAP_ZOOM_MIN,
                    max=MAP_ZOOM_MAX,
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(CONF_LANGUAGE): str,
            vol.Optional(CONF_USE_GPS, default=DEFAULT_USE_GPS): selector.BooleanSelector(
                selector.BooleanSelectorConfig()
            ),
            vol.Optional(
                CONF_EXTENDED_ATTR, default=DEFAULT_EXTENDED_ATTR
            ): selector.BooleanSelector(selector.BooleanSelectorConfig()),
            vol.Optional(CONF_SHOW_TIME, default=DEFAULT_SHOW_TIME): selector.BooleanSelector(
                selector.BooleanSelectorConfig()
            ),
            vol.Optional(CONF_DATE_FORMAT, default=DEFAULT_DATE_FORMAT): select_schema(
                DATE_FORMAT_OPTIONS, custom_value=False
            ),
        }
    )

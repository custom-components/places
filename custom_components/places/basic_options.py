"""Parser for basic options in a sensor configuration."""

from __future__ import annotations

from collections.abc import MutableMapping
import logging
from typing import Any

from .const import PLACE_NAME_DUPLICATE_LIST
from .sensor import Places

_LOGGER = logging.getLogger(__name__)


async def build_basic_display(
    internal_attr: MutableMapping[str, Any],
    display_options: list[str],
    sensor: Places,
) -> str:
    """Generate the display string for basic options."""
    user_display: list[str] = []

    def add_to_display(
        attr_key: str,
        option_key: str | None = None,
        condition: bool = True,
        require_in_display_options: bool = True,
    ) -> None:
        if (
            (not require_in_display_options or option_key in display_options)
            and not sensor.is_attr_blank(attr_key)
            and condition
        ):
            user_display.append(sensor.get_attr_safe_str(attr_key))

    # Add basic options
    add_to_display(option_key="driving", attr_key="driving")
    add_to_display(
        option_key="zone_name",
        attr_key="devicetracker_zone_name",
        condition=await sensor.in_zone() or "do_not_show_not_home" not in display_options,
    )
    add_to_display(
        option_key="zone",
        attr_key="devicetracker_zone",
        condition=await sensor.in_zone() or "do_not_show_not_home" not in display_options,
    )
    add_to_display("place_name", "place_name")

    # Handle "place" and its sub-options
    if "place" in display_options:
        add_to_display(
            attr_key="place_name",
            condition=internal_attr.get("place_name") != internal_attr.get("street"),
            require_in_display_options=False,
        )
        add_to_display(
            attr_key="place_category",
            condition=sensor.get_attr_safe_str("place_category").lower() != "place",
            require_in_display_options=False,
        )
        add_to_display(
            attr_key="place_type",
            condition=sensor.get_attr_safe_str("place_type").lower() != "yes",
            require_in_display_options=False,
        )
        add_to_display(
            attr_key="place_neighbourhood",
            require_in_display_options=False,
        )
        add_to_display(
            attr_key="street_number",
            require_in_display_options=False,
        )
        add_to_display(
            attr_key="street",
            require_in_display_options=False,
        )
    else:
        add_to_display(option_key="street_number", attr_key="street_number")
        add_to_display(option_key="street", attr_key="street")

    # Add remaining location details
    for option_key, attr_key in {
        "city": "city",
        "county": "county",
        "state": "region",
        "region": "region",
        "postal_code": "postal_code",
        "country": "country",
        "formatted_address": "formatted_address",
    }.items():
        add_to_display(option_key=option_key, attr_key=attr_key)

    # Handle "do_not_reorder" option
    if "do_not_reorder" in display_options:
        user_display = []
        display_options.remove("do_not_reorder")
        for option in display_options:
            attr_key = (
                "region"
                if option == "state"
                else "place_neighbourhood"
                if option == "place_neighborhood"
                else option
            )
            if not sensor.is_attr_blank(attr_key):
                user_display.append(sensor.get_attr_safe_str(attr_key))

    return ", ".join(user_display)


async def build_formatted_place(
    internal_attr: MutableMapping[str, Any],
    display_options: list[str],
    sensor: Places,
) -> str:
    """Build the formatted place string for display."""
    formatted_place_array: list[str] = []
    if not await sensor.in_zone():
        if not sensor.is_attr_blank("driving") and "driving" in sensor.get_attr_safe_list(
            "display_options_list"
        ):
            formatted_place_array.append(sensor.get_attr_safe_str("driving"))
        use_place_name = should_use_place_name(internal_attr, sensor)
        if not use_place_name:
            add_type_or_category(formatted_place_array, internal_attr, sensor)
            add_street_info(formatted_place_array, internal_attr, sensor)
            add_neighbourhood_if_house(formatted_place_array, internal_attr, sensor)
        else:
            formatted_place_array.append(sensor.get_attr_safe_str("place_name").strip())
        add_city_county_state(formatted_place_array, internal_attr, sensor)
    else:
        formatted_place_array.append(sensor.get_attr_safe_str("devicetracker_zone_name").strip())
    formatted_place = ", ".join(item for item in formatted_place_array)
    return formatted_place.replace("\n", " ").replace("  ", " ").strip()


def should_use_place_name(internal_attr: MutableMapping[str, Any], sensor: Places) -> bool:
    """Determine if the place name should be used based on attributes."""
    use_place_name = True
    sensor_attributes_values = [
        sensor.get_attr_safe_str(attr)
        for attr in PLACE_NAME_DUPLICATE_LIST
        if not sensor.is_attr_blank(attr)
    ]
    if (
        sensor.is_attr_blank("place_name")
        or internal_attr.get("place_name") in sensor_attributes_values
    ):
        use_place_name = False
    _LOGGER.debug("use_place_name: %s", use_place_name)
    return use_place_name


def add_type_or_category(
    formatted_place_array: list[str],
    internal_attr: MutableMapping[str, Any],
    sensor: Places,
) -> None:
    """Add place type or category to the formatted place array."""
    if (
        not sensor.is_attr_blank("place_type")
        and sensor.get_attr_safe_str("place_type").lower() != "unclassified"
        and sensor.get_attr_safe_str("place_category").lower() != "highway"
    ):
        formatted_place_array.append(
            sensor.get_attr_safe_str("place_type")
            .title()
            .replace("Proposed", "")
            .replace("Construction", "")
            .strip()
        )
    elif (
        not sensor.is_attr_blank("place_category")
        and sensor.get_attr_safe_str("place_category").lower() != "highway"
    ):
        formatted_place_array.append(sensor.get_attr_safe_str("place_category").title().strip())


def add_street_info(
    formatted_place_array: list[str],
    internal_attr: MutableMapping[str, Any],
    sensor: Places,
) -> None:
    """Add street information to the formatted place array."""
    street = None
    if sensor.is_attr_blank("street") and not sensor.is_attr_blank("street_ref"):
        street = sensor.get_attr_safe_str("street_ref").strip()
        _LOGGER.debug("Using street_ref: %s", street)
    elif not sensor.is_attr_blank("street"):
        if (
            not sensor.is_attr_blank("place_category")
            and sensor.get_attr_safe_str("place_category").lower() == "highway"
            and not sensor.is_attr_blank("place_type")
            and sensor.get_attr_safe_str("place_type").lower() in {"motorway", "trunk"}
            and not sensor.is_attr_blank("street_ref")
        ):
            street = sensor.get_attr_safe_str("street_ref").strip()
            _LOGGER.debug("Using street_ref: %s", street)
        else:
            street = sensor.get_attr_safe_str("street").strip()
            _LOGGER.debug("Using street: %s", street)
    if street and sensor.is_attr_blank("street_number"):
        formatted_place_array.append(street)
    elif street and not sensor.is_attr_blank("street_number"):
        formatted_place_array.append(
            f"{sensor.get_attr_safe_str('street_number').strip()} {street}"
        )


def add_neighbourhood_if_house(
    formatted_place_array: list[str],
    internal_attr: MutableMapping[str, Any],
    sensor: Places,
) -> None:
    """Add neighbourhood to the formatted place array if the place is a house."""
    if (
        not sensor.is_attr_blank("place_type")
        and sensor.get_attr_safe_str("place_type").lower() == "house"
        and not sensor.is_attr_blank("place_neighbourhood")
    ):
        formatted_place_array.append(sensor.get_attr_safe_str("place_neighbourhood").strip())


def add_city_county_state(
    formatted_place_array: list[str],
    internal_attr: MutableMapping[str, Any],
    sensor: Places,
) -> None:
    """Add city, county, and state information to the formatted place array."""
    if not sensor.is_attr_blank("city_clean"):
        formatted_place_array.append(sensor.get_attr_safe_str("city_clean").strip())
    elif not sensor.is_attr_blank("city"):
        formatted_place_array.append(sensor.get_attr_safe_str("city").strip())
    elif not sensor.is_attr_blank("county"):
        formatted_place_array.append(sensor.get_attr_safe_str("county").strip())
    if not sensor.is_attr_blank("state_abbr"):
        formatted_place_array.append(sensor.get_attr_safe_str("state_abbr"))

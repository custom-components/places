"""Build simple Places coordinator state strings from configured display options."""

from __future__ import annotations

from collections.abc import MutableMapping
import logging
from typing import TYPE_CHECKING, Any

from .const import (
    ATTR_DEVICETRACKER_ZONE,
    ATTR_DEVICETRACKER_ZONE_NAME,
    ATTR_PLACE_NEIGHBOURHOOD,
    ATTR_REGION,
    ATTR_ROUTE_NUMBER,
    PLACE_NAME_DUPLICATE_LIST,
)

if TYPE_CHECKING:
    from .coordinator import PlacesUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


class BasicOptionsParser:
    """Build display strings that do not require advanced option parsing."""

    def __init__(
        self,
        coordinator: PlacesUpdateCoordinator,
        internal_attr: MutableMapping[str, Any],
        display_options: list[str],
    ) -> None:
        """Initialize the parser with coordinator state and selected display options.

        Args:
            coordinator: Places coordinator that provides attribute access helpers.
            internal_attr: Current coordinator attribute mapping used for duplicate
                checks.
            display_options: Ordered user-selected display option names.
        """
        self.coordinator = coordinator
        self._internal_attr = internal_attr
        self.display_options = display_options

    def _add_to_display(
        self,
        user_display: list[str],
        attr_key: str,
        option_key: str | None = None,
        condition: bool = True,
        require_in_display_options: bool = True,
    ) -> None:
        """Append an attribute value when the display rules allow it.

        Args:
            user_display: Mutable list to which the display value is appended.
            attr_key: Attribute name to check and append.
            option_key: Display option key that gates inclusion.
            condition: Additional condition required before adding the value.
            require_in_display_options: When true, require ``option_key`` to be
                present in display options.
        """
        if (
            (not require_in_display_options or option_key in self.display_options)
            and not self.coordinator.is_attr_blank(attr_key)
            and condition
        ):
            user_display.append(self.coordinator.get_attr_safe_str(attr_key))

    async def build_display(self) -> str:
        """Build a comma-separated state string from basic display options.

        Returns:
            Display state assembled from non-blank attributes allowed by the
            selected options.
        """
        user_display: list[str] = []
        in_zone = await self.coordinator.in_zone()

        # Add basic options
        self._add_to_display(user_display, "driving", option_key="driving")
        self._add_to_display(
            user_display,
            attr_key=ATTR_DEVICETRACKER_ZONE_NAME,
            option_key="zone_name",
            condition=in_zone or "do_not_show_not_home" not in self.display_options,
        )
        self._add_to_display(
            user_display,
            attr_key=ATTR_DEVICETRACKER_ZONE,
            option_key="zone",
            condition=in_zone or "do_not_show_not_home" not in self.display_options,
        )
        self._add_to_display(user_display, "place_name", option_key="place_name")

        # Handle "place" and its sub-options
        if "place" in self.display_options:
            self._add_to_display(
                user_display,
                attr_key="place_name",
                condition=self._internal_attr.get("place_name")
                != self._internal_attr.get("street"),
                require_in_display_options=False,
            )
            self._add_to_display(
                user_display,
                attr_key="place_category",
                condition=self.coordinator.get_attr_safe_str("place_category").lower() != "place",
                require_in_display_options=False,
            )
            self._add_to_display(
                user_display,
                attr_key="place_type",
                condition=self.coordinator.get_attr_safe_str("place_type").lower() != "yes",
                require_in_display_options=False,
            )
            self._add_to_display(
                user_display,
                attr_key=ATTR_PLACE_NEIGHBOURHOOD,
                require_in_display_options=False,
            )
            self._add_to_display(
                user_display,
                attr_key="street_number",
                require_in_display_options=False,
            )
            self._add_to_display(
                user_display,
                attr_key="street",
                require_in_display_options=False,
            )
        else:
            self._add_to_display(user_display, "street_number", option_key="street_number")
            self._add_to_display(user_display, "street", option_key="street")

        # Add remaining location details
        for option_key, attr_key in {
            "city": "city",
            "county": "county",
            "state": ATTR_REGION,
            "region": ATTR_REGION,
            "postal_code": "postal_code",
            "country": "country",
            "formatted_address": "formatted_address",
        }.items():
            self._add_to_display(user_display, attr_key, option_key=option_key)

        # Handle "do_not_reorder" option
        if "do_not_reorder" in self.display_options:
            user_display = []
            self.display_options.remove("do_not_reorder")
            for option in self.display_options:
                attr_key = (
                    ATTR_REGION
                    if option == "state"
                    else ATTR_PLACE_NEIGHBOURHOOD
                    if option == "place_neighborhood"
                    else option
                )
                if not self.coordinator.is_attr_blank(attr_key):
                    user_display.append(self.coordinator.get_attr_safe_str(attr_key))

        return ", ".join(user_display)

    async def build_formatted_place(self) -> str:
        """Build the opinionated ``formatted_place`` display value.

        Returns:
            Human-readable place string with driving, place/street, and locality
            components collapsed into a single line.
        """
        formatted_place_array: list[str] = []
        if not await self.coordinator.in_zone():
            if not self.coordinator.is_attr_blank(
                "driving"
            ) and "driving" in self.coordinator.get_attr_safe_list("display_options_list"):
                formatted_place_array.append(self.coordinator.get_attr_safe_str("driving"))
            use_place_name = self.should_use_place_name(self._internal_attr, self.coordinator)
            if not use_place_name:
                self.add_type_or_category(
                    formatted_place_array, self._internal_attr, self.coordinator
                )
                self.add_street_info(formatted_place_array, self.coordinator)
                self.add_neighbourhood_if_house(formatted_place_array, self.coordinator)
            else:
                formatted_place_array.append(
                    self.coordinator.get_attr_safe_str("place_name").strip()
                )
            self.add_city_county_state(formatted_place_array, self.coordinator)
        else:
            formatted_place_array.append(
                self.coordinator.get_attr_safe_str(ATTR_DEVICETRACKER_ZONE_NAME).strip()
            )
        formatted_place = ", ".join(item for item in formatted_place_array)
        return formatted_place.replace("\n", " ").replace("  ", " ").strip()

    def should_use_place_name(
        self,
        internal_attr: MutableMapping[str, Any],
        coordinator: PlacesUpdateCoordinator,
    ) -> bool:
        """Decide whether the OSM place name adds distinct information.

        Args:
            internal_attr: Current coordinator attribute mapping.
            coordinator: Places coordinator used for blank checks and safe value access.

        Returns:
            ``True`` when ``place_name`` exists and does not duplicate address
            fields that will already be shown.
        """
        use_place_name = True
        sensor_attributes_values = [
            coordinator.get_attr_safe_str(attr)
            for attr in PLACE_NAME_DUPLICATE_LIST
            if not coordinator.is_attr_blank(attr)
        ]
        if (
            coordinator.is_attr_blank("place_name")
            or internal_attr.get("place_name") in sensor_attributes_values
        ):
            use_place_name = False
        _LOGGER.debug("use_place_name: %s", use_place_name)
        return use_place_name

    def add_type_or_category(
        self,
        formatted_place_array: list[str],
        internal_attr: MutableMapping[str, Any],
        coordinator: PlacesUpdateCoordinator,
    ) -> None:
        """Append a useful place type or category to a formatted-place list.

        Args:
            formatted_place_array: Mutable output list being assembled.
            internal_attr: Current coordinator attribute mapping.
            coordinator: Places coordinator used for blank checks and safe value access.
        """
        if (
            not coordinator.is_attr_blank("place_type")
            and coordinator.get_attr_safe_str("place_type").lower() != "unclassified"
            and coordinator.get_attr_safe_str("place_category").lower() != "highway"
        ):
            formatted_place_array.append(
                coordinator.get_attr_safe_str("place_type")
                .title()
                .replace("Proposed", "")
                .replace("Construction", "")
                .strip()
            )
        elif (
            not coordinator.is_attr_blank("place_category")
            and coordinator.get_attr_safe_str("place_category").lower() != "highway"
        ):
            formatted_place_array.append(
                coordinator.get_attr_safe_str("place_category").title().strip()
            )

    def add_street_info(
        self,
        formatted_place_array: list[str],
        coordinator: PlacesUpdateCoordinator,
    ) -> None:
        """Append street reference or house-number/street details.

        Args:
            formatted_place_array: Mutable output list being assembled.
            coordinator: Places coordinator used for blank checks and safe value access.
        """
        street = None
        if coordinator.is_attr_blank("street") and not coordinator.is_attr_blank(ATTR_ROUTE_NUMBER):
            street = coordinator.get_attr_safe_str(ATTR_ROUTE_NUMBER).strip()
            _LOGGER.debug("Using route_number: %s", street)
        elif not coordinator.is_attr_blank("street"):
            if (
                not coordinator.is_attr_blank("place_category")
                and coordinator.get_attr_safe_str("place_category").lower() == "highway"
                and not coordinator.is_attr_blank("place_type")
                and coordinator.get_attr_safe_str("place_type").lower() in {"motorway", "trunk"}
                and not coordinator.is_attr_blank(ATTR_ROUTE_NUMBER)
            ):
                street = coordinator.get_attr_safe_str(ATTR_ROUTE_NUMBER).strip()
                _LOGGER.debug("Using route_number: %s", street)
            else:
                street = coordinator.get_attr_safe_str("street").strip()
                _LOGGER.debug("Using street: %s", street)
        if street and coordinator.is_attr_blank("street_number"):
            formatted_place_array.append(street)
        elif street and not coordinator.is_attr_blank("street_number"):
            formatted_place_array.append(
                f"{coordinator.get_attr_safe_str('street_number').strip()} {street}"
            )

    def add_neighbourhood_if_house(
        self,
        formatted_place_array: list[str],
        coordinator: PlacesUpdateCoordinator,
    ) -> None:
        """Append neighbourhood context for house-level places.

        Args:
            formatted_place_array: Mutable output list being assembled.
            coordinator: Places coordinator used for blank checks and safe value access.
        """
        if (
            not coordinator.is_attr_blank("place_type")
            and coordinator.get_attr_safe_str("place_type").lower() == "house"
            and not coordinator.is_attr_blank(ATTR_PLACE_NEIGHBOURHOOD)
        ):
            formatted_place_array.append(
                coordinator.get_attr_safe_str(ATTR_PLACE_NEIGHBOURHOOD).strip()
            )

    def add_city_county_state(
        self,
        formatted_place_array: list[str],
        coordinator: PlacesUpdateCoordinator,
    ) -> None:
        """Append the best locality and state abbreviation available.

        Args:
            formatted_place_array: Mutable output list being assembled.
            coordinator: Places coordinator used for blank checks and safe value access.
        """
        if not coordinator.is_attr_blank("city_clean"):
            formatted_place_array.append(coordinator.get_attr_safe_str("city_clean").strip())
        elif not coordinator.is_attr_blank("city"):
            formatted_place_array.append(coordinator.get_attr_safe_str("city").strip())
        elif not coordinator.is_attr_blank("county"):
            formatted_place_array.append(coordinator.get_attr_safe_str("county").strip())
        if not coordinator.is_attr_blank("state_abbr"):
            formatted_place_array.append(coordinator.get_attr_safe_str("state_abbr"))

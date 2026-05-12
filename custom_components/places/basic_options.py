"""Build simple Places sensor state strings from configured display options."""

from __future__ import annotations

from collections.abc import MutableMapping
import logging
from typing import TYPE_CHECKING, Any

from .const import PLACE_NAME_DUPLICATE_LIST

if TYPE_CHECKING:
    from .sensor import Places

_LOGGER = logging.getLogger(__name__)


class BasicOptionsParser:
    """Build display strings that do not require advanced option parsing."""

    def __init__(
        self, sensor: Places, internal_attr: MutableMapping[str, Any], display_options: list[str]
    ) -> None:
        """Initialize the parser with sensor state and selected display options.

        Args:
            sensor: Places sensor that provides attribute access helpers.
            internal_attr: Current sensor attribute mapping used for duplicate
                checks.
            display_options: Ordered user-selected display option names.
        """
        self.sensor = sensor
        self._internal_attr = internal_attr
        self.display_options = display_options

    async def build_display(self) -> str:
        """Build a comma-separated state string from basic display options.

        Returns:
            Display state assembled from non-blank attributes allowed by the
            selected options.
        """
        user_display: list[str] = []

        def add_to_display(
            attr_key: str,
            option_key: str | None = None,
            condition: bool = True,
            require_in_display_options: bool = True,
        ) -> None:
            """Append an attribute value when the display rules allow it.

            Args:
                attr_key: Sensor attribute whose string value should be added.
                option_key: Display option that enables the attribute.
                condition: Scenario-specific gate for including the value.
                require_in_display_options: Whether ``option_key`` must be
                    present in the configured display options.
            """
            if (
                (not require_in_display_options or option_key in self.display_options)
                and not self.sensor.is_attr_blank(attr_key)
                and condition
            ):
                user_display.append(self.sensor.get_attr_safe_str(attr_key))

        # Add basic options
        add_to_display(option_key="driving", attr_key="driving")
        add_to_display(
            option_key="zone_name",
            attr_key="devicetracker_zone_name",
            condition=await self.sensor.in_zone()
            or "do_not_show_not_home" not in self.display_options,
        )
        add_to_display(
            option_key="zone",
            attr_key="devicetracker_zone",
            condition=await self.sensor.in_zone()
            or "do_not_show_not_home" not in self.display_options,
        )
        add_to_display("place_name", "place_name")

        # Handle "place" and its sub-options
        if "place" in self.display_options:
            add_to_display(
                attr_key="place_name",
                condition=self._internal_attr.get("place_name")
                != self._internal_attr.get("street"),
                require_in_display_options=False,
            )
            add_to_display(
                attr_key="place_category",
                condition=self.sensor.get_attr_safe_str("place_category").lower() != "place",
                require_in_display_options=False,
            )
            add_to_display(
                attr_key="place_type",
                condition=self.sensor.get_attr_safe_str("place_type").lower() != "yes",
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
        if "do_not_reorder" in self.display_options:
            user_display = []
            self.display_options.remove("do_not_reorder")
            for option in self.display_options:
                attr_key = (
                    "region"
                    if option == "state"
                    else "place_neighbourhood"
                    if option == "place_neighborhood"
                    else option
                )
                if not self.sensor.is_attr_blank(attr_key):
                    user_display.append(self.sensor.get_attr_safe_str(attr_key))

        return ", ".join(user_display)

    async def build_formatted_place(self) -> str:
        """Build the opinionated ``formatted_place`` display value.

        Returns:
            Human-readable place string with driving, place/street, and locality
            components collapsed into a single line.
        """
        formatted_place_array: list[str] = []
        if not await self.sensor.in_zone():
            if not self.sensor.is_attr_blank(
                "driving"
            ) and "driving" in self.sensor.get_attr_safe_list("display_options_list"):
                formatted_place_array.append(self.sensor.get_attr_safe_str("driving"))
            use_place_name = self.should_use_place_name(self._internal_attr, self.sensor)
            if not use_place_name:
                self.add_type_or_category(formatted_place_array, self._internal_attr, self.sensor)
                self.add_street_info(formatted_place_array, self._internal_attr, self.sensor)
                self.add_neighbourhood_if_house(
                    formatted_place_array, self._internal_attr, self.sensor
                )
            else:
                formatted_place_array.append(self.sensor.get_attr_safe_str("place_name").strip())
            self.add_city_county_state(formatted_place_array, self._internal_attr, self.sensor)
        else:
            formatted_place_array.append(
                self.sensor.get_attr_safe_str("devicetracker_zone_name").strip()
            )
        formatted_place = ", ".join(item for item in formatted_place_array)
        return formatted_place.replace("\n", " ").replace("  ", " ").strip()

    def should_use_place_name(
        self, internal_attr: MutableMapping[str, Any], sensor: Places
    ) -> bool:
        """Decide whether the OSM place name adds distinct information.

        Args:
            internal_attr: Current sensor attribute mapping.
            sensor: Places sensor used for blank checks and safe value access.

        Returns:
            ``True`` when ``place_name`` exists and does not duplicate address
            fields that will already be shown.
        """
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
        self,
        formatted_place_array: list[str],
        internal_attr: MutableMapping[str, Any],
        sensor: Places,
    ) -> None:
        """Append a useful place type or category to a formatted-place list.

        Args:
            formatted_place_array: Mutable output list being assembled.
            internal_attr: Current sensor attribute mapping.
            sensor: Places sensor used for blank checks and safe value access.
        """
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
        self,
        formatted_place_array: list[str],
        internal_attr: MutableMapping[str, Any],
        sensor: Places,
    ) -> None:
        """Append street reference or house-number/street details.

        Args:
            formatted_place_array: Mutable output list being assembled.
            internal_attr: Current sensor attribute mapping.
            sensor: Places sensor used for blank checks and safe value access.
        """
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
        self,
        formatted_place_array: list[str],
        internal_attr: MutableMapping[str, Any],
        sensor: Places,
    ) -> None:
        """Append neighbourhood context for house-level places.

        Args:
            formatted_place_array: Mutable output list being assembled.
            internal_attr: Current sensor attribute mapping.
            sensor: Places sensor used for blank checks and safe value access.
        """
        if (
            not sensor.is_attr_blank("place_type")
            and sensor.get_attr_safe_str("place_type").lower() == "house"
            and not sensor.is_attr_blank("place_neighbourhood")
        ):
            formatted_place_array.append(sensor.get_attr_safe_str("place_neighbourhood").strip())

    def add_city_county_state(
        self,
        formatted_place_array: list[str],
        internal_attr: MutableMapping[str, Any],
        sensor: Places,
    ) -> None:
        """Append the best locality and state abbreviation available.

        Args:
            formatted_place_array: Mutable output list being assembled.
            internal_attr: Current sensor attribute mapping.
            sensor: Places sensor used for blank checks and safe value access.
        """
        if not sensor.is_attr_blank("city_clean"):
            formatted_place_array.append(sensor.get_attr_safe_str("city_clean").strip())
        elif not sensor.is_attr_blank("city"):
            formatted_place_array.append(sensor.get_attr_safe_str("city").strip())
        elif not sensor.is_attr_blank("county"):
            formatted_place_array.append(sensor.get_attr_safe_str("county").strip())
        if not sensor.is_attr_blank("state_abbr"):
            formatted_place_array.append(sensor.get_attr_safe_str("state_abbr"))

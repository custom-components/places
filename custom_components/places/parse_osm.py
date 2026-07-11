"""Parse OpenStreetMap (OSM) data for Places in Home Assistant.

This module handles parsing OSM data, extracting relevant attributes,
and setting them in the coordinator's internal attributes.
"""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
import logging
import re
from typing import TYPE_CHECKING, Any

from homeassistant.const import ATTR_ATTRIBUTION, CONF_NAME

from .const import (
    ATTR_CITY,
    ATTR_CITY_CLEAN,
    ATTR_COUNTRY,
    ATTR_COUNTRY_CODE,
    ATTR_COUNTY,
    ATTR_DEVICETRACKER_ZONE_NAME,
    ATTR_FORMATTED_ADDRESS,
    ATTR_INITIAL_UPDATE,
    ATTR_LAST_PLACE_NAME,
    ATTR_OSM_DICT,
    ATTR_OSM_ID,
    ATTR_OSM_TYPE,
    ATTR_PLACE_CATEGORY,
    ATTR_PLACE_NAME,
    ATTR_PLACE_NAME_NO_DUPE,
    ATTR_PLACE_NEIGHBOURHOOD,
    ATTR_PLACE_TYPE,
    ATTR_POSTAL_CODE,
    ATTR_POSTAL_TOWN,
    ATTR_REGION,
    ATTR_ROUTE_NUMBER,
    ATTR_STATE_ABBR,
    ATTR_STREET,
    ATTR_STREET_NUMBER,
    CITY_LIST,
    CONF_LANGUAGE,
    NEIGHBOURHOOD_LIST,
    PLACE_NAME_DUPLICATE_LIST,
    POSTAL_TOWN_LIST,
)

if TYPE_CHECKING:
    from .coordinator import PlacesUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


class OSMParser:
    """Translate Nominatim/OpenStreetMap response fields into coordinator attributes."""

    def __init__(self, coordinator: PlacesUpdateCoordinator) -> None:
        """Initialize the parser for a Places coordinator.

        Args:
            coordinator: Places coordinator whose internal attributes receive parsed OSM
                values.
        """
        self.coordinator = coordinator

    def current_osm_dict(self) -> MutableMapping[str, Any]:
        """Return the current OSM response mapping from coordinator attributes.

        Returns:
            Current parsed OSM response mapping.
        """
        return self.coordinator.get_attr_safe_dict(ATTR_OSM_DICT)

    async def parse_osm_dict(self) -> None:
        """Parse the current OSM response stored on the coordinator.

        Reads ``ATTR_OSM_DICT`` from the coordinator, extracts attribution, place
        classification, address, display, OSM identity, and de-duplicated place
        name fields, then leaves the parsed values on the coordinator attributes.
        """
        osm_dict: MutableMapping[str, Any] | None = self.coordinator.get_attr(ATTR_OSM_DICT)
        if not osm_dict:
            return
        await self.set_attribution(osm_dict)
        await self.parse_type(osm_dict)
        await self.parse_category(osm_dict)
        await self.parse_namedetails(osm_dict)
        await self.parse_address(osm_dict)
        await self.parse_miscellaneous(osm_dict)
        await self.set_place_name_no_dupe()
        _LOGGER.debug(
            "(%s) Entity attributes after parsing OSM Dict: %s",
            self.coordinator.get_attr(CONF_NAME),
            self.coordinator.get_internal_attr(),
        )

    async def set_attribution(self, osm_dict: MutableMapping[str, Any]) -> None:
        """Store OSM licence text when the response provides it.

        Args:
            osm_dict: Parsed Nominatim response payload.
        """
        if "licence" not in osm_dict:
            return
        attribution: str | None = osm_dict.get("licence")
        if attribution:
            self.coordinator.set_attr(ATTR_ATTRIBUTION, attribution)

    async def parse_type(self, osm_dict: MutableMapping[str, Any]) -> None:
        """Resolve the most specific OSM place type for display decisions.

        Args:
            osm_dict: Parsed Nominatim response payload.
        """
        if "type" not in osm_dict:
            return
        place_type = osm_dict.get("type")
        if place_type == "yes":
            place_type = osm_dict.get("addresstype")
            if not place_type:
                self.coordinator.clear_attr(ATTR_PLACE_TYPE)
                return
        self.coordinator.set_attr(ATTR_PLACE_TYPE, place_type)
        address = osm_dict.get("address")
        if isinstance(address, MutableMapping) and place_type in address:
            self.coordinator.set_attr(
                ATTR_PLACE_NAME,
                address.get(place_type),
            )

    async def parse_category(self, osm_dict: MutableMapping[str, Any]) -> None:
        """Store the broad OSM category and matching address-derived name.

        Args:
            osm_dict: Parsed Nominatim response payload.
        """
        if "category" not in osm_dict:
            return

        self.coordinator.set_attr(
            ATTR_PLACE_CATEGORY,
            osm_dict.get("category"),
        )
        if (
            "address" in osm_dict
            and self.coordinator.get_attr(ATTR_PLACE_CATEGORY) in osm_dict["address"]
        ):
            self.coordinator.set_attr(
                ATTR_PLACE_NAME,
                osm_dict["address"].get(self.coordinator.get_attr(ATTR_PLACE_CATEGORY)),
            )

    async def parse_namedetails(self, osm_dict: MutableMapping[str, Any]) -> None:
        """Choose the preferred place name from Nominatim ``namedetails``.

        The generic ``name`` is used first, then any configured language-specific
        names are checked in order and may replace it.

        Args:
            osm_dict: Parsed Nominatim response payload.
        """
        namedetails: MutableMapping[str, Any] | None = osm_dict.get("namedetails")
        if not namedetails:
            return
        if "name" in namedetails:
            self.coordinator.set_attr(
                ATTR_PLACE_NAME,
                namedetails.get("name"),
            )
        if not self.coordinator.is_attr_blank(CONF_LANGUAGE):
            for language in self.coordinator.get_attr_safe_str(CONF_LANGUAGE).split(","):
                if f"name:{language}" in namedetails:
                    self.coordinator.set_attr(
                        ATTR_PLACE_NAME,
                        namedetails.get(f"name:{language}"),
                    )
                    break

    async def parse_address(self, osm_dict: MutableMapping[str, Any]) -> None:
        """Parse address components when the OSM response includes them.

        Args:
            osm_dict: Parsed Nominatim response payload.
        """
        address: MutableMapping[str, Any] | None = osm_dict.get("address")
        if not address:
            return

        await self.set_address_details(address)
        await self.set_city_details(address)
        await self.set_region_details(address)

    async def set_address_details(self, address: MutableMapping[str, Any]) -> None:
        """Store street-level address fields and retail fallback place names.

        Args:
            address: Nominatim ``address`` mapping from the current response.
        """
        if "house_number" in address:
            self.coordinator.set_attr(
                ATTR_STREET_NUMBER,
                address.get("house_number"),
            )
        if "road" in address:
            self.coordinator.set_attr(
                ATTR_STREET,
                address.get("road"),
            )
        if "retail" in address and (
            self.coordinator.is_attr_blank(ATTR_PLACE_NAME)
            or (
                not self.coordinator.is_attr_blank(ATTR_PLACE_CATEGORY)
                and not self.coordinator.is_attr_blank(ATTR_STREET)
                and self.coordinator.get_attr(ATTR_PLACE_CATEGORY) == "highway"
                and self.coordinator.get_attr(ATTR_STREET)
                == self.coordinator.get_attr(ATTR_PLACE_NAME)
            )
        ):
            self.coordinator.set_attr(
                ATTR_PLACE_NAME,
                address.get("retail"),
            )
        _LOGGER.debug(
            "(%s) Place Name: %s",
            self.coordinator.get_attr(CONF_NAME),
            self.coordinator.get_attr(ATTR_PLACE_NAME),
        )

    async def set_city_details(self, address: MutableMapping[str, Any]) -> None:
        """Store the first matching city, postal town, and neighbourhood fields.

        Args:
            address: Nominatim ``address`` mapping from the current response.
        """
        city_types_to_skip: list[str] = []
        for city_type in CITY_LIST:
            if city_type in address:
                self.coordinator.set_attr(
                    ATTR_CITY,
                    address.get(city_type),
                )
                city_types_to_skip = _prioritized_types_through_match(CITY_LIST, city_type)
                break

        postal_town_types = _without_prioritized_types(POSTAL_TOWN_LIST, city_types_to_skip)
        postal_town_types_to_skip: list[str] = []
        for postal_town_type in postal_town_types:
            if postal_town_type in address:
                self.coordinator.set_attr(
                    ATTR_POSTAL_TOWN,
                    address.get(postal_town_type),
                )
                postal_town_types_to_skip = _prioritized_types_through_match(
                    postal_town_types,
                    postal_town_type,
                )
                break

        neighbourhood_types = _without_prioritized_types(
            NEIGHBOURHOOD_LIST,
            [*city_types_to_skip, *postal_town_types_to_skip],
        )
        for neighbourhood_type in neighbourhood_types:
            if neighbourhood_type in address:
                self.coordinator.set_attr(
                    ATTR_PLACE_NEIGHBOURHOOD,
                    address.get(neighbourhood_type),
                )
                break

        if not self.coordinator.is_attr_blank(ATTR_CITY):
            self.coordinator.set_attr(
                ATTR_CITY_CLEAN,
                self.coordinator.get_attr_safe_str(ATTR_CITY).replace(" Township", "").strip(),
            )
            if self.coordinator.get_attr_safe_str(ATTR_CITY_CLEAN).startswith("City of"):
                self.coordinator.set_attr(
                    ATTR_CITY_CLEAN,
                    f"{self.coordinator.get_attr_safe_str(ATTR_CITY_CLEAN)[8:]} City",
                )

    async def set_region_details(self, address: MutableMapping[str, Any]) -> None:
        """Store regional and country-level address fields.

        Args:
            address: Nominatim ``address`` mapping from the current response.
        """
        if "state" in address:
            self.coordinator.set_attr(
                ATTR_REGION,
                address.get("state"),
            )
        if "ISO3166-2-lvl4" in address:
            iso_parts = address["ISO3166-2-lvl4"].split("-")
            if len(iso_parts) >= 2:
                self.coordinator.set_attr(
                    ATTR_STATE_ABBR,
                    iso_parts[1].upper(),
                )
        if "county" in address:
            self.coordinator.set_attr(
                ATTR_COUNTY,
                address.get("county"),
            )
        if "country" in address:
            self.coordinator.set_attr(
                ATTR_COUNTRY,
                address.get("country"),
            )
        if "country_code" in address:
            self.coordinator.set_attr(
                ATTR_COUNTRY_CODE,
                address["country_code"].upper(),
            )
        if "postcode" in address:
            self.coordinator.set_attr(
                ATTR_POSTAL_CODE,
                address.get("postcode"),
            )

    async def parse_miscellaneous(self, osm_dict: MutableMapping[str, Any]) -> None:
        """Store display address, OSM identifiers, and highway reference numbers.

        Args:
            osm_dict: Parsed Nominatim response payload.
        """
        if "display_name" in osm_dict:
            self.coordinator.set_attr(
                ATTR_FORMATTED_ADDRESS,
                osm_dict.get("display_name"),
            )

        if "osm_id" in osm_dict:
            self.coordinator.set_attr(
                ATTR_OSM_ID,
                str(osm_dict.get("osm_id", "")),
            )
        if "osm_type" in osm_dict:
            self.coordinator.set_attr(
                ATTR_OSM_TYPE,
                osm_dict.get("osm_type"),
            )

        namedetails = osm_dict.get("namedetails")
        if (
            not self.coordinator.is_attr_blank(ATTR_PLACE_CATEGORY)
            and self.coordinator.get_attr_safe_str(ATTR_PLACE_CATEGORY).lower() == "highway"
            and isinstance(namedetails, Mapping)
            and "ref" in namedetails
        ):
            raw_ref = namedetails.get("ref")
            if not isinstance(raw_ref, str) or not raw_ref.strip():
                self.coordinator.clear_attr(ATTR_ROUTE_NUMBER)
                _LOGGER.debug(
                    "(%s) Skipping street ref parsing due to invalid ref value: %r",
                    self.coordinator.get_attr(CONF_NAME),
                    raw_ref,
                )
            else:
                street_refs: list[str] = re.split(r"[;\\/,.:]", raw_ref)
                street_refs = [i for i in street_refs if i.strip()]  # Remove blank strings
                for ref in street_refs:
                    if bool(re.search(r"\d", ref)):
                        self.coordinator.set_attr(ATTR_ROUTE_NUMBER, ref)
                        break
                else:
                    self.coordinator.clear_attr(ATTR_ROUTE_NUMBER)
            if not self.coordinator.is_attr_blank(ATTR_ROUTE_NUMBER):
                _LOGGER.debug(
                    "(%s) Street: %s / Street Ref: %s",
                    self.coordinator.get_attr(CONF_NAME),
                    self.coordinator.get_attr(ATTR_STREET),
                    self.coordinator.get_attr(ATTR_ROUTE_NUMBER),
                )

    async def set_place_name_no_dupe(self) -> None:
        """Expose place name only when it is not already shown by another field."""
        dupe_attributes_check: list[str] = []
        dupe_attributes_check.extend(
            [
                self.coordinator.get_attr_safe_str(attr)
                for attr in PLACE_NAME_DUPLICATE_LIST
                if not self.coordinator.is_attr_blank(attr)
            ]
        )
        if (
            not self.coordinator.is_attr_blank(ATTR_PLACE_NAME)
            and self.coordinator.get_attr(ATTR_PLACE_NAME) not in dupe_attributes_check
        ):
            self.coordinator.set_attr(
                ATTR_PLACE_NAME_NO_DUPE,
                self.coordinator.get_attr(ATTR_PLACE_NAME),
            )

    async def finalize_last_place_name(self, prev_last_place_name: str) -> None:
        """Preserve the useful previous place name after a successful parse.

        Args:
            prev_last_place_name: Last known place name captured before this
                update began.
        """
        if self.coordinator.get_attr(ATTR_INITIAL_UPDATE):
            self.coordinator.set_attr(ATTR_LAST_PLACE_NAME, prev_last_place_name)
            _LOGGER.debug(
                "(%s) Running initial update after load, using prior last_place_name",
                self.coordinator.get_attr(CONF_NAME),
            )
        elif self.coordinator.get_attr(ATTR_LAST_PLACE_NAME) == self.coordinator.get_attr(
            ATTR_PLACE_NAME
        ) or self.coordinator.get_attr(ATTR_LAST_PLACE_NAME) == self.coordinator.get_attr(
            ATTR_DEVICETRACKER_ZONE_NAME
        ):
            # If current place name/zone are the same as previous, keep older last_place_name
            self.coordinator.set_attr(ATTR_LAST_PLACE_NAME, prev_last_place_name)
            _LOGGER.debug(
                "(%s) Initial last_place_name is same as new: place_name=%s or "
                "devicetracker_zone_name=%s, "
                "keeping previous last_place_name",
                self.coordinator.get_attr(CONF_NAME),
                self.coordinator.get_attr(ATTR_PLACE_NAME),
                self.coordinator.get_attr(ATTR_DEVICETRACKER_ZONE_NAME),
            )
        else:
            _LOGGER.debug(
                "(%s) Keeping initial last_place_name", self.coordinator.get_attr(CONF_NAME)
            )
        _LOGGER.info(
            "(%s) last_place_name: %s",
            self.coordinator.get_attr(CONF_NAME),
            self.coordinator.get_attr(ATTR_LAST_PLACE_NAME),
        )


def _without_prioritized_types(types: list[str], prioritized_types: list[str]) -> list[str]:
    """Return address types not already claimed by a higher-priority group.

    Args:
        types: Candidate address types for the current group.
        prioritized_types: Address types already considered by earlier groups.

    Returns:
        Candidate address types preserving original order and excluding higher-priority types.
    """
    prioritized = set(prioritized_types)
    return [address_type for address_type in types if address_type not in prioritized]


def _prioritized_types_through_match(types: list[str], matched_type: str) -> list[str]:
    """Return candidate types through the matched type, preserving precedence order.

    Args:
        types: Candidate address types in precedence order.
        matched_type: Address type selected from the candidate list.

    Returns:
        Address types at or above the selected type in the precedence order.
    """
    return types[: types.index(matched_type) + 1]

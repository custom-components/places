"""Parse OpenStreetMap (OSM) data for Places in Home Assistant.

This module handles parsing OSM data, extracting relevant attributes,
and setting them in the sensor's internal attributes.
"""

from __future__ import annotations

from collections.abc import MutableMapping
import contextlib
import logging
import re
from typing import Any

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
    ATTR_STATE_ABBR,
    ATTR_STREET,
    ATTR_STREET_NUMBER,
    ATTR_STREET_REF,
    CONF_LANGUAGE,
    PLACE_NAME_DUPLICATE_LIST,
)
from .sensor import Places

_LOGGER = logging.getLogger(__name__)


class OSMParser:
    """Handles parsing of OSM data for Places."""

    def __init__(self, sensor: Places) -> None:
        """Initialize the OSMParser with a Places sensor."""
        self.sensor = sensor

    async def parse_osm_dict(self) -> None:
        """Parse the OSM dictionary and set attributes in the sensor."""
        osm_dict: MutableMapping[str, Any] | None = self.sensor.get_attr(ATTR_OSM_DICT)
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
            self.sensor.get_attr(CONF_NAME),
            self.sensor.get_internal_attr(),
        )

    async def set_attribution(self, osm_dict: MutableMapping[str, Any]) -> None:
        """Set the attribution from the OSM dictionary."""
        if "licence" not in osm_dict:
            return
        attribution: str | None = osm_dict.get("licence")
        if attribution:
            self.sensor.set_attr(ATTR_ATTRIBUTION, attribution)
        #     _LOGGER.debug(
        #         "(%s) OSM Attribution: %s",
        #         self.sensor.get_attr(CONF_NAME),
        #         self.sensor.get_attr(ATTR_ATTRIBUTION),
        #     )
        # else:
        #     _LOGGER.debug("(%s) No OSM Attribution found", self.sensor.get_attr(CONF_NAME))

    async def parse_type(self, osm_dict: MutableMapping[str, Any]) -> None:
        """Parse the type from the OSM dictionary and set it in the sensor."""
        if "type" not in osm_dict:
            return
        self.sensor.set_attr(ATTR_PLACE_TYPE, osm_dict.get("type"))
        if self.sensor.get_attr(ATTR_PLACE_TYPE) == "yes":
            if "addresstype" in osm_dict:
                self.sensor.set_attr(
                    ATTR_PLACE_TYPE,
                    osm_dict.get("addresstype"),
                )
            else:
                self.sensor.clear_attr(ATTR_PLACE_TYPE)
        if "address" in osm_dict and self.sensor.get_attr(ATTR_PLACE_TYPE) in osm_dict["address"]:
            self.sensor.set_attr(
                ATTR_PLACE_NAME,
                osm_dict["address"].get(self.sensor.get_attr(ATTR_PLACE_TYPE)),
            )

    async def parse_category(self, osm_dict: MutableMapping[str, Any]) -> None:
        """Parse the category from the OSM dictionary and set it in the sensor."""
        if "category" not in osm_dict:
            return

        self.sensor.set_attr(
            ATTR_PLACE_CATEGORY,
            osm_dict.get("category"),
        )
        if (
            "address" in osm_dict
            and self.sensor.get_attr(ATTR_PLACE_CATEGORY) in osm_dict["address"]
        ):
            self.sensor.set_attr(
                ATTR_PLACE_NAME,
                osm_dict["address"].get(self.sensor.get_attr(ATTR_PLACE_CATEGORY)),
            )

    async def parse_namedetails(self, osm_dict: MutableMapping[str, Any]) -> None:
        """Parse the namedetails from the OSM dictionary and set them in the sensor."""
        namedetails: MutableMapping[str, Any] | None = osm_dict.get("namedetails")
        if not namedetails:
            return
        if "name" in namedetails:
            self.sensor.set_attr(
                ATTR_PLACE_NAME,
                namedetails.get("name"),
            )
        if not self.sensor.is_attr_blank(CONF_LANGUAGE):
            for language in self.sensor.get_attr_safe_str(CONF_LANGUAGE).split(","):
                if f"name:{language}" in namedetails:
                    self.sensor.set_attr(
                        ATTR_PLACE_NAME,
                        namedetails.get(f"name:{language}"),
                    )
                    break

    async def parse_address(self, osm_dict: MutableMapping[str, Any]) -> None:
        """Parse the address from the OSM dictionary and set it in the sensor."""
        address: MutableMapping[str, Any] | None = osm_dict.get("address")
        if not address:
            return

        await self.set_address_details(address)
        await self.set_city_details(address)
        await self.set_region_details(address)

    async def set_address_details(self, address: MutableMapping[str, Any]) -> None:
        """Set address details in the sensor from the OSM address dictionary."""
        if "house_number" in address:
            self.sensor.set_attr(
                ATTR_STREET_NUMBER,
                address.get("house_number"),
            )
        if "road" in address:
            self.sensor.set_attr(
                ATTR_STREET,
                address.get("road"),
            )
        if "retail" in address and (
            self.sensor.is_attr_blank(ATTR_PLACE_NAME)
            or (
                not self.sensor.is_attr_blank(ATTR_PLACE_CATEGORY)
                and not self.sensor.is_attr_blank(ATTR_STREET)
                and self.sensor.get_attr(ATTR_PLACE_CATEGORY) == "highway"
                and self.sensor.get_attr(ATTR_STREET) == self.sensor.get_attr(ATTR_PLACE_NAME)
            )
        ):
            self.sensor.set_attr(
                ATTR_PLACE_NAME,
                self.sensor.get_attr_safe_dict(ATTR_OSM_DICT).get("address", {}).get("retail"),
            )
        _LOGGER.debug(
            "(%s) Place Name: %s",
            self.sensor.get_attr(CONF_NAME),
            self.sensor.get_attr(ATTR_PLACE_NAME),
        )

    async def set_city_details(self, address: MutableMapping[str, Any]) -> None:
        """Set city, postal town, and neighbourhood details in the sensor from the OSM address dictionary."""
        CITY_LIST: list[str] = [
            "city",
            "town",
            "village",
            "township",
            "hamlet",
            "city_district",
            "municipality",
        ]
        POSTAL_TOWN_LIST: list[str] = [
            "city",
            "town",
            "village",
            "township",
            "hamlet",
            "borough",
            "suburb",
        ]
        NEIGHBOURHOOD_LIST: list[str] = [
            "village",
            "township",
            "hamlet",
            "borough",
            "suburb",
            "quarter",
            "neighbourhood",
        ]
        for city_type in CITY_LIST:
            with contextlib.suppress(ValueError):
                POSTAL_TOWN_LIST.remove(city_type)

            with contextlib.suppress(ValueError):
                NEIGHBOURHOOD_LIST.remove(city_type)
            if city_type in address:
                self.sensor.set_attr(
                    ATTR_CITY,
                    address.get(city_type),
                )
                break
        for postal_town_type in POSTAL_TOWN_LIST:
            with contextlib.suppress(ValueError):
                NEIGHBOURHOOD_LIST.remove(postal_town_type)
            if postal_town_type in address:
                self.sensor.set_attr(
                    ATTR_POSTAL_TOWN,
                    address.get(postal_town_type),
                )
                break
        for neighbourhood_type in NEIGHBOURHOOD_LIST:
            if neighbourhood_type in address:
                self.sensor.set_attr(
                    ATTR_PLACE_NEIGHBOURHOOD,
                    address.get(neighbourhood_type),
                )
                break

        if not self.sensor.is_attr_blank(ATTR_CITY):
            self.sensor.set_attr(
                ATTR_CITY_CLEAN,
                self.sensor.get_attr_safe_str(ATTR_CITY).replace(" Township", "").strip(),
            )
            if self.sensor.get_attr_safe_str(ATTR_CITY_CLEAN).startswith("City of"):
                self.sensor.set_attr(
                    ATTR_CITY_CLEAN,
                    f"{self.sensor.get_attr_safe_str(ATTR_CITY_CLEAN)[8:]} City",
                )

    async def set_region_details(self, address: MutableMapping[str, Any]) -> None:
        """Set region, state abbreviation, county, country, and postal code details in the sensor from the OSM address dictionary."""
        if "state" in address:
            self.sensor.set_attr(
                ATTR_REGION,
                address.get("state"),
            )
        if "ISO3166-2-lvl4" in address:
            self.sensor.set_attr(
                ATTR_STATE_ABBR,
                address["ISO3166-2-lvl4"].split("-")[1].upper(),
            )
        if "county" in address:
            self.sensor.set_attr(
                ATTR_COUNTY,
                address.get("county"),
            )
        if "country" in address:
            self.sensor.set_attr(
                ATTR_COUNTRY,
                address.get("country"),
            )
        if "country_code" in address:
            self.sensor.set_attr(
                ATTR_COUNTRY_CODE,
                address["country_code"].upper(),
            )
        if "postcode" in address:
            self.sensor.set_attr(
                ATTR_POSTAL_CODE,
                self.sensor.get_attr_safe_dict(ATTR_OSM_DICT).get("address", {}).get("postcode"),
            )

    async def parse_miscellaneous(self, osm_dict: MutableMapping[str, Any]) -> None:
        """Parse miscellaneous attributes from the OSM dictionary and set them in the sensor."""
        if "display_name" in osm_dict:
            self.sensor.set_attr(
                ATTR_FORMATTED_ADDRESS,
                osm_dict.get("display_name"),
            )

        if "osm_id" in osm_dict:
            self.sensor.set_attr(
                ATTR_OSM_ID,
                str(self.sensor.get_attr_safe_dict(ATTR_OSM_DICT).get("osm_id", "")),
            )
        if "osm_type" in osm_dict:
            self.sensor.set_attr(
                ATTR_OSM_TYPE,
                osm_dict.get("osm_type"),
            )

        if (
            not self.sensor.is_attr_blank(ATTR_PLACE_CATEGORY)
            and self.sensor.get_attr_safe_str(ATTR_PLACE_CATEGORY).lower() == "highway"
            and "namedetails" in osm_dict
            and osm_dict.get("namedetails") is not None
            and "ref" in osm_dict["namedetails"]
        ):
            street_refs: list = re.split(
                r"[\;\\\/\,\.\:]",
                osm_dict["namedetails"].get("ref"),
            )
            street_refs = [i for i in street_refs if i.strip()]  # Remove blank strings
            # _LOGGER.debug("(%s) Street Refs: %s", self.sensor.get_attr(CONF_NAME), street_refs)
            for ref in street_refs:
                if bool(re.search(r"\d", ref)):
                    self.sensor.set_attr(ATTR_STREET_REF, ref)
                    break
            if not self.sensor.is_attr_blank(ATTR_STREET_REF):
                _LOGGER.debug(
                    "(%s) Street: %s / Street Ref: %s",
                    self.sensor.get_attr(CONF_NAME),
                    self.sensor.get_attr(ATTR_STREET),
                    self.sensor.get_attr(ATTR_STREET_REF),
                )

    async def set_place_name_no_dupe(self) -> None:
        """Set the place name without duplicates in the sensor."""
        dupe_attributes_check: list[str] = []
        dupe_attributes_check.extend(
            [
                self.sensor.get_attr_safe_str(attr)
                for attr in PLACE_NAME_DUPLICATE_LIST
                if not self.sensor.is_attr_blank(attr)
            ]
        )
        if (
            not self.sensor.is_attr_blank(ATTR_PLACE_NAME)
            and self.sensor.get_attr(ATTR_PLACE_NAME) not in dupe_attributes_check
        ):
            self.sensor.set_attr(ATTR_PLACE_NAME_NO_DUPE, self.sensor.get_attr(ATTR_PLACE_NAME))

    async def finalize_last_place_name(self, prev_last_place_name: str) -> None:
        """Finalize the last place name after parsing OSM data."""
        if self.sensor.get_attr(ATTR_INITIAL_UPDATE):
            self.sensor.set_attr(ATTR_LAST_PLACE_NAME, prev_last_place_name)
            _LOGGER.debug(
                "(%s) Runnining initial update after load, using prior last_place_name",
                self.sensor.get_attr(CONF_NAME),
            )
        elif self.sensor.get_attr(ATTR_LAST_PLACE_NAME) == self.sensor.get_attr(
            ATTR_PLACE_NAME
        ) or self.sensor.get_attr(ATTR_LAST_PLACE_NAME) == self.sensor.get_attr(
            ATTR_DEVICETRACKER_ZONE_NAME
        ):
            # If current place name/zone are the same as previous, keep older last_place_name
            self.sensor.set_attr(ATTR_LAST_PLACE_NAME, prev_last_place_name)
            _LOGGER.debug(
                "(%s) Initial last_place_name is same as new: place_name=%s or devicetracker_zone_name=%s, "
                "keeping previous last_place_name",
                self.sensor.get_attr(CONF_NAME),
                self.sensor.get_attr(ATTR_PLACE_NAME),
                self.sensor.get_attr(ATTR_DEVICETRACKER_ZONE_NAME),
            )
        else:
            _LOGGER.debug("(%s) Keeping initial last_place_name", self.sensor.get_attr(CONF_NAME))
        _LOGGER.info(
            "(%s) last_place_name: %s",
            self.sensor.get_attr(CONF_NAME),
            self.sensor.get_attr(ATTR_LAST_PLACE_NAME),
        )

"""
Place Support for OpenStreetMap Geocode sensors.

Original Author:  Jim Thompson
Subsequent Author: Ian Richardson
Current Author: Snuffy2

Description:
  Provides a sensor with a variable state consisting of reverse geocode (place) details for a linked device_tracker entity that provides GPS co-ordinates (ie owntracks, icloud)
  Optionally allows you to specify a 'home_zone' for each device and calculates distance from home and direction of travel.
  Configuration Instructions are on GitHub.
  
GitHub: https://github.com/Snuffy2/places
"""

import json
import logging
from datetime import datetime
from datetime import timedelta
from math import asin
from math import cos
from math import radians
from math import sin
from math import sqrt

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant import config_entries
from homeassistant import core
from homeassistant.components.sensor import PLATFORM_SCHEMA
from homeassistant.const import CONF_API_KEY
from homeassistant.const import CONF_FRIENDLY_NAME
from homeassistant.const import CONF_NAME
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.const import CONF_ZONE
from homeassistant.const import Platform
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.event import async_track_state_change
from homeassistant.util import Throttle
from homeassistant.util.location import distance
from requests import get

from .const import ATTR_CITY
from .const import ATTR_COUNTRY
from .const import ATTR_COUNTY
from .const import ATTR_DEVICETRACKER_ID
from .const import ATTR_DEVICETRACKER_ZONE
from .const import ATTR_DEVICETRACKER_ZONE_NAME
from .const import ATTR_DIRECTION_OF_TRAVEL
from .const import ATTR_DISTANCE_KM
from .const import ATTR_DISTANCE_M
from .const import ATTR_FORMATTED_ADDRESS
from .const import ATTR_FORMATTED_PLACE
from .const import ATTR_HOME_LATITUDE
from .const import ATTR_HOME_LONGITUDE
from .const import ATTR_HOME_ZONE
from .const import ATTR_LAST_PLACE_NAME
from .const import ATTR_LATITUDE
from .const import ATTR_LATITUDE_OLD
from .const import ATTR_LOCATION_CURRENT
from .const import ATTR_LOCATION_PREVIOUS
from .const import ATTR_LONGITUDE
from .const import ATTR_LONGITUDE_OLD
from .const import ATTR_MAP_LINK
from .const import ATTR_MTIME
from .const import ATTR_OPTIONS
from .const import ATTR_OSM_DETAILS_DICT
from .const import ATTR_OSM_DICT
from .const import ATTR_OSM_ID
from .const import ATTR_OSM_TYPE
from .const import ATTR_PICTURE
from .const import ATTR_PLACE_CATEGORY
from .const import ATTR_PLACE_NAME
from .const import ATTR_PLACE_NEIGHBOURHOOD
from .const import ATTR_PLACE_TYPE
from .const import ATTR_POSTAL_CODE
from .const import ATTR_POSTAL_TOWN
from .const import ATTR_REGION
from .const import ATTR_STATE_ABBR
from .const import ATTR_STREET
from .const import ATTR_STREET_NUMBER
from .const import ATTR_WIKIDATA_DICT
from .const import ATTR_WIKIDATA_ID
from .const import CONF_DEVICETRACKER_ID
from .const import CONF_EXTENDED_ATTR
from .const import CONF_HOME_ZONE
from .const import CONF_LANGUAGE
from .const import CONF_MAP_PROVIDER
from .const import CONF_MAP_ZOOM
from .const import CONF_OPTIONS
from .const import DEFAULT_EXTENDED_ATTR
from .const import DEFAULT_HOME_ZONE
from .const import DEFAULT_KEY
from .const import DEFAULT_LANGUAGE
from .const import DEFAULT_MAP_PROVIDER
from .const import DEFAULT_MAP_ZOOM
from .const import DEFAULT_OPTION
from .const import DOMAIN

THROTTLE_INTERVAL = timedelta(seconds=600)
TRACKING_DOMAIN = Platform.DEVICE_TRACKER
HOME_LOCATION_DOMAIN = CONF_ZONE
SCAN_INTERVAL = timedelta(seconds=30)
_LOGGER = logging.getLogger(__name__)


PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_DEVICETRACKER_ID): cv.string,
        vol.Optional(CONF_API_KEY, default=DEFAULT_KEY): cv.string,
        vol.Optional(CONF_OPTIONS, default=DEFAULT_OPTION): cv.string,
        vol.Optional(CONF_HOME_ZONE, default=DEFAULT_HOME_ZONE): cv.string,
        vol.Optional(CONF_NAME): cv.string,
        vol.Optional(CONF_MAP_PROVIDER, default=DEFAULT_MAP_PROVIDER): cv.string,
        vol.Optional(CONF_MAP_ZOOM, default=DEFAULT_MAP_ZOOM): cv.positive_int,
        vol.Optional(CONF_LANGUAGE, default=DEFAULT_LANGUAGE): cv.string,
        vol.Optional(CONF_SCAN_INTERVAL, default=SCAN_INTERVAL): cv.time_period,
        vol.Optional(CONF_EXTENDED_ATTR, default=DEFAULT_EXTENDED_ATTR): cv.boolean,
    }
)


async def async_setup_entry(
    hass: core.HomeAssistant,
    config_entry: config_entries.ConfigEntry,
    async_add_entities,
) -> None:
    """Setup the sensor platform."""

    config = hass.data[DOMAIN][config_entry.entry_id]
    unique_id = config_entry.entry_id
    name = config.get(CONF_NAME)
    _LOGGER.debug("[async_setup_entry] config: " + str(config))
    async_add_entities([Places(hass, config, name, unique_id)], update_before_add=True)


class Places(Entity):
    """Representation of a Places Sensor."""

    def __init__(self, hass, config, name, unique_id):
        """Initialize the sensor."""
        _LOGGER.debug("[Init] New places sensor: " + str(name))
        _LOGGER.debug("(" + str(name) + ") [Init] unique_id: " + str(unique_id))
        _LOGGER.debug("(" + str(name) + ") [Init] config: " + str(config))

        self._config = config
        self._hass = hass
        self._name = name
        self._unique_id = unique_id
        self._api_key = config.setdefault(CONF_API_KEY, DEFAULT_KEY)
        self._options = config.setdefault(CONF_OPTIONS, DEFAULT_OPTION).lower()
        self._devicetracker_id = config.get(CONF_DEVICETRACKER_ID).lower()
        self._home_zone = config.setdefault(CONF_HOME_ZONE, DEFAULT_HOME_ZONE).lower()
        self._map_provider = config.setdefault(
            CONF_MAP_PROVIDER, DEFAULT_MAP_PROVIDER
        ).lower()
        self._map_zoom = config.setdefault(CONF_MAP_ZOOM, DEFAULT_MAP_ZOOM)
        self._language = config.setdefault(CONF_LANGUAGE, DEFAULT_LANGUAGE).lower()
        self._language.replace(" ", "")
        self._extended_attr = config.setdefault(
            CONF_EXTENDED_ATTR, DEFAULT_EXTENDED_ATTR
        )
        self._state = "Initializing..."

        home_latitude = str(hass.states.get(self._home_zone).attributes.get("latitude"))
        if not self.is_float(home_latitude):
            home_latitude = None
        home_longitude = str(
            hass.states.get(self._home_zone).attributes.get("longitude")
        )
        if not self.is_float(home_longitude):
            home_longitude = None
        self._entity_picture = (
            hass.states.get(self._devicetracker_id).attributes.get("entity_picture")
            if hass.states.get(self._devicetracker_id)
            else None
        )
        self._street_number = None
        self._street = None
        self._city = None
        self._postal_town = None
        self._postal_code = None
        self._city = None
        self._region = None
        self._state_abbr = None
        self._country = None
        self._county = None
        self._formatted_address = None
        self._place_type = None
        self._place_name = None
        self._place_category = None
        self._place_neighbourhood = None
        self._home_latitude = home_latitude
        self._home_longitude = home_longitude
        self._latitude_old = home_latitude
        self._longitude_old = home_longitude
        self._latitude = home_latitude
        self._longitude = home_longitude
        self._devicetracker_zone = "Home"
        self._devicetracker_zone_name = "Home"
        self._mtime = str(datetime.now())
        self._last_place_name = None
        self._distance_km = 0
        self._distance_m = 0
        self._location_current = home_latitude + "," + home_longitude
        self._location_previous = home_latitude + "," + home_longitude
        self._updateskipped = 0
        self._direction = "stationary"
        self._map_link = None
        self._formatted_place = None
        self._osm_id = None
        self._osm_type = None
        self._wikidata_id = None
        self._osm_dict = None
        self._osm_details_dict = None
        self._wikidata_dict = None

        # Check if devicetracker_id was specified correctly
        _LOGGER.info(
            "("
            + self._name
            + ") [Init] DeviceTracker Entity ID: "
            + self._devicetracker_id
        )

        # if devicetracker_id.split(".", 1)[0] in TRACKABLE_DOMAINS:
        # self._devicetracker_id = devicetracker_id
        async_track_state_change(
            hass,
            self._devicetracker_id,
            self.tsc_update,
            from_state=None,
            to_state=None,
        )
        _LOGGER.info(
            "("
            + self._name
            + ") [Init] Subscribed to DeviceTracker state change events"
        )

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    @property
    def unique_id(self):
        """Return a unique ID to use for this sensor."""
        return self._unique_id

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    @property
    def entity_picture(self):
        """Return the picture of the device."""
        return self._entity_picture

    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        return_attr = {}

        if self._street_number is not None:
            return_attr[ATTR_STREET_NUMBER] = self._street_number
        if self._street is not None:
            return_attr[ATTR_STREET] = self._street
        if self._city is not None:
            return_attr[ATTR_CITY] = self._city
        if self._postal_town is not None:
            return_attr[ATTR_POSTAL_TOWN] = self._postal_town
        if self._postal_code is not None:
            return_attr[ATTR_POSTAL_CODE] = self._postal_code
        if self._region is not None:
            return_attr[ATTR_REGION] = self._region
        if self._state_abbr is not None:
            return_attr[ATTR_STATE_ABBR] = self._state_abbr
        if self._country is not None:
            return_attr[ATTR_COUNTRY] = self._country
        if self._county is not None:
            return_attr[ATTR_COUNTY] = self._county
        if self._formatted_address is not None:
            return_attr[ATTR_FORMATTED_ADDRESS] = self._formatted_address
        if self._place_type is not None:
            return_attr[ATTR_PLACE_TYPE] = self._place_type
        if self._place_name is not None:
            return_attr[ATTR_PLACE_NAME] = self._place_name
        if self._place_category is not None:
            return_attr[ATTR_PLACE_CATEGORY] = self._place_category
        if self._place_neighbourhood is not None:
            return_attr[ATTR_PLACE_NEIGHBOURHOOD] = self._place_neighbourhood
        if self._formatted_place is not None:
            return_attr[ATTR_FORMATTED_PLACE] = self._formatted_place
        if self._latitude_old is not None:
            return_attr[ATTR_LATITUDE_OLD] = self._latitude_old
        if self._longitude_old is not None:
            return_attr[ATTR_LONGITUDE_OLD] = self._longitude_old
        if self._latitude is not None:
            return_attr[ATTR_LATITUDE] = self._latitude
        if self._longitude is not None:
            return_attr[ATTR_LONGITUDE] = self._longitude
        if self._devicetracker_id is not None:
            return_attr[ATTR_DEVICETRACKER_ID] = self._devicetracker_id
        if self._devicetracker_zone is not None:
            return_attr[ATTR_DEVICETRACKER_ZONE] = self._devicetracker_zone
        if self._devicetracker_zone_name is not None:
            return_attr[ATTR_DEVICETRACKER_ZONE_NAME] = self._devicetracker_zone_name
        if self._home_zone is not None:
            return_attr[ATTR_HOME_ZONE] = self._home_zone
        if self._entity_picture is not None:
            return_attr[ATTR_PICTURE] = self._entity_picture
        if self._distance_km is not None:
            return_attr[ATTR_DISTANCE_KM] = self._distance_km
        if self._distance_m is not None:
            return_attr[ATTR_DISTANCE_M] = self._distance_m
        if self._mtime is not None:
            return_attr[ATTR_MTIME] = self._mtime
        if self._last_place_name is not None:
            return_attr[ATTR_LAST_PLACE_NAME] = self._last_place_name
        if self._location_current is not None:
            return_attr[ATTR_LOCATION_CURRENT] = self._location_current
        if self._location_previous is not None:
            return_attr[ATTR_LOCATION_PREVIOUS] = self._location_previous
        if self._home_latitude is not None:
            return_attr[ATTR_HOME_LATITUDE] = self._home_latitude
        if self._home_longitude is not None:
            return_attr[ATTR_HOME_LONGITUDE] = self._home_longitude
        if self._direction is not None:
            return_attr[ATTR_DIRECTION_OF_TRAVEL] = self._direction
        if self._map_link is not None:
            return_attr[ATTR_MAP_LINK] = self._map_link
        if self._options is not None:
            return_attr[ATTR_OPTIONS] = self._options
        if self._osm_id is not None:
            return_attr[ATTR_OSM_ID] = self._osm_id
        if self._osm_type is not None:
            return_attr[ATTR_OSM_TYPE] = self._osm_type
        if self._wikidata_id is not None:
            return_attr[ATTR_WIKIDATA_ID] = self._wikidata_id
        if self._osm_dict is not None:
            return_attr[ATTR_OSM_DICT] = self._osm_dict
        if self._osm_details_dict is not None:
            return_attr[ATTR_OSM_DETAILS_DICT] = self._osm_details_dict
        if self._wikidata_dict is not None:
            return_attr[ATTR_WIKIDATA_DICT] = self._wikidata_dict
        # _LOGGER.debug("(" + self._name + ") Extra State Attributes - " + return_attr)
        return return_attr

    def is_devicetracker_set(self):
        # _LOGGER.debug(
        #    "(" + self._name + ") DeviceTracker Entity ID: " + self._devicetracker_id
        # )
        # _LOGGER.debug(
        #    "("
        #    + self._name
        #    + ") DeviceTracker Attribute Exists: "
        #    + str(hasattr(self, "_devicetracker_id"))
        # )
        # _LOGGER.debug(
        #    "("
        #    + self._name
        #    + ") DeviceTracker Entity: "
        #    + str(self._hass.states.get(self._devicetracker_id))
        # )
        _LOGGER.debug(
            "("
            + self._name
            + ") [is_devicetracker_set] DeviceTracker State: "
            + str(
                self._hass.states.get(self._devicetracker_id).state
                if self._hass.states.get(self._devicetracker_id) is not None
                else None
            )
        )

        if (
            hasattr(self, "_devicetracker_id")
            and self._hass.states.get(self._devicetracker_id) is not None
            and self._hass.states.get(self._devicetracker_id).state.lower() != "notset"
        ):
            return True
        else:
            return False

    def tsc_update(self, tscarg2, tsarg3, tsarg4):
        """Call the do_update function based on the TSC (track state change) event"""
        if self.is_devicetracker_set():
            _LOGGER.debug(
                "("
                + self._name
                + ") [TSC Update] Running Update - Devicetracker is set"
            )
            self.do_update("Track State Change")
        else:
            _LOGGER.debug(
                "("
                + self._name
                + ") [TSC Update] Not Running Update - Devicetracker is not set"
            )

    @Throttle(THROTTLE_INTERVAL)
    async def async_update(self):
        """Call the do_update function based on scan interval and throttle"""
        if self.is_devicetracker_set():
            _LOGGER.debug(
                "("
                + self._name
                + ") [Async Update] Running Update - Devicetracker is set"
            )
            # await self._hass.async_add_executor_job(self.do_update("Scan Interval"))
            self.do_update("Scan Interval")
        else:
            _LOGGER.debug(
                "("
                + self._name
                + ") [Async Update] Not Running Update - Devicetracker is not set"
            )

    def haversine(self, lon1, lat1, lon2, lat2):
        """
        Calculate the great circle distance between two points
        on the earth (specified in decimal degrees)
        """
        # convert decimal degrees to radians
        lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])

        # haversine formula
        dlon = lon2 - lon1
        dlat = lat2 - lat1
        a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
        c = 2 * asin(sqrt(a))
        r = 6371  # Radius of earth in kilometers. Use 3956 for miles
        return c * r

    def is_float(self, value):
        try:
            float(value)
            return True
        except ValueError:
            return False

    def in_zone(self):
        if (
            "stationary" in self._devicetracker_zone.lower()
            or self._devicetracker_zone.lower() == "away"
            or self._devicetracker_zone.lower() == "not_home"
            or self._devicetracker_zone.lower() == "notset"
        ):
            return False
        else:
            return True

    def do_update(self, reason):
        """Get the latest data and updates the states."""

        _LOGGER.info("(" + self._name + ") Starting Update...")
        previous_state = self._state
        new_state = None
        distance_traveled = 0
        devicetracker_zone = None
        devicetracker_zone_id = None
        devicetracker_zone_name_state = None
        home_latitude = None
        home_longitude = None
        last_distance_m = None
        last_updated = None
        current_location = None
        previous_location = None
        home_location = None
        maplink_apple = None
        maplink_google = None
        maplink_osm = None
        last_place_name = None
        prev_last_place_name = None

        _LOGGER.info("(" + self._name + ") Calling update due to " + str(reason))
        if hasattr(self, "entity_id") and self.entity_id is not None:
            # _LOGGER.debug("(" + self._name + ") Entity ID: " + str(self.entity_id))
            # _LOGGER.debug(
            #    "("
            #    + self._name
            #    + ") Entity Data: "
            #    + str(self._hass.states.get(str(self.entity_id)))
            # )
            if self._hass.states.get(str(self.entity_id)).attributes.get(
                CONF_FRIENDLY_NAME
            ) is not None and self._name != self._hass.states.get(
                str(self.entity_id)
            ).attributes.get(
                CONF_FRIENDLY_NAME
            ):
                _LOGGER.debug(
                    "("
                    + self._name
                    + ") Updating Name to: "
                    + str(
                        self._hass.states.get(str(self.entity_id)).attributes.get(
                            CONF_FRIENDLY_NAME
                        )
                    )
                )
                self._name = self._hass.states.get(str(self.entity_id)).attributes.get(
                    CONF_FRIENDLY_NAME
                )
            if self._name != self._config[CONF_NAME]:

                _LOGGER.debug(
                    "("
                    + self._name
                    + ") Updating Config Name: Old: "
                    + str(self._config[CONF_NAME])
                    + ", New: "
                    + self._name
                )
                self._config[CONF_NAME] = self._name

        _LOGGER.info(
            "(" + self._name + ") Check if update req'd: " + str(self._devicetracker_id)
        )
        _LOGGER.debug("(" + self._name + ") Previous State: " + str(previous_state))

        # Can remove this 'if' now since we are checking before calling do_update
        # if (
        #    hasattr(self, "_devicetracker_id")
        #    and self._hass.states.get(self._devicetracker_id) is not None
        # ):
        now = datetime.now()
        old_latitude = str(self._latitude)
        if not self.is_float(old_latitude):
            old_latitude = None
        old_longitude = str(self._longitude)
        if not self.is_float(old_latitude):
            old_latitude = None
        new_latitude = str(
            self._hass.states.get(self._devicetracker_id).attributes.get("latitude")
        )
        if not self.is_float(new_latitude):
            new_latitude = None
        new_longitude = str(
            self._hass.states.get(self._devicetracker_id).attributes.get("longitude")
        )
        if not self.is_float(new_longitude):
            new_longitude = None
        home_latitude = str(self._home_latitude)
        if not self.is_float(home_latitude):
            home_latitude = None
        home_longitude = str(self._home_longitude)
        if not self.is_float(home_longitude):
            home_longitude = None
        last_distance_m = self._distance_m
        last_updated = self._mtime
        current_location = new_latitude + "," + new_longitude
        previous_location = old_latitude + "," + old_longitude
        home_location = home_latitude + "," + home_longitude
        prev_last_place_name = self._last_place_name
        _LOGGER.debug(
            "("
            + self._name
            + ") Previous last_place_name: "
            + str(self._last_place_name)
        )

        if not self.in_zone():
            # Not in a Zone
            if self._place_name is not None and self._place_name != "-":
                # If place name is set
                last_place_name = self._place_name
                _LOGGER.debug(
                    "("
                    + self._name
                    + ") Previous Place Name is set: "
                    + str(last_place_name)
                )
            else:
                # If blank, keep previous last place name
                last_place_name = self._last_place_name
                _LOGGER.debug(
                    "(" + self._name + ") Previous Place Name is None, keeping prior"
                )
        else:
            # In a Zone
            last_place_name = self._devicetracker_zone_name
            _LOGGER.debug(
                "(" + self._name + ") Previous Place is Zone: " + str(last_place_name)
            )
        _LOGGER.debug(
            "(" + self._name + ") Last Place Name (Initial): " + str(last_place_name)
        )

        maplink_apple = (
            "https://maps.apple.com/maps/?q="
            + str(current_location)
            + "&z="
            + str(self._map_zoom)
        )
        # maplink_google = 'https://www.google.com/maps/dir/?api=1&origin=' + current_location + '&destination=' + home_location + '&travelmode=driving&layer=traffic'
        maplink_google = (
            "https://www.google.com/maps/search/?api=1&basemap=roadmap&layer=traffic&query="
            + str(current_location)
        )
        maplink_osm = (
            "https://www.openstreetmap.org/?mlat="
            + str(new_latitude)
            + "&mlon="
            + str(new_longitude)
            + "#map="
            + str(self._map_zoom)
            + "/"
            + str(new_latitude)[:8]
            + "/"
            + str(new_longitude)[:9]
        )
        if (
            new_latitude is not None
            and new_longitude is not None
            and home_latitude is not None
            and home_longitude is not None
        ):
            distance_m = distance(
                float(new_latitude),
                float(new_longitude),
                float(home_latitude),
                float(home_longitude),
            )
            distance_km = round(distance_m / 1000, 3)

            deviation = self.haversine(
                float(old_latitude),
                float(old_longitude),
                float(new_latitude),
                float(new_longitude),
            )
            if deviation <= 0.2:  # in kilometers
                direction = "stationary"
            elif last_distance_m > distance_m:
                direction = "towards home"
            elif last_distance_m < distance_m:
                direction = "away from home"
            else:
                direction = "stationary"

            _LOGGER.debug(
                "(" + self._name + ") Previous Location: " + str(previous_location)
            )
            _LOGGER.debug(
                "(" + self._name + ") Current Location: " + str(current_location)
            )
            _LOGGER.debug("(" + self._name + ") Home Location: " + str(home_location))
            _LOGGER.info(
                "("
                + self._name
                + ") Distance from home ["
                + (self._home_zone).split(".")[1]
                + "]: "
                + str(distance_km)
                + " km"
            )
            _LOGGER.info("(" + self._name + ") Travel Direction: " + str(direction))

            """Update if location has changed."""

            devicetracker_zone = self._hass.states.get(self._devicetracker_id).state
            _LOGGER.info(
                "(" + self._name + ") DeviceTracker Zone: " + str(devicetracker_zone)
            )

            devicetracker_zone_id = self._hass.states.get(
                self._devicetracker_id
            ).attributes.get("zone")
            if devicetracker_zone_id is not None:
                devicetracker_zone_id = "zone." + str(devicetracker_zone_id)
                devicetracker_zone_name_state = self._hass.states.get(
                    devicetracker_zone_id
                )
            if devicetracker_zone_name_state is not None:
                devicetracker_zone_name = devicetracker_zone_name_state.name
            else:
                devicetracker_zone_name = devicetracker_zone
            _LOGGER.debug(
                "("
                + self._name
                + ") DeviceTracker Zone Name: "
                + str(devicetracker_zone_name)
            )

            distance_traveled = distance(
                float(new_latitude),
                float(new_longitude),
                float(old_latitude),
                float(old_longitude),
            )

            _LOGGER.info(
                "("
                + self._name
                + ") Meters traveled since last update: "
                + str(round(distance_traveled, 1))
            )
        else:
            _LOGGER.error(
                "("
                + self._name
                + ") Problem with updated lat/long, this will likely error: new_latitude="
                + str(new_latitude)
                + ", new_longitude="
                + str(new_longitude)
                + ", home_latitude="
                + str(home_latitude)
                + ", home_longitude="
                + str(home_longitude)
            )
        # else:
        #    _LOGGER.error(
        #        "(" + self._name + ") Missing _devicetracker_id, this will likely error"
        #    )

        proceed_with_update = True
        initial_update = False

        if current_location == previous_location:
            _LOGGER.debug(
                "(" + self._name + ") Stopping update because coordinates are identical"
            )
            proceed_with_update = False
        elif int(distance_traveled) > 0 and self._updateskipped > 3:
            proceed_with_update = True
            _LOGGER.debug(
                "("
                + self._name
                + ") Allowing update after 3 skips even with distance traveled < 10m"
            )
        elif int(distance_traveled) < 10:
            self._updateskipped = self._updateskipped + 1
            _LOGGER.debug(
                "("
                + self._name
                + ") Stopping update because location changed "
                + str(round(distance_traveled, 1))
                + " < 10m  ("
                + str(self._updateskipped)
                + ")"
            )
            proceed_with_update = False

        if previous_state == "Initializing...":
            _LOGGER.debug("(" + self._name + ") Performing Initial Update for user...")
            proceed_with_update = True
            initial_update = True

        if proceed_with_update and devicetracker_zone:
            _LOGGER.debug(
                "("
                + self._name
                + ") Meets criteria, proceeding with OpenStreetMap query"
            )
            self._devicetracker_zone = devicetracker_zone
            _LOGGER.info(
                "("
                + self._name
                + ") DeviceTracker Zone (current): "
                + str(self._devicetracker_zone)
                + " / Skipped Updates: "
                + str(self._updateskipped)
            )

            self._reset_attributes()

            self._latitude = new_latitude
            self._longitude = new_longitude
            self._latitude_old = old_latitude
            self._longitude_old = old_longitude
            self._location_current = current_location
            self._location_previous = previous_location
            self._devicetracker_zone = devicetracker_zone
            self._devicetracker_zone_name = devicetracker_zone_name
            self._distance_km = distance_km
            self._distance_m = distance_m
            self._direction = direction

            if self._map_provider == "google":
                self._map_link = maplink_google
            elif self._map_provider == "osm":
                self._map_link = maplink_osm
            else:
                self._map_link = maplink_apple
            _LOGGER.debug(
                "(" + self._name + ") Map Link Type: " + str(self._map_provider)
            )
            _LOGGER.debug(
                "(" + self._name + ") Map Link generated: " + str(self._map_link)
            )

            # Change logic and default_key for api-Key
            osm_url = (
                "https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat="
                + str(self._latitude)
                + "&lon="
                + str(self._longitude)
                + (
                    "&accept-language=" + str(self._language)
                    if self._language != DEFAULT_LANGUAGE
                    else ""
                )
                + "&addressdetails=1&namedetails=1&zoom=18&limit=1"
                + (
                    "&email=" + str(self._api_key)
                    if self._api_key != DEFAULT_KEY
                    else ""
                )
            )

            osm_decoded = {}
            _LOGGER.info(
                "("
                + self._name
                + ") OpenStreetMap Request: lat="
                + str(self._latitude)
                + " and lon="
                + str(self._longitude)
            )
            _LOGGER.debug("(" + self._name + ") OSM URL: " + str(osm_url))
            osm_response = get(osm_url)
            osm_json_input = osm_response.text
            _LOGGER.debug("(" + self._name + ") OSM Response: " + osm_json_input)
            osm_decoded = json.loads(osm_json_input)

            place_options = self._options.lower()
            place_type = None
            place_name = None
            place_category = None
            place_neighbourhood = None
            street_number = None
            street = None
            city = None
            postal_town = None
            region = None
            state_abbr = None
            county = None
            country = None
            postal_code = None
            formatted_address = None
            target_option = None
            formatted_place = None
            osm_id = None
            osm_type = None
            wikidata_id = None

            if "place" in self._options:
                place_type = osm_decoded["type"]
                if place_type == "yes":
                    place_type = osm_decoded["addresstype"]
                if place_type in osm_decoded["address"]:
                    place_name = osm_decoded["address"][place_type]
                if "category" in osm_decoded:
                    place_category = osm_decoded["category"]
                    if place_category in osm_decoded["address"]:
                        place_name = osm_decoded["address"][place_category]
                if "name" in osm_decoded["namedetails"]:
                    place_name = osm_decoded["namedetails"]["name"]
                for language in self._language.split(","):
                    if "name:" + language in osm_decoded["namedetails"]:
                        place_name = osm_decoded["namedetails"]["name:" + language]
                        break
                if not self.in_zone() and place_name != "house":
                    new_state = place_name

            if "house_number" in osm_decoded["address"]:
                street_number = osm_decoded["address"]["house_number"]
            if "road" in osm_decoded["address"]:
                street = osm_decoded["address"]["road"]

            if "neighbourhood" in osm_decoded["address"]:
                place_neighbourhood = osm_decoded["address"]["neighbourhood"]
            elif "hamlet" in osm_decoded["address"]:
                place_neighbourhood = osm_decoded["address"]["hamlet"]

            if "city" in osm_decoded["address"]:
                city = osm_decoded["address"]["city"]
            elif "town" in osm_decoded["address"]:
                city = osm_decoded["address"]["town"]
            elif "village" in osm_decoded["address"]:
                city = osm_decoded["address"]["village"]
            elif "township" in osm_decoded["address"]:
                city = osm_decoded["address"]["township"]
            elif "municipality" in osm_decoded["address"]:
                city = osm_decoded["address"]["municipality"]
            elif "city_district" in osm_decoded["address"]:
                city = osm_decoded["address"]["city_district"]
            if city is not None and city.startswith("City of"):
                city = city[8:] + " City"

            if "city_district" in osm_decoded["address"]:
                postal_town = osm_decoded["address"]["city_district"]
            if "suburb" in osm_decoded["address"]:
                postal_town = osm_decoded["address"]["suburb"]
            if "state" in osm_decoded["address"]:
                region = osm_decoded["address"]["state"]
            if "ISO3166-2-lvl4" in osm_decoded["address"]:
                state_abbr = (
                    osm_decoded["address"]["ISO3166-2-lvl4"].split("-")[1].upper()
                )
            if "county" in osm_decoded["address"]:
                county = osm_decoded["address"]["county"]
            if "country" in osm_decoded["address"]:
                country = osm_decoded["address"]["country"]
            if "postcode" in osm_decoded["address"]:
                postal_code = osm_decoded["address"]["postcode"]
            if "display_name" in osm_decoded:
                formatted_address = osm_decoded["display_name"]

            if "osm_id" in osm_decoded:
                osm_id = str(osm_decoded["osm_id"])
            if "osm_type" in osm_decoded:
                osm_type = osm_decoded["osm_type"]

            self._place_type = place_type
            self._place_category = place_category
            self._place_neighbourhood = place_neighbourhood
            self._place_name = place_name

            self._street_number = street_number
            self._street = street
            self._city = city
            self._postal_town = postal_town
            self._region = region
            self._state_abbr = state_abbr
            self._county = county
            self._country = country
            self._postal_code = postal_code
            self._formatted_address = formatted_address
            self._mtime = str(datetime.now())
            if osm_id is not None:
                self._osm_id = str(osm_id)
            self._osm_type = osm_type
            if initial_update is True:
                last_place_name = self._last_place_name
                _LOGGER.debug(
                    "("
                    + self._name
                    + ") Runnining initial update after load, using prior last_place_name"
                )
            elif (
                last_place_name == place_name
                or last_place_name == devicetracker_zone_name
            ):
                # If current place name/zone are the same as previous, keep older last place name
                last_place_name = self._last_place_name
                _LOGGER.debug(
                    "("
                    + self._name
                    + ") Initial last_place_name is same as new: place_name="
                    + str(place_name)
                    + " or devicetracker_zone_name="
                    + str(devicetracker_zone_name)
                    + ", keeping previous last_place_name"
                )
            else:
                _LOGGER.debug("(" + self._name + ") Keeping initial last_place_name")
            self._last_place_name = last_place_name
            _LOGGER.debug(
                "(" + self._name + ") Last Place Name (Final): " + str(last_place_name)
            )

            isDriving = False

            display_options = []
            options_array = self._options.split(",")
            for option in options_array:
                display_options.append(option.strip())

            # Formatted Place
            formatted_place_array = []
            if not self.in_zone():
                if (
                    self._direction != "stationary"
                    and (
                        self._place_category == "highway"
                        or self._place_type == "motorway"
                    )
                    and "driving" in display_options
                ):
                    formatted_place_array.append("Driving")
                    isDriving = True
                if self._place_name is None:
                    if (
                        self._place_type is not None
                        and self._place_type.lower() != "unclassified"
                        and self._place_category.lower() != "highway"
                    ):
                        formatted_place_array.append(
                            self._place_type.title()
                            .replace("Proposed", "")
                            .replace("Construction", "")
                            .strip()
                        )
                    elif (
                        self._place_category is not None
                        and self._place_category.lower() != "highway"
                    ):
                        formatted_place_array.append(
                            self._place_category.title().strip()
                        )
                    if self._street is not None:
                        if self._street_number is None:
                            formatted_place_array.append(self._street.strip())
                        else:
                            formatted_place_array.append(
                                self._street_number.strip() + " " + self._street.strip()
                            )
                    if (
                        self._place_type.lower() == "house"
                        and self._place_neighbourhood is not None
                    ):
                        formatted_place_array.append(self._place_neighbourhood.strip())

                else:
                    formatted_place_array.append(self._place_name.strip())
                if self._city is not None:
                    formatted_place_array.append(
                        self._city.replace(" Township", "").strip()
                    )
                elif self._county is not None:
                    formatted_place_array.append(self._county.strip())
                if self._state_abbr is not None:
                    formatted_place_array.append(self._state_abbr)
            else:
                formatted_place_array.append(devicetracker_zone_name.strip())
            formatted_place = ", ".join(item for item in formatted_place_array)
            formatted_place = (
                formatted_place.replace("\n", " ").replace("  ", " ").strip()
            )
            self._formatted_place = formatted_place

            if "error_message" in osm_decoded:
                new_state = osm_decoded["error_message"]
                _LOGGER.warning(
                    "("
                    + self._name
                    + ") An error occurred contacting the web service for OpenStreetMap"
                )
            elif "formatted_place" in display_options:
                new_state = self._formatted_place
                _LOGGER.info(
                    "("
                    + self._name
                    + ") New State using formatted_place: "
                    + str(new_state)
                )
            elif not self.in_zone():

                # Options:  "formatted_place, zone, zone_name, place, street_number, street, city, county, state, postal_code, country, formatted_address"

                _LOGGER.debug(
                    "("
                    + self._name
                    + ") Building State from Display Options: "
                    + str(self._options)
                )

                user_display = []

                if "driving" in display_options and isDriving:
                    user_display.append("Driving")

                if (
                    "zone_name" in display_options
                    and "do_not_show_not_home" not in display_options
                    and self._devicetracker_zone_name is not None
                ):
                    # zone = self._devicetracker_zone
                    user_display.append(self._devicetracker_zone_name)
                elif (
                    "zone" in display_options
                    and "do_not_show_not_home" not in display_options
                    and self._devicetracker_zone is not None
                ):
                    # zone = self._devicetracker_zone
                    user_display.append(self._devicetracker_zone)

                if "place_name" in display_options and place_name is not None:
                    user_display.append(place_name)
                if "place" in display_options:
                    if place_name is not None:
                        user_display.append(place_name)
                    if place_category is not None and place_category.lower() != "place":
                        user_display.append(place_category)
                    if place_type is not None and place_type.lower() != "yes":
                        user_display.append(place_type)
                    if place_neighbourhood is not None:
                        user_display.append(place_neighbourhood)
                    if street_number is not None:
                        user_display.append(street_number)
                    if street is not None:
                        user_display.append(street)
                else:
                    if "street_number" in display_options and street_number is not None:
                        user_display.append(street_number)
                    if "street" in display_options and street is not None:
                        user_display.append(street)
                if "city" in display_options and self._city is not None:
                    user_display.append(self._city)
                if "county" in display_options and self._county is not None:
                    user_display.append(self._county)
                if "state" in display_options and self._region is not None:
                    user_display.append(self._region)
                elif "region" in display_options and self._region is not None:
                    user_display.append(self._region)
                if "postal_code" in display_options and self._postal_code is not None:
                    user_display.append(self._postal_code)
                if "country" in display_options and self._country is not None:
                    user_display.append(self._country)
                if (
                    "formatted_address" in display_options
                    and self._formatted_address is not None
                ):
                    user_display.append(self._formatted_address)

                if "do_not_reorder" in display_options:
                    user_display = []
                    display_options.remove("do_not_reorder")
                    for option in display_options:
                        if option == "state":
                            target_option = "region"
                        if option == "place_neighborhood":
                            target_option = "place_neighbourhood"
                        if option in locals():
                            user_display.append(target_option)

                if user_display:
                    new_state = ", ".join(item for item in user_display)
                _LOGGER.debug(
                    "("
                    + self._name
                    + ") New State from Display Options: "
                    + str(new_state)
                )
            elif (
                "zone_name" in display_options
                and self._devicetracker_zone_name is not None
            ):
                new_state = self._devicetracker_zone_name
                _LOGGER.debug(
                    "("
                    + self._name
                    + ") New State from DeviceTracker Zone Name: "
                    + str(new_state)
                )
            elif self._devicetracker_zone is not None:
                new_state = devicetracker_zone
                _LOGGER.debug(
                    "("
                    + self._name
                    + ") New State from DeviceTracker Zone: "
                    + str(new_state)
                )

            if self._extended_attr:
                self._osm_dict = osm_decoded
            current_time = "%02d:%02d" % (now.hour, now.minute)

            if (
                previous_state.lower().strip() != new_state.lower().strip()
                and previous_state.replace(" ", "").lower().strip()
                != new_state.lower().strip()
                and previous_state.lower().strip() != devicetracker_zone.lower().strip()
            ) or previous_state.strip() == "Initializing...":

                if self._extended_attr:
                    osm_details_dict = {}
                    if osm_id is not None and osm_type is not None:
                        if osm_type.lower() == "node":
                            osm_type_abbr = "N"
                        elif osm_type.lower() == "way":
                            osm_type_abbr = "W"
                        elif osm_type.lower() == "relation":
                            osm_type_abbr = "R"

                        osm_details_url = (
                            "https://nominatim.openstreetmap.org/details.php?osmtype="
                            + str(osm_type_abbr)
                            + "&osmid="
                            + str(osm_id)
                            + "&linkedplaces=1&hierarchy=1&group_hierarchy=1&limit=1&format=json"
                            + (
                                "&email=" + str(self._api_key)
                                if self._api_key != DEFAULT_KEY
                                else ""
                            )
                        )

                        _LOGGER.info(
                            "("
                            + self._name
                            + ") OpenStreetMap Details Request: type="
                            + str(osm_type)
                            + " ("
                            + str(osm_type_abbr)
                            + ") and id="
                            + str(osm_id)
                        )
                        _LOGGER.debug(
                            "("
                            + self._name
                            + ") OSM Details URL: "
                            + str(osm_details_url)
                        )
                        osm_details_response = get(osm_details_url)
                        if "error_message" in osm_details_response:
                            osm_details_dict = osm_details_response["error_message"]
                            _LOGGER.info(
                                "("
                                + self._name
                                + ") An error occurred contacting the web service for OSM Details"
                            )
                        else:
                            osm_details_json_input = osm_details_response.text
                            osm_details_dict = json.loads(osm_details_json_input)
                            _LOGGER.debug(
                                "("
                                + self._name
                                + ") OSM Details JSON: "
                                + osm_details_json_input
                            )
                            # _LOGGER.debug("(" + self._name + ") OSM Details Dict: " + str(osm_details_dict))
                            self._osm_details_dict = osm_details_dict

                            if (
                                "extratags" in osm_details_dict
                                and "wikidata" in osm_details_dict["extratags"]
                            ):
                                wikidata_id = osm_details_dict["extratags"]["wikidata"]
                            self._wikidata_id = wikidata_id

                            wikidata_dict = {}
                            if wikidata_id is not None:
                                wikidata_url = (
                                    "https://www.wikidata.org/wiki/Special:EntityData/"
                                    + str(wikidata_id)
                                    + ".json"
                                )

                                _LOGGER.info(
                                    "("
                                    + self._name
                                    + ") Wikidata Request: id="
                                    + str(wikidata_id)
                                )
                                _LOGGER.debug(
                                    "("
                                    + self._name
                                    + ") Wikidata URL: "
                                    + str(wikidata_url)
                                )
                                wikidata_response = get(wikidata_url)
                                if "error_message" in wikidata_response:
                                    wikidata_dict = wikidata_response["error_message"]
                                    _LOGGER.info(
                                        "("
                                        + self._name
                                        + ") An error occurred contacting the web service for Wikidata"
                                    )
                                else:
                                    wikidata_json_input = wikidata_response.text
                                    wikidata_dict = json.loads(wikidata_json_input)
                                    _LOGGER.debug(
                                        "("
                                        + self._name
                                        + ") Wikidata JSON: "
                                        + wikidata_json_input
                                    )
                                    # _LOGGER.debug(
                                    #    "("
                                    #    + self._name
                                    #    + ") Wikidata Dict: "
                                    #    + str(wikidata_dict)
                                    # )
                                    self._wikidata_dict = wikidata_dict
                if new_state is not None:
                    _LOGGER.debug(
                        "(" + self._name + ") New State (Final): " + str(new_state)
                    )
                    self._state = new_state[:255]
                else:
                    self._state = "<Unknown>"
                    _LOGGER.warning(
                        "("
                        + self._name
                        + ") New State is None, setting to: "
                        + str(self._state)
                    )
                _LOGGER.debug("(" + self._name + ") Building EventData")
                event_data = {}
                event_data["entity"] = self._name
                event_data["from_state"] = previous_state
                event_data["to_state"] = new_state

                if place_name is not None:
                    event_data[ATTR_PLACE_NAME] = place_name
                if current_time is not None:
                    event_data[ATTR_MTIME] = current_time
                if (
                    last_place_name is not None
                    and last_place_name != prev_last_place_name
                ):
                    event_data[ATTR_LAST_PLACE_NAME] = last_place_name
                if distance_km is not None:
                    event_data[ATTR_DISTANCE_KM] = distance_km
                if distance_m is not None:
                    event_data[ATTR_DISTANCE_M] = distance_m
                if direction is not None:
                    event_data[ATTR_DIRECTION_OF_TRAVEL] = direction
                if devicetracker_zone is not None:
                    event_data[ATTR_DEVICETRACKER_ZONE] = devicetracker_zone
                if devicetracker_zone_name is not None:
                    event_data[ATTR_DEVICETRACKER_ZONE_NAME] = devicetracker_zone_name
                if self._latitude is not None:
                    event_data[ATTR_LATITUDE] = self._latitude
                if self._longitude is not None:
                    event_data[ATTR_LONGITUDE] = self._longitude
                if self._latitude_old is not None:
                    event_data[ATTR_LATITUDE_OLD] = self._latitude_old
                if self._longitude_old is not None:
                    event_data[ATTR_LONGITUDE_OLD] = self._longitude_old
                if self._map_link is not None:
                    event_data[ATTR_MAP_LINK] = self._map_link
                if osm_id is not None:
                    event_data[ATTR_OSM_ID] = osm_id
                if osm_type is not None:
                    event_data[ATTR_OSM_TYPE] = osm_type
                if self._extended_attr:
                    if wikidata_id is not None:
                        event_data[ATTR_WIKIDATA_ID] = wikidata_id
                    if osm_decoded is not None:
                        event_data[ATTR_OSM_DICT] = osm_decoded
                    if osm_details_dict is not None:
                        event_data[ATTR_OSM_DETAILS_DICT] = osm_details_dict
                    if wikidata_dict is not None:
                        event_data[ATTR_WIKIDATA_DICT] = wikidata_dict
                self._hass.bus.fire(DOMAIN + "_state_update", event_data)
                _LOGGER.debug(
                    "("
                    + self._name
                    + ") Event Fired [event_type: "
                    + DOMAIN
                    + "_state_update]: "
                    + str(event_data)
                )
            else:
                _LOGGER.debug(
                    "("
                    + self._name
                    + ") No entity update needed, Previous State = New State"
                )
        _LOGGER.info("(" + self._name + ") End of Update")

    def _reset_attributes(self):
        """Resets attributes."""
        self._street = None
        self._street_number = None
        self._city = None
        self._postal_town = None
        self._postal_code = None
        self._region = None
        self._state_abbr = None
        self._country = None
        self._county = None
        self._formatted_address = None
        self._place_type = None
        self._place_name = None
        self._mtime = datetime.now()
        # self._last_place_name = None
        self._osm_id = None
        self._osm_type = None
        self._wikidata_id = None
        self._osm_dict = None
        self._osm_details_dict = None
        self._wikidata_dict = None
        self._updateskipped = 0

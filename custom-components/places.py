"""
Place Support for OpenStreetMap Geocode sensors.

Original Author:  Jim Thompson

Current Version:  1.2  20180510 - Jim Thompson

20180330 - Initial Release
         - Event driven and timed updates
         - Subscribes to DeviceTracker state update events
         - State display options are (default "zone, place"):
           "zone, place, street_number, street, city, county, state, postal_code, country, formatted_address"
         - If state display options are specified in the configuration.yaml file:
           - The state display string begins as a null and appends the following in order:
             - 'zone' - as defined in the device_tracker entity
             - If 'place' is included in the options string, a concatenated string is created with the following attributes
               - place_name, 
               - place_category, 
               - place_type, 
               - place_neighbourhood, 
               - street number, 
               - street
               - If 'street_number' and 'street' are also in the options string, they are ignored
             - If 'place' is NOT included:
               - If 'street_number' is included in the options string, the 'street number' will be appended to the display string
               - If 'street' is included in the options string, the 'street name' will be appended to the display string
            - If specified in the options string, the following attributes are also appended in order:
              - "city"
              - "county"
              - "state'
              - "postal_code"
              - "country"
              - "formatted_address"
           - If for some reason the option string is null at this point, the following values are concatenated:
             - "zone"
             - "street"
             - "city"
         - Whenever the actual 'state' changes, this sensor fires a custom event named 'places_state_update' containing:
           - entity
           - to_state
           - from_state
           - place_name
           - direction
           - distance_from_home
           - devicetracker_zone
           - latitude
           - longitude
         - Added Map_link option to generate a Google or Apple Maps link to the users current location
20180509 - Updated to support new option value of "do_not_reorder" to disable the automatic ordered display of any specified options
         - If "do_not_reorder" appears anywhere in the list of comma delimited options, the state display will be built 
           using the order of options as they are specified in the options config value.
           ie:  options: street, street_number, do_not_reorder, postal_code, city, country 
           will result in a state comprised of: 
                <street>, <street_number>, <postal_code>, <city>, <country> 
           without the "do_not_reorder" option, it would be:
                <street_number>, <street>, <postal_code>, <city>, <country>
         - The following attributes can be specified in any order for building the display string manually:
            - do_not_reorder
            - place_type, place_name, place_category, place_neighbourhood, street_number, street, city,
            - postal_town, state, region, county, country, postal_code, formatted_address
            Notes:  All options must be specified in lower case.  
                    State and Region return the same data (so only use one of them).
         - Also added 'options' to the attribute list that gets populated by this sensor (to make it easier to see why a specific state is being generated)
20180510 - Fixed stupid bug introduced yesterday.  Converted display options from string to list.

           
Description:
  Provides a sensor with a variable state consisting of reverse geocode (place) details for a linked device_tracker entity that provides GPS co-ordinates (ie owntracks, icloud)
  Optionally allows you to specify a 'home_zone' for each device and calculates distance from home and direction of travel.
  The displayed state adds a time stamp "(since hh:mm)" so you can tell how long a person has been at a location.
  Configuration Instructions are below - as well as sample automations for notifications.
  
  The display options I have set for Sharon are "zone, place" so her state is displayed as:
  - not_home, Richmond Hill GO Station, building, building, Beverley Acres, 6, Newkirk Road (since 18:44)
  There are a lot of additional attributes (beyond state) that are available which can be used in notifications, alerts, etc:
  (The "home latitude/longitudes" below have been randomized to protect her privacy)
{
  "formatted_address": "Richmond Hill GO Station, 6, Newkirk Road, Beverley Acres, Richmond Hill, York Region, Ontario, L4C 1B3, Canada",
  "friendly_name": "sharon",
  "postal_town": "-",
  "current_latitude": "43.874149009154095",
  "distance_from_home_km": "7.24 km",
  "country": "Canada",
  "postal_code": "L4C 1B3",
  "direction_of_travel": "towards home",
  "neighbourhood": "Beverley Acres",
  "entity_picture": "/local/sharon.png",
  "street_number": "6",
  "devicetracker_entityid": "device_tracker.sharon_iphone7",
  "home_longitude": "-79.7323453871",
  "devicetracker_zone": "not_home",
  "distance_from_home_m": 17239.053,
  "home_latitude": "43.983234888",
  "previous_location": "43.86684124904056,-79.4253896502715",
  "previous_longitude": "-79.4253896502715",
  "place_category": "building",
  "map_link": "https://maps.apple.com/maps/?ll=43.874149009154095,-79.42642783709209&z=18",
  "last_changed": "2018-05-02 13:44:51.019837",
  "state_province": "Ontario",
  "county": "York Region",
  "current_longitude": "-79.42642783709209",
  "current_location": "43.874149009154095,-79.42642783709209",
  "place_type": "building",
  "previous_latitude": "43.86684124904056",
  "place_name": "Richmond Hill GO Station",
  "street": "Newkirk Road",
  "city": "Richmond Hill",
  "home_zone": "zone.sharon_home"
}

Note:  The Google Map Link for above location would have been:
       https://www.google.com/maps/search/?api=1&basemap=roadmap&layer=traffic&query=43.874149009154095,-79.42642783709209

Sample Configuration.yaml configurations:
sensor places_jim:
  - platform: places
    name: jim
    devicetracker_id: device_tracker.jim_iphone8
    options: zone,place
    display_zone: show
    map_provider: google
    map_zoom: 19
    home_zone: zone.jim_home
    api_key: !secret email_jim

sensor places_sharon:
  - platform: places
    name: sharon
    devicetracker_id: device_tracker.sharon_iphone7
    options: zone, place
    map_provider: apple
    map_zoom: 18
    home_zone: zone.sharon_home
    api_key: !secret email_sharon

sensor places_aidan:
  - platform: places
    name: aidan
    devicetracker_id: device_tracker.aidan_iphone7plus
    options: place
    map_provider: google
    map_zoom: 17
    home_zone: zone.aidan_home
    api_key: !secret email_aidan
  
Sample generic automations.yaml snippet to send an iOS notify on any device state change:
(the only difference is the second one uses a condition to only trigger for a specific user)

- alias: ReverseLocateEveryone
  initial_state: 'on'
  trigger:
    platform: event
    event_type: places_state_update
  action:
  - service: notify.ios_jim_iphone8
    data_template:
      title: 'ReverseLocate: {{ trigger.event.data.entity }} ({{ trigger.event.data.devicetracker_zone }}) {{ trigger.event.data.place_name }}'
      message: |-
        {{ trigger.event.data.entity }} ({{ trigger.event.data.devicetracker_zone }}) 
        {{ trigger.event.data.place_name }}
        {{ trigger.event.data.distance_from_home }} from home and traveling {{ trigger.event.data.direction }}
        {{ trigger.event.data.to_state }} ({{ trigger.event.data.mtime }})
      data:
        attachment:
          url: '{{ trigger.event.data.map }}'
          hide_thumbnail: false

- alias: ReverseLocateAidan
  initial_state: 'on'
  trigger:
    platform: event
    event_type: places_state_update
  condition:
    condition: template
    value_template: '{{ trigger.event.data.entity == "aidan" }}'
  action:
  - service: notify.ios_jim_iphone8
    data_template:
      title: 'ReverseLocate: {{ trigger.event.data.entity }} ({{ trigger.event.data.devicetracker_zone }}) {{ trigger.event.data.place_name }}'
      message: |-
        {{ trigger.event.data.entity }} ({{ trigger.event.data.devicetracker_zone }}) 
        {{ trigger.event.data.place_name }}
        {{ trigger.event.data.distance_from_home }} from home and traveling {{ trigger.event.data.direction }}
        {{ trigger.event.data.to_state }} ({{ trigger.event.data.mtime }})
      data:
        attachment:
          url: '{{ trigger.event.data.map }}'
          hide_thumbnail: false


Note:  The OpenStreetMap database is very flexible with regards to tag_names in their
       database schema.  If you come across a set of co-ordinates that do not parse
       properly, you can enable debug messages to see the actual JSON that is returned from the query.

Note:  The OpenStreetMap API requests that you include your valid e-mail address in each API call
       if you are making a large numbers of requests.  They say that this information will be kept
       confidential and only used to contact you in the event of a problem, see their Usage Policy for more details.

Configuration.yaml:
  sensor places_jim:
    - platform: Places
      name: jim                                     (optional)
      devicetracker_id: device_tracker.jim_iphone   (required)
      home_zone: zone.home                          (optional)
      api_key: <email_address>                      (optional)
      map_provider: [google|apple]                  (optional)
      map_zoom: <1-20>                              (optional)
      option: <zone, place, street_number, street, city, county, state, postal_code, country, formatted_address>  (optional)
      
The map link that gets generated for Google maps has a push pin marking the users location.
The map link for Apple maps is centered on the users location - but without any marker.
      
To enable detailed logging for this component, add the following to your configuration.yaml file
  logger:
    default: warn
    logs:
      custom_components.sensor.places: debug  

"""

import logging, json, requests
from datetime import datetime, timedelta
from requests import get

import voluptuous as vol
import homeassistant.helpers.location as location
import homeassistant.helpers.config_validation as cv

from homeassistant.components.sensor import PLATFORM_SCHEMA
from homeassistant.helpers.event import track_state_change
from homeassistant.util import Throttle
from homeassistant.util.location import distance
from homeassistant.helpers.entity import Entity
from homeassistant.const import (
    CONF_API_KEY, CONF_NAME, CONF_SCAN_INTERVAL)

_LOGGER = logging.getLogger(__name__)

DEPENDENCIES = ['zone', 'device_tracker']

CONF_DEVICETRACKER_ID = 'devicetracker_id'
CONF_HOME_ZONE = 'home_zone'
CONF_OPTIONS = 'options'
CONF_MAP_PROVIDER = 'map_provider'
CONF_MAP_ZOOM = 'map_zoom'

ATTR_OPTIONS = 'options'
ATTR_STREET_NUMBER = 'street_number'
ATTR_STREET = 'street'
ATTR_CITY = 'city'
ATTR_POSTAL_TOWN = 'postal_town'
ATTR_POSTAL_CODE = 'postal_code'
ATTR_REGION = 'state_province'
ATTR_COUNTRY = 'country'
ATTR_COUNTY = 'county'
ATTR_FORMATTED_ADDRESS = 'formatted_address'
ATTR_PLACE_TYPE = 'place_type'
ATTR_PLACE_NAME = 'place_name'
ATTR_PLACE_CATEGORY = 'place_category'
ATTR_PLACE_NEIGHBOURHOOD = 'neighbourhood'
ATTR_DEVICETRACKER_ID = 'devicetracker_entityid'
ATTR_DEVICETRACKER_ZONE = 'devicetracker_zone'
ATTR_PICTURE = 'entity_picture'
ATTR_LATITUDE_OLD = 'previous_latitude'
ATTR_LONGITUDE_OLD = 'previous_longitude'
ATTR_LATITUDE = 'current_latitude'
ATTR_LONGITUDE = 'current_longitude'
ATTR_MTIME = 'last_changed'
ATTR_DISTANCE_KM = 'distance_from_home_km'
ATTR_DISTANCE_M = 'distance_from_home_m'
ATTR_HOME_ZONE = 'home_zone'
ATTR_HOME_LATITUDE = 'home_latitude'
ATTR_HOME_LONGITUDE = 'home_longitude'
ATTR_LOCATION_CURRENT = 'current_location'
ATTR_LOCATION_PREVIOUS = 'previous_location'
ATTR_DIRECTION_OF_TRAVEL = 'direction_of_travel'
ATTR_MAP_LINK = 'map_link'

DEFAULT_NAME = 'places'
DEFAULT_OPTION = 'zone, place'
DEFAULT_HOME_ZONE = 'zone.home'
DEFAULT_KEY = "no key"
DEFAULT_MAP_PROVIDER = 'apple'
DEFAULT_MAP_ZOOM = '18'

SCAN_INTERVAL = timedelta(seconds=30)
THROTTLE_INTERVAL = timedelta(seconds=600)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_DEVICETRACKER_ID): cv.string,
    vol.Optional(CONF_API_KEY, default=DEFAULT_KEY): cv.string,
    vol.Optional(CONF_OPTIONS, default=DEFAULT_OPTION): cv.string,
    vol.Optional(CONF_HOME_ZONE, default=DEFAULT_HOME_ZONE): cv.string,
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
    vol.Optional(CONF_MAP_PROVIDER, default=DEFAULT_MAP_PROVIDER): cv.string,
    vol.Optional(CONF_MAP_ZOOM, default=DEFAULT_MAP_ZOOM): cv.string,
    vol.Optional(CONF_SCAN_INTERVAL, default=SCAN_INTERVAL): cv.time_period,
})

TRACKABLE_DOMAINS = ['device_tracker']

def setup_platform(hass, config, add_devices, discovery_info=None):
    """Setup the sensor platform."""
    name = config.get(CONF_NAME)
    api_key = config.get(CONF_API_KEY)
    devicetracker_id = config.get(CONF_DEVICETRACKER_ID)
    options = config.get(CONF_OPTIONS)
    home_zone = config.get(CONF_HOME_ZONE)
    map_provider = config.get(CONF_MAP_PROVIDER)
    map_zoom = config.get(CONF_MAP_ZOOM)

    add_devices([Places(hass, devicetracker_id, name, api_key, options, home_zone, map_provider, map_zoom)])


class Places(Entity):
    """Representation of a Places Sensor."""

    def __init__(self, hass, devicetracker_id, name, api_key, options, home_zone, map_provider, map_zoom):
        """Initialize the sensor."""
        self._hass = hass
        self._name = name
        self._api_key = api_key
        self._options = options.lower()
        self._devicetracker_id = devicetracker_id.lower()
        self._home_zone = home_zone.lower()
        self._map_provider = map_provider.lower()
        self._map_zoom = map_zoom.lower()
        self._state = "Initializing... (since 99:99)"

        home_latitude = str(hass.states.get(home_zone).attributes.get('latitude'))
        home_longitude = str(hass.states.get(home_zone).attributes.get('longitude'))
        self._entity_picture = hass.states.get(devicetracker_id).attributes.get('entity_picture')
        self._street_number = None
        self._street = None
        self._city = None
        self._postal_town = None
        self._postal_code = None
        self._city = None
        self._region = None
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
        self._devicetracker_zone = 'Home'
        self._mtime = str(datetime.now())
        self._distance_km = 0
        self._distance_m = 0
        self._location_current = home_latitude + ',' + home_longitude
        self._location_previous = home_latitude + ',' + home_longitude
        self._updateskipped = 0
        self._direction = 'stationary'
        self._map_link = None
        #'https://www.google.com/maps/@' + home_latitude + "," + home_longitude + ',19z'

        # Check if devicetracker_id was specified correctly
        _LOGGER.info( "(" + self._name + ") DeviceTracker Entity ID is " + devicetracker_id.split('.', 1)[1] )

        if devicetracker_id.split('.', 1)[0] in TRACKABLE_DOMAINS:
            self._devicetracker_id = devicetracker_id
            track_state_change(hass, self._devicetracker_id, self.tsc_update, from_state=None, to_state=None)
            _LOGGER.info( "(" + self._name + ") Now subscribed to state change events from " + self._devicetracker_id )

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    @property
    def entity_picture(self):
        """Return the picture of the device."""
        return self._entity_picture

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        return{
            ATTR_STREET_NUMBER: self._street_number,
            ATTR_STREET: self._street,
            ATTR_CITY: self._city,
            ATTR_POSTAL_TOWN: self._postal_town,
            ATTR_POSTAL_CODE: self._postal_code,
            ATTR_REGION: self._region,
            ATTR_COUNTRY: self._country,
            ATTR_COUNTY: self._county,
            ATTR_FORMATTED_ADDRESS: self._formatted_address,
            ATTR_PLACE_TYPE: self._place_type,
            ATTR_PLACE_NAME: self._place_name,
            ATTR_PLACE_CATEGORY: self._place_category,
            ATTR_PLACE_NEIGHBOURHOOD: self._place_neighbourhood,
            ATTR_LATITUDE_OLD: self._latitude_old,
            ATTR_LONGITUDE_OLD: self._longitude_old,
            ATTR_LATITUDE: self._latitude,
            ATTR_LONGITUDE: self._longitude,
            ATTR_DEVICETRACKER_ID: self._devicetracker_id,
            ATTR_DEVICETRACKER_ZONE: self._devicetracker_zone,
            ATTR_HOME_ZONE: self._home_zone,
            ATTR_PICTURE: self._entity_picture,
            ATTR_DISTANCE_KM: self._distance_km,
            ATTR_DISTANCE_M: self._distance_m,
            ATTR_MTIME: self._mtime,
            ATTR_LOCATION_CURRENT: self._location_current,
            ATTR_LOCATION_PREVIOUS: self._location_previous,
            ATTR_HOME_LATITUDE: self._home_latitude,
            ATTR_HOME_LONGITUDE: self._home_longitude,
            ATTR_DIRECTION_OF_TRAVEL: self._direction,
            ATTR_MAP_LINK: self._map_link,
            ATTR_OPTIONS: self._options
        }


    def tsc_update(self, tscarg2, tsarg3, tsarg4):
        """ Call the do_update function based on the TSC (track state change) event    """
        self.do_update("Track State Change")

    @Throttle(THROTTLE_INTERVAL)
    def update(self):
        """ Call the do_update function based on scan interval and throttle    """
        self.do_update("Scan Interval")

    def do_update(self, reason):
        """Get the latest data and updates the states."""

        previous_state = self.state[:-14]

        _LOGGER.info( "(" + self._name + ") Calling update due to " + reason )
        _LOGGER.info( "(" + self._name + ") Check if update req'd : " + self._devicetracker_id )
        _LOGGER.debug( "(" + self._name + ") Previous State        : " + previous_state )

        if hasattr(self, '_devicetracker_id'):
            now = datetime.now()
            old_latitude    = str(self._latitude)
            old_longitude   = str(self._longitude)
            new_latitude    = str(self._hass.states.get(self._devicetracker_id).attributes.get('latitude'))
            new_longitude   = str(self._hass.states.get(self._devicetracker_id).attributes.get('longitude'))
            home_latitude   = str(self._home_latitude)
            home_longitude  = str(self._home_longitude)
            last_distance_m = self._distance_m
            last_updated    = self._mtime
            current_location  = new_latitude + "," + new_longitude
            previous_location = old_latitude + "," + old_longitude
            home_location     = home_latitude + "," + home_longitude
            
            #maplink_google ='https://www.google.com/maps/@' + current_location+',' + self._map_zoom + 'z'
            maplink_apple  = 'https://maps.apple.com/maps/?ll=' + current_location + '&z=' + self._map_zoom
            #maplink_google = 'https://www.google.com/maps/dir/?api=1&origin=' + current_location + '&destination=' + home_location + '&travelmode=driving&layer=traffic'
            maplink_google = 'https://www.google.com/maps/search/?api=1&basemap=roadmap&layer=traffic&query=' + current_location

            distance_m = distance(float(new_latitude), float(new_longitude), float(home_latitude), float(home_longitude))
            distance_km = round(distance_m / 1000, 2)
            distance_from_home = str(distance_km)+' km'

            if last_distance_m > distance_m:
              direction = "towards home"
            elif last_distance_m < distance_m:
              direction = "away from home"
            else:
              direction = "stationary"

            _LOGGER.debug( "(" + self._name + ") Previous Location: " + previous_location)
            _LOGGER.debug( "(" + self._name + ") Current Location : " + current_location)
            _LOGGER.debug( "(" + self._name + ") Home Location    : " + home_location)           
            _LOGGER.info( "(" + self._name + ") Distance from home : (" + (self._home_zone).split(".")[1] + "): " + distance_from_home )
            _LOGGER.info( "(" + self._name + ") Travel Direction   :(" + direction + ")" )
           
        """Update if location has changed."""

        devicetracker_zone = self.hass.states.get(self._devicetracker_id).state
        distance_traveled = distance(float(new_latitude), float(new_longitude), float(old_latitude), float(old_longitude))

        _LOGGER.info( "(" + self._name + ") DeviceTracker Zone (before update): " + devicetracker_zone )
        _LOGGER.info( "(" + self._name + ") Meters traveled since last update: " + str(round(distance_traveled)) )

        proceed_with_update = True

        if current_location == previous_location:
            _LOGGER.debug( "(" + self._name + ") Skipping update because co-ordinates are identical" )
            proceed_with_update = False
        elif int(distance_traveled) > 0 and self._updateskipped > 3:
            proceed_with_update = True
            _LOGGER.debug( "(" + self._name + ") Allowing update after 3 skips even with distance traveled < 10m" )            
        elif int(distance_traveled) < 10:
            self._updateskipped = self._updateskipped + 1
            _LOGGER.debug( "(" + self._name + ") Skipping update because location changed " + str(distance_traveled) + " < 10m  (" + str(self._updateskipped) + ")" )
            proceed_with_update = False
        
        if previous_state == 'Initializing...':
            _LOGGER.debug( "(" + self._name + ") Peforming Initial Update for user at home..." )
            proceed_with_update = True

        if proceed_with_update:   
            _LOGGER.debug( "(" + self._name + ") Proceeding with update for " + self._devicetracker_id )
            self._devicetracker_zone = devicetracker_zone
            _LOGGER.info( "(" + self._name + ") DeviceTracker Zone (current) " + devicetracker_zone + " Skipped Updates: " + str(self._updateskipped))

            self._reset_attributes()
            
            self._latitude = new_latitude
            self._longitude = new_longitude
            self._latitude_old = old_latitude
            self._longitude_old = old_longitude
            self._location_current = current_location
            self._location_previous = previous_location
            self._devicetracker_zone = devicetracker_zone
            self._distance_km = distance_from_home
            self._distance_m = distance_m
            self._direction = direction

            if self._map_provider == 'google':
                _LOGGER.debug( "(" + self._name + ") Google Map Link requested for: [" + self._map_provider + "]")
                self._map_link = maplink_google
            else:
                _LOGGER.debug( "(" + self._name + ") Apple Map Link requested for: [" + self._map_provider + "]")
                self._map_link = maplink_apple
                
            _LOGGER.debug( "(" + self._name + ") Map Link generated: " + self._map_link )

            if self._api_key == 'no key':
                osm_url = "https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat=" + self._latitude + "&lon=" + self._longitude + "&addressdetails=1&namedetails=1&zoom=18&limit=1"
            else:
                osm_url = "https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat=" + self._latitude + "&lon=" + self._longitude + "&addressdetails=1&namedetails=1&zoom=18&limit=1&email=" + self._api_key

            osm_decoded = {}
            _LOGGER.info( "(" + self._name + ") OpenStreetMap request sent with lat=" + self._latitude + " and lon=" + self._longitude)
            _LOGGER.debug( "(" + self._name + ") url - " + osm_url)
            osm_response = get(osm_url)
            osm_json_input = osm_response.text
            _LOGGER.debug( "(" + self._name + ") response - " + osm_json_input)
            osm_decoded = json.loads(osm_json_input)
            decoded = osm_decoded

            place_options = self._options.lower()
            place_type = '-'
            place_name = '-'
            place_category = '-'
            place_neighbourhood = '-'
            street_number = ''
            street = 'Unnamed Road'
            city = '-'
            postal_town = '-'
            region = '-'
            county = '-'
            country = '-'
            postal_code = ''
            formatted_address = ''
            
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
                if "neighbourhood" in osm_decoded["address"]:
                    place_neighbourhood = osm_decoded["address"]["neighbourhood"]
                if self._devicetracker_zone == 'not_home' and place_name != 'house':
                    new_state = place_name
                    
            if "house_number" in osm_decoded["address"]:
                street_number = osm_decoded["address"]["house_number"]
            if "road" in osm_decoded["address"]:
                street = osm_decoded["address"]["road"]
            if "city" in osm_decoded["address"]:
                city = osm_decoded["address"]["city"]
            if "city_district" in osm_decoded["address"]:
                postal_town = osm_decoded["address"]["city_district"]
            if "suburb" in osm_decoded["address"]:
                postal_town = osm_decoded["address"]["suburb"]
            if "state" in osm_decoded["address"]:
                region = osm_decoded["address"]["state"]
            if "county" in osm_decoded["address"]:
                county = osm_decoded["address"]["county"]
            if "country" in osm_decoded["address"]:
                country = osm_decoded["address"]["country"]
            if "postcode" in osm_decoded["address"]:
                postal_code = osm_decoded["address"]["postcode"]
            if "display_name" in osm_decoded:
                formatted_address = osm_decoded["display_name"]

            self._place_type = place_type
            self._place_category = place_category
            self._place_neighbourhood = place_neighbourhood
            self._place_name = place_name
            
            self._street_number = street_number
            self._street = street
            self._city = city
            self._postal_town = postal_town
            self._region = region
            self._county = county
            self._country = country
            self._postal_code = postal_code
            self._formatted_address = formatted_address
            self._mtime = str(datetime.now())
            
            if 'error_message' in osm_decoded:
                new_state = osm_decoded['error_message']
                _LOGGER.info( "(" + self._name + ") An error occurred contacting the web service")
            elif self._devicetracker_zone == "not_home":
                if city == '':
                    city = postal_town
                    if city == '':
                        city = county

                # Options:  "zone, place, street_number, street, city, county, state, postal_code, country, formatted_address"

                _LOGGER.debug( "(" + self._name + ") Building State from Display Options: " + self._options)

                display_options = []
                options_array = self._options.split(',')
                for option in options_array:
                    display_options.append(option.strip())
                    
                user_display = []

                if "zone" in display_options:
                    zone = self._devicetracker_zone
                    user_display.append(zone)
                if "place" in display_options:
                    if place_name != "-":
                        user_display.append(place_name)
                    if place_category.lower() != "place":
                        user_display.append(place_category)
                    if place_type.lower() != "yes":
                        user_display.append(place_type)
                    user_display.append(place_neighbourhood)
                    user_display.append(street_number)
                    user_display.append(street)
                else:
                    if "street_number" in display_options:
                        user_display.append(street_number)
                    if "street" in display_options:
                        user_display.append(street)
                if "city" in display_options:
                    user_display.append(city)
                if "county" in display_options:
                    user_display.append(county)
                if "state" in display_options:
                    user_display.append(region)
                elif "region" in display_options:
                    user_display.append(region)
                if "postal_code" in display_options:
                    user_display.append(postal_code)
                if "country" in display_options:
                    user_display.append(country)
                if "formatted_address" in display_options:
                    user_display.append(formatted_address)

                if "do_not_reorder" in display_options:
                    user_display = []
                    display_options.remove("do_not_reorder")
                    for option in display_options:
                        if option == "state":
                            target_option = "region"
                        if option == "place_neighborhood":
                            target_option = "place_neighbourhood"
                        if option in locals():
                            user_display.append(targetoption)
                            

                if not user_display:
                    user_display = self._devicetracker_zone
                    user_display.append(street)
                    user_display.append(city)

                new_state = ', '.join( item for item in user_display )
                _LOGGER.debug( "(" + self._name + ") New State built from Display Options will be: " + new_state )
            else:
                new_state = devicetracker_zone
                _LOGGER.debug( "(" + self._name + ") New State from DeviceTracker set to: " + new_state)

            current_time = "%02d:%02d" % (now.hour, now.minute)
            
            if previous_state != new_state:
                _LOGGER.info( "(" + self._name + ") New state built using options: " + self._options)
                _LOGGER.debug( "(" + self._name + ") Building EventData for (" + new_state +")")
                self._state = new_state + " (since " + current_time + ")"
                event_data = {}
                event_data['entity'] = self._name
                event_data['place_name'] = place_name
                event_data['from_state'] = previous_state
                event_data['to_state'] = new_state
                event_data['distance_from_home'] = distance_from_home
                event_data['direction'] = direction
                event_data['devicetracker_zone'] = devicetracker_zone
                event_data['latitude'] = self._latitude
                event_data['longitude'] = self._longitude
                event_data['previous_latitude'] = self._latitude_old
                event_data['previous_longitude'] = self._longitude_old
                event_data['map'] = self._map_link
                event_data['mtime'] = current_time
                #_LOGGER.debug( "(" + self._name + ") Event Data: " + event_data )
                #self._hass.bus.fire(DEFAULT_NAME+'_state_update', { 'entity': self._name, 'place_name': place_name, 'from_state': previous_state, 'to_state': new_state, 'distance_from_home': distance_from_home, 'direction': direction, 'devicetracker_zone': devicetracker_zone, 'mtime': current_time, 'latitude': self._latitude, 'longitude': self._longitude, 'map': self._map_link })
                self._hass.bus.fire(DEFAULT_NAME+'_state_update', event_data )
                _LOGGER.debug( "(" + self._name + ") Update complete...")

    def _reset_attributes(self):
        """Resets attributes."""
        self._street = None
        self._street_number = None
        self._city = None
        self._postal_town = None
        self._postal_code = None
        self._region = None
        self._country = None
        self._county = None
        self._formatted_address = None
        self._place_type = None
        self._place_name = None
        self._mtime = datetime.now()
        self._updateskipped = 0

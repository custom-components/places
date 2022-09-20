from homeassistant.const import CONF_ZONE
from homeassistant.const import Platform

DOMAIN = "places"

# Defaults
DEFAULT_ICON = "mdi:map-marker-circle"
DEFAULT_OPTION = "zone, place"
DEFAULT_HOME_ZONE = "zone.home"
DEFAULT_MAP_PROVIDER = "apple"
DEFAULT_MAP_ZOOM = 18
DEFAULT_EXTENDED_ATTR = False

# Settings
TRACKING_DOMAINS = [
    str(Platform.DEVICE_TRACKER),
    str(Platform.PERSON),
    str(Platform.SENSOR),
]
HOME_LOCATION_DOMAIN = CONF_ZONE

# Config
CONF_DEVICETRACKER_ID = "devicetracker_id"
CONF_HOME_ZONE = "home_zone"
CONF_OPTIONS = "options"
CONF_MAP_PROVIDER = "map_provider"
CONF_MAP_ZOOM = "map_zoom"
CONF_LANGUAGE = "language"
CONF_EXTENDED_ATTR = "extended_attr"
CONF_YAML_HASH = "yaml_hash"

# Attributes
ATTR_OPTIONS = "options"
ATTR_STREET_NUMBER = "street_number"
ATTR_STREET = "street"
ATTR_CITY = "city"
ATTR_POSTAL_TOWN = "postal_town"
ATTR_POSTAL_CODE = "postal_code"
ATTR_REGION = "state_province"
ATTR_STATE_ABBR = "state_abbr"
ATTR_COUNTRY = "country"
ATTR_COUNTY = "county"
ATTR_FORMATTED_ADDRESS = "formatted_address"
ATTR_PLACE_TYPE = "place_type"
ATTR_PLACE_NAME = "place_name"
ATTR_PLACE_CATEGORY = "place_category"
ATTR_PLACE_NEIGHBOURHOOD = "neighbourhood"
ATTR_DEVICETRACKER_ID = "devicetracker_entityid"
ATTR_DEVICETRACKER_ZONE = "devicetracker_zone"
ATTR_DEVICETRACKER_ZONE_NAME = "devicetracker_zone_name"
ATTR_PICTURE = "entity_picture"
ATTR_LATITUDE_OLD = "previous_latitude"
ATTR_LONGITUDE_OLD = "previous_longitude"
ATTR_LATITUDE = "current_latitude"
ATTR_LONGITUDE = "current_longitude"
ATTR_MTIME = "last_changed"
ATTR_DISTANCE_KM = "distance_from_home_km"
ATTR_DISTANCE_M = "distance_from_home_m"
ATTR_HOME_ZONE = "home_zone"
ATTR_HOME_LATITUDE = "home_latitude"
ATTR_HOME_LONGITUDE = "home_longitude"
ATTR_LOCATION_CURRENT = "current_location"
ATTR_LOCATION_PREVIOUS = "previous_location"
ATTR_DIRECTION_OF_TRAVEL = "direction_of_travel"
ATTR_MAP_LINK = "map_link"
ATTR_FORMATTED_PLACE = "formatted_place"
ATTR_OSM_ID = "osm_id"
ATTR_OSM_TYPE = "osm_type"
ATTR_WIKIDATA_ID = "wikidata_id"
ATTR_OSM_DICT = "osm_dict"
ATTR_OSM_DETAILS_DICT = "osm_details_dict"
ATTR_WIKIDATA_DICT = "wikidata_dict"
ATTR_LAST_PLACE_NAME = "last_place_name"

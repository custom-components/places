# HomeAssistant-Places
A sensor custom_component for displaying Reverse Geocode (PLACE) details

Place Support for OpenStreetMap Geocode sensors.

Original Author:  Jim Thompson

```
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
 ```
 
Description:
  Provides a sensor with a variable state consisting of reverse geocode (place) details for a linked device_tracker entity that provides GPS co-ordinates (ie owntracks, icloud)
  Optionally allows you to specify a 'home_zone' for each device and calculates distance from home and direction of travel.
  The displayed state adds a time stamp "(since hh:mm)" so you can tell how long a person has been at a location.
  Configuration Instructions are below - as well as sample automations for notifications.
  
```
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
```

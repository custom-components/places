# places


[![GitHub Release][releases-shield]][releases]
[![GitHub Activity][commits-shield]][commits]
[![License][license-shield]](LICENSE.md)

[![hacs][hacsbadge]][hacs]

[![Discord][discord-shield]][discord]
[![Community Forum][forum-shield]][forum]

_Component to integrate with OpenStreetMap Reverse Geocode (PLACE)_

## Installation

1. Using the tool of choice open the directory (folder) for your HA configuration (where you find `configuration.yaml`).
2. If you do not have a `custom_components` directory (folder) there, you need to create it.
3. In the `custom_components` directory (folder) create a new folder called `places`.
4. Download _all_ the files from the `custom_components/places/` directory (folder) in this repository.
5. Place the files you downloaded in the new directory (folder) you created.
6. Add your configuration
6. Restart Home Assistant

Using your HA configuration directory (folder) as a starting point you should now also have this:

```text
custom_components/places/__init__.py
custom_components/places/manifest.json
custom_components/places/sensor.py
```

## Example configuration.yaml

```yaml
sensor places_jim:
  - platform: places
    name: jim
    devicetracker_id: device_tracker.jim_iphone8
    options: zone,place
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
    language: de
    home_zone: zone.sharon_home
    api_key: !secret email_sharon

sensor places_aidan:
  - platform: places
    name: aidan
    devicetracker_id: device_tracker.aidan_iphone7plus
    options: place
    map_provider: google
    map_zoom: 17
    language: jp,en
    home_zone: zone.aidan_home
    api_key: !secret email_aidan
```

## Configuration options

Key | Type | Required | Description | Default |
-- | -- | -- | -- | --
`platform` | `string` | `True` | `places` | None
`devicetracker_id` | `string` | `True` | `entity_id` of the device you wish to track | None
`name` | `string` | `False` | Friendly name of the sensor | `places`
`home_zone` | `string` | `False` | Calculates distance from home and direction of travel if set | `zone.home`
`api_key` | `string` | `False` | OpenStreetMap API key (your email address). | `no key`
`map_provider` | `string` | `False` | `google` or `apple` | `apple`
`map_zoom` | `number` | `False` | Level of zoom for the generated map link <1-20> | `18`
`language` | `string` | `False` | Requested* language(s) for state and attributes. Two-Letter language code(s). | *Refer to Notes
`options` | `string` | `False` | Display options: `zone, place, place_name, street_number, street, city, county, state, postal_code, country, formatted_address, do_not_show_not_home` | `zone, place`

Sample attributes that can be used in notifications, alerts, automations, etc:
```json
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
```

Sample generic automations.yaml snippet to send an iOS notify on any device state change:
(the only difference is the second one uses a condition to only trigger for a specific user)
```yaml
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
```

## Notes:

* This component is only useful to those who have device tracking enabled via a mechanism that provides latitude and longitude co-ordinates (such as Owntracks or iCloud).
* The OpenStreetMap database is very flexible with regards to tag_names in their database schema.  If you come across a set of co-ordinates that do not parse properly, you can enable debug messages to see the actual JSON that is returned from the query.
* The OpenStreetMap API requests that you include your valid e-mail address in each API call if you are making a large numbers of requests.  They say that this information will be kept confidential and only used to contact you in the event of a problem, see their Usage Policy for more details.
* The map link that gets generated for Google maps has a push pin marking the users location.
* The map link for Apple maps is centered on the users location - but without any marker.
* When no `language` value is given, default language will be location's local language or English. When a comma separated list of languages is provided - the component will attempt to fill each address field in desired languages by order.
* Translations are partial in OpenStreetMap database. For each field, if a translation is missing in first requested language it will be resolved with a language following in the provided list, defaulting to local language if no matching translations were found for the list.
* To enable detailed logging for this component, add the following to your configuration.yaml file
```yaml
  logger:
    default: warn
    logs:
      custom_components.sensor.places: debug  
```

Original Author: [Jim Thompson](https://github.com/tenly2000)

## Contributions are welcome!

If you want to contribute to this please read the [Contribution guidelines](CONTRIBUTING.md)

***

[places]: https://github.com/custom-components/places
[commits-shield]: https://img.shields.io/github/commit-activity/y/custom-components/places.svg?style=for-the-badge
[commits]: https://github.com/custom-components/places/commits/master
[hacs]: https://github.com/custom-components/hacs
[hacsbadge]: https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge
[discord]: https://discord.gg/Qa5fW2R
[discord-shield]: https://img.shields.io/discord/330944238910963714.svg?style=for-the-badge
[forum-shield]: https://img.shields.io/badge/community-forum-brightgreen.svg?style=for-the-badge
[forum]: https://community.home-assistant.io/t/reverse-geocode-sensor-places-using-openstreetmap-custom-component
[license-shield]: https://img.shields.io/github/license/custom-components/places.svg?style=for-the-badge
[maintenance-shield]: https://img.shields.io/badge/maintainer-Ian%20Richardson%20%40iantrich-blue.svg?style=for-the-badge
[releases-shield]: https://img.shields.io/github/release/custom-components/places.svg?style=for-the-badge
[releases]: https://github.com/custom-components/places/releases

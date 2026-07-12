# places
<picture>
  <img alt="places Logo" src="https://github.com/custom-components/places/raw/master/logo/icon.png">
</picture>

[![Integration Usage][integration-usage-shield]][releases]

[![GitHub Downloads][downloads-shield]][releases]
[![GitHub Latest Downloads][downloads-latest-shield]][releases]
[![GitHub Release][releases-shield]][releases]
[![GitHub Release Date][release-date-shield]][releases]
[![GitHub Activity][commits-shield]][commits]
[![Coverage][coverage-shield]][coverage]
[![License][license-shield]](LICENSE)
[![hacs][hacsbadge]][hacs]

_Component to integrate with OpenStreetMap Reverse Geocode and create a sensor with numerous address and place attributes from a device_tracker, person, or sensor_

## Breaking Change with v3: Entity model and migration notes

The main places sensor keeps the Display Options state. It now only exposes location-context attributes. Most values that used to be attributes are child sensors under the same places device. For example:

* `state_attr('sensor.alice', 'place_name')` becomes `states('sensor.alice_place_name')`
* `state_attr('sensor.alice', 'city')` becomes `states('sensor.alice_city')`
* `state_attr('sensor.alice', 'state')` becomes `states('sensor.alice_state')`
* `state_attr('sensor.alice', 'map_link')` becomes `states('sensor.alice_map_link')`

`country` and detailed address/diagnostic sensors are disabled by default. Enable them from the places device page if you use them in automations.

When Extended Attributes is enabled, raw payloads move to `sensor.<name>_extended_data`:

* `state_attr('sensor.alice_extended_data', 'osm_dict')`
* `state_attr('sensor.alice_extended_data', 'osm_details_dict')`
* `state_attr('sensor.alice_extended_data', 'wikidata_dict')`
* `state_attr('sensor.alice_extended_data', 'wikidata_id')`

## Installation via HACS

Ensure that [HACS](https://hacs.xyz/) is installed

<a href="https://my.home-assistant.io/redirect/hacs_repository/?owner=custom-components&repository=places" target="_blank" rel="noreferrer noopener"><img src="https://my.home-assistant.io/badges/hacs_repository.svg" alt="Open your Home Assistant instance to download the places integration." /></a>

Download the `places` integration

Restart Home Assistant

## Configuration

<a href="https://my.home-assistant.io/redirect/config_flow_start/?domain=places" target="_blank" rel="noreferrer noopener"><img src="https://my.home-assistant.io/badges/config_flow_start.svg" alt="Open your Home Assistant instance to create a places entry." /></a>

[See Configuration Options below](#configuration-options)

Repeat as needed to create additional `places` entries

Options for existing places entries can be changed by clicking the gear icon next to the desired entry under Settings > Devices & services > `places` integration.

## Configuration Options

Key | Required | Default | Description |
-- | -- | -- | --
`Sensor Name` | `Yes` | | Friendly name of the places sensor
`Tracked Entity ID` | `Yes` | | The location entity to track. **Must** have `latitude` and `longitude` as attributes. Supports these entities: `device_tracker`, `person`, `sensor`, `variable` & `zone`
`Email Address` | `No` | | OpenStreetMap API key (your email address).
`Display Options` | `No` | `zone_name`, `place` | Display options: `formatted_place` *(exclusive option)*, `driving` *(can be used with formatted_place or other options)*, `zone` or `zone_name`, `place`, `place_name`, `street_number`, `street`, `city`, `county`, `state`, `postal_code`, `country`, `osm_formatted_address`, `do_not_show_not_home`<br /><br />**See optional Advanced Display Options below to use more complex display logic.**
`Home Zone` | `No` | `zone.home` | Used to calculate distance from home and direction of travel
`Map Provider` | `No` | `apple` | `google`, `apple`, `osm`
`Map Zoom` | `No` | `18` | Level of zoom for the generated map link <1-20>
`Language` | `No` |location's local language | Requested<sup>\*</sup> language(s) for state and attributes. Two-Letter language code(s), separated by commas.<br /><sup>\*</sup>Refer to [Notes](#notes)
`Use GPS Accuracy` | `No` | `True` | Use GPS Accuracy when determining whether to update the places sensor (if 0, don't update the places sensor). By not updating when GPS Accuracy is 0, should prevent inaccurate locations from being set in the places sensors.<br /><br />**Set this to `False` if your Device Tracker has a GPS Accuracy (`gps_accuracy`) attribute, but it always shows 0 even if the latitude and longitude are correct.**
`Extended Attributes` | `No` | `False` | Create an enabled diagnostic `Extended data` sensor and fetch raw OSM details/Wikidata payloads. When disabled, the sensor is removed and the extra lookups are skipped. The extended sensor's raw attributes are excluded from recorder. |
`Show Last Updated` | `No` | `False` | Show last updated time at end of state `(since xx:yy)`

<details>
<summary><h3>Advanced Display Options</h3></summary>

To use, simply enter your advanced options into the `display_options` text area. Any display_options that contain `[]` or `()` will be processed with the Advanced Display Options.<br />
__Tip:__ _Build your advanced display options string in a text editor and copy/paste it into display_options field as it is pretty small._

### __Brackets [ ]:__ Fields to show if initial field is blank or empty<br />

These can be nested.

#### Examples

* `name[type]` will show the name, but if name is blank, will show the type instead. If type is also blank, nothing will show for that field
* `name[type[category]]` will show the name, but if name is blank, will show the type instead, but if type is blank, will show the category. If category is also blank, nothing will show for that field.

### __Parenthesis ( ):__ Inclusion/Exclusion Logic to filter the field<br />

#### To include/exclude based on the main field

* __Include:__ Set the first item inside the parenthesis to + to only show the field if it equals one of the states listed
* __Exclude:__ Set the first item inside the parenthesis to - to only show the field if doesn't equal one of the states listed
* If + or - isn't listed as the first item inside the parenthesis, include(+) is assumed.

  #### Examples

  * `type(-, house)` will show type if it is anything but "house"
  * `type(+, house)` will show type only if it is "house"
  * `type(house)` same as `type(+, house)`
  * `type(-, house, retail)` will show type if it is anything but "house" or "retail"
  * `type(+, house, retail)` will show type only if it is "house" or "retail"

#### To include/exclude based on other fields

* __Include:__ List the field to test followed by another set of parenthesis. In there, set the first item inside the parenthesis to + to only show the main field if the field to be tested equals one of the states listed
* __Exclude:__ List the field to test followed by another set of parenthesis. In there, set the first item inside the parenthesis to - to only show the main field if the field to be tested doesn't equal one of the states listed
* As above, if + or - isn't listed as the first item inside the parenthesis, include(+) is assumed.

  #### Examples

  * `type(category(-, highway))` will show type if category is anything but "highway"
  * `type(category(+, highway))` will show type only if category is "highway"
  * `type(category(highway))` same as `type(category(+, highway))`
  * `type(category(-, highway, building))` will show type if category is anything but "highway" or "building"
  * `type(category(+, highway, building))` will show type only if category is "highway" or "building"

#### The two types of include/excludes can also be combined

* `type(-,motorway, category(-, highway, building))` will show type if it is not "motorway" and if category is not "highway" or "building"

### Brackets and Parenthesis can also be combined

* To recreate `place`:

```text
name_no_dupe, category(-, place), type(-, yes), neighborhood, house_number, street
```

* To recreate `formatted_place`:

```text
zone_name[driving, name_no_dupe[type(-, unclassified, category(-, highway))[category(-, highway)], house_number, route_number(type(+, motorway, trunk))[street[route_number]], neighborhood(type(house))], city_clean[county], state_abbr]
```

### Fields

* `driving`
* `name` (Synonym: `place_name`)
* `name_no_dupe` (Synonym: `place_name_no_dupe`)
  * _Will be blank if the name is the same as one of the other attributes_
* `type` (Synonym: `place_type`)
* `category` (Synonym: `place_category`)
* `street_number` (Synonym: `house_number`)
* `street`
* `route_number` (Synonym: `street_ref`)
* `neighborhood` (Synonyms: `neighbourhood`, `place_neighborhood`, `place_neighbourhood`)
* `city`
* `city_clean`
  * _`city` but removes "Township" and moves "City" to the end if it starts with "City of"_
* `postal_town` (Synonyms: `borough`, `suburb`)
* `state` (Synonyms: `province`, `region`)
* `state_abbr`
* `county`
* `country`
* `country_code`
* `zip_code` (Synonym: `postal_code`)
* `latitude`
* `longitude`
* `zone`
* `zone_name`

__Note:__ `place` and `formatted_place` are not valid fields in the advanced display options. See examples [above](#brackets-and-parenthesis-can-also-be-combined) for how to recreate them.

-------
</details>

<details>
<summary>Sample generic `automations.yaml` snippet to send an iOS notify on any device state change</summary>

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
      title: 'ReverseLocate: {{ trigger.event.data.entity }} ({{ trigger.event.data.zone }}) {{ trigger.event.data.place_name }}'
      message: |-
        {{ trigger.event.data.entity }} ({{ trigger.event.data.zone }})
        {{ trigger.event.data.place_name }}
        {{ trigger.event.data.distance_from_home }} m from home and traveling {{ trigger.event.data.direction_of_travel }}
        {{ trigger.event.data.to_state }} ({{ trigger.event.data.last_changed }})
      data:
        attachment:
          url: '{{ trigger.event.data.map_link }}'
          hide_thumbnail: false

- alias: ReverseLocateFred
  initial_state: 'on'
  trigger:
    platform: event
    event_type: places_state_update
  condition:
    condition: template
    value_template: '{{ trigger.event.data.entity == "fred" }}'
  action:
  - service: notify.ios_jim_iphone8
    data_template:
      title: 'ReverseLocate: {{ trigger.event.data.entity }} ({{ trigger.event.data.zone }}) {{ trigger.event.data.place_name }}'
      message: |-
        {{ trigger.event.data.entity }} ({{ trigger.event.data.zone }})
        {{ trigger.event.data.place_name }}
        {{ trigger.event.data.distance_from_home }} m from home and traveling {{ trigger.event.data.direction_of_travel }}
        {{ trigger.event.data.to_state }} ({{ trigger.event.data.last_changed }})
      data:
        attachment:
          url: '{{ trigger.event.data.map_link }}'
          hide_thumbnail: false
```

</details>

## Notes

* This component is only useful to those who have device tracking enabled via a mechanism that provides latitude and longitude coordinates (such as the [Home Assistant Mobile App](https://www.home-assistant.io/integrations/mobile_app/), [OwnTracks](https://www.home-assistant.io/integrations/owntracks/), or [iCloud3](https://github.com/gcobb321/icloud3)).
* The OpenStreetMap database is very flexible with regards to tag_names in their database schema.  If you come across a set of coordinates that do not parse properly, you can enable debug logging (see below) to see the actual JSON that is returned from the query.
* The OpenStreetMap API requests that you include your valid e-mail address in each API call if you are making a large numbers of requests.  They say that this information will be kept confidential and only used to contact you in the event of a problem, see their Usage Policy for more details.
* The map link that gets generated for Google, Apple or OpenStreetMaps has a push pin marking the users location. Note that when opening the Apple link on a non-Apple device, it will open in Google Maps.
* When no `language` value is given, default language will be in the location's local language. When a comma-separated list of languages is provided - the component will attempt to fill each address field in desired languages by order.
* Translations are partial in OpenStreetMap database. For each field, if a translation is missing in first requested language it will be resolved with a language following in the provided list, defaulting to local language if no matching translations were found for the list.
* To enable debug logging for this component, add the following to your `configuration.yaml` file

```yaml
logger:
  default: warning
  logs:
    custom_components.places: debug  
```

## Development

To install development and testing dependencies locally, create a virtual environment and use the extras defined in `pyproject.toml`:

```bash
python -m pip install --upgrade pip
python -m pip install --group dev -e .
```

## Prior Contributions:

* Previous Authors: [Jim Thompson](https://github.com/tenly2000) & [Ian Richardson](https://github.com/iantrich)
* Current Author: [Snuffy2](https://github.com/Snuffy2)

## Contributions are welcome!

If you want to contribute to this please read the [Contribution guidelines](CONTRIBUTING.md)
***

[integration-usage-shield]: https://img.shields.io/badge/dynamic/json?color=41BDF5&logo=home-assistant&label=integration%20usage&suffix=%20installs&cacheSeconds=15600&url=https%3A%2F%2Fanalytics.home-assistant.io%2Fcustom_integrations.json&query=%24.places.total&style=for-the-badge
[downloads-shield]: https://img.shields.io/github/downloads/custom-components/places/total?style=for-the-badge&label=total%20downloads
[downloads-latest-shield]: https://img.shields.io/github/downloads-pre/custom-components/places/latest/total?style=for-the-badge
[releases]: https://github.com/custom-components/places/releases
[releases-shield]: https://img.shields.io/github/release/custom-components/places.svg?style=for-the-badge
[release-date-shield]: https://img.shields.io/github/release-date/custom-components/places?style=for-the-badge
[commits]: https://github.com/custom-components/places/commits/main
[commits-shield]: https://img.shields.io/github/last-commit/custom-components/places?style=for-the-badge
[license-shield]: https://img.shields.io/github/license/custom-components/places?color=blue&style=for-the-badge
[hacsbadge]: https://img.shields.io/badge/HACS-Default-blue.svg?style=for-the-badge
[hacs]: https://hacs.xyz
[coverage]: https://htmlpreview.github.io/?https://github.com/custom-components/places/blob/python-coverage-comment-action-data/htmlcov/index.html
[coverage-shield]: https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fcustom-components%2Fplaces%2Fpython-coverage-comment-action-data%2Fendpoint.json&style=for-the-badge

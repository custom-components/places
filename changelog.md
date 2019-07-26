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
```

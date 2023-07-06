# Home Assistant Recorder History Prefilter

The HA Recorder module was modified in HA 2023.6.0 to no longer allow a custom component to insert a sensor or other type of entity into the *_exclude_e* list that defined the entities that should not be added to the History database (home_assistant_v2.db).

This module fixes that problem. 



## How it Works

#### The Home Assistant Recorder Component

When Home Assistant starts, it loads the recorder component. The recorder component gets it's parameters from the HA configuration file (configuration.yaml) and builds the list of entities, globs, etc. to be filtered. It then starts a state change listener to call the filter module whenever an entity's state is changed. The filter determines if the entity should be added to the History database,

For efficiency, Home Assistant builds the filter that is checked one time when Home Assistant is loaded. The filter can not be changed or added to by a custom_component.

#### The Recorder History Prefilter

This module injects it's own filter (actually a copy of the recorder's filter) into the HA Recorder component, removes the HA listener that was set up by the HA Recorder and sets up a new state change listener. It is called when an entity's state changes instead of the HA Recorder filter and checks to see if the entity should be filtered. It the entity is not in it's list, the entity is passed to the HA Recorder filter module as it normally would be.



### Using the Recorder Prefilter

Entities are added or removed from this list using function calls from a custom component. More than one custom component can use this.

#### Adding Entities

The recorder prefilter is contained in the *recorder_prefilter.py* module. 

- Download it and add it to your code base.

Import it into the your module that determines the entities to be filtered. This may be in  *\__init__.py*, *sensor.py* or another module.

- `import recorder_prefilter`

The a single entity or a list of entities can be added at one time using the *add_filter* function call.

- `recorder_prefilter.add_filter(hass, 'icloud3_event_log')`
- `recorder_prefilter.add_filter(hass, ['icloud3_event_log', 'icloud3_wazehist_track', 'gary_iphone_info'])`
- `recorder_prefilter.add_filter(hass, [filtered_entities_list)`

Notes: 

- The entity_type (*input_boolean, light, etc* ) needs to be used if it is a non-sensor entity. 
- The first custom component to use the *add_filter* function call will inject the *recorder_prefilter* into the HA Recorder component. All subsequent *add_filter* calls will update the filter list.

#### Removing Entities

Entities can be removed from the filter list using the *remove_filter* function call.

The a single entity or a list of entities can be removed at one time.

- `recorder_prefilter.remove_filter(hass, 'icloud3_event_log')`

- `recorder_prefilter.remove_filter(hass, ['icloud3_event_log', 'icloud3_wazehist_track', 'gary_iphone_info'])`

- `recorder_prefilter.remove_filter(hass, [filtered_entities_list)`

  

### Logging

Normal HA Logging is available for the *recorder_prefilter* module. Enable it in configuration.yaml as you would do with any other component.

    logger:
      default: info
      logs:
        custom_components.icloud3.support.recorder_prefilter: info
        custom_components.places.recorder_prefilter: info

**Info logging** - Add basic records to the *home-assistant.log* file

```Recorder Prefilter Injection Started
Recorder Prefilter Injection Started
Recorder Prefilter Injection Completed
Added Recorder Prefilter Entities (icloud3)-2
Recorder Prefilter Entities Updated, Entities Filtered-2
...
...
Added Recorder Prefilter Entities (places)-1
Recorder Prefilter Entities Updated, Entities Filtered-3
...
...
Added Recorder Prefilter Entities (icloud3)-6
Recorder Prefilter Entities Updated, Entities Filtered-9
```



**Debug logging** - Add operational records to the *home-assistant.log* file.

    custom_components.icloud3.support.recorder_prefilter: debug
    custom_components.places.recorder_prefilter: debug

```Recorder Prefilter Injection Started
Recorder Prefilter Injection Started
Injecting Custom Exclude Entity Prefilter into Recorder
Removing Recorder Event Listener
Reinitializing Recorder Event Listener
Recorder Prefilter Injection Completed
Added Prefilter Entities-['icloud3_event_log', 'icloud3_wazehist_track']
Added Recorder Prefilter Entities (icloud3)-2
All Prefiltered Entities-['sensor.icloud3_event_log', 'sensor.icloud3_wazehist_track']
Recorder Prefilter Entities Updated, Entities Filtered-2
...
...
Added Prefilter Entities-sensor.gary_place
Added Recorder Prefilter Entities (places)-1
All Prefiltered Entities-['sensor.gary_place', 'sensor.icloud3_event_log', 'sensor.icloud3_wazehist_track']
Recorder Prefilter Entities Updated, Entities Filtered-3
...
...
Added Prefilter Entities-['sensor.gary_iphone_info', 'sensor.gary_iphone_trigger', 'sensor.lillian_iphone_info', 'sensor.lillian_iphone_trigger', 'sensor.lillian_watch_info', 'sensor.lillian_watch_trigger']
Added Recorder Prefilter Entities (icloud3)-6
All Prefiltered Entities-['sensor.gary_iphone_info', 'sensor.gary_iphone_trigger', 'sensor.gary_place', 'sensor.icloud3_event_log', 'sensor.icloud3_wazehist_track', 'sensor.lillian_iphone_info', 'sensor.lillian_iphone_trigger', 'sensor.lillian_watch_info', 'sensor.lillian_watch_trigger']
Recorder Prefilter Entities Updated, Entities Filtered-9

```



Developed by:  Gary Cobb, *iCloud3 iDevice Tracker custom component*, (aka geekstergary)
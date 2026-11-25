# GPS accuracy of 0 means "not reported" until a source tracker proves otherwise

Home Assistant Core reports `gps_accuracy: 0` whenever an integration does not set an accuracy (`TrackerEntity._attr_location_accuracy` defaults to `0`, and legacy `see()` uses `gps_accuracy or 0`). Many trackers therefore send 0 alongside correct coordinates. Places used to skip every Update with an accuracy of 0, which stopped those trackers from updating at all.

We decided that an accuracy of 0 means "not reported" until the source tracker has reported a positive GPS accuracy. After that, a 0 reading from that source tracker is treated as a bad fix and skips the Update. For a person entity, the source tracker is its `source` attribute, so a phone that reports accuracy does not cause a router tracker's 0-accuracy home readings to be skipped. Places saves which source trackers have reported accuracy with the Places entry, and forgets a source tracker after 5 consecutive 0 readings that each moved more than 10 m from the previous reading, so a tracker whose integration stops reporting accuracy cannot get stuck. An identical repeat of the previous reading is ignored: it neither counts nor restarts the run.

Places summarizes earlier readings in order using a fixed amount of history per source tracker. A failed reverse lookup discards the candidate's effect on GPS accuracy history. Earlier readings and readings received during the lookup still count toward the next Update.

Reported accuracy also raises the stationary threshold to `max(10 m, accuracy)`, so movement within the accuracy radius is treated as noise. Because of this, Places has no separate cut-off for very imprecise readings. For a device tracker or person, the threshold stays at 10 m while its Current zone differs from the zone at the last successful reverse lookup. A closer reading can publish the Current zone while retaining the Place. Places saves the last resolved zone separately so the 10 m threshold still applies to later readings in the new zone.

When a reading keeps the same zone label and its source tracker supplies no zone membership, Places keeps the previous active zone ID if it still matches the label. Reported membership takes precedence. A reading can also fill in a missing last resolved zone ID when it confirms membership at the saved Place's coordinates and reports the saved label.

## Considered Options

- **Always skip 0 (previous behavior)**: blocks every tracker that does not report accuracy, and users had to find the README note telling them to turn the setting off.
- **Never skip 0**: removes the protection that helps trackers that do report accuracy, such as the Companion app.
- **Strict / Auto / Off setting**: adds a migration and a choice most users cannot make well; the existing on/off setting keeps its name, with "on" meaning this behavior.
- **Remember accuracy reporting per tracked entity instead of per source tracker**: simpler, but a person with a phone and a router tracker would have the router's home readings skipped forever.
- **Accept 0 readings while the tracked entity is in a zone**: needs no saved data, but also lets a phone's bad 0 readings through inside a zone.

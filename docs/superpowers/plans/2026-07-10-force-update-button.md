# Force Update Button Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a per-entry Home Assistant button that deletes persisted Store data and performs one cache- and timer-bypassing update.

**Architecture:** A new button platform calls one coordinator method. The coordinator owns serialization and Store removal, while a call-scoped `force` boolean flows through `PlacesUpdater` to `OSMClient`; shared cache and throttle state are never cleared or replaced.

**Tech Stack:** Python 3.14, Home Assistant entity/coordinator APIs, pytest, prek.

---

### Task 1: One-shot update bypass

**Files:**
- Modify: `custom_components/places/osm_client.py`
- Modify: `custom_components/places/update_sensor.py`
- Modify: `custom_components/places/coordinator.py`
- Test: `tests/test_osm_client.py`
- Test: `tests/test_update_sensor.py`
- Test: `tests/test_sensor.py`

- [ ] **Step 1: Write failing tests**

Add focused tests proving `OSMClient.get_json(..., use_cache=False)` performs the request despite an existing cached value without deleting the cache; `PlacesUpdater.do_update(..., force=True)` skips `determine_update_criteria`; and coordinator forced updates do not consult `_last_scan_update`.

- [ ] **Step 2: Verify RED**

Run `./.venv/bin/python -m pytest tests/test_osm_client.py tests/test_update_sensor.py tests/test_sensor.py -q`. Expect failures because the call-scoped arguments and coordinator method do not exist.

- [ ] **Step 3: Implement the minimum bypass**

Add `use_cache: bool = True` to `OSMClient.get_json`; guard only the cache-read branch. Add `force: bool = False` to updater/coordinator calls, use `UpdateStatus.PROCEED` instead of `determine_update_criteria()` when forced, and forward `use_cache=not force` to every lookup in the forced update. Keep normal defaults unchanged.

- [ ] **Step 4: Verify GREEN**

Repeat the focused pytest command and expect all selected tests to pass.

### Task 2: Force Update button

**Files:**
- Create: `custom_components/places/button.py`
- Modify: `custom_components/places/const.py`
- Modify: `custom_components/places/persistence.py`
- Modify: `custom_components/places/coordinator.py`
- Modify: `custom_components/places/manifest.json`
- Modify: `custom_components/places/translations/en.json`
- Test: `tests/test_button.py`
- Test: `tests/test_integration.py`

- [ ] **Step 1: Write failing button tests**

Test that setup creates one disabled-by-default diagnostic button tied to the config entry and pressing it calls the coordinator force method. Test the coordinator method removes Store data before running the forced update, and does not update when removal raises.

- [ ] **Step 2: Verify RED**

Run `./.venv/bin/python -m pytest tests/test_button.py tests/test_integration.py -q`. Expect collection/import failure because the button platform is absent.

- [ ] **Step 3: Implement the minimum button path**

Add `Platform.BUTTON` to `PLATFORMS`; retain the existing `PlacesStorage` instance on the coordinator; add `async_force_update()` that acquires the existing update lock, calls `async_remove()`, captures current attributes, and invokes `PlacesUpdater.do_update(reason="Force Update", previous_attr=..., force=True)`. Create one `ButtonEntity` with translation key `force_update`, diagnostic category, and the entry device association. Add English UI strings.

- [ ] **Step 4: Verify GREEN**

Repeat the focused pytest command and expect all selected tests to pass.

### Task 3: Final validation

**Files:**
- Modify only files rewritten by formatters.

- [ ] **Step 1: Run full tests**

Run `./.venv/bin/python -m pytest`. Expect the complete suite to pass without warnings.

- [ ] **Step 2: Run repository checks**

Run `./.venv/bin/python -m prek run -a`. Expect every hook to pass. If hooks rewrite files, rerun both commands.

- [ ] **Step 3: Review the final diff**

Run `git diff --check`, `git status --short --branch`, and `git diff --stat`. Confirm only the button, one-shot force path, strings, tests, and plan/spec documents changed.

- [ ] **Step 4: Commit implementation**

Stage the implementation and tests, then commit with `Add Force Update button`. Do not push the implementation commit without a new explicit push request.

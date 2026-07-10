# Configuration Entities Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add three disabled configuration entities that persist Places display settings and locally update affected sensors.

**Architecture:** Thin text/select/switch platforms delegate writes to one coordinator setting method. The coordinator updates `ConfigEntry.data`, runtime attributes, reuses existing render helpers, publishes one snapshot, and persists runtime state without reload or network access.

**Tech Stack:** Python 3.14, Home Assistant entity platforms and config-entry API, pytest, prek/ruff/mypy.

---

### Task 1: Configuration entity platforms

**Files:**
- Modify: `custom_components/places/const.py`
- Create: `custom_components/places/text.py`
- Create: `custom_components/places/select.py`
- Create: `custom_components/places/switch.py`
- Modify: `custom_components/places/translations/en.json`
- Create: `tests/test_text.py`
- Create: `tests/test_select.py`
- Create: `tests/test_switch.py`

- [ ] Write failing platform tests asserting one entity per platform, `EntityCategory.CONFIG`, disabled-by-default metadata, current config values, map-provider options, and delegation to `coordinator.async_update_setting()`.
- [ ] Run `./.venv/bin/python -m pytest tests/test_text.py tests/test_select.py tests/test_switch.py -q`; expect import/setup failures because the platforms do not exist.
- [ ] Add `Platform.TEXT`, `Platform.SELECT`, and `Platform.SWITCH` to `PLATFORMS`; implement minimal entities extending `PlacesEntity` plus the native HA entity class. Each write method delegates its setting key and new value to `async_update_setting()`.
- [ ] Add English entity translation keys `display_options`, `map_provider`, and `show_last_updated`.
- [ ] Re-run the three test modules; expect them to pass.

### Task 2: Persist and apply settings locally

**Files:**
- Modify: `custom_components/places/coordinator.py`
- Modify: `custom_components/places/update_sensor.py`
- Modify: `custom_components/places/config_flow.py`
- Modify: `tests/test_sensor.py`

- [ ] Write failing coordinator tests for display re-render, map-link regeneration, time-suffix toggling, `async_update_entry(data=...)`, one publish, persistence, invalid display input rollback, and no refresh call.
- [ ] Run the new targeted tests; expect failure because `async_update_setting()` is absent.
- [ ] Expose the existing display validator without duplicating rules. Implement `async_update_setting(key, value)` to validate first, copy and persist entry data with `async_update_entry`, update `config` and runtime attributes, then dispatch only the local recalculation required by the key.
- [ ] Reuse `process_display_options()`, `PlacesUpdater.get_map_link()`, and `clear_since_from_state()`; use HA local time for the enabled suffix. Publish once and persist after successful recalculation.
- [ ] Run targeted tests; expect all to pass.

### Task 3: Verify the complete change

**Files:**
- Modify as required only for formatter/type-checker findings.

- [ ] Run `./.venv/bin/python -m pytest`; expect the full suite to pass without warnings.
- [ ] Run `./.venv/bin/python -m prek run -a`; apply only mechanical required fixes.
- [ ] If hooks modify files, rerun both full commands so evidence matches the final tree.
- [ ] Run `git diff --check`, `git status --short --branch`, `git branch -vv`, and `git rev-parse --abbrev-ref --symbolic-full-name @{u}`; expect clean whitespace and upstream `origin/add-configuration-entities`.

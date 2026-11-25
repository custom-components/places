"""GPS accuracy history learned by one Places entry."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import TYPE_CHECKING

from .const import (
    ATTR_GPS_ACCURACY_SOURCES,
    ATTR_GPS_ACCURACY_TRACKED_ENTITY,
    CONF_DEVICETRACKER_ID,
    CONF_USE_GPS,
    GPS_ACCURACY_FORGET_COUNT,
    GPS_ACCURACY_RECORD_ATTRIBUTES,
    MOVEMENT_THRESHOLD_M,
    UpdateStatus,
)
from .location import CoordinatePair, LocationSnapshot
from .tracker import TrackerSnapshot

if TYPE_CHECKING:
    from homeassistant.core import State

    from .state import PlacesState

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _SourceTrackerHistory:
    """The last usable reading and run of moving zeros for a learned source tracker."""

    latitude: float
    longitude: float
    gps_accuracy: float | None
    moving_zero_readings: int


@dataclass(slots=True)
class _ReadingSummary:
    """Summarize an ordered run of readings with one history entry per source tracker."""

    sources: dict[str, None]
    readings: dict[str, _SourceTrackerHistory] = field(default_factory=dict)
    forgotten_sources: dict[str, None] = field(default_factory=dict)

    def fork(self) -> _ReadingSummary:
        """Copy current readings and source membership for a new run.

        Returns:
            _ReadingSummary: Independent summary with fresh forgetting notifications.
        """
        return _ReadingSummary(self.sources.copy(), self.readings.copy())

    def record(self, reading: TrackerSnapshot) -> bool:
        """Apply one reading to the source's GPS accuracy history.

        Args:
            reading (TrackerSnapshot): Reading from the tracked entity.

        Returns:
            bool: Whether this reading is a 0 that must skip its lookup.
        """
        source = reading.source_tracker
        accuracy = reading.gps_accuracy
        if accuracy is not None and accuracy > 0:
            self.sources[source] = None
        elif source not in self.sources:
            return False

        is_zero = accuracy == 0
        latitude = reading.latitude
        longitude = reading.longitude
        if latitude is None or longitude is None:
            return is_zero

        moving_zero_readings = 0
        previous = self.readings.get(source)
        if is_zero and previous is not None:
            if (latitude, longitude, accuracy) == (
                previous.latitude,
                previous.longitude,
                previous.gps_accuracy,
            ):
                return True
            movement = LocationSnapshot(
                current=CoordinatePair(latitude=latitude, longitude=longitude),
                previous=CoordinatePair(latitude=previous.latitude, longitude=previous.longitude),
            )
            movement.calculate()
            if (movement.distance_traveled or 0.0) > MOVEMENT_THRESHOLD_M:
                moving_zero_readings = previous.moving_zero_readings + 1

        should_forget = moving_zero_readings >= GPS_ACCURACY_FORGET_COUNT
        self.readings[source] = _SourceTrackerHistory(
            latitude, longitude, accuracy, 0 if should_forget else moving_zero_readings
        )
        if should_forget:
            self.sources.pop(source)
            self.forgotten_sources[source] = None
        return is_zero and not should_forget


class GPSAccuracyHistory:
    """Evaluate readings and learn from accepted Update attempts."""

    def __init__(self, state: PlacesState) -> None:
        """Restore source membership for the configured tracked entity.

        Args:
            state (PlacesState): Configured and restored attributes of the Places entry.
        """
        self._enabled = bool(state.get_attr(CONF_USE_GPS))
        self._tracked_entity = state.get_attr_safe_str(CONF_DEVICETRACKER_ID)
        sources: dict[str, None] = {}
        # Defer the latest event because it may be selected as the Place candidate.
        self._latest_reading: tuple[State, TrackerSnapshot] | None = None
        self._pending: _ReadingSummary | None = None
        self._staged: _ReadingSummary | None = None
        self._pending_after_commit: _ReadingSummary | None = None
        if (
            self._enabled
            and state.get_attr_safe_str(ATTR_GPS_ACCURACY_TRACKED_ENTITY) == self._tracked_entity
        ):
            sources = dict.fromkeys(
                str(source) for source in state.get_attr_safe_list(ATTR_GPS_ACCURACY_SOURCES)
            )
        else:
            for attr in GPS_ACCURACY_RECORD_ATTRIBUTES:
                state.clear_attr(attr)
        self._committed = _ReadingSummary(sources)

    def capture(self, state: State) -> None:
        """Capture an available tracked entity reading with usable coordinates.

        Args:
            state (State): Home Assistant state from the tracked entity event.
        """
        if self._enabled:
            reading = TrackerSnapshot.from_state(self._tracked_entity, state)
            if reading.has_valid_coordinates:
                self._fold_latest_reading()
                self._latest_reading = (state, reading)

    def stage_readings(
        self, current_state: State | None, candidate: TrackerSnapshot, places_name: str
    ) -> UpdateStatus:
        """Stage readings in arrival order and check the current candidate's accuracy.

        Args:
            current_state (State | None): Exact Home Assistant state used for the candidate.
            candidate (TrackerSnapshot): The reading being considered for a reverse lookup.
            places_name (str): Current friendly name of the Places entry for logging.

        Returns:
            UpdateStatus: Whether the current candidate passes the GPS accuracy check.
        """
        if not self._enabled:
            return UpdateStatus.PROCEED

        self._fold_latest_reading(current_state)
        earlier = self._pending or self._committed
        staged = earlier.fork()
        skip = staged.record(candidate)
        for source in earlier.forgotten_sources | staged.forgotten_sources:
            _LOGGER.warning(
                "(%s) %s sent %s GPS accuracy 0 readings in a row, each moving more than %s m, "
                "so Places is trying the latest reading",
                places_name,
                source,
                GPS_ACCURACY_FORGET_COUNT,
                MOVEMENT_THRESHOLD_M,
            )
        staged.forgotten_sources.clear()
        self._staged = staged
        return UpdateStatus.SKIP if skip else UpdateStatus.PROCEED

    def _fold_latest_reading(self, current_state: State | None = None) -> None:
        """Summarize the last event unless it is being evaluated as the candidate.

        Args:
            current_state (State | None): Exact state to exclude from earlier readings.
        """
        latest = self._latest_reading
        self._latest_reading = None
        if latest is None or latest[0] is current_state:
            return

        # Keep independent summaries for each possible outcome of an in-flight lookup.
        if self._pending is None:
            self._pending = self._committed.fork()
        self._pending.record(latest[1])
        if self._staged is not None:
            if self._pending_after_commit is None:
                self._pending_after_commit = self._staged.fork()
            self._pending_after_commit.record(latest[1])

    def commit(self, state: PlacesState) -> None:
        """Accept staged history, consume its readings, and record source membership.

        Args:
            state (PlacesState): Place attributes to publish and persist for this Update.
        """
        if self._staged is None:
            return
        if self._staged.sources:
            state.set_attr(ATTR_GPS_ACCURACY_SOURCES, list(self._staged.sources))
            state.set_attr(ATTR_GPS_ACCURACY_TRACKED_ENTITY, self._tracked_entity)
        else:
            for attr in GPS_ACCURACY_RECORD_ATTRIBUTES:
                state.clear_attr(attr)
        self._committed = self._staged
        self._pending = self._pending_after_commit
        self.discard()

    def clear_pending_readings(self) -> None:
        """Drop pending readings on final teardown."""
        self._latest_reading = None
        self._pending = None

    def discard(self) -> None:
        """Discard staged changes, keeping committed history and pending readings."""
        self._staged = None
        self._pending_after_commit = None

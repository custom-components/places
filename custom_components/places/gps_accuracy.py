"""GPS accuracy history learned by one Places entry."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import TYPE_CHECKING

from homeassistant.const import CONF_NAME

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

if TYPE_CHECKING:
    from collections.abc import Iterable

    from .state import PlacesState
    from .tracker import TrackerSnapshot

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _SourceTrackerHistory:
    """The last usable reading and run of moving zeros for a learned source tracker."""

    latitude: float
    longitude: float
    gps_accuracy: float | None
    moving_zero_readings: int


class GPSAccuracyHistory:
    """Evaluate readings and learn from accepted Update attempts."""

    def __init__(self, state: PlacesState) -> None:
        """Restore source membership for the configured tracked entity.

        Args:
            state (PlacesState): Configured and restored attributes of the Places entry.
        """
        self._enabled = bool(state.get_attr(CONF_USE_GPS))
        self._tracked_entity = state.get_attr_safe_str(CONF_DEVICETRACKER_ID)
        self._places_name = state.get_attr_safe_str(CONF_NAME)
        # Restored sources have no preceding reading or active run.
        self._sources: dict[str, _SourceTrackerHistory | None] = {}
        self._staged: dict[str, _SourceTrackerHistory | None] | None = None
        if (
            self._enabled
            and state.get_attr_safe_str(ATTR_GPS_ACCURACY_TRACKED_ENTITY) == self._tracked_entity
        ):
            self._sources = dict.fromkeys(
                str(source) for source in state.get_attr_safe_list(ATTR_GPS_ACCURACY_SOURCES)
            )
        else:
            for attr in GPS_ACCURACY_RECORD_ATTRIBUTES:
                state.clear_attr(attr)

    def stage_readings(
        self, earlier: Iterable[TrackerSnapshot], candidate: TrackerSnapshot
    ) -> UpdateStatus:
        """Stage readings in arrival order and check the current candidate's accuracy.

        Args:
            earlier (Iterable[TrackerSnapshot]): Earlier readings included in this Update.
            candidate (TrackerSnapshot): The reading being considered for a reverse lookup.

        Returns:
            UpdateStatus: Whether the current candidate passes the GPS accuracy check.
        """
        if not self._enabled:
            return UpdateStatus.PROCEED
        staged = self._sources.copy()
        for reading in earlier:
            self._evaluate_reading(staged, reading)
        status = self._evaluate_reading(staged, candidate)
        self._staged = staged
        return status

    def commit(self, state: PlacesState) -> None:
        """Accept staged history and write membership into the attributes to be saved.

        Args:
            state (PlacesState): Place attributes to publish and persist for this Update.
        """
        if self._staged is None:
            return
        if self._staged:
            state.set_attr(ATTR_GPS_ACCURACY_SOURCES, list(self._staged))
            state.set_attr(ATTR_GPS_ACCURACY_TRACKED_ENTITY, self._tracked_entity)
        else:
            for attr in GPS_ACCURACY_RECORD_ATTRIBUTES:
                state.clear_attr(attr)
        self._sources = self._staged
        self.discard()

    def discard(self) -> None:
        """Discard the current attempt's readings and retain committed history."""
        self._staged = None

    def _evaluate_reading(
        self, sources: dict[str, _SourceTrackerHistory | None], reading: TrackerSnapshot
    ) -> UpdateStatus:
        """Apply one reading to staged source membership and movement history.

        Args:
            sources (dict[str, _SourceTrackerHistory | None]): Learned sources in this attempt.
            reading (TrackerSnapshot): Reading from the tracked entity.

        Returns:
            UpdateStatus: Whether this reading passes the GPS accuracy check.
        """
        source = reading.source_tracker
        accuracy = reading.gps_accuracy
        latitude, longitude = reading.latitude, reading.longitude
        is_zero = accuracy == 0
        if accuracy is not None and accuracy > 0:
            sources.setdefault(source, None)
        elif source not in sources:
            return UpdateStatus.PROCEED

        status = UpdateStatus.SKIP if is_zero else UpdateStatus.PROCEED
        if latitude is None or longitude is None:
            return status

        previous = sources[source]
        moving_zeros = 0
        if is_zero and previous is not None:
            if (latitude, longitude, accuracy) == (
                previous.latitude,
                previous.longitude,
                previous.gps_accuracy,
            ):
                return status
            movement = LocationSnapshot(
                current=CoordinatePair(latitude, longitude),
                previous=CoordinatePair(previous.latitude, previous.longitude),
            )
            movement.calculate()
            if (movement.distance_traveled or 0.0) > MOVEMENT_THRESHOLD_M:
                moving_zeros = previous.moving_zero_readings + 1

        if moving_zeros >= GPS_ACCURACY_FORGET_COUNT:
            del sources[source]
            _LOGGER.warning(
                "(%s) %s sent %s GPS accuracy 0 readings in a row, each moving more than %s m, "
                "so Places is trying the latest reading",
                self._places_name,
                source,
                GPS_ACCURACY_FORGET_COUNT,
                MOVEMENT_THRESHOLD_M,
            )
            return UpdateStatus.PROCEED

        sources[source] = _SourceTrackerHistory(latitude, longitude, accuracy, moving_zeros)
        return status

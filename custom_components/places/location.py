"""Location snapshot and distance helper objects."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.util.location import distance


@dataclass(slots=True)
class CoordinatePair:
    """Simple latitude and longitude container."""

    latitude: float
    longitude: float

    def as_location(self) -> str:
        """Render location as ``lat,lon``."""
        return f"{self.latitude},{self.longitude}"


@dataclass(slots=True)
class LocationSnapshot:
    """Derived-location snapshot used by the Places updater."""

    current: CoordinatePair | None = None
    previous: CoordinatePair | None = None
    home: CoordinatePair | None = None
    distance_from_home: float | None = None
    distance_traveled: float | None = None

    def calculate(self) -> None:
        """Calculate supported distance values for this snapshot."""
        if self.current is not None and self.home is not None:
            self.distance_from_home = distance(
                self.current.latitude,
                self.current.longitude,
                self.home.latitude,
                self.home.longitude,
            )
        if self.current is not None and self.previous is not None:
            self.distance_traveled = distance(
                self.current.latitude,
                self.current.longitude,
                self.previous.latitude,
                self.previous.longitude,
            )


def direction_of_travel(
    previous_distance_from_home: float | None, distance_from_home: float | None
) -> str:
    """Compare home-distance snapshots and return a user-facing direction string.

    Args:
        previous_distance_from_home: Prior distance from home.
        distance_from_home: New distance from home.

    Returns:
        ``towards home``, ``away from home``, or ``stationary``.
    """
    if previous_distance_from_home is None or distance_from_home is None:
        return "stationary"

    if previous_distance_from_home > distance_from_home:
        return "towards home"
    if previous_distance_from_home < distance_from_home:
        return "away from home"
    return "stationary"

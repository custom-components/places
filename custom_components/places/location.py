"""Location snapshot and distance helper objects."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.util.location import distance

from .const import METERS_PER_MILE


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
    distance_from_home_m: float | None = None
    distance_traveled_m: float | None = None

    def calculate(self) -> None:
        """Calculate supported distance values for this snapshot."""
        if self.current is not None and self.home is not None:
            self.distance_from_home_m = distance(
                self.current.latitude,
                self.current.longitude,
                self.home.latitude,
                self.home.longitude,
            )
        if self.current is not None and self.previous is not None:
            self.distance_traveled_m = distance(
                self.current.latitude,
                self.current.longitude,
                self.previous.latitude,
                self.previous.longitude,
            )

    @property
    def distance_from_home_km(self) -> float | None:
        """Distance from home in kilometers."""
        if self.distance_from_home_m is None:
            return None
        return round(self.distance_from_home_m / 1000, 3)

    @property
    def distance_from_home_mi(self) -> float | None:
        """Distance from home in miles."""
        if self.distance_from_home_m is None:
            return None
        return round(self.distance_from_home_m / METERS_PER_MILE, 3)

    @property
    def distance_traveled_mi(self) -> float | None:
        """Distance traveled from previous sample in miles."""
        if self.distance_traveled_m is None:
            return None
        return round(self.distance_traveled_m / METERS_PER_MILE, 3)


def direction_of_travel(
    previous_distance_from_home_m: float | None, distance_from_home_m: float | None
) -> str:
    """Compare home-distance snapshots and return a user-facing direction string.

    Args:
        previous_distance_from_home_m: Prior distance from home.
        distance_from_home_m: New distance from home.

    Returns:
        ``towards home``, ``away from home``, or ``stationary``.
    """
    if previous_distance_from_home_m is None or distance_from_home_m is None:
        return "stationary"

    if previous_distance_from_home_m > distance_from_home_m:
        return "towards home"
    if previous_distance_from_home_m < distance_from_home_m:
        return "away from home"
    return "stationary"

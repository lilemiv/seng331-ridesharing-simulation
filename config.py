"""Simulation settings; all times are in minutes."""

from dataclasses import dataclass
from math import isfinite, log


@dataclass(frozen=True)
class SimulationConfig:
    mean_interarrival_minutes: float = 0.75  # 45 seconds
    duration_minutes: float = 60.0
    random_seed: int = 42
    fleet_size: int = 20
    mean_patience_minutes: float = 5.0
    pickup_min_minutes: float = 2.0
    pickup_max_minutes: float = 8.0
    trip_mean_minutes: float = 10.0  # Arithmetic mean, not the normal mean mu.
    trip_sigma: float = 0.5  # Standard deviation of log(trip duration).
    city_width: float = 10.0  # Abstract planar kilometres; not travel-time inputs.
    city_height: float = 10.0
    dispatch_policy: str = "random"
    pickup_mode: str = "uniform"
    pickup_speed_units_per_minute: float = 1.0
    pickup_base_delay_minutes: float = 1.0

    @property
    def trip_mu(self) -> float:
        """For T = exp(N(mu, sigma^2)), E[T] = exp(mu + sigma^2 / 2)."""
        return log(self.trip_mean_minutes) - self.trip_sigma * self.trip_sigma / 2.0

    def __post_init__(self) -> None:
        if self.pickup_mode not in ("uniform", "distance_aware"):
            raise ValueError("pickup_mode must be 'uniform' or 'distance_aware'.")
        for name, allow_zero in (("pickup_speed_units_per_minute", False),
                                 ("pickup_base_delay_minutes", True)):
            value = getattr(self, name)
            try:
                valid = (not isinstance(value, bool) and isinstance(value, (int, float))
                         and isfinite(value) and (value >= 0 if allow_zero else value > 0))
            except OverflowError:
                valid = False
            if not valid:
                bound = "nonnegative" if allow_zero else "positive"
                raise ValueError(f"{name} must be finite and {bound}.")
        if self.dispatch_policy not in ("random", "nearest"):
            raise ValueError("dispatch_policy must be 'random' or 'nearest'.")
        for name in ("city_width", "city_height"):
            value = getattr(self, name)
            try:
                valid = (not isinstance(value, bool) and isinstance(value, (int, float))
                         and isfinite(value) and value > 0)
            except OverflowError:
                valid = False
            if not valid:
                raise ValueError(f"{name} must be finite and positive.")
        if isinstance(self.random_seed, bool) or not isinstance(self.random_seed, int):
            raise ValueError("Random seed must be an integer.")
        if (
            not isfinite(self.mean_interarrival_minutes)
            or self.mean_interarrival_minutes <= 0
        ):
            raise ValueError("Mean interarrival time must be finite and positive.")
        if not isfinite(self.duration_minutes) or self.duration_minutes <= 0:
            raise ValueError("Simulation duration must be finite and positive.")
        if (
            isinstance(self.fleet_size, bool)
            or not isinstance(self.fleet_size, int)
            or self.fleet_size <= 0
        ):
            raise ValueError("Fleet size must be a positive integer.")
        if (
            not isfinite(self.mean_patience_minutes)
            or not 3.0 <= self.mean_patience_minutes <= 8.0
        ):
            raise ValueError("Mean patience must be between 3 and 8 minutes.")
        if (
            not isfinite(self.pickup_min_minutes)
            or not isfinite(self.pickup_max_minutes)
            or not 0 < self.pickup_min_minutes <= self.pickup_max_minutes
        ):
            raise ValueError("Pickup limits must be finite, positive, and ordered.")
        if not isfinite(self.trip_mean_minutes) or self.trip_mean_minutes <= 0:
            raise ValueError("Trip arithmetic mean must be finite and positive.")
        if not isfinite(self.trip_sigma) or self.trip_sigma < 0:
            raise ValueError("Trip log-scale sigma must be finite and nonnegative.")
        if not isfinite(self.trip_mu):
            raise ValueError("Trip parameters must produce a finite log-scale mu.")

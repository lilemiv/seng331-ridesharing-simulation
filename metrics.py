"""Finite-run statistics in minutes, without rounding or modifying records.

Use records from a successful run. Empty means return 0.0/count 0, not a sample.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from math import fsum, isfinite
from typing import Literal

from simulation import RideRequest, SimulationEvent


@dataclass(frozen=True)
class SampleMean:
    """Sample mean in minutes and its observation count."""

    mean: float
    count: int


def _sample_mean(values: Iterable[float]) -> SampleMean:
    samples = tuple(values)
    return SampleMean(fsum(samples) / len(samples) if samples else 0.0, len(samples))


def average_queue_delay(requests: Iterable[RideRequest]) -> SampleMean:
    """Mean assignment minus arrival, including unfinished service.

    Excludes abandoned and still-waiting customers, and excludes pickup travel.
    A zero assignment timestamp is valid.
    """
    return _sample_mean(
        r.driver_assignment_time - r.arrival_time
        for r in requests
        if r.status != "abandoned" and r.driver_assignment_time is not None
    )


def average_time_in_system(requests: Iterable[RideRequest]) -> SampleMean:
    """Mean completion minus arrival over completed trips only.

    Abandoned and unfinished customers are excluded from sum and denominator.
    """
    return _sample_mean(
        r.completion_time - r.arrival_time
        for r in requests
        if r.status == "completed" and r.completion_time is not None
    )


def _time_average(
    history: Iterable[SimulationEvent],
    horizon: float,
    field: Literal["waiting", "in_system", "busy_drivers"],
    capacity: int | None = None,
) -> float:
    """Integrate post-event states over [0, horizon], optionally per capacity.

    Sort by (time, sequence), starting from zero and holding the last state to T.
    Equal-time rows have zero area; rows beyond T do not contribute.
    Empty histories and T=0 return 0.0; T=0 skips history validation.
    Reject negative/nonfinite inputs and states above the supplied capacity.
    """
    if not isfinite(horizon) or horizon < 0:
        raise ValueError("Observation horizon must be finite and nonnegative.")
    if horizon == 0:
        return 0.0
    rows = list(history)
    if any(not isfinite(event.time) or event.time < 0 for event in rows):
        raise ValueError("Event timestamps must be finite and nonnegative.")
    rows.sort(key=lambda event: (event.time, event.sequence))
    previous_time = 0.0
    previous_state = 0.0
    contributions = []
    for event in rows:
        if event.time > horizon:
            break
        contributions.append(previous_state * ((event.time - previous_time) / horizon))
        value = getattr(event, field)
        if not isfinite(value) or value < 0 or (capacity is not None and value > capacity):
            raise ValueError(f"Invalid {field} state for observation window.")
        previous_state = value if capacity is None else value / capacity
        previous_time = event.time
    contributions.append(previous_state * ((horizon - previous_time) / horizon))
    return fsum(contributions)


def time_average_queue_length(history: Iterable[SimulationEvent], horizon: float) -> float:
    """Integral of Q(t) / T, including unfinished waiting through the horizon."""
    return _time_average(history, horizon, "waiting")


def time_average_number_in_system(history: Iterable[SimulationEvent], horizon: float) -> float:
    """Integral of engine N(t) / T: waiting plus pickup/trip, until departure."""
    return _time_average(history, horizon, "in_system")


def driver_utilization(
    history: Iterable[SimulationEvent], horizon: float, fleet_size: int
) -> float:
    """Integral of B(t) / (fleet_size * T), as a fraction in [0, 1].

    Includes pickup, trip, and partial service at T. Use the configured fleet.
    Reject invalid capacity or B; clamp only floating-point drift above one.
    """
    if isinstance(fleet_size, bool) or not isinstance(fleet_size, int) or fleet_size <= 0:
        raise ValueError("Fleet size must be a positive integer.")
    return min(1.0, _time_average(history, horizon, "busy_drivers", fleet_size))


def abandonment_rate(requests: Iterable[RideRequest]) -> float:
    """Abandoned / all arrivals, including unfinished arrivals; fraction [0, 1]."""
    rows = tuple(requests)
    return sum(r.status == "abandoned" for r in rows) / len(rows) if rows else 0.0


def calculate_simulation_metrics(requests: list[RideRequest]) -> dict[str, float]:
    """Legacy two-key API, also re-exported by main.

    Its rate is a percentage; individual metric functions expose counts and
    fraction-valued rates.
    """
    return {
        "average_waiting_time": average_queue_delay(requests).mean,
        "abandonment_rate_percent": abandonment_rate(requests) * 100,
    }

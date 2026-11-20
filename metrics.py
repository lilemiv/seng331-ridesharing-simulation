"""Read-only finite-run statistics; times are minutes and values are unrounded.

Consume request records after a successful, settled simulation run. Empty
populations have mean 0.0 and count 0; this convention is not an observation.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from math import fsum, isfinite
from typing import Literal

from simulation import RideRequest, SimulationEvent


@dataclass(frozen=True)
class SampleMean:
    """Unrounded sample mean in minutes and its observation denominator."""

    mean: float
    count: int


def _sample_mean(values: Iterable[float]) -> SampleMean:
    samples = tuple(values)
    return SampleMean(fsum(samples) / len(samples) if samples else 0.0, len(samples))


def average_queue_delay(requests: Iterable[RideRequest]) -> SampleMean:
    """Assignment minus arrival for assigned customers, including active service.

    Excludes abandoned and still-waiting customers. Pickup travel is not queue
    delay. A timestamp of zero is a recorded assignment, not a missing value.
    """
    return _sample_mean(
        r.driver_assignment_time - r.arrival_time
        for r in requests
        if r.status != "abandoned" and r.driver_assignment_time is not None
    )


def average_time_in_system(requests: Iterable[RideRequest]) -> SampleMean:
    """Completion minus arrival for completed trips only.

    Abandoned residence times and unfinished (censored) pickup/trip/waiting
    outcomes do not enter either the sum or the observation denominator.
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

    Sort a copy by (time, sequence). Initial state is zero before the first row;
    the last state persists to the horizon. Same-time intervals have zero area.
    Rows beyond the horizon do not contribute. Empty histories and T=0 return
    0.0. Negative/nonfinite horizons, timestamps, and states raise ValueError;
    capacity, when supplied, also bounds the state. T=0 needs no history scan.
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

    B includes pickup and trip, including partial service at T. Use the current
    config's fleet_size. Invalid capacity or B outside capacity raises ValueError;
    only floating-point drift of a valid integral is bounded at one.
    """
    if isinstance(fleet_size, bool) or not isinstance(fleet_size, int) or fleet_size <= 0:
        raise ValueError("Fleet size must be a positive integer.")
    return min(1.0, _time_average(history, horizon, "busy_drivers", fleet_size))


def abandonment_rate(requests: Iterable[RideRequest]) -> float:
    """Abandoned / all arrivals, including unfinished arrivals; fraction [0, 1]."""
    rows = tuple(requests)
    return sum(r.status == "abandoned" for r in rows) / len(rows) if rows else 0.0


def calculate_simulation_metrics(requests: list[RideRequest]) -> dict[str, float]:
    """Preserve the Week 1 two-key API, including its abandonment percentage.

    main re-exports this function for existing imports. New consumers should
    use the individual functions for observation counts and fraction-valued rates.
    """
    return {
        "average_waiting_time": average_queue_delay(requests).mean,
        "abandonment_rate_percent": abandonment_rate(requests) * 100,
    }

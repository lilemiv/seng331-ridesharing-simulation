"""Reusable illustrative configurations, independent of experiment runners."""

from dataclasses import replace

from config import SimulationConfig


_SCENARIO_CHANGES = {
    "baseline": {},
    "low_demand": {"mean_interarrival_minutes": 1.5},
    "high_demand": {"mean_interarrival_minutes": 0.25},
    "small_fleet": {"fleet_size": 5},
    "large_fleet": {"fleet_size": 40},
}
SCENARIO_NAMES = tuple(_SCENARIO_CHANGES)


def get_scenario(name: str = "baseline", **overrides) -> SimulationConfig:
    """Return a validated preset with explicit overrides taking precedence.

    Unspecified fields retain SimulationConfig defaults, including seed/horizon.
    """
    try:
        changes = _SCENARIO_CHANGES[name]
    except KeyError as error:
        raise ValueError(
            f"Unknown scenario {name!r}; choose from {', '.join(SCENARIO_NAMES)}."
        ) from error
    return replace(SimulationConfig(), **{**changes, **overrides})

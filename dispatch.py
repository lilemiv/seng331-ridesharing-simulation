"""Named driver state and selection, separate from FIFO customer scheduling."""

from dataclasses import dataclass
from collections.abc import Iterable
from math import hypot, isfinite
import random


@dataclass(frozen=True)
class Driver:
    """Immutable driver snapshot; unassigned drivers are available."""

    driver_id: int
    x: float
    y: float
    assigned_request_id: int | None = None

    @property
    def is_available(self) -> bool:
        return self.assigned_request_id is None


def select_random_driver(drivers: Iterable[Driver], rng: random.Random) -> Driver:
    """Choose uniformly from idle drivers in stable ID order."""
    available = sorted((driver for driver in drivers if driver.is_available),
                       key=lambda driver: driver.driver_id)
    if not available:
        raise ValueError("No available driver to select.")
    return rng.choice(available)


def select_nearest_driver(drivers: Iterable[Driver], pickup_x: float, pickup_y: float) -> Driver:
    """Euclidean nearest idle driver; exact distance ties use the lowest ID."""
    available = [driver for driver in drivers if driver.is_available]
    if not available:
        raise ValueError("No available driver to select.")
    distances = [(hypot(driver.x - pickup_x, driver.y - pickup_y), driver.driver_id, driver)
                 for driver in available]
    distance, _, nearest = min(distances, key=lambda row: row[:2])
    if isfinite(distance):
        return nearest
    # Rescale only if all distances overflow; outliers can erase tiny distances.
    scale = max(abs(pickup_x), abs(pickup_y),
                *(max(abs(driver.x), abs(driver.y)) for driver in available)) or 1.0
    return min(available, key=lambda driver: (
        hypot((driver.x - pickup_x) / scale, (driver.y - pickup_y) / scale), driver.driver_id,
    ))

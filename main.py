"""Run the simulation and print lifecycle counts and performance metrics."""

from collections import Counter

from config import SimulationConfig
from metrics import (
    abandonment_rate,
    average_queue_delay,
    average_time_in_system,
    calculate_simulation_metrics,  # Re-export the existing Week 1 import path.
    driver_utilization,
    time_average_number_in_system,
    time_average_queue_length,
)
from simulation import RideSharingSimulation


def format_time(value: float | None) -> str:
    """Keep missing timestamps distinct from time zero."""
    return "pending" if value is None else f"{value:.3f}"


def main() -> None:
    config = SimulationConfig()
    simulation = RideSharingSimulation(config)
    simulation.run()

    print(f"Simulated duration: {simulation.env.now:.1f} minutes")
    print(f"Random seed: {config.random_seed}")
    print(f"Fleet size: {config.fleet_size}")
    print(f"Mean patience: {config.mean_patience_minutes:.1f} minutes")
    print(f"Requests arrived: {len(simulation.requests)}")

    counts = Counter(r.status for r in simulation.requests)
    print(f"Completed: {counts['completed']}")
    print(f"In service: {counts['in_service']}")
    print(f"Waiting: {counts['waiting']}")
    print(f"Abandoned: {counts['abandoned']}")

    queue_delay = average_queue_delay(simulation.requests)
    system_time = average_time_in_system(simulation.requests)
    horizon = simulation.env.now
    queue_length = time_average_queue_length(simulation.event_history, horizon)
    population = time_average_number_in_system(simulation.event_history, horizon)
    utilization = driver_utilization(simulation.event_history, horizon, simulation.config.fleet_size)

    print(f"Average Queue Delay (assigned customers, n={queue_delay.count}): "
          f"{queue_delay.mean:.2f} minutes")
    print(f"Average Time in System (completed customers, n={system_time.count}): "
          f"{system_time.mean:.2f} minutes")
    print(f"Time-average Queue Length: {queue_length:.3f}")
    print(f"Time-average Number in System: {population:.3f}")
    print(f"Driver Utilization: {utilization:.2%}")
    print(f"Abandonment Rate: {abandonment_rate(simulation.requests):.2%}")


if __name__ == "__main__":
    main()

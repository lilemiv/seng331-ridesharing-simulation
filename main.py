"""Run the core simulation and display request lifecycle records."""

from collections import Counter

from config import SimulationConfig
from simulation import RideSharingSimulation


def format_time(value: float | None) -> str:
    """Display an unrecorded timestamp without confusing it with time zero."""
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
    print("First five requests (minutes; pending means no recorded timestamp):")
    for request in simulation.requests[:5]:
        print(
            f"  Request {request.request_id}: arrival={request.arrival_time:.3f}, "
            f"patience={request.patience_time:.3f}, "
            f"assigned={format_time(request.driver_assignment_time)}, "
            f"abandonment={format_time(request.abandonment_time)}, "
            f"status={request.status}"
        )
        print(
            f"    Pickup: start={format_time(request.pickup_start_time)}, "
            f"completion={format_time(request.pickup_completion_time)}, "
            f"duration={format_time(request.pickup_duration)}"
        )
        print(
            f"    Trip: start={format_time(request.trip_start_time)}, "
            f"completion={format_time(request.trip_completion_time)}, "
            f"duration={format_time(request.trip_duration)}"
        )


if __name__ == "__main__":
    main()

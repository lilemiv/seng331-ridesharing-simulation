"""Run the core simulation and display request lifecycle records."""

from collections import Counter

from config import SimulationConfig
from simulation import RideSharingSimulation, RideRequest


def format_time(value: float | None) -> str:
    """Display an unrecorded timestamp without confusing it with time zero."""
    return "pending" if value is None else f"{value:.3f}"


def calculate_simulation_metrics(requests: list[RideRequest]) -> dict:
    """Simülasyon istek listesinden temel performans metriklerini hesaplar."""
    total_arrivals = len(requests)
    if total_arrivals == 0:
        return {
            "average_waiting_time": 0.0,
            "abandonment_rate_percent": 0.0
        }

    abandoned_count = sum(1 for r in requests if r.status == "abandoned")

    waiting_times = []
    for r in requests:
        if r.service_start_time is not None:
            waiting_times.append(r.service_start_time - r.arrival_time)
        elif r.abandonment_time is not None:
            waiting_times.append(r.abandonment_time - r.arrival_time)

    avg_waiting_time = sum(waiting_times) / len(waiting_times) if waiting_times else 0.0
    abandonment_rate = (abandoned_count / total_arrivals) * 100

    return {
        "average_waiting_time": round(avg_waiting_time, 2),
        "abandonment_rate_percent": round(abandonment_rate, 2)
    }


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

    # En alta metrikleri hesaplayıp yazdıran kısmı ekledik:
    metrics = calculate_simulation_metrics(simulation.requests)
    print(f"Average Waiting Time: {metrics['average_waiting_time']} minutes")
    print(f"Abandonment Rate: %{metrics['abandonment_rate_percent']}")


if __name__ == "__main__":
    main()

"""Reproducible finite-horizon replications using the existing engine and metrics."""

import csv
import json
from dataclasses import asdict, dataclass, replace
from math import fsum
from pathlib import Path

from config import SimulationConfig
from inference import confidence_interval, positive_integer
from metrics import (abandonment_rate, average_queue_delay, average_time_in_system,
                     driver_utilization, time_average_number_in_system,
                     time_average_queue_length)
from simulation import RideSharingSimulation


STREAM_NAMES = ("arrivals", "patience", "pickup", "trip", "driver_location",
                "pickup_location", "destination", "dispatch")
STREAM_STRIDE = len(STREAM_NAMES)
METRIC_NAMES = ("average_queue_delay", "average_time_in_system", "time_average_queue_length",
                "time_average_number_in_system", "driver_utilization", "abandonment_rate",
                "mean_assignment_distance")


def seed_bundle(master_seed: int, replication_id: int) -> dict[str, int]:
    """Allocate disjoint eight-seed blocks, matching abs(seed)+0..7 in the engine."""
    if isinstance(master_seed, bool) or not isinstance(master_seed, int):
        raise ValueError("master_seed must be an integer.")
    positive_integer(replication_id, "replication_id", 0)
    base = abs(master_seed) + STREAM_STRIDE * replication_id
    return {name: base + offset for offset, name in enumerate(STREAM_NAMES)}


@dataclass(frozen=True)
class ReplicationResult:
    scenario: str
    replication_id: int
    master_seed: int
    config: SimulationConfig
    stream_seeds: dict[str, int]
    counts: dict[str, int]
    metrics: dict[str, float | None]


def run_replications(config: SimulationConfig, count: int, *, master_seed: int | None = None,
                     start_index: int = 0, scenario: str = "baseline") -> list[ReplicationResult]:
    """One observation per metric per run. Empty customer populations become None.

    Continue a batch with the same master_seed and a disjoint start_index. Sharing
    bundles across experimental cells is intentional pairing, not independence
    between cells. Distinct master seeds alone do not guarantee disjoint blocks.
    """
    positive_integer(count, "count")
    positive_integer(start_index, "start_index", 0)
    master_seed = config.random_seed if master_seed is None else master_seed
    results = []
    for replication_id in range(start_index, start_index + count):
        seeds = seed_bundle(master_seed, replication_id)
        actual_config = replace(config, random_seed=seeds["arrivals"])
        sim = RideSharingSimulation(actual_config)
        sim.run()
        queue = average_queue_delay(sim.requests)
        system = average_time_in_system(sim.requests)
        distances = [r.assignment_distance for r in sim.requests if r.assignment_distance is not None]
        counts = {"arrivals": len(sim.requests), "assigned": queue.count,
                  "completed": system.count, "distance_observations": len(distances),
                  "abandoned": sum(r.status == "abandoned" for r in sim.requests)}
        metrics = {
            "average_queue_delay": queue.mean if queue.count else None,
            "average_time_in_system": system.mean if system.count else None,
            "time_average_queue_length": time_average_queue_length(sim.event_history, sim.env.now),
            "time_average_number_in_system": time_average_number_in_system(sim.event_history, sim.env.now),
            "driver_utilization": driver_utilization(sim.event_history, sim.env.now, config.fleet_size),
            "abandonment_rate": abandonment_rate(sim.requests) if sim.requests else None,
            "mean_assignment_distance": fsum(distances) / len(distances) if distances else None,
        }
        results.append(ReplicationResult(scenario, replication_id, master_seed,
                                         actual_config, seeds, counts, metrics))
    return results


def summarize_replications(results, confidence: float = 0.95) -> dict:
    rows = tuple(results)
    return {name: asdict(confidence_interval((row.metrics[name] for row in rows), confidence))
            for name in METRIC_NAMES}


def export_replications(results, path: str | Path) -> None:
    """UTF-8 JSON or flattened CSV; full configuration, counts, IDs and seeds."""
    rows = [asdict(row) for row in results]
    path = Path(path)
    if path.suffix.lower() == ".json":
        path.write_text(json.dumps(rows, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    elif path.suffix.lower() == ".csv":
        flat = []
        for row in rows:
            record = {key: row[key] for key in ("scenario", "replication_id", "master_seed")}
            for group in ("config", "stream_seeds", "counts", "metrics"):
                record.update({f"{group}.{key}": value for key, value in row[group].items()})
            flat.append(record)
        if not flat:
            raise ValueError("CSV export requires at least one replication.")
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(flat[0]))
            writer.writeheader()
            writer.writerows(flat)
    else:
        raise ValueError("Export path must end in .json or .csv.")

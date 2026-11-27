"""Matched-seed fleet/demand/policy experiments; run `python experiments.py --help`."""

import argparse
import json
from dataclasses import asdict, dataclass, replace
from math import isclose
from pathlib import Path

from config import SimulationConfig
from inference import confidence_interval, estimate_replications
from replications import (METRIC_NAMES, export_replications, run_replications,
                          summarize_replications)
from scenarios import SCENARIO_NAMES, get_scenario


@dataclass(frozen=True)
class ExperimentCell:
    name: str
    config: SimulationConfig


def assert_report_matches(actual, expected, *, relative_tolerance=1e-10, absolute_tolerance=1e-12):
    """Check all metadata exactly and floats within cross-platform libm tolerance."""
    def compare(left, right, path):
        if isinstance(right, dict):
            assert isinstance(left, dict) and left.keys() == right.keys(), path
            for key in right:
                compare(left[key], right[key], f"{path}.{key}")
        elif isinstance(right, list):
            assert isinstance(left, list) and len(left) == len(right), path
            for i, (a, b) in enumerate(zip(left, right)):
                compare(a, b, f"{path}[{i}]")
        elif isinstance(right, float):
            assert isinstance(left, (int, float)) and isclose(
                left, right, rel_tol=relative_tolerance, abs_tol=absolute_tolerance), path
        else:
            assert type(left) is type(right) and left == right, path
    compare(actual, expected, "report")


def default_design(duration_minutes: float = 240.0, *, include_distance_aware: bool = True):
    """Five fleet/demand settings crossed with policy and, optionally, pickup mode."""
    modes = ("uniform", "distance_aware") if include_distance_aware else ("uniform",)
    return [ExperimentCell(f"{scenario}/{mode}/{policy}",
                           get_scenario(scenario, duration_minutes=duration_minutes,
                                        dispatch_policy=policy, pickup_mode=mode))
            for scenario in SCENARIO_NAMES for mode in modes for policy in ("random", "nearest")]


def paired_comparison(reference, alternative, confidence: float = 0.95) -> dict:
    """CI on alternative-reference differences, paired by replication ID and seeds."""
    reference, alternative = tuple(reference), tuple(alternative)
    left = {row.replication_id: row for row in reference}
    right = {row.replication_id: row for row in alternative}
    if len(left) != len(reference) or len(right) != len(alternative) or left.keys() != right.keys():
        raise ValueError("Paired comparisons require unique, matching replication IDs.")
    if any(left[i].stream_seeds != right[i].stream_seeds for i in left):
        raise ValueError("Paired comparisons require matching seed bundles.")
    differences = {name: [] for name in METRIC_NAMES}
    for i in sorted(left):
        for name in METRIC_NAMES:
            a, b = left[i].metrics[name], right[i].metrics[name]
            differences[name].append(None if a is None or b is None else b - a)
    return {name: asdict(confidence_interval(values, confidence))
            for name, values in differences.items()}


def run_experiment(cells, count: int = 20, *, master_seed: int = 2026,
                   confidence: float = 0.95, beta: float = 0.05) -> dict:
    cells = tuple(cells)
    if not cells or len({cell.name for cell in cells}) != len(cells):
        raise ValueError("Experiment cells must have unique names and be nonempty.")
    runs = {cell.name: run_replications(cell.config, count, master_seed=master_seed, scenario=cell.name)
            for cell in cells}
    summaries = {name: summarize_replications(rows, confidence) for name, rows in runs.items()}
    policy_comparisons = {}
    factor_comparisons = {}
    for cell in cells:
        if cell.config.dispatch_policy == "random":
            target = replace(cell.config, dispatch_policy="nearest")
            for other in cells:
                if other.config == target:
                    key = f"{other.name} - {cell.name}"
                    policy_comparisons[key] = paired_comparison(runs[cell.name], runs[other.name], confidence)
    # Only report contrasts differing in exactly one nominated factor.
    for cell in cells:
        if not cell.name.startswith("baseline/"):
            continue
        for other in cells:
            changed = [key for key, value in asdict(cell.config).items()
                       if value != getattr(other.config, key)]
            if changed == ["pickup_mode"] and cell.config.pickup_mode != "uniform":
                continue
            if len(changed) == 1 and changed[0] in {"fleet_size", "mean_interarrival_minutes", "pickup_mode"}:
                key = f"{other.name} - {cell.name}"
                factor_comparisons[key] = {"factor": changed[0], "metrics":
                    paired_comparison(runs[cell.name], runs[other.name], confidence)}
    planning = {}
    for name, rows in runs.items():
        values = [row.metrics["abandonment_rate"] for row in rows]
        planning[name] = (asdict(estimate_replications(values, beta, confidence))
                          if sum(x is not None for x in values) >= 2 else None)
    return {
        "design": {"replications_per_cell": count, "master_seed": master_seed,
                   "confidence": confidence, "beta_absolute_half_width": beta,
                   "beta_metric": "abandonment_rate", "warmup_minutes": 0,
                   "seed_strategy": "abs(master_seed) + 8 * replication_id + stream_offset",
                   "comparison": "paired alternative minus reference; matched bundles across cells",
                   "cells": [asdict(cell) for cell in cells]},
        "summaries": summaries, "policy_comparisons": policy_comparisons,
        "factor_comparisons": factor_comparisons, "beta_planning": planning,
        "replications": {name: [asdict(row) for row in rows] for name, rows in runs.items()},
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replications", type=int, default=20)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--duration", type=float, default=240)
    parser.add_argument("--confidence", type=float, default=0.95)
    parser.add_argument("--beta", type=float, default=0.05)
    parser.add_argument("--uniform-only", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("experiment_results.json"))
    parser.add_argument("--csv", type=Path, help="Optional flattened replication CSV")
    args = parser.parse_args(argv)
    report = run_experiment(default_design(args.duration, include_distance_aware=not args.uniform_only),
                            args.replications, master_seed=args.seed,
                            confidence=args.confidence, beta=args.beta)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    if args.csv:
        # Reconstruct only the export records; the simulation is not rerun.
        from replications import ReplicationResult
        rows = [ReplicationResult(**{**row, "config": SimulationConfig(**row["config"])})
                for group in report["replications"].values() for row in group]
        export_replications(rows, args.csv)
    print(f"Wrote {len(report['summaries'])} cells x {args.replications} replications to {args.output}")
    return report


if __name__ == "__main__":
    main()

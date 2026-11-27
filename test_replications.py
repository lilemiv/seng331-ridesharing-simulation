import csv
import json
import random
import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path

from config import SimulationConfig
from replications import (METRIC_NAMES, STREAM_NAMES, export_replications, run_replications,
                          seed_bundle, summarize_replications)
from simulation import RideSharingSimulation
from metrics import (abandonment_rate, average_queue_delay, average_time_in_system,
                     driver_utilization, time_average_number_in_system, time_average_queue_length)


class ReplicationTests(unittest.TestCase):
    def test_seed_bundles_disjoint_for_1000_replications(self):
        for master in (42, -42, 0):
            seeds = [seed for i in range(1000) for seed in seed_bundle(master, i).values()]
            self.assertEqual(len(seeds), len(set(seeds)))

    def test_seed_bundle_matches_actual_rng_initialization(self):
        config = SimulationConfig(random_seed=seed_bundle(-17, 3)["arrivals"])
        sim = RideSharingSimulation(config)
        attrs = ("rng", "patience_rng", "pickup_rng", "trip_rng", "driver_location_rng",
                 "pickup_location_rng", "destination_rng", "dispatch_rng")
        # Initial driver coordinates already consume their stream.
        for name, attr in zip(STREAM_NAMES, attrs):
            expected = random.Random(seed_bundle(-17, 3)[name])
            if name == "driver_location":
                for _ in range(config.fleet_size):
                    expected.uniform(0, config.city_width)
                    expected.uniform(0, config.city_height)
            self.assertEqual(getattr(sim, attr).getstate(), expected.getstate())

    def test_reproducible_full_results(self):
        for mode in ("uniform", "distance_aware"):
            config = SimulationConfig(pickup_mode=mode, dispatch_policy="nearest")
            self.assertEqual(run_replications(config, 3), run_replications(config, 3))

    def test_continuation_avoids_seed_reuse(self):
        config = SimulationConfig(random_seed=-42)
        combined = run_replications(config, 5)
        self.assertEqual(combined, run_replications(config, 2) + run_replications(config, 3, start_index=2))

    def test_metrics_match_public_apis(self):
        config = SimulationConfig()
        row = run_replications(config, 1)[0]
        sim = RideSharingSimulation(config)
        sim.run()
        self.assertEqual(row.metrics["average_queue_delay"], average_queue_delay(sim.requests).mean)
        self.assertEqual(row.metrics["average_time_in_system"], average_time_in_system(sim.requests).mean)
        self.assertEqual(row.metrics["time_average_queue_length"], time_average_queue_length(sim.event_history, 60))
        self.assertEqual(row.metrics["time_average_number_in_system"], time_average_number_in_system(sim.event_history, 60))
        self.assertEqual(row.metrics["driver_utilization"], driver_utilization(sim.event_history, 60, 20))
        self.assertEqual(row.metrics["abandonment_rate"], abandonment_rate(sim.requests))
        self.assertAlmostEqual(row.metrics["mean_assignment_distance"],
                               sum(r.assignment_distance for r in sim.requests if r.assignment_distance is not None) / 78)
        self.assertEqual((row.counts["arrivals"], row.counts["completed"], row.counts["abandoned"]), (86, 58, 8))

    def test_empty_population_not_fake_zero(self):
        row = run_replications(SimulationConfig(duration_minutes=1e-12), 1)[0]
        for name in ("average_queue_delay", "average_time_in_system", "mean_assignment_distance", "abandonment_rate"):
            self.assertIsNone(row.metrics[name])
        self.assertEqual(row.metrics["driver_utilization"], 0)
        summary = summarize_replications([row])
        self.assertEqual(summary["average_queue_delay"]["n"], 0)
        self.assertEqual(summary["average_queue_delay"]["missing"], 1)

    def test_no_completed_population(self):
        row = run_replications(SimulationConfig(duration_minutes=2), 1)[0]
        self.assertGreater(row.counts["assigned"], 0)
        self.assertIsNone(row.metrics["average_time_in_system"])
        self.assertIsNotNone(row.metrics["average_queue_delay"])

    def test_summary_uses_runs_not_customer_counts(self):
        rows = run_replications(SimulationConfig(), 3)
        for name in METRIC_NAMES:
            self.assertEqual(summarize_replications(rows)[name]["n"], 3)

    def test_config_and_global_random_state_unchanged(self):
        config = SimulationConfig()
        before = random.getstate()
        rows = run_replications(config, 2, master_seed=100, scenario="custom")
        self.assertEqual(config, SimulationConfig())
        self.assertEqual(before, random.getstate())
        self.assertEqual(rows[1].config, replace(config, random_seed=108))
        self.assertEqual(rows[1].scenario, "custom")

    def test_json_and_csv_record_full_configuration_and_nulls(self):
        rows = run_replications(SimulationConfig(duration_minutes=1e-12), 2)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runs.json"
            export_replications(rows, path)
            self.assertEqual(json.loads(path.read_text(encoding="utf8")), [asdict(row) for row in rows])
            path = path.with_suffix(".csv")
            export_replications(rows, path)
            with path.open(newline="", encoding="utf8") as stream:
                exported = list(csv.DictReader(stream))
            self.assertEqual(exported[1]["stream_seeds.arrivals"], "50")
            self.assertEqual(exported[0]["config.dispatch_policy"], "random")
            self.assertEqual(exported[0]["metrics.average_time_in_system"], "")

    def test_invalid_run_arguments(self):
        for kwargs in ({"count": 0}, {"count": True}, {"count": 1, "start_index": -1},
                       {"count": 1, "master_seed": True}, {"count": 1, "master_seed": 2.5}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                run_replications(SimulationConfig(), **kwargs)

    def test_invalid_seed_id_and_export(self):
        for i in (-1, True, 1.5):
            with self.subTest(i=i), self.assertRaises(ValueError):
                seed_bundle(42, i)
        with tempfile.TemporaryDirectory() as directory:
            for name in ("rows.txt", "rows.csv"):
                with self.assertRaises(ValueError):
                    export_replications([], Path(directory) / name)

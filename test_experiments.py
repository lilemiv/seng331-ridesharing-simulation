import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from contextlib import redirect_stdout
from io import StringIO

from config import SimulationConfig
from experiments import (ExperimentCell, assert_report_matches, default_design, main,
                         paired_comparison, run_experiment)
from replications import METRIC_NAMES, run_replications


class ExperimentTests(unittest.TestCase):
    def test_report_comparison_allows_only_small_float_differences(self):
        assert_report_matches({"seed": 42, "x": [1.0]}, {"seed": 42, "x": [1.0 + 1e-13]})
        for actual in ({"seed": 43, "x": [1.0]}, {"seed": 42, "x": [1.1]},
                       {"seed": 42, "x": []}, {"seed": 42}):
            with self.subTest(actual=actual), self.assertRaises(AssertionError):
                assert_report_matches(actual, {"seed": 42, "x": [1.0]})

    def test_default_design_has_baseline_and_contrasts(self):
        cells = default_design()
        self.assertEqual(len(cells), 20)
        self.assertEqual(len({c.name for c in cells}), 20)
        self.assertEqual({c.config.fleet_size for c in cells}, {5, 20, 40})
        self.assertEqual({c.config.mean_interarrival_minutes for c in cells}, {.25, .75, 1.5})
        self.assertEqual(len(default_design(include_distance_aware=False)), 10)

    def test_uniform_timing_identical_for_every_replication(self):
        config = SimulationConfig(duration_minutes=120)
        left = run_replications(config, 8)
        right = run_replications(replace(config, dispatch_policy="nearest"), 8)
        result = paired_comparison(left, right)
        for name in METRIC_NAMES[:-1]:
            self.assertEqual(result[name]["mean"], 0)
            self.assertEqual(result[name]["half_width"], 0)
        self.assertLess(result["mean_assignment_distance"]["upper"], 0)

    def test_distance_aware_preserves_separate_comparison(self):
        cells = default_design(60)[:4]
        report = run_experiment(cells, 3)
        self.assertEqual(len(report["policy_comparisons"]), 2)
        self.assertNotEqual(report["summaries"][cells[0].name]["driver_utilization"]["mean"],
                            report["summaries"][cells[2].name]["driver_utilization"]["mean"])

    def test_reproducible_whole_report(self):
        cells = default_design(30)[:2]
        self.assertEqual(run_experiment(cells, 3), run_experiment(cells, 3))

    def test_paired_difference_sign_and_standard_error(self):
        rows = run_replications(SimulationConfig(), 3)
        other = [replace(row, metrics={**row.metrics, "average_queue_delay": row.metrics["average_queue_delay"] + delta})
                 for row, delta in zip(rows, (1, 2, 3))]
        result = paired_comparison(rows, reversed(other))["average_queue_delay"]
        self.assertAlmostEqual(result["mean"], 2)
        self.assertAlmostEqual(result["standard_deviation"], 1)
        self.assertAlmostEqual(result["standard_error"], 1 / 3 ** .5)

    def test_pairing_rejects_unmatched_or_duplicate_ids_and_seeds(self):
        rows = run_replications(SimulationConfig(), 2)
        alternatives = (rows[:1], [rows[0], rows[0]],
                        run_replications(SimulationConfig(), 2, master_seed=43))
        for other in alternatives:
            with self.subTest(other=other), self.assertRaises(ValueError):
                paired_comparison(rows, other)

    def test_pairwise_missing_is_excluded(self):
        rows = run_replications(SimulationConfig(), 2)
        other = [replace(rows[0], metrics={**rows[0].metrics, "average_queue_delay": None}), rows[1]]
        result = paired_comparison(rows, other)["average_queue_delay"]
        self.assertEqual((result["n"], result["missing"]), (1, 1))
        self.assertIsNone(result["half_width"])

    def test_factor_contrasts_change_one_factor_only(self):
        report = run_experiment(default_design(10), 2)
        self.assertEqual(len(report["factor_comparisons"]), 18)
        factors = {v["factor"] for v in report["factor_comparisons"].values()}
        self.assertEqual(factors, {"fleet_size", "mean_interarrival_minutes", "pickup_mode"})
        self.assertEqual(len(report["replications"]), 20)

    def test_invalid_design(self):
        for cells in ([], [ExperimentCell("same", SimulationConfig())] * 2):
            with self.subTest(cells=cells), self.assertRaises(ValueError):
                run_experiment(cells, 2)

    def test_empty_experiment_populations_and_planning(self):
        report = run_experiment(default_design(1e-12)[:2], 2)
        self.assertIsNone(next(iter(report["beta_planning"].values())))
        for comparison in report["policy_comparisons"].values():
            self.assertEqual(comparison["abandonment_rate"]["missing"], 2)

    def test_cli_json_and_csv(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(StringIO()):
            path = Path(directory) / "report.json"
            csv_path = path.with_suffix(".csv")
            report = main(["--duration", "10", "--replications", "2", "--uniform-only",
                           "--output", str(path), "--csv", str(csv_path)])
            self.assertEqual(json.loads(path.read_text(encoding="utf8")), report)
            self.assertEqual(len(csv_path.read_text().splitlines()), 21)

"""CSV schema, ordering, round-trip, and input-preservation checks."""

import csv
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from config import SimulationConfig
from event_export import CSV_COLUMNS, export_event_history
from simulation import RideSharingSimulation


class EventExportTests(unittest.TestCase):
    def setUp(self):
        self.simulation = RideSharingSimulation(
            SimulationConfig(fleet_size=1, duration_minutes=21)
        )
        with (
            patch.object(self.simulation.rng, "expovariate", side_effect=[0, 0, 1, 99]),
            patch.object(self.simulation.patience_rng, "expovariate", return_value=100),
            patch.object(self.simulation.pickup_rng, "uniform", return_value=2),
            patch.object(self.simulation.trip_rng, "lognormvariate", return_value=8),
        ):
            self.simulation.run()
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "events.csv"

    def read_csv(self):
        with self.path.open(newline="", encoding="utf-8") as source:
            reader = csv.DictReader(source)
            return reader.fieldnames, list(reader)

    def test_all_fields_round_trip_without_mutating_history(self):
        history = self.simulation.event_history
        before = [asdict(event) for event in history]
        identities = [id(event) for event in history]
        export_event_history(history, self.path)
        headers, rows = self.read_csv()
        self.assertEqual(headers, [
            "sequence", "time", "event_type", "request_id", "request_status",
            "service_stage", "arrivals", "waiting", "in_system", "busy_drivers",
            "completed", "abandoned",
        ])
        self.assertEqual(len(rows), len(history))
        self.assertEqual(rows, [
            {key: "" if value is None else str(value) for key, value in row.items()}
            for row in before
        ])
        self.assertEqual([asdict(event) for event in history], before)
        self.assertEqual([id(event) for event in history], identities)

    def test_timestamp_and_sequence_order_including_simultaneous_events(self):
        export_event_history(self.simulation.event_history, self.path)
        _, rows = self.read_csv()
        self.assertEqual([int(row["sequence"]) for row in rows], list(range(len(rows))))
        times = [float(row["time"]) for row in rows]
        self.assertEqual(times, sorted(times))
        self.assertLess(len(set(times)), len(times))
        self.assertEqual(
            [(row["event_type"], row["request_id"]) for row in rows if float(row["time"]) == 0],
            [(event.event_type, "" if event.request_id is None else str(event.request_id))
             for event in self.simulation.event_history if event.time == 0],
        )

    def test_empty_iterable_writes_header_only(self):
        export_event_history([], self.path)
        headers, rows = self.read_csv()
        self.assertEqual(headers, list(CSV_COLUMNS))
        self.assertEqual(rows, [])

    def test_one_shot_iterable_and_string_path_are_supported(self):
        export_event_history(iter(self.simulation.event_history), str(self.path))
        _, rows = self.read_csv()
        self.assertEqual(len(rows), len(self.simulation.event_history))
        self.assertEqual(rows[0]["request_id"], "")
        self.assertEqual(rows[-1]["event_type"], "simulation_end")

    def test_zero_arrival_run_retains_boundary_markers(self):
        simulation = RideSharingSimulation(SimulationConfig(duration_minutes=0.001))
        with patch.object(simulation.rng, "expovariate", return_value=1):
            simulation.run()
        export_event_history(simulation.event_history, self.path)
        _, rows = self.read_csv()
        self.assertEqual([row["event_type"] for row in rows], ["simulation_start", "simulation_end"])
        self.assertTrue(all(row["arrivals"] == "0" for row in rows))

    def test_export_preserves_supplied_order_instead_of_sorting(self):
        events = list(reversed(self.simulation.event_history))
        export_event_history(events, self.path)
        _, rows = self.read_csv()
        self.assertEqual([int(row["sequence"]) for row in rows], [event.sequence for event in events])


if __name__ == "__main__":
    unittest.main()

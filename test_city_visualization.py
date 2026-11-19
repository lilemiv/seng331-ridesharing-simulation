"""Pure replay-state tests; no GUI display or SimPy installation required."""
import csv
import tempfile
import unittest
from pathlib import Path

from city_visualization import ReplayState, load_csv, normalize_events


FIELDS = ["sequence", "time", "event_type", "request_id", "request_status", "service_stage",
          "arrivals", "waiting", "in_system", "busy_drivers", "completed", "abandoned"]


def row(seq, time, event_type, rid, arrivals, waiting, busy, completed, abandoned):
    return dict(sequence=seq, time=time, event_type=event_type, request_id=rid,
                request_status="", service_stage="", arrivals=arrivals, waiting=waiting,
                in_system=waiting + busy, busy_drivers=busy, completed=completed, abandoned=abandoned)


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            row(0, 0, "simulation_start", "", 0, 0, 0, 0, 0),
            row(1, 1, "arrival", 1, 1, 1, 0, 0, 0),
            row(2, 1, "driver_assignment", 1, 1, 0, 1, 0, 0),
            row(3, 2, "arrival", 2, 2, 1, 1, 0, 0),
            row(4, 3, "pickup_completion", 1, 2, 1, 1, 0, 0),
            row(5, 4, "abandonment", 2, 2, 0, 1, 0, 1),
            row(6, 5, "trip_completion", 1, 2, 0, 0, 1, 1),
            row(7, 6, "simulation_end", "", 2, 0, 0, 1, 1),
        ]

    def test_full_lifecycle(self):
        state = ReplayState()
        for e in normalize_events(self.rows):
            state.apply(e)
        self.assertEqual(state.customers, {1: "completed", 2: "abandoned"})

    def test_same_time_sequence_is_preserved(self):
        events = normalize_events(self.rows)
        self.assertEqual([e.sequence for e in events], list(range(8)))
        self.assertEqual([e.time for e in events][1:3], [1, 1])

    def test_csv_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "events.csv"
            with p.open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=FIELDS)
                w.writeheader()
                w.writerows(self.rows)
            self.assertEqual(load_csv(p), normalize_events(self.rows))

    def test_invalid_transition(self):
        events = normalize_events(self.rows)
        state = ReplayState()
        with self.assertRaises(ValueError):
            state.apply(events[4])

    def test_missing_end_rejected(self):
        with self.assertRaises(ValueError):
            normalize_events(self.rows[:-1])


if __name__ == "__main__":
    unittest.main()

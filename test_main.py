"""Regression checks for the legacy CLI metrics API."""

import unittest
from unittest.mock import patch

from config import SimulationConfig
from main import calculate_simulation_metrics
from simulation import RideSharingSimulation


def controlled_run(arrivals, patience, *, duration=13, trip_duration=8):
    """Produce real engine records with fixed arrivals and service durations."""
    simulation = RideSharingSimulation(
        SimulationConfig(fleet_size=1, duration_minutes=duration)
    )
    previous = 0.0
    delays = []
    for arrival in arrivals:
        delays.append(arrival - previous)
        previous = arrival
    delays.append(duration + 1)
    with (
        patch.object(simulation.rng, "expovariate", side_effect=delays),
        patch.object(simulation.patience_rng, "expovariate", side_effect=patience),
        patch.object(simulation.pickup_rng, "uniform", return_value=2.0),
        patch.object(simulation.trip_rng, "lognormvariate", return_value=trip_duration),
    ):
        simulation.run()
    return simulation


class MainCalculationTests(unittest.TestCase):
    def test_queue_delay_excludes_abandoned_and_still_waiting_customers(self):
        simulation = controlled_run([0, 1, 2, 11], [100, 2, 100, 100])
        self.assertEqual(
            [request.status for request in simulation.requests],
            ["completed", "abandoned", "in_service", "waiting"],
        )
        result = calculate_simulation_metrics(simulation.requests)
        # Assigned at 0 and 10: delays are 0 and 8. The abandoned wait is 2.
        self.assertEqual(result["average_waiting_time"], 4.0)
        # All arrivals remain in the abandonment denominator, including waiters.
        self.assertEqual(result["abandonment_rate_percent"], 25.0)

    def test_calculations_preserve_precision(self):
        simulation = controlled_run(
            [0, 1, 2], [100, 1, 100], duration=7, trip_duration=3.25
        )
        result = calculate_simulation_metrics(simulation.requests)
        # Assigned delays are 0 and 3.25; one of three arrivals abandons.
        self.assertEqual(result["average_waiting_time"], 1.625)
        self.assertAlmostEqual(result["abandonment_rate_percent"], 100 / 3)

    def test_empty_arrivals_and_no_assignments_are_safe(self):
        for arrivals, patience, expected_abandonment in (
            ([], [], 0.0),
            ([0, 0], [0, 0], 100.0),
        ):
            with self.subTest(arrivals=arrivals):
                simulation = controlled_run(arrivals, patience, duration=1)
                self.assertTrue(all(
                    request.service_start_time is None
                    for request in simulation.requests
                ))
                result = calculate_simulation_metrics(simulation.requests)
                self.assertEqual(result["average_waiting_time"], 0.0)
                self.assertEqual(
                    result["abandonment_rate_percent"], expected_abandonment
                )


if __name__ == "__main__":
    unittest.main()

"""Exact finite-run metric examples and real-engine integration regressions."""

from collections import Counter
from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
from math import fsum
import unittest
from unittest.mock import patch

from config import SimulationConfig
from main import calculate_simulation_metrics, main as run_main
from metrics import (
    SampleMean, abandonment_rate, average_queue_delay, average_time_in_system,
    driver_utilization, time_average_number_in_system, time_average_queue_length,
)
from simulation import RideRequest, RideSharingSimulation, SimulationEvent
from test_main import controlled_run


def snapshot(sequence, time, q, b=0):
    """Construct an actual event snapshot with N=Q+B and consistent counts."""
    return SimulationEvent(sequence, time, "arrival", None, None, None,
                           q + b, q, q + b, b, 0, 0)


class RequestMetricsTests(unittest.TestCase):
    def test_empty_populations(self):
        self.assertEqual(average_queue_delay([]), SampleMean(0.0, 0))
        self.assertEqual(average_time_in_system([]), SampleMean(0.0, 0))
        self.assertEqual(abandonment_rate([]), 0.0)

    def test_immediate_assignment_at_zero_is_an_observation(self):
        request = RideRequest(1, 0.0, 5.0, service_start_time=0.0, status="in_service")
        self.assertEqual(average_queue_delay([request]), SampleMean(0.0, 1))

    def test_positive_queue_delay_and_assigned_denominator(self):
        requests = [
            RideRequest(1, 0.0, 100.0, service_start_time=0.0,
                        completion_time=10.0, status="completed"),
            RideRequest(2, 1.0, 2.0, abandonment_time=3.0, status="abandoned"),
            RideRequest(3, 2.0, 100.0, service_start_time=10.0, status="in_service"),
            RideRequest(4, 11.0, 100.0),
        ]
        self.assertEqual(average_queue_delay(iter(requests)), SampleMean(4.0, 2))
        self.assertEqual(abandonment_rate(requests), 0.25)

    def test_no_assignments(self):
        requests = [
            RideRequest(1, 1.0, 2.0, abandonment_time=3.0, status="abandoned"),
            RideRequest(2, 4.0, 10.0),
        ]
        self.assertEqual(average_queue_delay(requests), SampleMean(0.0, 0))

    def test_queue_delay_is_not_rounded(self):
        requests = [
            RideRequest(1, 0.0, 10.0, service_start_time=0.0, status="in_service"),
            RideRequest(2, 2.0, 10.0, service_start_time=5.25, status="in_service"),
        ]
        self.assertEqual(average_queue_delay(requests), SampleMean(1.625, 2))

    def test_completed_only_denominator_excludes_abandoned_and_censored(self):
        requests = [
            RideRequest(1, 0.0, 100.0, service_start_time=0.0,
                        completion_time=10.0, status="completed"),
            RideRequest(2, 1.0, 2.0, abandonment_time=3.0, status="abandoned"),
            RideRequest(3, 2.0, 100.0, service_start_time=10.0, status="in_service"),
            RideRequest(4, 11.0, 100.0),
            RideRequest(5, 3.0, 100.0, service_start_time=4.0,
                        completion_time=20.25, status="completed"),
        ]
        self.assertEqual(average_time_in_system(iter(requests)), SampleMean(13.625, 2))

    def test_unfinished_pickup_has_queue_delay_but_no_completed_system_time(self):
        request = RideRequest(1, 1.0, 100.0, service_start_time=3.0,
                              pickup_start_time=3.0, pickup_duration=2.0,
                              status="in_service")
        self.assertEqual(request.service_stage, "pickup")
        self.assertEqual(average_queue_delay([request]), SampleMean(2.0, 1))
        self.assertEqual(average_time_in_system([request]), SampleMean(0.0, 0))

    def test_unfinished_trip_has_queue_delay_but_no_completed_system_time(self):
        request = RideRequest(1, 1.0, 100.0, service_start_time=3.0,
                              pickup_start_time=3.0, pickup_completion_time=5.0,
                              trip_start_time=5.0, trip_duration=10.0,
                              status="in_service")
        self.assertEqual(request.service_stage, "trip")
        self.assertEqual(average_queue_delay([request]), SampleMean(2.0, 1))
        self.assertEqual(average_time_in_system([request]), SampleMean(0.0, 0))


class TimeAverageTests(unittest.TestCase):
    def test_event_sample_mean_is_not_time_average(self):
        history = [snapshot(0, 0, 0)]
        history += [snapshot(i, 1, 10) for i in range(1, 101)]
        history += [snapshot(101, 1, 0), snapshot(102, 2, 1)]
        self.assertAlmostEqual(time_average_queue_length(history, 3), 1 / 3)
        self.assertNotAlmostEqual(
            time_average_queue_length(history, 3),
            sum(event.waiting for event in history) / len(history),
        )

    def test_fractional_timestamp_precision(self):
        history = [snapshot(0, 0.1, 1, 1), snapshot(1, 0.2, 2, 2)]
        self.assertAlmostEqual(time_average_queue_length(history, 0.3), 1.0, places=14)
        self.assertAlmostEqual(time_average_number_in_system(history, 0.3), 2.0, places=14)
        self.assertAlmostEqual(driver_utilization(history, 0.3, 2), 0.5, places=14)

    def test_b_integral_and_capacity_denominator(self):
        # B=0 for 2 min, 1 for 3 min, 2 for 5 min: 13 driver-minutes.
        history = [snapshot(0, 2, 3, 1), snapshot(1, 5, 1, 2)]
        self.assertAlmostEqual(driver_utilization(history, 10, 2), 13 / 20)
        self.assertAlmostEqual(driver_utilization(history, 10, 4), 13 / 40)

    def test_zero_and_full_utilization(self):
        self.assertEqual(driver_utilization([snapshot(0, 0, 5)], 10, 2), 0.0)
        self.assertEqual(driver_utilization([snapshot(0, 0, 0, 2)], 10, 2), 1.0)

    def test_b_simultaneous_events_and_partial_horizon(self):
        history = [snapshot(2, 2, 0, 2), snapshot(1, 2, 0, 1), snapshot(0, 0, 0)]
        self.assertEqual(driver_utilization(iter(history), 5, 2), 0.6)

    def test_utilization_is_bounded_for_valid_histories(self):
        for busy in range(6):
            with self.subTest(busy=busy):
                result = driver_utilization([snapshot(0, 0.1, 0, busy)], 0.3, 5)
                self.assertGreaterEqual(result, 0.0)
                self.assertLessEqual(result, 1.0)

    def test_invalid_fleet_and_busy_counts_are_rejected(self):
        for fleet_size in (0, -1, 1.5, True, None):
            with self.subTest(fleet_size=fleet_size), self.assertRaises(ValueError):
                driver_utilization([], 10, fleet_size)
        for busy in (-1, 3, float("nan"), float("inf")):
            with self.subTest(busy=busy), self.assertRaises(ValueError):
                driver_utilization([snapshot(0, 0, 0, busy)], 10, 2)

    def test_n_step_integral_uses_waiting_plus_busy(self):
        # N=0 for 2 min, N=4 for 3 min, N=3 for 5 min: 27/10.
        history = [snapshot(0, 2, 3, 1), snapshot(1, 5, 1, 2)]
        self.assertAlmostEqual(time_average_number_in_system(history, 10), 2.7)

    def test_n_simultaneous_events_preserve_sequence(self):
        history = [snapshot(2, 2, 1, 1), snapshot(1, 2, 1, 0), snapshot(0, 0, 0)]
        self.assertAlmostEqual(time_average_number_in_system(history, 5), 1.2)

    def test_q_step_integral_includes_initial_and_final_intervals(self):
        # Q=0 on [0,2), 3 on [2,5), 1 on [5,10): area=9+5=14.
        history = [snapshot(0, 2, 3), snapshot(1, 5, 1)]
        self.assertEqual(time_average_queue_length(history, 10), 1.4)

    def test_same_timestamp_uses_last_sequence_not_input_order(self):
        history = [snapshot(2, 2, 1), snapshot(0, 0, 0), snapshot(1, 2, 100)]
        before = history.copy()
        self.assertEqual(time_average_queue_length(history, 5), 0.6)
        self.assertEqual(history, before)

    def test_empty_history(self):
        self.assertEqual(time_average_queue_length([], 10), 0.0)
        self.assertEqual(time_average_number_in_system([], 10), 0.0)
        self.assertEqual(driver_utilization([], 10, 2), 0.0)

    def test_zero_duration(self):
        self.assertEqual(time_average_queue_length([snapshot(0, 0, 3)], 0), 0.0)
        self.assertEqual(time_average_queue_length([], 0), 0.0)
        self.assertEqual(time_average_number_in_system([snapshot(0, 0, 3, 2)], 0), 0.0)
        self.assertEqual(driver_utilization([snapshot(0, 0, 3, 2)], 0, 2), 0.0)

    def test_horizon_clips_history_and_end_event_has_zero_area(self):
        history = [snapshot(0, 0, 2), snapshot(1, 4, 99), snapshot(2, 5, 100)]
        self.assertEqual(time_average_queue_length(iter(history), 4), 2.0)

    def test_first_event_after_horizon(self):
        self.assertEqual(time_average_queue_length([snapshot(0, 11, 2)], 10), 0.0)

    def test_invalid_horizons_and_history_fail_clearly(self):
        for horizon in (-1, float("nan"), float("inf")):
            with self.subTest(horizon=horizon), self.assertRaises(ValueError):
                time_average_queue_length([], horizon)
        for event in (snapshot(0, -1, 0), snapshot(0, float("nan"), 0),
                      snapshot(0, float("inf"), 0), snapshot(0, 0, -1)):
            with self.subTest(event=event), self.assertRaises(ValueError):
                time_average_queue_length([event], 10)


class SimulationMetricsTests(unittest.TestCase):
    def test_cli_displays_metric_populations_units_and_percentages(self):
        sim = controlled_run([0, 1, 2, 11], [100, 2, 100, 100])
        output = StringIO()
        with (patch("main.SimulationConfig", return_value=sim.config),
              patch("main.RideSharingSimulation", return_value=sim),
              patch.object(sim, "run"), redirect_stdout(output)):
            run_main()
        for line in (
            "Requests arrived: 4", "Completed: 1", "In service: 1", "Waiting: 1",
            "Abandoned: 1",
            "Average Queue Delay (assigned customers, n=2): 4.00 minutes",
            "Average Time in System (completed customers, n=1): 10.00 minutes",
            "Time-average Queue Length: 0.923", "Time-average Number in System: 1.923",
            "Driver Utilization: 100.00%", "Abandonment Rate: 25.00%",
        ):
            self.assertIn(line, output.getvalue())

    def test_real_zero_arrival_run(self):
        sim = controlled_run([], [], duration=10)
        self.assertEqual(average_queue_delay(sim.requests), SampleMean(0.0, 0))
        self.assertEqual(average_time_in_system(sim.requests), SampleMean(0.0, 0))
        self.assertEqual(time_average_queue_length(sim.event_history, 10), 0.0)
        self.assertEqual(time_average_number_in_system(sim.event_history, 10), 0.0)
        self.assertEqual(driver_utilization(sim.event_history, 10, 1), 0.0)
        self.assertEqual(abandonment_rate(sim.requests), 0.0)

    def test_real_mixed_run_matches_hand_calculated_exposures(self):
        sim = controlled_run([0, 1, 2, 11], [100, 2, 100, 100])
        self.assertEqual(average_queue_delay(sim.requests), SampleMean(4.0, 2))
        self.assertEqual(average_time_in_system(sim.requests), SampleMean(10.0, 1))
        # Q exposures: abandoned 2 + assigned 8 + still waiting 2 = 12.
        # N exposures: completed 10 + abandoned 2 + active 11 + waiting 2 = 25.
        # B exposures: first customer 10 + active customer 3 = 13.
        self.assertAlmostEqual(time_average_queue_length(sim.event_history, 13), 12 / 13)
        self.assertAlmostEqual(time_average_number_in_system(sim.event_history, 13), 25 / 13)
        self.assertEqual(driver_utilization(sim.event_history, 13, 1), 1.0)
        self.assertEqual(abandonment_rate(sim.requests), 0.25)
        sim.validate_invariants()

    def test_real_unfinished_pickup_includes_partial_service(self):
        sim = controlled_run([0], [100], duration=1)
        self.assertEqual(sim.requests[0].service_stage, "pickup")
        self.assertEqual(average_queue_delay(sim.requests), SampleMean(0.0, 1))
        self.assertEqual(average_time_in_system(sim.requests), SampleMean(0.0, 0))
        self.assertEqual(time_average_number_in_system(sim.event_history, 1), 1.0)
        self.assertEqual(driver_utilization(sim.event_history, 1, 1), 1.0)

    def test_real_unfinished_trip_includes_pickup_and_partial_trip(self):
        sim = controlled_run([0], [100], duration=5)
        self.assertEqual(sim.requests[0].service_stage, "trip")
        self.assertEqual(average_queue_delay(sim.requests), SampleMean(0.0, 1))
        self.assertEqual(average_time_in_system(sim.requests), SampleMean(0.0, 0))
        self.assertEqual(time_average_number_in_system(sim.event_history, 5), 1.0)
        self.assertEqual(driver_utilization(sim.event_history, 5, 1), 1.0)

    def test_waiter_expiring_at_horizon_remains_censored(self):
        sim = controlled_run([0, 1], [100, 2], duration=3)
        self.assertEqual(sim.requests[1].status, "waiting")
        self.assertEqual(average_queue_delay(sim.requests), SampleMean(0.0, 1))
        self.assertEqual(average_time_in_system(sim.requests), SampleMean(0.0, 0))
        self.assertAlmostEqual(time_average_queue_length(sim.event_history, 3), 2 / 3)
        self.assertAlmostEqual(time_average_number_in_system(sim.event_history, 3), 5 / 3)
        self.assertEqual(abandonment_rate(sim.requests), 0.0)

    def test_completion_exactly_at_horizon_remains_censored(self):
        sim = controlled_run([0], [100], duration=10)
        self.assertIsNone(sim.requests[0].completion_time)
        self.assertEqual(average_time_in_system(sim.requests), SampleMean(0.0, 0))
        self.assertEqual(driver_utilization(sim.event_history, 10, 1), 1.0)

    def test_pickup_completion_at_horizon_remains_censored(self):
        sim = controlled_run([0], [100], duration=2)
        self.assertIsNone(sim.requests[0].pickup_completion_time)
        self.assertEqual(average_time_in_system(sim.requests), SampleMean(0.0, 0))
        self.assertEqual(driver_utilization(sim.event_history, 2, 1), 1.0)

    def measure(self, sim):
        return (
            average_queue_delay(sim.requests), average_time_in_system(sim.requests),
            time_average_queue_length(sim.event_history, sim.env.now),
            time_average_number_in_system(sim.event_history, sim.env.now),
            driver_utilization(sim.event_history, sim.env.now, sim.config.fleet_size),
            abandonment_rate(sim.requests),
        )

    def test_seeded_runs_match_independent_request_interval_sums(self):
        for config in (SimulationConfig(), SimulationConfig(fleet_size=2),
                       SimulationConfig(fleet_size=40)):
            with self.subTest(fleet_size=config.fleet_size):
                sim = RideSharingSimulation(config)
                sim.run()
                horizon = sim.env.now
                # Independent oracle: customer timestamp intervals, no event history.
                queue_exposure, system_exposure, busy_exposure = [], [], []
                for request in sim.requests:
                    departure = (request.completion_time if request.completion_time is not None
                                 else request.abandonment_time if request.abandonment_time is not None
                                 else horizon)
                    assignment = request.driver_assignment_time
                    queue_end = assignment if assignment is not None else departure
                    queue_exposure.append(queue_end - request.arrival_time)
                    system_exposure.append(departure - request.arrival_time)
                    if assignment is not None:
                        busy_exposure.append(departure - assignment)
                result = self.measure(sim)
                self.assertAlmostEqual(result[2], fsum(queue_exposure) / horizon, places=12)
                self.assertAlmostEqual(result[3], fsum(system_exposure) / horizon, places=12)
                self.assertAlmostEqual(result[4], fsum(busy_exposure) / horizon / config.fleet_size,
                                       places=12)
                self.assertAlmostEqual(result[3], result[2] + config.fleet_size * result[4],
                                       places=12)
                self.assertGreaterEqual(result[4], 0.0)
                self.assertLessEqual(result[4], 1.0)
                counts = Counter(r.status for r in sim.requests)
                self.assertEqual(len(sim.requests), sum(counts.values()))
                sim.validate_invariants()

    def test_reproducibility_and_metrics_do_not_change_engine_or_rngs(self):
        config = SimulationConfig(fleet_size=2)
        first, second = RideSharingSimulation(config), RideSharingSimulation(config)
        first.run()
        second.run()
        before = deepcopy((first.requests, first.event_history))
        streams = (first.rng, first.patience_rng, first.pickup_rng, first.trip_rng)
        rng_states = [rng.getstate() for rng in streams]
        self.assertEqual(self.measure(first), self.measure(second))
        self.assertEqual((first.requests, first.event_history), before)
        self.assertEqual([rng.getstate() for rng in streams], rng_states)
        self.assertEqual(first.requests, second.requests)
        self.assertEqual(first.event_history, second.event_history)
        self.assertEqual(first.env.now, config.duration_minutes)
        first.validate_invariants()

    def test_week1_values_and_legacy_import_remain_compatible(self):
        sim = controlled_run([0, 1, 2], [100, 1, 100], duration=7, trip_duration=3.25)
        old_result = calculate_simulation_metrics(sim.requests)
        assigned = [r for r in sim.requests if r.service_start_time is not None]
        expected_delay = sum(r.service_start_time - r.arrival_time for r in assigned) / len(assigned)
        self.assertEqual(average_queue_delay(sim.requests).mean, expected_delay)
        self.assertEqual(old_result["average_waiting_time"], expected_delay)
        self.assertAlmostEqual(abandonment_rate(sim.requests) * 100,
                               old_result["abandonment_rate_percent"])
        self.assertEqual(set(old_result), {"average_waiting_time", "abandonment_rate_percent"})


if __name__ == "__main__":
    unittest.main()

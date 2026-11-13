"""Core simulation regression checks. Run with: python -m unittest -v"""

from collections import Counter
from dataclasses import FrozenInstanceError, asdict, replace
from math import exp, isfinite, log
import random
import unittest
from unittest.mock import call, patch

from config import SimulationConfig
from simulation import RideSharingSimulation


class DriverPoolTests(unittest.TestCase):
    def run_with_arrivals(
        self,
        arrival_times: list[float],
        *,
        fleet_size: int = 1,
        duration: float = 31.0,
        patience_times: list[float] | None = None,
        pickup_duration: float = 2.0,
        trip_duration: float = 8.0,
    ) -> RideSharingSimulation:
        """Control arrivals while exercising the real arrival/customer processes."""
        simulation = RideSharingSimulation(
            SimulationConfig(fleet_size=fleet_size, duration_minutes=duration)
        )
        previous_time = 0.0
        delays = []
        for arrival_time in arrival_times:
            delays.append(arrival_time - previous_time)
            previous_time = arrival_time
        # The final delay puts the next arrival beyond the test's horizon.
        delays.append(duration + 1.0)
        if patience_times is None:
            # Preserve the Step 2 scenarios: nobody abandons during those runs.
            patience_times = [duration + 1.0] * len(arrival_times)
        with (
            patch.object(simulation.rng, "expovariate", side_effect=delays),
            patch.object(
                simulation.patience_rng, "expovariate", side_effect=patience_times
            ),
            # Existing 10-minute regression scenarios now exercise both stages.
            patch.object(simulation.pickup_rng, "uniform", return_value=pickup_duration),
            patch.object(simulation.trip_rng, "lognormvariate", return_value=trip_duration),
        ):
            simulation.run()
        return simulation

    def test_default_fleet_has_twenty_drivers(self):
        simulation = RideSharingSimulation(SimulationConfig())
        self.assertEqual(simulation.driver_pool.capacity, 20)

    def test_invalid_fleet_sizes_are_rejected(self):
        for fleet_size in (0, -1, 1.5, True, "20", None):
            with self.subTest(fleet_size=fleet_size):
                with self.assertRaises(ValueError):
                    SimulationConfig(fleet_size=fleet_size)

    def test_requests_start_immediately_when_capacity_is_available(self):
        simulation = self.run_with_arrivals([0.0, 1.0], fleet_size=2, duration=12)
        self.assertEqual(len(simulation.requests), 2)
        for request in simulation.requests:
            self.assertEqual(request.service_start_time, request.arrival_time)
            self.assertEqual(request.completion_time, request.arrival_time + 10.0)

    def test_request_waits_when_all_drivers_are_busy(self):
        simulation = self.run_with_arrivals([0.0, 1.0], duration=2)
        first, second = simulation.requests
        self.assertEqual(first.service_start_time, 0.0)
        self.assertIsNone(second.service_start_time)
        self.assertIsNone(second.completion_time)
        self.assertEqual(simulation.driver_pool.count, 1)
        self.assertEqual(len(simulation.driver_pool.queue), 1)

    def test_waiting_requests_start_in_fifo_order(self):
        simulation = self.run_with_arrivals([0.0, 1.0, 2.0, 3.0], duration=41)
        self.assertEqual(
            [r.service_start_time for r in simulation.requests],
            [0.0, 10.0, 20.0, 30.0],
        )
        self.assertEqual(
            [r.completion_time for r in simulation.requests],
            [10.0, 20.0, 30.0, 40.0],
        )

    def test_simultaneous_arrivals_keep_fifo_order(self):
        simulation = self.run_with_arrivals([0.0, 0.0, 0.0])
        self.assertEqual(
            [r.service_start_time for r in simulation.requests],
            [0.0, 10.0, 20.0],
        )

    def test_driver_is_released_and_reused_after_service(self):
        simulation = self.run_with_arrivals([0.0, 1.0], duration=21)
        first, second = simulation.requests
        self.assertEqual(first.completion_time, 10.0)
        self.assertEqual(second.service_start_time, first.completion_time)
        self.assertEqual(second.completion_time, 20.0)
        self.assertEqual(simulation.driver_pool.count, 0)
        self.assertEqual(len(simulation.driver_pool.queue), 0)

    def test_active_service_never_exceeds_fleet_capacity(self):
        simulation = RideSharingSimulation(
            SimulationConfig(
                mean_interarrival_minutes=0.1,
                fleet_size=3,
                duration_minutes=35.0,
            )
        )
        peak_active = 0
        queue_observed = False
        # Inspect after every SimPy event, including acquisitions and releases.
        while simulation.env.peek() < simulation.config.duration_minutes:
            simulation.env.step()
            active = sum(
                r.service_start_time is not None and r.completion_time is None
                for r in simulation.requests
            )
            self.assertLessEqual(active, simulation.config.fleet_size)
            self.assertLessEqual(
                simulation.driver_pool.count, simulation.config.fleet_size
            )
            peak_active = max(peak_active, active)
            queue_observed |= bool(simulation.driver_pool.queue)
        self.assertEqual(peak_active, 3)
        self.assertTrue(queue_observed)

    def test_arrival_history_is_separate_from_active_queue(self):
        simulation = self.run_with_arrivals([0.0, 1.0, 2.0], duration=15)
        first, second, third = simulation.requests
        self.assertEqual(first.completion_time, 10.0)
        self.assertEqual(second.service_start_time, 10.0)
        self.assertIsNone(second.completion_time)
        self.assertIsNone(third.service_start_time)
        self.assertIsNone(third.completion_time)
        self.assertEqual(len(simulation.requests), 3)  # Full history remains.
        self.assertEqual(simulation.driver_pool.count, 1)
        self.assertEqual(len(simulation.driver_pool.queue), 1)  # Only the waiter.

    def test_results_are_reproducible_with_same_seed(self):
        # A small fleet ensures reproducibility also covers waiting customers.
        config = SimulationConfig(fleet_size=2, random_seed=42)
        first = RideSharingSimulation(config)
        second = RideSharingSimulation(config)
        first.run()
        second.run()
        # Dataclass equality compares IDs, all recorded times, and statuses.
        self.assertEqual(first.requests, second.requests)
        self.assertEqual(first.driver_pool.count, second.driver_pool.count)
        self.assertEqual(len(first.driver_pool.queue), len(second.driver_pool.queue))
        self.assertTrue(any(r.completion_time is not None for r in first.requests))
        self.assertGreater(len(first.driver_pool.queue), 0)

    def assert_consistent(self, simulation: RideSharingSimulation) -> None:
        """Check the request ledger against the resource at a settled run end."""
        counts = Counter(r.status for r in simulation.requests)
        self.assertLessEqual(
            set(counts), {"waiting", "in_service", "completed", "abandoned"}
        )
        self.assertEqual(
            [r.request_id for r in simulation.requests],
            list(range(1, len(simulation.requests) + 1)),
        )
        self.assertEqual(counts["waiting"], len(simulation.driver_pool.queue))
        self.assertEqual(counts["in_service"], simulation.driver_pool.count)
        self.assertLessEqual(counts["in_service"], simulation.config.fleet_size)

        for request in simulation.requests:
            with self.subTest(request_id=request.request_id):
                self.assertGreaterEqual(request.arrival_time, 0.0)
                self.assertLess(request.arrival_time, simulation.env.now)
                self.assertGreaterEqual(request.patience_time, 0.0)
                deadline = request.arrival_time + request.patience_time
                if request.status in {"waiting", "abandoned"}:
                    self.assertIsNone(request.service_start_time)
                    self.assertIsNone(request.completion_time)
                    for value in (
                        request.pickup_start_time, request.pickup_completion_time,
                        request.trip_start_time, request.pickup_duration,
                        request.trip_duration, request.service_stage,
                    ):
                        self.assertIsNone(value)
                    if request.status == "waiting":
                        self.assertIsNone(request.abandonment_time)
                        self.assertGreaterEqual(deadline, simulation.env.now)
                    else:
                        self.assertAlmostEqual(request.abandonment_time, deadline)
                        self.assertLess(request.abandonment_time, simulation.env.now)
                else:
                    self.assertIsNone(request.abandonment_time)
                    self.assertIsNotNone(request.service_start_time)
                    self.assertGreaterEqual(
                        request.service_start_time, request.arrival_time
                    )
                    self.assertLess(request.service_start_time, deadline)
                    self.assertLess(request.service_start_time, simulation.env.now)
                    self.assertEqual(
                        request.driver_assignment_time, request.service_start_time
                    )
                    self.assertEqual(
                        request.pickup_start_time, request.service_start_time
                    )
                    self.assertGreaterEqual(
                        request.pickup_duration, simulation.config.pickup_min_minutes
                    )
                    self.assertLessEqual(
                        request.pickup_duration, simulation.config.pickup_max_minutes
                    )
                    if request.pickup_completion_time is None:
                        self.assertEqual(request.service_stage, "pickup")
                        self.assertIsNone(request.trip_start_time)
                        self.assertIsNone(request.trip_duration)
                        self.assertGreaterEqual(
                            request.pickup_start_time + request.pickup_duration,
                            simulation.env.now,
                        )
                    else:
                        self.assertAlmostEqual(
                            request.pickup_completion_time - request.pickup_start_time,
                            request.pickup_duration,
                        )
                        self.assertEqual(
                            request.trip_start_time, request.pickup_completion_time
                        )
                        self.assertGreater(request.trip_duration, 0.0)
                        self.assertTrue(isfinite(request.trip_duration))
                    if request.status == "in_service":
                        self.assertIsNone(request.completion_time)
                        if request.trip_start_time is not None:
                            self.assertEqual(request.service_stage, "trip")
                            self.assertGreaterEqual(
                                request.trip_start_time + request.trip_duration,
                                simulation.env.now,
                            )
                    else:
                        self.assertIsNotNone(request.completion_time)
                        self.assertAlmostEqual(
                            request.completion_time - request.trip_start_time,
                            request.trip_duration,
                        )
                        self.assertEqual(
                            request.trip_completion_time, request.completion_time
                        )
                        self.assertIsNone(request.service_stage)
                        self.assertLess(request.completion_time, simulation.env.now)

    def test_patience_mean_default_and_inclusive_bounds(self):
        self.assertEqual(SimulationConfig().mean_patience_minutes, 5.0)
        for mean in (3.0, 8.0):
            with self.subTest(mean=mean):
                self.assertEqual(
                    SimulationConfig(mean_patience_minutes=mean).mean_patience_minutes,
                    mean,
                )

    def test_invalid_patience_means_are_rejected(self):
        for mean in (0, -1, 2.99, 8.01, float("nan"), float("inf")):
            with self.subTest(mean=mean):
                with self.assertRaises(ValueError):
                    SimulationConfig(mean_patience_minutes=mean)

    def test_invalid_arrival_and_duration_settings_remain_rejected(self):
        for field in ("mean_interarrival_minutes", "duration_minutes"):
            for value in (0, -1, float("nan"), float("inf"), -float("inf")):
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ValueError):
                        SimulationConfig(**{field: value})

    def test_patience_is_sampled_once_for_every_arrival(self):
        simulation = RideSharingSimulation(
            SimulationConfig(fleet_size=3, duration_minutes=3)
        )
        with (
            patch.object(simulation.rng, "expovariate", side_effect=[0, 1, 1, 99]),
            patch.object(
                simulation.patience_rng, "expovariate", side_effect=[0.1, 25.0, 4.0]
            ) as patience_sampler,
        ):
            simulation.run()
        self.assertEqual(
            [r.patience_time for r in simulation.requests], [0.1, 25.0, 4.0]
        )
        self.assertEqual(patience_sampler.call_args_list, [call(1.0 / 5.0)] * 3)
        self.assert_consistent(simulation)

    def test_arrival_stream_is_preserved_and_patience_has_its_own_stream(self):
        config = SimulationConfig()
        simulation = RideSharingSimulation(config)
        simulation.run()
        arrival_rng = random.Random(config.random_seed)
        patience_rng = random.Random(config.random_seed + 1)
        arrival_time = 0.0
        for request in simulation.requests:
            arrival_time += arrival_rng.expovariate(
                1.0 / config.mean_interarrival_minutes
            )
            self.assertEqual(request.arrival_time, arrival_time)
            self.assertEqual(
                request.patience_time,
                patience_rng.expovariate(1.0 / config.mean_patience_minutes),
            )
        self.assertEqual(len(simulation.requests), 86)
        self.assert_consistent(simulation)

    def test_immediate_service_is_not_abandoned_during_service(self):
        simulation = self.run_with_arrivals(
            [0.0], duration=11, patience_times=[0.1]
        )
        request = simulation.requests[0]
        self.assertEqual(request.service_start_time, 0.0)
        self.assertEqual(request.completion_time, 10.0)
        self.assertIsNone(request.abandonment_time)
        self.assertEqual(request.status, "completed")
        self.assert_consistent(simulation)

    def test_waiting_customer_abandons_at_deadline_and_leaves_queue(self):
        simulation = self.run_with_arrivals(
            [0.0, 1.0], duration=4, patience_times=[50.0, 2.0]
        )
        first, second = simulation.requests
        self.assertEqual(first.status, "in_service")
        self.assertEqual(second.status, "abandoned")
        self.assertEqual(second.abandonment_time, 3.0)
        self.assertIsNone(second.service_start_time)
        self.assertIsNone(second.completion_time)
        self.assertEqual(len(simulation.driver_pool.queue), 0)
        self.assertEqual(simulation.driver_pool.count, 1)
        self.assert_consistent(simulation)

    def test_abandoned_customer_never_receives_a_driver_later(self):
        simulation = self.run_with_arrivals(
            [0.0, 1.0, 12.0], duration=25, patience_times=[50.0, 2.0, 50.0]
        )
        first, abandoned, later = simulation.requests
        self.assertEqual(first.completion_time, 10.0)
        self.assertEqual(abandoned.status, "abandoned")
        self.assertEqual(abandoned.abandonment_time, 3.0)
        self.assertIsNone(abandoned.service_start_time)
        self.assertIsNone(abandoned.completion_time)
        self.assertEqual(later.service_start_time, 12.0)
        self.assertEqual(later.completion_time, 22.0)
        self.assertEqual(simulation.driver_pool.count, 0)
        self.assert_consistent(simulation)

    def test_assignment_before_expiry_prevents_later_abandonment(self):
        simulation = self.run_with_arrivals(
            [0.0, 1.0], duration=21, patience_times=[0.1, 9.001]
        )
        second = simulation.requests[1]
        self.assertEqual(second.service_start_time, 10.0)
        self.assertEqual(second.completion_time, 20.0)
        self.assertIsNone(second.abandonment_time)
        self.assertEqual(second.status, "completed")
        self.assert_consistent(simulation)

    def test_fifo_survives_abandonment_of_a_waiter(self):
        simulation = self.run_with_arrivals(
            [0.0, 1.0, 2.0, 3.0], patience_times=[100.0, 2.0, 50.0, 50.0]
        )
        self.assertEqual(
            [r.service_start_time for r in simulation.requests],
            [0.0, None, 10.0, 20.0],
        )
        self.assertEqual(simulation.requests[1].abandonment_time, 3.0)
        self.assert_consistent(simulation)

    def test_later_waiter_can_abandon_before_fifo_head(self):
        simulation = self.run_with_arrivals(
            [0.0, 1.0, 2.0, 3.0], patience_times=[100.0, 50.0, 1.0, 50.0]
        )
        self.assertEqual(
            [r.service_start_time for r in simulation.requests],
            [0.0, 10.0, None, 20.0],
        )
        self.assertEqual(simulation.requests[2].abandonment_time, 3.0)
        self.assert_consistent(simulation)

    def test_expiry_wins_exact_tie_with_driver_availability(self):
        simulation = self.run_with_arrivals(
            [0.0, 1.0, 11.0], duration=22, patience_times=[100.0, 9.0, 100.0]
        )
        first, abandoned, later = simulation.requests
        self.assertEqual(first.completion_time, 10.0)
        self.assertEqual(abandoned.abandonment_time, 10.0)
        self.assertEqual(abandoned.status, "abandoned")
        self.assertIsNone(abandoned.service_start_time)
        self.assertEqual(later.service_start_time, 11.0)
        self.assertEqual(later.completion_time, 21.0)
        self.assert_consistent(simulation)

    def test_expiry_just_before_driver_availability(self):
        simulation = self.run_with_arrivals(
            [0.0, 1.0], duration=21, patience_times=[100.0, 8.999]
        )
        request = simulation.requests[1]
        self.assertEqual(request.status, "abandoned")
        self.assertAlmostEqual(request.abandonment_time, 9.999)
        self.assertIsNone(request.service_start_time)
        self.assert_consistent(simulation)

    def test_zero_patience_releases_an_immediately_granted_driver(self):
        simulation = self.run_with_arrivals(
            [0.0, 0.0], duration=11, patience_times=[0.0, 100.0]
        )
        abandoned, survivor = simulation.requests
        self.assertEqual(abandoned.status, "abandoned")
        self.assertEqual(abandoned.abandonment_time, 0.0)
        self.assertIsNone(abandoned.service_start_time)
        self.assertEqual(survivor.service_start_time, 0.0)
        self.assertEqual(survivor.completion_time, 10.0)
        self.assert_consistent(simulation)

    def test_simultaneous_abandonments_do_not_block_surviving_waiter(self):
        simulation = self.run_with_arrivals(
            [0.0, 1.0, 1.0, 1.0, 3.0],
            duration=21,
            patience_times=[100.0, 2.0, 2.0, 2.0, 100.0],
        )
        for request in simulation.requests[1:4]:
            self.assertEqual(request.status, "abandoned")
            self.assertEqual(request.abandonment_time, 3.0)
            self.assertIsNone(request.service_start_time)
        survivor = simulation.requests[4]
        self.assertEqual(survivor.service_start_time, 10.0)
        self.assertEqual(survivor.completion_time, 20.0)
        self.assert_consistent(simulation)

    def test_expiry_at_run_horizon_is_not_processed(self):
        simulation = self.run_with_arrivals(
            [0.0, 1.0], duration=3, patience_times=[100.0, 2.0]
        )
        second = simulation.requests[1]
        self.assertEqual(second.status, "waiting")
        self.assertIsNone(second.abandonment_time)
        self.assertEqual(len(simulation.driver_pool.queue), 1)
        self.assert_consistent(simulation)

    def test_run_can_end_before_any_arrival(self):
        simulation = RideSharingSimulation(SimulationConfig(duration_minutes=0.001))
        simulation.run()
        self.assertEqual(simulation.requests, [])
        self.assert_consistent(simulation)

    def test_all_timestamps_statuses_and_counts_are_consistent(self):
        simulation = RideSharingSimulation(
            SimulationConfig(
                fleet_size=2, mean_interarrival_minutes=0.25, duration_minutes=35
            )
        )
        simulation.run()
        self.assertEqual(
            {r.status for r in simulation.requests},
            {"waiting", "in_service", "completed", "abandoned"},
        )
        self.assert_consistent(simulation)

    def test_status_transitions_never_reverse(self):
        simulation = RideSharingSimulation(
            SimulationConfig(
                fleet_size=1, mean_interarrival_minutes=0.1, duration_minutes=25
            )
        )
        transitions = {
            "waiting": {"waiting", "in_service", "abandoned"},
            "in_service": {"in_service", "completed"},
            "completed": {"completed"},
            "abandoned": {"abandoned"},
        }
        previous = {}
        seen = set()
        while simulation.env.peek() < simulation.config.duration_minutes:
            simulation.env.step()
            for request in simulation.requests:
                old_status = previous.get(request.request_id, "waiting")
                self.assertIn(request.status, transitions[old_status])
                previous[request.request_id] = request.status
                seen.add(request.status)
        self.assertEqual(seen, set(transitions))
        simulation.run()
        self.assert_consistent(simulation)

    def test_simulation_does_not_change_global_random_state(self):
        state = random.getstate()
        simulation = RideSharingSimulation(SimulationConfig())
        simulation.run()
        self.assertEqual(random.getstate(), state)

    def test_trip_parameters_give_requested_arithmetic_mean(self):
        config = SimulationConfig()
        self.assertEqual(config.trip_mean_minutes, 10.0)
        self.assertEqual(config.trip_sigma, 0.5)
        self.assertAlmostEqual(config.trip_mu, log(10.0) - 0.5 ** 2 / 2.0)
        self.assertAlmostEqual(
            exp(config.trip_mu + config.trip_sigma ** 2 / 2.0), 10.0
        )
        custom = SimulationConfig(trip_mean_minutes=12.0, trip_sigma=0.8)
        self.assertAlmostEqual(
            exp(custom.trip_mu + custom.trip_sigma ** 2 / 2.0), 12.0
        )

    def test_invalid_pickup_limits_are_rejected(self):
        for lower, upper in (
            (0, 8), (-1, 8), (8, 2), (2, float("inf")),
            (float("nan"), 8), (2, float("nan")),
        ):
            with self.subTest(lower=lower, upper=upper):
                with self.assertRaises(ValueError):
                    SimulationConfig(pickup_min_minutes=lower, pickup_max_minutes=upper)

    def test_invalid_trip_parameters_are_rejected(self):
        invalid_values = {
            "trip_mean_minutes": (0, -1, float("nan"), float("inf")),
            "trip_sigma": (-1, float("nan"), float("inf"), 1e308),
        }
        for field, values in invalid_values.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ValueError):
                        SimulationConfig(**{field: value})

    def test_pickup_samples_use_configured_uniform_limits(self):
        simulation = RideSharingSimulation(
            SimulationConfig(pickup_min_minutes=1.0, pickup_max_minutes=1.25)
        )
        simulation.run()
        durations = [
            r.pickup_duration for r in simulation.requests if r.pickup_duration is not None
        ]
        self.assertTrue(durations)
        self.assertTrue(all(1.0 <= duration <= 1.25 for duration in durations))
        self.assert_consistent(simulation)

    def test_real_trip_samples_are_finite_and_strictly_positive(self):
        simulation = RideSharingSimulation(SimulationConfig())
        simulation.run()
        durations = [
            r.trip_duration for r in simulation.requests if r.trip_duration is not None
        ]
        self.assertTrue(durations)
        self.assertTrue(all(isfinite(duration) and duration > 0 for duration in durations))
        self.assert_consistent(simulation)

    def test_equal_pickup_limits_and_zero_trip_sigma_are_supported(self):
        simulation = RideSharingSimulation(
            SimulationConfig(pickup_min_minutes=2, pickup_max_minutes=2, trip_sigma=0)
        )
        simulation.run()
        self.assertTrue(simulation.requests)
        for request in simulation.requests:
            if request.pickup_duration is not None:
                self.assertEqual(request.pickup_duration, 2.0)
            if request.trip_duration is not None:
                self.assertAlmostEqual(request.trip_duration, 10.0)
        self.assert_consistent(simulation)

    def test_pickup_precedes_trip_and_all_timestamps_are_recorded(self):
        simulation = self.run_with_arrivals(
            [0.0], duration=11, pickup_duration=3.0, trip_duration=7.0
        )
        request = simulation.requests[0]
        self.assertEqual(request.driver_assignment_time, 0.0)
        self.assertEqual(request.service_start_time, 0.0)
        self.assertEqual(request.pickup_start_time, 0.0)
        self.assertEqual(request.pickup_completion_time, 3.0)
        self.assertEqual(request.trip_start_time, 3.0)
        self.assertEqual(request.trip_completion_time, 10.0)
        self.assertEqual(request.completion_time, 10.0)
        self.assertEqual(request.status, "completed")
        self.assert_consistent(simulation)

    def test_driver_remains_busy_during_unfinished_pickup(self):
        simulation = self.run_with_arrivals(
            [0.0, 1.0], duration=3, pickup_duration=4.0, trip_duration=6.0
        )
        first, second = simulation.requests
        self.assertEqual(first.status, "in_service")
        self.assertEqual(first.service_stage, "pickup")
        self.assertIsNone(first.pickup_completion_time)
        self.assertIsNone(first.trip_start_time)
        self.assertIsNone(first.trip_duration)
        self.assertIsNone(first.completion_time)
        self.assertEqual(second.status, "waiting")
        self.assertEqual(simulation.driver_pool.count, 1)
        self.assert_consistent(simulation)

    def test_driver_remains_busy_during_unfinished_trip(self):
        simulation = self.run_with_arrivals([0.0, 1.0], duration=5)
        first, second = simulation.requests
        self.assertEqual(first.service_stage, "trip")
        self.assertEqual(first.pickup_completion_time, 2.0)
        self.assertEqual(first.trip_start_time, 2.0)
        self.assertIsNone(first.trip_completion_time)
        self.assertEqual(second.status, "waiting")
        self.assertEqual(simulation.driver_pool.count, 1)
        self.assert_consistent(simulation)

    def test_driver_release_after_trip_starts_waiting_customer(self):
        simulation = self.run_with_arrivals(
            [0.0, 1.0], duration=27, pickup_duration=4.0, trip_duration=9.0
        )
        first, second = simulation.requests
        self.assertEqual(first.pickup_completion_time, 4.0)
        self.assertEqual(first.trip_completion_time, 13.0)
        self.assertEqual(second.driver_assignment_time, 13.0)
        self.assertEqual(second.pickup_start_time, 13.0)
        self.assertEqual(second.trip_completion_time, 26.0)
        self.assertEqual(simulation.driver_pool.count, 0)
        self.assert_consistent(simulation)

    def test_abandoned_customer_never_enters_pickup_or_trip(self):
        simulation = self.run_with_arrivals(
            [0.0, 1.0], duration=12, patience_times=[100.0, 1.0]
        )
        abandoned = simulation.requests[1]
        self.assertEqual(abandoned.status, "abandoned")
        self.assertEqual(abandoned.abandonment_time, 2.0)
        for value in (
            abandoned.driver_assignment_time, abandoned.pickup_start_time,
            abandoned.pickup_completion_time, abandoned.trip_start_time,
            abandoned.trip_completion_time, abandoned.pickup_duration,
            abandoned.trip_duration,
        ):
            self.assertIsNone(value)
        self.assert_consistent(simulation)

    def test_pickup_completion_at_horizon_is_not_processed(self):
        simulation = self.run_with_arrivals([0.0], duration=2)
        request = simulation.requests[0]
        self.assertEqual(request.service_stage, "pickup")
        self.assertIsNone(request.pickup_completion_time)
        self.assertIsNone(request.trip_start_time)
        self.assertIsNone(request.trip_duration)
        self.assertEqual(simulation.driver_pool.count, 1)
        self.assert_consistent(simulation)

    def test_trip_completion_at_horizon_is_not_processed(self):
        simulation = self.run_with_arrivals([0.0], duration=10)
        request = simulation.requests[0]
        self.assertEqual(request.service_stage, "trip")
        self.assertIsNone(request.trip_completion_time)
        self.assertEqual(request.status, "in_service")
        self.assertEqual(simulation.driver_pool.count, 1)
        self.assert_consistent(simulation)

    def test_simultaneous_trip_completions_release_both_drivers(self):
        simulation = self.run_with_arrivals(
            [0.0, 0.0, 1.0, 1.0], fleet_size=2, duration=21
        )
        self.assertEqual(
            [r.driver_assignment_time for r in simulation.requests],
            [0.0, 0.0, 10.0, 10.0],
        )
        self.assertEqual(
            [r.trip_completion_time for r in simulation.requests],
            [10.0, 10.0, 20.0, 20.0],
        )
        self.assertEqual(simulation.driver_pool.count, 0)
        self.assert_consistent(simulation)

    def test_service_samples_are_drawn_only_when_their_stage_starts(self):
        simulation = RideSharingSimulation(
            SimulationConfig(fleet_size=1, duration_minutes=3)
        )
        with (
            patch.object(simulation.rng, "expovariate", side_effect=[0, 1, 1, 99]),
            patch.object(
                simulation.patience_rng, "expovariate", side_effect=[100, 0, 100]
            ),
            patch.object(simulation.pickup_rng, "uniform", return_value=5) as pickup,
            patch.object(simulation.trip_rng, "lognormvariate") as trip,
        ):
            simulation.run()
        pickup.assert_called_once_with(2.0, 8.0)
        trip.assert_not_called()
        self.assertEqual(
            [r.status for r in simulation.requests],
            ["in_service", "abandoned", "waiting"],
        )
        self.assert_consistent(simulation)

    def test_patience_expiry_during_either_service_stage_is_ignored(self):
        for patience in (1.0, 5.0):
            with self.subTest(patience=patience):
                simulation = self.run_with_arrivals(
                    [0.0], duration=11, patience_times=[patience],
                    pickup_duration=4.0, trip_duration=6.0,
                )
                request = simulation.requests[0]
                self.assertEqual(request.status, "completed")
                self.assertEqual(request.trip_completion_time, 10.0)
                self.assertIsNone(request.abandonment_time)
                self.assert_consistent(simulation)

    def test_service_parameter_changes_preserve_arrivals_and_patience(self):
        baseline = RideSharingSimulation(SimulationConfig())
        changed = RideSharingSimulation(
            SimulationConfig(
                pickup_min_minutes=3, pickup_max_minutes=5,
                trip_mean_minutes=20, trip_sigma=0.8,
            )
        )
        baseline.run()
        changed.run()
        self.assertEqual(
            [(r.request_id, r.arrival_time, r.patience_time) for r in baseline.requests],
            [(r.request_id, r.arrival_time, r.patience_time) for r in changed.requests],
        )
        self.assert_consistent(baseline)
        self.assert_consistent(changed)

    def test_pickup_and_trip_have_separate_reproducible_random_streams(self):
        config = SimulationConfig()
        simulation = RideSharingSimulation(config)
        simulation.run()
        pickup_rng = random.Random(config.random_seed + 2)
        trip_rng = random.Random(config.random_seed + 3)
        pickups = sorted(
            (r for r in simulation.requests if r.pickup_start_time is not None),
            key=lambda r: (r.pickup_start_time, r.request_id),
        )
        trips = sorted(
            (r for r in simulation.requests if r.trip_start_time is not None),
            key=lambda r: (r.trip_start_time, r.request_id),
        )
        self.assertTrue(pickups)
        self.assertTrue(trips)
        for request in pickups:
            self.assertEqual(
                request.pickup_duration,
                pickup_rng.uniform(config.pickup_min_minutes, config.pickup_max_minutes),
            )
        for request in trips:
            self.assertEqual(
                request.trip_duration,
                trip_rng.lognormvariate(config.trip_mu, config.trip_sigma),
            )

    def test_service_stages_and_capacity_are_valid_after_every_event(self):
        simulation = RideSharingSimulation(
            SimulationConfig(
                fleet_size=2, mean_interarrival_minutes=0.1, duration_minutes=35
            )
        )
        allowed = {
            ("waiting", None): {("waiting", None), ("in_service", "pickup"),
                                ("abandoned", None)},
            ("in_service", "pickup"): {("in_service", "pickup"), ("in_service", "trip")},
            ("in_service", "trip"): {("in_service", "trip"), ("completed", None)},
            ("completed", None): {("completed", None)},
            ("abandoned", None): {("abandoned", None)},
        }
        previous = {}
        seen = set()
        while simulation.env.peek() < simulation.config.duration_minutes:
            simulation.env.step()
            for request in simulation.requests:
                state = (request.status, request.service_stage)
                self.assertIn(state, allowed[previous.get(request.request_id, ("waiting", None))])
                previous[request.request_id] = state
                seen.add(state)
            active = sum(r.status == "in_service" for r in simulation.requests)
            self.assertLessEqual(active, simulation.config.fleet_size)
            self.assertLessEqual(simulation.driver_pool.count, simulation.config.fleet_size)
        self.assertEqual(seen, set(allowed))
        simulation.run()
        self.assert_consistent(simulation)

    def test_unrepresentable_trip_samples_fail_clearly_and_release_driver(self):
        for sample in (0.0, -1.0, float("nan"), float("inf"), OverflowError()):
            with self.subTest(sample=sample):
                simulation = RideSharingSimulation(
                    SimulationConfig(fleet_size=1, duration_minutes=20)
                )
                with (
                    patch.object(simulation.rng, "expovariate", side_effect=[0, 99]),
                    patch.object(simulation.patience_rng, "expovariate", return_value=100),
                    patch.object(simulation.pickup_rng, "uniform", return_value=2),
                    patch.object(simulation.trip_rng, "lognormvariate", side_effect=[sample]),
                ):
                    with self.assertRaises(ValueError):
                        simulation.run()
                self.assertEqual(simulation.driver_pool.count, 0)
                self.assertEqual(len(simulation.driver_pool.queue), 0)

    def assert_history_consistent(self, simulation: RideSharingSimulation) -> None:
        """Replay lifecycle events independently and compare every state snapshot."""
        states = {}
        stages = {}
        previous_time = 0.0
        history = simulation.event_history
        self.assertEqual(history[0].event_type, "simulation_start")
        self.assertEqual(history[0].time, 0.0)
        self.assertEqual(history[-1].event_type, "simulation_end")
        self.assertEqual(history[-1].time, simulation.env.now)
        for sequence, event in enumerate(history):
            self.assertEqual(event.sequence, sequence)
            self.assertGreaterEqual(event.time, previous_time)
            previous_time = event.time
            request_id = event.request_id
            if event.event_type == "arrival":
                self.assertNotIn(request_id, states)
                states[request_id] = "waiting"
                stages[request_id] = None
            elif event.event_type == "driver_assignment":
                self.assertEqual(states[request_id], "waiting")
                states[request_id] = "in_service"
                stages[request_id] = "pickup"
            elif event.event_type == "pickup_completion":
                self.assertEqual((states[request_id], stages[request_id]),
                                 ("in_service", "pickup"))
                stages[request_id] = "trip"
            elif event.event_type == "trip_completion":
                self.assertEqual((states[request_id], stages[request_id]),
                                 ("in_service", "trip"))
                states[request_id] = "completed"
                stages[request_id] = None
            elif event.event_type == "abandonment":
                self.assertEqual(states[request_id], "waiting")
                states[request_id] = "abandoned"
            else:
                self.assertIn(event.event_type, {"simulation_start", "simulation_end"})
                self.assertIsNone(request_id)
            if request_id is not None:
                self.assertEqual(event.request_status, states[request_id])
                self.assertEqual(event.service_stage, stages[request_id])
            counts = Counter(states.values())
            self.assertEqual(event.arrivals, len(states))
            self.assertEqual(event.waiting, counts["waiting"])
            self.assertEqual(event.busy_drivers, counts["in_service"])
            self.assertEqual(event.completed, counts["completed"])
            self.assertEqual(event.abandoned, counts["abandoned"])
            self.assertEqual(event.in_system, event.waiting + event.busy_drivers)
            self.assertEqual(event.arrivals, event.in_system + event.completed + event.abandoned)
            self.assertLessEqual(event.busy_drivers, simulation.config.fleet_size)
        self.assertEqual(states, {r.request_id: r.status for r in simulation.requests})
        self.assertEqual(stages, {r.request_id: r.service_stage for r in simulation.requests})
        simulation.validate_invariants()

    def test_history_records_exact_single_customer_lifecycle(self):
        simulation = self.run_with_arrivals([0.0], duration=11, patience_times=[0.1])
        self.assertEqual(
            [(e.time, e.event_type, e.request_id, e.waiting, e.in_system,
              e.busy_drivers, e.completed, e.abandoned) for e in simulation.event_history],
            [
                (0, "simulation_start", None, 0, 0, 0, 0, 0),
                (0, "arrival", 1, 1, 1, 0, 0, 0),
                (0, "driver_assignment", 1, 0, 1, 1, 0, 0),
                (2, "pickup_completion", 1, 0, 1, 1, 0, 0),
                (10, "trip_completion", 1, 0, 0, 0, 1, 0),
                (11, "simulation_end", None, 0, 0, 0, 1, 0),
            ],
        )
        self.assert_history_consistent(simulation)

    def test_history_abandonment_updates_queue_and_system_without_service(self):
        simulation = self.run_with_arrivals(
            [0.0, 1.0], duration=12, patience_times=[100.0, 2.0]
        )
        abandoned_events = [e for e in simulation.event_history if e.request_id == 2]
        self.assertEqual([e.event_type for e in abandoned_events], ["arrival", "abandonment"])
        event = abandoned_events[-1]
        self.assertEqual((event.time, event.waiting, event.in_system, event.busy_drivers,
                          event.abandoned), (3.0, 0, 1, 1, 1))
        self.assert_history_consistent(simulation)

    def test_history_matches_all_request_lifecycle_timestamps(self):
        simulation = RideSharingSimulation(SimulationConfig(fleet_size=2))
        simulation.run()
        for request in simulation.requests:
            expected = {
                "arrival": request.arrival_time,
                "driver_assignment": request.driver_assignment_time,
                "pickup_completion": request.pickup_completion_time,
                "trip_completion": request.trip_completion_time,
                "abandonment": request.abandonment_time,
            }
            expected = {kind: time for kind, time in expected.items() if time is not None}
            events = [e for e in simulation.event_history if e.request_id == request.request_id]
            self.assertEqual(len(events), len(expected))
            self.assertEqual({e.event_type: e.time for e in events}, expected)
        self.assert_history_consistent(simulation)

    def test_history_and_invariants_cover_normal_high_small_and_large_fleets(self):
        configs = [
            SimulationConfig(),
            SimulationConfig(fleet_size=2, mean_interarrival_minutes=0.1),
            SimulationConfig(fleet_size=1),
            SimulationConfig(fleet_size=100),
            SimulationConfig(fleet_size=1, mean_interarrival_minutes=0.05,
                             mean_patience_minutes=3),
        ]
        for config in configs:
            with self.subTest(config=config):
                simulation = RideSharingSimulation(config)
                simulation.run()
                self.assert_history_consistent(simulation)
                self.assert_consistent(simulation)
                if config.mean_interarrival_minutes == 0.05:
                    self.assertGreater(
                        sum(r.status == "abandoned" for r in simulation.requests),
                        len(simulation.requests) // 2,
                    )

    def test_history_preserves_simultaneous_event_order(self):
        simulation = self.run_with_arrivals(
            [0.0, 0.0, 1.0, 1.0], fleet_size=2, duration=21
        )
        self.assert_history_consistent(simulation)
        events = [e for e in simulation.event_history if e.time == 10.0]
        self.assertEqual(Counter(e.event_type for e in events),
                         Counter({"trip_completion": 2, "driver_assignment": 2}))
        self.assertEqual((events[-1].waiting, events[-1].busy_drivers), (0, 2))

    def test_history_deadline_tie_records_no_assignment_for_abandoned_customer(self):
        simulation = self.run_with_arrivals(
            [0.0, 1.0, 11.0], duration=22, patience_times=[100.0, 9.0, 100.0]
        )
        self.assertEqual(
            [e.event_type for e in simulation.event_history if e.request_id == 2],
            ["arrival", "abandonment"],
        )
        last_at_tie = [e for e in simulation.event_history if e.time == 10.0][-1]
        self.assertEqual((last_at_tie.waiting, last_at_tie.in_system,
                          last_at_tie.busy_drivers), (0, 0, 0))
        self.assert_history_consistent(simulation)

    def test_history_zero_patience_does_not_count_transient_resource_grant(self):
        simulation = self.run_with_arrivals(
            [0.0, 0.0], duration=11, patience_times=[0.0, 100.0]
        )
        self.assertFalse(any(e.event_type == "driver_assignment" and e.request_id == 1
                             for e in simulation.event_history))
        self.assert_history_consistent(simulation)

    def test_history_empty_run_has_initial_and_final_zero_snapshots(self):
        simulation = RideSharingSimulation(SimulationConfig(duration_minutes=0.001))
        simulation.run()
        self.assertEqual(len(simulation.event_history), 2)
        self.assertEqual([e.time for e in simulation.event_history], [0.0, 0.001])
        self.assert_history_consistent(simulation)

    def test_history_horizon_does_not_invent_pickup_or_trip_completion(self):
        for horizon, expected_stage in ((2.0, "pickup"), (5.0, "trip"), (10.0, "trip")):
            with self.subTest(horizon=horizon):
                simulation = self.run_with_arrivals([0.0], duration=horizon)
                self.assertEqual(simulation.requests[0].service_stage, expected_stage)
                self.assertFalse(any(e.event_type == "trip_completion"
                                     for e in simulation.event_history))
                self.assertTrue(all(e.time < horizon for e in simulation.event_history[:-1]))
                self.assertEqual(simulation.event_history[-1].busy_drivers, 1)
                self.assert_history_consistent(simulation)

    def test_history_rows_are_immutable_and_not_live_request_references(self):
        simulation = self.run_with_arrivals([0.0], duration=11)
        arrival = simulation.event_history[1]
        self.assertEqual(arrival.request_status, "waiting")
        self.assertEqual(simulation.requests[0].status, "completed")
        with self.assertRaises(FrozenInstanceError):
            arrival.waiting = 999
        row = asdict(arrival)
        self.assertEqual((row["waiting"], row["in_system"], row["busy_drivers"]), (1, 1, 0))
        row["waiting"] = 999
        self.assertEqual(arrival.waiting, 1)

    def test_history_is_reproducible_with_same_seed(self):
        first = RideSharingSimulation(SimulationConfig(fleet_size=2))
        second = RideSharingSimulation(SimulationConfig(fleet_size=2))
        first.run()
        second.run()
        self.assertEqual(first.event_history, second.event_history)
        self.assertEqual(first.requests, second.requests)

    def test_waiting_customer_view_matches_actual_fifo_queue(self):
        simulation = self.run_with_arrivals([0.0, 1.0, 2.0], duration=3)
        self.assertIsInstance(simulation.waiting_requests, tuple)
        self.assertEqual([r.request_id for r in simulation.waiting_requests], [2, 3])
        self.assertIs(simulation.waiting_requests[0], simulation.requests[1])
        self.assertEqual(simulation.busy_driver_count, 1)

    def test_invariant_check_runs_automatically_after_successful_run(self):
        simulation = RideSharingSimulation(SimulationConfig())
        with patch.object(simulation, "validate_invariants",
                          wraps=simulation.validate_invariants) as validator:
            simulation.run()
        validator.assert_called_once_with()

    def test_invariant_check_detects_corrupted_lifecycle_timestamp(self):
        simulation = self.run_with_arrivals([0.0], duration=11)
        simulation.requests[0].completion_time = 9.0
        with self.assertRaisesRegex(RuntimeError, "invalid trip completion"):
            simulation.validate_invariants()

    def test_invariant_check_detects_duplicate_requests(self):
        simulation = self.run_with_arrivals([0.0], duration=11)
        simulation.requests.append(simulation.requests[0])
        with self.assertRaises(RuntimeError):
            simulation.validate_invariants()

    def test_invariant_check_detects_orphaned_driver_slot(self):
        simulation = self.run_with_arrivals([0.0], duration=11)
        extra = simulation.driver_pool.request()
        try:
            with self.assertRaisesRegex(RuntimeError, "orphaned resource request"):
                simulation.validate_invariants()
        finally:
            simulation.driver_pool.release(extra)

    def test_invariant_check_detects_wrong_fifo_membership_order(self):
        simulation = self.run_with_arrivals([0.0, 1.0, 2.0], duration=3)
        simulation.driver_pool.queue.reverse()
        with self.assertRaisesRegex(RuntimeError, "FIFO queue membership"):
            simulation.validate_invariants()

    def test_invariant_check_detects_corrupted_history(self):
        simulation = self.run_with_arrivals([0.0], duration=11)
        simulation.event_history[-1] = replace(simulation.event_history[-1], waiting=1)
        with self.assertRaisesRegex(RuntimeError, "history conservation"):
            simulation.validate_invariants()

    def test_negative_seed_streams_are_distinct_and_reproducible(self):
        config = SimulationConfig(random_seed=-1)
        simulation = RideSharingSimulation(config)
        streams = [simulation.rng, simulation.patience_rng,
                   simulation.pickup_rng, simulation.trip_rng]
        states = [stream.getstate() for stream in streams]
        self.assertEqual(len(set(states)), 4)
        for offset, stream in enumerate(streams):
            self.assertEqual(stream.getstate(), random.Random(1 + offset).getstate())
        simulation.run()
        repeated = RideSharingSimulation(config)
        repeated.run()
        self.assertEqual(simulation.event_history, repeated.event_history)
        self.assertEqual(simulation.requests, repeated.requests)

    def test_random_seed_must_be_an_integer(self):
        for seed in (None, 1.5, "42", True):
            with self.subTest(seed=seed):
                with self.assertRaises(ValueError):
                    SimulationConfig(random_seed=seed)


if __name__ == "__main__":
    unittest.main()

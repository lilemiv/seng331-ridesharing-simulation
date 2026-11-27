"""Optional pickup model, legacy compatibility, and integration checks."""

from collections import Counter
from dataclasses import asdict
from math import fsum, hypot
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch

from city_visualization import ReplayState, load_csv, normalize_events
from config import SimulationConfig
from dispatch import Driver
from event_export import CSV_COLUMNS, export_event_history
from metrics import (abandonment_rate, average_queue_delay, average_time_in_system,
                     driver_utilization, time_average_number_in_system,
                     time_average_queue_length)
from scenarios import get_scenario
from simulation import RideRequest, RideSharingSimulation


COMBINATIONS = [(policy, mode) for policy in ("random", "nearest")
                for mode in ("uniform", "distance_aware")]


def controlled_run(arrivals=(0,), *, pickups=None, destinations=None,
                   positions=((0, 0),), patience=None, **overrides):
    settings = dict(duration_minutes=31, fleet_size=len(positions),
                    pickup_mode="distance_aware")
    settings.update(overrides)
    sim = RideSharingSimulation(SimulationConfig(**settings))
    sim._drivers = {i: Driver(i, *position) for i, position in enumerate(positions, 1)}
    sim._initial_drivers = sim.drivers
    delays = [time - prior for time, prior in zip(arrivals, (0, *arrivals))]
    pickups = pickups if pickups is not None else [(1, 0)] * len(arrivals)
    destinations = destinations if destinations is not None else [(0, 0)] * len(arrivals)
    patience = patience if patience is not None else [100] * len(arrivals)
    with (
        patch.object(sim.rng, "expovariate", side_effect=[*delays, settings["duration_minutes"] + 1]),
        patch.object(sim.patience_rng, "expovariate", side_effect=patience),
        patch.object(sim.pickup_location_rng, "uniform", side_effect=[v for p in pickups for v in p]),
        patch.object(sim.destination_rng, "uniform", side_effect=[v for p in destinations for v in p]),
        patch.object(sim.pickup_rng, "uniform", return_value=2),
        patch.object(sim.trip_rng, "lognormvariate", return_value=8),
    ):
        sim.run()
    return sim


class PickupConfigTests(unittest.TestCase):
    def test_uniform_is_default(self):
        config = SimulationConfig()
        self.assertEqual(config.pickup_mode, "uniform")
        self.assertEqual(config.pickup_speed_units_per_minute, 1.0)
        self.assertEqual(config.pickup_base_delay_minutes, 1.0)

    def test_invalid_modes_are_rejected(self):
        for value in ("", "Uniform", "distance", None, True, ["uniform"]):
            with self.subTest(value=value), self.assertRaises(ValueError):
                SimulationConfig(pickup_mode=value)

    def test_invalid_speeds_are_rejected_in_both_modes(self):
        for mode in ("uniform", "distance_aware"):
            for value in (0, -1, float("nan"), float("inf"), True, None, "1", 10**1000):
                with self.subTest(mode=mode, value=value), self.assertRaises(ValueError):
                    SimulationConfig(pickup_mode=mode, pickup_speed_units_per_minute=value)

    def test_invalid_overheads_are_rejected_in_both_modes(self):
        for mode in ("uniform", "distance_aware"):
            for value in (-1, float("nan"), float("inf"), True, None, "1", 10**1000):
                with self.subTest(mode=mode, value=value), self.assertRaises(ValueError):
                    SimulationConfig(pickup_mode=mode, pickup_base_delay_minutes=value)

    def test_zero_overhead_is_supported(self):
        self.assertEqual(SimulationConfig(pickup_base_delay_minutes=0).pickup_base_delay_minutes, 0)

    def test_integer_speed_and_overhead_are_supported(self):
        config = SimulationConfig(pickup_speed_units_per_minute=2, pickup_base_delay_minutes=3)
        self.assertEqual(config.pickup_speed_units_per_minute, 2)
        self.assertEqual(config.pickup_base_delay_minutes, 3)

    def test_scenario_overrides_accept_pickup_parameters(self):
        config = get_scenario("small_fleet", pickup_mode="distance_aware",
                              pickup_speed_units_per_minute=2, pickup_base_delay_minutes=0)
        self.assertEqual(config.fleet_size, 5)
        self.assertEqual(config.pickup_mode, "distance_aware")
        self.assertEqual(config.pickup_speed_units_per_minute, 2)


class PickupModelTests(unittest.TestCase):
    def test_euclidean_distance_and_travel_time(self):
        sim = controlled_run(pickups=[(3, 4)], pickup_speed_units_per_minute=2,
                             pickup_base_delay_minutes=1.5)
        request = sim.requests[0]
        self.assertEqual(request.assignment_distance, 5)
        self.assertEqual(request.pickup_duration, 4)
        self.assertEqual(request.pickup_completion_time, 4)
        self.assertEqual(request.completion_time, 12)

    def test_zero_distance_keeps_base_delay(self):
        sim = controlled_run(pickups=[(0, 0)], pickup_base_delay_minutes=1.5)
        self.assertEqual(sim.requests[0].assignment_distance, 0)
        self.assertEqual(sim.requests[0].pickup_duration, 1.5)

    def test_zero_distance_zero_overhead_has_ordered_same_time_events(self):
        sim = controlled_run(pickups=[(0, 0)], pickup_base_delay_minutes=0)
        request = sim.requests[0]
        self.assertEqual(request.pickup_duration, 0)
        self.assertEqual(request.pickup_completion_time, request.driver_assignment_time)
        self.assertEqual([e.event_type for e in sim.event_history if e.time == 0],
                         ["simulation_start", "arrival", "driver_assignment", "pickup_completion"])
        self.assertEqual(request.completion_time, 8)
        sim.validate_invariants()

    def test_longer_distance_increases_pickup_time(self):
        short = controlled_run(pickups=[(2, 0)], pickup_speed_units_per_minute=2)
        long = controlled_run(pickups=[(6, 0)], pickup_speed_units_per_minute=2)
        self.assertEqual(short.requests[0].pickup_duration, 2)
        self.assertEqual(long.requests[0].pickup_duration, 4)

    def test_distance_pickup_is_not_clipped_to_uniform_bounds(self):
        short = controlled_run(pickups=[(0, 0)], pickup_base_delay_minutes=0.5)
        long = controlled_run(pickups=[(10, 10)], pickup_speed_units_per_minute=0.5)
        self.assertLess(short.requests[0].pickup_duration, 2)
        self.assertGreater(long.requests[0].pickup_duration, 8)

    def test_uniform_ignores_distance_parameters(self):
        first = RideSharingSimulation(SimulationConfig())
        second = RideSharingSimulation(SimulationConfig(pickup_speed_units_per_minute=0.01,
                                                        pickup_base_delay_minutes=100))
        first.run()
        second.run()
        self.assertEqual(first.requests, second.requests)
        self.assertEqual(first.event_history, second.event_history)
        self.assertEqual(first.driver_history, second.driver_history)

    def test_default_uniform_preserves_known_baseline_and_rng_draws(self):
        sim = RideSharingSimulation(SimulationConfig())
        sim.run()
        self.assertEqual(Counter(r.status for r in sim.requests),
                         {"completed": 58, "in_service": 20, "abandoned": 8})
        self.assertEqual(len(sim.event_history), 305)
        self.assertEqual(average_queue_delay(sim.requests).mean, 0.2825360041096634)
        samples = random.Random(44)
        for event in sim.driver_history:
            if event.event_type == "driver_assignment":
                self.assertEqual(sim.requests[event.request_id - 1].pickup_duration,
                                 samples.uniform(2, 8))

    def test_distance_is_recorded_for_both_policies_and_modes(self):
        for policy, mode in COMBINATIONS:
            with self.subTest(policy=policy, mode=mode):
                sim = controlled_run(positions=((0, 0), (9, 9)), pickups=[(8, 8)],
                                     dispatch_policy=policy, pickup_mode=mode)
                event = sim.driver_history[0]
                expected = hypot(event.x - 8, event.y - 8)
                self.assertEqual(sim.requests[0].assignment_distance, expected)
                expected_id = (random.Random(49).choice([1, 2]) if policy == "random" else 2)
                self.assertEqual(event.driver_id, expected_id)

    def test_distance_uses_assignment_position_and_survives_destination_update(self):
        sim = controlled_run((0, 1), pickups=[(3, 4), (6, 8)], destinations=[(6, 8), (9, 9)])
        self.assertEqual([r.assignment_distance for r in sim.requests], [5, 0])
        self.assertEqual([r.driver_assignment_time for r in sim.requests], [0, 14])
        self.assertEqual((sim.drivers[0].x, sim.drivers[0].y), (9, 9))
        self.assertTrue(sim.drivers[0].is_available)

    def test_assignment_distance_accessor_preserves_request_serialization(self):
        request = RideRequest(1, 0, 5)
        self.assertIsNone(request.assignment_distance)
        self.assertNotIn("assignment_distance", asdict(request))
        with self.assertRaises(AttributeError):
            request.assignment_distance = 3

    def test_distance_mode_does_not_consume_uniform_pickup_rng(self):
        sim = RideSharingSimulation(SimulationConfig(pickup_mode="distance_aware"))
        before = sim.pickup_rng.getstate()
        with patch.object(sim.pickup_rng, "uniform", side_effect=AssertionError("unexpected draw")):
            sim.run()
        self.assertEqual(sim.pickup_rng.getstate(), before)

    def test_unrepresentable_pickup_fails_and_releases_driver(self):
        sim = RideSharingSimulation(SimulationConfig(pickup_mode="distance_aware",
                                                     pickup_speed_units_per_minute=1e-320))
        with self.assertRaisesRegex(ValueError, "pickup duration"):
            sim.run()
        self.assertEqual(sim.driver_pool.count, 0)
        self.assertEqual(len(sim.available_drivers), sim.config.fleet_size)

    def test_unrepresentable_assignment_distance_fails_without_reservation(self):
        sim = RideSharingSimulation(SimulationConfig(city_width=1.7e308, city_height=1.7e308))
        sim._drivers = {i: Driver(i, 0, 0) for i in range(1, 21)}
        sim._initial_drivers = sim.drivers
        with (patch.object(sim.pickup_location_rng, "uniform", return_value=1.7e308),
              self.assertRaisesRegex(ValueError, "Assignment distance")):
            sim.run()
        self.assertEqual(sim.driver_pool.count, 0)
        self.assertEqual(len(sim.available_drivers), 20)

    def test_corrupted_distance_is_detected_from_assignment_history(self):
        sim = controlled_run()
        sim.requests[0]._assignment_distance += 1
        with self.assertRaises(RuntimeError):
            sim.validate_invariants()

    def test_corrupted_pickup_duration_is_detected(self):
        sim = controlled_run()
        sim.requests[0].pickup_duration += 1
        with self.assertRaisesRegex(RuntimeError, "distance-aware pickup"):
            sim.validate_invariants()

    def test_unassigned_request_must_not_have_distance(self):
        sim = controlled_run((0, 0), duration_minutes=1)
        sim.requests[1]._assignment_distance = 0
        with self.assertRaisesRegex(RuntimeError, "unassigned request has assignment distance"):
            sim.validate_invariants()


class PickupIntegrationTests(unittest.TestCase):
    def test_fifo_deadline_tie_and_middle_abandonment_in_all_combinations(self):
        for policy, mode in COMBINATIONS:
            with self.subTest(policy=policy, mode=mode):
                sim = controlled_run((0, 1, 1, 2, 10), patience=[100, 9, 100, 1, 100],
                                     dispatch_policy=policy, pickup_mode=mode)
                self.assertEqual([r.driver_assignment_time for r in sim.requests],
                                 [0, None, 10, None, 20])
                self.assertEqual([r.status for r in sim.requests],
                                 ["completed", "abandoned", "completed", "abandoned", "completed"])
                self.assertTrue(all(r.assignment_distance is None for r in sim.requests
                                    if r.status == "abandoned"))
                self.assertEqual(sim.driver_pool.count, 0)
                self.assertEqual(len(sim.available_drivers), 1)

    def test_patience_does_not_apply_after_assignment(self):
        for policy, mode in COMBINATIONS:
            sim = controlled_run(patience=[0.1], pickups=[(3, 4)],
                                 dispatch_policy=policy, pickup_mode=mode)
            self.assertEqual(sim.requests[0].status, "completed")
            self.assertIsNone(sim.requests[0].abandonment_time)

    def test_capacity_and_ownership_after_every_internal_event(self):
        for policy, mode in COMBINATIONS:
            sim = RideSharingSimulation(SimulationConfig(fleet_size=2, duration_minutes=20,
                                                         mean_interarrival_minutes=0.1,
                                                         dispatch_policy=policy, pickup_mode=mode))
            while sim.env.peek() < 20:
                sim.env.step()
                assigned = [r.assigned_driver_id for r in sim.requests if r.status == "in_service"]
                self.assertEqual(len(assigned), len(set(assigned)))
                self.assertEqual(set(assigned), {d.driver_id for d in sim.busy_drivers})
                self.assertLessEqual(len(assigned), sim.driver_pool.count)
                self.assertLessEqual(sim.driver_pool.count, 2)
            sim.run()

    def test_exclusive_pickup_and_trip_horizons(self):
        for policy, mode in COMBINATIONS:
            for horizon, stage in ((1, "pickup"), (2, "pickup"), (5, "trip"), (10, "trip")):
                with self.subTest(policy=policy, mode=mode, horizon=horizon):
                    sim = controlled_run((0, 1), duration_minutes=horizon,
                                         dispatch_policy=policy, pickup_mode=mode)
                    self.assertEqual(sim.requests[0].service_stage, stage)
                    self.assertIsNone(sim.requests[0].completion_time)
                    self.assertEqual(sim.busy_driver_count, 1)
                    if horizon > 1:
                        self.assertEqual(sim.requests[1].status, "waiting")
                    else:
                        self.assertEqual(len(sim.requests), 1)
                    self.assertEqual(sim.event_history[-1].time, horizon)

    def test_zero_arrivals(self):
        for policy, mode in COMBINATIONS:
            sim = controlled_run((), dispatch_policy=policy, pickup_mode=mode)
            self.assertEqual(sim.requests, [])
            self.assertEqual([e.event_type for e in sim.event_history],
                             ["simulation_start", "simulation_end"])

    def test_expiry_at_horizon_remains_censored(self):
        for policy, mode in COMBINATIONS:
            sim = controlled_run((0, 1), patience=[100, 2], duration_minutes=3,
                                 dispatch_policy=policy, pickup_mode=mode)
            waiting = sim.requests[1]
            self.assertEqual(waiting.status, "waiting")
            self.assertIsNone(waiting.abandonment_time)
            self.assertIsNone(waiting.assignment_distance)
            self.assertEqual(sim.event_history[-1].waiting, 1)

    def test_metrics_match_exact_controlled_exposures(self):
        for policy, mode in COMBINATIONS:
            sim = controlled_run((0, 1, 2, 11), patience=[100, 2, 100, 100], duration_minutes=13,
                                 dispatch_policy=policy, pickup_mode=mode)
            self.assertEqual(average_queue_delay(sim.requests).mean, 4)
            self.assertEqual(average_queue_delay(sim.requests).count, 2)
            self.assertEqual(average_time_in_system(sim.requests).mean, 10)
            self.assertEqual(average_time_in_system(sim.requests).count, 1)
            # Queue/system/busy exposures are 12, 25, and 13 customer/driver-minutes.
            self.assertAlmostEqual(time_average_queue_length(sim.event_history, 13), 12 / 13)
            self.assertAlmostEqual(time_average_number_in_system(sim.event_history, 13), 25 / 13)
            self.assertEqual(driver_utilization(sim.event_history, 13, 1), 1)
            self.assertEqual(abandonment_rate(sim.requests), 1 / 4)

    def test_real_metrics_match_independent_timestamp_intervals(self):
        for policy, mode in COMBINATIONS:
            for scenario in ("baseline", "small_fleet", "high_demand", "low_demand"):
                sim = RideSharingSimulation(get_scenario(scenario, dispatch_policy=policy, pickup_mode=mode))
                sim.run()
                T = sim.env.now
                q, n, b = [], [], []
                for r in sim.requests:
                    end = (r.completion_time if r.completion_time is not None else
                           r.abandonment_time if r.abandonment_time is not None else T)
                    assignment = r.driver_assignment_time
                    q.append((assignment if assignment is not None else end) - r.arrival_time)
                    n.append(end - r.arrival_time)
                    if assignment is not None:
                        b.append(end - assignment)
                self.assertAlmostEqual(time_average_queue_length(sim.event_history, T), fsum(q) / T)
                self.assertAlmostEqual(time_average_number_in_system(sim.event_history, T), fsum(n) / T)
                self.assertAlmostEqual(driver_utilization(sim.event_history, T, sim.config.fleet_size),
                                       fsum(b) / T / sim.config.fleet_size)

    def test_history_conservation_fifo_and_csv_replay(self):
        for policy, mode in COMBINATIONS:
            sim = RideSharingSimulation(SimulationConfig(fleet_size=3, duration_minutes=20,
                                                         mean_interarrival_minutes=0.1,
                                                         dispatch_policy=policy, pickup_mode=mode))
            sim.run()
            waiting = []
            for event in sim.event_history:
                if event.event_type == "arrival":
                    waiting.append(event.request_id)
                elif event.event_type == "driver_assignment":
                    self.assertEqual(waiting.pop(0), event.request_id)
                elif event.event_type == "abandonment":
                    waiting.remove(event.request_id)
                self.assertEqual(event.arrivals, event.waiting + event.busy_drivers
                                 + event.completed + event.abandoned)
                self.assertLessEqual(event.busy_drivers, 3)
            events = normalize_events(sim.event_history)
            state = ReplayState()
            for event in events:
                state.apply(event)
            self.assertEqual(state.customers,
                             {r.request_id: r.service_stage if r.status == "in_service" else r.status
                              for r in sim.requests})
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "events.csv"
                export_event_history(sim.event_history, path)
                self.assertEqual(load_csv(path), events)
                self.assertEqual(path.read_text(encoding="utf-8").splitlines()[0], ",".join(CSV_COLUMNS))

    def test_matched_inputs_and_trip_stream_design(self):
        simulations = []
        for policy, mode in COMBINATIONS:
            sim = RideSharingSimulation(SimulationConfig(fleet_size=5, dispatch_policy=policy,
                                                         pickup_mode=mode))
            sim.run()
            simulations.append(sim)
            samples = random.Random(45)
            for event in sim.event_history:
                if event.event_type == "pickup_completion":
                    expected = samples.lognormvariate(sim.config.trip_mu, sim.config.trip_sigma)
                    self.assertEqual(sim.requests[event.request_id - 1].trip_duration, expected)
        def inputs(sim):
            return [(r.arrival_time, r.patience_time, r.pickup_x, r.pickup_y,
                     r.destination_x, r.destination_y) for r in sim.requests]
        for sim in simulations[1:]:
            self.assertEqual(sim.initial_drivers, simulations[0].initial_drivers)
            self.assertEqual(inputs(sim), inputs(simulations[0]))

    def test_reproducibility_includes_distance_and_driver_history(self):
        for policy, mode in COMBINATIONS:
            for seed in (42, -17):
                config = SimulationConfig(dispatch_policy=policy, pickup_mode=mode, random_seed=seed)
                first, second = RideSharingSimulation(config), RideSharingSimulation(config)
                first.run()
                second.run()
                self.assertEqual(first.requests, second.requests)
                self.assertEqual([r.assignment_distance for r in first.requests],
                                 [r.assignment_distance for r in second.requests])
                self.assertEqual(first.event_history, second.event_history)
                self.assertEqual(first.driver_history, second.driver_history)
                self.assertEqual(first.drivers, second.drivers)

    def test_distance_mode_can_change_timing_while_uniform_preserves_it(self):
        histories = {}
        for policy, mode in COMBINATIONS:
            sim = RideSharingSimulation(SimulationConfig(dispatch_policy=policy, pickup_mode=mode))
            sim.run()
            histories[policy, mode] = sim.event_history
        self.assertEqual(histories["random", "uniform"], histories["nearest", "uniform"])
        self.assertNotEqual(histories["random", "distance_aware"], histories["nearest", "distance_aware"])


if __name__ == "__main__":
    unittest.main()

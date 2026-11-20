"""Driver identity, policy, scheduling, and consumer integration regressions."""

from dataclasses import FrozenInstanceError, asdict, fields, replace
from pathlib import Path
import math
import random
import tempfile
import unittest
from unittest.mock import patch

from config import SimulationConfig
from dispatch import Driver, select_nearest_driver, select_random_driver
from simulation import RideSharingSimulation, SimulationEvent
from event_export import export_event_history
from city_visualization import ReplayState, normalize_events, load_csv
from metrics import (average_queue_delay, average_time_in_system,
                     time_average_queue_length, time_average_number_in_system,
                     driver_utilization, abandonment_rate)


def controlled_run(arrivals, *, patience=None, policy=None, fleet=1, duration=31):
    settings = dict(fleet_size=fleet, duration_minutes=duration)
    if policy is not None:
        settings['dispatch_policy'] = policy
    sim = RideSharingSimulation(SimulationConfig(**settings))
    delays = [time - prior for time, prior in zip(arrivals, [0, *arrivals])]
    if patience is None:
        patience = [duration + 1] * len(arrivals)
    with (
        patch.object(sim.rng, 'expovariate', side_effect=[*delays, duration + 1]),
        patch.object(sim.patience_rng, 'expovariate', side_effect=patience),
        patch.object(sim.pickup_rng, 'uniform', return_value=2),
        patch.object(sim.trip_rng, 'lognormvariate', return_value=8),
    ):
        sim.run()
    return sim


class DriverIdentityTests(unittest.TestCase):
    def test_unique_ids_and_configured_fleet(self):
        for size in (1, 3, 20):
            sim = RideSharingSimulation(SimulationConfig(fleet_size=size))
            self.assertEqual([d.driver_id for d in sim.drivers], list(range(1, size+1)))
            self.assertEqual(len(sim.available_drivers), size)
            self.assertEqual(sim.driver_pool.capacity, size)

    def test_driver_snapshots_are_immutable(self):
        sim = RideSharingSimulation(SimulationConfig())
        with self.assertRaises(FrozenInstanceError):
            sim.drivers[0].assigned_request_id = 10

    def test_assignment_is_observable_and_not_shared(self):
        sim = controlled_run([0, 0, 1], fleet=2, duration=5)
        first, second, waiting = sim.requests
        self.assertNotEqual(first.assigned_driver_id, second.assigned_driver_id)
        self.assertIsNone(waiting.assigned_driver_id)
        self.assertEqual({d.assigned_request_id for d in sim.drivers}, {1, 2})
        self.assertEqual(sim.available_drivers, ())
        self.assertEqual([e.request_id for e in sim.driver_history], [1, 2])

    def test_driver_release_and_same_time_reassignment(self):
        sim = controlled_run([0, 1], duration=21)
        self.assertEqual([r.assigned_driver_id for r in sim.requests], [1, 1])
        self.assertEqual([e.event_type for e in sim.driver_history],
                         ['driver_assignment', 'driver_release'] * 2)
        self.assertEqual([e.time for e in sim.driver_history], [0, 10, 10, 20])
        self.assertTrue(sim.drivers[0].is_available)

    def test_abandoned_requests_have_no_driver(self):
        sim = controlled_run([0, 1], patience=[100, 1])
        self.assertEqual(sim.requests[1].status, 'abandoned')
        self.assertIsNone(sim.requests[1].assigned_driver_id)
        self.assertTrue(all(e.request_id == 1 for e in sim.driver_history))

    def test_unfinished_trip_keeps_named_driver_at_horizon(self):
        sim = controlled_run([0], duration=10)
        self.assertEqual(sim.requests[0].status, 'in_service')
        self.assertEqual(sim.drivers[0].assigned_request_id, 1)
        self.assertEqual([e.event_type for e in sim.driver_history], ['driver_assignment'])

    def test_service_failure_releases_identity_and_resource(self):
        sim = RideSharingSimulation(SimulationConfig(fleet_size=1))
        with (
            patch.object(sim.rng, 'expovariate', side_effect=[0, 1000]),
            patch.object(sim.trip_rng, 'lognormvariate', return_value=float('inf')),
        ):
            with self.assertRaises(ValueError):
                sim.run()
        self.assertEqual(sim.driver_pool.count, 0)
        self.assertTrue(sim.drivers[0].is_available)


class CoordinateTests(unittest.TestCase):
    def test_coordinate_bounds_validation(self):
        for name in ('city_width', 'city_height'):
            for value in (0, -1, float('nan'), float('inf'), True, None, '10', 10**1000):
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    SimulationConfig(**{name: value})

    def test_driver_pickup_and_destination_positions_reproduce(self):
        first = controlled_run([0, 1, 2])
        second = controlled_run([0, 1, 2])
        self.assertEqual(first.initial_drivers, second.initial_drivers)
        self.assertEqual(first.requests, second.requests)
        self.assertNotEqual((first.requests[0].pickup_x, first.requests[0].pickup_y),
                            (first.requests[0].destination_x, first.requests[0].destination_y))

    def test_all_coordinates_stay_inside_configured_rectangle(self):
        sim = RideSharingSimulation(SimulationConfig(city_width=2.5, city_height=7))
        sim.run()
        points = [(d.x, d.y) for d in sim.drivers]
        points += [(r.pickup_x, r.pickup_y) for r in sim.requests]
        points += [(r.destination_x, r.destination_y) for r in sim.requests]
        self.assertTrue(points)
        for x, y in points:
            self.assertTrue(0 <= x <= 2.5 and 0 <= y <= 7)

    def test_existing_four_rng_streams_not_consumed_by_coordinates(self):
        sim = RideSharingSimulation(SimulationConfig(random_seed=-17))
        for offset, stream in enumerate((sim.rng, sim.patience_rng, sim.pickup_rng, sim.trip_rng)):
            self.assertEqual(stream.getstate(), random.Random(17 + offset).getstate())
        sim.run()
        arrivals = random.Random(17)
        patience = random.Random(18)
        time = 0
        for request in sim.requests:
            time += arrivals.expovariate(1 / sim.config.mean_interarrival_minutes)
            self.assertEqual(request.arrival_time, time)
            self.assertEqual(request.patience_time, patience.expovariate(1 / 5))

    def test_coordinates_do_not_depend_on_fleet_size(self):
        first = controlled_run([0, 1, 2], fleet=1)
        second = controlled_run([0, 1, 2], fleet=4)
        self.assertEqual([(r.pickup_x, r.pickup_y, r.destination_x, r.destination_y) for r in first.requests],
                         [(r.pickup_x, r.pickup_y, r.destination_x, r.destination_y) for r in second.requests])


class RandomDispatchTests(unittest.TestCase):
    def test_only_idle_drivers_are_selectable_in_stable_id_order(self):
        drivers = [Driver(3, 0, 0), Driver(2, 0, 0, 99), Driver(1, 0, 0)]
        rng = random.Random(42)
        with patch.object(rng, 'choice', side_effect=lambda candidates: candidates[-1]) as choose:
            self.assertEqual(select_random_driver(drivers, rng).driver_id, 3)
        self.assertEqual([d.driver_id for d in choose.call_args.args[0]], [1, 3])

    def test_every_idle_driver_can_be_selected(self):
        drivers = [Driver(i, 0, 0) for i in (1, 2, 3)]
        rng = random.Random(42)
        with patch.object(rng, '_randbelow', side_effect=[0, 1, 2]):
            self.assertEqual([select_random_driver(drivers, rng).driver_id for _ in range(3)], [1, 2, 3])

    def test_empty_idle_set_is_rejected(self):
        with self.assertRaises(ValueError):
            select_random_driver([Driver(1, 0, 0, 99)], random.Random(1))

    def test_seeded_selection_reproduces_in_actual_simulation(self):
        first = controlled_run([0, 0, 1, 2], fleet=3, policy='random')
        second = controlled_run([0, 0, 1, 2], fleet=3, policy='random')
        self.assertEqual(first.requests, second.requests)
        self.assertEqual(first.driver_history, second.driver_history)

    def test_dispatch_stream_does_not_use_service_randomness(self):
        sim = RideSharingSimulation(SimulationConfig())
        self.assertEqual(sim.dispatch_rng.getstate(), random.Random(49).getstate())
        original = [stream.getstate() for stream in (sim.rng, sim.patience_rng, sim.pickup_rng, sim.trip_rng)]
        select_random_driver(sim.drivers, sim.dispatch_rng)
        self.assertEqual(original, [stream.getstate() for stream in (sim.rng, sim.patience_rng, sim.pickup_rng, sim.trip_rng)])


class NearestDispatchTests(unittest.TestCase):
    def test_euclidean_nearest_not_id_or_axis_order(self):
        drivers = [Driver(1, 3, 4), Driver(2, 4, 0), Driver(3, 0, 0, 99)]
        self.assertEqual(select_nearest_driver(drivers, 0, 0).driver_id, 2)

    def test_exact_ties_use_lowest_id_independent_of_input_order(self):
        drivers = [Driver(7, 0, 1), Driver(2, 2, 1)]
        self.assertEqual(select_nearest_driver(drivers, 1, 1).driver_id, 2)
        self.assertEqual(select_nearest_driver(reversed(drivers), 1, 1).driver_id, 2)

    def test_extreme_finite_coordinates_do_not_collapse_to_infinite_ties(self):
        drivers = [Driver(1, 1.7e308, 1.7e308), Driver(2, 1.5e308, 1.5e308)]
        self.assertEqual(select_nearest_driver(drivers, 0, 0).driver_id, 2)

    def test_subnormal_coordinate_distances_remain_distinct(self):
        drivers = [Driver(1, 2e-320, 2e-320), Driver(2, 1e-320, 1e-320)]
        self.assertEqual(select_nearest_driver(drivers, 0, 0).driver_id, 2)

    def test_distant_outlier_does_not_erase_small_distances(self):
        drivers = [Driver(1, 2e-320, 0), Driver(2, 1e-320, 0), Driver(3, 1e308, 0)]
        self.assertEqual(select_nearest_driver(drivers, 0, 0).driver_id, 2)

    def test_empty_idle_set_is_rejected(self):
        with self.assertRaises(ValueError):
            select_nearest_driver([Driver(1, 0, 0, 99)], 0, 0)

    def test_engine_uses_customer_pickup_and_only_idle_candidates(self):
        sim = RideSharingSimulation(SimulationConfig(fleet_size=2, duration_minutes=1, dispatch_policy='nearest'))
        sim._drivers = {1: Driver(1, 0, 0), 2: Driver(2, 9, 9)}
        sim._initial_drivers = sim.drivers
        with (
            patch.object(sim.rng, 'expovariate', side_effect=[0, 0, 100]),
            patch.object(sim.pickup_location_rng, 'uniform', side_effect=[9, 9, 9, 9]),
        ):
            sim.run()
        self.assertEqual([r.assigned_driver_id for r in sim.requests], [2, 1])
        self.assertEqual([e.request_id for e in sim.driver_history], [1, 2])

    def test_nearest_reproduces_and_does_not_consume_dispatch_rng(self):
        first = controlled_run([0, 0, 1, 2], fleet=3, policy='nearest')
        second = controlled_run([0, 0, 1, 2], fleet=3, policy='nearest')
        self.assertEqual(first.requests, second.requests)
        self.assertEqual(first.driver_history, second.driver_history)
        self.assertEqual(first.dispatch_rng.getstate(), random.Random(49).getstate())

    def test_invalid_policy_is_rejected(self):
        for policy in ('Nearest', '', None, 'fifo', ['random']):
            with self.subTest(policy=policy), self.assertRaises(ValueError):
                SimulationConfig(dispatch_policy=policy)


class DriverMovementTests(unittest.TestCase):
    def test_completed_driver_is_available_at_destination(self):
        sim = controlled_run([0], duration=11)
        request = sim.requests[0]
        driver = sim.drivers[0]
        self.assertTrue(driver.is_available)
        self.assertEqual((driver.x, driver.y), (request.destination_x, request.destination_y))
        release = sim.driver_history[-1]
        self.assertEqual((release.x, release.y), (driver.x, driver.y))
        self.assertEqual(release.time, request.completion_time)

    def test_release_position_precedes_next_same_time_assignment(self):
        sim = controlled_run([0, 1], duration=21, policy='nearest')
        release, assignment = sim.driver_history[1:3]
        self.assertEqual((release.time, assignment.time), (10, 10))
        self.assertEqual((assignment.x, assignment.y),
                         (sim.requests[0].destination_x, sim.requests[0].destination_y))

    def test_unfinished_driver_does_not_teleport_to_future_destination(self):
        for duration in (1, 5, 10):
            sim = controlled_run([0], duration=duration)
            self.assertEqual((sim.drivers[0].x, sim.drivers[0].y),
                             (sim.initial_drivers[0].x, sim.initial_drivers[0].y))

    def test_nearest_uses_updated_location_after_idle_trip_completion(self):
        sim = RideSharingSimulation(SimulationConfig(fleet_size=2, duration_minutes=23, dispatch_policy='nearest'))
        sim._drivers = {1: Driver(1, 0, 0), 2: Driver(2, 5, 5)}
        sim._initial_drivers = sim.drivers
        with (
            patch.object(sim.rng, 'expovariate', side_effect=[0, 11, 100]),
            patch.object(sim.pickup_location_rng, 'uniform', side_effect=[0, 0, 9, 9]),
            patch.object(sim.destination_rng, 'uniform', side_effect=[9, 9, 1, 1]),
            patch.object(sim.pickup_rng, 'uniform', return_value=2),
            patch.object(sim.trip_rng, 'lognormvariate', return_value=8),
        ):
            sim.run()
        self.assertEqual([r.assigned_driver_id for r in sim.requests], [1, 1])
        self.assertEqual((sim.drivers[0].x, sim.drivers[0].y), (1, 1))


class DispatchInvariantTests(unittest.TestCase):
    def test_corrupted_driver_ownership_is_detected(self):
        sim = controlled_run([0, 0], fleet=2, duration=5)
        driver = sim.drivers[0]
        sim._drivers[driver.driver_id] = replace(driver, assigned_request_id=999)
        with self.assertRaisesRegex(RuntimeError, 'named drivers'):
            sim.validate_invariants()

    def test_corrupted_fleet_is_detected(self):
        sim = controlled_run([0])
        del sim._drivers[1]
        with self.assertRaisesRegex(RuntimeError, 'fleet size'):
            sim.validate_invariants()

    def test_corrupted_request_coordinates_are_detected(self):
        sim = controlled_run([0])
        sim.requests[0].pickup_x = float('nan')
        with self.assertRaisesRegex(RuntimeError, 'coordinates'):
            sim.validate_invariants()

    def test_corrupted_driver_coordinates_are_detected(self):
        sim = controlled_run([0])
        sim._drivers[1] = replace(sim.drivers[0], x=11)
        with self.assertRaisesRegex(RuntimeError, 'coordinates'):
            sim.validate_invariants()

    def test_missing_driver_release_is_detected(self):
        sim = controlled_run([0])
        sim._driver_history.pop()
        with self.assertRaisesRegex(RuntimeError, 'missing driver'):
            sim.validate_invariants()

    def test_corrupted_history_location_is_detected(self):
        sim = controlled_run([0])
        sim._driver_history[0] = replace(sim.driver_history[0], x=0)
        with self.assertRaisesRegex(RuntimeError, 'assignment position'):
            sim.validate_invariants()

    def test_abandonment_must_not_acquire_identity(self):
        sim = controlled_run([0, 1], patience=[100, 1])
        sim.requests[1].assigned_driver_id = 1
        with self.assertRaisesRegex(RuntimeError, 'unassigned request'):
            sim.validate_invariants()


class DispatchConsumerTests(unittest.TestCase):
    def test_driver_views_and_events_are_immutable_snapshots(self):
        sim = controlled_run([0], duration=5)
        self.assertEqual(sim.busy_drivers, sim.drivers)
        self.assertIsInstance(sim.driver_history, tuple)
        with self.assertRaises(FrozenInstanceError):
            sim.driver_history[0].x = 1
        with self.assertRaises(AttributeError):
            sim.initial_drivers = ()
        with self.assertRaises(AttributeError):
            sim.drivers = ()

    def test_metrics_compatibility_for_both_policies(self):
        for policy in ('random', 'nearest'):
            sim = controlled_run([0, 1, 2, 11], patience=[100, 2, 100, 100],
                                 duration=13, policy=policy)
            self.assertEqual((average_queue_delay(sim.requests).mean,
                              average_queue_delay(sim.requests).count), (4, 2))
            self.assertEqual(average_time_in_system(sim.requests).mean, 10)
            self.assertAlmostEqual(time_average_queue_length(sim.event_history, 13), 12/13)
            self.assertAlmostEqual(time_average_number_in_system(sim.event_history, 13), 25/13)
            self.assertEqual(driver_utilization(sim.event_history, 13, 1), 1)
            self.assertEqual(abandonment_rate(sim.requests), 1/4)

    def test_viewer_and_csv_interfaces_for_both_policies(self):
        for policy in ('random', 'nearest'):
            sim = controlled_run([0, 1, 2, 11], patience=[100, 2, 100, 100],
                                 duration=13, policy=policy)
            state = ReplayState()
            events = normalize_events(sim.event_history)
            for event in events:
                state.apply(event)
            self.assertEqual(state.customers, {1: 'completed', 2: 'abandoned', 3: 'trip', 4: 'waiting'})
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'events.csv'
                export_event_history(sim.event_history, path)
                self.assertEqual(load_csv(path), events)
                self.assertEqual(path.read_text(encoding='utf-8').splitlines()[0].split(','),
                                 [field.name for field in fields(SimulationEvent)])

    def test_driver_events_join_customer_lifecycle_by_id_and_time(self):
        for policy in ('random', 'nearest'):
            sim = controlled_run([0, 1, 2], fleet=2, policy=policy)
            records = {r.request_id: r for r in sim.requests}
            for event in sim.driver_history:
                request = records[event.request_id]
                self.assertEqual(event.driver_id, request.assigned_driver_id)
                kind = 'driver_assignment' if event.event_type == 'driver_assignment' else 'trip_completion'
                self.assertEqual(len([row for row in sim.event_history
                                      if (row.request_id, row.time, row.event_type)
                                      == (event.request_id, event.time, kind)]), 1)


class DispatchSchedulingTests(unittest.TestCase):
    def test_fifo_survives_deadline_tie_middle_expiry_and_same_time_arrival(self):
        for policy in ('random', 'nearest'):
            with self.subTest(policy=policy):
                sim = controlled_run([0, 1, 1, 2, 10], patience=[100, 9, 100, 1, 100], policy=policy)
                self.assertEqual([r.driver_assignment_time for r in sim.requests], [0, None, 10, None, 20])
                self.assertEqual([r.assigned_driver_id for r in sim.requests], [1, None, 1, None, 1])
                self.assertEqual(sim.requests[1].abandonment_time, 10)
                self.assertEqual(sim.requests[3].abandonment_time, 3)

    def test_zero_patience_does_not_reserve_idle_identity(self):
        for policy in ('random', 'nearest'):
            sim = controlled_run([0, 0], patience=[0, 100], policy=policy)
            self.assertIsNone(sim.requests[0].assigned_driver_id)
            self.assertEqual(sim.requests[1].driver_assignment_time, 0)
            self.assertEqual([e.request_id for e in sim.driver_history], [2, 2])

    def test_simultaneous_releases_preserve_fifo_and_unique_reservations(self):
        for policy in ('random', 'nearest'):
            sim = controlled_run([0, 0, 1, 1], fleet=2, duration=21, policy=policy)
            events = [e for e in sim.driver_history if e.time == 10]
            self.assertEqual([e.request_id for e in events if e.event_type == 'driver_assignment'], [3, 4])
            self.assertEqual(len({e.driver_id for e in events if e.event_type == 'driver_assignment'}), 2)
            self.assertEqual(len(sim.available_drivers), 2)
            self.assertEqual(sim.busy_driver_count, 0)
            self.assertEqual(sim.waiting_requests, ())

    def test_policy_does_not_change_legacy_lifecycle_or_existing_rng_draws(self):
        simulations = []
        for policy in ('random', 'nearest'):
            sim = RideSharingSimulation(SimulationConfig(dispatch_policy=policy, fleet_size=3, mean_interarrival_minutes=0.2))
            sim.run()
            simulations.append(sim)
        first, second = simulations
        self.assertEqual(first.event_history, second.event_history)
        for a, b in zip(first.requests, second.requests):
            self.assertEqual({k: v for k, v in asdict(a).items() if k != 'assigned_driver_id'},
                             {k: v for k, v in asdict(b).items() if k != 'assigned_driver_id'})
        for name in ('rng', 'patience_rng', 'pickup_rng', 'trip_rng'):
            self.assertEqual(getattr(first, name).getstate(), getattr(second, name).getstate())
        self.assertNotEqual([r.assigned_driver_id for r in first.requests],
                            [r.assigned_driver_id for r in second.requests])

    def test_high_demand_both_policies_preserve_every_history_count_and_fifo(self):
        for policy in ('random', 'nearest'):
            sim = RideSharingSimulation(SimulationConfig(dispatch_policy=policy, fleet_size=2,
                                                        mean_interarrival_minutes=0.08))
            sim.run()
            waiting, active, completed, abandoned = [], set(), set(), set()
            for event in sim.event_history:
                rid = event.request_id
                if event.event_type == 'arrival':
                    waiting.append(rid)
                elif event.event_type == 'driver_assignment':
                    self.assertEqual(waiting.pop(0), rid)
                    active.add(rid)
                elif event.event_type == 'abandonment':
                    waiting.remove(rid)
                    abandoned.add(rid)
                elif event.event_type == 'trip_completion':
                    active.remove(rid)
                    completed.add(rid)
                self.assertEqual((event.waiting, event.busy_drivers, event.completed, event.abandoned),
                                 (len(waiting), len(active), len(completed), len(abandoned)))
                self.assertEqual(event.arrivals, len(waiting) + len(active) + len(completed) + len(abandoned))
            self.assertTrue(abandoned)
            self.assertLessEqual(len(active), 2)
            for request in sim.requests:
                if request.driver_assignment_time is not None:
                    self.assertTrue(2 <= request.pickup_duration <= 8)
                if request.trip_duration is not None:
                    self.assertTrue(math.isfinite(request.trip_duration) and request.trip_duration > 0)

    def test_capacity_and_identity_hold_after_every_internal_simpy_event(self):
        for policy in ('random', 'nearest'):
            sim = RideSharingSimulation(SimulationConfig(dispatch_policy=policy, fleet_size=2,
                                                        mean_interarrival_minutes=0.1, duration_minutes=20))
            while sim.env.peek() < 20:
                sim.env.step()
                active = {r.request_id: r.assigned_driver_id for r in sim.requests if r.status == 'in_service'}
                self.assertEqual(len(active), len(set(active.values())))
                self.assertEqual({d.assigned_request_id for d in sim.busy_drivers}, set(active))
                self.assertLessEqual(len(active), sim.driver_pool.count)
                self.assertLessEqual(sim.driver_pool.count, 2)
            sim.run()
            sim.validate_invariants()

    def test_both_policies_reproduce_full_state_with_negative_seed(self):
        for policy in ('random', 'nearest'):
            config = SimulationConfig(dispatch_policy=policy, random_seed=-17, fleet_size=2,
                                      mean_interarrival_minutes=0.1)
            first, second = RideSharingSimulation(config), RideSharingSimulation(config)
            first.run()
            second.run()
            self.assertEqual(first.requests, second.requests)
            self.assertEqual(first.drivers, second.drivers)
            self.assertEqual(first.driver_history, second.driver_history)
            self.assertEqual(first.event_history, second.event_history)


if __name__ == '__main__':
    unittest.main()

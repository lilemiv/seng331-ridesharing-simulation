"""Bounded reliability checks, not statistical experiments or benchmarks."""

from collections import Counter
import unittest
from unittest.mock import patch

from config import SimulationConfig
from simulation import RideSharingSimulation


class SimulationStressTests(unittest.TestCase):
    def assert_consistent_history(self, simulation):
        """Replay transitions independently, checking FIFO and every raw snapshot."""
        waiting = {}
        active = {}
        states = {}
        completed = set()
        abandoned = set()
        records = {request.request_id: request for request in simulation.requests}
        observed = {}
        timestamps = {
            "arrival": "arrival_time",
            "driver_assignment": "driver_assignment_time",
            "pickup_completion": "pickup_completion_time",
            "trip_completion": "trip_completion_time",
            "abandonment": "abandonment_time",
        }
        previous_time = 0
        for sequence, event in enumerate(simulation.event_history):
            self.assertEqual(event.sequence, sequence)
            self.assertGreaterEqual(event.time, previous_time)
            previous_time = event.time
            request_id = event.request_id
            kind = event.event_type
            if kind == "arrival":
                self.assertNotIn(request_id, states)
                states[request_id] = "waiting"
                waiting[request_id] = None
            elif kind == "driver_assignment":
                self.assertEqual(states[request_id], "waiting")
                self.assertEqual(request_id, next(iter(waiting)), "FIFO was violated")
                del waiting[request_id]
                states[request_id] = "in_service"
                active[request_id] = "pickup"
            elif kind == "pickup_completion":
                self.assertEqual(active[request_id], "pickup")
                active[request_id] = "trip"
            elif kind == "trip_completion":
                self.assertEqual(active.pop(request_id), "trip")
                states[request_id] = "completed"
                completed.add(request_id)
            elif kind == "abandonment":
                self.assertEqual(states[request_id], "waiting")
                del waiting[request_id]
                states[request_id] = "abandoned"
                abandoned.add(request_id)
            else:
                self.assertIn(kind, {"simulation_start", "simulation_end"})
                self.assertIsNone(request_id)
                self.assertIsNone(event.request_status)
                self.assertIsNone(event.service_stage)
            if request_id is not None:
                self.assertEqual(event.request_status, states[request_id])
                self.assertEqual(event.service_stage, active.get(request_id))
                self.assertEqual(event.time, getattr(records[request_id], timestamps[kind]))
                self.assertNotIn((request_id, kind), observed)
                observed[request_id, kind] = event.time
            self.assertEqual(
                (event.arrivals, event.waiting, event.busy_drivers, event.completed, event.abandoned),
                (len(states), len(waiting), len(active), len(completed), len(abandoned)),
            )
            self.assertEqual(event.in_system, len(waiting) + len(active))
            self.assertEqual(event.arrivals, event.in_system + event.completed + event.abandoned)
            self.assertLessEqual(event.busy_drivers, simulation.config.fleet_size)
        self.assertEqual(states, {request.request_id: request.status for request in simulation.requests})
        self.assertEqual(list(waiting), [request.request_id for request in simulation.waiting_requests])
        self.assertEqual(len(active), simulation.busy_driver_count)
        self.assertEqual(set(records), set(range(1, len(records) + 1)))
        self.assertEqual(simulation.event_history[0].event_type, "simulation_start")
        self.assertEqual(simulation.event_history[0].time, 0)
        self.assertEqual(simulation.event_history[-1].event_type, "simulation_end")
        self.assertEqual(simulation.event_history[-1].time, simulation.config.duration_minutes)
        self.assertTrue(all(
            event.time < simulation.config.duration_minutes
            for event in simulation.event_history[:-1]
        ))
        for request in simulation.requests:
            for kind, attribute in timestamps.items():
                self.assertEqual(observed.get((request.request_id, kind)), getattr(request, attribute))
        simulation.validate_invariants()

    def run_config(self, **settings):
        simulation = RideSharingSimulation(SimulationConfig(**settings))
        simulation.run()
        self.assert_consistent_history(simulation)
        return simulation

    def controlled_run(self, arrivals, patience, *, fleet_size=1, duration=31):
        simulation = RideSharingSimulation(
            SimulationConfig(fleet_size=fleet_size, duration_minutes=duration)
        )
        previous = 0
        delays = []
        for arrival in arrivals:
            delays.append(arrival - previous)
            previous = arrival
        with (
            patch.object(simulation.rng, "expovariate", side_effect=delays + [duration + 1]),
            patch.object(simulation.patience_rng, "expovariate", side_effect=patience),
            patch.object(simulation.pickup_rng, "uniform", return_value=2),
            patch.object(simulation.trip_rng, "lognormvariate", return_value=8),
        ):
            simulation.run()
        self.assert_consistent_history(simulation)
        return simulation

    def test_very_small_fleet_under_high_demand(self):
        simulation = self.run_config(fleet_size=1, mean_interarrival_minutes=0.05)
        self.assertTrue(any(event.waiting > 0 for event in simulation.event_history))
        self.assertEqual(max(event.busy_drivers for event in simulation.event_history), 1)
        self.assertGreater(sum(request.status == "abandoned" for request in simulation.requests), 0)

    def test_large_fleet_under_low_demand(self):
        simulation = self.run_config(
            fleet_size=100, mean_interarrival_minutes=3, duration_minutes=120
        )
        self.assertGreater(len(simulation.requests), 0)
        self.assertTrue(all(
            request.driver_assignment_time == request.arrival_time
            for request in simulation.requests
        ))
        self.assertLess(max(event.busy_drivers for event in simulation.event_history), 100)

    def test_high_abandonment_cleans_up_expired_waiters(self):
        simulation = self.run_config(
            fleet_size=2, mean_interarrival_minutes=0.08,
            mean_patience_minutes=3, duration_minutes=120,
        )
        counts = Counter(request.status for request in simulation.requests)
        self.assertGreater(counts["abandoned"], len(simulation.requests) // 2)
        queued = {request.request_id for request in simulation.waiting_requests}
        self.assertTrue(all(
            request.request_id not in queued and request.driver_assignment_time is None
            for request in simulation.requests if request.status == "abandoned"
        ))

    def test_one_day_horizon_preserves_history_and_conservation(self):
        simulation = self.run_config(duration_minutes=1440)
        self.assertTrue(any(request.status == "completed" for request in simulation.requests))
        self.assertTrue(any(event.time > 1000 for event in simulation.event_history))

    def test_simultaneous_releases_reassign_in_fifo_order(self):
        simulation = self.controlled_run(
            [0, 0, 1, 1], [100] * 4, fleet_size=2, duration=21
        )
        events = [event for event in simulation.event_history if event.time == 10]
        self.assertEqual(Counter(event.event_type for event in events),
                         {"trip_completion": 2, "driver_assignment": 2})
        self.assertEqual(
            [event.request_id for event in events if event.event_type == "driver_assignment"],
            [3, 4],
        )
        self.assertEqual(simulation.busy_driver_count, 0)
        self.assertEqual(simulation.waiting_requests, ())

    def test_deadline_tie_and_middle_abandonment_preserve_fifo(self):
        simulation = self.controlled_run([0, 1, 1, 2, 10], [100, 9, 100, 1, 100])
        self.assertEqual(
            [request.driver_assignment_time for request in simulation.requests],
            [0, None, 10, None, 20],
        )
        self.assertEqual(simulation.requests[1].abandonment_time, 10)
        self.assertEqual(simulation.requests[3].abandonment_time, 3)

    def test_congested_run_is_reproducible(self):
        settings = dict(fleet_size=2, mean_interarrival_minutes=0.1,
                        duration_minutes=120, random_seed=-17)
        first = self.run_config(**settings)
        second = self.run_config(**settings)
        self.assertEqual(first.requests, second.requests)
        self.assertEqual(first.event_history, second.event_history)

    def test_zero_arrivals_has_only_zero_boundary_snapshots(self):
        simulation = self.controlled_run([], [], duration=1)
        self.assertEqual(simulation.requests, [])
        self.assertEqual(len(simulation.event_history), 2)
        self.assertTrue(all(event.in_system == 0 for event in simulation.event_history))

    def test_unfinished_service_and_waiter_at_exclusive_horizon(self):
        for horizon, stage in ((2, "pickup"), (5, "trip"), (10, "trip")):
            with self.subTest(horizon=horizon):
                simulation = self.controlled_run([0, 1], [100, 100], duration=horizon)
                assigned, waiting = simulation.requests
                self.assertEqual(assigned.service_stage, stage)
                self.assertIsNone(assigned.trip_completion_time)
                self.assertEqual(waiting.status, "waiting")
                self.assertEqual(simulation.busy_driver_count, 1)


if __name__ == "__main__":
    unittest.main()

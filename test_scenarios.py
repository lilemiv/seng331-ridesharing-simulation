"""Configuration preset validation and compatibility checks."""

from dataclasses import FrozenInstanceError, asdict
import unittest

from config import SimulationConfig
from scenarios import SCENARIO_NAMES, get_scenario
from simulation import RideSharingSimulation


class ScenarioTests(unittest.TestCase):
    def test_baseline_preserves_default_records_and_history(self):
        self.assertEqual(get_scenario(), SimulationConfig())
        default = RideSharingSimulation(SimulationConfig())
        baseline = RideSharingSimulation(get_scenario("baseline"))
        default.run()
        baseline.run()
        self.assertEqual(baseline.requests, default.requests)
        self.assertEqual(baseline.event_history, default.event_history)

    def test_presets_change_only_documented_parameters(self):
        changes = {
            "baseline": {},
            "low_demand": {"mean_interarrival_minutes": 1.5},
            "high_demand": {"mean_interarrival_minutes": 0.25},
            "small_fleet": {"fleet_size": 5},
            "large_fleet": {"fleet_size": 40},
        }
        self.assertEqual(set(SCENARIO_NAMES), set(changes))
        for name, expected_changes in changes.items():
            with self.subTest(name=name):
                config = get_scenario(name)
                self.assertEqual(asdict(config), {**asdict(SimulationConfig()), **expected_changes})
                simulation = RideSharingSimulation(config)
                self.assertEqual(simulation.driver_pool.capacity, config.fleet_size)

    def test_demand_presets_scale_the_same_seeded_arrival_stream(self):
        simulations = {}
        for name in ("low_demand", "baseline", "high_demand"):
            simulation = RideSharingSimulation(get_scenario(name))
            simulation.run()
            simulations[name] = simulation
        low, baseline, high = (simulations[name] for name in ("low_demand", "baseline", "high_demand"))
        self.assertLess(len(low.requests), len(baseline.requests))
        self.assertLess(len(baseline.requests), len(high.requests))
        for index, request in enumerate(low.requests):
            self.assertAlmostEqual(request.arrival_time, baseline.requests[index].arrival_time * 2)
            self.assertAlmostEqual(request.arrival_time, high.requests[index].arrival_time * 6)

    def test_overrides_are_validated_and_preserve_reproducibility(self):
        config = get_scenario("small_fleet", fleet_size=3, random_seed=17, duration_minutes=15)
        self.assertEqual((config.fleet_size, config.random_seed, config.duration_minutes), (3, 17, 15))
        first, second = RideSharingSimulation(config), RideSharingSimulation(config)
        first.run()
        second.run()
        self.assertEqual(first.event_history, second.event_history)
        with self.assertRaises(ValueError):
            get_scenario("baseline", fleet_size=0)
        with self.assertRaises(TypeError):
            get_scenario("baseline", unknown_parameter=1)

    def test_calls_return_fresh_immutable_configurations(self):
        first, second = get_scenario(), get_scenario()
        self.assertIsNot(first, second)
        with self.assertRaises(FrozenInstanceError):
            first.fleet_size = 99
        self.assertEqual(get_scenario("small_fleet").fleet_size, 5)

    def test_unknown_name_reports_available_scenarios(self):
        with self.assertRaisesRegex(ValueError, "Unknown scenario.*baseline"):
            get_scenario("missing")


if __name__ == "__main__":
    unittest.main()

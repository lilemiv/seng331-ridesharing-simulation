"""Independent numerical examples for replication-level inference."""

import math
import unittest

from inference import confidence_interval, estimate_replications


class ConfidenceIntervalTests(unittest.TestCase):
    def test_hand_calculated_five_observations(self):
        result = confidence_interval([1, 2, 3, 4, 5])
        self.assertEqual(result.n, 5)
        self.assertEqual(result.mean, 3)
        self.assertAlmostEqual(result.standard_deviation, math.sqrt(2.5))
        self.assertAlmostEqual(result.standard_error, math.sqrt(0.5))
        # Independent tabulated t(4, .975) = 2.7764451051977987.
        half = 2.7764451051977987 * math.sqrt(0.5)
        self.assertAlmostEqual(result.half_width, half, places=10)
        self.assertAlmostEqual(result.lower, 3 - half, places=10)
        self.assertAlmostEqual(result.upper, 3 + half, places=10)

    def test_two_observations_use_t_not_normal(self):
        result = confidence_interval([0, 2])
        self.assertAlmostEqual(result.half_width, 12.706204736432095, places=8)

    def test_empty(self):
        result = confidence_interval([])
        self.assertEqual(result.n, 0)
        self.assertIsNone(result.mean)
        self.assertIsNone(result.half_width)

    def test_single_observation(self):
        result = confidence_interval([7])
        self.assertEqual(result.mean, 7)
        self.assertIsNone(result.standard_deviation)
        self.assertIsNone(result.lower)

    def test_zero_variance(self):
        result = confidence_interval([4, 4, 4])
        self.assertEqual((result.standard_deviation, result.standard_error, result.half_width), (0, 0, 0))
        self.assertEqual((result.lower, result.upper), (4, 4))

    def test_missing_is_not_zero(self):
        result = confidence_interval([None, 2, 4, None])
        self.assertEqual((result.n, result.missing, result.mean), (2, 2, 3))

    def test_generator_not_mutated_or_rounded(self):
        values = [0.123456789123, 0.987654321987, 0.333333333333]
        result = confidence_interval(iter(values))
        self.assertAlmostEqual(result.mean, sum(values) / 3, places=15)

    def test_configurable_confidence(self):
        self.assertLess(confidence_interval([1, 2, 3], .90).half_width,
                        confidence_interval([1, 2, 3], .99).half_width)

    def test_invalid_confidence(self):
        for value in (0, 1, -1, math.nan, math.inf, True, "95"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                confidence_interval([1, 2], value)

    def test_invalid_observations(self):
        for value in (math.nan, math.inf, -math.inf, True, "2"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                confidence_interval([1, value])


class ReplicationEstimateTests(unittest.TestCase):
    def test_known_minimum_count(self):
        # Pilot s^2 = 2.5; t(11,.975)*sqrt(2.5/12)=1.0046 > 1,
        # t(12,.975)*sqrt(2.5/13)=.9554 < 1. Minimum total n is 13.
        result = estimate_replications([1, 2, 3, 4, 5], 1)
        self.assertEqual(result.required_replications, 13)
        self.assertAlmostEqual(result.estimated_variance, 2.5)
        self.assertEqual(result.pilot_sample_size, 5)
        self.assertLessEqual(result.estimated_half_width, 1)
        self.assertTrue(result.target_reachable)

    def test_existing_pilot_already_sufficient(self):
        self.assertEqual(estimate_replications([1, 2, 3, 4, 5], 2).required_replications, 5)

    def test_zero_variance_retains_pilot_count(self):
        result = estimate_replications([2, 2, 2], .001)
        self.assertEqual(result.required_replications, 3)
        self.assertEqual(result.estimated_half_width, 0)

    def test_cap_does_not_claim_precision(self):
        result = estimate_replications([1, 2, 3], .00001, max_replications=10)
        self.assertEqual(result.required_replications, 10)
        self.assertFalse(result.target_reachable)
        self.assertGreater(result.estimated_half_width, result.target_half_width)

    def test_missing_pilot_population(self):
        result = estimate_replications([1, None, 2, 3], 1)
        self.assertEqual((result.pilot_sample_size, result.missing), (3, 1))

    def test_insufficient_pilot(self):
        for values in ([], [1], [None, 1]):
            with self.subTest(values=values), self.assertRaises(ValueError):
                estimate_replications(values, 1)

    def test_invalid_beta(self):
        for beta in (0, -1, math.nan, math.inf, True, "1"):
            with self.subTest(beta=beta), self.assertRaises(ValueError):
                estimate_replications([1, 2], beta)

    def test_invalid_cap(self):
        for cap in (0, 1, 2.5, True, 2):
            with self.subTest(cap=cap), self.assertRaises(ValueError):
                estimate_replications([1, 2, 3], 1, max_replications=cap)

    def test_tighter_precision_and_higher_confidence_need_more_runs(self):
        pilot = [1, 2, 3, 4, 5]
        self.assertGreater(estimate_replications(pilot, .5).required_replications,
                           estimate_replications(pilot, 1).required_replications)
        self.assertGreater(estimate_replications(pilot, 1, .99).required_replications,
                           estimate_replications(pilot, 1, .95).required_replications)

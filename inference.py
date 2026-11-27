"""Student-t inference on independent replication outputs, not customer rows."""

from dataclasses import dataclass
from math import isfinite, sqrt
from statistics import mean, stdev

from scipy.stats import t


def positive_integer(value: int, name: str, minimum: int = 1) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}.")


def _confidence(value: float) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value < 1:
        raise ValueError("Confidence must be strictly between zero and one.")


def _observations(values):
    rows = tuple(values)
    valid = tuple(value for value in rows if value is not None)
    if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not isfinite(x)
           for x in valid):
        raise ValueError("Observations must be finite numbers or None for missing values.")
    return valid, len(rows) - len(valid)


@dataclass(frozen=True)
class ConfidenceInterval:
    confidence: float
    n: int
    missing: int
    mean: float | None
    standard_deviation: float | None
    standard_error: float | None
    lower: float | None
    upper: float | None
    half_width: float | None


def confidence_interval(values, confidence: float = 0.95) -> ConfidenceInterval:
    """Missing values are counted and excluded; n < 2 has no interval."""
    _confidence(confidence)
    samples, missing = _observations(values)
    n = len(samples)
    center = mean(samples) if n else None
    if n < 2:
        return ConfidenceInterval(confidence, n, missing, center, None, None, None, None, None)
    sd = stdev(samples)
    se = sd / sqrt(n)
    half_width = float(t.isf((1 - confidence) / 2, n - 1)) * se
    return ConfidenceInterval(confidence, n, missing, center, sd, se,
                              center - half_width, center + half_width, half_width)


@dataclass(frozen=True)
class ReplicationEstimate:
    confidence: float
    target_half_width: float
    pilot_sample_size: int
    missing: int
    estimated_variance: float
    required_replications: int
    estimated_half_width: float
    max_replications: int
    target_reachable: bool


def estimate_replications(pilot, beta: float, confidence: float = 0.95,
                          max_replications: int = 1_000_000) -> ReplicationEstimate:
    """Smallest n >= pilot n with t(n-1)*s_pilot/sqrt(n) <= beta.

    Beta is assumed to be an absolute CI half-width, in the metric's units.
    Pilot variance is held fixed; this is planning, not a precision guarantee.
    Binary search refines the t critical value using the candidate degrees of
    freedom. A cap is explicit and never reported as achieving the target.
    """
    _confidence(confidence)
    if isinstance(beta, bool) or not isinstance(beta, (int, float)) or not isfinite(beta) or beta <= 0:
        raise ValueError("Beta must be a finite positive absolute half-width.")
    positive_integer(max_replications, "max_replications", 2)
    interval = confidence_interval(pilot, confidence)
    if interval.n < 2:
        raise ValueError("At least two nonmissing pilot observations are required.")
    if max_replications < interval.n:
        raise ValueError("Replication cap must be at least the pilot sample size.")

    def half_width(n):
        return float(t.isf((1 - confidence) / 2, n - 1)) * (interval.standard_deviation / sqrt(n))

    low, high = interval.n, max_replications
    reachable = half_width(high) <= beta
    if reachable:
        while low < high:
            mid = (low + high) // 2
            if half_width(mid) <= beta:
                high = mid
            else:
                low = mid + 1
    else:
        low = max_replications
    return ReplicationEstimate(confidence, beta, interval.n, interval.missing,
                               interval.standard_deviation ** 2, low,
                               half_width(low), max_replications, reachable)

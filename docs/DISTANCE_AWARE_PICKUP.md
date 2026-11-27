# Optional distance-aware pickup

The default model remains the original Uniform(2,8) pickup distribution. The
optional distance-aware mode lets driver selection affect service occupancy and
therefore queue delay, completions, abandonment, and utilization. It is a separate
modeling assumption, not a replacement for the original project specification.

## Configuration and units

| Parameter | Default | Validation |
| --- | --- | --- |
| `pickup_mode` | `"uniform"` | `"uniform"` or `"distance_aware"` |
| `pickup_speed_units_per_minute` | `1.0` | Finite, positive number; not boolean |
| `pickup_base_delay_minutes` | `1.0` | Finite, nonnegative number; not boolean |
| `pickup_min_minutes`, `pickup_max_minutes` | `2.0`, `8.0` | Existing positive ordered limits; used only by uniform mode |

All existing configuration validation remains active in either mode. Scenario
presets accept the new options through their existing keyword overrides.

For the chosen driver position `(x_d, y_d)` and customer pickup `(x_c, y_c)`:

```text
assignment_distance = hypot(x_d - x_c, y_d - y_c)
uniform:        pickup_duration ~ Uniform(pickup_min_minutes, pickup_max_minutes)
distance_aware: pickup_duration = pickup_base_delay_minutes
                                 + assignment_distance / pickup_speed_units_per_minute
```

One unit means the coordinate unit used by `city_width` and `city_height`. Speed
is expressed in those units per minute; no real-world km/h calibration is implied.
In the default 10 by 10 city, a five-unit pickup takes six minutes with the optional
defaults. The overhead represents dispatch/boarding time, and the speed gives a
simple constant-speed approximation. These are illustrative, configurable values,
not estimates fitted to travel data or chosen to ensure one policy wins.

There is no clipping or rescaling to the 2-8 minute interval. With default city
dimensions the distance-aware formula ranges from 1 to about 15.14 minutes.
Zero distance gives the overhead alone. Zero overhead is allowed; with zero
distance, pickup completes at the assignment timestamp in event sequence order.
Nonfinite distances or computed durations abort the run with `ValueError`;
discard failed runs. Named ownership and the Resource slot are released on error.

The lognormal trip distribution and its arithmetic-mean parameterization are
unchanged. Trip time remains independent of geographic trip length in both modes.

## Architecture and data contract

The FIFO Resource still grants capacity before a policy selects a named driver.
`_assign_driver()` measures distance before reserving the driver's identity.
`provide_service()` selects the pickup formula, then schedules pickup and trip
with the existing SimPy processes. The driver remains busy through both stages.
Patience applies only before assignment, and expiry still wins exact deadline ties.
The driver's last-known position changes to the destination only at trip completion.

`request.assignment_distance` records the assignment-time distance in **both**
modes. It is `None` for waiting and abandoned customers and remains available for
completed or unfinished assigned requests. It is read-only to consumers and is
checked against the assignment position in driver history by the invariants.

This property is backed by private request state rather than a dataclass field,
preserving the existing request constructor, `asdict()` schema, and equality
behavior. Read it explicitly, just like `driver_assignment_time` and `service_stage`.
Dataclass equality alone does not compare assignment distance; reproducibility
checks should compare the property too. A newly constructed/replaced request starts
with no recorded distance; use the engine-owned ledger for analysis.

The customer event schema, driver event schema, and event CSV are unchanged.
Spatial measurements are available through the request objects and driver history,
not through the legacy event CSV. No change to `metrics.py` is needed.

## Matched random inputs

For the same seed, city dimensions, fleet size, demand, and horizon, all four
policy/mode combinations share:

- Arrival times and patience samples for each request.
- Customer pickup and destination coordinates for each request.
- Initial driver positions.
- The seeded lognormal trip-draw sequence.

The eight existing RNG streams keep their offsets from `abs(random_seed)`:
arrivals 0, patience 1, pickup 2, trips 3, initial drivers 4, pickup locations 5,
destinations 6, random dispatch 7. No new stream or global RNG is introduced.
Uniform mode consumes the pickup stream at assignment exactly as before.
Distance-aware mode consumes no pickup-duration randomness.

Trip durations are drawn when pickup completes. Policies/modes can change pickup
completion order, which customers receive each trip draw, and how many draws occur
before the horizon. They do **not** guarantee identical trip durations per request.
Random dispatch likewise consumes one selection per assignment, whose number and
available candidates can change. Nearest selection does not consume that stream.
Fleet positions after initialization are endogenous and need not stay matched.

Uniform mode still gives identical aggregate timing across policies for matched
inputs. Distance-aware mode can change release times and downstream outcomes.
With one driver or only one available candidate, a policy difference may disappear.

These guarantees support matched diagnostics, not statistical independence across
replications. A future replication runner must avoid overlapping seed bundles
`abs(seed)+0..7`; consecutive base seeds reuse stream seeds, and `s`/`-s` duplicate
runs. Replications, confidence intervals, and experiment design remain Person 2 work.

## Reproduce the four combinations

Use the project virtual environment from the repository root. On Windows, start
`.\.venv\Scripts\python.exe` and paste the following; on Linux/macOS use
`.venv/bin/python`.

```python
from math import fsum
from config import SimulationConfig
from simulation import RideSharingSimulation
from metrics import average_queue_delay, abandonment_rate, driver_utilization

for mode in ("uniform", "distance_aware"):
    for policy in ("random", "nearest"):
        sim = RideSharingSimulation(SimulationConfig(
            random_seed=42, dispatch_policy=policy, pickup_mode=mode,
            pickup_speed_units_per_minute=1.0, pickup_base_delay_minutes=1.0,
        ))
        sim.run()
        assigned = [r for r in sim.requests if r.assignment_distance is not None]
        count = len(assigned)
        distance = fsum(r.assignment_distance for r in assigned) / count if count else None
        pickup = fsum(r.pickup_duration for r in assigned) / count if count else None
        print(policy, mode, count, distance, pickup,
              average_queue_delay(sim.requests).mean,
              sum(r.status == "completed" for r in sim.requests),
              abandonment_rate(sim.requests),
              driver_utilization(sim.event_history, sim.env.now, sim.config.fleet_size))
```

Distance and pickup means above use all assigned requests, including unfinished
service. Pickup duration is a scheduled duration, not proof that pickup completed.
Queue delay uses assigned customers; system time uses completed customers only.
Time-average Q/N and utilization include partial exposure through the exclusive
horizon. No late pickup/trip completion is invented.

Executed seed-42, 60-minute, 20-driver example (86 arrivals in every run):

| Dispatch | Pickup | Mean distance | Mean pickup (min) | Queue delay (min) | Completed | Abandonment | Utilization |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Random | uniform | 5.5563 | 4.6957 | 0.2825 | 58 | 9.30% | 86.65% |
| Nearest | uniform | 4.4025 | 4.6957 | 0.2825 | 58 | 9.30% | 86.65% |
| Random | distance_aware | 5.2195 | 6.2195 | 0.5450 | 54 | 13.95% | 89.13% |
| Nearest | distance_aware | 3.6743 | 4.6743 | 0.2141 | 59 | 9.30% | 84.50% |

Here the formula turns different assignment distances into different pickup times,
which changes driver releases, later queues, assignments, and completions. In the
five-driver diagnostic with the same seed, distance-aware random completed 19 trips
and nearest 17; their mean distances were 5.2577 and 5.7173. Nearest minimizes each
selection over its own current idle candidates, not the full-run objective across
different evolving fleet states. A smaller assigned-customer queue delay can also
reflect which customers were served rather than improved outcomes for all arrivals.
Do not infer statistical significance or universal policy superiority from these
single-seed examples.

## Verification and handoff

Run `.\.venv\Scripts\python.exe -B -m unittest discover -v` on Windows.
The original 182 tests remain unchanged; 35 new tests cover validation, formula,
zero pickup, both policies/modes, RNGs, capacity, FIFO, abandonment, destination
updates, conservation, reproducibility, history/CSV replay, metrics, and horizons.
Full discovery passes 217 tests. The 20 uniform-mode comparisons against the
pre-change engine match all legacy request/event fields, driver histories, RNG
states, CSV bytes, metrics, and CLI output; only configuration gains three fields.

Person 2 can use configuration mode/policy/seed and `assignment_distance` alongside
the existing metric APIs. No statistical runner, confidence intervals, plots, or
new spatial-metric module is added.

Person 3 can continue passing `event_history` to the unchanged schematic viewer.
The future Event Graph update should label pickup as configurable Uniform(a,b) or
overhead + distance/speed and allow zero delay. Driver travel visualization still
requires joining requests with driver history; continuous routes are not modeled.
This change does not modify the Event Graph, visualization, or notebook.

PR #9's comment cleanup remains separate. This branch starts from main `675637a`
and does not merge or edit the cleanup branch.

# Project 9: Ride-Sharing Dispatch in a City Zone

## Ownership and scope

This repository implements the Weeks 1-2 core simulation for a three-person
Modeling and Simulation with Python project. Core delivery target: November 27,
2026. Steps 1-5 complete the engine. Person 1's approved Week 2 scope adds CI,
configuration reuse, raw event export, bounded testing, and integration support.
Statistics and visualization remain with their assigned team members; further
driver/location/policy development requires a separately agreed scope.

## Core simulation checklist

- [x] Python and SimPy discrete-event engine; minutes throughout; no GUI.
- [x] Poisson arrivals with configurable mean interarrival time (default 0.75 min).
- [x] Configurable anonymous driver capacity (default 20), using `simpy.Resource`.
- [x] FIFO waiting, driver allocation, and release after service.
- [x] Independent exponential patience sampled once per arrival (mean 5 min,
  configurable within 3-8 min). Individual samples are not restricted to 3-8 min.
- [x] Abandonment cancels queued requests. Expiry wins exact assignment ties.
- [x] Uniform pickup duration (default 2-8 min; positive ordered limits configurable).
- [x] Lognormal trip duration (default arithmetic mean 10 min, log-scale sigma 0.5).
- [x] One driver remains occupied through pickup and trip; no abandonment after assignment.
- [x] Request history, stage timestamps, sampled durations, and current status exposed.
- [x] Separate seeded streams for arrivals, patience, pickup, and trip.
- [x] Automated regression, resource, abandonment, stage, and horizon checks.
- [x] Immutable, timestamped event snapshots for raw Q/N/B reconstruction.
- [x] Automatic end-of-run invariants, actual FIFO customer view, and driver ownership checks.
- [x] README, integration handoff, measurement definitions, and dispatch extension design.
- [x] Original 50 tests retained, plus 20 final verification/history tests.

## Week 2 Person 1 infrastructure checklist

- [x] GitHub Actions on PRs targeting main and pushes to main: Python 3.14,
  requirements installation, unittest discovery, read-only contents permission,
  and no external API secrets. View results under PR Checks or Actions > Python tests.
- [x] Validated presets for baseline, low/high demand, and small/large fleets.
  Defaults and random streams are unchanged; no experiment runner is introduced.
- [x] Optional standard-library CSV export with all 12 actual event fields,
  header-only empty history support, raw precision, and stable input order.
- [x] 21 additional automated tests: 6 presets, 6 CSV, 9 stress tests. All 70
  original tests are retained unchanged; discovery runs 91 tests on this baseline.
- [x] Integration review confirms existing lifecycle and event fields are sufficient
  for the current non-geographic Week 2 consumers; no engine refactor is required.
- [x] README and TEAM_HANDOFF document usage, schema, CI, ownership, and limitations.

Presets use `scenarios.get_scenario(name, **overrides)`. Baseline is unchanged;
low/high demand set mean interarrival to 1.5/0.25 minutes; small/large fleet set
capacity to 5/40. All unspecified settings retain `SimulationConfig` defaults.
Export explicitly with `event_export.export_event_history(sim.event_history, path)`;
normal runs create no CSV. Column definitions are in TEAM_HANDOFF sections 5/12.

Verify locally with `.venv\Scripts\python.exe -B -m unittest discover -v`.
Hosted CI execution is separate from local verification. The original infrastructure
baseline was main `95fda6d`; PR #2 was separate at that delivery. The current
statistics baseline is main `100696b`, which already includes merged PRs #2/#3.

## Week 2 Person 2 statistics checklist

- [x] Dedicated `metrics.py` with modular calculations and no new dependencies.
- [x] Queue delay: assignment minus arrival over assigned customers, including
  unfinished pickup/trip; abandoned and still-waiting customers excluded.
- [x] Completed system time: completion minus arrival over completed trips only.
  Abandoned residence and unfinished/censored requests excluded.
- [x] Both customer means expose the exact observation denominator via
  `SampleMean.count` and the unrounded value via `.mean`; empty means are 0/count 0.
- [x] Time-average Q and N from post-event states, divided by observation time T;
  N includes waiting, pickup, and trip and excludes completed/abandoned customers.
- [x] Driver utilization: B area / (configured fleet_size * T), including partial
  pickup and trip exposure; waiting and abandoned customers do not occupy drivers.
- [x] Shared integration sorts by time/sequence, handles simultaneous zero-duration
  events, zero initial state, final exposure through T, and clipping after T.
  Empty history and T=0 return zero; invalid numerical inputs raise `ValueError`.
- [x] Abandonment fraction uses all arrivals as denominator, including unfinished
  requests. Fractions [0,1] become percentages only for display; the retained
  legacy `abandonment_rate_percent` dictionary key stays on the 0-100 scale.
- [x] CLI displays all six metrics, minutes, and customer observation counts.
  Calculations live only in `metrics.py`; the existing Week 1 import is preserved.
- [x] 35 new tests cover exact Q/N/B integrals, all requested outcome/horizon
  cases, independent per-request exposure checks, precision, bounds,
  reproducibility, non-mutation, real engine outputs, CLI, and Week 1 compatibility.
  All 99 baseline tests are retained; discovery passes 134 tests, zero failures/errors.
- [x] README usage and TEAM_HANDOFF section 13 document API, formulas, populations,
  denominators, horizon conventions, mathematical examples, and verification.

Use the ledger from a successful run and pass `sim.event_history`, `sim.env.now`,
and `sim.config.fleet_size` to time-based metrics. Abandoned residence time is
abandonment minus arrival, a separate population; no residence mean is exposed.
Request means do not reconstruct an earlier horizon from later final statuses.
The exclusive engine horizon and all core interfaces are unchanged. No statistics
function rounds results. The full suite was run after each implementation task;
the final command is `python -m unittest discover -v` in the virtual environment.

Week 3 warm-up, replications, confidence intervals, beta analysis, and experiments
remain future work. This statistics delivery does not change Person 3's Event
Graph, animation, or notebook work. Results describe one finite run, not steady state.

## Lognormal configuration

For a duration `T = exp(Y)` with `Y ~ Normal(mu, sigma^2)`, the arithmetic mean
is `E[T] = exp(mu + sigma^2 / 2)`. Configuration exposes `trip_mean_minutes` and
`trip_sigma`; `trip_mu` is derived as `log(trip_mean_minutes) - trip_sigma^2 / 2`.
Defaults give `mu = 2.177585093...`, `sigma = 0.5`, and arithmetic mean 10 minutes.
The mean is a distribution property; a particular run's sample mean will vary.
Sigma zero is supported as the deterministic limiting case. Extreme parameters
that produce nonfinite or zero floating-point trip samples abort the run with
`ValueError`; failed runs should be discarded.

## Integration contract

Create `RideSharingSimulation(SimulationConfig(...))`, call `run()` once, and read
`simulation.requests` and `simulation.event_history`. Each successful run checks
invariants automatically; `validate_invariants()` can also be called at a settled
run boundary. The request list retains every arrival, including abandoned and
unfinished requests, in request-ID order. Its entries are mutable `RideRequest`
dataclasses maintained by the engine; consumers should treat them as read-only.

| Field/property | Meaning |
| --- | --- |
| `request_id` | Unique sequential integer, starting at 1 |
| `arrival_time` | Time the request entered the system |
| `patience_time` | Sampled waiting allowance, measured from arrival |
| `service_start_time` | Driver assignment time, preserved from earlier steps |
| `driver_assignment_time` | Read-only alias of `service_start_time` |
| `pickup_start_time` | Pickup begins at assignment |
| `pickup_completion_time` | Actual end of pickup |
| `trip_start_time` | Actual trip start, equal to pickup completion |
| `completion_time` | Actual trip end, preserved from earlier steps |
| `trip_completion_time` | Read-only alias of `completion_time` |
| `pickup_duration`, `trip_duration` | Sampled durations, set only when the respective stage starts |
| `abandonment_time` | Actual departure time for an abandoned customer |
| `status` | `waiting`, `in_service`, `completed`, or `abandoned` |
| `service_stage` | Derived read-only property: `pickup`/`trip` while in service, otherwise `None` |

All time fields use simulation minutes. `None` means the event has not occurred;
never replace it with zero or infer completion from a sampled duration. Completed
and abandoned are terminal statuses. `in_service` covers both service stages.
For reconstructing past states, use timestamps; `status`/`service_stage` describe
the current state at the end of a run. `dataclasses.asdict(request)` includes stored
fields; read-only aliases and the stage property must be accessed separately.

`waiting_requests` is a tuple of customers in actual Resource FIFO order.
`driver_pool.queue` holds active SimPy resource request events, not the arrival
history or customer records. `busy_driver_count` and `driver_pool.count` expose
occupied capacity. The engine
uses anonymous driver slots; it provides no driver IDs, coordinates, or routes.

The horizon is exclusive: events exactly at `duration_minutes` are not processed.
Runs stop with unfinished requests still waiting or holding a driver. Their future
timestamps stay `None`; the engine does not drain service after the horizon.
At individual internal SimPy events, a resource grant may precede its customer's
timestamp update at the same clock time; inspect after all events at that time
have settled when comparing the ledger with resource counts.

Local RNG seeds are `abs(random_seed)` plus offsets 0, 1, 2, and 3 for arrivals,
patience, pickup, and trips respectively. Normalization prevents negative seeds
from collapsing different streams. The seed must be an integer. Service
parameter changes preserve arrival/patience samples but can change later
assignments and which requests reach each service stage.

Run locally using `.venv\Scripts\python.exe main.py` and verify using
`.venv\Scripts\python.exe -B -m unittest discover -v`.

`event_history` contains immutable `SimulationEvent` snapshots, with ordered
lifecycle events plus initial and horizon markers. Fields include time, sequence,
event type, request ID/status/stage, arrivals, waiting Q, in-system N, busy drivers
B, completed, and abandoned. Same-time events keep sequence order; use the last
row at a time for the state until the next distinct timestamp. History supplies
raw states only, not metrics or plots. See [TEAM_HANDOFF.md](TEAM_HANDOFF.md) for
the complete schema, censoring rules, timing definitions, and consumer instructions.

## Remaining team responsibilities

- [ ] Person 2: further statistical analysis beyond the completed Week 2 metrics.
- [ ] Person 2: multiple replications, confidence intervals, beta analysis, and experiments.
- [ ] Person 3: Event Graph improvements, Matplotlib/Pygame research, Jupyter Notebook,
  2D visualization prototype, event-history visualization integration, and presentation.
- [ ] Group: final report and coordination of statistical plots/visualizations.
- [ ] Instructor-required random-versus-nearest comparison, after an agreed
  driver/location/policy extension is implemented.

Individual driver identities, nearest-driver/advanced dispatch, and further engine
features are deferred beyond this Step 5 handoff and require a separate approved
scope. Their proposed design is documented in TEAM_HANDOFF.md; Resource has not
been replaced and no selection policy or experiment has been implemented.

# Project 9: Ride-Sharing Dispatch in a City Zone

## Ownership and scope

This repository implements the Weeks 1-2 core simulation for a three-person
Modeling and Simulation with Python project. Core delivery target: November 27,
2026. Step 5 is the final core verification and team handoff. Further development
requires explicit approval.

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
`.venv\Scripts\python.exe -m unittest -v`.

`event_history` contains immutable `SimulationEvent` snapshots, with ordered
lifecycle events plus initial and horizon markers. Fields include time, sequence,
event type, request ID/status/stage, arrivals, waiting Q, in-system N, busy drivers
B, completed, and abandoned. Same-time events keep sequence order; use the last
row at a time for the state until the next distinct timestamp. History supplies
raw states only, not metrics or plots. See [TEAM_HANDOFF.md](TEAM_HANDOFF.md) for
the complete schema, censoring rules, timing definitions, and consumer instructions.

## Other team members' responsibilities (not implemented here)

- [ ] Performance statistics and metrics; Q(t), N(t), and B(t) plots.
- [ ] Multiple replications, confidence intervals, beta analysis, and comparisons.
- [ ] Final Event Graph documentation and Jupyter Notebook organization.
- [ ] 2D animation, final report, and presentation.
- [ ] Instructor-required random-versus-nearest comparison, after an agreed
  driver/location/policy extension is implemented.

Individual driver identities, nearest-driver/advanced dispatch, and further engine
features are deferred beyond this Step 5 handoff and require a separate approved
scope. Their proposed design is documented in TEAM_HANDOFF.md; Resource has not
been replaced and no selection policy or experiment has been implemented.

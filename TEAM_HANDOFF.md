# Core Simulation Team Handoff

## 1. Setup, execution, and tests

Use Python 3.10+ and run the following from the repository directory in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
.\.venv\Scripts\python.exe -B -m unittest discover -v
```

The verified environment uses Python 3.14.7 and SimPy 4.1.2. Requirements permit
SimPy 4.1.x and later 4.x versions; retain the verified versions when reproducing
the handoff output. On macOS/Linux, use `.venv/bin/python`. No test runner package
or display is needed for tests, but full discovery requires importable Tkinter.
The viewer additionally needs Tcl/Tk and a graphical desktop (section 7).
Requirements contain SimPy (`simpy>=4.1,<5`) and Matplotlib for existing plots.
Do not copy another member's `.venv` directory.

## 2. Configuration

Create a fresh immutable `SimulationConfig` and engine for every independent run.
All durations and time limits are in minutes.

| Setting | Default | Meaning / constraint |
| --- | --- | --- |
| `mean_interarrival_minutes` | `0.75` | Positive finite exponential mean (45 seconds) |
| `duration_minutes` | `60.0` | Positive finite exclusive simulation horizon |
| `random_seed` | `42` | Integer seed; booleans are rejected |
| `fleet_size` | `20` | Positive integer number of named drivers |
| `mean_patience_minutes` | `5.0` | Exponential mean, inclusive range 3-8 |
| `pickup_min_minutes` | `2.0` | Positive finite uniform lower bound |
| `pickup_max_minutes` | `8.0` | Finite upper bound, at least the lower bound |
| `trip_mean_minutes` | `10.0` | Positive finite arithmetic trip mean |
| `trip_sigma` | `0.5` | Finite nonnegative log-scale standard deviation |
| `city_width`, `city_height` | `10.0`, `10.0` | Positive finite abstract city bounds |
| `dispatch_policy` | `"random"` | `"random"` or `"nearest"` |
| `pickup_mode` | `"uniform"` | `"uniform"` or `"distance_aware"` |
| `pickup_speed_units_per_minute` | `1.0` | Positive finite pickup speed |
| `pickup_base_delay_minutes` | `1.0` | Nonnegative finite overhead |

`trip_mu` is derived as `log(trip_mean_minutes) - trip_sigma^2 / 2`. The sampler
uses `exp(Normal(mu, sigma^2))`, whose arithmetic mean is
`exp(mu + sigma^2 / 2)`. Do not pass the desired arithmetic mean as `mu`.
The default mu is approximately 2.177585. Sigma zero is a deterministic limiting
case. Pickup bounds may be equal. Individual patience samples can be outside 3-8.

The original four local RNGs use `abs(random_seed) + offset`, where offsets
0/1/2/3 belong to arrivals, patience, pickup and trips. Negative seeds normalize
to their absolute value, matching Python's integer seeding behavior. These
streams stay distinct. Service samples never consume arrival/patience randomness.
Additional offsets 4/5/6/7 are initial driver locations, customer pickups,
destinations and random dispatch. All eight seeds must be disjoint across future
independent replications. Uniform pickup is sampled at assignment; distance-aware
pickup uses assignment distance without consuming the uniform pickup RNG.
Trip duration is sampled when the trip starts.
Different parameters can change who receives service even when arrivals and
patience samples remain identical.

## 3. Stable integration interface

```python
from dataclasses import asdict
from config import SimulationConfig
from simulation import RideSharingSimulation

config = SimulationConfig(fleet_size=20, duration_minutes=60, random_seed=42)
sim = RideSharingSimulation(config)
sim.run()

request_rows = [asdict(request) for request in sim.requests]
event_rows = [asdict(event) for event in sim.event_history]
fifo_customers = sim.waiting_requests  # Tuple of RideRequest objects in actual FIFO order.
busy_count = sim.busy_driver_count
actual_duration = sim.env.now
fleet_size = sim.config.fleet_size
```

These examples access raw data only; they do not compute statistical results.
`run()` is intended to be called once per instance. It ends at `duration_minutes`,
records a boundary snapshot, then calls `validate_invariants()`. That method can
also be called at a settled run boundary; it raises `RuntimeError` on invalid
results. It is not a synchronization mechanism for arbitrary internal `env.step()`
points. A Resource grant and its customer's callback can be separate internal
events at the same simulation time.

`requests` is the complete arrival ledger in sequential ID order, including all
abandoned and unfinished customers. Treat the list and its mutable records as
read-only. `waiting_requests` is a tuple snapshot of current FIFO membership;
its contained customer records are the same engine-owned objects. The underlying
`driver_pool.queue` contains SimPy request events, not customer records.
`busy_driver_count` exposes occupied Resource slots. The existing `driver_pool`,
`env`, `config`, `requests`, and timestamp fields remain available.

## 4. Lifecycle and request records

```text
waiting -> in_service (pickup -> trip) -> completed
waiting -> abandoned
```

Pickup represents the assigned driver traveling to the customer. Pickup completion
is the customer's boarding/trip start. Driver and customer coordinates are modeled;
routes and continuous movement are not.
A driver is occupied continuously from assignment through trip completion.
Patience applies only before assignment; exact assignment/expiry ties favor expiry.

### Event Graph

```mermaid
flowchart TD
    arrival([Request Arrival])
    available{"Driver Availability<br/>Check"}
    queue["Waiting Queue - FIFO<br/>Patience: Exponential, mean 5 min"]
    abandon([Customer Abandonment])
    assign([Driver Assignment])
    pickup["Pickup<br/>Uniform 2-8 min; driver busy"]
    pickupDone([Pickup Completion])
    trip["Trip execution<br/>Lognormal, arithmetic mean 10 min; driver busy"]
    tripDone([Trip Completion])
    release([Driver Release])

    arrival -->|"Next arrival after<br/>Exponential interarrival, mean 0.75 min"| arrival
    arrival --> available
    available -->|"Free capacity, FIFO turn,<br/>and before patience deadline"| assign
    available -->|"Otherwise: wait or expire"| queue
    queue -->|"Free capacity, FIFO turn,<br/>and strictly before patience deadline"| assign
    queue -->|"Patience deadline reached<br/>Expiry wins exact ties"| abandon
    assign --> pickup
    pickup --> pickupDone
    pickupDone --> trip
    trip --> tripDone
    tripDone --> release
    release -.->|"Capacity signal:<br/>check the next eligible FIFO waiter"| available
```

This is the same corrected lifecycle graph shown in [README.md](README.md#event-graph).
Assignment requires free capacity, FIFO eligibility, and an unexpired patience
deadline. Drivers stay busy throughout pickup and trip. The dashed return link
signals released capacity for another waiting customer, not a completed
customer returning to the queue.

| Record member | Meaning |
| --- | --- |
| `request_id` | Unique sequential integer starting at 1 |
| `arrival_time` | Customer enters the system |
| `patience_time` | Sampled allowance, measured from arrival |
| `service_start_time` | Driver assignment, preserved from previous steps |
| `driver_assignment_time` | Read-only alias of `service_start_time` |
| `pickup_start_time` | Driver starts pickup; equal to assignment time |
| `pickup_completion_time` | Driver reaches customer; pickup ends |
| `trip_start_time` | Customer trip starts; equal to pickup completion |
| `completion_time` | Customer trip ends; preserved from previous steps |
| `trip_completion_time` | Read-only alias of `completion_time` |
| `pickup_duration`, `trip_duration` | Sampled duration, available once that stage starts |
| `abandonment_time` | Customer leaves before assignment |
| `status` | Current waiting/in_service/completed/abandoned state |
| `service_stage` | Read-only current pickup/trip stage, otherwise `None` |
| `assigned_driver_id` | Named driver ID, or `None` before assignment |
| `pickup_x`, `pickup_y` | Customer pickup coordinates |
| `destination_x`, `destination_y` | Customer destination coordinates |
| `assignment_distance` | Read-only assignment distance, otherwise `None`; outside `asdict()` |

All timestamps are relative to simulation start, in minutes. `None` means an event
has not occurred. Zero is a valid timestamp. A sampled duration is not evidence of
completion. `asdict()` includes stored fields; aliases and `service_stage` must
be accessed separately if consumers want those named columns.

Events at exactly the horizon are excluded. Thus an unfinished pickup has no
pickup completion or trip start; an unfinished trip has no trip completion. The
driver is still busy at the boundary. A waiting customer's deadline can equal the
horizon without abandonment being processed. Unfinished requests are censored,
not completed or abandoned. The engine does not drain customers after the horizon.

## 5. Immutable event history

`sim.event_history` is a list of frozen `SimulationEvent` dataclass snapshots.
Treat the list itself as read-only. Rows do not hold live customer references.

| Column | Meaning |
| --- | --- |
| `sequence` | Zero-based total order, including events at the same time |
| `time` | Simulation timestamp, in minutes |
| `event_type` | Lifecycle event or simulation boundary marker |
| `request_id` | Affected customer ID, or `None` for boundary markers |
| `request_status` | That customer's state immediately after the event |
| `service_stage` | That customer's stage immediately after the event |
| `arrivals` | Cumulative number of arrivals |
| `waiting` | Q: customers awaiting driver assignment |
| `in_system` | N: customers waiting or in service |
| `busy_drivers` | B: logically assigned drivers, including pickup and trip |
| `completed`, `abandoned` | Cumulative terminal customer counts |

Event types are `simulation_start`, `arrival`, `driver_assignment`, `abandonment`,
`pickup_completion`, `trip_completion`, and `simulation_end`. Boundary markers
have no request ID/status/stage. The start row is at time zero with zero counts;
the end row is at the horizon with unchanged final counts. The end marker does
not process lifecycle events excluded by the horizon.

Each row describes the logical state after its named transition. For example,
assignment decreases Q and increases B; pickup completion changes stage but keeps
Q, N, and B unchanged; abandonment decreases Q and N; trip completion decreases N
and B. Every row conserves arrivals as waiting + busy + completed + abandoned.

Several rows can share one timestamp. Preserve `sequence`; do not reorder equal
times by event type or customer ID. An immediate-service arrival has a waiting
row followed by assignment at the same time. For a right-continuous Q/N/B trace,
use the last row at a timestamp as the state until the next distinct timestamp.
Earlier rows at that same time have zero elapsed duration. This also removes
transient SimPy grant/callback differences from duration-based measurements.

The only events produced for an abandoned customer are arrival and abandonment.
The history contains no extra event for a patience timer firing after assignment.
All time boundaries needed to reconstruct occupancy are supplied, including for
empty runs and services unfinished at the horizon.

## 6. Instructions for the statistics developer

Use the following definitions consistently. Person 2's Week 2 implementation is
in `metrics.py`; section 13 documents its API and verification. Integrate through
those functions after a successful `run()`; `main.py` formats their results.
Replications, comparisons, and uncertainty analysis remain future work.

| Quantity | Definition and population |
| --- | --- |
| Queue delay until assignment | Assignment minus arrival, for assigned customers |
| Time until pickup begins | Pickup start minus arrival; equals queue delay in this model |
| Customer waiting until vehicle arrives | Pickup completion minus arrival; includes queue delay and driver travel to the customer |
| Pickup travel duration | Pickup completion minus pickup start |
| Trip duration | Trip completion minus trip start |
| Completed customer's time in system | Trip completion minus arrival |
| Abandoned customer's time in system | Abandonment minus arrival; report separately from completed journeys |
| Driver busy interval | Assignment through trip completion, covering pickup and trip, excluding queue delay |

For unfinished requests, mark missing outcomes as censored. Do not substitute zero
for missing timestamps or mix completed-only averages with censored outcomes
without choosing and stating an appropriate method. For within-run exposure only,
clip an unfinished waiting/busy/system interval at the actual horizon.

For time-average queue length and system population, accumulate each history
state's Q or N over the elapsed interval for which it holds, ending at the horizon,
then normalize by observation duration. Fleet utilization uses the corresponding
B exposure normalized by fleet size and observation duration. This is time
weighting, not an unweighted average of event rows. Use the initial/final markers
and the same-time convention above; include unfinished exposure through the end.
Named assignment/release history now exists (section 8); pooled utilization is
implemented. No per-driver utilization metric API is currently provided.

Throughput uses completed trips over observation time. For customer outcomes,
distinguish completion fraction, assignment fraction, abandonment fraction, and
the still-waiting/in-service fractions at the finite horizon; assignment and
completion are different outcomes. Choose an explicit denominator for each.
Do not infer steady-state results from one short debugging run. Seeds, warm-up,
replications, uncertainty analysis, and experiment designs belong to your work.

## 7. Instructions for the animation and notebook developer

Import the engine as shown above; importing `main.py` does not launch a run.
Use request IDs as stable customer keys and `event_history` sequence/time to replay
lifecycle changes. Use timestamps for past stages; final `status`/`service_stage`
alone do not represent earlier animation frames. Sampled stage durations allow
progress within a stage, but do not invent an observed completion beyond the run
horizon. Keep the final frame consistent with unfinished and abandoned customers.

### Existing Tkinter viewer and launch commands

`city_visualization.py` implements `CityViewer(root: tk.Tk,
events: list[ReplayEvent])`. It projects recorded customer stages into schematic
waiting, pickup, trip, completed, and abandoned areas. It shows aggregate counts,
event details, and simulation time, with Play/Pause, Restart, and a speed slider
(simulated minutes per real second). Equal-time events are applied in sequence
order before drawing that timestamp's frame.

Run from the repository directory with your configured Python:

```powershell
python city_visualization.py
python city_visualization.py --csv events.csv
```

Replace `python` with `.\.venv\Scripts\python.exe` on Windows or
`.venv/bin/python` on macOS/Linux to use the project environment. Without `--csv`,
the entry point runs the default simulation once, normalizes its history, creates
`tk.Tk()`, and starts the viewer's main loop. With `--csv`, it replays a prior
export without running the engine. `main.py` is the console/statistics entry point.

### Replay interfaces

- `normalize_events(events: Iterable[object]) -> list[ReplayEvent]` accepts engine
  event objects or dictionaries such as `csv.DictReader` rows. It converts time,
  IDs, sequence, and counts to numeric values and preserves input order; it does
  not sort. It requires nonnegative finite nondecreasing times, sequences exactly
  `0..n-1`, known event types, absent request IDs only for boundary markers,
  nonnegative counts, `N = Q + B`, and `arrivals = N + completed + abandoned`.
  Empty input or missing first `simulation_start`/last `simulation_end` raises
  `ValueError`. `ReplayEvent` contains sequence/time/type/request ID and six
  counts; it does not retain `request_status` or `service_stage`.
- `ReplayState.apply(event: ReplayEvent) -> None` consumes one normalized event
  in order. It updates `.customers`, a request-ID-to-display-stage dictionary,
  through waiting -> pickup -> trip -> completed, or waiting -> abandoned, and
  stores the latest event in `.event`. It raises `ValueError` for duplicate
  arrivals, invalid lifecycle transitions, or counts that disagree with history.
  Stages are reconstructed from event types rather than final request status.
- `load_csv(path: str | Path) -> list[ReplayEvent]` opens UTF-8 CSV (accepting a
  BOM), passes `csv.DictReader` rows to `normalize_events()`, and returns the
  normalized list. Use a complete export from section 12; a header-only export is
  valid CSV but has no replayable events. Ordinary file/conversion errors propagate.

After `sim.run()` returns, other team members can replay that exact run directly:

```python
import tkinter as tk
from city_visualization import CityViewer, normalize_events

# sim is the successful simulation from section 3.
events = normalize_events(sim.event_history)
root = tk.Tk()
viewer = CityViewer(root, events)
root.mainloop()
```

Alternatively, export `sim.event_history` using section 12 and launch the CSV
command above, or pass `load_csv("events.csv")` to `CityViewer`. For a replay
without opening a window, iterate over normalized events with a fresh
`ReplayState()` and call `.apply(event)` for each row. These consumers do not
modify engine records or recompute simulation outcomes.

### Runtime requirements and limitations

Python must include `tkinter`/`ttk` and its Tcl/Tk runtime. Install Tcl/Tk support
through the Python distribution or operating system if it is missing; it is not
a pip dependency. Opening the viewer requires an accessible graphical desktop.
Headless environments can run the pure replay logic/tests if Tkinter is importable,
but cannot create `tk.Tk()` without a display. The five existing viewer tests
exercise replay state, ordering, CSV round trips, and validation without a window;
they do not verify GUI rendering.

This is an initial **schematic 2D prototype**, not a final polished bonus animation
or a geographic driver movement simulation. Roads/buildings and customer positions
are illustrative; stages change at events rather than through continuous motion.
Crowded areas use overflow counts. The engine provides named drivers, coordinates,
destinations and random/nearest policies (section 8); the viewer displays schematic
customer stages. Initial Q(t)/B(t) plots and the Version 1 notebook exist from
PR #8. Notebook development, broader control/rendering verification and useful
animation improvements remain pending. The latest dispatch Event Graph is in
[EVENT_GRAPH.md](EVENT_GRAPH.md); its uniform-only pickup label needs a future
mode-aware update. The embedded lifecycle diagram above describes default pickup.
Keep notebook and presentation logic outside the engine.

## 8. Implemented Person 1 dispatch and spatial interfaces

PR #7 implements driver identities/locations and both dispatch policies; PR #10
adds optional distance-aware pickup. Both survive the PR #12 revert.
[DISPATCH_DESIGN.md](DISPATCH_DESIGN.md) documents the complete contract.

- Resource remains the FIFO capacity gate. After a valid grant strictly before
  expiry, an idle driver is selected/reserved without yielding. Exact deadline
  ties reserve no identity.
- Frozen `Driver(driver_id, x, y, assigned_request_id)` snapshots use IDs
  `1..fleet_size`; `is_available` is derived from assignment.
  `sim.drivers`, `initial_drivers`, `available_drivers` and `busy_drivers`
  are tuple snapshots. Reacquire views after events.
- Random selection uses an ID-sorted idle set and offset-7 RNG; nearest uses
  Euclidean distance to pickup, breaking exact ties by lowest driver ID.
- Driver coordinates are last known positions. Completion updates to destination
  before releasing capacity; unfinished trips do not move to future destinations.
- `sim.driver_history` is a separate tuple of immutable `DriverEvent` records:
  `sequence, time, event_type, driver_id, request_id, x, y`.
  Join assignment/release events to requests by ID/time. Its sequence is separate
  from customer event sequence; customer CSV remains unchanged.
- `request.assignment_distance` records distance in either pickup mode.
  Uniform remains the default and ignores distance for duration. Optional
  distance-aware pickup is overhead + distance / speed, without clipping to the
  uniform bounds. Trips remain lognormal and route-independent.

Existing API, timing RNG streams, event schema, metrics and replay are preserved.
See [optional pickup details](docs/DISTANCE_AWARE_PICKUP.md).

## 9. Known limitations and checks

`run()` performs conservation, lifecycle, FIFO membership, occupied-slot, and raw
history checks on successful completion. It does not calculate performance metrics.
Tests cover normal/high demand, small/large fleets, abandonment-heavy demand,
simultaneous events, empty runs, horizons, reproducibility, and immutable history.

Resource capacity is paired with named drivers and a separate driver trace.
Coordinates are abstract and do not define routes or continuous movement.
History storage grows with lifecycle events. Both output lists
are engine-owned mutable containers and must not be changed by consumers. Extreme
trip parameters that overflow/underflow floating-point sampling raise `ValueError`;
invariant violations raise `RuntimeError`. Discard failed runs and fix their input
or cause rather than continuing from partial records. Configuration type hints
describe intended inputs; only the documented numerical/seed/fleet checks are
enforced, so do not pass arbitrary nonnumeric objects.

## 10. Remaining group deliverables

Person 2 retains the two Week 3 statistics tasks, and Person 3 retains the two
notebook/visualization tasks. Their scope, proposed interfaces, dependencies and
subsequent-stage ownership are in section 15 and the
[requirements checklist](PROJECT_REQUIREMENTS.md). Initial plots, notebook and
viewer are preserved. Replicated experiments, factor analysis, statistical
notebook integration, final report and presentation remain planned work.

## 11. Week 2 integration compatibility review

No additional engine interface is required for the current statistics or event
replay work. The existing contract supports both direct Python consumption and
optional raw event CSV export. `metrics.py` computes statistics, and
`city_visualization.py` supplies the schematic viewer; the engine supplies raw data.

| Consumer | Existing data | Access |
| --- | --- | --- |
| Person 2 | Lifecycle timestamps, terminal and unfinished states | `sim.requests`: `arrival_time`, `driver_assignment_time`, pickup/trip timestamps, `abandonment_time`, `status`, `service_stage` |
| Person 2 | Q, N, B and cumulative customer counts | `sim.event_history`: `waiting`, `in_system`, `busy_drivers`, `arrivals`, `completed`, `abandoned` |
| Person 2 | Run horizon, fleet, distribution parameters and seed | `sim.config`, `sim.env.now`; presets from `scenarios.get_scenario` |
| Person 3 | Event ordering, timing, customer keys and transitions | `sim.event_history`: `sequence`, `time`, `event_type`, `request_id`, `request_status`, `service_stage` |

Consume data after `run()` returns successfully; treat engine-owned containers
and request records as read-only. Preserve equal-time sequence order and the
exclusive horizon. Missing timestamps remain censored outcomes. CSV is a serialized
snapshot, not a new source of lifecycle events or derived measurements.

Customer event history supports schematic replay. Named drivers, coordinates,
destinations and separate driver history also exist (section 8). They support
future spatial views, but do not supply routes or continuous vehicle positions.
Preserve the customer CSV schema when adding any spatial consumer.

## 12. Week 2 core infrastructure

### Checks and CI

The integrated Week 2 repository includes the core infrastructure, corrected
assigned-customer queue delay, statistics module, and schematic viewer.

Run `.\.venv\Scripts\python.exe -B -m unittest discover -v` (or
`.venv/bin/python -B -m unittest discover -v` on macOS/Linux). Full discovery
passes 217 tests: 70 core, 6 preset, 6 CSV, 9 bounded stress, 3 CLI regression,
5 visualization, 35 metrics, 48 dispatch and 35 distance-aware pickup tests,
with zero failures, errors or skips. The one-day simulation is simulated time,
not a real-time wait. Requirements contain SimPy and Matplotlib; see section 7
for Tkinter requirements. Check dependency consistency with `python -m pip check`.

`.github/workflows/python-tests.yml` runs the same discovery command on Python
3.14 and Ubuntu after installing `requirements.txt`. Triggers are PRs targeting
`main` and pushes to `main`; permissions are `contents: read`, with no external
API keys. Failed tests fail CI. View a PR's **Checks** tab or **Actions > Python
tests**, then open the `unittest` job's logs. Local results and actual hosted CI
results must be reported separately. Enabling Actions and requiring status checks
are repository-owner settings, not changes made by this branch.

### Configuration reuse

```python
from scenarios import SCENARIO_NAMES, get_scenario
from simulation import RideSharingSimulation

config = get_scenario("high_demand", fleet_size=5, random_seed=42)
sim = RideSharingSimulation(config)
sim.run()
```

`SCENARIO_NAMES` lists `baseline`, `low_demand`, `high_demand`, `small_fleet`, and
`large_fleet`. Baseline equals `SimulationConfig()`: mean interarrival 0.75 minutes,
20 drivers. Low/high demand change only that mean to 1.5/0.25 minutes; small/large
fleet change only capacity to 5/40. These are illustrative inputs, not experiments.
Each call returns a fresh frozen config using the existing dataclass validation.
Explicit overrides win; seed, 60-minute horizon, and every unspecified setting
retain their defaults. Unknown scenario names raise `ValueError`; invalid fields
or values follow dataclass errors/validation. There is no experiment runner.

### Optional CSV snapshot

```python
from event_export import export_event_history

export_event_history(sim.event_history, "events.csv")
```

The exporter accepts an iterable of actual `SimulationEvent` records and a string
or path object. It writes UTF-8 using Python's standard `csv` module, does not run
or mutate the simulation, and is never called automatically. Choose an existing
parent directory; existing output files are overwritten and I/O errors propagate.
An empty iterable writes only the header. A zero-arrival simulation still exports
its initial and final boundary markers.

Columns, in order, are:

```text
sequence,time,event_type,request_id,request_status,service_stage,arrivals,waiting,in_system,busy_drivers,completed,abandoned
```

Every column is the identically named field defined in section 5. `waiting` is Q,
`in_system` is N, and `busy_drivers` is B. Counts are logical state after each
event; `time` is simulation minutes. Missing request IDs/statuses/stages become
empty cells, not zero. Numbers are not rounded. Rows preserve supplied order,
including equal-time events; the exporter does not sort or invent observations.

Reopen with `csv.DictReader`; CSV cells are strings. Convert `sequence`, nonempty
`request_id`, and count fields to integers, and `time` to float. Use the last row
at a timestamp for the state until the next distinct timestamp. No metrics,
plots, animation frames, driver identities, or locations are added by export.

## 13. Week 2 Person 2 statistics delivery

### Integrated API

`metrics.py` contains the performance calculations, including the corrected
assigned-customer queue-delay definition. `main.py` calls these functions and
formats output. The engine produces raw history; the viewer consumes it for replay.
`main.calculate_simulation_metrics(requests)` remains an importable alias of
`metrics.calculate_simulation_metrics`, preserving both legacy dictionary keys
and their units. It returns full precision; only the CLI formats numbers.

```python
from metrics import (
    average_queue_delay, average_time_in_system, time_average_queue_length,
    time_average_number_in_system, driver_utilization, abandonment_rate,
)

# sim has completed run() successfully; use its ledger at this same horizon.
delay = average_queue_delay(sim.requests)
system_time = average_time_in_system(sim.requests)
T = sim.env.now
q = time_average_queue_length(sim.event_history, T)
n = time_average_number_in_system(sim.event_history, T)
u = driver_utilization(sim.event_history, T, sim.config.fleet_size)
a = abandonment_rate(sim.requests)
print(delay.mean, delay.count, system_time.mean, system_time.count)
print(f"Driver utilization: {u:.2%}; abandonment: {a:.2%}")
```

Each public metric accepts an iterable of actual engine records. Materialize a
one-shot iterator before reusing it across calls. Request averages assume a valid
ledger at the observation horizon; they do not reconstruct earlier outcomes from
a later ledger. Neither request records, history order, resource state, nor random
streams are mutated. No additional dependencies are needed.

### Populations and denominators

| Metric | Numerator | Denominator / population |
| --- | --- | --- |
| Queue delay | Sum of assignment minus arrival | Assigned count, including completed and active pickup/trip; excludes abandoned and waiting |
| Completed time in system | Sum of completion minus arrival | Completed count only; excludes abandoned and unfinished pickup/trip/waiting |
| Time-average queue length | Integral of engine `waiting` Q(t) | Observation duration T |
| Time-average number in system | Integral of engine `in_system` N(t) | T; N includes waiting and assigned pickup/trip, excludes departures |
| Pooled driver utilization | Integral of engine `busy_drivers` B(t) | Configured fleet_size * T; includes pickup and trip |
| Abandonment rate | Abandoned count | All arrivals, including unfinished arrivals |

Customer means return frozen `SampleMean(mean, count)`, with no rounding. Empty
populations return `SampleMean(0.0, 0)`; the zero mean does not indicate an observed
zero-duration customer. Abandonment residence is abandonment minus arrival and is
distinct from completed-trip system time; no separate residence mean is exposed
in this version. Unfinished requests are censored and excluded from the primary
completed-customer mean, but assigned unfinished requests do enter queue delay.
Do not use sampled durations to fabricate future completion timestamps.

### Integration, horizons, and conventions

The common integration helper sorts a copy by `(event.time, event.sequence)`.
It uses each post-event state until the next timestamp, summing rectangles
`state * elapsed_minutes / T` with `math.fsum`. Utilization uses `B/fleet_size`
as that state. The initial state is zero from 0 until the first event; the last
state persists to T. Equal-time rows contribute zero-duration rectangles, and
the final sequence at that time supplies the following interval. History after
T is ignored for exposure; a row at T has zero following duration. This method
does not average event samples.

The exclusive engine horizon is unchanged: an event scheduled exactly at T is
not processed. Unfinished queue, pickup, and trip exposure is included up to T,
without draining the system. For a successful full run pass `sim.env.now` and
`sim.config.fleet_size`; never normalize busy exposure by arrivals or completions.

Empty histories mean zero state throughout. T=0 returns 0.0 without scanning
history; the engine configuration continues to require positive duration.
Negative/nonfinite horizons and timestamps, negative/nonfinite in-window states,
nonpositive/noninteger/bool fleet capacity, and B above fleet capacity raise
`ValueError`. Valid utilization is bounded at 1.0 only to suppress floating-point
drift. Utilization and abandonment return fractions [0, 1]; multiply by 100 or
use Python percentage formatting for display. The legacy
`abandonment_rate_percent` key is already on the 0-100 scale.

### Mathematical and regression verification

Deterministic example: T=10, Q=0 until 2, Q=3 from 2 to 5, Q=1 from 5 to 10;
Q area is 14 customer-minutes and Q average is 1.4. With B=1 from 2 to 5 and B=2
from 5 to 10, B area is 13 driver-minutes, N area is 27 customer-minutes, N average
is 2.7, and a two-driver fleet has utilization 13/(2*10)=0.65 (65%).

A controlled real run with arrivals 0/1/2/11, patience 100/2/100/100, one driver,
pickup 2, trip 8, and T=13 yields queue delay 4 (n=2), completed system time 10
(n=1), Q average 12/13, N average 25/13, utilization 1, and abandonment 1/4.
This includes completed, abandoned, active-trip, and waiting customers.

`test_metrics.py` adds 35 tests. Tests independently sum per-request timestamp
intervals for Q/N/B exposure and compare against event integrals to 12 decimal
places, including partial service. They check N_average = Q_average + fleet*u,
same-time ordering, initial/final intervals, zero arrivals/windows, empty history,
correct populations, precision, utilization bounds, censoring at exact horizons,
non-mutation, reproducibility, legacy Week 1 imports/values, and CLI formatting.
All 99 baseline tests remain unchanged: 70 core, 21 infrastructure, 3 Week 1 CLI,
and 5 existing visualization tests. With the 35 metrics, 48 dispatch and 35
optional pickup tests, current full discovery passes 217 tests, zero failures,
errors or skips. Run `python -m unittest discover -v` in the project environment.

Default `main.py` output is documented in README:
86 arrivals = 58 completed + 20 active + 0 waiting + 8 abandoned;
queue delay 0.28 (n=78), completed system time 15.01 (n=58), Q average 0.462,
N average 17.792, utilization 86.65%, abandonment 9.30%.

These are descriptive finite-run metrics, with no steady-state or uncertainty
claim. Week 3 warm-up/replications/confidence intervals/beta analysis/experiments
remain pending in current main. Initial Q(t)/B(t) plots and the Version 1 notebook
are present from PR #8; further notebook/visualization work is in section 15.

## 14. Optional distance-aware pickup

`SimulationConfig.pickup_mode` defaults to `"uniform"`, preserving the existing
pickup distribution and deterministic outputs. `"distance_aware"` uses
`pickup_base_delay_minutes + assignment_distance / pickup_speed_units_per_minute`.
Defaults are 1 minute overhead and 1 city coordinate unit/minute.

`request.assignment_distance` is a read-only property recorded at assignment in
both modes; unassigned requests return `None`. Like the existing timestamp aliases,
it is not included in `dataclasses.asdict()` or dataclass equality. Read it explicitly
for spatial analysis. Customer/driver event schemas and the event CSV are unchanged.

See [DISTANCE_AWARE_PICKUP.md](docs/DISTANCE_AWARE_PICKUP.md) for validation, matched
random inputs, reproduction commands, example results, and limitations. Existing
metrics and schematic replay need no code changes. Person 3 should later label the
pickup edge in the Event Graph by mode; this change does not edit the graph/viewer.

## 15. Week 3 team task separation

### Repository recovery

Local main was fast-forwarded to `f46ece5bd797a540a2ce1be4cace1ddb1244b85a`
on November 27, 2026. Both [PR #11](https://github.com/lilemiv/seng331-ridesharing-simulation/pull/11)
and its revert [PR #12](https://github.com/lilemiv/seng331-ridesharing-simulation/pull/12)
are merged. Main contains revert `4a8cde3` and has the pre-PR #11 tree
`98ac3b8590ba06ec25ded4c347f4ab6bf45bb128`. No open PR was found at recovery.
The combined implementation was created, then reverted for team workflow reasons.
It remains recoverable at `c5bc097`, its original branch and PR #11.
Do not merge the old branch or replay the entire combined change.

### 1. Week 1 completed tasks

- [x] SimPy, Poisson arrivals, FIFO, abandonment, uniform pickup/lognormal trips,
  lifecycle timestamps, deterministic streams and legacy CLI/API.

### 2. Week 2 completed tasks

- [x] Person 1: history/invariants, presets, CSV, stress coverage and GitHub Actions.
- [x] Person 2: six finite-run metrics, observation counts and numerical tests.
- [x] Person 3: Event Graph, initial viewer, existing controls and direct/CSV replay.

Initial Q(t)/B(t) plots and Version 1 notebook subsequently merged in PR #8 remain
available. Preserve these prior contributions.

### 3. Person 1 Week 3 completed tasks

- [x] Driver identities/coordinates, customer pickups/destinations, random/nearest
  dispatch, driver location updates, FIFO/abandonment and dispatch tests.
- [x] Optional distance-aware pickup, default uniform mode and core/API compatibility.

### 4. Person 2 Week 3 pending tasks

- [ ] Task 1: independent replications, disjoint reproducible seed bundles,
  structured replication metrics and tests.
- [ ] Task 2: 95% Student's t intervals, sample variance/standard error,
  beta-based replication count estimation and numerical tests.

**Proposed interfaces, documentation only:** the future replication runner takes
an immutable config or preset overrides, master seed, replication count and
starting replication ID. Return one structured record per independent run with
ID, full config, base/eight stream seeds, horizon, customer observation counts
and unrounded metric outcomes. Use existing engine/metric APIs. Do not pool
customers across runs or treat `SampleMean.count == 0` as an observed zero.

A possible bundle allocation is nonnegative base `abs(master_seed) + 8 * id`
and offsets 0..7. Person 2 must specify ID uniqueness across continued batches,
test nonoverlap/reproducibility, and avoid positive/negative seed aliasing.
This proposed contract is not an implemented replication API.

Inference depends on those independent replication outcomes. Proposed inputs:
a metric series and confidence/precision settings. Proposed outputs: valid sample
count, mean, sample variance, SD, SE, t degrees of freedom, interval bounds and
half-width, with explicit missing/insufficient/zero-variance behavior.
Beta planning should report pilot size, definition/units, target precision,
required total/additional replications and any limit/unreachable case.
Agree the instructor's beta definition before implementation; no convention is
silently selected here.

No replication/inference modules or placeholders are present. Select and declare
any Student's t numerical dependency in Person 2's PR; current engine/metrics
require no statistical package. Task 2 follows Task 1's reviewed result contract.

### 5. Person 3 Week 3 pending tasks

- [ ] Task 1: develop the existing notebook with latest Event Graph,
  assumptions/distributions, metrics, executable examples and future statistics.
- [ ] Task 2: review/improve animation; verify Play/Pause/Restart/speed and
  direct/CSV replay for both policies/modes; add regression tests.

Use `normalize_events`, `load_csv`, `ReplayState` and `CityViewer` from section 7.
Preserve customer schema and equal-time ordering. Spatial views can use section
8's separate driver/request data; the viewer currently uses schematic positions.

Preserve initial notebook cells and `plot_q_b(sim.event_history)`. Notebook
statistical sections should consume Person 2's future records rather than
duplicate inference. Explanations/examples and visualization work can proceed now;
actual statistical integration follows Person 2's reviewed results.
Declare notebook execution tooling in the future PR. Do not import absent
statistics modules, add placeholders or automatically restore PR #11 enhancements.

### 6. Following development stage

- [ ] Fleet/demand experiments and random-versus-nearest comparisons:
  Person 1 owns orchestration/integration; Person 2 owns statistical analysis.
- [ ] Factor analysis: Person 2, with Person 1's configuration support.
- [ ] Statistical notebook integration: Person 3, after Person 2's results.
- [ ] Final report: Person 1 coordinates; Person 2 supplies methods/analysis;
  Person 3 supplies figures/notebook content.
- [ ] Final presentation: Person 3 leads; all contribute.
- [ ] Final integration/submission verification: Person 1 leads; all review.

### 7. Final submission requirements

- [ ] Complete separately reviewed team PRs; verify tests, dependencies, CI,
  notebook reproducibility and visualization for the integrated version.
- [ ] Complete report, notebook/results and presentation by **December 16, 2026**,
  checking instructor format/rubric and submission contents.

Create fresh branches from up-to-date main; scope each teammate PR to assigned
tasks. This documentation PR implements no pending work and must not be merged
automatically.

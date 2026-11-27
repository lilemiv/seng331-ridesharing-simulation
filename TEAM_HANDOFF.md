# Weeks 1–3 Team Handoff

This is the current integration contract. The engine and its distributions are
preserved; replications and experiments call the existing simulation/metrics APIs.
See [README](README.md) for setup and commands and the [audit](docs/WEEKS1_3_AUDIT.md)
for original/final statuses. Final submission deadline supplied: December 16, 2026.

## 1. Setup and ownership

Python 3.11+; verified with Python 3.14.7, SimPy 4.1.2, Matplotlib 3.11.2 and
SciPy 1.18.1. Install `requirements.txt`; for notebook execution install
`requirements-notebook.txt`. Full unittest discovery has 268 tests. Notebook
execution and real-window smoke testing are separate checks, never silently skipped.
Temporary verification dependencies and Tcl/Tk libraries live only under ignored tmp.

| Owner | Integrated deliverables |
|---|---|
| Person 1 | Engine, configuration/presets, CSV, CI, stress, driver IDs/coordinates/dispatch, optional pickup, integration |
| Person 2 | Existing metrics, replication runner, Student-t intervals, beta estimator, paired factor/policy experiments |
| Person 3 | Event Graph, schematic replay and controls, Q/B plots, executable analysis notebook |
| Group | Integration, experimental interpretation, documentation; later final report and presentation |

## 2. Configuration

Create a new frozen `SimulationConfig` and simulation per run. Times are minutes.

| Parameter | Default | Contract |
|---|---|---|
| `mean_interarrival_minutes` | 0.75 | Positive finite exponential mean |
| `duration_minutes` | 60 | Positive finite exclusive horizon |
| `random_seed` | 42 | Integer, bool rejected; normalized by abs before stream offsets |
| `fleet_size` | 20 | Positive integer; FIFO Resource capacity and named fleet size |
| `mean_patience_minutes` | 5 | Exponential mean constrained to [3,8]; samples are unbounded |
| `pickup_min_minutes`, `pickup_max_minutes` | 2, 8 | Positive ordered finite uniform bounds |
| `trip_mean_minutes`, `trip_sigma` | 10, 0.5 | Positive arithmetic mean; nonnegative finite log-scale sigma |
| `city_width`, `city_height` | 10, 10 | Positive finite abstract planar bounds |
| `dispatch_policy` | random | random or nearest |
| `pickup_mode` | uniform | uniform or distance_aware |
| `pickup_speed_units_per_minute` | 1 | Positive finite coordinate units/minute |
| `pickup_base_delay_minutes` | 1 | Nonnegative finite overhead |

`trip_mu = log(trip_mean_minutes) - trip_sigma**2/2`. Trip samples are
exp(Normal(mu,sigma²)); sigma zero is the deterministic limit. Uniform bounds may
be equal. Distance-aware pickup is overhead + distance/speed, may be zero, and
does not consume pickup RNG draws. Unrepresentable samples abort; discard failed runs.

`scenarios.get_scenario(name, **overrides)` supports baseline, low_demand (1.5),
high_demand (0.25), small_fleet (5), large_fleet (40). Only the indicated setting
changes; explicit overrides take precedence. The engine's default horizon is 60;
the experiment explicitly requests 240.

## 3. Stable engine interface

```python
from config import SimulationConfig
from simulation import RideSharingSimulation
sim = RideSharingSimulation(SimulationConfig())
sim.run()
requests, history = sim.requests, sim.event_history
fifo_customers = sim.waiting_requests
initial, current = sim.initial_drivers, sim.drivers
driver_events = sim.driver_history
sim.validate_invariants()
```

Run once per instance. Successful `run()` checks invariants automatically.
`requests` is the full ID-ordered arrival ledger, including abandoned and censored
requests. Treat mutable engine-owned lists/records as read-only. Driver snapshots
and events are frozen. `waiting_requests` gives actual FIFO membership;
`driver_pool.queue` instead holds SimPy resource requests. `busy_driver_count`
counts occupied capacity. Resource grants and customer callbacks can be separate
internal events at one clock time; inspect a settled boundary for ledger equality.

## 4. Lifecycle and request records

`waiting → in_service (pickup → trip) → completed`, or `waiting → abandoned`.
Pre-assignment expiry wins exact ties; assigned customers cannot abandon.
The driver is reserved atomically after a valid Resource grant, remains busy for
pickup and trip, then moves to the destination and releases capacity. No extra
driver Store or second customer queue is used. See [Event Graph](EVENT_GRAPH.md).

| Field/property | Meaning |
|---|---|
| `request_id`, `arrival_time`, `patience_time` | Sequential ID starting at 1, arrival, once-sampled allowance |
| `service_start_time`, `driver_assignment_time` | Assignment; second is a read-only alias |
| `pickup_start_time` | Equals assignment |
| `pickup_completion_time`, `trip_start_time` | Pickup end equals trip start |
| `completion_time`, `trip_completion_time` | Trip end; second is a read-only alias |
| `abandonment_time` | Pre-assignment departure |
| `pickup_duration`, `trip_duration` | Available only when respective stage starts |
| `status` | waiting, in_service, completed, abandoned |
| `service_stage` | Current pickup/trip, otherwise None |
| `assigned_driver_id` | Named ownership, None before assignment |
| `pickup_x`, `pickup_y`, `destination_x`, `destination_y` | Arrival-sampled customer positions |
| `assignment_distance` | Read-only Euclidean distance recorded at assignment; None if unassigned |

`None` means an event has not occurred; zero is a valid time. Sampled duration does
not imply completion. The distance is intentionally outside dataclass fields;
`asdict(request)` does not include it or the alias/stage properties. Read these
explicitly. At T, unfinished customers retain missing future timestamps and
occupied service; events exactly at T do not execute. The engine does not drain.

## 5. Histories, export and time ordering

Customer `SimulationEvent` schema (unchanged, CSV order):

`sequence,time,event_type,request_id,request_status,service_stage,arrivals,waiting,in_system,busy_drivers,completed,abandoned`

Sequence is a zero-based total order, time is minutes, and statuses/stages are
post-event snapshots. Boundary markers have no request ID/status/stage. Event
types: simulation_start, arrival, driver_assignment, abandonment,
pickup_completion, trip_completion, simulation_end. Every row obeys:

`arrivals = waiting + busy_drivers + completed + abandoned`, `N = Q + B`.

Start is at zero, end at T with final counts; the end marker does not process
excluded lifecycle events. An immediate arrival has a waiting row followed by
assignment at the same time. Preserve sequence among equal timestamps; the last
state holds until the next distinct time. Intermediate same-time states contribute
zero duration. Abandoned customers have arrival/abandonment only; expired patience
timers after assignment add no customer events.

Driver `DriverEvent` fields are sequence, time, event_type, driver_id, request_id,
x, y. Assignment/release history is separate; join with customer records by
request ID/time. Driver positions update on trip completion, not continuously.
Driver IDs and coordinates intentionally do not alter the customer CSV schema.

`export_event_history(history, path)` writes UTF-8, full precision, input order,
and blank cells for None. Existing output is overwritten; parent must exist.
An empty history produces a header only. Normal CLI runs produce no CSV.

## 6. Metrics, populations and independent checks

All existing metric calculations remain in `metrics.py`:

| Quantity | Population / denominator |
|---|---|
| Queue delay | Assignment − arrival; all assigned, including censored service |
| Completed system time | Completion − arrival; completed only |
| Mean Q/N | Post-event state integrals divided by T |
| Utilization | B integral / (fleet_size × T), pickup plus trip |
| Abandonment | Abandoned / all arrivals, including unfinished |
| Mean assignment distance | New runner aggregation of recorded distances; assigned only |

Customer means expose mean/count; no observations is 0/count 0. Abandoned
residence is a different population, not mixed with completed system time.
Vehicle-arrival wait includes pickup; queue delay does not. Rates are fractions;
only display and the legacy `abandonment_rate_percent` key use percentages.

Time integration sorts `(time, sequence)`, starts from zero, includes exposure
through T, clips later rows, and handles zero windows. Request means use the
ledger at the observation horizon; they do not reconstruct earlier outcomes from
later final states. Use timestamps rather than final status to reconstruct history.

Independent exact example: T=10, Q=0 until 2, Q=3 until 5, Q=1 until 10; B=0 until
2, B=1 until 5, B=2 until 10. Areas Q=14, B=13, N=27; mean Q=1.4, N=2.7, two-driver
utilization=.65. A controlled actual run (arrivals 0/1/2/11, patience
100/2/100/100, one driver, pickup 2, trip 8, T=13) gives assigned queue delay 4
(n=2), completed system time 10 (n=1), Q=12/13, N=25/13, utilization 1,
abandonment 1/4. Existing tests and the notebook independently sum customer
interval exposure to cross-check history integrals.

## 7. Instructions for the animation and notebook developer

Pass `sim.event_history` through `normalize_events` for direct replay; `load_csv`
parses the export. `ReplayState.apply` validates lifecycle and counts.
`CityViewer(root, events)` requires Tkinter/ttk, working Tcl/Tk and a real display.
It displays waiting/pickup/trip/completed/abandoned, counts and event details;
Play/Pause, Restart and speed controls are tested. Positions and transitions are
schematic, not actual driver trajectories. Crowded areas show overflow counts.
Full start/end markers are required; header-only CSV cannot replay.

Headless replay tests need importable tkinter but never call `tk.Tk()`. A missing
init.tcl is an environmental installation problem. Real GUI testing passed with
temporary matching CPython Tcl/Tk libraries. `verify_gui.py` opens and renders all
four mode/policy combinations both directly and via CSV, exercises controls, then
closes every window. Pending transition callbacks are cancelled on redraw,
pause, restart and close, preventing Tcl errors after widget destruction.

`simulation_plots.plot_q_b(history)` returns a Matplotlib Figure using post-event
steps sorted by time/sequence; it accepts generators and preserves input data.
Set MPLBACKEND=Agg on headless runners. Notebook execution:

```powershell
python -m pip install -r requirements-notebook.txt
python verify_notebook.py --output tmp/executed_analysis.ipynb
```

The verifier uses the invoking Python in a fresh kernel, temporary Jupyter/IPython/
Matplotlib directories, and shuts down the kernel. It needs local loopback sockets.
The notebook preserves the working baseline code and adds model/SimPy explanations,
embedded graph, exposure validation, replication/CI/beta, all experimental outcomes,
paired contrasts, conclusions and limitations. All 10 substantive code cells execute.

## 8. Dispatch and pickup integration

Implemented and merged through PR #7 (dispatch) and #10 (optional pickup);
cleanup PR #9 is also in current main. No overlap PR remains open at preparation.
Nearest minimizes distance among its current idle candidates, with ID tie-breaking;
Random samples available IDs in stable order using a separate RNG. Customer FIFO,
capacity, expiry ties, ownership and destination updates remain enforced.
Full contract: [DISPATCH_DESIGN.md](DISPATCH_DESIGN.md).

Uniform mode has identical matched timing across policies: independent pickup/trip
draws never use distance. Distance-aware mode can change release times and later
candidate sets. Nearest does not optimize the full future run. Customer means can
also change through selection of who gets served. The trip distribution stays
route-independent. Compare modes separately and use replicated paired outputs.

## 9. RNGs and replication APIs

Offsets 0…7: arrivals, patience, pickup, trip, driver_location, pickup_location,
destination, dispatch. Local RNGs leave global random state unchanged.
The base is abs(config.random_seed), normalized before offsets. Initial driver
positions consume their stream during construction. Trip draws occur at trip
start, so distance-aware policies can assign the same stream draws to different
requests. Matched bundles do not guarantee identical per-request trip draws.

`seed_bundle(master_seed, replication_id)` reserves base abs(master_seed)+8*i.
`run_replications(config, count, master_seed=..., start_index=..., scenario=...)`
returns `ReplicationResult` rows containing config, IDs, master seed, eight stream
seeds, counts and seven metric values. Continue IDs to extend a batch. Different
master seeds can overlap; allocate disjoint IDs under one master for independent
batches. Experimental cells intentionally share bundles for paired differences.

Core empty means become None in replication inference, and zero-arrival
abandonment is None. Time averages remain zero for empty runs. Summaries report
nonmissing n and missing; run-level means have equal weight, not customer weights.
Inference with missing values describes the conditional population where defined.
`export_replications` supports full JSON and flat CSV; empty CSV is rejected.

## 10. Inference and experiment handoff

`confidence_interval(values, confidence=.95)` returns mean, sample SD (n−1), SE,
bounds and half-width. None is counted/excluded; nonfinite values are rejected.
n<2 leaves interval/SD/SE undefined; zero variance gives a point interval.
No internal rounding or physical-bound clipping is performed.

`estimate_replications(pilot, beta, confidence=.95, max_replications=1000000)`
interprets beta as an absolute half-width (assumption, instructor wording unavailable).
It records pilot size/missing count, sample variance and minimal total n meeting
t(n−1)*s_pilot/sqrt(n) ≤ beta, or the cap with target_reachable=False. It neither
reruns the engine nor guarantees realized precision. A zero-variance pilot is
not proof of no uncertainty. See [methodology](docs/STATISTICAL_ANALYSIS.md).

`default_design` defines five baseline/contrasting settings crossed with policies
and modes. `run_experiment` calls the runner and existing metric APIs.
`paired_comparison` validates IDs and seeds, computes alternative minus reference
per run, then applies a t interval to differences. Missing pairs are excluded
jointly. Factor contrasts change exactly one nominated setting.
`assert_report_matches` checks committed outputs with strict metadata and float
tolerance for platform math. `experiments.py --help` documents the CLI.

## 11. Verification, CI and remaining deliverables

Main at preparation: 35f338c (PRs #7–#10 included). Existing 217 tests were run
before changes; final 268 all pass with zero failures/errors/skips. Existing
tests were retained. CI installs notebook dependencies, runs all tests and executes
the notebook/reproduces all 400 runs on Python 3.14 Ubuntu. GUI smoke testing is
separate because hosted CI is headless. Consult PR Checks for hosted results.

Completed engine/metric behavior is preserved. The final report, presentation and
polished bonus animation are uncompleted separate submission deliverables. No
original instructor schedule or beta definition exists in the supplied repository;
the provided request's Weeks 1–3 inventory and allowed beta assumption define this
audit. Finite-run results do not establish steady state or empirical calibration.

# Project 9: Ride-Sharing Dispatch in a City Zone

SENG 331 Python/SimPy discrete-event simulation for a three-person team. Weeks
1–3 provide the engine, metrics, driver dispatch, replay, replication statistics,
experiments, plots and an executed notebook. All times are minutes. See the
[requirements](PROJECT_REQUIREMENTS.md) and [item-by-item audit](docs/WEEKS1_3_AUDIT.md).

## Install and run

Use Python 3.11+ (verified: Python 3.14.7). In PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
.\.venv\Scripts\python.exe -B -m unittest discover -v
```

On Linux/macOS, substitute `.venv/bin/python`. Dependencies are SimPy, Matplotlib
and SciPy; notebook execution additionally uses `requirements-notebook.txt`.
Unittest needs importable Tkinter but opens no windows. Full GUI testing needs
Tcl/Tk and a graphical desktop. Do not copy a teammate's virtual environment.

## Model and Event Graph

Poisson arrivals (exponential interarrival mean 0.75), exponential patience
(mean 5), FIFO access to 20 drivers, Uniform(2,8) pickup and lognormal trips
(arithmetic mean 10, log-scale sigma 0.5) define the default model. Patience applies
before assignment; expiry wins exact ties. A driver stays busy through pickup
and trip and becomes available at the destination. Events exactly at the configured
horizon are excluded; the system is not drained. Final default seed-42 counts
remain 86 arrivals = 58 completed + 20 in service + 0 waiting + 8 abandoned.

The [Event Graph](EVENT_GRAPH.md) includes initialization, independent arrivals,
FIFO/patience, atomic driver selection, both pickup modes, trip completion,
destination updates, release and the exclusive horizon. The same graph is
embedded in the notebook. The engine is independent of the GUI.

Random dispatch samples available drivers uniformly using its own RNG. Nearest
uses Euclidean distance, resolving exact ties by lowest driver ID. Neither
changes FIFO customer order. Drivers and customers have bounded planar positions.
The optional `pickup_mode="distance_aware"` uses base delay + assignment distance /
speed, with no clipping to uniform bounds. Default `"uniform"` preserves the
original distribution and RNG consumption. Trips remain lognormal in both modes.
Speed is in abstract coordinate units/minute, not a calibrated road speed. See
[dispatch](DISPATCH_DESIGN.md) and [pickup assumptions](docs/DISTANCE_AWARE_PICKUP.md).

## Public APIs and scenarios

```python
from config import SimulationConfig
from simulation import RideSharingSimulation
from scenarios import get_scenario

config = get_scenario("baseline", dispatch_policy="nearest")
simulation = RideSharingSimulation(config)
simulation.run()  # Once per instance; validates invariants automatically.
requests, history = simulation.requests, simulation.event_history
```

`get_scenario(name, **overrides)` returns a frozen validated config. Presets are
baseline, low_demand (mean interarrival 1.5), high_demand (0.25), small_fleet (5),
large_fleet (40). Unspecified parameters retain the defaults, including a
60-minute horizon and seed 42. `main.py` retains its original interface.
Full fields, request timestamps and history schemas are in [TEAM_HANDOFF.md](TEAM_HANDOFF.md).

## Metrics and observation populations

| API in metrics.py | Definition |
|---|---|
| `average_queue_delay(requests)` | Assignment − arrival over assigned customers, including unfinished service |
| `average_time_in_system(requests)` | Completion − arrival over completed trips only |
| `time_average_queue_length(history, T)` | Integral Q(t) dt / T |
| `time_average_number_in_system(history, T)` | Integral N(t) dt / T, N = Q + B |
| `driver_utilization(history, T, fleet_size)` | Integral B(t) dt / (fleet_size × T) |
| `abandonment_rate(requests)` | Abandoned / all arrivals, including unfinished arrivals |

Customer means return `SampleMean(mean, count)`; no observations means 0/count 0.
Time averages use post-event states in `(time, sequence)` order and include partial
exposure through T. Rates are fractions; the legacy
`main.calculate_simulation_metrics` still returns `abandonment_rate_percent` on
the 0–100 scale. No internal rounding occurs. Default queue delay is 0.2825 min,
completed system time 15.01 min, utilization 86.65%, abandonment 9.30%.

## Independent replications, confidence intervals and beta

```python
from replications import run_replications, summarize_replications, export_replications
from inference import estimate_replications

runs = run_replications(SimulationConfig(), 20, master_seed=2026)
summary = summarize_replications(runs)  # 95% Student-t intervals across runs.
export_replications(runs, "replications.json")  # Or .csv
plan = estimate_replications([r.metrics["abandonment_rate"] for r in runs], beta=0.05)
```

Each replication i uses base `abs(master_seed) + 8*i`, with engine stream offsets
0…7. Blocks are disjoint across IDs, including for negative master seeds. Extend
a batch with the same master seed and `start_index=previous_count`. Independent
batches must reserve disjoint indices; changing master seeds alone does not
guarantee nonoverlap. Shared bundles across experimental cells intentionally pair
their outcomes; different replication IDs supply independent pseudorandom runs.

The seven outcomes include all existing metrics plus mean assignment distance.
JSON/CSV retain replication IDs, full configurations, all eight seeds and customer
counts. Empty customer populations become `None` (JSON null/CSV blank), including
abandonment for zero arrivals. Valid empty time averages remain zero. Summaries
report usable n and missing counts; n < 2 has no interval. Sample SD uses n−1,
SE = s/sqrt(n), half-width = Student-t critical value × SE. Zero variance yields
zero half-width. One run supplies one observation; customers are never pooled.

**Beta assumption:** the original instructor definition is unavailable. Beta is
configurably interpreted as an absolute CI half-width in the outcome's units,
not as relative error or Type II error. The pilot estimator holds sample variance
fixed and finds the smallest total n ≥ pilot n satisfying the t half-width target,
updating degrees of freedom by binary search. A cap reports unreachable targets.
It plans a fixed batch; it does not guarantee achieved precision or perform
optional stopping. See [analysis methodology](docs/STATISTICAL_ANALYSIS.md).

## Reproduce the experiment and notebook

```powershell
python experiments.py --replications 20 --seed 2026 --duration 240 --output docs/results/week3_experiment.json --csv docs/results/week3_replications.csv
python -m pip install -r requirements-notebook.txt
python verify_notebook.py --output tmp/executed_analysis.ipynb
```

The design crosses five fleet/demand settings with two policies and two pickup
modes: 20 cells × 20 replications = 400 runs. Demand/fleet contrasts change one
factor from baseline; it is not a full demand-by-fleet factorial. Results and
paired 95% CIs are committed in [JSON](docs/results/week3_experiment.json) and
[CSV](docs/results/week3_replications.csv). The [notebook](ridesharing_analysis.ipynb)
reruns and checks all results; float tolerance permits platform math differences
(1e-10 relative, 1e-12 absolute), with exact IDs, counts and metadata.

Baseline 240-minute results, nearest minus random, 20 matched replications:

| Pickup model | Assignment-distance difference (95% CI) | Queue-delay difference, min (95% CI) |
|---|---|---|
| Uniform | −1.1492 [−1.2552, −1.0433] | 0 [0, 0] |
| Distance-aware | −1.2418 [−1.3650, −1.1185] | −0.1635 [−0.2009, −0.1261] |

Uniform timing results are exactly equal because assignment distance cannot alter
pickup/trip durations. Distance-aware comparisons are separate and conditional on
the illustrative speed/overhead. The small-fleet distance-aware distance contrast
includes zero; there is no universal superiority claim. Finite-run, initially empty
experiments have no warm-up or steady-state claim. CIs are pointwise without a
multiple-comparison adjustment. See the analysis document for all contrasts.

## Event export, replay and plots

```python
from event_export import export_event_history
from simulation_plots import plot_q_b
export_event_history(simulation.event_history, "events.csv")
fig = plot_q_b(iter(simulation.event_history))
fig.savefig("queue_busy.png")
```

```powershell
python city_visualization.py
python city_visualization.py --csv events.csv
python verify_gui.py
```

Event CSV retains the unchanged 12-field customer schema, precision and sequence.
Empty export is header-only and cannot be replayed. `normalize_events` and
`ReplayState` validate real lifecycle/count history. Play/Pause, Restart and speed
control replay; transition timers are cancelled on pause, redraw, restart and close.
`plot_q_b` accepts an iterable, sorts a copy by `(time, sequence)` and draws post-event
steps. The viewer uses schematic positions; it does not draw actual driver routes.

If `tk.Tk()` reports missing `init.tcl`, repair the Python distribution's Tcl/Tk
installation. This machine's default runtime has that environmental issue. Real
window/control/direct-and-CSV replay tests passed using matching official CPython
Tcl/Tk 9.0.4 libraries under ignored `tmp/` with process-local TCL_LIBRARY/TK_LIBRARY.
No installed Python files were changed. Headless tests need no Tcl initialization.

## Verification and team scope

Full discovery: **268 passed, zero failed/errors/skipped** (217 original + 51 new).
The notebook executes 10 substantive code cells top-to-bottom. GUI smoke testing
opens eight real windows (four policy/mode combinations, each direct and CSV).
CI installs notebook dependencies, runs all tests, then executes the notebook on
Python 3.14/Ubuntu with Agg plotting. See PR Checks / Actions > Python tests for
hosted status; local checks alone do not establish a hosted pass.

Person 1 owns engine/dispatch/infrastructure/integration; Person 2 owns metrics,
replications, inference and experiments; Person 3 owns Event Graph, schematic
viewer, plots and notebook. The supplied final deadline is December 16, 2026.
Final report, presentation and polished bonus animation remain uncompleted
submission deliverables. The instructor's exact beta wording and original
week-by-week schedule are unavailable; no claim of instructor confirmation is made.

# Project 9: Ride-Sharing Dispatch in a City Zone

A university Modeling and Simulation with Python project. This repository contains
the core discrete-event simulation engine, performance statistics, and a schematic
Tkinter 2D event-history viewer. All simulation times are minutes. Steps 1-5 and
Week 2 are complete, including CI, reusable configurations, optional raw event
export, bounded reliability tests, finite-run performance metrics, and the initial
visualization prototype.

Requests arrive through a Poisson process. An anonymous SimPy driver Resource
serves customers in FIFO order, subject to exponential patience before assignment.
Assigned drivers remain occupied through uniform pickup and lognormal trip stages.

## Event Graph

The code-aligned Event Graph and detailed lifecycle explanations are available in [EVENT_GRAPH.md](EVENT_GRAPH.md).

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

Arrivals continue independently of customers already waiting or in service. Each
customer samples patience on arrival and either receives a free driver immediately
when eligible or waits in FIFO order. Abandonment applies only before assignment; reaching the
patience deadline wins an exact tie with driver availability. Assigned drivers
remain occupied through pickup and trip, then become available at trip completion.
The dashed link signals released capacity for the next FIFO waiter; a completed
customer leaves the system and never returns to the queue or abandons. The times
shown are configurable defaults, measured in minutes.

## Install and run (PowerShell)

Use Python 3.10 or newer. The checked environment is Python 3.14.7 and SimPy 4.1.2.
Run these commands from the project directory; activating the environment is optional.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
.\.venv\Scripts\python.exe -B -m unittest discover -v
```

On macOS/Linux, use `.venv/bin/python` in place of the Windows executable path.
SimPy (`simpy>=4.1,<5` in `requirements.txt`) is the only pip dependency. Tests
use `unittest`; full discovery also imports Tkinter for the replay-state tests,
but does not open a GUI. See the visualization section for Tcl/Tk requirements.

## Continuous integration

`.github/workflows/python-tests.yml` runs unittest discovery on Python 3.14 for
Pull Requests targeting `main` and pushes to `main`. It installs `requirements.txt`
on a fresh Ubuntu runner. Test failures fail the job; no external keys or secrets
are required, and the workflow has only `contents: read` permission.

Open a Pull Request's **Checks** tab to see **Python tests / unittest**, or open
the repository's **Actions** tab and select **Python tests**. Expand the install
and test steps to inspect logs. A local passing run does not establish that a
GitHub-hosted run has passed. Run the same tests locally with:

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -v
```

See the official [workflow syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax)
and [Python setup action](https://github.com/actions/setup-python/tree/v6) for the
workflow format and runner setup. Repository owners must enable Actions if it has
been disabled; this change does not alter repository settings or branch protection.

## Use the engine

```python
from config import SimulationConfig
from simulation import RideSharingSimulation

simulation = RideSharingSimulation(SimulationConfig(fleet_size=20, random_seed=42))
simulation.run()  # Runs once to the exclusive configured horizon and validates results.
requests = simulation.requests
history = simulation.event_history
waiting_customers = simulation.waiting_requests
busy_drivers = simulation.busy_driver_count
```

Configuration is a frozen dataclass. Create a new configuration and simulation to
change settings or repeat a run. Each simulation owns its RNG streams; global
Python random state is unchanged. Full parameter and result definitions are in
[TEAM_HANDOFF.md](TEAM_HANDOFF.md).

## Reusable configurations

Reusable configurations are available through `scenarios.get_scenario(name,
**overrides)`. They return fresh, validated `SimulationConfig` objects without
running simulations. Explicit overrides take precedence; all other settings
(including seed 42 and the 60-minute horizon) retain the existing defaults.

| Preset | Difference from baseline |
| --- | --- |
| `baseline` | No changes: interarrival mean 0.75 minutes, fleet 20 |
| `low_demand` | Interarrival mean 1.5 minutes |
| `high_demand` | Interarrival mean 0.25 minutes |
| `small_fleet` | Fleet size 5 |
| `large_fleet` | Fleet size 40 |

These are illustrative configurations, not experimental results or calibrated
recommendations. Demand and fleet changes are separate; combine them explicitly
when needed. `main.py` continues to use the unchanged default configuration.

```python
from scenarios import get_scenario
from simulation import RideSharingSimulation

simulation = RideSharingSimulation(get_scenario("high_demand", random_seed=42))
simulation.run()
```

## Optional CSV export

```python
from event_export import export_event_history

export_event_history(simulation.event_history, "events.csv")
```

Normal runs create no CSV. The explicit exporter writes UTF-8 with a header and
all actual `SimulationEvent` fields: `sequence`, `time`, `event_type`, `request_id`,
`request_status`, `service_stage`, `arrivals`, `waiting` (Q), `in_system` (N),
`busy_drivers` (B), `completed`, and `abandoned`. Time is in minutes; missing
values are empty cells. Rows retain input order, including equal timestamps;
values are not rounded. Empty histories produce a header only. Choose any output
path whose parent already exists; an existing file is overwritten. Reopen using
`csv.DictReader`. Full field definitions are in [TEAM_HANDOFF.md](TEAM_HANDOFF.md).

## Tkinter 2D city visualization

From the repository directory, run either command with the configured Python:

```powershell
python city_visualization.py
python city_visualization.py --csv events.csv
```

For the project virtual environment, replace `python` with
`.\.venv\Scripts\python.exe` (Windows) or `.venv/bin/python` (macOS/Linux).
The first command runs `RideSharingSimulation(SimulationConfig())` once and then
replays its `event_history`. The second loads an existing CSV created by
`export_event_history`, as shown above, without running a new simulation.
`main.py` runs the console simulation and statistics; it does not launch the viewer.

`CityViewer` displays customers in waiting, pickup, trip, completed, and abandoned
areas, with event details, simulation time, and aggregate counts. Play/Pause,
Restart, and a speed slider control replay. `normalize_events()` accepts engine
events or CSV dictionaries and returns ordered `ReplayEvent` records;
`ReplayState.apply()` reconstructs customer stages from lifecycle transitions
and checks them against the recorded counts. Same-time events retain sequence
order and are drawn together. Full replay requires start/end boundary events;
a header-only CSV cannot be replayed. See [TEAM_HANDOFF.md](TEAM_HANDOFF.md#7-instructions-for-the-animation-and-notebook-developer)
for interfaces and a direct Python example.

The viewer requires Python's `tkinter`/`ttk` modules, the Tcl/Tk runtime, and an
accessible graphical desktop. If Tkinter is absent, install your Python
distribution's Tcl/Tk support; it is not provided by `requirements.txt` or a pip
package. A headless runner can execute replay-state tests if Tkinter is importable,
but cannot open `tk.Tk()` without a display. The console engine and CSV export
can run without opening a window.

Importing Tkinter alone does not verify its runtime installation: `tk.Tk()` can
still fail if Tcl/Tk files such as `init.tcl` are missing. Restore the Python
distribution's Tcl/Tk support before launching the viewer in that case.

This is a **schematic 2D prototype**, not a complete geographic driver movement
simulation or the final polished bonus animation. Roads, buildings, and customer
positions are illustrative. Customers change areas at recorded events; there are
no individual driver IDs, actual coordinates, routes, continuous movement, or
random/nearest-driver selection. Crowded areas show overflow counts. The viewer
does not provide Q(t)/B(t) plots or notebook analysis.

## Performance statistics (`metrics.py`)

`metrics.py` reads the existing request ledger and event history after a successful
`run()`. Calculations retain full precision; only console output is formatted.
All customer times and integration timestamps are minutes.

| Function | Definition and denominator |
| --- | --- |
| `average_queue_delay(requests)` | Mean assignment minus arrival over assigned customers, including unfinished pickup/trip; excludes abandoned and still waiting |
| `average_time_in_system(requests)` | Mean completion minus arrival over completed trips only; excludes abandoned and all unfinished outcomes |
| `time_average_queue_length(history, T)` | Integral of post-event `waiting` Q(t), divided by T |
| `time_average_number_in_system(history, T)` | Integral of `in_system` N(t), divided by T; N includes waiting, pickup, and trip |
| `driver_utilization(history, T, fleet_size)` | Integral of `busy_drivers` B(t), divided by fleet_size * T; pickup and trip both occupy drivers |
| `abandonment_rate(requests)` | Abandoned / all arrivals, including completed, assigned, and waiting arrivals |

The customer averages return an immutable `SampleMean` with `.mean` and `.count`;
the count is the actual denominator. No observations returns `(mean=0.0, count=0)`.
Abandoned residence time means abandonment minus arrival; it is a separate
population and is not included in either customer average. Unfinished requests
are censored, not zero-duration completions. No abandonment residence mean is
provided in this version.

Time integration sorts a copy by `(time, sequence)` and sums state times elapsed
duration. Initial Q/N/B are zero from time 0 to the first event, and the final
state persists to T. Same-time intervals have zero area; the last sequence at a
timestamp supplies the next interval's state. This is not an arithmetic mean of
event rows. Unfinished waiting and service contribute exposure until T; history
beyond T is clipped. Events exactly at T contribute no duration. Empty histories
and T=0 return 0.0. Invalid negative/nonfinite horizons or timestamps, invalid
in-window states, and invalid fleet capacity raise `ValueError`; T=0 returns
without scanning history. The engine itself still requires a positive horizon.

```python
from metrics import (
    average_queue_delay, average_time_in_system, time_average_queue_length,
    time_average_number_in_system, driver_utilization, abandonment_rate,
)

# Use the simulation created and run in "Use the engine" above.
delay = average_queue_delay(simulation.requests)
system_time = average_time_in_system(simulation.requests)
T = simulation.env.now
q_average = time_average_queue_length(simulation.event_history, T)
n_average = time_average_number_in_system(simulation.event_history, T)
utilization = driver_utilization(simulation.event_history, T, simulation.config.fleet_size)
abandonment = abandonment_rate(simulation.requests)
print(delay.mean, delay.count, system_time.mean, system_time.count)
print(f"Utilization: {utilization:.2%}; abandonment: {abandonment:.2%}")
```

Utilization and abandonment are fractions in [0, 1]; 0.65 displays as 65.00%.
The Week 1 `from main import calculate_simulation_metrics` API remains available,
with the same `average_waiting_time` and `abandonment_rate_percent` keys. Its
implementation now lives in `metrics.py`; the legacy rate key remains a percentage.
Records and RNG streams are never changed by metrics.

Default seed-42 metric output from `python main.py`:

```text
Average Queue Delay (assigned customers, n=78): 0.28 minutes
Average Time in System (completed customers, n=58): 15.01 minutes
Time-average Queue Length: 0.462
Time-average Number in System: 17.792
Driver Utilization: 86.65%
Abandonment Rate: 9.30%
```

These are descriptive results for a finite 60-minute run. Week 3 replications,
warm-up selection, confidence intervals, beta analysis, and statistical
experiments remain future work. No steady-state or uncertainty claim is made.

## Files and verification

- `config.py`: validated parameters and the arithmetic-mean lognormal conversion.
- `scenarios.py`: five reusable presets and explicit validated overrides.
- `simulation.py`: arrival/customer processes, resources, records, immutable event
  snapshots, and automatic end-of-run invariant checks.
- `event_export.py`: opt-in serialization of raw event history, with no metrics.
- `metrics.py`: modular, unrounded customer means/counts, time averages, and rates.
- `main.py`: the command-line run and formatted statistics from `metrics.py`.
- `city_visualization.py`: Tkinter `CityViewer`, event normalization, CSV loading,
  and validated replay state; schematic display only.
- `test_simulation.py`: 70 core simulation tests.
- `test_scenarios.py`, `test_event_export.py`, `test_stress_simulation.py`: 21
  additional tests.
- `test_main.py`: 3 Week 1 queue-delay regressions.
- `test_city_visualization.py`: 5 replay-state, ordering, CSV, and validation tests;
  no GUI window is opened.
- `test_metrics.py`: 35 metric tests, including independent timestamp exposure
  checks, deterministic integrals, censoring, precision, reproducibility, and CLI.
  Unittest discovery covers 134 tests in total.
- `.github/workflows/python-tests.yml`: CI on PRs and main pushes.
- [PROJECT_REQUIREMENTS.md](PROJECT_REQUIREMENTS.md): scope and completion checklist.
- [TEAM_HANDOFF.md](TEAM_HANDOFF.md): integration contract, measurement definitions,
  consumer guidance, limitations, and proposed dispatch extension.

Default seed-42 output: 86 arrivals, 58 completed, 20 in service, 0 waiting, and 8
abandoned after 60 minutes. The engine validates conservation, lifecycle timing,
FIFO membership, driver ownership/capacity, and history consistency on each
successful `run()`. Invalid results raise `RuntimeError`; failed runs must be
discarded.

## Team scope

Person 1 owns core reliability, validation, configuration infrastructure, raw data
export, CI, and integration support.

Person 2's Week 2 metrics and tests are implemented. Further statistical analysis,
replications, confidence intervals, and experiments remain with Person 2.
Person 3 has delivered the corrected Event Graph and initial Tkinter 2D prototype
with event-history and CSV integration. Further animation improvements, Q(t)/B(t)
plots, the final Jupyter Notebook, and presentation remain future work. The group
owns the final report and coordination of the experimental factor analysis and
random-versus-nearest dispatch comparison, which still needs a driver/location
model. See [PROJECT_REQUIREMENTS.md](PROJECT_REQUIREMENTS.md) for the checklist.

Resource slots remain anonymous: there are no driver IDs, coordinates, routes,
or dispatch policies. The existing viewer provides schematic replay; location-based
animation needs a future agreed model, proposed in handoff section 8. No such
extension is implemented. History grows with events, so stress tests are bounded
(the longest horizon is 1440 simulated minutes). CSV exports contain raw data only.

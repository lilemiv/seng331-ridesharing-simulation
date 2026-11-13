# Project 9: Ride-Sharing Dispatch in a City Zone

A university Modeling and Simulation with Python project. This repository contains
the Weeks 1-2 core discrete-event simulation engine and its team integration data.
All simulation times are minutes. The core handoff ends at Step 5.

Requests arrive through a Poisson process. An anonymous SimPy driver Resource
serves customers in FIFO order, subject to exponential patience before assignment.
Assigned drivers remain occupied through uniform pickup and lognormal trip stages.

## Install and run (PowerShell)

Use Python 3.10 or newer. The checked environment is Python 3.14.7 and SimPy 4.1.2.
Run these commands from the project directory; activating the environment is optional.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
.\.venv\Scripts\python.exe -m unittest -v
```

On macOS/Linux, use `.venv/bin/python` in place of the Windows executable path.
SimPy is the only external dependency; tests use the standard library.

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

## Files and verification

- `config.py`: validated parameters and the arithmetic-mean lognormal conversion.
- `simulation.py`: arrival/customer processes, resources, records, immutable event
  snapshots, and automatic end-of-run invariant checks.
- `main.py`: one command-line run and a basic lifecycle summary.
- `test_simulation.py`: 70 automated tests, including the original 50 regressions.
- [PROJECT_REQUIREMENTS.md](PROJECT_REQUIREMENTS.md): scope and completion checklist.
- [TEAM_HANDOFF.md](TEAM_HANDOFF.md): integration contract, measurement definitions,
  consumer guidance, limitations, and proposed dispatch extension.

Default seed-42 output: 86 arrivals, 58 completed, 20 in service, 0 waiting, and 8
abandoned after 60 minutes. The engine validates conservation, lifecycle timing,
FIFO membership, driver ownership/capacity, and history consistency on each
successful `run()`. Invalid results raise `RuntimeError`; failed runs must be
discarded.

## Team scope

Statistics, plots, experimental replications, confidence intervals, beta analysis,
notebooks, 2D animation, final Event Graph documentation, report, and presentation
belong to the other team members. None are implemented here. Random-versus-nearest
driver selection remains an instructor-required future group extension; this
handoff documents its design without implementing policies or replacing Resource.

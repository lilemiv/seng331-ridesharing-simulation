# Week 3 driver dispatch

This document describes Person 1's implemented driver/location/dispatch contract,
merged in PR #7. It supplements [README.md](README.md),
[TEAM_HANDOFF.md](TEAM_HANDOFF.md), and [PROJECT_REQUIREMENTS.md](PROJECT_REQUIREMENTS.md).
The implementation chronology below records the original dispatch delivery;
current full-suite counts and integrated statistics/experiments/plots/notebook
verification are in [the Weeks 1–3 audit](docs/WEEKS1_3_AUDIT.md).

## Architecture

Keep the existing `simpy.Resource` as the single FIFO customer capacity gate.
Its request/timeout race and explicit strictly-before-deadline check preserve
cancellation and abandonment, including exact ties. A Store of drivers would
require a new queue/cancellation protocol and could alter simultaneous events;
there is no need to replace the proven Resource interface.

After a customer obtains a valid slot, select and reserve one idle Driver without
yielding. Driver assignment records are authoritative for named availability;
idle/busy views are derived, with no separate available-driver Store or queue.
The Resource gates capacity rather than selecting identities. At settled event
boundaries, each held slot must correspond to exactly one assigned driver and
one in-service request. Internal Resource grant/callback events can temporarily
precede the logical assignment, as they already do for request timestamps.

On trip completion, update the driver's location, clear its assignment, then
release the Resource slot without yielding. FIFO waiters may acquire that slot
immediately at the same simulated time. Never select a customer by location.
Failed service must clean up its named reservation as well as its Resource slot;
failed runs remain invalid and must be discarded.

## Compatibility boundary

Preserve the request lifecycle/timestamps, `requests`, `event_history`, Resource
`queue`/`users`/`count`, `waiting_requests`, and `validate_invariants()`.
Keep all 12 `SimulationEvent` fields and all existing event types unchanged:
the CSV exporter derives its header from this dataclass and the viewer rejects
unknown types. Expose driver assignment/release snapshots in a separate
`driver_history` instead. This avoids changes to Person 2/Person 3 modules.

## Driver and position model

[dispatch.py](dispatch.py) defines frozen `Driver(driver_id, x, y,
assigned_request_id=None)` snapshots. IDs are integers `1..fleet_size`.
`is_available` is derived from `assigned_request_id is None`; no independent
availability flag can drift out of sync. The simulation replaces its private
records atomically. Public tuple views contain immutable snapshots: reacquire
the view after events to see updated state.

`SimulationConfig.city_width` and `.city_height` default to `10.0`; each must be
a positive finite Python int/float (booleans are rejected). The rectangular city
is `[0, city_width] x [0, city_height]`, with inclusive bounds. Coordinates are
abstract planar kilometres, with no real-world map calibration or street network.
Initial drivers, customer pickups, and destinations are sampled independently
and uniformly inside that rectangle. Every arrival receives both coordinates,
including customers who later abandon or remain waiting.

The old four RNG streams remain `abs(random_seed) + 0/1/2/3` for arrivals,
patience, pickup duration, and trip duration. New streams use offsets `4` for
initial drivers, `5` for customer pickups, `6` for destinations, and `7` for Random
dispatch. Location draws never consume arrival, patience, or service randomness.
Changing fleet size does not shift customer location streams. Equal configurations
and seeds reproduce the complete state and both histories.

A driver's `x/y` are its **last known location**, initially its sampled position,
then its most recently completed destination. They stay at that prior location
during pickup/trip: they are not an interpolated current vehicle position.
Trip completion moves the driver to the customer's destination before releasing
its slot. Unfinished trips at the exclusive horizon do not move to an unobserved
destination or emit a release. Failure cleanup clears a named reservation without
inventing a successful trip/release event; discard the failed run.

## Policy configuration and execution

`SimulationConfig.dispatch_policy` accepts exactly `"random"` (the default) or
`"nearest"`; other values raise `ValueError`. Presets accept both policy and city
overrides through the existing `get_scenario(name, **overrides)` interface.

- Random calls `select_random_driver(drivers, rng)`, which filters idle drivers,
  sorts them by driver ID, and uses the dedicated RNG's `choice` for uniform
  selection. It never draws from the global RNG.
- Nearest calls `select_nearest_driver(drivers, pickup_x, pickup_y)`, minimizing
  `sqrt((driver.x - pickup_x)^2 + (driver.y - pickup_y)^2)` over idle drivers.
  `math.hypot` computes the distance; an overflow fallback rescales all candidates
  by a common factor. Exact distance ties use the lowest driver ID, independently
  of input order. Nearest does not consume the Random dispatch stream.
- These functions only select an identity and raise `ValueError` if no driver is
  available. The engine reserves the result after the existing FIFO gate; a
  policy never chooses/reorders customers or bypasses patience.
- Patience expiry wins exact deadline ties, including a slot granted at that
  instant. Such customers never reserve a named driver or emit an assignment.

From the repository directory, execute this Python example using the project's
environment (`.\.venv\Scripts\python.exe` on Windows, `.venv/bin/python` on
macOS/Linux):

```python
from config import SimulationConfig
from simulation import RideSharingSimulation

sim = RideSharingSimulation(SimulationConfig(dispatch_policy="nearest"))
sim.run()
sim.validate_invariants()  # Also called automatically by run().
print(sim.config.dispatch_policy, sim.config.fleet_size, sim.env.now)
print([request.assigned_driver_id for request in sim.requests[:5]])
print(sim.available_drivers)
```

Set `dispatch_policy="random"` for Random. `python main.py` still runs the default
configuration and existing console statistics; there are no new CLI arguments.
No new pip dependencies are introduced. Core execution is headless; importing
the existing viewer replay tests still requires Tkinter, but no window is opened.

## Integration interfaces

| Interface | Contract |
| --- | --- |
| `sim.drivers` | ID-ordered tuple of current frozen Driver snapshots |
| `sim.initial_drivers` | Read-only tuple of frozen initial positions; no assignments |
| `sim.available_drivers` / `sim.busy_drivers` | Derived tuples filtered by current assignment |
| `request.assigned_driver_id` | Assigned identity retained after completion; `None` for waiting/abandoned requests |
| `request.pickup_x`, `request.pickup_y` | Pickup position, populated at arrival |
| `request.destination_x`, `request.destination_y` | Destination, populated at arrival |
| `sim.driver_history` | Read-only tuple of frozen `DriverEvent` snapshots |
| `sim.config.dispatch_policy` | Selected policy for run metadata |

New request fields are appended with `None` defaults, preserving old positional
construction for metrics fixtures. Engine-generated requests always have locations.
Request records remain engine-owned mutable dataclasses; consumers must treat
them as read-only. `dataclasses.asdict(request)` now includes five additional
fields; consumers that enforce the old exact request schema must allow/project
them. Aliases and lifecycle statuses are unchanged.

`DriverEvent` has `sequence`, `time`, `event_type`, `driver_id`, `request_id`, `x`,
and `y`. Its types are `driver_assignment` (driver position before this service)
and `driver_release` (completed destination). Time is simulation minutes; sequence
starts at zero and orders equal-time records within this history. It has no
boundary markers. Sequence numbers are independent of `event_history` and cannot
be compared across histories. A release at time t precedes reassignment of that
driver at t. For playback, start with `initial_drivers`, process driver events in
their recorded order, and join customer events by request ID and timestamp.

Person 2 can continue calling the existing `metrics.py` functions with the request
ledger, `sim.event_history`, `sim.env.now`, and fleet size. Record dispatch policy
and seed from the configuration; use `assigned_driver_id` for future per-driver
analysis. No replications, uncertainty estimates, or experimental runner are added.

Person 3 can join the new driver snapshots/history to pickup/destination fields
on `sim.requests`. Continue feeding **only `sim.event_history`** to
`normalize_events()` / `ReplayState.apply()`. The existing viewer remains a
schematic customer-stage replay and does not consume driver/location data.
No viewer changes are needed for compatibility, and geographic movement must
not be inferred from last-known positions. `export_event_history` still exports
the same 12 customer event fields; driver history is accessible in Python and
is not included in that CSV. No new exporter or animation is implemented.

## Guarantees and limitations

`validate_invariants()` retains the existing checks and now also verifies fleet
identity/capacity, bounded positions, one driver per active customer, agreement
with Resource holders, request assignment IDs, driver history chronology,
assignment/release matching, and final positions reconstructed from history.
Call it at a settled boundary, not between internal Resource grants and callbacks.
Both histories grow with events; driver views are copied on access.

Uniform pickup durations (default 2-8 minutes) and lognormal trip durations
(arithmetic mean 10 minutes, sigma 0.5) remain independent of distance. Positions
change discretely at completed trips. Consequently, policies change **who** serves
customers but do not change service timing or aggregate performance in this model.
This is not evidence that policies have equal performance in a geographic model;
distance-dependent travel times would require a separate agreed model change.
No roads, speeds, physical movement, routing, rebalancing, or animation are added.
Customers remain FIFO regardless of distance; unfinished service remains busy at
the horizon. There is no policy switch during a run.

## Verification

The baseline at `origin/main` commit `8740086` ran 134 tests. No original tests
were modified or removed. [test_dispatch.py](test_dispatch.py) adds 48 tests for
identity, coordinates/validation, dedicated RNG streams, both selectors, ties,
FIFO/expiry/simultaneous events, capacity after every internal SimPy event,
destination updates, failure cleanup, invariant corruption detection, and
unchanged metrics/viewer/CSV integration.

Full regression results after each checkpoint (all zero failures/errors):

| Task | Full suite | Dispatch tests |
| --- | --- | --- |
| 1: Architecture | 134 | 0 |
| 2: Identity | 141 | 7 |
| 3: Coordinates | 146 | 12 |
| 4: Random | 151 | 17 |
| 5: Nearest | 157 | 23 |
| 6: Destination updates | 161 | 27 |
| 7: Core invariants | 168 | 34 |
| 8: Consumer interfaces | 172 | 38 |
| 9: Expanded regression tests and numerical hardening | 182 | 48 |
| 10: Documentation and final verification | 182 | 48 |

Run from the repository directory:

```powershell
.\.venv\Scripts\python.exe -m unittest test_dispatch -v
.\.venv\Scripts\python.exe -m unittest discover -v
.\.venv\Scripts\python.exe main.py
```

Verified with Python 3.14.7 and SimPy 4.1.2. A direct run against the original
engine from `8740086` matched every old request field, every customer event row,
and all four original RNG states for both policies with baseline, high-demand
(fleet 2), and small-fleet (seed -17) configurations. Both policies also reproduced
their new complete request/driver state and histories on repeated runs.

Default seed-42, 60-minute debug results:

| Policy | First five request driver IDs | Arrivals | Completed | In service | Waiting | Abandoned |
| --- | --- | --- | --- | --- | --- | --- |
| Random | 3, 13, 16, 5, 14 | 86 | 58 | 20 | 0 | 8 |
| Nearest | 3, 11, 13, 19, 5 | 86 | 58 | 20 | 0 | 8 |

Each default run has 305 customer event rows and 136 driver events (78 assignments
and 58 releases). These are reproducible debug examples, not an experimental
comparison or statistical conclusion. The old console counts and six metrics
are unchanged. Intentional interface additions are the five request fields, new
configuration fields, frozen Driver/DriverEvent views, and separate driver history.
Existing modules for metrics, visualization, CSV, scenarios, and the Event Graph
are unchanged. GUI rendering is not tested here; pure replay compatibility is.

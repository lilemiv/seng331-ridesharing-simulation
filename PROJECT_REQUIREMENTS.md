# Project 9: Ride-Sharing Dispatch in a City Zone

## Repository recovery and ownership

SENG 331, three-person team. Final deadline: **December 16, 2026**.
Verified November 27, 2026 against synchronized main
`f46ece5bd797a540a2ce1be4cace1ddb1244b85a`.

[PR #11, Genel Düzenleme](https://github.com/lilemiv/seng331-ridesharing-simulation/pull/11)
was merged and then reverted by merged
[PR #12](https://github.com/lilemiv/seng331-ridesharing-simulation/pull/12)
for team workflow reasons, to separate contributions for review.
The combined implementation was created and remains recoverable at
`c5bc0978f82134b3f7f118cfd1dcfb265dd4b234` and its original branch.
Current main's tree equals pre-PR #11 commit `35f338c` (tree `98ac3b8`).
PR #7 dispatch, PR #10 optional pickup, and Person 3's initial PR #4
viewer/Event Graph and PR #8 plots/notebook remain present.

Checked items exist and were verified. Unchecked items remain pending in current
main even where earlier implementations exist in reverted history. This
documentation change restores none of PR #11's implementation.

## 1. Week 1 completed tasks

- [x] Python/SimPy discrete-event engine, GUI-independent, with minutes throughout.
- [x] Poisson arrivals: exponential interarrival mean 0.75 minutes by default.
- [x] Configurable SimPy Resource capacity (default 20), FIFO waiting and release.
- [x] Exponential patience sampled once per arrival (default mean 5 minutes;
  configurable mean 3-8). Individual samples are not restricted to that interval.
- [x] Queued abandonment cancellation; expiry wins exact assignment ties.
- [x] Default uniform pickup (2-8 minutes), followed by lognormal trips
  (arithmetic mean 10 minutes, log-scale sigma 0.5).
- [x] Driver occupied throughout pickup/trip; no abandonment after assignment.
- [x] Request lifecycle, timestamps, sampled durations, exclusive horizon,
  deterministic duration RNG streams and original CLI/API regressions.

## 2. Week 2 completed tasks

- [x] Immutable event history, FIFO customer view and automatic lifecycle,
  conservation, capacity and history invariants.
- [x] Person 1: baseline, low/high demand and small/large fleet presets;
  optional standard-library 12-field event CSV export and bounded stress tests.
- [x] GitHub Actions: full unittest discovery, Python 3.14 Ubuntu, PRs to main
  and pushes to main, read-only contents permission.
- [x] Person 2: assigned-customer queue delay, completed-only system time,
  time-average Q/N, pooled driver utilization and abandonment fraction.
  Means expose observation counts; exposure includes censored waiting/service.
- [x] Person 3: Event Graph, initial Tkinter schematic viewer, customer stages,
  Play/Pause, Restart, speed slider and validated event-history/CSV replay.
- [x] Setup, integration contracts, metric definitions and replay documentation.

Initial Q(t)/B(t) plots (`simulation_plots.py`) and Version 1 notebook
(`ridesharing_analysis.ipynb`) were subsequently merged in PR #8 and remain
available. They are verified initial contributions, separate from the pending
Week 3 enhancements. The viewer uses illustrative positions rather than the
engine's driver coordinates. Controls exist; broader GUI regressions remain
Person 3's pending work.

## 3. Person 1 Week 3 completed tasks

- [x] Individual driver identities and initial driver coordinates.
- [x] Customer pickup/destination coordinates and isolated spatial RNG streams.
- [x] Random idle-driver dispatch (`dispatch_policy="random"`, default).
- [x] Nearest idle-driver dispatch (`"nearest"`), Euclidean distance and lowest-ID ties.
- [x] Driver location updates to destination before release, with separate
  immutable assignment/release history.
- [x] FIFO/abandonment integration, including exact deadline ties.
- [x] Dispatch tests and driver ownership/capacity invariants.
- [x] Optional `pickup_mode="distance_aware"`: overhead + assignment distance / speed.
  Default pickup mode remains `"uniform"`.
- [x] Core integration: legacy APIs, deterministic default output, customer
  event schema, CSV, metrics and schematic replay preserved.

See [DISPATCH_DESIGN.md](DISPATCH_DESIGN.md) and
[distance-aware pickup](docs/DISTANCE_AWARE_PICKUP.md).
No simulation algorithm changes are needed for this recovery.

## 4. Person 2 Week 3 pending tasks — Statistics

### Task 1: Multiple independent replications

- [ ] Independent fresh simulation instances and reproducible, disjoint seed bundles.
- [ ] Replication-level metrics, observation counts, structured results and
  configuration/seed metadata.
- [ ] Independence, seed isolation, reproducibility and collection tests.

Use `SimulationConfig`, `scenarios.get_scenario`, `RideSharingSimulation.run()`
and `metrics.py`. Eight engine seeds are `abs(random_seed) + 0..7`;
consecutive base seeds overlap. Document bundle allocation and continuation IDs
without changing the deterministic engine API. A customer mean with
`SampleMean.count == 0` is not an observed zero.

### Task 2: Confidence intervals and beta

- [ ] 95% Student's t intervals over independent replication outcomes.
- [ ] Sample variance, standard error, bounds and half-width, numerically tested.
- [ ] Beta-based replication count estimation, assumptions and tests.

Task 2 depends on Task 1's structured results. Agree the course's beta definition,
precision units and small/missing-sample behavior before implementation.
Declare any Student's t dependency in that future PR. Neither `replications.py`
nor `inference.py` exists in current main; add no placeholders or wholesale
restoration. Proposed interfaces are in [TEAM_HANDOFF.md](TEAM_HANDOFF.md#15-week-3-team-task-separation).

## 5. Person 3 Week 3 pending tasks — Visualization and Notebook

### Task 1: Jupyter Notebook development

- [ ] Extend the existing Version 1 notebook with the latest Event Graph,
  including both pickup modes, assumptions and distribution explanations.
- [ ] Explain metric populations/censoring and add executable simulation examples.
- [ ] Prepare interfaces for Person 2's future statistical results.

### Task 2: 2D visualization improvements

- [ ] Review the existing animation; verify Play/Pause, Restart and speed controls.
- [ ] Extend event-history/CSV replay verification across both dispatch policies
  and pickup modes, including GUI behavior.
- [ ] Improve visualization quality where useful and add regression tests.

Preserve the initial viewer, transition effects, plots and notebook cells.
Existing replay tests already pass across policies/modes; they do not complete
this future GUI/notebook work. Do not automatically restore PR #11 enhancements.
The customer CSV has no coordinates; spatial views must use driver/request APIs.

## 6. Following development stage — planned work

- [ ] Fleet-size/demand experiments — Person 1 orchestrates; Person 2 designs
  analysis; Person 3 presents results.
- [ ] Random versus nearest comparisons under both pickup modes — Person 1
  integrates configurations; Person 2 analyzes replication outcomes.
- [ ] Experimental factor analysis — Person 2, with Person 1's orchestration.
- [ ] Statistical results in the notebook — Person 3, after Person 2's result
  contract is available and Person 1 verifies integration.
- [ ] Final report — Person 1 coordinates documentation; Person 2 supplies
  methods/analysis; Person 3 supplies figures/notebook material.
- [ ] Final presentation — Person 3 leads, with all members contributing.
- [ ] Final integration and submission verification — Person 1 leads; all review.

Presets and single-run plots exist; replicated experiments and factor analysis
remain pending. No future-stage implementation is included here.

## 7. Final submission requirements

- [ ] Complete and review each member's scoped PRs before final integration.
- [ ] Submit the reproducible notebook, final report and presentation by
  **December 16, 2026**, checking the instructor's required format/rubric.
- [ ] Document experiment configurations, seeds, statistical assumptions,
  results and limitations; verify final code, dependencies, CI and replay.
- [ ] Verify submission contents and any agreed polished animation deliverable.

## Verification and compatibility contract

Actual discovery on the recovered baseline: **217 passed, 0 failures, 0 errors,
0 skips**. Breakdown: 70 core, 6 presets, 6 CSV, 9 stress, 3 CLI, 5 replay,
35 metrics, 48 dispatch and 35 distance-aware pickup tests.
Run `.\.venv\Scripts\python.exe -B -m unittest discover -v`.
Local results do not establish hosted CI success.

Additional recovery checks passed: direct/CSV replay, plot data/rendering and
headless controller behavior for all four policy/pickup combinations; all five
substantive initial notebook cells executed in a fresh kernel using an existing
isolated verification environment. GUI windows/rendering were not exercised.
This preserves the initial work without completing Person 3's pending enhancements.

Dependencies remain `simpy>=4.1,<5` and `matplotlib`; unittest is standard library.
Full discovery needs importable Tkinter; windows additionally need Tcl/Tk and
a desktop. Notebook execution needs a Jupyter-capable environment. No new
dependency is introduced here.

Call `run()` once on a fresh engine; treat requests, histories and driver views
as read-only. Missing timestamps remain censored. Preserve equal-time sequence
order and the exclusive horizon. `assignment_distance` is a read-only property
outside `asdict()` and the unchanged 12-field CSV. Driver coordinates are last
known locations, without route interpolation. Full APIs, metric formulas and
examples remain in [TEAM_HANDOFF.md](TEAM_HANDOFF.md) and [README.md](README.md).

# SENG 331 — Weeks 1–3 requirements

Project: Ride-Sharing Dispatch in a City Zone. This checklist follows the supplied
Weeks 1–3 request. Final deadline supplied: December 16, 2026. The original
instructor schedule and exact beta definition are unavailable; the explicitly
permitted absolute-half-width interpretation is documented, not presented as
confirmed instructor wording. See [full audit](docs/WEEKS1_3_AUDIT.md) for every
task's owner, original/final status, source and verification evidence.

## Week 1 — core simulation (Person 1; tests/documentation shared)

- [x] Python/SimPy discrete-event engine with configurable environment/horizon.
- [x] Poisson arrivals using exponential interarrival times.
- [x] Configurable fleet, FIFO waiting, driver assignment and release.
- [x] Exponential patience, pre-assignment abandonment and expiry-winning exact ties.
- [x] Default Uniform(2,8) pickup and lognormal trip durations.
- [x] Lifecycle records, stage timestamps, final statuses and immutable event history.
- [x] Request conservation and driver capacity/ownership invariants.
- [x] Reproducible local random streams without global RNG mutation.
- [x] Automated unit and regression coverage; baseline outputs retained.

## Week 2 — Person 1 infrastructure

- [x] Validated baseline, low/high demand, small/large fleet presets.
- [x] Raw event CSV export with unchanged 12-field schema, precision and ordering.
- [x] GitHub Actions PR/main CI and bounded stress tests.
- [x] Integration documentation and event-history schema contract.

## Week 2 — Person 2 performance metrics

- [x] Average queue delay: all assigned customers, including unfinished service.
- [x] Average time in system: completed trips only.
- [x] Time-average queue length and number in system.
- [x] Utilization includes pickup and trip; abandonment uses all arrivals.
- [x] Correct populations/denominators, post-event time weighting and horizon clipping.
- [x] Independent controlled numerical examples and per-request exposure checks.
- [x] Metric unit tests, precision, empty populations and legacy CLI compatibility.

## Week 2 — Person 3 Event Graph and visualization

- [x] Code-aligned Event Graph, now including optional distance-aware pickup.
- [x] Tkinter schematic 2D city visualization from actual event history.
- [x] CSV replay and lifecycle state/count validation.
- [x] Play/Pause, Restart and speed controls.
- [x] Existing replay tests retained; transition callback cleanup regressions added.
- [x] Real GUI render/control/direct-and-CSV replay tested across policies/modes.

Ordinary local GUI launch needs a complete Tcl/Tk installation. Missing init.tcl
was diagnosed as environmental; real-window tests used temporary official matching
CPython Tcl/Tk 9.0.4 libraries, without changing installed Python files.

## Week 3 — Person 1 dispatch and integration

- [x] Individual driver IDs and bounded driver/pickup/destination coordinates.
- [x] Random and nearest available-driver policies with Euclidean distance.
- [x] Deterministic lowest-driver-ID nearest ties.
- [x] Destination updates after trips and consistent resource/named-driver ownership.
- [x] FIFO, abandonment, deadline and horizon compatibility.
- [x] Dispatch tests and compatibility with metrics, CSV and schematic replay.
- [x] Optional distance-aware pickup independently verified; uniform baseline preserved.

PR #7 dispatch, #10 pickup, #9 readability and #8 plots/notebook were already
merged at preparation; their working behavior was retained.

## Week 3 — Person 2 statistical analysis

- [x] Reusable independent replication runner calling existing simulation/metric APIs.
- [x] Disjoint eight-stream seed bundles, reproducibility and continuation IDs.
- [x] All existing metrics plus mean assignment distance, full config/IDs/seeds/counts.
- [x] Explicit missing populations, structured JSON/CSV export and automated tests.
- [x] Configurable 95% Student-t means/SD/SE/bounds/half-width across replications.
- [x] Insufficient sample size and zero variance handling, unrounded calculations.
- [x] Independent numerical CI verification; no pooling of customer observations.
- [x] Pilot beta estimator under the explicitly permitted absolute-half-width assumption.
- [x] Recorded confidence, target, pilot n/missing, variance, total count and cap status.
- [x] Minimal integer count using candidate t degrees of freedom; edge/numerical tests.
- [x] Reproducible fleet/demand/policy/mode design: 20 cells × 20 runs, 240 min, seed 2026.
- [x] Paired policy and single-factor contrasts with uncertainty for all seven outcomes.
- [x] Separate uniform/distance-aware analyses; structural uniform timing equality explained.
- [x] Committed reproducible JSON/CSV results, no single-seed significance claims.

## Week 3 — Person 3 plots and notebook

- [x] Q(t)/B(t) post-event plots and ordering/generator/render tests.
- [x] Executable Jupyter Notebook preserving working baseline code.
- [x] Faithfully embedded current Event Graph and model/distribution/SimPy explanations.
- [x] Metric definitions, populations, denominators and independent exposure validation.
- [x] Replication methodology, CIs, beta planning and experimental comparisons/results.
- [x] Conclusions, model/statistical limitations and instructor-beta assumption.
- [x] All 10 substantive code cells execute top-to-bottom; CI executes them too.

## Integrated verification

- [x] Core → metrics → replications → CIs/beta/experiments.
- [x] Dispatch → paired comparisons; original baseline metrics retained.
- [x] Engine → direct replay and event CSV → replay, including real windows.
- [x] Results → notebook and Event Graph → current architecture.
- [x] Notebook uses public APIs and checks the committed 400-run report.
- [x] All original 217 tests retained; final full suite 268 passed, 0 failed/errors/skipped.
- [x] Isolated dependency environment, package consistency, diff/whitespace review.

## Separate final-submission work and unresolved source questions

- [ ] Final report and presentation.
- [ ] Final polished bonus animation beyond the verified schematic prototype.
- [ ] Confirm instructor's exact beta semantics against original assignment.
- [ ] Confirm original instructor week-by-week schedule.

These unchecked items are not represented as finished. The supplied request
explicitly allows beta implementation under a documented assumption. No original
schedule was available to establish the timing of separate final deliverables.
No steady-state study, empirical road calibration or continuous geographic routes
is claimed. Full evidence and remaining limitations are in the audit.

# Week 3 statistical analysis and experiment

## Reproduction and scope

```powershell
python experiments.py --replications 20 --seed 2026 --duration 240 --output docs/results/week3_experiment.json --csv docs/results/week3_replications.csv
python verify_notebook.py --output tmp/executed_analysis.ipynb
```

Install `requirements-notebook.txt` for the second command. The checked environment
is Python 3.14.7, SimPy 4.1.2, SciPy 1.18.1 and Matplotlib 3.11.2. Experiments
describe initially empty finite runs of 240 minutes, without warm-up or draining.
The engine and `main.py` retain their original default 60-minute run.

## Independent observations and seeds

The engine initializes eight streams with `abs(random_seed)+0…7`. Replication i
uses base `abs(master_seed)+8*i`. In the reference experiment, i=0…19, base seeds
2026, 2034, …, 2178; all stream seeds span 2026…2185 without reuse across IDs.
The base is normalized before offsets, so negative master seeds do not collapse
streams. Tests inspect all actual RNG states, including initial position draws,
and check 1,000 allocated bundles for positive, negative and zero master seeds.

The same bundles intentionally recur across cells for common-random-number paired
comparisons. Independent units are replication IDs; cells within an ID are paired,
not independent. Extend a batch with the same master and disjoint start_index.
Distinct masters by themselves do not guarantee disjoint seed ranges. Seed
separation supports reproducible pseudorandom runs; it is not a proof of
mathematical independence of RNG sequences.

Each metric contributes one equally weighted value per replication. Individual
customers across runs are not pooled as replication observations. Customer delay
means require at least one assigned/completed request as appropriate. Empty
populations and zero-arrival abandonment become None; valid empty time averages
remain zero. Every summary reports usable n and missing counts. With missing
populations the result is conditional on the statistic being defined. Reference
400-run outputs have no missing metric populations.

## Student-t intervals and numerical checks

For replication observations x₁…xₙ, use sample mean, sample variance with denominator
n−1, SE=s/√n, and mean ± t(n−1, (1+confidence)/2) × SE. SciPy supplies the inverse
t distribution, using inverse survival probability to avoid precision loss near
confidence one. No rounding, customer pooling, physical-bound clipping or
multiple-comparison correction is performed. n<2 retains the mean if available
but has undefined SD/SE/bounds; n≥2 with zero variance yields a point interval.

Independent example: [1,2,3,4,5] gives mean 3, sample variance 2.5, SE=√0.5,
t₄,.₉₇₅=2.7764451051977987, half-width 1.963243161477561 and bounds
[1.036756838522439,4.963243161477561]. Two values [0,2] use one degree of freedom,
half-width 12.7062047364, rather than a normal approximation. Tests also cover
missing, empty, singleton, zero variance, invalid/nonfinite values and precision.

The method assumes independent replication outputs with sufficiently well-behaved
run-level distributions; it is exact for normal outputs and approximate otherwise.
Reference: [SciPy Student-t distribution](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.t.html)
and [standard error convention](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.sem.html).

## Beta assumption and pilot planning

No original instructor beta definition is present in tracked files or their
history. The supplied request explicitly permits a conventional assumption:
**beta is a target absolute CI half-width in the outcome's units**. This is not
claimed as instructor-confirmed wording, relative precision, or Type II error.
Confidence defaults to .95 and is independently configurable.

`estimate_replications` holds usable pilot sample variance fixed and searches for
the smallest total n≥pilot n satisfying t(n−1)*s_pilot/√n≤beta. Binary search updates
the candidate degrees of freedom; it stops at the minimal integer or the configured
cap. The result records confidence, beta, usable/missing pilot size, estimated
variance, required total count, predicted half-width, cap and target_reachable.
Insufficient pilots raise ValueError. Zero variance retains the pilot size; that
does not establish certainty. A cap never claims precision when unmet.

For pilot [1,2,3,4,5], beta=1: n=12 gives about 1.0046>1; n=13 gives about
.9554<1, so total n=13 is required. The reference baseline/uniform/random
abandonment pilot has n=20, variance .001036336376153702, beta=.05 (five percentage
points), and estimated half-width .01506640345435429, retaining n=20.

This is planning, not an achieved-precision guarantee. The reference design uses
a fixed 20 replications per cell and does not adapt or repeatedly stop when an
interval happens to become narrow. For a new study, plan with the pilot, reserve
disjoint replication IDs for a fixed confirmatory batch, then report its actual
interval. A tighter target may require more runs; the API reports that count.

## Design and outputs

Five settings (baseline, low/high demand, small/large fleet) are crossed with both
dispatch policies and both pickup models: 20 cells × 20 runs = 400. Fleet settings
are 5/20/40; interarrival means are .25/.75/1.5 minutes. This is a baseline with
one-factor fleet/demand contrasts, not a full demand-by-fleet factorial. Mode and
policy are crossed at every setting. Optional distance-aware pickup was already
merged in PR #10 and is explicitly included in this requested analysis.

Seven outcomes: queue delay, completed system time, time-average Q/N, utilization,
abandonment and assignment distance. The runner calls the existing metric APIs.
Distance averages include every assigned request, including unfinished service.
JSON includes full design, every replication/configuration/seed/count/outcome,
cell-level CIs, paired policy differences, single-factor contrasts and beta plans.
CSV flattens all 400 replication records. The notebook prints all outcomes and
checks every report field against committed output. Two same-environment runs
match exactly; cross-platform verification tolerates 1e-10 relative/1e-12 absolute
float differences while requiring exact metadata, counts and seeds.

## Replicated comparisons

Pair by replication ID and identical seed bundle, and apply the t interval to
alternative−reference differences. Missing differences are excluded jointly and
their count reported. Duplicate/mismatched IDs or bundles are rejected.

Baseline, 240 minutes, 20 matched runs, 95% pointwise intervals:

| Pickup | Outcome | Random mean | Nearest mean | Nearest − Random (95% CI) |
|---|---|---:|---:|---|
| Uniform | Assignment distance | 5.252044 | 4.102816 | −1.149228 [−1.255156,−1.043301] |
| Uniform | Queue delay, min | .471838 | .471838 | 0 [0,0] |
| Uniform | Abandonment fraction | .104836 | .104836 | 0 [0,0] |
| Distance-aware | Assignment distance | 5.271022 | 4.029237 | −1.241785 [−1.365025,−1.118545] |
| Distance-aware | Queue delay, min | .624315 | .460813 | −.163502 [−.200906,−.126098] |
| Distance-aware | Abandonment fraction | .144602 | .109456 | −.035146 [−.039945,−.030347] |

Uniform mode has exactly equal timing metrics, Q/N, utilization and abandonment
in matched policies: neither service distribution depends on driver identity or
distance. The zero differences follow the model structure. They are not a claim
about real spatial dispatch. Distance-aware mode explicitly changes this coupling;
trip durations still ignore route length. Nearest's current choice changes future
driver locations/candidates, so it does not guarantee a better full-run outcome.
For small-fleet distance-aware assignment distance, the paired CI is
[−.222165,.102477], which includes zero (see raw report for unrounded values).

Uniform/random abandonment contrasts, alternative minus baseline:

| Setting | Difference | 95% CI |
|---|---:|---|
| Low demand | −.102613 | [−.115885,−.089341] |
| High demand | .541786 | [.530195,.553378] |
| Small fleet | .626507 | [.616172,.636841] |
| Large fleet | −.104836 | [−.119902,−.089770] |

These are conditional replicated effects at the fixed other parameters. They do
not identify general real-world causal effects or optimize the fleet. There is
no multiple-comparison adjustment; intervals containing zero are inconclusive.
Queue delay describes served customers, so a lower value can reflect changes in
who gets served; interpret it alongside abandonment and censored outcomes.

## Remaining limits

Uncalibrated speed/overhead and Euclidean geography, route-independent trip time,
finite-run censoring, initially empty state, approximate t coverage for nonnormal
outputs, unadjusted comparisons, and unresolved instructor beta semantics remain
explicit. The final report, presentation and polished bonus animation are not
claimed complete. GUI verification used temporary official Tcl/Tk libraries;
ordinary launch still requires a complete local Tcl/Tk installation.

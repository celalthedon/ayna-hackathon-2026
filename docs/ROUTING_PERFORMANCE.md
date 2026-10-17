# Bounded routing performance experiment

Branch/worktree: `codex/routing-performance` / `routing-performance`, based exactly
on activation commit `696421d204631b3665f84d9243cabf59b59f7d66`. Read-only fetch
found main at `067ba836f161e69bbce68bccb2edee42b218bac4`. At publication,
PR #10 is merged into `celal/c4-routing-contract-v1`, but activation is not
in main. This performance-only PR therefore targets `celal/c5-activate-service`.
Activation integration into main is a prerequisite. No automatic merge is performed.

## Experiment and boundaries

`tools/benchmark_routing.py` uses eight deterministic distinct valid requests:
four per P/B profile (existing-service stress, exact final R2 headway patch,
synthetic 6-minute activation, and both variants with stress/headway patches).
It copies the existing immutable bundle config and synthetic registry to a
temporary external config directory. Catalog values, OD set and source files
are unchanged. There is no candidate reduction, compiler, exhaustive 2,550-case
run or production precomputation.

Stage profiling executes six representative requests: stress/headway/one-service
activation for P/B. Each gets a first uncached call, immediate cache-hit repeat,
and second explicitly uncached call. Uncached refers to derived scenario/OD RAM
caches, not cold filesystem caches; the OS file cache is never flushed.
Temporary timing probes wrap actual routing definitions in the benchmark process
and restore them afterward. They never edit a notebook or generated module.
The recorded non-overlapping stages are:

1. Asset/scenario preparation (with activation detail separately visible).
2. Source arc read/alignment, bus weight transform and parallel-edge minimum.
3. CSR graph construction and reverse-graph CSR preparation.
4. Directed Dijkstra shortest-path search.
5. OD access-option reduction/gather.
6. Public result construction and validation.

Serialization is measured afterward, including its validation. External eval
wall time is reported alongside engine duration_ms: duration_ms is captured
before final EvaluationResult construction/validation, so it is not full caller
wall time. Total including serialization is a separate field. A cProfile call
diagnostic is excluded from throughput measurements. Timing-probe overhead and
machine contention can affect stage samples; they are not throughput figures.

## Windows spawn throughput and memory safety

The identical eight-item workload is scheduled with 1, then 2, then 4 spawn
workers. Each process imports/loads its own model exactly once in its initializer.
Native-library thread environment caps are set to 1 before scientific imports:
OMP, OpenBLAS, MKL, NumExpr, BLIS and vecLib. Thread counts are also sampled.
Worker startup/import/hash-check/model-load cost is separated from workload time.
The supervisor reports calls/second and sampled peak summed process-tree RSS,
Windows private bytes and minimum available system memory with a target 50 ms sampling wait plus collection overhead.
Summed RSS may double-count shared pages; a sampled peak is a lower bound on
instantaneous peak. The default safety floor is 2 GiB available, with process-tree
RSS capped at min(45% of physical RAM, 6 GiB). The floor cannot be lowered below
1.5 GiB through the CLI. Benchmarking does not terminate unrelated applications.

If memory pressure appears, worker jobs are terminated and higher worker counts
are not launched. During in-process stage profiling the guard acts at evaluation
boundaries, not in the middle of a native algorithm. If throughput declines when
adding workers, the next worker count is skipped. There is no claim that four
workers are safe simply because the host has 16 GB RAM.

Sequential (one spawned worker) and parallel outputs are compared by canonical
full-result SHA-256 excluding only duration_ms, plus explicit config_hash checks.
Every OD row/status/minute/capped value is included. Only compact fingerprints
and metrics cross IPC; transferring full OD payloads in Ali's integration could
add overhead. This comparison proves routing multiprocessing only after a real
pool run succeeds; testing the machinery alone does not establish that.

Workers only read the shared bundle/config/fixture; routing caches stay in their
separate process RAM, bytecode writes are disabled, and only the supervisor writes
the exclusive-create report. Full file snapshots of the bundle and temporary
config are compared afterward to detect mutation or unexpected cache files.

## Commands

From the performance worktree with the existing project interpreter:

```powershell
$py = '..\ayna-hackathon-2026\notebooks\citypilot-env\Scripts\python.exe'
$bundle = '..\ayna-hackathon-2026\outputs\c4_model_alpha_20261017_155941_581069'
& $py -I -X utf8 -m unittest discover -s tests -p test_routing_benchmark.py -v
& $py -I -X utf8 tools/benchmark_routing.py --artifact-dir $bundle --mode all --output outputs/routing_performance_v1/initial_run.json
```

The report is exclusive-create: choose a new filename for another experiment;
existing results are preserved. `--mode profile` separates before/after stage
measurements. `--mode throughput --reference <successful-profile-report>` also
checks pool signatures against prior profile results. Reports are ignored output
artifacts, not proposed source changes.

After successful live measurements, per-profile 2,550-call projections use the
measured mean task cost under the recommended concurrency / worker count, plus
startup separately. These are estimates from four distinct samples/profile and
the mixed workload, not profile-exclusive measurements or a guarantee. Real
M-line assets, more active stops/segments, final candidate combinations, memory
contention and IPC payload size may change them substantially.

## Measured bottleneck and single optimization

The original per-destination/per-origin access filtering cost 0.949–1.268 s per
uncached evaluation; Dijkstra was only 0.081–0.283 s. The same origin entries,
start-node arrays and record dictionaries were built nine times. `_solve` now
prepares them once per origin per scenario (302 rather than 2,718 filters), then
uses the unchanged advanced-index/argmin calculation. Row order and ownership
selection stay unchanged; each output row gets its own dictionary copy. There
is no persistent cache, source-arc optimization, contract/catalog change or
second routing refactor. Notebook export cells are authoritative; the generated
module was rebuilt through the exporter. All 67 analysis cells are preserved.

The following are instrumented **first uncached** external wall seconds,
not duration_ms. Relative wall improvements are observations from these samples,
not a statistical guarantee; host scheduling and measurement overhead vary.

| Case | Before wall s | After wall s | Reduction | After duration_ms | Serialization s |
|---|---:|---:|---:|---:|---:|
| P_stress | 2.135 | 1.247 | 41.6% | 1106.0 | 0.130 |
| P_headway | 1.893 | 1.252 | 33.8% | 1047.9 | 0.227 |
| P_activation6 | 2.108 | 1.037 | 50.8% | 919.5 | 0.136 |
| B_stress | 3.305 | 2.015 | 39.0% | 1890.2 | 0.152 |
| B_headway | 2.784 | 2.182 | 21.6% | 1964.5 | 0.133 |
| B_activation6 | 2.989 | 1.889 | 36.8% | 1761.7 | 0.148 |

After-optimization breakdown, milliseconds (sums exclude serialization):

| Case | Asset/scenario | Arc/weight | Sparse CSR | Dijkstra | OD access gather | Result/validation |
|---|---:|---:|---:|---:|---:|---:|
| P_stress | 28.8 | 609.9 | 6.5 | 86.5 | 223.4 | 291.9 |
| P_headway | 39.8 | 514.2 | 27.7 | 84.5 | 189.9 | 396.4 |
| P_activation6 | 67.3 | 489.2 | 19.2 | 86.3 | 109.8 | 265.7 |
| B_stress | 67.2 | 1075.4 | 11.9 | 296.6 | 204.3 | 359.6 |
| B_headway | 113.9 | 981.5 | 21.7 | 296.9 | 232.4 | 535.4 |
| B_activation6 | 159.8 | 1065.5 | 24.4 | 244.0 | 117.3 | 277.6 |

The remaining largest cost is source arc parsing/alignment and weight construction
(~0.49–0.61 s P, ~0.98–1.08 s B); no second optimization was implemented. The
cProfile diagnostic includes monitoring/waiting activity, so the explicit stage
probes, not unfiltered cProfile cumulative totals, establish routing attribution.
Full raw timings, including first/second uncached calls and details, are retained.

| Case | Before 2nd uncached s | After 2nd uncached s | After immediate cache-hit wall s |
|---|---:|---:|---:|
| P_stress | 2.001 | 1.217 | 0.296 |
| P_headway | 2.140 | 1.240 | 0.474 |
| P_activation6 | 2.814 | 1.205 | 0.326 |
| B_stress | 2.518 | 1.844 | 0.260 |
| B_headway | 3.065 | 1.791 | 0.286 |
| B_activation6 | 3.126 | 1.770 | 0.262 |

Cache-hit calls still construct/validate results. Those costs were not optimized;
their observed 0.26–0.47 s range must not be attributed to graph recomputation.

## Spawn worker throughput and recommendation

All worker runs use the identical eight configs with forced uncached derived
solutions, and no AST/cProfile instrumentation. One model load per successful
worker PID was verified. All eight full-result/config hashes agree between the
1-worker control and 2-worker concurrency; the six profiled configurations also
match the pre-optimization results exactly. That covers all OD rows, not just
rounded counts. The 1-worker parity flag in the raw report denotes the control;
actual multi-worker agreement is established by the 2-worker run.

| Workers | Startup s | Eight-call workload s | Calls/s | Peak tree RSS GiB | Peak tree private GiB | Min available GiB |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 2.344 | 12.638 | 0.633 | 0.519 | 0.502 | 2.610 |
| 2 | 2.680 | 7.398 | 1.081 | 0.816 | 0.842 | 2.390 |
| 4 | aborted | not completed | not measured | 1.408 | 1.454 | 1.878 |

Recommend **2 workers with the live 2 GiB floor** for this 15.63 GiB machine
under the measured headroom; it achieved 1.71× the one-worker throughput. Do not
use 4 on the strength of this test: the guard terminated that run when available
memory fell to 1.878 GiB. No completed 4-worker throughput/parity is claimed, and
no unrelated application was terminated. Use 1 if 2 cannot retain headroom; if
the floor is already violated, do not launch even one routing worker. Reopening
a large VS Code notebook or loading larger real assets can change this advice.

Native compute environment caps were 1. Observed OS threads reached 8 per worker
and 11 in the supervisor (including monitoring/runtime threads); environment caps
do not imply a single total OS thread. Only process-level routing concurrency of
two is verified here. File snapshots confirm no model/config/fixture mutation;
all caches are per-process RAM and no concurrent routing cache file is written.

## Estimated 2,550-call time per profile

These are **estimates**, not 2,550 evaluated packages: mean task time from four
configs/profile under the measured mixed-workload concurrency, divided by worker
count, plus one startup. Sustained utilization/load balance is assumed. Full OD
IPC rather than compact signatures, final M stop counts/access geometry and a
different configuration distribution can increase cost. They are not deadlines
or proof of real-M optimization readiness.

| Workers | P estimate, minutes | B estimate, minutes |
|---:|---:|---:|
| 1 | 45.9 | 88.0 |
| 2 | 29.2 | 45.6 |

## Execution, artifacts and validation

Initial attempts were correctly blocked/stopped under low memory. The first
report had 1.770 GiB available; a second attempt hit the floor during profiling.
After the user saved a separate notebook backup and closed VS Code, available
RAM was rechecked at 3.567 GiB. The successful reports above retained the default
2 GiB floor; no guard was lowered to force a result. Earlier reports are preserved.

Actual experiment commands, from this worktree:

```powershell
$py = '..\ayna-hackathon-2026\notebooks\citypilot-env\Scripts\python.exe'
$bundle = '..\ayna-hackathon-2026\outputs\c4_model_alpha_20261017_155941_581069'
& $py -I -X utf8 tools/benchmark_routing.py --artifact-dir $bundle --mode profile --output outputs/routing_performance_v1/before_profile.json
# notebook optimization, followed by exporter regeneration:
& $py -I tools/export_notebooks.py --owner celal --notebook notebooks/01_network_routing.ipynb
& $py -I -X utf8 tools/benchmark_routing.py --artifact-dir $bundle --mode all --reference outputs/routing_performance_v1/before_profile.json --output outputs/routing_performance_v1/after_benchmark.json
```

70 relevant tests passed, zero failures/errors/skips, in separate serial processes
to release suite-level model memory between suites. All 10,872 saved baseline
rows/statuses/capped values/sums match within 1e-6 min, including inactive
registration. Counts remain P normal 2060/2339/2496, P disrupted 636/1191/1697,
and B normal/disrupted 2406/2506/2511. Activation/stress, terminal/grid journeys,
leg sums, directed supplemental access, ownership, zero edges, tie ordering,
dictionary isolation and strict shared serialization remain valid.

```powershell
$env:CITYPILOT_TEST_BUNDLE = (Resolve-Path $bundle).Path
# Native thread environment caps are set to 1 as described above.
foreach ($pattern in @('test_routing_benchmark.py','test_solver_access.py','test_routing.py','test_export.py','test_baseline_adapters.py','test_service_stress.py','test_activate_service.py')) {
  & $py -I -X utf8 -m unittest discover -s tests -p $pattern -v
}
& $py -I tools/export_notebooks.py --owner celal --notebook notebooks/01_network_routing.ipynb --check
git diff --check
```

Suite results: benchmark 9 / 0.175 s; access 1 / 0.680 s; shared 9 / 0.247 s;
exporter 9 / 0.326 s; baseline 9 / 33.475 s; phase-1 stress 11 / 28.252 s;
activation 22 / 15.631 s. The baseline geometry test reports existing Shapely
deprecation warnings; no new failures. No raw notebook analysis was executed.

Raw before/after/guard reports and summary.json are under
outputs/routing_performance_v1 (ignored artifacts). Validation log and original
notebook backup are outside tracked source under
C:\Users\celal\OneDrive\Belgeler\ChatGPT\AYNA\routing_perf_work.
Only six source/notebook/test/documentation paths changed; existing branches,
PRs, catalog, immutable bundle, raw inputs and environments are preserved. No
frontend, compiler or production precomputation was added. Publication uses only
the dedicated performance branch; no main push or merge is authorized.


Final guard-only check: a late-pressure recommendation regression was added after
the measurements; the benchmark machinery suite passed 10 tests in 0.161 s.
This is one additional unique test, bringing completed focused coverage to 71
(70 initial tests plus that guard regression). The final changes only exclude
unsafe recommendations and retain future aborted-run startup diagnostics; routing
and measured work are unchanged, so expensive numerical suites were not repeated.
Reapplying the final safe-run selector to the saved data still selects 2 workers.

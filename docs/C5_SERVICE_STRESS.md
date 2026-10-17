# C5 phase 1 — existing-service headways and real bus stress

Phase-1 work on `celal/c5-service-stress`, isolated from the dirty original
checkout and PR #6. Starts exactly at C4 commit
`1f115812b69b52bfe3c85e30459ef3650036f062`. Published as a stacked PR targeting
`celal/c4-routing-contract-v1`, dependent on C4 PR #6 while it remains open.
No main push, merge or Ali-owned file changes. The test/preservation report
records verification before publication authorization; its no-commit snapshot
does not describe the subsequent authorized branch publication. The immutable external 49-payload bundle and fixed 302×9 OD selection
are unchanged; its existing manifest hashes are verified by load_model.

## Implemented semantics

- Positive finite speed_factor divides **only bus_ride moving-time arcs**.
  Bus_continue dwell, walking/pushing, cycling, metro, parking and transfers stay
  unchanged, including exact sparse graph weights. Initial grid access is unchanged.
- A nonnull headway_factor_by_group must contain exactly all existing groups
  (SG_R2 and SG_R14 here); partial/empty/unknown/prebuilt mappings fail. Null uses
  factor 1 everywhere. Boarding wait is baseline headway × factor / 2.
- Mitigated permits set_service_headway against actual existing IDs. Its finite
  positive value is the **final** headway and overrides the factored value; it
  is never multiplied twice. 7.5×1.2 gives 9 min / 4.5 wait; explicit 7.2 gives
  3.6 wait. Duplicate/order-equivalent patches canonicalize; conflicts fail.
- Normal/disrupted permit stress without patches. Mitigated uses disrupted
  topology and the declared closure. Empty mitigated and disrupted give identical
  OD rows for equal factors, with different state/config identities as expected.
- Continuing onboard never creates a boarding arc or a second wait. No topology
  or calibration change is introduced. Activation kinds are explicitly rejected.

Public config_hash remains canonical shared v1 JSON, including model/bundle/OD,
state, closure, profile, factors and patches, thresholds/cap and trace. Equivalent
mapping/patch ordering preserves it. Null versus explicit all-ones mappings can
have distinct wire hashes with identical physical costs. All public results
retain strict shared parsers/serializers and finite/null time semantics.

## Scenario implementation and preservation

Notebook routing_export definitions remain authoritative. routing_engine.py was
generated only through tools/export_notebooks.py. Source notebook was backed up
outside tracked source before editing; all 67 non-export cells remain intact.
No recovery history was appended/executed. Full raw-data notebook reproducibility
is still pending, not implied by adapter/source checks.

Each cache miss reads immutable baseline arc alternatives, applies only the
requested cost rules, then chooses stable minimum cost for each directed pair.
No CSR parallel-edge sum and no explicit-zero elimination occurs. Original
winning arc costs are aligned to exact NPZ values (CSV parsing may differ by an
ULP); this preserves untouched weights exactly. All parallel alternatives remain
available before scenario minimisation, including a previously losing bus arc
that becomes cheaper under speed stress.

The original graphs, catalog and cached source arc tables are never rewritten.
Derived views have their own graph, winning arc table, OD solutions and directed
predecessors. A two-entry LRU cache is keyed by physical topology/speed/effective
headways, not runtime, paths, thresholds/cap or trace fields. Evaluation and
inspection select the same view. Cache eviction can change runtime, not results.
Scenario provenance remains assumption status and explains the explicit cost
transformations; source assumptions are not upgraded to observations.

The exporter also now recognizes its exact generated first-line marker after a
Windows CRLF checkout, so it can regenerate LF output without treating that module
as hand-maintained. Non-generated files still cannot be overwritten. A regression
test confirms this and preserves the other owner's module.

## Verification and measured real-model results

**38 focused tests passed**, 0 failures/errors/skips, using the existing Desktop
Python 3.13.1 interpreter. Suites: phase 1 11 tests (65.015 s), shared contracts
9 (0.362 s), exporter 9 (0.428 s), baseline 9 (61.691 s). Exporter --check passed.
Both default and explicit all-ones factors preserve all **10,872** saved baseline
rows/statuses/capped values/sums within 1e-6 min and original 40/45/50 counts.
Checks also cover parallel-winner changes/zero edges, invalid factors/IDs/full
mappings, exact patch precedence/conflicts, unchanged dwell/metro/nonbus costs,
bounded interleaved scenario caches and baseline immutability, empty mitigated
equivalence, terminal/grid directed access and journey sums, clean-process
load/evaluate/journey and tagged-source/export numeric parity.

The following are actual 2718-pair evaluations, not fixture estimates. Sums are
capped physical minutes with C=120. Evaluation timings include scenario graph
derivation and OD calculation before duration capture, not model load. Each row
is the first evaluation of that physical scenario in its measurement process;
journey inspection reuses it. Timings are hardware/cache dependent.

| Scenario | Speed | R2/R14 factors | R2 final override | ≤40/45/50 | Capped sum (min) | Eval ms |
|---|---:|---|---:|---|---:|---:|
| P normal | 1.0 | 1.2/1.0 | — | 2049/2338/2496 | 94498.07626603 | 1675.0 |
| P mitigated | 1.0 | 1.2/1.0 | 7.2 | 643/1197/1712 | 128391.40918743 | 2692.5 |
| P disrupted | 0.8 | 1.2/1.1 | — | 522/932/1413 | 134477.69167553 | 2651.6 |
| P mitigated | 0.8 | 1.2/1.1 | 7.2 | 541/955/1468 | 133533.43299146 | 2688.1 |
| B mitigated | 0.8 | 1.2/1.1 | 7.2 | 2406/2506/2511 | 74039.03126967 | 4105.7 |

Verified model load: 1651.6 ms. Full inputs, config hashes,
actual timings, effective headways and journey details are in
`C5_SERVICE_STRESS_RESULTS.json`.

For the P mitigated slow-bus patched scenario, terminal → metro exit 44 takes
44.27490074173089 min, exactly matching the 70-leg sum; the source geometry has
32 disclosed gaps. B's measured aggregate remains unchanged for this scenario. Aggregate equality
does not assert that all over-cap physical times or bus arc costs are unchanged;
bus movement scaling in B is explicitly tested.

## Exact commands and runnable request

From this worktree in PowerShell (reuse the original interpreter and external model):

```powershell
$py = 'C:\Users\celal\OneDrive\Desktop\ayna-hackathon-2026\ayna-hackathon-2026\notebooks\citypilot-env\Scripts\python.exe'
$env:CITYPILOT_TEST_BUNDLE = 'C:\Users\celal\OneDrive\Desktop\ayna-hackathon-2026\ayna-hackathon-2026\outputs\c4_model_alpha_20261017_155941_581069'
& $py -I tools/export_notebooks.py --owner celal --notebook notebooks/01_network_routing.ipynb
& $py -I tools/export_notebooks.py --owner celal --notebook notebooks/01_network_routing.ipynb --check
foreach ($pattern in @('test_routing.py','test_export.py','test_baseline_adapters.py','test_service_stress.py')) {
    & $py -I -X utf8 -m unittest discover -s tests -p $pattern -v
    if ($LASTEXITCODE -ne 0) { throw "Failed: $pattern" }
}
@'
import os,sys
from pathlib import Path
from dataclasses import replace
sys.path.insert(0,str(Path('src').resolve()))
from citypilot import routing_engine as routing
from citypilot.contracts import RoutingPatch
b=Path(os.environ['CITYPILOT_TEST_BUNDLE'])
model=routing.load_model(b,b/'config')
request=replace(routing.baseline_request(model,'mitigated','P'),
    speed_factor=0.8,headway_factor_by_group={'SG_R2':1.2,'SG_R14':1.1},
    patches=(RoutingPatch(kind='set_service_headway',target_id='SG_R2',headway_min=7.2),))
result=routing.evaluate_package(model,request)
journey=routing.inspect_journey(model,request,'origin:terminal:baku_international','destination:metro_exit:44')
print(dict(result.within_counts),result.capped_time_sum,result.duration_ms)
print(journey.total_min,sum(leg.total_min for leg in journey.legs))
'@ | & $py -I -X utf8 -
```

## Remaining C5/integration gaps

activate_service, activate_link and enable_parking remain explicitly unsupported.
There are no fabricated ready services/links/parking candidates, no activation
readiness rules, compiler, resource accounting, optimisation, frontend or CO2
implementation. Ali still needs to migrate consumers to shared v1, provide the
complete existing-service factor map and concrete final headway patches, and
validate his compiler/resource/search integration separately. His code/tests were
not modified or executed; no integration-success claim follows from these checks.
The C4 PR/allowlist documents remain historical C4 artifacts, not a C5 commit plan.

## Changed files (11; C5 delta only)

```text
docs/C34_ADAPTERS.md
docs/C5_SERVICE_STRESS.md
docs/C5_SERVICE_STRESS_RESULTS.json
docs/CONTRACT.md
notebooks/01_network_routing.ipynb
src/citypilot/contracts.py
src/citypilot/routing_engine.py
tests/test_baseline_adapters.py
tests/test_export.py
tests/test_service_stress.py
tools/export_notebooks.py
```

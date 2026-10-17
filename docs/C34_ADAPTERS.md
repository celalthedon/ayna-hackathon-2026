# C3/C4 baseline adapters with shared contract 1.0

Notebook `routing_export` cells remain the source of truth; generate the module
only with `tools/export_notebooks.py --owner celal`. Shared contracts are now v1;
the local BaselineJourneyResult dialect and legacy payload fields are removed.
See `CONTRACT.md` for exact schemas, units, evidence and future stress semantics.
Declaring patches/stress does not implement their C5 execution.

## Immutable inputs and history

Explicit 49-file bundle: `outputs/c4_model_alpha_20261017_155941_581069`.
Bundle hash: `9457bfe95125b1d8bddb1be662ad6f0bbd1a00c0ac8f8abcc2fbecf872d53066`.
OD hash: `10c1b58f1d704cec25b11936da32c2c09bc995323e8a4083fd0bd46f50286ac8`.
Every manifest file is hashed; bundle hash is recomputed from UTF-8
`json.dumps(files, sort_keys=True)`. References, access costs and sparse dimensions
are validated. OD hash agrees across the manifests; its independent construction
recipe was not recorded, so OD payloads are additionally verified through bundle
hash entries. Runtime accepts explicit directories only, no implicit latest
bundle or machine-specific runtime path. External config must match bundle inputs.

No bundle files or fixed OD selection changed. No Ali notebook/module,
curated/config inputs, virtual environment or recovery history was edited.
Before this migration, notebook/contracts/module/exporter/tests were backed up to
`../contract_v1_backup_20261017T163109Z/`; protected file hashes were recorded there.
All non-export notebook cells, including analysis and their saved outputs, remain
identical to that backup. Existing executed source history under
`outputs/notebook_recovery/executed_cells_*.json` is preserved. It contains failed
and debug cells too; it was not appended to the notebook or executed. This task
does **not** establish full source recovery or clean execution of all analysis
cells. Only self-contained tagged definitions and adapters are executed by checks.

Prior fetched main was `f3047071c45b85c9be295b42e948b83c23b107ff` (PR #4).
Its P1–P20 assumptions CSV matched the bundle byte-for-byte; no new parameters
were adopted. The YAML assumptions file was absent there. No fetch/merge/reset/
stash/commit/push is part of this migration.

## Unchanged numerical and journey logic

Reverse-graph searches cover 302 origins × 9 individual street exits per scenario.
Grid access weighs both segment endpoints, including walk/push-to-snap and
permitted directional cycling. B starts with a bike and can finish with it;
there is no transit boarding with a bike, at most one parking transition, no
retrieval. Sparse explicit zero edges survive; parallel arcs use minimum cost.
Actual time remains uncapped internally and on over_cap wire rows. No_path wire
minutes is null and its finite objective penalty is C.

Calibration/network/closure remain fixed: walk 4.788 km/h, bike 15 km/h, parking
1 min, metro ride 2.5 min, entry/exit/interchange 4 min, metro headways
green/red/purple 3.5/2.5/8 min. Bus speeds remain ~24.27746/24.34068 km/h for
routes 2/14; dwell 25 s at 87/55 intermediate stops; full-cycle layover 10 min.
The interpretation of durationMinuts as mean one-way time remains an assumption.
Existing service IDs/patterns and all 639 baseline parking IDs are retained.
No prebuilt services, candidate links or candidate parking were invented.

Journeys reconstruct the actual winning directed access/ownership route. Waiting
is charged only on boarding; staying onboard uses saved continue arcs. Bus shapes
are the successful projected-stop substrings, preserving source distances for
time. Source gaps are now MultiLineString plus GEOMETRY_GAPS/partial provenance,
not null path geometry. Route 14 stop 105 alignment is unresolved (~148–163 m);
access/grade/parking transitions remain assumed; metro entry/interchange is
schematic. No physical connectors were invented. Points encode zero motion.

## Verification

The v1 regression checks compare all 10,872 saved rows/statuses, actual and capped
minutes, capped sums and threshold counts to 1e-6 min. They also cover every saved
directed predecessor path, terminal/grid journey sums and chosen access costs,
shared v1 round-trips, no_path/over_cap/zero-motion/gapped geometry, typed evidence,
existing/prebuilt separation, parking flags, corruption, unsupported requests,
clean-process load/evaluate/journey and source/export numerical parity.

| Profile/state | ≤40 / ≤45 / ≤50 | Capped sum, min |
|---|---|---:|
| P normal | 2060 / 2339 / 2496 | 94375.40594217333 |
| P disrupted | 636 / 1191 / 1697 | 128583.2876033397 |
| B normal | 2406 / 2506 / 2511 | 73577.91477922363 |
| B disrupted | 2406 / 2506 / 2511 | 74039.0312696655 |

Actual current-run results and maximum errors are recorded in `C34_PARITY.json`.
No whole-notebook clean-run claim follows from these adapter/export checks.

From the canonical Desktop repository in PowerShell, using the existing interpreter:

```powershell
$py = '.\notebooks\citypilot-env\Scripts\python.exe'
& $py -I tools/export_notebooks.py --owner celal --notebook notebooks/01_network_routing.ipynb
& $py -I tools/export_notebooks.py --owner celal --notebook notebooks/01_network_routing.ipynb --check
$env:CITYPILOT_TEST_BUNDLE = (Resolve-Path 'outputs/c4_model_alpha_20261017_155941_581069').Path
foreach ($pattern in @('test_routing.py', 'test_export.py', 'test_baseline_adapters.py')) {
    & $py -I -X utf8 -m unittest discover -s tests -p $pattern -v
    if ($LASTEXITCODE -ne 0) { throw "Failed: $pattern" }
}
& $py -I -X utf8 tools/check_baseline.py --artifact-dir outputs/c4_model_alpha_20261017_155941_581069 --config-dir outputs/c4_model_alpha_20261017_155941_581069/config --profile P --state normal
```

The CLI prints a strict v1 normal/P request, catalog IDs, 2718-row metrics and
terminal-to-first-exit journey. Expected physical/leg-sum time is
34.91077163959099 min (38 legs); geometry is partial MultiLineString. Catalog,
request, evaluation and journey all parse through shared v1 serializers.

Ali still needs to replace/import his shared stubs and adapt his consumer logic
as listed in `CONTRACT.md`, then verify resource/search integration. Baseline
runtime explicitly rejects C5/stress; activation/readiness, frontend and CO2
remain out of scope. OD distance definition/schema is unresolved; no distance
default or zero substitution was added and manual input remains the future fallback.

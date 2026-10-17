# Constructed M-service supplement handoff

All five lines built, all ten variants load, and no service is blocked. This is
a complete **CONSTRUCTED model cycle**, not verified official M-route coverage.
Approximate ordinary-stop coordinates are not verified express platforms.
Forward stop order is supplied as published; return order, design intervals,
transferred speed, street paths and bus access retain their stated assumptions.

Branch: `celal/m-service-supplement`. The PR stacks on
`codex/routing-performance` at `9915cac6a39603511bcdd7d85cf6335c40611f76`,
which includes activation `696421d204631b3665f84d9243cabf59b59f7d66` (PR #10)
and performance (PR #13). Publication-time read-only fetch found main at
`9302852`, including merged PRs #17/#18 but still lacking both prerequisites;
ancestry and loader inspection confirmed this. The remote prerequisite tip was
verified; no prerequisite merge or direct main push is part of this change.
Ali coordinates integration and eventual retargeting after prerequisites merge.
The primary checkout, other worktrees and Ali's unfinished A6 remain untouched.

New files:

- `src/citypilot/m_service_builder.py`: offline preparation only.
- `tools/build_m_services.py`: explicit CSV/bundle/output CLI.
- `tests/test_m_service_builder.py`: focused preparation tests.
- `tools/verify_m_services.py`: clean-process loading and numerical verification.
- This handoff and `supplements/m_services_v1/`: original CSV, build report,
  verification receipt, unchanged external `config/limits.yaml`, registered
  `config/prebuilt_services/{assets,manifest}.json`, and scoped `.gitattributes`
  preserving all supplement bytes on checkout.

Routing engine, contracts, notebook, existing curated R2/R14 files, immutable
bundle and its manifest are unchanged. All 49 bundle payload hashes were checked
again after verification; manifest SHA-256 remains
`a372e5ade6df97dbf99228306ce79bc2e1ff3231bce41a5c32e29b29d4dcd3f9`.

## Loading and identity

Run from the repository root in an environment with the validated routing
dependencies. The repository-relative `config_dir` is
`supplements/m_services_v1/config`. The immutable bundle is supplied separately;
it is not included in this PR. Place it at the explicit repository-relative path
below, or pass its actual location. Config is always external to that bundle.

```powershell
python -I -X utf8 -c "import sys; sys.path.insert(0,'src'); from citypilot.routing_engine import load_model,get_catalog; m=load_model('outputs/c4_model_alpha_20261017_155941_581069','supplements/m_services_v1/config'); print(sorted(get_catalog(m).prebuilt_services))"
```

`assets.json` exactly follows the CURRENT dependency loader schema in
`docs/C5_ACTIVATE_SERVICE.md` and the fixture: four top-level keys, exact shared
ServicePattern/ServiceGroup/provenance fields, explicit segment distances and
WGS84 geometry. There are no engine/schema changes. The manifest uses the existing
`prebuilt-services-1` registration and canonical manifest identity mechanism:

```json
{
  "asset_version": "prebuilt-services-1",
  "bundle_hash": "9457bfe95125b1d8bddb1be662ad6f0bbd1a00c0ac8f8abcc2fbecf872d53066",
  "files": {"assets.json": "b806210d0e3bf4813077a03f654e78bb8cdc8c1447ab0104fff99614259dc407"},
  "supplement_hash": "42a560089d459f61667e6624425e04e03429d03f139605ef02124874d801835a"
}
```

Use the loaded catalog's `model_version` in requests; it has the existing
`+prebuilt@42a560089d459f61667e6624425e04e03429d03f139605ef02124874d801835a`
suffix. All 10 catalog IDs are `SVC_M{1,2,3,5,6}_{A,B}`. Service suffix **A means
6-minute design headway; B means 9 minutes**. Either references both road
patterns `M<n>_A` and `M<n>_B`; the service suffix is independent of direction.

## Construction and evidence

The supplied CSV is preserved byte-for-byte as `source_stops.csv`, SHA-256
`9033230f0c97a9e45b88f681713e4519251d77f2239720c35ab882c22ca69af6`.
All fields are read as strings before numeric validation; leading zero Google
IDs, point IDs, original decimal coordinate text, names and Ali's notes survive
in both the source/report and stop provenance. Validation confirms 24 rows,
7 physical stops, 10 directed patterns and 14 ride segments, consecutive seq,
consistent coordinates/IDs per stop, finite WGS84 values, exact line membership,
published A order and reversed-by-assumption B order. M9 is excluded.

The bundle has no separate bus flag: its directed drive road class approximation
is used for BUS paths, **including permitted busways**. Filtering is
`edge_type == road AND (drive_forward OR drive_reverse)`. There are 104,120
eligible segments, including 192 busway segments, and 186,026 directed minimum
connections. The private-car supplement's busway exclusion is not used.
Weights are source `length_m`, never travel time. Parallel edges use minimum
distance, stable edge ID/direction ties and sorted CSR traversal.

Each physical stop snaps once to its nearest nondegenerate eligible road segment
within an explicit **100 m** model assumption. Exact distance ties use edge ID;
no component or reachability preference is applied. Original coordinates remain
unchanged for both A and B. Partial-edge costs use the source directed length
times fraction, retaining oneway flags, node identities and grade topology.
There are no joins between geometric crossings, new grade links, boundary clips,
area expansion or straight-line ride fallback.

Ordered paths are shortest DISTANCE subject to a consistent traversal orientation
at each intermediate anchor. Dynamic programming retains the arrival orientation
for departure at Nizami; an artificial snap cannot create a U-turn. B is solved
independently. Turns at existing source nodes follow bundle topology; source
turn restrictions and grade transitions are not independently verified. The
delivered paths contain no immediately reversed source-edge pieces. Full-cycle
resource fields sum both complete paths; no passenger through-run or terminal
turnaround street geometry is manufactured.

Bus ride geometry starts/ends at the road anchors. Bus snap displacement is
reported and excluded from ride distance; no off-road bus connector is invented.
The existing loader independently supplies assumed pedestrian access to the
original stop coordinate. Its nearest walk-road snaps are audited separately
and agree with clean-process loading. Both snap policies use the same 100 m limit.

## Distances and review diagnostics

Distances below are metres; cycle is kilometres. The report retains full
precision and every directed edge ID, fraction and partial length.

| Line | A distance m | B distance m | Cycle km | Intermediate dwells/cycle | Segment detour ratios A / B |
|---|---:|---:|---:|---:|---|
| M1 | 4093.617 | 4432.218 | 8.525835 | 0 | 1.452 / 1.572 |
| M2 | 6461.072 | 6669.296 | 13.130368 | 2 | 1.673, 1.252 / 1.524, 1.597 |
| M3 | 5388.433 | 5877.014 | 11.265447 | 2 | 1.097, 1.252 / 1.524, 1.120 |
| M5 | 5140.396 | 5748.737 | 10.889133 | 0 | 1.410 / 1.576 |
| M6 | 5837.486 | 6099.565 | 11.937051 | 0 | 1.436 / 1.500 |

Detour ratio = road distance / metric chord between bus-road anchors. Review
threshold is explicitly greater than 3.0; no segment is flagged (range
1.097–1.673). No no_path, excessive snap, outside-model stop or blocked line was
found. A failed direction would exclude both variants of that line. An entirely
blocked build produces its diagnostic report without an activatable registry.

| Original stop_key | Bus-road displacement m | Loader walk displacement m |
|---|---:|---:|
| M_20YANVAR_VELOTREK | 1.660 | 1.660 |
| M_28MAY_NMM | 10.000 | 0.244 |
| M_ELMLER | 8.904 | 0.331 |
| M_GENCLIK_NMM | 6.622 | 22.872 |
| M_INSAATCILAR | 9.522 | 9.522 |
| M_NIZAMI | 18.938 | 1.776 |
| M_ZERDABI_TBILISI | 17.597 | 17.597 |

All variants use **24.309068600209667 km/h**, the arithmetic mean of actual
curated R2 `24.277458329768773` and R14 `24.340678870650557` calibrated speeds.
This transfer is an assumption, not an M observation. Dwell is 25 seconds;
only M2/M3 serve Nizami, giving two intermediate dwells per cycle. M1/M5/M6
have their two terminals only. Full-cycle layover is `2 × P5 default 5 min =
10 min`, not passenger time. `coverage=full` is explicitly assumption-labelled
constructed cycle completeness, never official M route coverage.

## Reproduction and verification

Build into a **new** directory; the CLI refuses existing output and paths that
overlap the immutable bundle:

```powershell
python -I -X utf8 tools/build_m_services.py --artifact-dir outputs/c4_model_alpha_20261017_155941_581069 --stops-csv supplements/m_services_v1/source_stops.csv --output-dir outputs/m_services_rebuild --max-snap-m 100 --detour-ratio 3
python -I -X utf8 -m unittest discover -s tests -p test_m_service_builder.py -v
python -I -X utf8 tools/verify_m_services.py --artifact-dir outputs/c4_model_alpha_20261017_155941_581069 --config-dir supplements/m_services_v1/config --report outputs/m_services_verification.json --original-csv supplements/m_services_v1/source_stops.csv
git diff --check
```

Results: **11 focused tests passed** in 1.107 s, zero failures/errors/skips.
Coverage includes directed one-way and independently routed return partial
costs, shortest-distance weights, busway retention, exact endpoints, intermediate
anchor orientation, geometry, grade-separated coincident nodes, deterministic
nearest-edge/component choice, missing/bad CSV/network/calibration/P5 inputs,
blocked/excessive stop exclusion, cycle totals, variants and deterministic assets.

Clean-process `verify_m_services.py` passed. It loaded all 10 variants and strict
catalog round-trip/units, rebuilt into a temporary directory and byte-compared
all five preparation files (source CSV, report, limits, assets and manifest),
checked every saved no-patch baseline row/status/capped value and sum, then
smoke-tested one 6-minute variant per line. Each smoke found an improved OD
actually using the activated service, checked shared serialization and 3-minute
wait, and matched evaluation, journey and leg sum within 1e-6 min.

| Registered no-patch scenario | OD rows | Counts within 40 / 45 / 50 min | Maximum error min |
|---|---:|---|---:|
| P normal | 2718 | 2060 / 2339 / 2496 | 7.11e-15 |
| P disrupted | 2718 | 636 / 1191 / 1697 | 1.42e-14 |
| B normal | 2718 | 2406 / 2506 / 2511 | 1.42e-14 |
| B disrupted | 2718 | 2406 / 2506 / 2511 | 1.42e-14 |

Example `SVC_M1_A`: `origin:metro_exit:42` to `destination:metro_exit:44`;
evaluation = journey = leg sum = **14.245307454077144 minutes**, including one
3-minute design wait. The complete request/journey and all five smoke receipts
are in `supplements/m_services_v1/verification.json`. These are model smoke
results, not service calibration or optimization claims.

The unchanged engine's full verification receipt is reused from
`docs/ROUTING_PERFORMANCE.md` at `9915cac` (71 focused tests). No optimizer,
full precompute, new benchmark or notebook execution was run.

Read-only interpreter check for Ali:

```text
shapely.__version__ = 2.2.0
pyproj.__version__ = 3.8.0
```

The existing project interpreter was used without package/environment changes.
The machine-specific `sys_executable` field is omitted from the published receipt;
all numerical results, dependency versions and byte-comparison evidence are
retained. Code, source CSV, registered assets, manifests and build report are
unchanged from the completed verification, so its 11-test/deterministic rebuild/
10,872-row parity evidence is reused. Only publication documentation, receipt
path redaction and checkout byte-preservation metadata changed.

## Remaining review

Ali/team should review actual express boarding locations and side-of-road access,
assumed B order, plausible bus paths/permissions/turns and source grade assumptions,
terminal turnaround operation, the 100 m snap/3× detour thresholds, and the design
headway/speed/dwell/layover assumptions. Complete constructed cycles do not settle
official service coverage or operational feasibility. Ali retains decision/resource
optimization ownership and coordinates adoption of activation, performance and
this supplement into the advanced main integration. Opening this stacked PR
does not authorize automatic merging, optimization or precomputation.

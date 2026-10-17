# Static modelled OD car-distance supplement v1

Offline Celal-owned supplement on branch `celal/od-car-distances`, based exactly
on C4 commit `1f115812b69b52bfe3c85e30459ef3650036f062`. Initial implementation and verification involved no commit/push/merge,
Ali-owned changes, CO2 arithmetic/UI, compiler/consumer migration, aggregation
helper, interventions or transit routing changes. The original 49-file bundle,
302 origins, 9 individual exits and canonical profile-aware OD mapping stay fixed.

## Inputs, policy and limitations

The saved drive network was bus-oriented. The private-car **approximation** keeps
only source `road` edges with a saved drive direction and removes every fclass
starting with `busway` (casefolded). All source direction flags, nodes and grade
topology remain intact. Neither coordinate coincidences nor geometric crossings
create links. Source endpoint/grade assumptions remain assumptions. This is not
observed taxi routing and is not a fully verified private-car legal network.

Source graph: `drive_distance_graph.npz`, checked against `drive_arcs.csv.gz` and
the matching `edges.csv.gz` directions/lengths. All bundle manifest hashes are
verified before computing. Filtered graph: **103,928 segments / 185,834 directed
connections**, after excluding **192 busway segments/arcs**, preserving all source
node IDs (97,058 active car nodes). It retains 314 source nodes marked as assumed
endpoint transitions. Detailed private/access/motor_vehicle restrictions and
turn/time-dependent restrictions are absent; dropoff/parking legality is unknown.
No detailed car or taxi legality is inferred from bus eligibility.

Metric CRS is **EPSG:32639**, WGS84 input points transformed with always_xy=True.
Snap actual saved origin/exit coordinates, not their transit walk-node positions.
Use the nearest eligible segment; exact distance ties choose lexicographically
smallest source edge_id. Never select another component or a farther segment to
obtain a route. OD points have no grade information: a coincident over/underpass
tie chooses one existing segment deterministically without joining levels.

`--max-snap-m` is required, positive finite. This run explicitly uses **100 m**,
recorded as an assumption. Endpoint tolerance is 1e-8 m for numerical projection
roundoff. Zero-extent geometry is not a snap target; any such directed graph edge
is retained (none exists in the real filtered graph). Current snapping assumes
straight source segments; the saved road polylines are already exploded segments.

For interior snaps, add weighted directional origin exits and destination entries.
Exact endpoints permit their actual node at zero extra network cost without a
forbidden reverse partial segment. Also check the direct legal same-segment
fractional distance; an endpoint-only detour cannot replace it. Nine reverse
virtual-sink searches compute all **2718 physical pair results once**, which are
then associated with both profiles' exact canonical OD IDs (**5436 rows**).
Zero sparse edges are retained; parallel pairs use minimum, never sum. No other
component, straight-line distance or zero substitutes for a missing route.

Distance excludes all off-network snap displacement. A successful zero network
distance is legitimate for coincident snapped positions or a zero-length directed
path even if actual points have separately reported off-network displacement.
This run has no successful zero pairs; focused synthetic checks verify that case.

## Output schema and provenance

CSV (UTF-8, LF) columns, exactly:

```text
od_id,origin_id,destination_id,profile,car_distance_km,status,snap_m,origin_snap_m,destination_snap_m
```

Internal graph/partial distances are metres; successful output is kilometres.
`modelled` carries finite nonnegative km. `no_path` means both snaps satisfy the
limit but no permitted directed route was found. `snap_failed` means a nearest
snap exceeds the limit or no eligible target exists. Unknown km stays empty,
never zero. Both known displacements give snap_m=max(origin_snap_m,
destination_snap_m), including rejected snaps; otherwise snap_m is empty.

Manifest identifies model/bundle/OD versions/hashes, source file hashes, source
and filtered graph, CRS/units, full policy and its hash, explicit 100 m assumption,
all 311 point snap records (edge/fraction/coordinates/displacement), output hash,
implementation hash, runtime and exact P/B evaluator ID checks. The filtered CSR
hash is SHA-256 over canonical shape/encoding JSON, then sorted CSR indptr/indices
as little-endian int64 and data as little-endian float64. It identifies the
derived graph without writing another model bundle. Manifest has no NaN/Infinity;
solver Infinity remains internal. CSV is deterministic for fixed inputs/policy;
manifest timestamp/runtime reflect the retrieval. Existing outputs are never
overwritten; use another output directory for a subsequent build.

## Completed result and checks

| Status | Physical pairs | Profile-specific CSV rows |
|---|---:|---:|
| modelled | 2664 | 5328 |
| no_path | 45 | 90 |
| snap_failed | 9 | 18 |
| Total | 2718 | 5436 |

16 focused tests passed, no failures/errors/skips in the final run (7.309 s).
They cover forward/reverse one-way and bidirectional partials, asymmetric loop
routes, same-segment direct travel, exact endpoints, disconnected nearest
components, grade crossings/ties, busway exclusion, snap cutoffs, valid zero,
zero/parallel graph edges, source-index preservation, finite output and exact
independent joins against normal P/B evaluations. Every physical row has the
same values in both profiles. No stress suite or full notebook was run.

Examples, to destination `destination:metro_exit:44` (identical for P and B):

| Origin | Result | Network km | Origin snap m | Destination snap m |
|---|---|---:|---:|---:|
| origin:grid:32639:1319:14916 | modelled | 11.477477738863 | 20.218599 | 35.673227 |
| origin:terminal:baku_international | no_path | null | 31.921044 | 35.673227 |
| origin:grid:32639:1334:14917 | snap_failed | null | 110.279901 | 35.673227 |

The terminal example is intentionally **not repaired by a different snap**. These
failures/approximations are explicit inputs for future consumers, not a finding
that no real car/taxi journey exists. No averaging or CO2 fallback is added here.

Build runtime: **7.815 s**, including source verification
and normal P/B evaluator ID checks.

CSV SHA-256: `588f3fb6597b5dc830c51ec9e6be3cf8930bc9881fc2c46b92e24b3727818a59`.

Manifest SHA-256: `85b8ee04caa8849131d77aef2d82c8c6776960120e5f68f789620e8299e16486`.

Filtered graph SHA-256: `fdb16bb5d94939727104952b2aa2ab1a91726e0ffdab7b5ad0ddeb307d520310`.

## Exact commands (from the OD worktree)

Initial build already executed successfully:

```powershell
$py = 'C:\Users\celal\OneDrive\Desktop\ayna-hackathon-2026\ayna-hackathon-2026\notebooks\citypilot-env\Scripts\python.exe'
$bundle = 'C:\Users\celal\OneDrive\Desktop\ayna-hackathon-2026\ayna-hackathon-2026\outputs\c4_model_alpha_20261017_155941_581069'
& $py -I -X utf8 tools/build_od_car_distances.py --artifact-dir $bundle --max-snap-m 100 --output-dir outputs/od_car_distances_v1
$env:CITYPILOT_TEST_BUNDLE = $bundle
$env:CITYPILOT_CAR_OUTPUT_DIR = (Resolve-Path 'outputs/od_car_distances_v1').Path
& $py -I -X utf8 -m unittest discover -s tests -p test_od_car_distances.py -v
```

Artifacts are local/ignored:
`outputs/od_car_distances_v1/od_car_distances.csv` and
`outputs/od_car_distances_v1/manifest.json`. Existing environment/dependencies were
reused in place, no installs or new environment. New source files only:
`src/citypilot/od_car_distances.py`, `tools/build_od_car_distances.py`,
`tests/test_od_car_distances.py`, `docs/OD_CAR_DISTANCES.md`.
The immutable model, existing notebooks/exporter/contracts/routing module, Ali
files and all other worktrees/PRs remain unchanged.

## Failure review

See `OD_CAR_DISTANCE_DIAGNOSTICS.md` for the independent forward-Dijkstra review
of all 45 no_path pairs and the 9 snap_failed pairs. No implementation mismatch
was confirmed; original CSV/manifest bytes and null distances remain unchanged.

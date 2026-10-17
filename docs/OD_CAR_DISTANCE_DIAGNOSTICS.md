# OD car-distance failure diagnosis

Independent review of the existing v1 supplement; **no production implementation
error confirmed**. All 45 physical no_path pairs (5 origins × 9 exits) remain
unreachable on the filtered graph. The snap_failed group is 1 origin × 9
exits, beyond the explicit 100 m threshold. CSV and manifest bytes are preserved;
no versioned replacement supplement is required because results did not change.
No road directions/permissions, links, snaps, immutable bundle, other worktrees
or PRs were changed. During this diagnostic review, no commit/push/merge or unrelated test suite was run.

## Independent method

`tools/audit_od_car_failures.py` does **not** import/call the production OD solver,
Snap helpers, reverse virtual-sink search or CarNetwork implementation. It uses a
separate heap-based **forward directed Dijkstra**, deriving origin/destination
partial-segment costs directly from saved fractions, lengths and direction flags.
Exact endpoints and same-segment directional paths are handled independently.
Forward distances cover the permitted departure endpoints and add each exit's
legal partial entry cost. Basic directed/zero-cost positive controls passed.
All 45 failure pairs were checked; no finite filtered path contradicted no_path.
Nearest selected segments/displacements were independently checked against all
saved eligible drive geometries, without replacing them.

Before = original immutable bus-oriented drive_distance_graph.npz with busways.
After = independently rebuilt graph from source road arcs excluding busway.
Both comparisons keep the **same original six snap positions**. Nearby projections
are diagnostic context only; they are not new supplement snaps or offered routes.

Component IDs below are the minimum original node ID in the component, followed
by original-node count. Weak component includes both edge endpoints. Strong
components are reported for allowed departure endpoint(s), not an invented
virtual snapped node. Reachable counts include those original departure nodes,
exclude the virtual snap point and use the same weighted partial costs.

## Every failed origin

Prefix `origin:grid:32639:` is omitted for grid IDs in the table.

| Origin | Original snap edge | F/R | Snap m | Weak before → after | Departure SCC before → after | Reachable nodes before → after | Destinations before → after |
|---|---|---|---:|---|---|---:|---:|
| 1327:14910 | `roadrow:74304:segment:0` | F/R | 50.254 | 51910 (2) → 51910 (2) | 51910 (2) → 51910 (2) | 2 → 2 | 0 → 0 |
| 1327:14915 | `roadrow:213642:segment:12` | F/R | 15.406 | 55786 (15) → 55786 (15) | 55786 (15) → 55786 (15) | 15 → 15 | 0 → 0 |
| 1327:14916 | `roadrow:76119:segment:11` | F only | 0.872 | 0 (96685) → 0 (96513) | 56049 (1) → 56049 (1) | 8 → 8 | 0 → 0 |
| 1333:14918 | `roadrow:336680:segment:1` | F/R | 46.158 | 0 (96685) → 0 (96513) | 0 (95275) → 56903 (14) | 95998 → 14 | 9 → 0 |
| 1334:14917* | `roadrow:637:segment:6` | F/R | 110.280 | 0 (96685) → 0 (96513) | 0 (95275) → 0 (95101) | 95998 → 95834 | 9 → 9 |
| origin:terminal:baku_international | `roadrow:76119:segment:11` | F only | 31.921 | 0 (96685) → 0 (96513) | 56049 (1) → 56049 (1) | 8 → 8 | 0 → 0 |

*The snap_failed row's reachability is hypothetical graph context **ignoring**
the exceeded 100 m cutoff, not an accepted snap/result. Its km remains empty.
Strong components for both source u/v endpoints and exact partial costs are in
the JSON; the table shows the allowed departure endpoint SCC(s).

## Causes and diagnostic alternatives

- **1327:14910 — disconnected source topology.** Snaps to a two-node isolated
  service-road component, before and after filtering. Nearby road
  `roadrow:107419:segment:8` is 59.568 m away and can reach the destinations,
  compared with the selected 50.254 m segment. No resnap was made.
- **1327:14915 — disconnected source topology.** Remains in the same 15-node
  island. Nearby `roadrow:240998:segment:0` is reachable at 15.908 m, but the
  selected isolated segment is closer at 15.406 m. The strict nearest policy
  deliberately does not select the reachable alternative.
- **1327:14916 — source directed dead-end.** Same one-way segment as the
  terminal. Only 8 original nodes are forward reachable with or without busways.
  Nearby reachable `roadrow:2765:segment:4` is 31.592 m away; selected road is
  0.872 m away. Neither road permissions nor snapping was changed.
- **1333:14918 — busway policy causes directed disconnection.** With the same
  snap, original source graph reaches all 9 exits (95,998 nodes); filtered graph
  reaches only a 14-node SCC and no exits, although weak connectivity remains.
  The SCC's only two original outbound arcs are busways:
  `roadrow:244678:segment:0` (56903→93559, 4.725940 m) and
  `roadrow:340257:segment:0` (111282→93568, 5.848066 m). Both are intentionally
  excluded by private-car approximation policy. An original-graph witness to
  exit 44 is 7,111.378 m and uses excluded busway edges; it is **not** a legal
  private-car result. Nearby reachable `roadrow:197874:segment:2` is 103.118 m
  away and also beyond the configured snap limit. Keep null.
- **1334:14917 — snap limit/source geometry, not busway removal.** Nearest drive
  segment is the same residential road before/after filtering, at 110.280 m.
  Its component can reach all exits if hypothetically accepted, but the explicit
  100 m assumption rejects it. No eligible segment within the threshold exists;
  no farther-road or straight-line fallback is used.

## Bakı terminal in detail

Original snap: `roadrow:76119:segment:11`, service road, u=56048, v=56049,
fraction **0.3505470663002963**, displacement **31.921043578633356 m**.
Saved permissions: **forward only**, reverse=false. The only legal departure
endpoint is **v=56049**, after **194.491363365873 m** of partial-segment travel;
returning to u would violate the stored direction. Both u and v have singleton
SCCs (56048 and 56049). The weak component is main network 0 (96,513 nodes after
filtering), so weak membership alone cannot establish directed accessibility.

Forward reachable set, unchanged with busways included/excluded:
`56049, 101171, 101172, 101173, 101174, 101175, 101176, 101177`.
Its directed chain terminates at node 101174, with no outgoing escape. All nine
exit distances remain infinite internally and null in the supplement. This is a
**saved source-direction/topology limitation**, not an implementation error or
busway-exclusion effect; it does not prove real-world taxi access is impossible.

Nearby `roadrow:74329:segment:8` at **57.946 m** lies in main strong component 0
(95,101 nodes) and can reach the destinations. It is farther than the selected
31.921 m road and was inspected only as context; no replacement snap/link or
pickup/dropoff access assumption was introduced. Other closer alternatives at
34.248 m and 54.713 m also cannot reach the exits under saved permissions.

## Reproduction and preserved artifacts

Executed from this OD worktree with the existing interpreter:

```powershell
$py = 'C:\Users\celal\OneDrive\Desktop\ayna-hackathon-2026\ayna-hackathon-2026\notebooks\citypilot-env\Scripts\python.exe'
& $py -I -X utf8 tools/audit_od_car_failures.py --artifact-dir 'C:\Users\celal\OneDrive\Desktop\ayna-hackathon-2026\ayna-hackathon-2026\outputs\c4_model_alpha_20261017_155941_581069' --supplement-dir outputs/od_car_distances_v1 --output-dir outputs/od_car_distance_diagnostics_v1
```

Independent results: `outputs/od_car_distance_diagnostics_v1/diagnostics.json`
(all original snaps, components, partial costs, fixed-snap forward distances,
original busway path witness, eight nearby distinct source roads per origin) and
`failed_origins.csv`. Outputs are exclusive-create; choose a different diagnostic
directory to rerun rather than overwriting preserved evidence.

Existing supplement counts remain 2664 modelled / 45 no_path / 9 snap_failed
physical pairs; profile rows remain 5328 / 90 / 18. No production source fix or
regression test was added because no implementation error was confirmed. The
existing directional test suite was not rerun; the independent audit is the new
verification. This leaves modelled, not observed or fully legally verified, car
distances and the prior access/turn/grade-policy limitations intact.

Preserved `manifest.json` SHA-256: `85b8ee04caa8849131d77aef2d82c8c6776960120e5f68f789620e8299e16486`.

Preserved `od_car_distances.csv` SHA-256: `588f3fb6597b5dc830c51ec9e6be3cf8930bc9881fc2c46b92e24b3727818a59`.

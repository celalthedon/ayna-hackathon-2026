# C5 phase 2: registered prebuilt bus services

Worktree `c5-activate-service`, branch `celal/c5-activate-service`, starts at the
actual phase-1 implementation `46f56a623d6e9456d96de49c8a865f941cd6d166`.
Read-only fetch found PR #7 merged into the C4 branch; main was `067ba83`.
No main adoption/merge, commit, push or Ali-owned edits are part of this work.
Main's looser catalog factor-map validator was not adopted: the phase-1 exact
existing-group mapping rule remains authoritative here.

The routing_export cell in `notebooks/01_network_routing.ipynb` is authoritative;
`src/citypilot/routing_engine.py` is generated only by the existing owner-scoped
exporter. All 67 analysis cells are preserved. The original notebook backup is
outside tracked source in `C:\Users\celal\OneDrive\Belgeler\ChatGPT\AYNA\c5_activation_work\01_network_routing.before_phase2.ipynb`.
No executed-cell recovery history was appended or executed. Full raw-data
notebook clean-run reproducibility remains pending.

## Registration and identity

The API stays `load_model(artifact_dir, config_dir)`. Without a registry it loads
the same baseline model/catalog. To opt in, supply an **external** config directory
containing unchanged copies of the bundle config files, plus:

```
config_dir/
  assumptions.yaml, limits.yaml, ...  # exact original bundle config bytes
  prebuilt_services/
    manifest.json
    assets.json
```

Do not write this directory into the immutable bundle. All 49 original payloads
and its manifest remain unchanged. Loading verifies every baseline payload and
config hash, supplement version, baseline bundle binding, supplement hash and
the assets.json SHA-256. There is no latest-bundle lookup or notebook execution.
Malformed JSON, duplicate JSON keys and non-finite numeric assets are rejected.

Manifest exact keys:

```json
{
  "asset_version": "prebuilt-services-1",
  "bundle_hash": "9457bfe95125b1d8bddb1be662ad6f0bbd1a00c0ac8f8abcc2fbecf872d53066",
  "files": {"assets.json": "<SHA-256 of actual UTF-8 assets.json bytes>"},
  "supplement_hash": "<identity hash below>"
}
```

Calculate supplement_hash as SHA-256 of UTF-8
`json.dumps(manifest_without_supplement_hash, sort_keys=True, separators=(',', ':'), allow_nan=False)`.
Only assets.json is listed in files. Its actual-byte hash binds every asset,
policy, geometry and provenance change. Model version gains
`+prebuilt@<supplement_hash>`, including when nothing is active. Requests must use
the loaded identity; stale identities are rejected. Graph cache keys include
that hash and sorted activated variant IDs, topology, speed and effective existing
headways. Runtime and machine paths do not enter identity. OD version/hash and
profile-aware OD IDs stay unchanged.

## Exact assets.json input for Ali

Top-level keys are `access_policy`, `stops`, `patterns`, `prebuilt_services`.
The checked-in complete runnable sample is
`tests/fixtures/prebuilt_services/{assets,manifest}.json`. It is synthetic,
outside production curated data, and must not be presented as researched M data.

- access_policy: `{"max_snap_m": 100.0, "excessive_snap": "unreachable"}`.
  The finite positive limit is an explicit access assumption, not an observation.
- stops: array of objects with `stop_id`, `coordinates` (WGS84 [lon,lat]),
  `provenance`; optional `location_kind` (bus_stop by default, or
  station_exit_proxy), and optionally **one** of `model_node_id` or `model_stop_id`.
  station_exit_proxy requires assumption provenance; it is explicitly not a verified
  bus-stop coordinate. The label is retained in access metadata, catalog source
  provenance and journey warnings; boarding/alighting legs retain location evidence.
  Existing node references must be walk-active physical access nodes and retain
  their real coordinates within 1e-5 m projection tolerance. Existing bus-stop
  references retain source coordinates and use the existing pedestrian access
  node. A source stop ID may be reused only with its own model_stop_id; aliases
  must be new stable IDs. Without either reference this is a new coordinate stop.
- patterns: array of objects with exact keys `pattern`, `segment_m`,
  `segment_geometry`. `pattern` is the shared ServicePattern object:
  `pattern_id`, `route_id`, `direction_id`, ordered `stop_ids`, `provenance`.
  Every consecutive directed pair needs one finite nonnegative segment_m value
  (metres) and one geometry entry. A reverse pattern is a separately supplied
  sequence; it is never inferred by the loader. A preparation step may explicitly
  assume reversed A stop order with assumption provenance, but must independently
  supply B's legal directed road path/distances, not blindly reverse A geometry.
  Missing segment_m is an error. No straight-line
  length or drive-shortest-path substitute is manufactured.
- segment_geometry entries: shared GeoJSON LineString, MultiLineString or Point,
  in WGS84, or explicit null when absent. No extra GeoJSON properties. Geometry
  and timing distances are independent supplied evidence. Gaps are retained.
- prebuilt_services: array of **exact shared ServiceGroup objects**. The service
  variant ID is `service_group_id`, used as the prebuilt_services mapping key and
  activate_service.target_id; it is never an existing service_groups member.
  Fields: `service_group_id`, `pattern_ids`, `base_headway_min` (design minutes),
  `full_cycle_km`, `speed_kmh`, `stops_per_cycle` (intermediate dwell count),
  `dwell_s` (seconds), `layover_min` (full-cycle resource minutes), `coverage`
  (`full`/`partial`), `field_status`, `provenance`.
- field_status must cover precisely pattern_ids, base_headway_min, full_cycle_km,
  speed_kmh, stops_per_cycle, dwell_s, layover_min, coverage. Evidence statuses
  are the shared typed vocabulary: observed, published, curated, modelled,
  assumption, unverified. Synthetic provenance requires assumption; synthetic
  service values may only be assumption/unverified, never promoted observations.
- Provenance exact required fields: `source_id`, `status`, `source`, `evidence`;
  optional `source_date` and `synthetic`. Duplicate/conflicting source IDs fail.

Runtime needs positive speed_kmh and base_headway_min and nonnegative dwell_s.
Full coverage requires all cycle fields. full_cycle_km must equal the sum of
all directed segment_m / 1000; ordered patterns must join end-to-start around
the declared cycle. stops_per_cycle must equal the sum of max(stop_count-2,0)
per directed pattern. Layover is nonnegative and is not added to passenger time.
Partial coverage keeps full_cycle_km, stops_per_cycle and layover_min null with
unverified field statuses. It remains partial and cannot acquire fabricated
resource cycle values. Feasibility/exclusions/resource calculations belong to Ali.

Minimal pattern record (illustrative synthetic IDs; full fixtures supply stops,
services and provenance):

```json
{
  "pattern": {
    "pattern_id": "SYN_SHUTTLE_OUT", "route_id": "SYN_SHUTTLE",
    "direction_id": "out", "stop_ids": ["SYN_INSAAT", "SYN_28MAY"],
    "provenance": {"source_id":"synthetic:sample","status":"assumption",
      "source":"synthetic fixture","evidence":"explicit design assumption","synthetic":true}
  },
  "segment_m": [6000.0], "segment_geometry": [null]
}
```

## Street access and passenger semantics

New coordinate stops must lie within the original physical-node metric bounds
(1e-6 m numerical roundoff allowance). Snap deterministically to the nearest
eligible nondegenerate physical road segment with pedestrian permission; exact
distance ties use the lexicographic edge ID. Never prefer a reachable component.
An excessive/no snap is registered as snap_failed and a
PREBUILT_STOP_UNREACHABLE warning, with no street connection. Access reports
are in model['prebuilt_stops']; actual coordinates are retained. A stop may
remain inaccessible from an origin even if another service stop can reach it.

Only active services attach stops. Subdivide their chosen road segments before
attaching assumed bidirectional pedestrian connectors at measured snap distance
and baseline walking speed. Preserve each original directed modal arc, its cost
and length proportion, and source grade/node topology. No endpoint shortcut or
cross-component link is added. Access provenance explicitly stays assumption
even if stop coordinates were observed. Exact endpoint snaps use existing nodes.

Saved OD endpoint access options and costs remain unchanged. A split on the
same grid-origin segment also gets legal directional partial access from the
saved snap, with the same initial walk/push displacement and cycling permissions.
The fixed OD set is neither resnapped nor expanded. B keeps separate carrying
states along split streets and cannot use pedestrian stop connectors/board buses
until its existing one-way parking transition; no bike retrieval is added.

Each activated service variant/directed pattern has its own arrival/departure
states even when patterns/stops are shared. Boarding goes to departure with
design headway / 2. Arrival can alight immediately at zero cost. Only staying
onboard at an intermediate stop pays dwell_s / 60 and reaches the next departure.
There is no second wait onboard; terminal passenger paths end, with no invented
through-run between directions. Full-cycle layover is resource metadata only.

speed_factor divides moving time for **all** bus rides, including activations;
walking, cycling, metro, dwell, parking and transfer costs stay fixed.
headway_factor_by_group must exactly cover existing SG_R2/SG_R14 when supplied;
prebuilt keys are rejected and design intervals stay unchanged.
set_service_headway still targets existing groups only and is the exact final
interval. Only mitigated requests may carry activations; closure is the declared
disrupted closure. Normal/disrupted can still use phase-1 stress without patches.
Identical duplicate patches canonicalize; conflicting patches fail. Equivalent
patch/mapping order yields identical hashes, states and costs. Fresh graphs start
from immutable baseline alternatives, preserving explicit zeros/minimum parallels.
Caches are bounded; catalog and baseline arrays are not mutated between requests.

Inspection uses the same graph/predecessors as evaluation. For prebuilt bus legs,
shared JourneyLeg.route_id is the **service variant ID**; pattern_id remains the
shared directed pattern ID. No new wire fields/dialect are introduced. Provenance
includes timing/service and geometry/pattern evidence. Missing ride geometry is
represented by disconnected degenerate endpoint pieces, not a connecting line.
Supplied gaps yield shared MultiLineString/partial metadata and GEOMETRY_GAPS.
Waiting uses Point. All public catalog/request/result/journey values round-trip
through strict shared v1 serializers/parsers. Ali must adopt variant route IDs
and the supplement-aware model identity; this convention is pending his review.

## Verification and runnable example

Use the existing Python, from the phase-2 worktree:

```powershell
$py = '..\ayna-hackathon-2026\notebooks\citypilot-env\Scripts\python.exe'
$env:CITYPILOT_TEST_BUNDLE = (Resolve-Path '..\ayna-hackathon-2026\outputs\c4_model_alpha_20261017_155941_581069').Path
& $py -I tools/export_notebooks.py --owner celal --notebook notebooks/01_network_routing.ipynb --check
& $py -I -X utf8 -m unittest discover -s tests -p test_activate_service.py -v
& $py -I -X utf8 -m unittest discover -s tests -p test_service_stress.py -v
& $py -I -X utf8 -m unittest discover -s tests -p test_baseline_adapters.py -v
& $py -I -X utf8 -m unittest discover -s tests -p test_routing.py -v
& $py -I -X utf8 -m unittest discover -s tests -p test_export.py -v
& $py -I -X utf8 tools/demo_activate_service.py --artifact-dir $env:CITYPILOT_TEST_BUNDLE
```

The demo creates an external temporary config, copies the explicit synthetic
registry, calls load/catalog/evaluate/journey without executing a notebook,
checks v1 round-trips, prints the full request and removes its temporary config.
Select `--service-id SYN_INS_28_9` for the 9-minute variant. Direct request after
load is `replace(baseline_request(model,'mitigated'), patches=(RoutingPatch(kind='activate_service', target_id='SYN_INS_28_6'),))`.

Both synthetic variants share the supplied two-stop out/back patterns, explicit
6,000 m per direction, schematic geometry and mean calibrated R2/R14 design
speed 24.309068600209667 km/h; dwell 25 s, cycle layover 10 min. These are design
assumptions. No real M1/M2/M3/M5/M6 route, measurement or reverse direction is claimed.
M9 is excluded from the current target assets.

Measured no-extra-stress SYN_INS_28_6: 734/1359/1879 at 40/45/50 min,
capped sum 125010.66997329824 min, first evaluation 2766.6 ms, load 2599.1 ms.
Grid origin origin:grid:32639:1328:14906 -> destination:metro_exit:44 takes
26.344718317273134 min (leg sum 26.34471831727313), with one 3-minute wait.
With existing R2/R14 headway factors 1.2/1.1, design wait stays 3 minutes:
707/1321/1855, capped sum 125816.63367314584 min, evaluation 2527.1 ms;
the same grid journey remains 26.344718317273134 min, terminal journey
39.913123463110296 min. Times are hardware/cache dependent and exclude model load.

All 10,872 saved baseline rows/statuses/capped values/sums match within 1e-6 min,
including with inactive registration. Counts remain P normal 2060/2339/2496,
P disrupted 636/1191/1697, B normal and disrupted 2406/2506/2511. Focused tests
cover zero/partial geometry, variant separation, directionality, dwell/alighting,
parking ownership, snapping/splitting/OD costs, repeated scenarios, invalid assets,
manifest corruption, changed-asset identity and clean-process/export parity.

## Remaining work

Current target services are **M1/M2/M3/M5/M6; exclude M9**. Per Ali's coordination,
M5 is 20 Yanvar (Velotrek entrance side) -> Gənclik NMM; M6 is Elmlər Akademiyası
(Hüseyn Cavid Parkı side) -> Gənclik NMM. These are scope notes, not curated
coordinates or researched street paths. Announcement images identify stop places
but supply no street paths; exact coordinates are being curated by Ali's teammate.

Real-service loading waits for curated assets. Ali must supply separately directed
stop sequences/coordinates, segment_m, geometry and honest provenance/statuses.
Future station-exit proxies use location_kind=station_exit_proxy and assumption
provenance/evidence explaining the proxy. A verified station location is not a
verified bus-stop location. No real coordinates or real M fixtures are added here.

Return B stop order may explicitly assume reversed A order with pattern provenance.
B needs an independently legal directed bus road path: do not blindly reverse A
road geometry. Missing segment distances will be derived in a separate preparation
step from the bus-eligible directed graph and labelled assumption. This loader
still rejects missing segment_m; it does not research/build missing paths or
manufacture reverse distances. Proposed 6/9-minute headways and mean R2/R14 speed
remain assumptions. Partial coverage is not optimization-ready full resource data.

activate_link and enable_parking remain explicitly unsupported. No compiler,
resource optimizer, frontend, CO2 arithmetic, candidate feasibility/exclusion or
real-M optimization readiness is implemented or inferred from synthetic success.


## Pre-coordination check receipt

57 distinct focused tests passed, zero failures/errors/skips: 9 shared-contract,
9 exporter, 9 baseline adapters, 11 phase-1 stress and 19 phase-2 activation tests.
The combined run (before the final opaque-ID/zero-access regressions were added)
ran 54 tests in 116.056 s. After those activation-only fixes, the complete final
19-test activation suite passed in 22.830 s; unchanged baseline/contracts/phase-1
checks were reused. Exporter --check and git diff --check passed after regeneration.
The exact commands above select these same five suites without unrelated tests.
Logs are preserved outside tracked source in the c5_activation_work directory.

Final activation measurements: with existing R2/R14 factors 1.2/1.1, SYN_INS_28_6
evaluation 1459.3 ms (707/1321/1855; capped sum 125816.63367314584). With both
variants, speed_factor=1.25, existing factors 1.2/1.1 and exact R2 final headway
7.2, P gives 1041/1647/2118, capped sum 118739.96439490473, 1184.9 ms; B gives
2406/2506/2511, capped sum 74031.93178043656, 2538.0 ms. Real terminal and grid
journey times/leg sums match evaluation for both profiles. The R2 wait is 3.6;
prebuilt waits remain 3 and 4.5. Measurements are synthetic-service scenarios,
not real M readiness or calibration claims, and are cache/hardware dependent.

All 49 original payloads and manifest.json were byte-compared with the prior
model handoff ZIP, not merely rehashed against a potentially changed manifest.
Manifest SHA-256: a372e5ade6df97dbf99228306ce79bc2e1ff3231bce41a5c32e29b29d4dcd3f9.
The notebook's 67 non-export cells compare equal to the saved original.
Other C4, C5 phase-1 and OD worktrees remain clean; the dirty primary checkout
was not edited. Phase-2 index is empty and all changes remain uncommitted.


## Coordination update verification

The assumption-only station_exit_proxy addition passed the complete affected
20-test activation suite in 31.528 s, zero failures/errors/skips. Command:
`python -I -X utf8 -m unittest discover -s tests -p test_activate_service.py -v`
using the same explicit project interpreter and CITYPILOT_TEST_BUNDLE above.
This rechecked all 10,872 inactive-registration OD rows/statuses/capped values
and counts, active P/B evaluation/journey parity, existing headway overrides,
proxy provenance, and clean-process/tagged-source parity. The 38 unchanged
contract/exporter/baseline/phase-1 checks above were reused, not rerun.
Exporter --check and git diff --check passed. All 67 analysis cells compare
equal to the separate before_proxy_labels notebook backup. Synthetic asset
files and production curated data were not changed by this coordination update.

Proxy fixture input uses location_kind="station_exit_proxy" with
provenance.status="assumption" and evidence explaining the substitution. The
loader rejects published/curated/observed/modelled/unverified proxy status and
unknown location_kind values; it never upgrades station-coordinate evidence to
verified bus-stop coordinates. The proxy label is hash-bound with the assets.


## Publication integration contract

The PR targets celal/c4-routing-contract-v1 at 5533ba8d4a4d9aa0e45558bb3867497dbed9ca01.
Main at 067ba836f161e69bbce68bccb2edee42b218bac4 still lacks phase 1. The advanced
integration branch must reach main first; Ali coordinates that integration.
Its only additional files versus this work's phase-1 parent are the six OD files;
shared routing/contracts/notebook/exporter inputs are identical, so no source
transfer or replacement of newer main files was necessary. This PR is phase-2 only.

For Ali's injected evaluator, explicitly construct the empty package with
baseline_request(model, 'disrupted', profile); closure_id is the declared closure.
Construct action requests from it with state='mitigated' and canonical patches.
The generic normal-reference helper default is unchanged; it is not the decision
empty-package convention. Empty mitigated remains equivalent to disrupted.

Unsupported well-formed capabilities raise shared
contracts.StressFactorsNotSupported, a NotImplementedError subclass. Supported
v1 stress remains executable. Malformed factors/mappings/types, unknown service
references, unknown JSON fields and invalid identities remain ContractError.
EvaluationResult fields are unchanged and reject candidate_ids; the request may
retain candidate_ids as trace metadata. The focused correction changes rejection
classification, not successful graph construction, cost arithmetic or OD results.

22 affected checks passed after the correction: two activation integration/input
tests, one phase-1 rejection test, one baseline rejection/schema test, nine shared
contract tests and nine exporter tests. Recorded expensive numeric verification
above was reused. Notebook was backed up again before this correction; exporter
--check and staged diff checks were run before publication. No Ali files were edited.

The exact synthetic assets.json payload has a scoped -text Git attribute so
Windows core.autocrlf cannot invalidate its recorded byte hash. No other paths
have altered line-ending rules. A focused fixture test and an actual checkout-index
copy verify the payload/manifest hash across Git checkout conversion.

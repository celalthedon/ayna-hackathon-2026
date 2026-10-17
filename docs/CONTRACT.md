# CityPilot shared contract 1.0

`src/citypilot/contracts.py` is the single shared wire definition, owned by Celal.
This implements `CONTRACT_v1_proposal.md` and the accompanying closure, geometry,
parking and retained-detail clarifications. The product scope remains
`CITYPILOT_FINAL_v4.md`; ownership/stages remain
`CITYPILOT_Balanced_Notebook_Roadmap.md`. Ali must replace his local stubs and
review the integration before a complete C4 handoff is claimed. No decision,
resource, search, frontend or CO2 implementation is included. C5 phase 1 now
implements existing-service headway changes and real bus stress; later activation
phases remain unsupported. See `C5_SERVICE_STRESS.md`.

## Serialization and identity

Frozen standard-library dataclasses expose `to_dict`, `to_json`, `from_dict`,
`from_json` and `content_hash`. Nested tuples/mappings are immutable; JSON uses
arrays/objects. Every versioned incoming payload must explicitly contain
`contract_version: "1.0"`. Legacy field names, extra fields, wrong types,
boolean-as-number values, duplicate JSON keys, NaN/Infinity and numeric overflow
are rejected. No legacy/v1 payload inference or fallback parser exists.
GeoJSON incoming objects must declare their `type`.

The baseline binds `model_version = artifact_version + "@" + bundle_hash` and
`od_set_id = od_version + "@" + od_hash`. This preserves the proposal's exact
request names while binding the immutable model, calibration, assumptions and
fixed OD selection. For this bundle these start `c4-alpha-1@9457bfe9…` and
`fixed_od_v1@10c1b58f…`; full values are in the runnable example output.
Runtime validates both identifiers and the declared closure against its model.

`config_hash` is SHA-256 of UTF-8 `RoutingRequest.to_json()`: sorted object keys,
compact separators, Unicode preserved, finite normalized numeric values. Patches
are sorted, exact duplicates collapsed, conflicting headways rejected; thresholds
and candidate IDs are sorted. Identity covers model/OD, state, profile, closure,
patches, stress, thresholds/primary/cap and candidate trace. Baseline assumptions
are bound by the bundle hash, not an unversioned machine default. Runtime and
machine paths never enter identity. `duration_ms` belongs to the result only.

All IDs are opaque nonempty trimmed strings. Use IDs, never labels, for joins.
Existing curated IDs (`SG_R2`, `SG_R14`, `2_A`, `2_B`, `14_A`, `14_B`, stop IDs,
parking IDs and the closure link ID) are retained without aliases to fabricated
services. Pattern stop sequences and source provenance remain inspectable.

## Request and declarative patches

`RoutingRequest`: `contract_version`, `model_version`, `od_set_id`,
`state` (normal/disrupted/mitigated), `closure_id`, `profile` (P/B), `patches`,
`speed_factor` (default 1), `headway_factor_by_group` (mapping or null),
`thresholds_min` (integer tuple, default 40/45/50), `primary_t_min` (default 45),
`cap_min` (default 120), `candidate_ids` (trace only). Thresholds are positive,
distinct, within C; the primary threshold must be reported. C is positive.
Normal requires null closure. Disrupted/mitigated require the model's declared
closure; this bundle declares `metro_link:green:670216816:5188836356`.

`RoutingPatch`: `kind`, `target_id`, `headway_min`. Kinds are
`set_service_headway`, `activate_service`, `activate_link`, `enable_parking`.
Only the first accepts a finite positive `headway_min`; all others require null.
Patches require mitigated state. Catalog validation checks target mappings and
P/B eligibility (P cannot activate cycling links or parking).

Implemented C5 phase-1 execution semantics:

- `speed_factor` is positive finite and divides only `bus_ride` moving time.
  Bus dwell/continuation, walking/pushing, cycling, metro, parking and transfers
  retain their exact baseline costs. No second boarding wait is added onboard.
- If supplied, `headway_factor_by_group` must **exactly cover** existing
  `service_groups`. Missing/unknown/prebuilt keys (including an empty mapping
  with this nonempty catalog) fail. Null means all factors equal 1. Each factor
  is positive finite; multiply the group's immutable baseline headway, then use
  half the effective headway for `bus_board`. Prebuilt activation is unsupported.
- An explicit `set_service_headway` is the exact final interval: it overrides
  the factored headway for that existing group. 7.2 stays 7.2, waits 3.6, and is
  never rounded or multiplied again. Conflicts fail; duplicate/order-equivalent
  patches canonicalize. Unknown existing-group patch IDs fail explicitly.
- Normal/disrupted permit stress but no intervention patches. Mitigated starts
  from disrupted topology and accepts only existing-group headway patches. Empty
  mitigated is numerically identical to disrupted with identical factors, while
  its public state/config_hash remain distinct.
- `activate_service`, `activate_link`, `enable_parking` still fail explicitly.
  Declaring these schema variants does not implement them. Candidate IDs remain
  trace information; no compiler is added. Assumption overrides have no v1 field.

Scenarios derive from immutable graphs/source alternatives on every cache miss;
no factor is compounded onto a prior scenario. A bounded two-entry physical-cost
cache excludes threshold/cap/trace metadata, while public config_hash covers the
entire canonical request. Mapping/patch ordering cannot alter the hash. Null
factors and explicit all-ones maps can have distinct wire hashes with equal costs.
All parallel alternatives are transformed before minimum-cost selection; explicit
zero edges are kept. Evaluation and journey share the same derived graph/arcs.
See `C5_SERVICE_STRESS.md` for evidence, runtime examples and remaining phases.

## Catalog and evidence

`ModelCatalog` carries version/OD identity and four separate mappings:
`service_groups` (existing only), `prebuilt_services` (activatable only), `links`,
`parking`. Existing/prebuilt service keys are disjoint; each key equals its
object ID. Extra preserved detail registries are `patterns`, `sources`,
`closure_ids`, `station_ids`, `exit_ids`, `stop_ids`. Sources and references are
validated. The baseline returns 2 existing groups, 4 patterns, 639 listed
parking sites, **zero prebuilt services and zero candidate links**.

`ServiceGroup` fields and units:

| Field | Meaning/unit |
|---|---|
| `service_group_id`, `pattern_ids` | Stable group and ordered-direction pattern references |
| `base_headway_min` | Existing base or prebuilt design interval, minutes, positive |
| `full_cycle_km` | Full-cycle geometry distance, **km**, not metres |
| `speed_kmh` | Calibrated moving speed, km/h, positive |
| `stops_per_cycle` | Integer intermediate dwell count; terminals excluded |
| `dwell_s` | Seconds per intermediate stop, not minutes |
| `layover_min` | Sum of terminal layovers over a full cycle, minutes |
| `coverage` | `full` or `partial`; cycle facts nullable only for partial |
| `field_status` | Typed evidence status for every value listed below |
| `provenance` | Source/evidence record, including original calibration notes |

`field_status` requires exactly `pattern_ids`, `base_headway_min`,
`full_cycle_km`, `speed_kmh`, `stops_per_cycle`, `dwell_s`, `layover_min`,
`coverage`. Evidence vocabulary is `observed`, `published`, `curated`,
`modelled`, `assumption`, `unverified`; missing numerical values require
`unverified`. These describe evidence, not readiness or runtime implementation.
Source geometry/stop counts/coverage map to curated; calibrated bus speed,
dwell and layover retain assumption. SG_R2 headway retains published;
SG_R14 headway retains assumption. Original source text/statuses stay in
provenance. No assumption is upgraded to observation. Synthetic evidence must
remain assumption. Old internal source token `assumed` explicitly maps to
`assumption`; it is not accepted in incoming v1 payloads.

`Link`: `link_id`, `kind` (walk/bike), positive `length_m` in metres,
`requires_construction` boolean, typed `status`, `provenance`.
`Parking`: `parking_id`, typed `status`, `baseline_enabled` boolean, `provenance`.
All source-listed baseline parking is enabled under the recorded operational
availability assumption. Future real candidate parking may be disabled; none
is fabricated here. `baseline_enabled` never asserts observed availability.

## OD mapping and evaluation

`get_od_table(model, profile)` returns `ODReference(od_id, origin_id,
destination_id, profile)` for the unchanged 302 × 9 pairs per profile, ordered
destination then origin as in the solver. The stable mapping is:

```python
payload = ["citypilot-od-v1", od_set_id, profile, origin_id, destination_id]
digest = sha256(json.dumps(payload, ensure_ascii=False,
                           separators=(",", ":")).encode("utf-8")).hexdigest()
od_id = "od:" + profile + ":" + digest
```

P/B have distinct OD IDs for the same physical pair. Normal/disrupted share IDs
within a profile. This adds an ID mapping; it does not resample/rebuild OD data.
Car-alternative distance, distance status/snap schema and CO2 defaults remain
unagreed and unimplemented. Unknown distance is never zero or multimodal journey
length. Ali must preserve the manual-input fallback pending a later agreement.

`ODResult`: `od_id`, `status`, `minutes`, `capped_minutes`.
`minutes` is actual physical elapsed minutes, null **iff** no_path. Status is
reachable iff actual time ≤ C; over_cap retains actual time > C. Capped minutes
is min(actual,C), or exactly C for no_path. No non-finite wire values are emitted.

`EvaluationResult`: version/model/OD identity, `state`, `profile`, `config_hash`,
`od_results`, `within_counts` (integer thresholds → integer counts),
`capped_time_sum` (minutes), `primary_t_min`, `cap_min`, `duration_ms`, `warnings`.
The shared validator checks every status/cap, every capped value, counts and sum.
Within T means nonnull actual minutes ≤ T. Ali reads routing's authoritative
counts and capped sum and uses `capped_minutes` for per-OD objective arithmetic;
never compare null physical minutes or convert no_path into a zero objective.
`validate_request()` checks identity/config/profile/state/threshold/cap echoes.

## Inspector

All results use shared `JourneyResult`; there is no BaselineJourneyResult dialect.
It retains identity/config, state/profile, `od_id`, origin/destination IDs, status,
cap, physical `total_min`, optional `generalised_cost_min`, geometry,
`geometry_metadata`, legs, provenance and warnings. Legs retain mode, semantic
from/to IDs, transit route/pattern/board/alight IDs and walk/wait/ride/transfer
minutes. Their sum must equal physical elapsed time within 1e-6 minutes.

Geometry uses GeoJSON WGS84 longitude/latitude `LineString`, `MultiLineString`
or `Point`; it is required for reachable/over_cap and null for no_path. Waiting
and zero-motion legs can be Points. Disconnected source pieces remain separate
MultiLineString pieces; no connecting segment is invented. Partial paths include
exact `GEOMETRY_GAPS` warning, `geometry_metadata.partial=true`, a validated
`gap_count` and explicit source/assumption provenance explaining omitted joins.
No_path has no geometry/legs/physical cost and nonpartial metadata.

Initial grid walk/push access and directed partial-edge travel are included.
Bus shapes use projected-stop substrings; timing keeps source ride distances.
B carries a bike initially, cannot board transit while carrying it, parks at
most once, never retrieves, and may finish carrying it at a street destination.
Route 14 stop 105 remains misaligned; grade/access/parking transitions are
assumed and metro entry/interchange geometry schematic, all disclosed in warnings.

## Examples and Ali's remaining integration

`docs/examples/synthetic_{request,catalog,evaluation,journey}.json` are explicitly
synthetic schema demonstrations, with invented IDs/data. Their mitigated/stress
request remains outside phase-1 runtime support because it contains activations. `tools/check_baseline.py`
provides a real baseline v1 request/result example against an explicit bundle;
see `C34_ADAPTERS.md` for commands and verified numerical parity.

Ali must remove his `decision_export` local catalog/request/result stubs and
import the shared types. Keep Candidate/Scenario/resource/decision-only types in
his module. Adapt mappings, patch target IDs, km/seconds units, nullable physical
minutes, authoritative capped objectives/counts, parking flags and per-field
evidence. Use the profile-aware OD table and validate model/OD/config hashes.
Per-profile objective gates remain Ali-owned. He should regenerate only his
module after his own notebook edits and test his resource/search fixtures against
these objects. No Ali-owned code was changed or its compatibility asserted here.

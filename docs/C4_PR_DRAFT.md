# C4: baseline routing adapters and shared contract v1

## Scope

Provide import-safe load/catalog/evaluate/journey baseline adapters from Celal's
tagged notebook cells, plus the single shared contract 1.0. Exported routing code
is generated only by the owner-scoped exporter. Existing notebook analysis is
preserved. This PR includes source, notebook, exporter/CLI, focused tests and
synthetic fixtures/documentation; the immutable runtime model is delivered as a
separate ZIP, not committed. No Ali-owned code is changed.

## Breaking contract changes Ali must adopt

- Replace local catalog/request/result stubs with imports from
  `citypilot.contracts`; explicitly parse version 1.0 (no legacy guessing).
- Requests use hash-bound `model_version` and `od_set_id`, `thresholds_min`,
  `primary_t_min`, typed `RoutingPatch(kind, target_id, headway_min)`, speed and
  existing-group headway factors. Normal closure is null; disrupted/mitigated
  require the declared closure. Candidate IDs are trace only.
- Separate `service_groups` (existing) from `prebuilt_services`; adopt
  `full_cycle_km`, `stops_per_cycle`, `dwell_s`, full-cycle `layover_min`, typed
  `field_status`, link `requires_construction`, and parking `baseline_enabled`.
  Baseline supplies 2 existing groups, 4 patterns, 639 enabled assumption-status
  parking sites, no fabricated prebuilt services or candidate links.
- Results use profile-aware stable `od_id`, nullable physical `minutes`, finite
  `capped_minutes`, `within_counts`, `capped_time_sum`, retained cap/runtime.
  No_path has null physical time and C objective; over_cap retains actual time.
  Read authoritative routing sums/counts and validate configuration identity.
- Inspector returns shared `JourneyResult`: reachable/over_cap geometry required,
  no_path null; Point/LineString/MultiLineString are supported. Disconnected source
  pieces carry GEOMETRY_GAPS plus partial metadata/provenance, never invented joins.
- Future headway factors affect existing groups only; prebuilt design headways
  stay unchanged. Speed factors affect all bus moving time; dwell stays fixed.
  Explicit set_service_headway is the exact final interval, never multiplied again.

## Validation already completed

Validated the final code tree on isolated branch `celal/c4-routing-contract-v1`,
based on origin/main `91d034ed4586b36ef4b96a2453d414eb382541d2`, using the existing Desktop
Python 3.13.1 interpreter. **26 focused tests passed**, 0 failures/errors:
contracts 9 (0.280 s), export 8 (0.362 s), baseline 9 (33.104 s), total 33.746 s.
Exporter --check passed. All **10,872 baseline OD rows/statuses**, capped values/
sums and original 40/45/50 counts match saved results within 1e-6 min. Prior
recorded maximum row error is 1.4210854715202004e-14 min and maximum capped-sum
error is 1.4551915228366852e-11 min; the final-tree regression rechecks the full
rows, not just rounded aggregates. Tests use the immutable bundle externally;
no model, ZIP or environment enters the commit.

Counts at 40/45/50: P normal 2060/2339/2496; P disrupted 636/1191/1697;
B normal and B disrupted 2406/2506/2511. Checks cover shared v1 round-trips,
terminal/grid journey and directed access/leg sums, all saved directed predecessor
routes, zero-cost and minimum-parallel edges, no_path/over_cap/zero-motion/gapped
geometry, corruption/rejected requests, clean-process load/catalog/evaluate/journey
and source/export parity. Evidence: docs/C34_PARITY.json. These are Celal's focused
checks, not a claim that Ali's consumer/resource/search integration has passed.
Ali's pytest/API suite was not run: existing environment lacks its API/test
dependencies and current main does not track generated decision_engine.py.
No Ali source or environment was changed to bypass this integration gap.

The only overlapping approved file was .gitignore: current main's rules,
including its data/curated exception, were preserved and C4 exclusions appended.
All other main/Ali files remain byte-identical. The original dirty checkout and
its staging area are preserved. Commit scope is exactly the 23 approved paths.

## Separate runtime dependency and remaining gaps

Ali needs **both this code PR and the separately transferred model ZIP**; the code
checkout alone does not contain the runtime model. See docs/C4_HANDOFF.md for its
exact hash, extraction layout, load/evaluate/journey commands and commit allowlist.
The ZIP contains the 49 manifest-listed immutable payloads plus manifest.json.

C5/mitigated/patch/stress execution remains explicitly unsupported. Schemas do
not imply runtime support. Full raw-data notebook clean-run reproducibility and
full executed-source recovery remain pending; recovery history includes failed/
debug cells and is preserved locally, not appended/executed/committed. Bus route
14 stop 105 alignment, assumed parking/access/grade transitions and schematic
metro geometry remain disclosed. Ali must replace his stubs, adapt consumers and
verify resource/search integration and per-profile gates. CO2/car-alternative
distance agreement is pending; no unknown-distance zero substitution was added.
No frontend/CO2 implementation or automatic merge is included. Ali coordinates merge.

Diff review: whitespace checks pass outside the supplied balanced roadmap. Its
four original Markdown two-space hard breaks are intentionally preserved; no
source-document whitespace was rewritten.

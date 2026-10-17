# C6 phase 1: routing HTTP adapter

Branch `codex/c6-routing-api`, isolated worktree `c6-routing-api`, based on main
`dcbdee238b41a66c215e2345f76da3a5726c7d1a` initially. Before publication the
unpublished branch was advanced to main
`d39de72096a8e0dc1b209ba2ac27b142d778947a` (#19 M supplement included).
The API implementation is byte-identical to the recorded 55-test version.
No routing algorithms, shared contracts, notebooks, exporter, decision/A6,
precompute, frontend or M production assets are changed.

## App composition and ownership

`citypilot.api:create_app` is the roadmap base FastAPI factory. Before C6 the
only app factory was `decision_dev.create_dev_app`, an explicitly synthetic
panel demo. It is preserved. The base factory accepts `app=existing_factory()`
and wraps its lifespan rather than launching another server or replacing its
routes. Tests exercise that exact dev factory, its static page, and decision
endpoints. Do not present its synthetic metrics as real routing decisions.

An existing app with /decision keeps those routes. Alternatively supply Ali's
`decision_backend` to `create_app(settings, decision_backend=backend)` to mount
his existing router once. Supplying a second backend to an app already serving
/decision fails; nested/lazy/hidden/mounted routes are checked too. Constructing
Ali's real backend/evaluator bridge and participating in his cache/precompute
policy remain A6 work. The default routing-only factory does not fabricate a
backend or automatically expose synthetic decision endpoints.

## Explicit Windows launch

Run one server process (one model and one admitted routing job). No reload,
multiple workers, implicit latest bundle or notebook execution:

```powershell
$repo = 'C:\Users\celal\OneDrive\Desktop\ayna-hackathon-2026\c6-routing-api'
$py = 'C:\Users\celal\OneDrive\Desktop\ayna-hackathon-2026\ayna-hackathon-2026\notebooks\citypilot-env\Scripts\python.exe'
$env:CITYPILOT_ARTIFACT_DIR = 'C:\Users\celal\OneDrive\Desktop\ayna-hackathon-2026\ayna-hackathon-2026\outputs\c4_model_alpha_20261017_155941_581069'
$env:CITYPILOT_CONFIG_DIR = 'C:\Users\celal\OneDrive\Desktop\ayna-hackathon-2026\ayna-hackathon-2026\outputs\c4_model_alpha_20261017_155941_581069\config'
& $py -I -B -m uvicorn citypilot.api:create_app --factory --app-dir "$repo\src" --host 127.0.0.1 --port 8000 --workers 1
```

Both environment values are mandatory absolute paths, or pass an explicit
`RoutingSettings(artifact_dir, config_dir)` in Python. Startup runs the existing
hash/reference/dimension-verifying `load_model` once on the routing worker.
Paths are never selected by HTTP requests. A load/verification failure leaves
readiness and routing at sanitized 503, with details only in server logs; it
does not erase existing decision routes or retry a corrupt model per request.
A corrected configuration requires a fresh app/process lifetime.

For supplements, use an explicit external config directory containing the
unchanged baseline config files plus the existing
`prebuilt_services/manifest.json` and hash-listed payloads. The engine performs
its existing bundle/config/supplement verification; readiness includes the
supplement hash and catalog keeps existing/prebuilt services separate. C6 does
not prepare or modify M assets. The immutable bundle is untouched.

## Baseline versus merged repository M configuration

The baseline config is `<artifact_dir>/config` (the exact Windows path above).
The merged repository-relative M config is `supplements/m_services_v1/config`.
Resolve that relative to **the code repository**, not the immutable bundle:

```powershell
# Alternative startup setting for a fresh M-supplement app lifetime:
$env:CITYPILOT_CONFIG_DIR = Join-Path $repo 'supplements\m_services_v1\config'
& $py -I -B -m uvicorn citypilot.api:create_app --factory --app-dir "$repo\src" --host 127.0.0.1 --port 8000 --workers 1
```

Do not run both commands on the same port or change a running app's environment
and expect a reload. Choose baseline OR M config before starting one process.
The artifact_dir is the same explicit immutable 49-payload C4 bundle in both.

- Bundle hash: `9457bfe95125b1d8bddb1be662ad6f0bbd1a00c0ac8f8abcc2fbecf872d53066`.
- Baseline `model_version`: `c4-alpha-1@9457bfe95125b1d8bddb1be662ad6f0bbd1a00c0ac8f8abcc2fbecf872d53066`; `supplement_hash=null`.
- M supplement hash: `42a560089d459f61667e6624425e04e03429d03f139605ef02124874d801835a`.
- M `model_version` is the exact baseline model_version plus
  `+prebuilt@42a560089d459f61667e6624425e04e03429d03f139605ef02124874d801835a`.
- OD version/hash/selection are identical. Model identity and therefore request
  config_hash differ even when no prebuilt service is activated. A request with
  the baseline model_version is rejected by the M app; use that app's readiness
  identities for every request and discard results from another model identity.

The M catalog adds ten constructed variants `SVC_M{1,2,3,5,6}_{A,B}` separately
from existing groups SG_R2/SG_R14. A/B here means 6/9-minute design variants,
not travel direction. Registration does not activate them. M provenance retains
curated/assumed stops, independently constructed directional road paths and
design assumptions; these are not verified official M operations. See
[M_SERVICE_SUPPLEMENT.md](M_SERVICE_SUPPLEMENT.md). C6 does not execute the
terminal's gate verification or connect Ali's unfinished real decision backend.

## Endpoints and exact wire contract

| Method | Path | Input / output |
|---|---|---|
| GET | /routing/ready | readiness and contract/model/OD/bundle/supplement identities, closure and OD dimensions |
| GET | /routing/catalog | exact shared ModelCatalog JSON |
| POST | /routing/evaluate_package | exact shared RoutingRequest JSON -> EvaluationResult JSON |
| POST | /routing/inspect_journey?origin_id=...&destination_id=... | same exact RoutingRequest body -> JourneyResult JSON |

JSON parsing uses `RoutingRequest.from_json` on original bytes (no Pydantic
coercion, legacy inference, wrapper object or duplicate-key loss). Results use
the shared `to_json` serializer and request/result validation. Journey IDs are
query parameters, not extra fields added to the shared request. Minutes and
GeoJSON/provenance/partial geometry semantics are unchanged. No-path nulls,
actual over-cap times and finite capped objectives remain the shared contract.

Copyable PowerShell requests after launch:

```powershell
$base = 'http://127.0.0.1:8000'
$ready = Invoke-RestMethod "$base/routing/ready"
$catalog = Invoke-RestMethod "$base/routing/catalog"
$body = @{
  contract_version = '1.0'; model_version = $ready.model_version
  od_set_id = $ready.od_set_id; state = 'disrupted'; profile = 'P'
  closure_id = $ready.closure_id; patches = @(); speed_factor = 1.0
  headway_factor_by_group = $null; thresholds_min = @(40,45,50)
  primary_t_min = 45; cap_min = 120.0; candidate_ids = @()
} | ConvertTo-Json -Depth 20
$result = Invoke-RestMethod "$base/routing/evaluate_package" -Method Post -ContentType 'application/json' -Body $body
$journey = Invoke-RestMethod "$base/routing/inspect_journey?origin_id=origin:terminal:baku_international&destination_id=destination:metro_exit:44" -Method Post -ContentType 'application/json' -Body $body
$result.within_counts
$journey.total_min
```

Normal uses `state='normal'` with null closure; action requests use mitigated
with declared closure and supported shared patches. Stress/headway/service
activation behavior is the existing engine's behavior. Link/parking activation
remains unavailable. No optimization, HTTP disk cache or multiprocessing is added.

## Bounded work and errors

All catalog work, model load, strict request parsing, calculation, validation
and result serialization run outside the async event loop. Exactly one routing
job is admitted; zero waiters are queued. Other routing jobs immediately get
429 with Retry-After: 1. Cancellation/disconnection does not release admission
before the underlying worker completes. Readiness remains responsive. Shutdown
waits for that worker. The gate covers /routing; Ali's future direct decision
evaluator integration must coordinate with it instead of bypassing it. Existing
engine-internal RAM caches are unchanged; C6 introduces no cache.

| Status | Stable error.code | Meaning |
|---|---|---|
| 422 | invalid_request | strict schema, version, model/OD/closure/ID or engine input validation |
| 413 | request_too_large | body exceeds 1 MiB |
| 415 | unsupported_media_type | application/json required |
| 429 | routing_busy | single routing slot occupied |
| 501 | not_available | shared StressFactorsNotSupported |
| 503 | model_not_ready | before startup, failed load or shutdown |
| 500 | internal_error | sanitized unexpected failure or invalid server result |

Error JSON is `{"error":{"code":"...","message":"..."}}`. Missing/invalid
journey query parameters use FastAPI's normal 422 detail response. Unexpected
exceptions and filesystem paths are not exposed to clients. No auth/CORS or
public deployment configuration is added in this local phase.

## Verification

Existing interpreter: Python 3.13.1. Requirements already contain all required
API dependencies; requirements.txt and pandas/numpy/scipy/shapely/pyproj pins
remain unchanged. Missing uvicorn==0.54.0 was explicitly reported, then installed
at that existing pin (with click==8.5.0); no existing packages were upgraded.
`pip check` passed and `python -I -B -m uvicorn --version` reported 0.54.0.
No persistent server was started.

Focused tests include startup load-once/failures/hash corruption, actual external
synthetic supplement loading, strict request/result/catalog round trips,
unsupported/invalid/500 distinctions, bounded worker admission, cancellation,
event-loop responsiveness, existing factory/lifespan/decision preservation,
clean import without notebook/scientific-load side effects and one real baseline
plus terminal journey. Existing decision API tests are included.

```powershell
$env:CITYPILOT_TEST_BUNDLE = $env:CITYPILOT_ARTIFACT_DIR
Set-Location $repo
& $py -I -B -c "import sys; from pathlib import Path; sys.path[:0]=[str(Path('src').resolve()),str(Path('tests').resolve())]; import pytest; raise SystemExit(pytest.main(['-q','-s','-p','no:cacheprovider','tests/test_api_routing.py','tests/test_api_decision.py']))"
```

Observed disrupted/P HTTP baseline: 2,718 rows; counts 636 / 1191 / 1697 at
40/45/50. Terminal to destination:metro_exit:44: 39.163123463110296 minutes,
70 legs; leg sum and matching evaluation OD agree within 1e-6 minutes. No full
10,872-row rerun was needed because engine/contracts/notebooks are unchanged.
Final run: **55 passed, 1 dependency deprecation warning in 24.14 s**. No skips or failures.
The warning is Starlette TestClient/httpx deprecation. `pip check` passed.


Publication checks reuse the 55-test evidence because the routing/API/decision
runtime sources and dependencies did not change during main advancement. New
integration coverage loads the checked-in M config through startup/readiness/
catalog, confirms the precise M/OD identities and all ten registered variants,
rejects a stale baseline model_version, and preserves the existing synthetic
/decision/state response. This is API composition evidence, not Ali real-A6
integration or another gate/parity/activation run. No package was installed for
publication; uvicorn==0.54.0 was already declared in root requirements.txt and
all five validated runtime pins remain unchanged.

Affected publication checks: **32 passed, 1 dependency deprecation warning in 8.56 s**.
`pip check` and exact installed/declaration matching for uvicorn plus the five
validated runtime dependencies passed. No new packages or persistent server.

# C4 review handoff

Prepared for authorized publication from isolated branch
`celal/c4-routing-contract-v1`, based on fetched origin/main
`91d034ed4586b36ef4b96a2453d414eb382541d2`. The dirty original Desktop checkout is preserved.
Only the 23 approved files enter this branch; current main's data/curated ignore
exception and all Ali-owned files are retained. Main is never pushed directly;
the PR targets main and Ali coordinates merge. Model ZIP delivery is separate.

## Proposed code scope

`C4_COMMIT_ALLOWLIST.txt` is the exact proposed repo-relative file list, including
the generated routing module so clean imports work without a notebook/export step.
The module's source of truth remains routing_export cells. `.gitignore` includes
the existing environment and exact raw ZIP exclusions. Its preceding rules stay.
The supplied product/roadmap documents retain their originals and define scope/
ownership. `C4_PR_DRAFT.md` contains the proposed title/body, not a published PR.

Explicitly excluded and preserved locally: contract_v1_work/ and other scratch
work, all backups, `.vscode/settings.json`, notebook environment, raw archives,
`notebooks/01_network_routing_recovery_20261017.ipynb`, all executed-cell recovery
history, model/output artifacts and the separate handoff ZIP. `config/limits.yaml`
and all Ali curated/notebook/module/fixture files are not part of this commit.
Historical C1_CHECKS.md and machine-specific ENVIRONMENT.md are also excluded from
this focused handoff. Untracked status is not authorization to include a file.
The parity report under docs is validation documentation, not a model artifact.

## Separate immutable bundle (required by Ali)

Ali needs the **code PR plus this separately transferred ZIP**, extracted under
the repository's `outputs/`. It is ignored by Git and must not enter the code PR.
The ZIP has a single top-level bundle directory. It contains exactly the 49
manifest-listed payload files and manifest.json (50 files total); all archived
payload SHA-256 values match the original manifest, manifest bytes are unchanged,
the bundle hash recomputes correctly and ZIP CRC/integrity checks pass.

```json
{
  "archive_absolute_path": "C:\\Users\\celal\\OneDrive\\Desktop\\ayna-hackathon-2026\\ayna-hackathon-2026\\outputs\\handoff\\c4_model_alpha_20261017_155941_581069.zip",
  "archive_size_bytes": 63491879,
  "archive_sha256": "d4a973fae1d8b004b4f553bf311c9ecdb68b66aa586fdf8962c9d90a0ec5218e",
  "bundle_hash": "9457bfe95125b1d8bddb1be662ad6f0bbd1a00c0ac8f8abcc2fbecf872d53066",
  "od_hash": "10c1b58f1d704cec25b11936da32c2c09bc995323e8a4083fd0bd46f50286ac8",
  "manifest_listed_payload_files": 49,
  "archive_members_including_manifest": 50,
  "all_manifest_payload_hashes_verified": true,
  "archive_crc_integrity_verified": true
}
```

Archive SHA-256 identifies ZIP bytes; bundle_hash identifies the manifest's file
hash map. They are different identities and must not be interchanged. Sharing a
local path does not transfer it to Ali: deliver this ZIP separately alongside the PR.

## Exact extraction and baseline commands

Run from the code checkout root in PowerShell, using the existing project Python:

```powershell
$py = '.\notebooks\citypilot-env\Scripts\python.exe'
# Set to the separately received ZIP; this preparation has not extracted it.
$archive = '.\outputs\handoff\c4_model_alpha_20261017_155941_581069.zip'
# Only when the bundle directory is absent; never overwrite a differing bundle.
if (-not (Test-Path -LiteralPath 'outputs/c4_model_alpha_20261017_155941_581069')) {
    Expand-Archive -LiteralPath $archive -DestinationPath '.\outputs'
}
$bundle = 'outputs/c4_model_alpha_20261017_155941_581069'
& $py -I -X utf8 tools/check_baseline.py --artifact-dir $bundle --config-dir "$bundle/config" --profile P --state normal
```

The CLI loads and verifies the explicit bundle, returns the catalog, constructs a
strict v1 baseline request, evaluates 2718 pairs, and inspects
`origin:terminal:baku_international` → `destination:metro_exit:44`.
Expected P normal counts: 2060/2339/2496; capped sum 94375.40594217333 min.
Journey physical time 34.91077163959099 min, 38 legs with matching sum; partial
MultiLineString with 7 source boundaries disclosed as gaps.

Direct API example (PowerShell, from the same root):

```powershell
@'
import sys
from pathlib import Path
sys.path.insert(0, str(Path("src").resolve()))
from citypilot.routing_engine import load_model, get_catalog, baseline_request, evaluate_package, inspect_journey
from citypilot.contracts import RoutingRequest, ModelCatalog, EvaluationResult, JourneyResult
b = Path("outputs/c4_model_alpha_20261017_155941_581069")
model = load_model(b, b / "config")
catalog = get_catalog(model)
request = baseline_request(model, state="normal", profile="P")
evaluation = evaluate_package(model, request)
journey = inspect_journey(model, request, "origin:terminal:baku_international", "destination:metro_exit:44")
for cls, value in ((RoutingRequest, request), (ModelCatalog, catalog), (EvaluationResult, evaluation), (JourneyResult, journey)):
    assert cls.from_json(value.to_json()) == value
print(request.to_json())
print(dict(evaluation.within_counts), evaluation.capped_time_sum)
print(journey.total_min, sum(leg.total_min for leg in journey.legs), journey.geometry.type)
'@ | & $py -I -X utf8 -
```

Checks rerun successfully on the isolated publication tree:

```powershell
& $py -I tools/export_notebooks.py --owner celal --notebook notebooks/01_network_routing.ipynb --check
$env:CITYPILOT_TEST_BUNDLE = (Resolve-Path $bundle).Path
foreach ($pattern in @('test_routing.py', 'test_export.py', 'test_baseline_adapters.py')) {
    & $py -I -X utf8 -m unittest discover -s tests -p $pattern -v
    if ($LASTEXITCODE -ne 0) { throw "Failed: $pattern" }
}
```

These commands use the validated project dependencies already installed here;
the environment itself is neither committed nor included in the model ZIP. Ali's
Python needs numpy/pandas/scipy/pyproj (shapely for the geometry audit). No new
environment or dependency install was performed for this handoff preparation.

## Validation reuse and remaining integration

Publication reran **26 focused tests**, all passed: contracts 9 (0.280 s),
exporter 8 (0.362 s), baseline 9 (33.104 s), total 33.746 s. Exporter --check
passed. Tests cover all 10,872 baseline rows/statuses and unchanged threshold
counts within 1e-6 min, clean-process adapter calls and notebook/source parity.
The immutable model was loaded by explicit absolute path from the original
checkout, not copied into or committed from this worktree. Original parity
evidence and a publication verification record are in docs/C34_PARITY.json.

Ali's pytest/API/resource/search suite was not run: this interpreter lacks the
current main API test dependencies (FastAPI/httpx/pytest/PyYAML/uvicorn), and
current main does not track generated decision_engine.py. No environment or
Ali-owned notebook/module was modified to work around that. Ali must perform his
own notebook export/migration and validate consumer integration. These focused
passes do not assert full repository or shared-consumer integration success.

All 67 non-export notebook cells and execution history were previously hash/
structure-checked as preserved; full raw-data notebook reproducibility remains
pending. No full source recovery or clean-run claim is made.

Ali must replace his local shared stubs with imports, migrate mappings/units/
patch names/null-time handling/OD mapping/config identity and verify his consumer,
resource/search and per-profile gate integration. C5/stress execution still rejects
unsupported requests; no frontend/CO2 work is included. Review the explicit schema
changes and unresolved source/geometry assumptions in CONTRACT.md/C4_PR_DRAFT.md.

# Running CITYPILOT from a clean checkout

[Back to README](../README.md). Use Windows PowerShell from the repository root. This documentation task did not install packages, launch a server or execute routing/precompute. Python 3.13.1 is the verified development version; native Linux/container execution is not asserted.

## Environment and external inputs

Preserve LF bytes: export parity and stored gate hashes are byte-sensitive.

```powershell
git clone -c core.autocrlf=false https://github.com/celalthedon/ayna-hackathon-2026.git
Set-Location ayna-hackathon-2026
py -3.13 -m venv .venv
$py = (Resolve-Path '.venv/Scripts/python.exe').Path
& $py -m pip install -r requirements.txt
```

Reuse a compatible existing interpreter when available. There is no `pip install .`/packaged CLI; use `--app-dir src`, `PYTHONPATH`, or tools' explicit `sys.path`. Do not upgrade individual scientific packages independently of the pins.

Obtain these separately from the maintainers; no public artifact downloader is supplied:

| Input | Provision |
|---|---|
| Immutable C4 ZIP | `c4_model_alpha_20261017_155941_581069.zip`, SHA-256 `d4a973fae1d8b004b4f553bf311c9ecdb68b66aa586fdf8962c9d90a0ec5218e`; extract its single top-level directory under `outputs/`. |
| Matching decision cache | Preserve `evaluations/`, `index_P_*.json`, `index_B_*.json`, supplied `stress_P_*.json`/`stress_B_*.json` and transfer manifests/checklists/provenance. |
| Car distances | Original `od_car_distances.csv` and its provenance/hash manifest; keep outside the bundle. |

Verify the ZIP before extraction into an absent directory; never overwrite a differing bundle. Runtime verifies the 49 payloads, not just the archive filename. [C4 handoff](C4_HANDOFF.md) records archive identity; its historical personal paths are not required.

After provisioning, set user-controlled paths:

```powershell
$bundle = (Resolve-Path 'outputs/c4_model_alpha_20261017_155941_581069').Path
$baselineConfig = (Resolve-Path (Join-Path $bundle 'config')).Path
$mConfig = (Resolve-Path 'supplements/m_services_v1/config').Path
# The following are needed only for full decision composition:
$cache = (Resolve-Path 'data/cache').Path
$car = (Resolve-Path 'outputs/od_car_distances_v1/od_car_distances.csv').Path
```

Baseline P/B routing needs only the bundle. M registration additionally needs the committed supplement config and changes model identity. The real decision catalog requires all ten M variants.

## Baseline-only routing and UI

```powershell
$env:CITYPILOT_ARTIFACT_DIR = $bundle
$env:CITYPILOT_CONFIG_DIR = $baselineConfig
& $py -I -B -X utf8 -m uvicorn citypilot.api:create_app --factory --app-dir src --host 127.0.0.1 --port 8000 --workers 1
```

Open `http://127.0.0.1:8000/` and `/routing/ready`. Ctrl+C stops this foreground server. Model-load failure leaves the UI available but readiness returns 503; a successful root response alone is insufficient.

The baseline API is useful, but committed map assets are **M-model-bound**: the map adapter rejects a baseline-only identity. For the integrated map, set `CITYPILOT_CONFIG_DIR=$mConfig` and use the same command. Registration activates no services. Neither configuration automatically enables `/decision`.

## Fully provisioned decision composition

The existing factory accepts `decision_backend=...`. There is no committed turnkey `demo_release` module or environment variable that constructs it. This composition uses the same factory and real backend, without another decision server.

### Exact gate bytes

Gate files are `config/objective/m_services_v1/objective_decision_{P,B}.json`. Each profile's baseline request hashes must match its loaded model. Stored stress also binds the **gate file bytes**; CRLF conversion can invalidate that binding without changing JSON meaning.

An LF-preserving clone can use that directory directly. For an existing CRLF checkout, create separate runtime copies from committed Git blobs without editing tracked files:

```powershell
$env:CITYPILOT_GATE_DIR = Join-Path $PWD 'outputs/runtime-gates/m_services_v1'
$gateMaterialisation = @'
import os, subprocess
from pathlib import Path
out = Path(os.environ['CITYPILOT_GATE_DIR'])
out.mkdir(parents=True, exist_ok=True)
for profile in ('P', 'B'):
    name = f'objective_decision_{profile}.json'
    data = subprocess.check_output(['git', 'cat-file', 'blob',
                                   f'HEAD:config/objective/m_services_v1/{name}'])
    target = out / name
    if target.exists() and target.read_bytes() != data:
        raise RuntimeError(f'Differing gate already exists: {name}')
    target.write_bytes(data)
'@
& $py -I -B -X utf8 -c $gateMaterialisation
```

Use the exact gates associated with the transferred cache. Never rewrite a stored key or substitute another model's gate to hide a mismatch.

### Launch

```powershell
$env:CITYPILOT_ARTIFACT_DIR = $bundle
$env:CITYPILOT_CONFIG_DIR = $mConfig
$env:CITYPILOT_DECISION_CACHE_DIR = $cache
$env:CITYPILOT_CAR_DISTANCES = $car
# Compare this to the supplier's manifest; hashing alone does not prove provenance.
$env:CITYPILOT_CAR_DISTANCES_SHA256 = (Get-FileHash -LiteralPath $car -Algorithm SHA256).Hash.ToLowerInvariant()
$env:OMP_NUM_THREADS = '1'
$env:OPENBLAS_NUM_THREADS = '1'
$env:MKL_NUM_THREADS = '1'
$env:NUMEXPR_NUM_THREADS = '1'
$launch = @'
import os, sys
from pathlib import Path
from dataclasses import replace
sys.path.insert(0, str(Path('src').resolve()))
import uvicorn
from citypilot.api import create_app
from citypilot.api_routing import RoutingSettings
from citypilot.decision_real import real_backend
from citypilot.routing_engine import load_model
settings = RoutingSettings.from_env()
model = load_model(settings.artifact_dir, settings.config_dir)
backend = real_backend(model, Path(os.environ['CITYPILOT_DECISION_CACHE_DIR']),
                       Path(os.environ['CITYPILOT_CAR_DISTANCES']),
                       os.environ['CITYPILOT_CAR_DISTANCES_SHA256'])
backend = replace(backend, objective_dirs=(Path(os.environ['CITYPILOT_GATE_DIR']),))
app = create_app(settings, decision_backend=backend)
uvicorn.run(app, host='127.0.0.1', port=8000, workers=1)
'@
& $py -I -B -X utf8 -c $launch
```

The extra environment names are consumed by this snippet, not by the routing-only factory. This public-interface composition loads the backend model and again loads routing at app startup: budget for duplicate memory. Main has no one-load backend-factory hook; the demo's local glue must not be assumed present.

Inspect `/citypilot-capabilities` (`decision_available=true`) and `/decision/state`: separate P/B objectives, expected index rows, dropped rows and comparison status. Router construction prepares complete-index AYNA comparisons without routing; absent indexes defer comparison. First requests can trigger broad priming/fresh evaluation when cache entries are missing. **No committed cache-only switch exists.** Provision the matching full cache before demonstrations.

Only after provisioning, a small request is:

```powershell
$body = @{profile='P'; B_h=30; K=2; N_a=3} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8000/decision/optimize' -ContentType 'application/json' -Body $body
```

Use the right-hand **Qərarlar** panel. Main's left resource warning and separate **Müqayisə** placeholders are not capability indicators. Keep the map/decision profiles aligned; recommendations do not automatically apply map patches. Recompute stress/CO₂ after changing package/profile.

## Preparation

Discover offline commands without running work:

```powershell
$env:PYTHONPATH = (Join-Path $PWD 'src')
& $py -B -X utf8 -m citypilot.precompute --help
& $py -I -B -X utf8 tools/build_m_services.py --help
& $py -I -B -X utf8 tools/build_od_car_distances.py --help
```

`--dry-run` is count-only but still loads/verifies the model. Precompute requires `--profile`, `--workers`, `--bundle` and `--config` (the last two accept routing environment defaults). `--index-only` reads cache; `--stress` can be expensive. Spawn workers each load a context; CPU count alone is not a safe memory budget. Synthetic benchmarks are not final M workload measurements.

## Contributing and lightweight checks

Use a dedicated branch and export only the edited owner. These checks are read-only:

```powershell
& $py -I -B -X utf8 tools/export_notebooks.py --owner celal --notebook notebooks/01_network_routing.ipynb --check
& $py -I -B -X utf8 tools/export_notebooks.py --owner ali --notebook notebooks/02_interventions_optimization.ipynb --check
git diff --check
```

For intentional source edits, omit `--check` for that owner, review the generated diff and run affected tests. In CRLF checkouts unchanged source can fail byte parity: distinguish newline conversion from source changes. Never hand-edit engines. Real-bundle test opt-ins use `CITYPILOT_TEST_BUNDLE`.

Full parity, geometry rebuilds and precompute are deliberate operations, not startup side effects. `tools/demo_smoke.py` starts a server, exercises decision routes and requires a separately generated results report; it is not a cheap health probe.

## Optional exposure

`cloudflared tunnel --no-autoupdate --url http://127.0.0.1:8000` can expose an already healthy local app. Quick Tunnels are temporary public access, not persistent hosting, authentication or production deployment. Keep the machine/network running; a restarted tunnel may get a new URL. Do not create a second server or replace a live demo merely to follow these instructions.

# CITYPILOT deployment packaging

Base main: `14bec5c` (#20 routing API and #21 M-bound gates merged).
Target: one Linux Docker image, Python 3.13, existing `requirements.txt` pins,
UID/GID 1000, `0.0.0.0:7860`, one Uvicorn application worker. Native numeric
thread pools are capped at one. The image runs the existing
`citypilot.api:create_app` factory unchanged. Startup verifies/loads routing
artifacts; it does not run notebooks, optimization, precompute or cache warming.

Only runtime Python modules, the M supplement config and original/M gate records
are copied. The Docker context denies everything else, including Git history,
environments, credentials, notebooks, raw archives, generated outputs, caches and
frontend files. No UI, A6, compiler, cache loader or API behavior is implemented
by this packaging. No remote deployment or account/resource changes are made.

## Actual settings and artifact locations

| Input | Image/rehearsal location | Actual application integration |
|---|---|---|
| Immutable C4 bundle | `/artifacts/c4-model`, external read-only mount | `CITYPILOT_ARTIFACT_DIR`; mandatory absolute path in existing RoutingSettings |
| M supplement config | `/app/supplements/m_services_v1/config`, included small files or replacement read-only mount | `CITYPILOT_CONFIG_DIR`; existing setting, overridable before startup |
| M gate directory | `/app/config/objective/m_services_v1`, included small records or replacement read-only mount | Existing `load_objective`/`DecisionProblem.objective_dir`; not read by routing startup |
| Verified precompute cache | `/artifacts/precompute`, reserved external read-only mount | No production cache loader or startup setting exists on this base; pending Ali's integration |

There is no implemented gate/cache environment variable. Container mount paths
are provisioning conventions, not invented application settings. Gate/cache
locations can be selected by the future injected backend's existing
`objective_dir`/`cache_dir` fields; the on-disk verified precompute format and its
reader are still required. Do not treat the old API EvaluationCache as a verified
production precompute loader.

`create_app(..., decision_backend=backend)` is the existing composition hook.
Ali must construct the real backend, select M gates, and provide the correct
normal/disrupted hashes separately for P/B. Current DecisionBackend has one
shared hash pair; changing the gate directory alone does not fix that gap.

## Immutable provisioning

The complete bundle is supplied externally, never copied from `outputs/` into
the image. Keep all 49 payloads and `manifest.json` byte-for-byte unchanged:

- Bundle hash: `9457bfe95125b1d8bddb1be662ad6f0bbd1a00c0ac8f8abcc2fbecf872d53066`.
- Bundle manifest SHA-256: `a372e5ade6df97dbf99228306ce79bc2e1ff3231bce41a5c32e29b29d4dcd3f9`.
- M supplement hash: `42a560089d459f61667e6624425e04e03429d03f139605ef02124874d801835a`.
- OD identity: `fixed_od_v1@10c1b58f1d704cec25b11936da32c2c09bc995323e8a4083fd0bd46f50286ac8`.

The existing loader verifies bundle/config/supplement hashes and references.
No manifest rewriting, automatic latest-bundle lookup, fallback model, runtime
artifact download or embedded credential is added. M registration changes
model_version to `c4-alpha-1@<bundle_hash>+prebuilt@<supplement_hash>` even with
no activation. Use the loaded identity; unchanged numerical results do not
authorize reuse of another model's gates/cache. See [M gates](M_SERVICE_GATES.md).

Tomorrow's verified cache can be mounted at `/artifacts/precompute` without
rebuilding or adding its contents to Git/image layers. That does not make it
consumable until Ali supplies its format/reader and backend wiring. Required
handoff inputs are: exact files/schema and manifest/checksums; bound model, OD,
supplement/catalog and contract identity; per-profile normal/disrupted hashes;
stress, canonical patch and threshold/cap coverage; and documented missing,
corrupt or incomplete-cache behavior. Budget-only changes should reuse identical
routing. No production cache format is assumed here.

## Local rehearsal

Run from this branch's repository root on a host with an already running Linux
Docker daemon. These commands do not upload anything. Use the explicit existing
bundle path on your machine; Docker never discovers it from a dirty checkout.

```powershell
docker build --platform linux/amd64 --tag citypilot:rehearsal .
if ($LASTEXITCODE -ne 0) { throw 'Image build failed' }
$bundle = (Resolve-Path '../ayna-hackathon-2026/outputs/c4_model_alpha_20261017_155941_581069').Path
$mConfig = (Resolve-Path 'supplements/m_services_v1/config').Path
docker run --detach --rm --name citypilot-rehearsal --publish 127.0.0.1:7860:7860 --read-only --tmpfs /tmp:rw,nosuid,size=128m --mount "type=bind,source=$bundle,target=/artifacts/c4-model,readonly" --mount "type=bind,source=$mConfig,target=/app/supplements/m_services_v1/config,readonly" citypilot:rehearsal
if ($LASTEXITCODE -ne 0) { throw 'Container start failed' }
try {
    # Bounded startup wait: at most 20 attempts, each with a 2-second HTTP timeout.
    $ready = $null
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        try { $ready = Invoke-RestMethod 'http://127.0.0.1:7860/routing/ready' -TimeoutSec 2; break }
        catch { Start-Sleep -Milliseconds 500 }
    }
    if ($null -eq $ready) { throw 'Routing did not become ready' }
    $ready | ConvertTo-Json -Depth 5
    if ($ready.supplement_hash -ne '42a560089d459f61667e6624425e04e03429d03f139605ef02124874d801835a') { throw 'Wrong supplement loaded' }
    Invoke-RestMethod 'http://127.0.0.1:7860/routing/catalog' -TimeoutSec 5 | Out-Null
    docker inspect --format '{{.Config.User}} {{json .Config.Cmd}}' citypilot-rehearsal
} finally { docker stop --time 10 citypilot-rehearsal }
```

Only readiness/catalog are queried; do not call optimize/precompute as a smoke
check. The `finally` stops the named test container and `--rm` removes it.
Missing bundle/corrupt hashes must leave routing readiness at 503, never a
fabricated 200. An explicitly missing/relative startup setting fails factory
configuration. Check logs locally for details; HTTP errors are sanitized.

Once a verified cache directory is supplied, add this read-only mount to the
same `docker run` command, before the image name (do not run it as a second
container). The source must already exist; no empty cache is fabricated:

```powershell
$verifiedCache = (Resolve-Path '<explicit local verified cache directory>').Path
# Additional argument: --mount "type=bind,source=$verifiedCache,target=/artifacts/precompute,readonly"
```

Gate overrides similarly mount to `/app/config/objective/m_services_v1`; use
only M-bound records. For an alternative absolute container location, pass that
path to the future backend explicitly. Routing config can already move via
`-e CITYPILOT_CONFIG_DIR=/your/mounted/config` plus the corresponding mount.
The built-in default bundle/config env values remain explicit absolute paths.

## Hugging Face configuration and approved UI

Root README metadata sets `sdk: docker` and `app_port: 7860`; Dockerfile is at
the root. The image runs as UID 1000, matching the documented Docker Space
runtime. See [official Docker Spaces documentation](https://huggingface.co/docs/hub/spaces-sdks-docker).

No Space or remote artifact store is created/configured by this PR. Before any
later publication, approve the Space visibility and code/artifact release scope.
Do not mirror the private GitHub repository or history into a Space. A reviewed
release staging tree needs only README, Dockerfile, .dockerignore, requirements,
runtime Python sources and the exact small config/gate files admitted by the
Docker allowlist. Dockerignore restricts build context; it does not hide files
uploaded to a public Space repository. Do not embed tokens in Dockerfile, build
arguments, image layers or Git. Any future private artifact authentication must
use an approved provider's secret/mount mechanism after its source is defined.

Remote provisioning is **not defined yet**: supply the approved artifact source,
immutable revision, access method, manifest/checksum and read-only mount/staging
path for the bundle and verified cache. A host bind mount in the local example
is not an HF mount recipe. No URLs, buckets, paid resources, persistent disks or
runtime download commands are assumed. Standard Space disk is ephemeral; a
restart must be provisioned from the chosen immutable source again unless
explicit storage is approved. See [official storage documentation](https://huggingface.co/docs/hub/spaces-storage).

No frontend assets are copied or changed; `/` is currently 404. The existing
factory's `app=`/`decision_backend=` hooks allow the eventual approved UI and
real backend to compose with routing. No extra hook is needed in this PR. The
UI owner can add a reviewed static mount or app factory later; root static
mounts must follow API route registration so `/routing` and `/decision` are not
shadowed. The image command can be overridden to that approved factory; there
is no implemented UI-directory environment setting or placeholder UI.

## Release checklist and current validation

- [ ] Linux image build and bounded container smoke pass; inspect UID 1000,
  one worker, bind/port, health/readiness and graceful stop.
- [ ] Select and verify remote bundle/cache provisioning and read permissions.
  On missing/corrupt bundle, readiness is 503; after correction restart the app.
- [ ] Confirm M model/OD/supplement identities and ten catalog variants.
- [ ] Ali supplies the verified cache manifest/reader and real backend with
  profile-specific gate hashes. Missing cache must have an explicit decision
  unavailable response; never silently run optimization/precompute as fallback.
- [ ] Test corrupt, incomplete and wrong-identity cache rejection once its
  format/consumer exists; test budget-only reuse without routing recomputation.
- [ ] Until backend wiring exists, `/decision/*` is 404 even if cache is mounted;
  missing cache does not prevent routing readiness. Routing health is not full
  application readiness. Once wired, test the backend's actual unavailable/miss
  behavior; no new error behavior is claimed here.
- [ ] Existing routing errors remain 413 oversized body, 415 wrong content type,
  422 invalid/stale request, 429 busy with Retry-After, 501 unsupported capability,
  and 503 model not ready. Verify internal errors do not expose paths or tokens.
- [ ] Integrate only the approved UI and verify same-origin API behavior;
  no redesign or frontend publication is part of this package.

Docker client 27.5.1 is present on the preparation host, but the Linux daemon
pipe is absent even outside the sandbox. **Image build and container execution
are unverified**; Docker was not installed, started or reconfigured. Python base
image resolution and Linux wheel availability therefore also remain unverified.
After a successful build, record the image digest; the Python 3.13 base tag alone
is not a reproducible image digest. No package changes were made to the existing
project environment, and no full routing suite or benchmark is needed here.

Static checks passed for the Docker command, Python version/pins, explicit COPY
inputs, context allowlist and HF metadata. The context admits 17 explicit files;
the seven-module runtime subset imports independently. All ten pinned versions
match the existing interpreter and `pip check` reports no broken requirements.
Native FastAPI lifecycle smoke with
the existing Python 3.13.1 passed: real M readiness 200, ten catalog variants,
UI/decision 404, wrong media 415, invalid request 422 and sanitized missing-bundle
readiness 503. Routing evaluation was replaced with a failure guard during the
smoke, proving startup/readiness did not invoke it. This checks the unchanged
factory on the host; it is not evidence of a Linux image build or container run.

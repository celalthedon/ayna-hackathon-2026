# CITYPILOT frontend integration checkpoint

Updated: 2026-10-18, final presentation and publication handoff. The user reports a successful outside-sandbox launch, HTTP 200 for startup/UI assets, readiness, catalog, OD metadata, evaluation and journey, and approves the rendered UI. This is user-reported live evidence; sandbox Python/browser restrictions below remain separate. Decision integration and deployment remain pending.

## Final presentation changes and publication status

- Display only: consecutive compatible walking legs share one `Piyada` summary. Every original leg, physical time, geometry gap and playback/seek ID remains unchanged. Layer changes, discontinuities, waiting and incompatible semantic endpoints prevent grouping. Summary highlighting maps each original leg ID to its row.
- Raw transport mode and time-component labels now use Azerbaijani. Authored UI text passes strict UTF-8 decoding and a mojibake/replacement-character regression check. Static text responses explicitly use `charset=utf-8`, independent of Windows/Linux MIME defaults. Original approved HTML, map/model data and vendor versions are preserved.
- Final Node command: `node --test tests/ui-adapter.test.mjs tests/ui-map.test.mjs tests/ui-presentation.test.mjs`: **20 passed, 0 failed, 0 skipped** (636 ms reported). Includes summary immutability, timing/seek mapping, gap/wait/layer boundaries, zero-time access, translated modes and UTF-8 validation. Syntax checks also passed.
- Focused Python command attempted once: `& 'C:\Users\celal\OneDrive\Desktop\ayna-hackathon-2026\ayna-hackathon-2026\notebooks\citypilot-env\Scripts\python.exe' -I -B -X utf8 -m pytest tests/test_ui_integration.py tests/test_api_routing.py -q`. Blocked before collection: base `Python313\python.exe` access denied. No Python pass claimed.
- User's running server was not restarted, stopped or replaced. Refresh the browser for static presentation changes; the explicit response-header change takes effect on the next ordinary app restart.
- Fetch attempted once in this finalization: Git cannot obtain credentials (`wincredman` / missing TTY); `gh auth status` reports the token invalid. GitHub connector also reports repository inaccessible (404). Latest remote main cannot be verified. Cached `origin/main` is still `14bec5cc61524ea23bbf68f0698eea14cece4d61`.
- Compared with that inspected main: Ali's decision modules/panels, routing engine/contracts, M supplement assets, gates/configuration, notebooks and `requirements.txt` dependency pins are unchanged. A prospective check against newer remote changes remains blocked by authentication. No main checkout or other worktree was changed.
- Integration commit created: `8a5093b5a2a5a849a1aa77e698946792649a1f23` (`Integrate approved CITYPILOT UI with fixed-OD routing and journey playback`). Audited 29 intended files; no original model outputs, environments, backups or unrelated changes included. A subsequent documentation-only commit records this handoff.
- Actual push attempted once: `git push -u origin HEAD:refs/heads/codex/citypilot-ui-integration`. It failed before publication because Git cannot obtain GitHub credentials (`wincredman`, missing `/dev/tty`, `could not read Username`). No retries with unchanged authentication. **No PR was opened and no PR URL exists.** The connector cannot access this repository either, and a PR cannot reference an unpublished head. PR description is prepared in `docs/UI_INTEGRATION_PR.md`.

- Worktree: `C:\Users\celal\OneDrive\Desktop\ayna-hackathon-2026\citypilot-ui-integration`
- Branch: `codex/citypilot-ui-integration`
- Inspected cached main: `14bec5cc61524ea23bbf68f0698eea14cece4d61` (PR #21).
- `git fetch origin main` attempted; unavailable Git credentials (wincredman/TTY). No credential/system changes made. Remote freshness remains unverified.
- Inspected all worktrees. No existing frontend worktree or UI_INTEGRATION_PROGRESS.md found. Main and review checkouts contain unfinished work and are preserved. No overlapping active frontend edits observed; process command-line inspection is denied by the environment. Never edit Ali's decision/A6/cache/precompute implementation.
- No applicable AGENTS.md found in workspace ancestry or repository.
- Approved original: `C:\Users\celal\OneDrive\Desktop\CITYPILOT.html`; preserve it byte-for-byte.
- Immutable bundle: `C:\Users\celal\OneDrive\Desktop\ayna-hackathon-2026\ayna-hackathon-2026\outputs\c4_model_alpha_20261017_155941_581069`, expected hash `9457bfe95125b1d8bddb1be662ad6f0bbd1a00c0ac8f8abcc2fbecf872d53066`.
- M config: this worktree's `supplements/m_services_v1/config`. P/B gates exist separately in `config/objective/m_services_v1/`; preserve separate P/B gate hash pairs.

## Milestones

1. Implemented; static checks pass, runtime checks blocked: approved HTML shell/CSS/Three.js 0.180.0 extracted into local files; same existing FastAPI app serves `/` and `/citypilot`, assets under `/citypilot-assets`. Existing app root/static/decision routes preserved, including roots in lazy included routers.
2. Derived and hash-checked: all 49 bundle payloads, M payload verified. Display copy has 15 stations, 53 saved street access exits, 13 metro links, R2/R14 and all five M lines, 130 stops, 639 parking, 302 origins, 9 destinations. Local OSM ZIP supplies 41,506 road parts, 17,925 buildings and 4,575 green polygons within the existing model bounds. Roads/bus routes are batched. Unknown heights/depths remain illustrative.
3. Implemented; user reports readiness/catalog/OD metadata/evaluation/journey HTTP 200 outside the sandbox. `/routing/od_metadata` exposes allowlisted loaded OD identities and configured headway choices; real API adapter uses exact contract fields. One queued client worker, debounce, outdated result handling, 429/manual retry, exclusive M variants. No engine/contracts/decision algorithms changed.
4. Implemented; adapter unit tests pass: physical JourneyResult component times, stationary waiting/dwell, explicit gap pauses (including sub-centimetre gaps), disable empty/stale playback, reduced motion, hidden-tab render pause and batched SVG fallback. Actual browser playback checks remain blocked.
5. Boundary preserved: supplied decision panel files unchanged. Mount once/unmount with existing signature only when server declares a decision backend; default UI marks decisions pending. No optimizer/precompute is invoked on load.
6. User reports successful live app rendering/API responses and approves the UI. Final Node suite: 20 passes. Agent-run Python/API suites and browser automation remain blocked by sandbox executable permissions; no screenshots were captured and final presentation changes have unit/static verification only. Detailed playback/control/M-activation browser assertions are not claimed as completed.

## Checks and blockers

- Worktree/status inspection completed. Used per-command `git -c safe.directory=...` for read-only status where ownership differs; no global configuration changes.
- Fetch blocked as above. Existing Python environment must be used; no package installation.
- Supplied interpreter launcher fails: `did not find executable at 'C:\Users\celal\AppData\Local\Programs\Python\Python313\python.exe': Access is denied.` Base executable access is denied too. No alternate environment, installation or permission changes attempted. Python API tests and live app launch are blocked in this sandbox.
- `node --check` passes for application, routing adapter and routing UI modules. Map generation completed and verified bundle payload hashes.
- Completed final run: `node --test tests/ui-adapter.test.mjs tests/ui-map.test.mjs`: **15 passed, 0 failed, 0 skipped** (502 ms reported), including actual bundle/approved-original hash preservation, all pilot IDs, projection agreement with saved destination exits, exact request/closure semantics, exclusive variants, physical playback sum/wait/dwell/gaps, late evaluation/journey rejection, evaluation reuse for OD-only changes, debounce, bounded requests, no 429 retry storms, and local asset/DOM references. Earlier 13/14-test runs were superseded only after relevant fixes/additions.
- Added `tests/test_ui_integration.py` for allowlisted read-only OD metadata, actual configured headway choices, same-app/static/decision preservation, unready and sanitized failures. Attempted with existing API suites: Python launch blocked before test collection (same interpreter access denial). No Python tests claimed passed.
- Browser smoke attempts failed before a usable page: Chrome GPU subprocess exits with `-1073741790` (access denied), then `GPU process isn't usable. Goodbye.` A CPU/2D attempt fails likewise. No sandbox/security flags were disabled and no unrelated processes were terminated. No further identical retries are useful. Actual failure log: `docs/ui-verification/browser-blocked.json`. This is **failure evidence**, not browser success. The CDP check creates no application server and does not fabricate routing results.
- `git diff --check` and final `node --check` of application, routing UI, and browser check pass. Existing `docs/C34_PARITY.json` / `docs/C34_ADAPTERS.md` remain the engine parity evidence; engine code was not changed, so optimization/precompute/benchmarks/full parity were not rerun.
- Approved HTML SHA-256: `eb4db9aef28fd2bf463bba0ec1ecd4aa9e6baa64bc961b5ed58634d5f402382b`.

## Commands

Exact Windows launch (explicit bundle and M config inside script):

```powershell
& 'C:\Users\celal\OneDrive\Desktop\ayna-hackathon-2026\citypilot-ui-integration\tools\launch_citypilot.ps1'
```

Browser URL: `http://127.0.0.1:8000/` (also `/citypilot`). Existing interpreter:
`C:\Users\celal\OneDrive\Desktop\ayna-hackathon-2026\ayna-hackathon-2026\notebooks\citypilot-env\Scripts\python.exe`.

Completed Node test command (PowerShell, worktree root):

```powershell
$env:CITYPILOT_TEST_BUNDLE = 'C:\Users\celal\OneDrive\Desktop\ayna-hackathon-2026\ayna-hackathon-2026\outputs\c4_model_alpha_20261017_155941_581069'
$env:CITYPILOT_APPROVED_HTML = 'C:\Users\celal\OneDrive\Desktop\CITYPILOT.html'
node --test tests/ui-adapter.test.mjs tests/ui-map.test.mjs tests/ui-presentation.test.mjs
```

Attempted Python verification (blocked before collection):

```powershell
& 'C:\Users\celal\OneDrive\Desktop\ayna-hackathon-2026\ayna-hackathon-2026\notebooks\citypilot-env\Scripts\python.exe' -I -B -X utf8 -m pytest tests/test_ui_integration.py tests/test_api_routing.py tests/test_api_decision.py -q
```

Browser verification command, **after** the launch script works in a session with Chrome executable access:

```powershell
Set-Location 'C:\Users\celal\OneDrive\Desktop\ayna-hackathon-2026\citypilot-ui-integration'
$env:CITYPILOT_LIVE_URL = 'http://127.0.0.1:8000/'
Remove-Item Env:CITYPILOT_BROWSER_2D_ONLY -ErrorAction SilentlyContinue
node tools/check_ui_browser.mjs --live
```

The `--live` check requires the actual same-origin app, verifies 302/9 selectors, P baseline counts, one catalogued M1 6-minute activation, physical total/leg sum/timeline duration, and playback controls. It captures theme/layer/laptop/fallback screenshots under `docs/ui-verification/` only if the checks actually run. It has **not** run successfully here. Without `--live`, the optional diagnostic uses intercepted static assets and an explicit 503; that mode is never real API evidence.

## Data, transform and API details

- `GET /routing/od_metadata` is the only new routing metadata endpoint. It returns the loaded identity, allowlisted saved origins/destinations, coordinates for display, configured headway choices/status, and explicitly unavailable interventions. It uses the existing one-job admission gate. It exposes no filesystem paths, matrices or full model. Existing four routing endpoints/contracts are unchanged.
- `GET /citypilot-capabilities` reports whether the existing app supplies a decision route. `/decision` behavior and source files are unchanged. The frontend mounts `window.CityPilotDecision.mount(element, {getAppState, onStateChange})` once and calls `unmount()` on cleanup. Default launch has no real decision backend; those sections stay pending.
- Background streets, buildings and green polygons derive from the local `azerbaijan-261016-free.shp.zip` (SHA-256 `ae7251147a0870554fa4060ad8acfaa8dfe33c24913acfc4cde9a4536da0e4d6`). No OSM fetch/download or source edit occurred. R2/R14 display uses the complete saved curated route geometry, clipped to the existing model bounds; M display uses the hash-bound supplement's independently constructed directions. Journey display uses returned passenger journey geometry.
- One transform across every layer: WGS84 longitude/latitude to local metres, `x = R * radians(lon-lon0) * cos(radians(lat0))`, `z = -R * radians(lat-lat0)`, `R=6378137`, center `[49.839794816480946,40.43763522949542]`. Static display copies round to 1 cm; dynamic journey projection does not round. `y` alone changes in exploded views. Routing distances, connectivity, selection, physical time and calibration do not use this display transform.
- Existing model metric bounds are `[392642.83355094807,4465166.698351468,410584.4876389144,4488800.093155404]` in EPSG:32639. Their enclosing WGS84 display box is `[49.73221380815476,40.330137967230556,49.94737582480714,40.545132491760285]`. This is the existing model extent, not a new all-Baku routing model. Saved metric exit/parking coordinates use a display-only inverse UTM conversion, checked against saved destination coordinates within 5 mm.
- Building height is uniformly illustrative 12 m; metro depths/layer offsets are illustrative. Station/metro review status and M assumptions are retained. Existing source-listed baseline parking remains available through unchanged B engine rules. New link/parking activation stays unavailable.
- Geometry is batched: one combined roads mesh, merged parks/buildings, one mesh per bus route, batched point layers; fallback uses disjoint SVG subpaths. Gaps are never bridged. Multipart leg animation distributes the supplied physical time across known pieces by length, discloses interpolation and pauses at gaps. No dwell is invented.
- Final map copy: 9,485,077 bytes. Source bundle, manifests, curated data, supplements, gates, notebook/engine/contract/decision implementations are unchanged.

Rebuild display data only if its source inputs intentionally change (not needed for launch):

```powershell
node tools/build_ui_map.mjs 'C:\Users\celal\OneDrive\Desktop\ayna-hackathon-2026\ayna-hackathon-2026\outputs\c4_model_alpha_20261017_155941_581069' supplements/m_services_v1/config 'C:\Users\celal\OneDrive\Desktop\ayna-hackathon-2026\ayna-hackathon-2026\data\raw\azerbaijan-261016-free.shp.zip' web/static/citypilot/pilot-map.json
```

## Reproducible demo sequence after unblocking runtime

1. Run the launch script once. Open `http://127.0.0.1:8000/`. Readiness must identify the exact supplied bundle and M supplement `42a560089d459f61667e6624425e04e03429d03f139605ef02124874d801835a`. The frontend rejects mismatched map/model/OD identities.
2. In the journey panel, verify 302 saved origins and 9 individual destination exits. Default is terminal `origin:terminal:baku_international` to `destination:metro_exit:44`. Map clicks inspect objects only. Use the camera reset for full pilot and adjacent focus button for the closure.
3. Select P / Normal, then P / Disrupted; wait for current results each time. Compare all 40/45/50 columns with historical baseline evidence below. Threshold buttons select an already computed count; they do not resubmit an evaluation.
4. Open Actions, choose M1 / 6 min. The UI selects Mitigated and sends the actual catalogued service ID. Select 9 min and confirm 6 min is deselected. A/B service suffixes are 6/9-minute variants; both travel-direction patterns belong to each variant. R2 / 6 min and R14 / 4.5 min are the saved configured reductions (7.5/5 min baselines); no optimizer action IDs or resource feasibility are invented.
5. Inspect physical component times/provenance. Timeline duration in seconds must equal `JourneyResult.total_min * 60`, which must equal the physical leg sum. Play, pause, seek, restart and change speed. At a geometry gap, the marker disappears and playback pauses until explicitly continued. Waiting/dwell stays stationary.
6. Select B and inspect a new fixed OD journey. The unchanged model starts carrying a bike, allows riding/pushing, permits one parking transition, forbids retrieval and transit boarding with the bike. Visit Normal/Disrupted once each if verifying B counts is required.
7. Toggle dark/light, Surface/Underground/Both, 2D/3D, OD/exits/parking/M layers, and the results drawer at laptop size. `?renderer=2d` exercises fallback; it explicitly lacks exploded layers. Hidden tabs pause render advancement; reduced motion disables camera tweening/damping and steps marker display.
8. Change selections during a request: old journey/playback clears immediately, stale results are labelled, late responses cannot replace current state. Errors/busy responses provide manual Retry; there are no automatic retries. Decision sections remain pending under the default launch. Do not present them as a finished optimizer.

Known baseline counts from unchanged engine parity evidence (not newly executed API results):

| Profile/scenario | 40 | 45 | 50 |
|---|---:|---:|---:|
| P normal | 2060 | 2339 | 2496 |
| P disrupted | 636 | 1191 | 1697 |
| B normal/disrupted | 2406 | 2506 | 2511 |

## Changed files and remaining dependencies

- Existing files edited: `src/citypilot/api.py` (UI composition), `src/citypilot/api_routing.py` (read-only OD endpoint).
- New backend files: `src/citypilot/ui.py`, `src/citypilot/ui_metadata.py`.
- Frontend: `web/citypilot.html`, `web/static/citypilot/{app.js,style.css,playback.js,routing-adapter.js,routing-ui.js,journey-presentation.js,pilot-map.json}`, three local notices/start files, and four unchanged-extraction vendor modules under `vendor/`. Approved external HTML and existing `web/static/decision/*` are preserved.
- Tools/tests: `tools/{build_ui_map.mjs,check_ui_browser.mjs,launch_citypilot.ps1}`, `tests/{test_ui_integration.py,ui-adapter.test.mjs,ui-map.test.mjs,ui-presentation.test.mjs}`; this checkpoint, prepared PR description and browser failure evidence.
- Ali's real decision backend/A6/catalog/cache/precompute integration is still a separate dependency. Default app serves real routing without fabricating optimizer outputs. Existing M objective files require separate profile-bound normal/disrupted hash pairs: P starts `29fe7ca2...` / `f20fdaa6...`; B starts `8e907b92...` / `82ab6245...`. A single shared pair cannot validate both. No gate check or decision implementation was weakened.
- Deployment packaging must include `web/` and these new source files and retain explicit bundle/M configuration. Docker/HF use same-origin relative URLs; neither image build nor cloud deployment was performed or verified. Remote main freshness remains unverified because fetch authentication failed.
- Earlier overnight work did not commit or publish. The user now explicitly authorizes an intended-scope commit, dedicated-branch push and focused PR. No merge/deployment, resets, stash, optimization/precompute runs, package installation/upgrades, server restarts or unrelated process termination are authorized or performed.

## Next concrete action

After publication authentication is available, fetch current main and inspect the prospective integration against it without changing Ali's files/assets/pins, then push the saved dedicated branch and open the prepared PR. Run focused Python tests from a session with access to the existing interpreter. Preserve the user's running server; do not start a second instance. Remaining manual checks can use the existing server after a normal browser refresh. Real decision backend/A6/cache/precompute integration remains separate. Do not repeat completed Node checks without relevant changes.

Publication commands after credentials are restored (run from this worktree; do not merge or deploy):

```powershell
git fetch origin main
git diff --name-status origin/main...HEAD
# Inspect newer main and any API composition overlap before publishing.
git push -u origin HEAD:refs/heads/codex/citypilot-ui-integration
gh pr create --repo celalthedon/ayna-hackathon-2026 --base main --head codex/citypilot-ui-integration --title 'Integrate approved CITYPILOT UI with real routing and journey simulation' --body-file docs/UI_INTEGRATION_PR.md
```

No merge/deployment performed. Remote freshness, successful branch publication/PR creation, focused Python execution, final browser presentation inspection and real decision integration remain distinct pending items.

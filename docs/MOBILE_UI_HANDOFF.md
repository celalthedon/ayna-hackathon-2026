# CITYPILOT mobile layout handoff

2026-10-18. Task checkout: `C:\Users\celal\OneDrive\Desktop\ayna-hackathon-2026\citypilot-mobile`, branch `codex/citypilot-mobile`.

Fresh main inspected before publication: `f74ed5cc457cd9435f89301e6e7d1d1829a0df8f`.
The currently served checkout remains `C:\Users\celal\OneDrive\Desktop\ayna-hackathon-2026\citypilot-ui-integration`, branch `codex/citypilot-od-labels`, commit `db51bc254bde5544a6993f0a8d361c9c313d9b29`. It was clean when inspected. Its existing HTML/app.js match the corresponding files on inspected main. No served files, running server or Cloudflare tunnel were changed.

## Changes

- Phone layout removes the rail/sidebar width, retains a compact brand/results/menu header and keeps the map visible by default.
- A single nonmodal, scrollable bottom sheet hosts the existing journey inputs (first), selected-leg details, playback speed/restart, results, menu, disruption details or legend. Hidden sections are inert; Escape collapses the sheet and restores trigger focus. Existing nodes/listeners/selection values are moved and restored, never duplicated.
- Existing scenario, level and projection controls remain available. Menu contains layer/action access, theme, info and camera focus/reset. Attribution remains visible between sheet and playback.
- Compact playback retains play/pause, native seek range and elapsed/total time. The exact corrupted caption source is corrected to `Səfər simulyasiyası`.
- Separate responsive CSS covers portrait and phone landscape, dynamic viewport height, safe-area insets and 44px targets. The canvas stays mounted; existing ResizeObserver/camera resize handling is reused. Panel scrolling is outside the map event surface.
- Desktop style.css and original approved HTML file remain unchanged. No APIs, contracts, routing/decision algorithms, dependency pins, vendor libraries, map/model assets or calibration were modified.

Changed files: `web/citypilot.html`, `web/static/citypilot/app.js`, new `mobile-layout.js` and `mobile.css` in that directory; `tests/ui-presentation.test.mjs`; `tools/check_ui_browser.mjs` and new `tools/mobile_browser_checks.mjs`; this handoff.

## Actual verification

From the task checkout:

```powershell
node --test tests/ui-adapter.test.mjs tests/ui-map.test.mjs tests/ui-presentation.test.mjs tests/od-labels.test.mjs
node tools/check_ui_browser.mjs --mobile
git diff --check
```

Node: **27 tests, 25 passed, 0 failed, 2 skipped**. The two existing optional map/bundle checks skip because `CITYPILOT_TEST_BUNDLE` was not set; immutable data was not changed or rebuilt. Existing adapter checks cover physical timing, gaps, seek/speed/restart, stale responses and OD identifiers. Added a regression for the exact Azerbaijani caption and extended UTF-8 validation to mobile files.

Chrome **155.0.8059.80**: passed at **360×800, 390×844, 430×932, 844×390** and restoration to **1366×900**. Checks cover full-width map, no page/sheet horizontal overflow, primary controls inside viewport with 44px targets, scenario/layer and sheet/playback separation, exclusive panels, focus restoration, themes, level/projection controls, original desktop DOM positions and renderer sizing. Direct phone loading with reduced-motion preference and 2D fallback passed; panel wheel scrolling leaves the map camera unchanged, map wheel zoom works outside the panel and sheet changes preserve the zoomed camera. Zero JS exceptions, console errors or file URL dependencies. Initial browser checks found undersized projection targets (fixed); subsequent harness selector/scroll handling was corrected. Final run passed.

Visually inspected portrait collapsed/expanded, landscape collapsed/results and restored desktop screenshots. The browser uses an isolated temporary Chrome profile and CDP interception of **this task checkout's static files**. Routing ready deliberately returns 503: this is layout/interaction evidence, **not a new live-routing/playback end-to-end test**. Existing server/API/tunnel are never contacted by this check. Touch sizing is checked in Chrome emulation; physical iOS/Android safe-area and touch behavior still require a device check.

Final local artifacts (ignored, not committed): `outputs/mobile-verification/browser-smoke.json` and 14 PNGs, including `mobile-360-collapsed.png`, `mobile-390-journey.png`, `mobile-844-results.png`, `mobile-390-2d-reduced-motion.png`, `desktop-restored.png`.

`git diff --check` passed. Fresh-main comparison is frontend/tests/browser-check/docs only. No Python suite, engine parity, precompute, optimization or benchmarks were run. Existing decision backend/gate integration remains unchanged and pending where reported by the current application; this PR supplies no decision results.

## Make the existing demo serve the fix

**Publishing this PR does not update the running checkout. A hard refresh alone cannot load absent files.** No commands in this section were executed by the agent.

After reviewing the PR, an operator can copy only its four runtime frontend files into the currently served checkout. FastAPI's existing FileResponse/StaticFiles read these files from disk, so this requires no server/tunnel restart. This deliberately leaves four frontend changes in the served checkout; it does not merge any branch. Preserve or reconcile any intervening local edits first. Run the following in PowerShell after the PR branch is present at the task path:

```powershell
$task = 'C:\Users\celal\OneDrive\Desktop\ayna-hackathon-2026\citypilot-mobile'
$served = 'C:\Users\celal\OneDrive\Desktop\ayna-hackathon-2026\citypilot-ui-integration'
$dirty = git -C $served status --porcelain
if ($LASTEXITCODE -ne 0 -or $dirty) { throw 'Served checkout is not clean; preserve/reconcile its changes before copying.' }
$files = @('web/citypilot.html','web/static/citypilot/app.js','web/static/citypilot/mobile-layout.js','web/static/citypilot/mobile.css')
$backup = Join-Path $env:TEMP ('citypilot-before-mobile-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
foreach ($file in $files) {
    $source = Join-Path $task $file
    if (-not (Test-Path -LiteralPath $source)) { throw "Missing PR file: $source" }
}
foreach ($file in $files) {
    $target = Join-Path $served $file
    if (Test-Path -LiteralPath $target) {
        $saved = Join-Path $backup $file
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $saved) | Out-Null
        Copy-Item -LiteralPath $target -Destination $saved
    }
}
foreach ($file in $files) {
    Copy-Item -LiteralPath (Join-Path $task $file) -Destination (Join-Path $served $file)
}
Write-Output "Previous served frontend files saved in $backup"
```

Then reload `http://127.0.0.1:8000/` with browser cache disabled/hard refresh. On the phone reopen the **existing** Cloudflare URL and reload without cached assets. Confirm a full-width map, `Menyu`, collapsed `Səfər və nəticələr`, correct playback caption, scenario and layer modes, results and journey selection. Expand the sheet for speed, restart and selected-leg/gap details. Test a real journey's play/pause/seek and P/B scenarios on the existing demo, then rotate the device and check desktop again. No tunnel URL or process change is needed.

Remaining limitations: no physical-device check in this session; no live API journey playback check against the newly copied files until an operator applies them; existing decision integration/deployment dependencies remain outside this PR. Next concrete action: review the PR, apply only the four frontend files using the controlled copy above, and perform the real-phone/real-journey check.

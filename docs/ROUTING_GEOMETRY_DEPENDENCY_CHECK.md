# Reported geometry and psutil failures

Inspected fresh main: `d807938591403d80860c964fcb1a13ffe88f6557`.
Branch: `codex/routing-geometry-dependencies`, isolated sibling worktree
`routing-geometry-dependencies`. No applicable AGENTS.md was found in the
repository or its ancestry. Existing dirty checkouts, Ali's work and the running
demo/server/tunnel were preserved. PRs #24–#27 were not inspected or changed.

## Actual environment

Existing interpreter: `../ayna-hackathon-2026/notebooks/citypilot-env/Scripts/python.exe`.
No packages were installed, upgraded or removed.

| Component | Installed version |
|---|---|
| Python | 3.13.1, Windows x64 |
| Shapely | 2.2.0 |
| GEOS | 3.14.1 |
| pyproj | 3.8.0 |
| NumPy | 2.5.4 |
| pandas | 3.0.6 |
| SciPy | 1.18.1 |
| pytest | 9.1.1 |
| psutil | 7.2.2 |

Shapely matches the existing `shapely==2.2.0` requirement exactly. Importing
psutil succeeds, and its module version matches installed distribution metadata.

## Coordinate discrepancy: not reproduced; no speculative geometry fix

Before any changes, the exact
`RealBundleTests::test_projected_stop_shapes_use_saved_substrings` passed with
the explicitly selected immutable C4 bundle. It does not hardcode 31 or 32: it
compares every regenerated ride's geometry type and ordered coordinates against
the saved geometry with `rtol=0, atol=1e-8`.

A read-only audit of all 146 rides compared the saved geometry, actual
`projected_bus_geometries` output, and source-route substrings selected by saved
`projected_chainage_m` values. Results:

- Same ride IDs and geometry types; **zero coordinate-count mismatches**.
- Regenerated versus saved ordered coordinates and endpoints: maximum error
  **0 degrees**. Metric Frechet distance and length difference: **0 m**.
- Source-chainage substring versus regenerated geometry after the WGS84/metric
  round trip: maximum directed discrete Frechet distance
  `2.794573987870897e-09 m`, endpoint error `1.870812694540736e-09 m`, and
  length error `4.921957952319644e-09 m`.
- Saved shapes include one 31-coordinate ride, two 32-coordinate rides and
  58 consecutive duplicate vertices across the dataset. All are reproduced
  exactly here; these observations do not identify the reported failing ride.

Thus there is no demonstrated production geometry error or incorrect assertion
in this environment. The report supplied no failing ride ID or dependency
version dump, so a different Shapely/GEOS environment cannot be asserted as its
cause. Reproduction requires that missing evidence. The actual verified
environment is listed above instead of guessing another version or changing a
count/tolerance. Original checks retain ordered direction, endpoints and path
shape; the audit additionally checked metric lengths.

No geometry assertion, routing notebook, generated module, bundle payload,
manifest, model asset or calibration changed. Exporter `--check` was not required
because neither export source nor generated code changed.

## psutil: confirmed dependency declaration omission

The benchmark CLI's `run()` and `MemoryMonitor.sample()` import psutil without an
optional fallback; the existing memory-guard test does too. This is required by
that tool at runtime, although the routing API does not import it at startup.
The populated notebook environment hid the missing root requirement.

Before the fix, an assertion that the installed `psutil==7.2.2` pin was present
in `requirements.txt` failed. A missing-module ImportError itself is not
reproduced here: psutil is already installed. The fix adds the exact verified
pin and a regression checking the required package/import version is declared.

## Verification

From this worktree in PowerShell:

```powershell
$projectPython = '..\ayna-hackathon-2026\notebooks\citypilot-env\Scripts\python.exe'
$env:CITYPILOT_TEST_BUNDLE = (Resolve-Path '..\ayna-hackathon-2026\outputs\c4_model_alpha_20261017_155941_581069').Path
& $projectPython -I -B -X utf8 -m pytest tests/test_baseline_adapters.py::RealBundleTests::test_projected_stop_shapes_use_saved_substrings tests/test_routing_benchmark.py -v
& $projectPython -I -B -m pip check
git diff --check
```

- Initial geometry reproduction: **1 passed, 8 deselected**, 150 existing
  `shapely.ops.transform` deprecation warnings, 1.30 s.
- After the dependency fix: **12 passed, 0 failed, 0 skipped**, 150 existing
  transform deprecation warnings, 2.05 s.
- `pip check`: **No broken requirements found.**
- `git diff --check`: passed.

The benchmark tests use tiny stubs/mocks and a low-memory guard; they do not run
real graph benchmarks or routing process pools. No full routing suite,
precompute, server restart, tunnel change, merge or deployment was performed.

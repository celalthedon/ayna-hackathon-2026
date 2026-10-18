# Saved bus-substring test comparison

Task worktree: `../saved-substring-comparison`, branch
`codex/saved-substring-comparison`, based on fresh main
`f74ed5cc457cd9435f89301e6e7d1d1829a0df8f` (2026-10-18).

Only tests and this note change. Production routing/notebook exports, geometry,
bundle, saved artifacts, dependency pins, other worktrees and the live
server/tunnel remain untouched.

## Evidence and reproduction limits

The report was initially absent from fresh main and all local worktrees. After
it was requested, the user supplied
`C:\Users\celal\OneDrive\Desktop\shapely_for_celal.zip`. Read its Markdown report,
`diag.py` source and `shapely_diff_linux.geojson`; no archive code was executed
and no source/archive artifacts were modified. Archive SHA-256:
`e69cca94d2b4704328ecf8a3241c1dde0ae58e4c314e43659bf478c2e6b4a64e`.
GeoJSON SHA-256:
`c75ba51f283ae2e5a04ece7c27f56f6d79b5c02cb7748c648f19d824b1c49bf8`.

The report describes 23/146 vertex-count differences: 11 near-duplicate start
vertices around 1e-9 m and 12 additional interior-vertex cases. All **23**
paired saved geometries exactly match this immutable bundle's coordinate
arrays. All 23 Linux-generated pairs fail the old array assertion and pass the
new directed metric assertion when checked here on Windows. The complete
small `bus_ride:14_B:16` pair is retained as a regression in test source.

There is a provenance discrepancy: the Markdown lists Python **3.13.13**, Linux
6.19.10 Fedora/glibc 2.41; GeoJSON metadata lists Python **3.13.16**, Linux
6.18.44-fc-v139/glibc 2.39. Both identify Shapely 2.2.0 and GEOS 3.14.1. The
report also lists pyproj 3.8.0, PROJ 9.8.1 and NumPy 2.5.4. Do not silently
conflate these environments or attribute a specific libm/PROJ root cause.

This validates supplied Linux output against the immutable saved data **on
Windows**, not a fresh execution of the test on Linux. That execution remains
pending; this PR must not be described as having passed a cross-platform test
run. Resolve the report/GeoJSON provenance when performing the Linux check.

Actual environment: existing `notebooks/citypilot-env/Scripts/python.exe`,
Windows Python **3.13.1**, Shapely **2.2.0**, GEOS **3.14.1**, pyproj **3.8.0**,
PROJ **9.8.1**, NumPy **2.5.4**. No packages installed or changed.

Before modification the exact original test passed on Windows. There are no
local saved/regenerated vertex-count mismatches among 146 rides. Thus this is
a correction of a representation-dependent test guarantee, not evidence of a
reproduced Windows production bug. The supplied Linux shapes are equivalent
under the documented directed metric bounds.

## Intended guarantee and replacement

`projected_bus_geometries` takes the saved **projected** stop chainages on the
source route in the model metric CRS, then transforms the substring back to
WGS84. Saved ride lengths still govern physical routing time. The test should
prove that regenerated and saved geometries describe the same directed ride;
it should not require the same representation/number of vertices.

The original ordered-array `assert_allclose` implicitly required equal shapes
and vertex counts. The replacement retains exact ride-ID set and geometry-type
checks, projects both coordinate sequences into the model's **EPSG:32639**
metres, and checks directed start/end, absolute total length difference and
the distance between corresponding normalized-chainage positions.

Positions are compared at the union of **both** polylines' vertex chainages,
including start/end. Between consecutive knots each traversal is affine;
their difference is affine and its Euclidean norm cannot exceed the maximum
at the interval endpoints. This bounds the entire traversed path, rather than
sampling at an arbitrary spacing. Exact repeated vertices remain in the input;
only identical sampling chainages share a check. No interior vertices are
deduplicated and no geometry is rewritten.

The absolute tolerance is **1e-6 m (one micrometre)** for endpoints, length and
ordered positions, with no relative-coordinate allowance. This is much tighter
than the previous 1e-8 degree component tolerance (roughly 1 mm in the pilot).
A read-only current Windows audit compared each regenerated geometry against
the source substring at its saved projected chainages, before the
metric/WGS84 round trip. Across all 146 rides:

| Quantity | Maximum |
| --- | ---: |
| Endpoint error | 1.870812694540736e-9 m |
| Hausdorff distance (audit diagnostic only) | 2.794573987870897e-9 m |
| Length difference | 4.921957952319644e-9 m |
| Coordinate float64 ULP | 9.313225746154785e-10 m |

All source substrings also passed the new directed comparison. The one
micrometre budget accommodates nanometre-scale projection/interpolation noise
while rejecting micrometre-plus displacement and accumulated length changes.
It is not derived from a guessed Linux maximum or a routing calibration.

For the **23 supplied Linux regenerated/saved pairs**, the measured maxima
were endpoint displacement **2.842656207986823e-9 m**, Hausdorff distance
**2.794573987870897e-9 m** and absolute length difference
**2.6128645913559012e-9 m**. Each also passed the full ordered-path bound. The
observed mismatch is vertex representation, not meaningful path displacement;
the precise platform/library operation causing the representation difference
has not been isolated.

Regressions cover redundant start/interior/end vertices and nanometre-scale
extra coordinates at realistic UTM magnitudes, preserved bends and stationary
paths. Counterexamples reject shifted endpoints, changed paths of identical
length, reversal, closed-loop reversal, backtracking, reordered loops with
identical spatial set/endpoints/length, accumulated tiny detours and invalid
coordinates. Hausdorff-only or direction-insensitive equality would miss some
of these cases.

## Actual focused checks

From this worktree in PowerShell:

```powershell
$env:CITYPILOT_TEST_BUNDLE = 'C:\Users\celal\OneDrive\Desktop\ayna-hackathon-2026\ayna-hackathon-2026\outputs\c4_model_alpha_20261017_155941_581069'
& 'C:\Users\celal\OneDrive\Desktop\ayna-hackathon-2026\ayna-hackathon-2026\notebooks\citypilot-env\Scripts\python.exe' -I -B -X utf8 -m pytest tests/test_geometry_assertions.py tests/test_baseline_adapters.py::RealBundleTests::test_projected_stop_shapes_use_saved_substrings -q
git diff --check
```

- Original test before edits: **1 passed**, 150 existing Shapely transform
  deprecation warnings, 4.50 s.
- Final focused run (including the supplied Linux pair regression): **22 passed,
  146 subtests passed, 0 failures/skips**, 150 existing transform deprecation
  warnings, 1.32 s.
- `git diff --check`: passed.
- No full routing suite, exporter, benchmark, precompute, dependency change,
  server restart or tunnel operation. No production code changed, so exporter
  regeneration/check is unnecessary.

Next action: run the same two focused targets on Ali's Linux environment with
its explicit immutable bundle, reconcile the report/GeoJSON environment
metadata, and investigate any metric mismatch instead of increasing tolerance.

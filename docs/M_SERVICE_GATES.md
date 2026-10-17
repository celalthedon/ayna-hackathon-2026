# M-bound objective gates

Generated from main `e5a527b` in the isolated `celal/m-service-gates` branch.
Only two new gate records, focused tests and this handoff are added. Original
`config/objective/objective_decision_{P,B}.json`, API/optimizer/A6 code, shared
identity validation, supplement assets and the immutable bundle are unchanged.

The existing `gate_decision(normal, disrupted, path)` API generated both files
under `config/objective/m_services_v1/` from actual canonical normal/disrupted
evaluations, using the existing project interpreter. Both profiles were checked
against the expected counts/objective before either file was written. Hashes
were taken from executed EvaluationResult objects, never manually substituted.

| Profile | Losses at 40 / 45 / 50 min | OD pairs | Objective |
|---|---|---:|---|
| P | 1424 / 1148 / 799 | 2718 | count |
| B | 0 / 0 / 0 | 2718 | sum |

The artifact is the immutable C4 bundle
`c4_model_alpha_20261017_155941_581069`, bundle hash
`9457bfe95125b1d8bddb1be662ad6f0bbd1a00c0ac8f8abcc2fbecf872d53066`.
Routing config is repository-relative `supplements/m_services_v1/config`;
supplement hash is
`42a560089d459f61667e6624425e04e03429d03f139605ef02124874d801835a`.
The M model_version is the original `c4-alpha-1@<bundle_hash>` plus
`+prebuilt@<supplement_hash>`. The OD set stays
`fixed_od_v1@10c1b58f1d704cec25b11936da32c2c09bc995323e8a4083fd0bd46f50286ac8`.
Registration changes identity even though these requests have no activation or
other patches, speed_factor=1 and headway_factor_by_group=null.

| Profile/state | Generated input hash |
|---|---|
| P normal | `29fe7ca2182a1bc3ee41da01c7248eda14e5bf206abcd3d09ab6b5ae93697f98` |
| P disrupted | `f20fdaa688eceecdab8e1367f6e681cbd73bdca53ba7730b0554d3d46467e456` |
| B normal | `8e907b9224fda41c084989b1b521f1ccfed822497b392620212ec0945158bd13` |
| B disrupted | `82ab6245a0bebc5a6dff4af3073a2026dcc74bc28b67dd22c10a7fd256b8f8ec` |

## Selecting records with the existing consumer

For an M-loaded model, use this explicit directory and the selected profile's
actual request hashes:

```python
from pathlib import Path
from citypilot.routing_engine import baseline_request
from citypilot.decision_engine import load_objective

hashes = {state: baseline_request(model, state, profile).config_hash
          for state in ("normal", "disrupted")}
objective = load_objective(Path("config/objective/m_services_v1"), profile, hashes)
```

For the original bundle config, keep `config/objective` and its original-model
hashes instead. Do not flatten the new files into that directory or weaken
`ObjectiveModelMismatch`. A profile-specific `DecisionProblem` already accepts
`objective_dir` and `model_hashes` explicitly.

**Remaining integration gap:** `DecisionBackend.objective_dir` can select this
directory when Ali constructs the backend. However, current `api_decision.py`
uses one shared `backend.model_hashes` pair for both P and B, including `/state`
and the profile-specific DecisionProblem it builds. The two profiles have
different valid pairs, so simply changing objective_dir cannot make one backend
validate both. Ali's backend/router wiring must supply the correct pair per
profile. This PR does not change that wiring or claim production decision API
readiness. C6 `create_app` accepts an injected decision_backend; it does not
construct Ali's real backend automatically. `CITYPILOT_CONFIG_DIR` selects only
routing config and does not choose a gate directory.

## Generation and verification

Existing generation API (no new CLI), from repository root with `src` importable
and `bundle` set to the explicit immutable bundle path:

```python
from pathlib import Path
from citypilot.routing_engine import load_model, baseline_request, evaluate_package
from citypilot.decision_engine import count_lost, gate_objective, gate_decision

model = load_model(bundle, "supplements/m_services_v1/config")
expected = {"P": ({40: 1424, 45: 1148, 50: 799}, "count"),
            "B": ({40: 0, 45: 0, 50: 0}, "sum")}
evaluations = {}
for profile in ("P", "B"):
    normal = evaluate_package(model, baseline_request(model, "normal", profile))
    disrupted = evaluate_package(model, baseline_request(model, "disrupted", profile))
    assert len(normal.od_results) == len(disrupted.od_results) == 2718
    lost = count_lost(normal, disrupted)
    assert (lost, gate_objective(lost, 2718)[0]) == expected[profile]
    evaluations[profile] = normal, disrupted
for profile, (normal, disrupted) in evaluations.items():
    gate_decision(normal, disrupted, Path("config/objective/m_services_v1"))
```

The generator refuses existing files; the checked-in records must not be
overwritten to rerun generation. A separate empty destination is needed for a
new generation audit. Timestamps are generation evidence, not request identity.

Run focused tests with `CITYPILOT_TEST_BUNDLE` set to the explicit immutable
bundle and the existing validated Python. No notebook/kernel or package changes:

```powershell
python -I -B -X utf8 -c "import sys,pytest; sys.path.insert(0,'src'); raise SystemExit(pytest.main(['-p','no:cacheprovider','-q','tests/test_m_gate_files.py']))"
```

Tests load the actual original and M models and construct canonical baseline
requests. They check both acceptance directions and cross-model/cross-profile
rejection without reconstructing hashes or repeating OD evaluation. Generation
performed the four actual M evaluations and confirmed the expected losses.
Result: **14 focused tests passed in 3.29 s**, zero failures or skips.
The prior full 10,872-row numerical parity is reused from
`supplements/m_services_v1/verification.json` and the prior executed gate review;
no new full OD comparison, optimization or precompute was run.

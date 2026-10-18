# README scope and verification

Documentation base: `origin/main` **28f387332c09fd41622e3f41017091520d6f7a21**, inspected 18 October 2026 (Asia/Baku). The original dirty checkout and all other worktrees were preserved. This documentation branch does not integrate open PR #41 or Docker PR #22.

## Evidence reconciled

| Topic | Current implementation and documentation treatment |
|---|---|
| Shared contract migration | `contracts.py` and real decision consumers use contract 1.0. Earlier C4/CONTRACT handoff text still says Ali must migrate; it is historical, not the current status. |
| Activation | The generated engine and M registry implement `activate_service`; older baseline handoffs saying it is unsupported are superseded. Link/new-parking activation remains unsupported. |
| Default startup | `api.create_app(..., decision_backend=None)` serves routing/UI without constructing the real backend. The launch helper embeds a development machine path. `RUNNING.md` uses explicit reader-provided paths and the existing injection interface. |
| Full composition | The documented public-interface recipe loads the model for `real_backend` and again for the routing lifetime. The one-load backend hook and resource-summary wiring used in the local demo are not committed to this main. No application repair is included. |
| UI | Optional decision mounting is implemented. Main still has the literal disconnected warning in the left resource summary and placeholders in the separate comparison tab. Recommendation selection is separate from map activation. |
| Cache correctness | `_answers` calls shared `validate_request`; RAM/disk/fresh paths enforce it. Index summaries validate identity and shape but do not enforce all numerical bounds or prove agreement with full OD payloads. The README does not claim equivalent validation strength. |
| Ranking | Main has pairwise absolute capped-sum ties at `1e-6` minutes, not transitive quantised ordering. Ranking-policy versioning is absent from derived identities. Open #41 is not documented as implemented. |
| Gain definition | Committed M receipt: P/M5_A at T=45 has 1941 within, disrupted has 1191. Their difference 750 is net gain. `run_a6_first_real.package_row` intersects normally reachable lost ODs for restored-lost counts; CO2 coverage uses the different post-versus-disrupted set. No historical 737 restoration claim is copied. |
| M evidence | The committed supplement has complete constructed cycles and independently routed return geometry, but approximate coordinates, assumed return order/intervals and transferred speed. It is not an officially verified street-routing/capacity model. |
| Linux evidence | The geometry document checks supplied Linux-produced pairs on Windows and records inconsistent supplied environment metadata; it is not a fresh native Linux run. Cross-platform numerical acceptance preserves original hashes/provenance. |
| Team | Roadmap explicitly assigns Celal/Ali ownership; data handoff describes an unnamed teammate. Xədicə is acknowledged as requested without inventing specific code/data authorship. |

## Checks performed for this documentation change

- Existing interpreter: Python 3.13.1 on Windows. Installed metadata agrees with all 11 exact requirements; no package changes or new environment.
- Clean-process imports of shared contracts, routing, API and real decision wiring; inspected callable signatures.
- Actual `citypilot.precompute --help`, `tools/build_m_services.py --help`, `tools/build_od_car_distances.py --help`. No dry-run/model-loading operation was needed.
- Python AST compilation of the README example and both embedded startup snippets; PowerShell parse-only validation of all eight fenced command blocks. No launch/install/materialisation command was executed.
- Strict baseline helper request round-trip and 2,718 profile-aware references using immutable metadata only; actual terminal/exit IDs checked against supplied GeoJSON. No graph loaded or shortest-path solve executed.
- Baseline table cross-checked with committed parity/registration receipts; M5 net-gain arithmetic checked against the committed supplement receipt.
- Markdown parsed with the existing bundled `marked` parser. Relative links/anchors, UTF-8, balanced fences, and absence of personal absolute paths/temporary tunnel hosts checked.
- Four Mermaid blocks checked statically for declarations, endpoints, participant references and balanced delimiters. No Mermaid parser/renderer is installed; GitHub's rendered appearance has **not** been independently verified.
- `git diff --check`; final scope restricted to README and two supporting Markdown documents.

### Exporter outcome: distinguish Git content from checkout conversion

Both direct exporter `--check` commands failed in this Windows worktree with `Generated module missing or stale`. Read-only exporter rendering showed:

| Owner | Committed Git blob equals deterministic export | Worktree equals export after CRLF→LF |
|---|---|---|
| Celal | yes | yes |
| Ali | yes | yes |

The failures are byte-level checkout line endings, not stale notebook source. Routing has one tagged cell in 68 total cells; decision has 22 tagged cells in 89 total cells. No notebook or generated module was changed/regenerated. The setup guide requests an LF-preserving new clone and explains existing-checkout handling; it does not silently report the failed checks as passes. Gate byte materialisation is likewise documented separately because stored stress keys include raw gate hashes.

## Deliberately not executed

No package installation, environment creation, full/focused application test suite, full model load, routing evaluation, optimisation, precompute, benchmark, server startup/restart, tunnel operation or live browser session. The README's end-to-end calculation and full startup are interface/syntax-checked recipes, not claims of a newly executed clean-install deployment. Historical model-consistency receipts are distinguished from field validation and fresh test execution.

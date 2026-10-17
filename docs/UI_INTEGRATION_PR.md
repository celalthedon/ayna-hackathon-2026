Serve the approved CITYPILOT interface from the existing FastAPI app and connect it to the real fixed-OD routing API. The UI shows the complete existing pilot geography, configured R2/R14 headways and mutually exclusive M service variants, accessibility counts and physical JourneyResult playback. The approved layout, themes, Three.js renderer, layer transitions and controls are retained.

Consecutive compatible walking legs appear as one `Piyada` list summary. Original legs, time, geometry gaps and playback/seek mapping remain intact. Mode/component labels use Azerbaijani and text assets explicitly declare UTF-8. Geometry and vendor assets are local; source model outputs, M assets, gates, dependency pins and Ali's decision implementation are unchanged relative to inspected main.

Validation:

- 20 Node tests pass, including original/bundle hash preservation, geography alignment, request and stale-response handling, physical playback, walking summaries and UTF-8.
- The user reports successful outside-sandbox startup, rendered UI approval, and HTTP 200 for assets, readiness, catalog, OD metadata, evaluation and journey.
- Focused Python tests were attempted but blocked before collection by access denied to the supplied environment's base Python executable. Browser automation is also restricted; no automated visual/control checks or screenshots are claimed.

Real decision/A6/catalog/cache/precompute integration remains pending; no synthetic optimizer output is presented as real. Separate P/B gate hash pairs remain required. No merge or deployment is included. See `docs/UI_INTEGRATION_PROGRESS.md` for the exact launch/test commands and remaining verification.

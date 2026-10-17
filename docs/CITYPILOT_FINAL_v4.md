# AYNA CityPilot — Final Specification v4.1 (audited against the 43 datasets and OSM; blind consistency review applied)

**Team:** Octopus — Celal and Ali · **Event:** AYNA Hackathon, Baku · **Time:** 2 days · **Document date:** 17 October 2026

**Status:** Specification only. Nothing below is built.

**Evidence labels used throughout:**
- **[inspected]** — re-checked on 17 Oct 2026 by opening the raw files listed in Part B with the scripts named there.
- **[retrieved]** — taken from official web sources.
- **[assumption]** — a scenario input chosen by us.
- **[unverified]** — not checked.

Proposed fixes are requirements, not implemented features.

---

# Part A — Specification

## A1. Product
**CityPilot helps AYNA compare transport-service and transfer improvements that restore modelled accessibility when a metro link is removed, under explicit resource limits, and shows why each package works.**

It is a scenario decision-support simulator for one corridor. It is not live monitoring. It does not measure passenger diversion or causal benefits.

| AYNA problem | MVP response | Limit |
|---|---|---|
| 1. Weak terminal → bus → micromobility transfers | Network-routed test journeys with explicit transfers. **Bakı Beynəlxalq Avtovağzal is a required origin.** Private-bike park-and-ride scenario. | One corridor; two curated bus routes |
| 2. No unified view of hubs and gaps | Corridor workspace: four AYNA layers, metro, OSM network, closure state, lost journeys, candidate actions, source dates | Open-data refresh only, not live |
| 3. CO₂ not measured | Separate scenario calculator incl. added bus emissions; assumption-based defaults, national DSK values shown as reference | Assumption-based; never derived from accessibility counts |

## A2. Anchor event and baseline semantics

**Facts [retrieved]:**
- AZERTAC, 4 Aug 2026 (https://azertag.az/xeber/4351205):
  - Trains between **28 May and Nizami** are suspended for about 10–11 months.
  - İçərişəhər–Həzi Aslanov and 28 May station keep operating.
  - Service in the Dərnəgül–Nizami direction "will be ensured".
  - The purple line is not mentioned.
- Express routes M1–M6 started on 14 Aug. The closure started on 15 Aug. Twenty regular routes were reinforced: 2, 6, 7A, 9, 10, 14, 17, 18, 26, 61, 65, 79, 85, 88, 88A, 93, 133, 165, 199, 202. Sources: https://azertag.az/xeber/4351909 and https://en.apa.az/infrastructure/train-services-between-baku-metros-28-may-and-nizami-stations-suspended-from-today-video-520425

**Model semantics:**
- Remove the **link** 28 May ↔ Nizami in both directions.
- All stations stay open. Dərnəgül–Nizami service continues.
- The purple line keeps operating with its interchange at Memar Əcəmi **[assumption — confirm]**.
- A station closure (link removal plus exit removal) is a separate operation and is not used by default.

**Default scenario = labelled synthetic stress test:**
1. *Normal:* pre-closure network at assumed baseline headways, with no express routes.
2. *Disrupted:* the same network minus the closed link. Nothing else changes.
3. *Mitigated:* the disrupted network plus a selected package.

This does **not** reconstruct the historical network. AYNA's express routes and reinforcement appear only as labelled candidate actions in state 3. The size of AYNA's reinforcement is unknown **[unverified]**. Putting express routes into states 1–2 would model a network that never existed.

## A3. Pilot boundary

**Corridor:**
- Dərnəgül / 20 Yanvar → İnşaatçılar → Elmlər Akademiyası → Nizami → 28 May, plus a ≥1.5 km buffer.
- Analysis box used for the audit: lon 49.77–49.90, lat 40.355–40.44.
- The box contains Avtovağzal metro and Bakı Beynəlxalq Avtovağzal.

**Affected stations:**
- Fixed **ex-ante** from the closure semantics, never from ridership: Nizami, Elmlər Akademiyası, İnşaatçılar, 20 Yanvar, Memar Əcəmi, Nəsimi, Azadlıq prospekti, Dərnəgül, plus the purple-line stations Memar Əcəmi 2, 8 Noyabr, Avtovağzal, Xocəsən **[assumption on topology — confirm with the OSM subway layer and the official diagram]**.
- Commit the list as `config/closure.yaml` before any result is computed.

**Bus services:**
- Routes **2** and **14** (both reinforced regular routes). Reserve: **79**.
- **The M routes in the AYNA bus layer cannot be used.** The layer is folder-dated "BusLinesAll271125", so probably 27 Nov 2025 **[inspected]**. Its M1–M6 do not match the official August 2026 express routes:
  - M1, M3, M5 and M6 do not reach their official end stations.
  - M2 is a 69.5 km loop that passes 13 extra stations.
- An optional express connector İnşaatçılar → Nizami → 28 May may be modelled as a **curated candidate**: stops at the three stations, path on the OSM drive network, assumed headway, all labelled.

## A4. Data gate (Day 1, time-boxed to 3 hours; status after audit)

| # | Input | Status after audit | Gate action | Fallback |
|---|---|---|---|---|
| G1 | OSM network | **Obtained [inspected].** Geofabrik free shapefiles, OSM as of 2026-10-16. Corridor box: 88,454 walk nodes, 109 components, the largest holding 94.8% of nodes. 39.8 km `cycleway`. 19.2% of ways one-way. 114 bridges, 242 tunnels. | Build walk and bike graphs from `gis_osm_roads_free_1`. Free shapefiles lack access/sidewalk/bicycle tags, so the legality rules are limited (see A5). | — |
| G2 | Directional stop sequences, routes 2 and 14 | **Partly unblocked [inspected].** 761 OSM `bus_stop` points in the box, 97.9% named. 104 lie within 15 m of route 2's line and 66 within 15 m of route 14's. Proximity ≠ service, and the free shapefiles carry no route relations. | Generate candidate stops from OSM; a person confirms which ones each route serves and in which order (AYNA MaaS app / site). Record the source per stop. | Curated corridor stops at metro-adjacent locations only, labelled assumed. The pitch says "topology & accessibility prototype". |
| G3 | Headways for 2 and 14, express connector | Unavailable | **One baseline peak headway per route** from the assumption sheet (P1, P2), each with separate low/high stress levels. Express connector headway P16. If nothing is published: **[assumption]** default 10 min, stress levels 6 and 15 min. | Bus headway is stress-tested |
| G4 | Bus speed, dwell, layover | Unavailable | **[assumption]** 15 km/h (range 10–20), 20 s, 5 min | Bus speed is stress-tested; dwell and layover are fixed |
| G5 | Metro topology and times | **Topology available [inspected].** OSM has 176 `subway` segments and station points for every corridor station. Times unavailable. | Build `(station, line, direction)` nodes from OSM and the exits file. **[assumption]** 2 min per station incl. dwell, 4 min headway, 2 min platform-to-exit, 3 min interchange Memar Əcəmi ↔ Memar Əcəmi 2 (P17) | Fixed; not in the demo stress grid |
| G6 | Closure operating pattern | Partially retrieved (A2) | Confirm Dərnəgül–Nizami through-running and purple-line status | A2 assumption, labelled |
| G7 | Destination POIs | **Unblocked [inspected].** OSM in the box: 19 universities, 16 colleges, 189 hospitals, 176 clinics. Dataset 09: 43 university-like names and 295 `HOSPITAL`-type points in the box. Datasets 14 and 19 have addresses but no coordinates. | Pick ≤8 POIs present in **both** OSM and dataset 09 (≤100 m apart, name match checked by hand). Record both IDs. | Destinations = 28 May, Sahil, Gənclik exits |
| G8 | Terminal access | **Resolved [inspected].** The terminal point snaps 37 m to the main walk component. Network distance to the nearest Avtovağzal metro exit is 430 m (412 m straight-line). | Use the OSM snap. Check the entrance on imagery. | — |
| G9 | Network defects found in the audit | **[inspected]** Exit "Xocəsən Çıxış 1" lies on a disconnected walk component (8.7 m to a way, 727 m to the main component). "28 May Çıxış 2" is 70 m from the nearest walk way. Median exit snap distance is 4.9 m. | **Base-network data fix:** add one curated connector per defect, present in **all three states** (not a candidate action) | Exclude the exit from all states and disclose it |

## A5. Network model

**Walk layer**
- OSM `fclass` ∈ {footway, pedestrian, path, steps, living_street, residential, service, unclassified, tertiary/secondary/primary (+links), track, cycleway, bridleway}.
- Exclude motorway, trunk and busway.
- Treat edges as undirected. One-way restrictions do not apply to walking.
- Tunnels and bridges are kept as given **[assumption: pedestrian-accessible unless the fclass excludes them]**.

**Drive layer (for bus paths only)**
- OSM `fclass` ∈ {motorway, trunk, primary, secondary, tertiary (+links), unclassified, residential, living_street, service, busway}.
- Respect `oneway`.
- **Route length** = sum of drive-network paths between consecutive curated stops. This one length feeds both trip edges and cycle time. `Shape_Leng` and the KMZ loop length are not used.

**Bike layer**
- The same ways minus steps, motorway and trunk.
- Respect `oneway` on roads; it is not applied to cycleways.
- Cycling on `footway` and `pedestrian` is allowed only as a labelled assumption toggle (default off), because the free shapefiles carry no bicycle-access tags.
- The AYNA lane layer is an **attribute** on OSM ways: 92.4% of 25 m samples along AYNA lanes lie within 10 m of an OSM way, and 57% are on OSM `cycleway` **[inspected]**. Match a lane to the nearest way within 10 m. Report unmatched lanes.

**Metro**
- `(station, line, direction)` platform nodes from OSM `subway` and station points.
- Exits from dataset 05 snapped to the walk graph.
- Platform-to-exit edge, boarding = headway/2, run edges **[assumptions]**.

**Bus**
- `(stop, route, direction)` nodes for curated stops.
- Boarding edge = headway/2 **[assumption: random arrivals, regular service, no bunching or denied boarding]**.
- Trip edge = OSM drive-network path length between consecutive stops / speed + dwell.
- Alighting edge = 0.
- A journey can never change route or direction without a new boarding.

**Bus direction**
- Loop geometry does **not** prove direction. Outbound and return overlap: 22% of route 2's vertices and 9% of route 14's lie within 25 m of another part of the same loop more than 600 m away **[inspected]**.
- Route 14 has 8 polylines: a 24.8 km main loop plus fragments of 0–1.5 km, all with `Shape_Leng` 27.2 **[inspected]**.
- Direction comes only from the curated stop order (G2).
- Snapping: project each stop onto the loop, keep along-path positions monotonic in curated order, and flag stops with both directions within 25 m for manual review.

**Private-bike scenario (B), separate from pedestrian + transit (P)**
- State `bike_with_me ∈ {yes, no}`. Origins start with `yes`.
- Cycling edges are allowed only while `yes`.
- `yes → no` happens only at a parking node: one of the 733 deduplicated sites snapped to the walk graph ≤30 m. In the box, 570 of 605 sites snap ≤30 m (median 9.8 m) **[inspected]**. Park cost is 1 min **[assumption]**.
- There is no `no → yes` transition. No transit boarding while `yes` **[assumption: bikes not carried on metro/bus; confirm]**.
- Walking edges are allowed while `yes` (pushing the bike) at walking speed **[assumption]**.
- Parking ≠ rental ≠ capacity.
- Tests:
  1. In (P), no cycling edge is used.
  2. In (B), no cycling edge follows parking.
  3. Every transition happens at a parking node.
  4. No boarding happens while `yes`.

**Journey time**
- Journey time = walk + wait + in-vehicle + transfer movement.
- Transfer penalty = **0 by default (P18)**, so routing minimises minutes. If a penalty is set, routing uses generalised cost and **reported times are the minutes of that chosen path**.
- Unreachable = no path within cap C.
- Network distances differ materially from straight lines. For example, İnşaatçılar → nearest AYNA lane is 814 m on the network vs 553 m straight-line (+47%) **[inspected]**. All earlier straight-line figures are superseded.

**Implementation**
- Own compact graph with explicit state expansion.
- `scipy.sparse.csgraph.dijkstra`, all origins in one call.
- Cache by (network version, closure, package, assumptions).
- Measure latency; do not claim it in advance.

## A6. Evaluation set and objective (fixed before any optimisation)

**OD set:**
- **Origins:**
  - all exits of the affected stations (excluding any exit dropped under G9, which is disclosed);
  - 300 m grid points within 800 m of those exits, snapped ≤100 m to the main walk component;
  - **Bakı Beynəlxalq Avtovağzal (required)**.
- **Destinations:** exits of 28 May, Sahil and Gənclik, plus ≤8 G7 POIs.
- Equal weights. Station-boarding weights are shown separately as a labelled proxy.

**Parameters:** T = 45 min (also report 40 and 50). Cap C = 120 min. An unreachable pair counts as C.

**Objective:**
- **Primary (maximise):** OD pairs with time ≤ T in the mitigated state.
- **Tie-breaks:**
  1. minimise Σ min(t, C);
  2. then minimise bus-hours, then **new-infrastructure km** (cycling connectors + pedestrian links; planning mode only), then action count.
- **Also report:** restoration (recovered lost / lost, N/A if 0); newly reachable pairs; still-unserved pairs; mean and P90 time change over pairs reachable in all states.

**Feasibility gate (Day 2 morning, before optimisation):**
1. Compute normal vs disrupted: time changes and lost pairs at 40, 45 and 50 min.
2. For each candidate alone, check whether it changes any evaluated time. Drop and record candidates with no effect.
3. If threshold counts are uninformative, switch the primary objective to *minimise Σ min(t, C)* and commit that switch before optimisation. **Uninformative** = at all three thresholds, lost pairs < 20, **or** lost pairs < 10% of pairs, **or** lost pairs > 90% of pairs. After a switch the tie-breaks become: (1) maximise pairs ≤ T, (2) bus-hours, new-infrastructure km, action count.
4. Never change the OD rule, T or the closure list after seeing results.

## A7. Candidates, constraints, search

| Type | Example | Mode | Prerequisite | Horizon |
|---|---|---|---|---|
| Interval improvement | Route 2 headway −25% *or* −50% vs baseline (mutually exclusive) | Immediate | G3 baseline | Days |
| Interval improvement | Route 14 headway −25% *or* −50% (mutually exclusive) | Immediate | G3 | Days |
| Temporary connector service | Curated İnşaatçılar → Nizami → 28 May express | Immediate | Stops and OSM path curated | Days |
| Pedestrian transfer improvement | Specific stop ↔ exit link (the G9 defects are base-network fixes, not candidates) | Immediate | Site check recorded | Weeks (informational) |
| Cycling connector | Link to the lane-matched OSM network (e.g. İnşaatçılar, 814 m on the network) | Planning only | Legal bike ways only | Months |
| Parking at a verified gap | Only where (B) journeys need it and no site lies within 150 m on the network | Planning only | Connector **or lane access** exists | Months |

**Resource formulas**
- Cycle time (min) = route length (km) / speed (km/h) × 60 + Σ dwell (min) + layover (min).
- Vehicles = ⌈cycle / headway⌉.
- Added bus-hours = (vehicles_new − vehicles_base) × analysis hours H.
- Connector km is measured on OSM.
- Action count = number of selected actions of any type. **Pedestrian actions count toward it.**

**Constraints**
- Immediate mode: bus-hours ≤ B_h **and** action count ≤ N_a. Planning candidates are not allowed.
- Planning mode: B_h (when service actions are allowed) **and** connector km ≤ K **and** N_a.
- The constraints are never merged into one score.
- Interval options on the same route are mutually exclusive. Prerequisites are explicit; a parking action requires a connector **or existing lane access**.
- Each candidate type belongs to exactly one mode (table above). **Planning mode is a superset of Immediate mode.** Horizon is informational only and is not a constraint.
- **Default limits (scenario settings in `config/limits.yaml`, adjustable in the UI) [assumption]:** analysis period H = 3 h (morning peak), B_h = 30 added bus-hours, K = 2.0 km of new infrastructure, N_a = 3 actions.

**Search**
- Exact enumeration of feasible subsets (≤1,024 for 10 candidates).
- Verify against a hand-solved 4-candidate case.
- Baselines under identical candidates and limits:
  - **no action**;
  - **nearest-gap first:** rank candidates by network distance from the candidate to the nearest origin with a lost pair; add candidates in that order while the limits allow;
  - **overlap-aware greedy:** repeatedly add the candidate with the largest marginal gain in the primary objective per unit of the binding resource, recomputing the gain after each addition.
- Report where exact and greedy differ, or state that they never do.

## A8. Demo (priority order)
1. Three-state map with lost / restored / unserved journeys.
2. Package panel: mode toggle, B_h / K / N_a sliders, package vs baselines.
3. Journey inspector: path, stops, transfers, time breakdown, provenance (observed / published / curated / assumed) per state.
4. Remove-one-action, with infeasibility flags.
5. Stress test: top-3 packages × **bus headway × bus speed** (3 levels each, from the assumption sheet), plus one re-optimisation at the worst grid point. A slower speed updates vehicle feasibility. Metro times are not stress-tested.
6. Scenario selector: (P) / (B).
7. CO₂ calculator, separate from the optimiser:
   - user inputs with documented defaults (A9);
   - subtracts added bus vehicle-km;
   - shows negative results;
   - excludes embodied emissions.
8. Source and date on each layer. The open-data refresh job is shown as such and never called "live".

## A9. CO₂ calculator defaults (documented, still assumptions for the corridor)
- Average trip length, Azerbaijan 2024 **[inspected, dataset 34; national]**: metro 11.8 km, bus 15.2 km, car 15.4 km, taxi 18.7 km. National averages include suburban and intercity trips. **Corridor trips are likely shorter, so the default trip length is the mean network length over the evaluated OD pairs that the package restores. National values are shown only as a reference.**
- Fleet context 2024 **[inspected, dataset 30; national]**: 32,107 buses (21,404 diesel, 10,300 petrol, 190 electric). This supports a diesel-bus emission factor as default. BakuBus's own fleet mix is **[unverified]**.
- Emission factors (car kg/pkm, bus kg/vehicle-km, metro kg/pkm): **[assumption]**. A cited source must be named in the UI, or the field is shown as a user input.
- National pollutant tables (datasets 22–25) are not CO₂ factors and are not used as local factors. Baku's 2023 road-transport pollutants, 480.4 thousand t, are context only **[inspected, dataset 22]**.

## A10. Acceptance checks
1. A no-change scenario reproduces the baseline exactly (Day 1 afternoon).
2. No path uses the closed link or an invalid transfer.
3. Bus paths follow the curated order and direction. No route or direction change without boarding.
4. Bike-state tests 1–4 (A5) pass.
5. Removing edges never decreases any shortest time.
6. Packages respect B_h / K / N_a, prerequisites, exclusions and horizon.
7. Exact search = the **hand-solved** result on the 4-candidate case. Baselines get identical inputs.
8. The same configuration gives identical results.
9. Three journeys are hand-checked per state, including the terminal origin and each G9 exit that is kept. Normal and disrupted states are checked on Day 1; the mitigated state on Day 2.
10. Latency is measured on the demo laptop, and one unscripted change is rehearsed.

## A11. Two-day plan

**Day 1**
- 09–12 **Data gate.**
  - Celal: OSM walk/bike graphs (G1), metro from OSM (G5), G9 fixes, `closure.yaml`, OD rule.
  - Ali: OSM candidate stops for routes 2 and 14 → human confirmation and ordering (G2); G3/G4 assumption sheet; G7 POIs (dual-source); FastAPI + Leaflet (CDN) skeleton with the four AYNA layers.
- 12–17
  - Celal: state-expanded graph and unit tests (checks 1–5).
  - Ali: candidate table with resource maths; 1 h open-data refresh job (CKAN → validation → timestamps).
- 17–19 Ali: three-state view and journey inspector on real results.
- **12:00 decision:** if G2 is not done, switch to "topology & accessibility prototype" claims at once.
- **Evening gate:** three hand-checked journeys correct in normal and disrupted states, including the terminal. Confirm that the 12:00 decision was applied.

**Day 2**
- 09–11 Feasibility gate → commit the objective.
- 11–15
  - Celal: exact search, baselines, checks 6–8.
  - Ali: package panel, remove-one-action, (P)/(B) selector, CO₂ calculator.
- 15–17 Mitigated-state hand checks (check 9); stress test + re-optimisation; latency. Defect fixes only after 15:00.
- 17–20 Pitch, rehearsal, backup recording.

**Cut order:** POIs (use stations) → (B) scenario → curated express connector → stress-grid size → candidates (keep ≥5).

**Never cut:** bus participation (or its labelled fallback), the three-state comparison, constrained selection with baselines, the terminal origin.

## A12. Claims

**Defensible now [inspected unless marked]**
- **Data-quality findings:**
  - 10 sample placemarks removed (844 → 834) and 101 duplicate parking points merged (→ 733);
  - 48 → 27 station names and the "28 May" date corruption;
  - 15 missing station-days;
  - 14 of 65 bus routes not complete across 273 days;
  - route 206 = 100% NFC;
  - the bus layer predates the August 2026 express routes;
  - OSM network defects at two corridor exits.
- **Official timeline and closure description** [retrieved].
- **Metro, Jan–Jul 2026 vs 2025:** weekday-aligned −1.2% (95% CI −4.4% to +2.2%); calendar total −2.2%. No detectable change before the closure (descriptive).
- **Daily year-over-year ratio:** 0.97 on 14 Aug → 0.75 on 15 Aug (descriptive).
- **Ridership scale cross-check:** dataset 06 gives 226.8 M metro trips in 2025. DSK 2024 gives 2,708 M passenger-km ÷ 11.8 km ≈ 229 M passengers (datasets 34–35). Two independent sources agree in scale (different years).
- **Published lanes:** 57.0 km. Connectivity depends on tolerance: largest component 71% at 2 m, 92% at 5 m, 95% at 15 m. 92.4% of lane samples lie within 10 m of OSM ways.
- **Network vs straight-line distances** differ materially (İnşaatçılar → lane 814 m vs 553 m).
- **NFC share:** metro 29.8% → 44.3%; bus 18.8% → 40.9% (Jan → Sep 2026).

**Removed**
- station "AUC 0.93";
- "≈150k/day shortfall"; "M routes absorbed 36%"; spillover ρ = 0.47;
- "M2 follows 16 stations"; "53.3/57 km connected" without a tolerance;
- all straight-line distance claims;
- "7A/17/14 overloaded"; "≈102k t CO₂/yr" as a result; Koroğlu as #1;
- live-monitoring, forecasting and fleet claims made without inputs.

**Allowed only after measurement:** "Under the stated inputs and assumptions, package X restores Y of Z lost test journeys within T minutes using N added bus-hours, and differs from nearest-gap selection by D."

## A13. Deferred
Citywide coverage, full GTFS, live feeds, dispatch, forecasting, crowding, shared bikes, district equity, monetary budgets, weather, chatbot, Pareto sets, microsimulation, railway integration.

---

# Part B — Dataset-fit audit

## B1. Inspection record
- **Archive:** `AYNA_Datasets_43.zip`, 104 files in 43 folders. Every folder has a `SOURCE.json` with CKAN metadata (`status: verified`, `substitute: false`, landing page, retrieval timestamp 17 Oct 2026).
- **Core files 01–07, 41, 42** are byte-identical (SHA-256) to the earlier uploads, so earlier inspections stand.
- **OSM:** `azerbaijan-261016-free_shp.zip`, Geofabrik, OSM data as of 2026-10-16T20:21Z, ODbL. 20 layers, incl. roads, transport, pois, railways.
- **Scripts:** `parse.py`, `analysis.py`, `audit.py`, `inspect43.py` and `osm_checks.py` (all run 17 Oct 2026). Outputs: `work/audit.json`, `work/inspect43.json`, `work/osm_checks.json`.
- **Checks performed:**
  - format, CRS, schema, row counts, duplicates and null shares for every file;
  - coordinate fields;
  - Baku coverage;
  - name joins (routes, stations);
  - layer dates;
  - lane topology at 2/5/15/30 m;
  - route loop and self-overlap;
  - M-route geometry vs official endpoints;
  - ridership method (calendar vs weekday-aligned, block bootstrap);
  - OSM walk-graph components;
  - snapping of exits, terminal and parking;
  - lane map-matching;
  - OSM stops near routes;
  - POI availability;
  - national-statistics cross-checks.

## B2. Key join and consistency findings [inspected]
- **Routes:**
  - 239 in geometry; 65 BakuBus routes in ridership and in payments, with identical names.
  - 149E and 195E have no geometry.
  - M2–M6 ridership starts 14–15 Aug 2026; M8 runs since January; there is no M1 ridership.
- **Stations:** 27 in exits, 48 raw names in ridership, 28 in payments. All map to 27 canonical stations. OSM station names also match, apart from the "20 Yanvar st." and "Montin \ Nərimanov" variants.
- **Layer dates are not one snapshot:**
  - bus ≈ Nov 2025;
  - lanes 2026;
  - parking folders dated July and September;
  - terminals undated, though the catalogue says "updated every 6 months";
  - OSM 16 Oct 2026.
  - Every layer must show its date.
- **POIs:**
  - Datasets 14 (62 universities; 27 addresses missing) and 19 (84 TƏBİB institutions; 21 in Baku) have addresses only.
  - Dataset 20 is a facility hierarchy (names only).
  - Dataset 21 holds annual visits by institution.
  - Coordinates come from OSM and dataset 09.
- **Population, employment and emissions** are national, regional or district level. They are not to be downscaled to streets.
- **Parse issues:**
  - 12 and 22 have multi-line headers and `;` separators, so they need cleaning.
  - 28 and 29 have multi-row headers.
  - 10 has 4 invalid polygons.

## B3. Audit table
Fit: **U** usable now · **UP** usable after processing · **SC** scenario/context only · **NN** not needed · **UV** unavailable/unverified. All rows below are **raw inspected** unless stated otherwise.

| # | Dataset | Usable fields / coverage | Role | Fit | Processing / note |
|---|---|---|---|---|---|
| 1 | Intercity terminals | 69 points, WGS84; 4 in Baku area; catalogue: 6-monthly updates | Terminal origin | UP | Snap to OSM (37 m) |
| 2 | Bus trajectories | 239 routes; Name, Shape_Leng; ≈Nov 2025; no stops/direction | Paths for 2 and 14 | UP | M codes outdated; direction from curated stops |
| 3 | Bicycle parking | 844 raw points → 834 after dropping 10 sample placemarks → 733 after merging 101 duplicates; mixed dates; no capacity | Park nodes (B) | UP | Dedupe; drop samples and old lanes; snap ≤30 m |
| 4 | Bicycle lanes | 61 segments, 57.0 km, central Baku | Lane attribute | UP | Map-match to OSM (92.4% within 10 m) |
| 5 | Metro exits | 98 exits, 27 stations | Exit nodes | UP | Fix "28 May"; G9 defects |
| 6 | Metro boardings 2025/26 | Station-day; 15 missing station-days | Context / proxy weights | SC | Not demand, OD or occupancy |
| 7 | BakuBus boardings 2026 | Route-day; 65 routes, 51 complete | Context | SC | Not occupancy |
| 8 | Railway geometry | 1,872 lines, WGS84, national; Code_OSM | Not in corridor scope | NN | — |
| 9 | Objects and places | 11,807 points (11,653 in Baku), TYPE incl. HOSPITAL 527, SCHOOL 655; metadata Aug 2025; 11 duplicate coordinates | POI coordinates (with OSM) | UP | Dual-source POI check |
| 10 | District boundaries | 86 polygons; 4 invalid | — | NN | — |
| 11 | Administrative units | 4,589 points | — | NN | — |
| 12 | Population 2024 | District/region table; multi-line header | Context | SC | Clean CSV; no street-level use |
| 13 | Employment by region | 810 rows, region-year | — | NN | — |
| 14 | Universities | 62 rows; addresses (27 missing); no coordinates | POI names | SC | Use OSM/09 for coordinates |
| 15 | Vocational institutions | 78 rows; region/district; no coordinates | — | NN | — |
| 16 | Colleges | 55 rows; addresses | — | NN | — |
| 17 | Public preschools | 1,711 rows; address mostly empty | — | NN | — |
| 18 | Private preschools | 161 rows | — | NN | — |
| 19 | TƏBİB institutions | 84 rows (21 Baku); addresses; no coordinates | Hospital names | SC | Match to OSM/09 by name and address |
| 20 | TƏBİB facilities | 2,354 parent–child rows (21 duplicates) | — | NN | — |
| 21 | Healthcare visits 2023–25 | 89 rows, annual by institution | Optional POI importance | SC | Not hourly demand; name match to 19 needed |
| 22 | Road pollutants by district 2023 | Baku 480.4 thousand t total (CO, NOx, HC); messy header | Context | SC | Not CO₂, not local factors |
| 23 | Road emissions by pollutant | National series 1993–2023 | Context | SC | — |
| 24 | National road emissions | National; overlaps 23 | — | NN | Avoid duplication |
| 25 | Emissions by source | National 1995–2024 | Context | SC | — |
| 26 | Air quality | City annual concentrations to 2023 | — | NN | — |
| 27 | Sector GHG | National Mt CO₂e to 2022 | Pitch context | SC | — |
| 28 | Fleet by fuel/capacity | National 2013–2021; multi-row header | — | NN | Superseded by 30 |
| 29 | Fleet age | National; multi-row header | — | NN | — |
| 30 | Annual vehicles | 2024: 32,107 buses (21,404 diesel) | Supports the bus-factor default | SC | National |
| 31 | Current weather | API snapshot (17 Oct 2026) | — | NN | Deferred |
| 32 | Temperature | Annual | — | NN | — |
| 33 | Precipitation | Annual | — | NN | — |
| 34 | Avg distance per passenger | 2024: metro 11.8, bus 15.2, car 15.4 km (national) | CO₂ reference values | SC | National, not corridor |
| 35 | Passenger-km | 2024: metro 2,708 M pkm; bus 26,724 M pkm | Scale cross-check | SC | — |
| 36 | Passenger transport by category | Urban metro/bus passengers to 2022 | Context | SC | — |
| 37 | Railway annual stats | National finance and volumes | — | NN | — |
| 38 | Public-road length | 2024: Baku 182 km of public roads (DSK definition) | — | NN | Not the street network |
| 39 | Passenger-transport expenditure | National | — | NN | No unit costs |
| 40 | Transport investment | National | — | NN | No unit costs |
| 41 | BakuBus payment shares | Route-month Jan–Sep 2026 | Context | SC | 3 implausible rows |
| 42 | Metro payment shares | Station-month Jan–Sep 2026 | Context | SC | Canonical names |
| 43 | Accidents (FHN) | National annual 2007–2025 | — | NN | — |
| + | OSM roads/paths | 2026-10-16; an audit graph was computed for statistics only (production graph not built) | Walk/bike/drive network | **U** | Legality limits (A5) |
| + | OSM bus stops | 761 in box; 97.9% named | Candidate stops | UP | Human confirmation of service and order |
| + | OSM subway + stations | 176 segments; all corridor stations | Metro topology | UP | Times assumed |
| + | OSM POIs | 19 univ., 16 colleges, 189 hospitals, 176 clinics in box | Destinations | UP | Dual-source check with 09 |
| + | Directional stop sequences (2, 14) | Not in any file | Bus model | UV (blocking for bus claims) | G2 |
| + | Headways / speeds / dwell / layover | Not in any file | Waiting and run times | SC (assumption) | G3, G4 |
| + | Metro times, platform-to-exit | Not in any file | Metro timing | SC (assumption) | G5 |
| + | Closure operating pattern | Retrieved, partial | Scenario | UP | G6 |
| + | Emission factors | Not in any file | CO₂ calculator | SC (assumption) | Cite or expose as user input |

## B4. Capability status
| Capability | Status |
|---|---|
| Layer workspace with dates | Supported now |
| Walk/cycle network routing | **Data sufficient** (OSM; legality limits disclosed); not yet built |
| Metro routing with closure | Topology supported; times assumption-based |
| Bus participation (2, 14) | **Blocked until G2 confirmation.** Candidate stops exist. Afterwards assumption-based (headway, speed). |
| Express connector | Assumption-based curated candidate |
| Private-bike park-and-ride | Supported after processing (parking snap), with assumption-based rules |
| Terminal origin | Supported (37 m snap, 430 m to metro on the network) |
| POI accessibility | Supported after dual-source curation (≤8 POIs) |
| Three-state comparison, exact selection, baselines | Supported once routing works |
| CO₂ calculator | Assumption-based with national reference values |
| Live monitoring; ridership diversion or forecasting | **Remove** |

**Smallest remaining missing-data package**
1. Human confirmation and ordering of the OSM candidate stops for routes 2 and 14, with a source per stop.
2. Two one-line confirmations: Dərnəgül–Nizami service pattern and purple-line status.
3. A labelled assumption sheet: headways, speeds, dwell, layover, metro times, park cost, emission factors, plus P16 express headway, P17 interchange time, P18 transfer penalty.

---

# Part C — Blocking inputs and fallbacks
| Input | Deadline | Fallback (and claim change) |
|---|---|---|
| G2 stop confirmation (2, 14) | Day 1, 12:00 | Curated corridor bus with metro-adjacent stops only, labelled. The pitch says "topology & accessibility prototype". |
| G6 closure pattern | Day 1, 12:00 | Use the A2 assumption, shown in the UI |
| G7 POIs | Day 1, 12:00 | Stations as destinations |
| G9 network defects | Day 1, 12:00 | Exclude the affected exits; disclose |

G1 (OSM) and G8 (terminal) are no longer blocking.

---

# Part D — Change log

**v4 → v4.1 (blind consistency review, 16 findings):**
- G9 defects are base-network fixes in all states.
- Defaults added for H, B_h, K and N_a.
- One baseline headway per route; express connector headway P16.
- Drive layer defined; one route length used for run times and cycle time.
- Modes mapped (planning ⊇ immediate); horizon is informational.
- Parking prerequisite wording unified.
- Numeric gate rule and post-switch tie-breaks.
- "New-infrastructure km" defined.
- Baselines defined.
- Walking with a bike, interchange time (P17) and transfer penalty (P18 = 0) specified.
- Check schedule aligned; check 7 uses the hand-solved case.
- G2 switch at 12:00.
- "Built" wording removed.
- A1/A9 CO₂ wording aligned.
- Parking count chain stated.
- Stress parameters named.

**v3 → v4:**
1. **OSM obtained and inspected.** G1 is resolved. Corridor walk-graph statistics, legality limits (no access tags in the free shapefiles) and two network defects (G9) are added.
2. **G2 partly unblocked.** OSM gives candidate stops (104 / 66 near routes 2 / 14). The task changes from collecting stops to confirming and ordering them.
3. **G5:** metro topology comes from the OSM subway layer.
4. **G7 unblocked:** dual-source POIs (OSM + dataset 09). Datasets 14 and 19 have no coordinates.
5. **G8 resolved:** terminal snap 37 m; 430 m network distance to the metro.
6. **All straight-line distances superseded by network distances.** Example: İnşaatçılar → lane 814 m (was 553 m).
7. **Lane handling:** lanes become an attribute matched to OSM (92.4% within 10 m). Cycling on footways is a labelled toggle.
8. **CO₂ defaults** anchored to national DSK references (datasets 30, 34) with explicit national-vs-corridor caveats. Pollutant tables are excluded as factors.
9. **Ridership scale cross-check added** (datasets 06 vs 34–35).
10. **Full audit of all 43 datasets from raw files.** Parse issues are noted for 10, 12, 22, 28 and 29. Most datasets are marked not needed or context only.
11. Two-day plan rebalanced: Day 1 morning now covers stop confirmation, POIs and G9 fixes instead of the OSM download.

---

# Part E — Verdict
**Proceed, with these conditions:**
1. G2 confirmation for routes 2 and 14 is done by Day 1, 12:00. Otherwise switch to the labelled topology & accessibility prototype.
2. The OD rule, T, cap, closure list and closure semantics are committed before any result.
3. The feasibility gate runs before optimisation and its decision is recorded.
4. G9 defects are fixed or disclosed.
5. Only the A12 "Defensible now" claims are used until measured results exist.

**Reason:** with OSM in hand, everything the decision engine needs is available or curatable within the time box, except service levels. Service levels are treated as explicit assumptions and stress-tested. The 43 datasets add destinations and CO₂ reference values. Most of them are context, which is fine. No redesign is needed. The scope stays one corridor and two bus routes.

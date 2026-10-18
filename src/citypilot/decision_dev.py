"""Dev-only backend and server for checking the decision panels before the main app exists.

Synthetic test fixture, not a city result. Run:
    python -m citypilot.decision_dev   ->  http://127.0.0.1:8765/  (port: DECISION_DEV_PORT)
"""
import copy
import csv
import hashlib
import json
from pathlib import Path

from citypilot.api_decision import Co2Inputs, DecisionBackend, build_decision_router
from citypilot.contracts import Link, ModelCatalog, Parking, Provenance, ServiceGroup, ServicePattern
from citypilot.decision_engine import (
    Candidate,
    Limits,
    Scenario,
    StressGrid,
    load_fixture,
    make_catalog_patches,
    make_catalog_resources,
    make_fixture_evaluator,
)

ROOT = Path(__file__).resolve().parents[2]
STRESS_FIXTURE = ROOT / "tests" / "fixtures" / "decision" / "fixture_stress.json"
ASSUMPTIONS = ROOT / "data" / "curated" / "assumptions.csv"
DEV_DIR = ROOT / "outputs" / "cache" / "decision_dev"
# synthetic normal / disrupted config hashes of the fixture model
FIXTURE_MODEL_HASHES = {name: hashlib.sha256(f"fixture-{name}".encode()).hexdigest()
                        for name in ("normal", "disrupted")}


SYNTHETIC = Provenance(source_id="synthetic-dev-fixture", status="assumption", source="fixture_stress.json",
                       evidence="synthetic test fixture, not a city result", synthetic=True)
SERVICE_FIELDS = ("pattern_ids", "base_headway_min", "full_cycle_km", "speed_kmh", "stops_per_cycle", "dwell_s",
                  "layover_min", "coverage")


def _service(sid: str, v: dict) -> ServiceGroup:
    return ServiceGroup(service_group_id=sid, pattern_ids=(f"{sid}_A",), base_headway_min=v["base_headway_min"],
                        full_cycle_km=v["full_cycle_km"], speed_kmh=v["speed_kmh"], stops_per_cycle=v["stops_per_cycle"],
                        dwell_s=v["dwell_s"], layover_min=v["layover_min"], coverage=v["coverage"],
                        field_status={f: "assumption" for f in SERVICE_FIELDS}, provenance=SYNTHETIC)


def _catalog(service_groups: dict, prebuilt_services: dict, links: dict, parking: dict) -> ModelCatalog:
    groups = {**service_groups, **prebuilt_services}
    patterns = tuple(ServicePattern(pattern_id=p, route_id=sid, direction_id="A", stop_ids=(f"{p}_s1", f"{p}_s2"),
                                    provenance=SYNTHETIC) for sid, g in groups.items() for p in g.pattern_ids)
    return ModelCatalog(model_version="fixture_stress", od_set_id="fixture-ods", service_groups=service_groups,
                        prebuilt_services=prebuilt_services, links=links, parking=parking, patterns=patterns,
                        sources=(SYNTHETIC,), stop_ids=tuple(s for p in patterns for s in p.stop_ids))


def _assumption(param_id: str) -> tuple[float, str]:
    with open(ASSUMPTIONS, newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["param_id"] == param_id]
    if len(rows) != 1:
        raise ValueError(f"{ASSUMPTIONS}: need exactly one {param_id} row")
    return float(rows[0]["value_default"]), rows[0]["status"]


def synthetic_evaluator_for(fx: dict):
    """Fixture time model (synthetic): t' = walk + h'/2 + (t - walk - h0/2) / speed_factor."""
    walk, catalog = fx["walk_min"], fx["catalog"]
    default = Scenario(1.0, 1.0, fx["limits"]["H_hours"])

    def headway(rides, requires, scenario):
        if rides in catalog["prebuilt_services"]:
            return catalog["prebuilt_services"][rides]["base_headway_min"]
        group, kind = rides.split(":")
        h = catalog["service_groups"][group]["base_headway_min"] * scenario.group_headway_factor(group)
        cut = [fx["actions"][c]["pct"] for c in requires if fx["actions"][c].get("target_id") == group]
        return h * (1 - cut[0]) if kind == "new" else h

    def evaluator_for(profile: str, scenario: Scenario):
        def at(t, rides, requires):
            h0, h1 = headway(rides, requires, default), headway(rides, requires, scenario)
            return walk + h1 / 2 + (t - walk - h0 / 2) / scenario.speed_factor

        moved = copy.deepcopy(fx)
        for od in moved["ods"]:
            if od["disrupted_min"] is not None:
                od["disrupted_min"] = at(od["disrupted_min"], od["disrupted_rides"], ())
            for opt in od["options"]:
                opt["minutes"] = at(opt["minutes"], opt["rides"], opt["requires"])
        return make_fixture_evaluator(moved)

    return evaluator_for


def fixture_stress_backend(objective_dir: Path, cache_dir: Path, reference=None,
                           od_car_distance_km=None) -> DecisionBackend:
    fx = load_fixture(STRESS_FIXTURE)
    lim, cat = fx["limits"], fx["catalog"]
    catalog = _catalog(
        {k: _service(k, v) for k, v in cat["service_groups"].items()},
        {k: _service(k, v) for k, v in cat["prebuilt_services"].items()},
        {k: Link(link_id=k, kind=v["kind"], length_m=v["length_m"], requires_construction=v["requires_construction"],
                 status="assumption", provenance=SYNTHETIC) for k, v in cat["links"].items()},
        {k: Parking(parking_id=k, status="assumption", baseline_enabled=v.get("baseline_enabled", False),
                    provenance=SYNTHETIC) for k, v in cat["parking"].items()},
    )
    candidates = {c: Candidate(c, a["kind"], target_id=a.get("target_id"), pct=a.get("pct"),
                               link_ids=tuple(a.get("link_ids", ()))) for c, a in fx["actions"].items()}
    bus_factor, bus_status = _assumption("P13")
    car_factor, car_status = _assumption("P12")
    fixture_hash = hashlib.sha256(STRESS_FIXTURE.read_bytes()).hexdigest()[:16]
    return DecisionBackend(
        config_hash=f"fixture_stress:{fixture_hash}",
        input_hashes={"fixture_stress.json": fixture_hash},
        candidate_ids=tuple(sorted(candidates)),
        exclusions=tuple(tuple(g) for g in fx["exclusions"]),
        prerequisites={},
        distance_m={c: a["distance_m"] for c, a in fx["actions"].items()},
        limits=Limits(lim["B_h_bus_hours"], lim["K_new_infra_km"], lim["N_a_actions"], lim["max_exact_packages"]),
        thresholds_min=(40, 45, 50),
        primary_t_min=lim["T_min"],
        cap_min=lim["C_min"],
        objective_dirs=(Path(objective_dir),),
        model_hashes={profile: FIXTURE_MODEL_HASHES for profile in ("P", "B")},
        model_version="fixture_stress",
        od_set_id="fixture-ods",
        closure_id="closure-28may-nizami",
        H_hours=lim["H_hours"],
        resources_for=lambda scenario: make_catalog_resources(candidates, catalog, scenario),
        evaluator_for=synthetic_evaluator_for(fx),
        cache_dir=Path(cache_dir),
        N_a_max=4,  # fixture settings (the real values come from config/limits.yaml)
        B_h_max=70.0,
        reference_package_ids=reference,
        stress_grid=StressGrid(fx["grid"]["speed_levels_kmh"], fx["grid"]["headway_levels_min"]),
        co2=Co2Inputs(candidates, catalog, bus_factor, car_factor,
                      {"bus_kg_per_vkm": f"P13 {bus_status}", "car_kg_per_pkm": f"P12 {car_status}"}),
        od_car_distance_km=od_car_distance_km,  # the fixture OD table has no car_distance_km
        patches_for=lambda scenario: make_catalog_patches(candidates, catalog, scenario),
    )


def create_dev_app():
    from fastapi import FastAPI
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    DEV_DIR.mkdir(parents=True, exist_ok=True)
    for profile in ("P", "B"):
        objective = DEV_DIR / f"objective_decision_{profile}.json"
        if not objective.exists():
            objective.write_text(json.dumps({"objective": "count", "profile": profile, "input_hashes": FIXTURE_MODEL_HASHES,
                                             "note": "dev fixture: set explicitly, gate not run"}))
    # dev reference package for the compare button: synthetic, not the real AYNA response
    backend = fixture_stress_backend(DEV_DIR, DEV_DIR, reference=("B", "C", "D"))
    app = FastAPI(title="CityPilot decision panels (dev, synthetic fixture)")
    app.include_router(build_decision_router(backend))
    app.mount("/static", StaticFiles(directory=ROOT / "web" / "static"), name="static")
    app.get("/")(lambda: FileResponse(ROOT / "web" / "decision_dev.html"))
    return app


if __name__ == "__main__":
    import os

    import uvicorn

    uvicorn.run(create_dev_app(), host="127.0.0.1", port=int(os.environ.get("DECISION_DEV_PORT", "8765")))

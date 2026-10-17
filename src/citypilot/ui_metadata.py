"""Small public display projection of an already verified routing model.

No filesystem locations, graph matrices, access costs, or internal model objects
are serialized. Selection IDs are the saved fixed OD identities, not coordinates.
"""
import math


def od_metadata(model, identity):
    def items(key, id_field):
        result = []
        allowed = (id_field, "origin_kind", "station_name", "exit_name")
        for stable_id, feature in model[key].items():
            properties = {k: feature["properties"][k] for k in allowed if k in feature["properties"]}
            properties[id_field] = stable_id
            result.append({"id": stable_id, "properties": properties,
                           "coordinates": list(feature["geometry"]["coordinates"])})
        return result

    headways = {}
    for row in model["services"].itertuples(index=False):
        baseline = float(row.headway_default_min)
        # Only choices actually recorded by the loaded bundle. No fabricated
        # action catalogue or optimizer parameters.
        choices = sorted({float(getattr(row, field)) for field in
                          ("headway_low_min", "headway_default_min", "headway_high_min")
                          if hasattr(row, field) and math.isfinite(float(getattr(row, field)))
                          and 0 < float(getattr(row, field)) <= baseline})
        headways[str(row.service_group_id)] = {
            "baseline_min": baseline, "choices_min": choices,
            "status": str(row.headway_status),
        }
    return {"schema_version": 1, "identity": dict(identity),
            "origins": items("origins", "origin_id"),
            "destinations": items("destinations", "destination_id"),
            "headways": headways,
            "selection_policy": "fixed_saved_ids_only",
            "unavailable_interventions": ["activate_link", "enable_parking"]}

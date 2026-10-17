"""Clearly synthetic shared v1 schema fixtures, not measured or routed city data."""
from citypilot.contracts import (
    RoutingRequest, RoutingPatch, Provenance, ServicePattern, ServiceGroup,
    Link, Parking, ModelCatalog, EvaluationResult, ODResult,
    JourneyResult, JourneyLeg, LineString, GeometryMetadata,
)


def examples():
    p=Provenance(source_id='synthetic:v1',status='assumption',source='Synthetic v1 demonstration',
        evidence='Invented IDs and values; no city measurement or routing execution',synthetic=True)
    identity={'model_version':'synthetic-model-1@'+'1'*64,'od_set_id':'synthetic-od-1@'+'2'*64}
    request=RoutingRequest(**identity,state='mitigated',closure_id='synthetic:closure',profile='B',
        patches=(RoutingPatch(kind='set_service_headway',target_id='synthetic:existing',headway_min=7.2),
                 RoutingPatch(kind='activate_service',target_id='synthetic:prebuilt'),
                 RoutingPatch(kind='activate_link',target_id='synthetic:link'),
                 RoutingPatch(kind='enable_parking',target_id='synthetic:parking')),
        headway_factor_by_group={'synthetic:existing':1.2},speed_factor=0.9,candidate_ids=('synthetic:candidate',))
    fields=('pattern_ids','base_headway_min','full_cycle_km','speed_kmh','stops_per_cycle','dwell_s','layover_min','coverage')
    def group(name,headway):
        return ServiceGroup(service_group_id=name,pattern_ids=('synthetic:pattern',),base_headway_min=headway,
            full_cycle_km=6,speed_kmh=15,stops_per_cycle=4,dwell_s=20,layover_min=5,coverage='full',
            field_status={k:'assumption' for k in fields},provenance=p)
    catalog=ModelCatalog(**identity,
        service_groups={'synthetic:existing':group('synthetic:existing',10)},
        prebuilt_services={'synthetic:prebuilt':group('synthetic:prebuilt',6)},
        links={'synthetic:link':Link(link_id='synthetic:link',kind='bike',length_m=100,requires_construction=True,status='assumption',provenance=p)},
        parking={'synthetic:parking':Parking(parking_id='synthetic:parking',status='assumption',baseline_enabled=False,provenance=p)},
        patterns=(ServicePattern(pattern_id='synthetic:pattern',route_id='synthetic:route',direction_id='outbound',
            stop_ids=('synthetic:stop:a','synthetic:stop:b'),provenance=p),),sources=(p,),
        closure_ids=('synthetic:closure',),stop_ids=('synthetic:stop:a','synthetic:stop:b'))
    result_identity=dict(identity,config_hash=request.config_hash,state=request.state,profile=request.profile,cap_min=request.cap_min)
    evaluation=EvaluationResult(**result_identity,primary_t_min=45,
        od_results=(ODResult(od_id='synthetic:od:B:1',status='reachable',minutes=30,capped_minutes=30),
                    ODResult(od_id='synthetic:od:B:2',status='over_cap',minutes=130,capped_minutes=120),
                    ODResult(od_id='synthetic:od:B:3',status='no_path',minutes=None,capped_minutes=120)),
        within_counts={40:1,45:1,50:1},capped_time_sum=270,duration_ms=0,
        warnings=('SYNTHETIC example; schemas do not implement stress or C5',))
    geometry=LineString(coordinates=((49.8,40.4),(49.801,40.401)))
    journey=JourneyResult(**result_identity,od_id='synthetic:od:B:1',origin_id='synthetic:origin',destination_id='synthetic:destination',
        status='reachable',total_min=30,geometry=geometry,
        geometry_metadata=GeometryMetadata(partial=False,gap_count=0,provenance=(p,)),
        legs=(JourneyLeg(mode='walk',from_id='synthetic:origin',to_id='synthetic:destination',route_id=None,pattern_id=None,
            board_stop_id=None,alight_stop_id=None,geometry=geometry,walk_min=30,wait_min=0,ride_min=0,transfer_min=0,provenance=(p,)),),
        provenance=(p,),warnings=('SYNTHETIC geometry and time; not a calculated city journey',))
    return request,catalog,evaluation,journey

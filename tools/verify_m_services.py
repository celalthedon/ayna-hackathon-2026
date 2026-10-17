"""Clean-process M supplement verification; no optimization or performance benchmark."""
import argparse
from dataclasses import replace
import json
import math
import os
from pathlib import Path
import sys
import tempfile

# Bound native thread pools as in the prior engine verification receipt.
for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS','VECLIB_MAXIMUM_THREADS'):
    os.environ[key]='1'
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))


def verify(bundle,config,original_csv=None):
    import pandas as pd
    import pyproj
    import shapely
    from citypilot import routing_engine as e
    from citypilot.contracts import RoutingPatch,ModelCatalog,EvaluationResult,JourneyResult
    from citypilot.m_service_builder import build_supplement,sha
    bundle=bundle.resolve();config=config.resolve();supplement=config.parent
    report=json.loads((supplement/'build_report.json').read_text(encoding='utf-8'))
    original_manifest=sha(bundle/'manifest.json')
    model=e.load_model(bundle,config);catalog=e.get_catalog(model)
    assert ModelCatalog.from_json(catalog.to_json())==catalog
    ids=sorted(catalog.prebuilt_services)
    assert ids==sorted(report['ready_service_ids'])
    assert len(ids)==2*(5-len(report['blocked_lines']))
    assert set(catalog.service_groups)=={'SG_R2','SG_R14'}
    for g in catalog.prebuilt_services.values():
        line=g.service_group_id.split('_')[1]
        assert g.pattern_ids==(line+'_A',line+'_B')
        assert g.base_headway_min==(6. if g.service_group_id.endswith('_A') else 9.)
        assert g.speed_kmh==24.309068600209667 and g.dwell_s==25. and g.layover_min==10.
        assert g.stops_per_cycle==(2 if line in ('M2','M3') else 0)
        assert g.full_cycle_km==report['cycles'][g.service_group_id]['full_cycle_km']
    # Rebuild into a separate temporary directory and byte-compare ALL preparation files.
    with tempfile.TemporaryDirectory(prefix='citypilot-m-rebuild-') as tmp:
        rebuilt=Path(tmp)/'m'
        build_supplement(bundle,supplement/'source_stops.csv',rebuilt,
                         max_snap_m=report['max_snap_m'],detour_ratio=report['suspicious_detour_ratio_above'])
        compared=[]
        for file in sorted(rebuilt.rglob('*')):
            if file.is_file():
                relative=file.relative_to(rebuilt)
                assert file.read_bytes()==(supplement/relative).read_bytes(),str(relative)
                compared.append(relative.as_posix())
    parity={};baseline_disrupted=None
    expected={'P_normal':[2060,2339,2496],'P_disrupted':[636,1191,1697],
              'B_normal':[2406,2506,2511],'B_disrupted':[2406,2506,2511]}
    for profile in ('P','B'):
        refs={r.od_id:(r.origin_id,r.destination_id) for r in e.get_od_table(model,profile)}
        for state in ('normal','disrupted'):
            request=e.baseline_request(model,state,profile)
            result=e.evaluate_package(model,request);result.validate_request(request)
            saved=pd.read_csv(bundle/f'od/times_{profile}_{state}.csv.gz').set_index(['origin_id','destination_id'])
            errors=[]
            for row in result.od_results:
                ref=saved.loc[refs[row.od_id]]
                assert row.status==ref.status
                if row.minutes is not None:errors.append(abs(row.minutes-ref.total_min))
                else:assert ref.status=='no_path'
                errors.append(abs(row.capped_minutes-ref.capped_min))
            maximum=max(errors)
            assert maximum<=1e-6
            assert abs(result.capped_time_sum-saved.capped_min.sum())<=1e-6
            counts=[result.within_counts[t] for t in (40,45,50)]
            assert counts==expected[profile+'_'+state]
            parity[profile+'_'+state]={'rows':len(result.od_results),'max_error_min':maximum,
                                      'within_counts':counts,'capped_time_sum_min':result.capped_time_sum}
            if profile=='P' and state=='disrupted':baseline_disrupted={r.od_id:r for r in result.od_results}
    refs={r.od_id:(r.origin_id,r.destination_id) for r in e.get_od_table(model,'P')}
    smoke={};journey_receipt=None
    for sid in ids:
        if not sid.endswith('_A'):continue
        request=replace(e.baseline_request(model,'mitigated','P'),patches=(RoutingPatch(kind='activate_service',target_id=sid),))
        catalog.validate_request(request)
        result=e.evaluate_package(model,request);result.validate_request(request)
        assert EvaluationResult.from_json(result.to_json())==result
        improvements=[r for r in result.od_results if r.minutes is not None and (
            baseline_disrupted[r.od_id].minutes is None or r.minutes<baseline_disrupted[r.od_id].minutes-1e-6)]
        assert improvements,'No exercised improvement for '+sid
        chosen=min(improvements,key=lambda r:(r.minutes,r.od_id))
        journey=e.inspect_journey(model,request,*refs[chosen.od_id])
        assert JourneyResult.from_json(journey.to_json())==journey
        assert any(leg.route_id==sid for leg in journey.legs)
        assert abs(journey.total_min-chosen.minutes)<1e-6
        leg_sum=math.fsum(leg.total_min for leg in journey.legs)
        assert abs(journey.total_min-leg_sum)<1e-6
        waits=[leg.wait_min for leg in journey.legs if leg.route_id==sid and leg.wait_min>0]
        assert waits and all(abs(w-3.)<1e-6 for w in waits)
        smoke[sid]={'within_counts':dict(result.within_counts),'capped_time_sum_min':result.capped_time_sum,
                    'improved_od_count':len(improvements),'activated_journey_min':journey.total_min,
                    'evaluation_od_min':chosen.minutes,'leg_sum_min':leg_sum,'design_waits_min':waits,
                    'origin_id':journey.origin_id,'destination_id':journey.destination_id}
        if journey_receipt is None:
            journey_receipt={'request':request.to_dict(),'journey':journey.to_dict()}
    # No payload/manifest may change during construction or verification.
    assert sha(bundle/'manifest.json')==original_manifest
    for relative,digest in model['manifest']['files'].items():assert sha(bundle/relative)==digest,relative
    if original_csv is not None:
        assert (supplement/'source_stops.csv').read_bytes()==original_csv.read_bytes()
    return {'sys_executable':sys.executable,'shapely':shapely.__version__,'pyproj':pyproj.__version__,
            'supplement_hash':model['supplement_hash'],'model_version':catalog.model_version,
            'catalog_ids':ids,'units':{'segment_m':'metres','full_cycle_km':'kilometres','speed_kmh':'km/h',
                                      'base_headway_min':'minutes','dwell_s':'seconds','layover_min':'minutes'},
            'deterministic_byte_comparison_files':compared,'baseline_parity':parity,'smoke':smoke,
            'activated_journey':journey_receipt,'all_bundle_payload_hashes_unchanged':True,
            'bundle_manifest_sha256':original_manifest}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifact-dir',required=True,type=Path)
    parser.add_argument('--config-dir',required=True,type=Path)
    parser.add_argument('--report',required=True,type=Path)
    parser.add_argument('--original-csv',type=Path)
    args=parser.parse_args()
    receipt=verify(args.artifact_dir,args.config_dir,args.original_csv)
    args.report.write_text(json.dumps(receipt,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps({k:receipt[k] for k in ('catalog_ids','baseline_parity','smoke','all_bundle_payload_hashes_unchanged')},indent=2))

"""Run the explicitly SYNTHETIC phase-2 shuttle, never real M-line data."""
import argparse
from dataclasses import replace
import json
from pathlib import Path
import shutil
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))


def main():
    from citypilot import routing_engine as engine
    from citypilot.contracts import RoutingPatch
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifact-dir',required=True,type=Path)
    parser.add_argument('--service-id',choices=('SYN_INS_28_6','SYN_INS_28_9'),default='SYN_INS_28_6')
    args=parser.parse_args();bundle=args.artifact_dir.resolve()
    with tempfile.TemporaryDirectory(prefix='citypilot-synthetic-activation-') as temporary:
        config=Path(temporary)/'config';shutil.copytree(bundle/'config',config)
        shutil.copytree(ROOT/'tests/fixtures/prebuilt_services',config/'prebuilt_services')
        started=time.perf_counter();model=engine.load_model(bundle,config);load_ms=(time.perf_counter()-started)*1000
        request=replace(engine.baseline_request(model,'mitigated'),
            patches=(RoutingPatch(kind='activate_service',target_id=args.service_id),))
        catalog=engine.get_catalog(model);catalog.validate_request(request)
        result=engine.evaluate_package(model,request)
        journey=engine.inspect_journey(model,request,'origin:grid:32639:1328:14906','destination:metro_exit:44')
        for value in (catalog,request,result,journey):assert type(value).from_json(value.to_json())==value
        assert any(leg.route_id==args.service_id for leg in journey.legs)
        print(json.dumps({'synthetic':True,'request':request.to_dict(),'supplement_hash':model['supplement_hash'],
            'load_ms':load_ms,'evaluation_ms':result.duration_ms,'within_counts':dict(result.within_counts),
            'capped_time_sum_min':result.capped_time_sum,'origin_id':journey.origin_id,
            'destination_id':journey.destination_id,'journey_total_min':journey.total_min,
            'leg_sum_min':sum(leg.total_min for leg in journey.legs),
            'activated_board_waits_min':[leg.wait_min for leg in journey.legs if leg.route_id==args.service_id and leg.wait_min>0],
            'service_ids':sorted({leg.route_id for leg in journey.legs if leg.mode=='bus'}),
            'warnings':journey.warnings},ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False))


if __name__=='__main__':main()

"""Run baseline adapters from an explicit bundle, without executing notebooks."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from citypilot import routing_engine as routing


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifact-dir',required=True,type=Path)
    parser.add_argument('--config-dir',required=True,type=Path)
    parser.add_argument('--profile',choices=('P','B'),default='P')
    parser.add_argument('--state',choices=('normal','disrupted'),default='normal')
    parser.add_argument('--origin-id',default='origin:terminal:baku_international')
    parser.add_argument('--destination-id')
    args=parser.parse_args()
    model=routing.load_model(args.artifact_dir,args.config_dir)
    catalog=routing.get_catalog(model)
    request=routing.baseline_request(model,args.state,args.profile)
    result=routing.evaluate_package(model,request)
    destination=args.destination_id or next(iter(model['destinations']))
    journey=routing.inspect_journey(model,request,args.origin_id,destination)
    print(json.dumps({'interpreter':sys.executable,'contract_version':request.contract_version,'request':request.to_dict(),
        'config_hash':request.config_hash,'service_groups':list(catalog.service_groups),
        'state':request.state,'profile':request.profile,'od_pairs':len(result.od_results),
        'counts':dict(result.within_counts),
        'capped_time_sum':result.capped_time_sum,'duration_ms':result.duration_ms,
        'journey':{'origin':args.origin_id,'destination':destination,'status':journey.status,
            'physical_elapsed_min':journey.total_min,'leg_sum_min':sum(l.total_min for l in journey.legs),
            'legs':len(journey.legs),'geometry_type':journey.geometry.type if journey.geometry else None,
            'geometry_metadata':journey.geometry_metadata.to_dict()},
        'warnings':journey.warnings},ensure_ascii=False,indent=2,allow_nan=False))


if __name__=='__main__':main()

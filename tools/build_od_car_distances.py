"""Build the static modelled car-distance supplement offline from an explicit bundle."""
import argparse
import json
import math
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from citypilot.od_car_distances import build_supplement,DistanceError


def positive_finite(value):
    try:result=float(value)
    except ValueError:raise argparse.ArgumentTypeError('must be a positive finite metre value')
    if not math.isfinite(result) or result<=0:raise argparse.ArgumentTypeError('must be a positive finite metre value')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifact-dir',required=True,type=Path)
    parser.add_argument('--max-snap-m',required=True,type=positive_finite)
    parser.add_argument('--output-dir',type=Path,default=Path('outputs/od_car_distances_v1'))
    args=parser.parse_args()
    try:manifest=build_supplement(args.artifact_dir,args.output_dir,max_snap_m=args.max_snap_m)
    except (DistanceError,ValueError,OSError) as exc:parser.exit(1,str(exc)+'\n')
    print(json.dumps({'output_dir':str(args.output_dir.resolve()),
        'physical_status_counts':manifest['physical_status_counts'],'profile_status_counts':manifest['profile_status_counts'],
        'profile_rows':manifest['profile_row_count'],'exact_evaluator_id_joins':manifest['evaluator_id_verification'],
        'runtime_seconds':manifest['runtime_seconds'],'csv_sha256':manifest['output_sha256']['od_car_distances.csv']},indent=2,allow_nan=False))


if __name__=='__main__':main()

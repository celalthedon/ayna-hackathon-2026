"""Build an external, hash-registered constructed M-service supplement."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from citypilot.m_service_builder import build_supplement


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifact-dir',required=True,type=Path)
    parser.add_argument('--stops-csv',required=True,type=Path)
    parser.add_argument('--output-dir',required=True,type=Path)
    parser.add_argument('--max-snap-m',required=True,type=float)
    parser.add_argument('--detour-ratio',type=float,default=3.)
    args=parser.parse_args()
    try:
        report=build_supplement(args.artifact_dir,args.stops_csv,args.output_dir,
                                max_snap_m=args.max_snap_m,detour_ratio=args.detour_ratio)
    except (OSError,ValueError) as exc: parser.exit(1,str(exc)+'\n')
    print(json.dumps({k:report[k] for k in ('ready_service_ids','blocked_lines','cycles','supplement_manifest') if k in report},indent=2))


if __name__=='__main__':main()

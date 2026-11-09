#!/usr/bin/env python3
"""One bounded read-only query; no product output files or bytecode writes."""
import sys
sys.dont_write_bytecode=True
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import argparse
import json
from polar.state_reader import read_state,StateError
from polar.history_bundle import HistoryError

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path)
    parser.add_argument('--qitem')
    parser.add_argument('--attempt')
    parser.add_argument('--experiment')
    parser.add_argument('--max-age-seconds',type=int,default=300)
    parser.add_argument('--max-file-bytes',type=int,default=1024**2)
    parser.add_argument('--max-total-bytes',type=int,default=8*1024**2)
    args=parser.parse_args()
    try:
        value=read_state(root=args.root,qitem=args.qitem,attempt=args.attempt,experiment=args.experiment,
                         max_age_seconds=args.max_age_seconds,max_file_bytes=args.max_file_bytes,max_total_bytes=args.max_total_bytes)
        print(json.dumps(value,sort_keys=True,allow_nan=False))
    except (StateError,HistoryError,OSError,ValueError,TypeError):
        print(json.dumps({'schema':'polar.state-error/1','status':'UNKNOWN','reason':'INVALID_OR_UNAVAILABLE_QUERY'}))
        return 2
    return 0
if __name__=='__main__':raise SystemExit(main())

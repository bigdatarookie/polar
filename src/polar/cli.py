"""CLI and HTTP use the same Service/Registry application operations."""
import argparse
import json
import sys
import uuid
from pathlib import Path

from .config import Settings
from .models import RunConfig
from .service import Service


def main(argv=None):
    parser = argparse.ArgumentParser(prog="polar")
    subs = parser.add_subparsers(dest="command",required=True)
    for name in ["migrate","ready","datasets","runs","worker-once","worker"]:
        subs.add_parser(name)
    subs.add_parser("register").add_argument("file",type=Path)
    submit = subs.add_parser("submit")
    submit.add_argument("file",type=Path)
    submit.add_argument("--key",required=True)
    for name in ["status","report","cancel","evidence"]:
        subs.add_parser(name).add_argument("run_id",type=uuid.UUID)
    compare = subs.add_parser("compare")
    compare.add_argument("left",type=uuid.UUID)
    compare.add_argument("right",type=uuid.UUID)
    args = parser.parse_args(argv)
    try:
        s = Service(Settings.load())
        match args.command:
            case "migrate":
                s.registry.migrate()
                result = {"schema_version":1}
            case "ready": result = s.ready()
            case "register":
                if args.file.stat().st_size > 1024**2: raise ValueError("INPUT_TOO_LARGE")
                raw = args.file.read_bytes()
                result = s.registry.register_dataset(json.loads(raw),raw)
            case "datasets": result = s.registry.datasets()
            case "submit":
                if args.file.stat().st_size > 1024**2: raise ValueError("INPUT_TOO_LARGE")
                if not 1 <= len(args.key) <= 128: raise ValueError("INVALID_KEY")
                result = s.registry.submit(args.key,RunConfig.model_validate_json(args.file.read_bytes()))
            case "runs": result = s.registry.search()
            case "status": result = s.registry.get(args.run_id)
            case "cancel": result = s.registry.cancel(args.run_id)
            case "report": result = s.report(args.run_id)
            case "evidence":
                from .artifacts import verify
                row = s.registry.get(args.run_id)
                if row["state"] != "completed": raise ValueError("REPORT_NOT_COMPLETE")
                s.report(args.run_id)
                result = verify(s.artifacts.directory(row["artifact_ref"]))
            case "compare": result = s.compare(args.left,args.right)
            case "worker-once":
                from .worker import work_once
                result = work_once(Settings.load())
            case "worker":
                from .worker import run_forever
                run_forever()
                return
        print(json.dumps(result,default=str,sort_keys=True,allow_nan=False))
    except Exception as exc:
        # Exception messages can contain DSNs or payloads. Stable type only.
        print(json.dumps({"status":"ERROR","code":type(exc).__name__}),file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()

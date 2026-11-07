"""CLI and HTTP use the same Service/Registry application operations."""
import argparse
import json
import sys
import uuid
from pathlib import Path

from .models import RunConfig


def page_limit(value):
    number = int(value)
    if not 1 <= number <= 10:
        raise argparse.ArgumentTypeError("limit must be between 1 and 10")
    return number


def page_offset(value):
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("offset must be nonnegative")
    return number


def main(argv=None):
    parser = argparse.ArgumentParser(prog="polar")
    subs = parser.add_subparsers(dest="command",required=True)
    for name in ["migrate","ready","worker-once","worker"]:
        subs.add_parser(name)
    for name in ["datasets", "runs"]:
        listing = subs.add_parser(name)
        listing.add_argument("--limit",type=page_limit,default=10)
        listing.add_argument("--offset",type=page_offset,default=0)
        if name == "runs":
            listing.add_argument("--dataset-id")
    subs.add_parser("dataset").add_argument("dataset_id")
    subs.add_parser("register").add_argument("file",type=Path)
    subs.add_parser("inspect-dataset").add_argument("file",type=Path)
    subs.add_parser("history-migrate")
    subs.add_parser("history-experiment").add_argument("config_file", type=Path)
    historical = subs.add_parser("history-register")
    historical.add_argument("directory", type=Path)
    historical.add_argument("--manifest-sha256", required=True)
    historical = subs.add_parser("history-catalog")
    historical.add_argument("--limit", type=int, default=50)
    historical.add_argument("--cursor")
    historical = subs.add_parser("history-revision")
    historical.add_argument("dataset_id")
    historical.add_argument("revision")
    asof = subs.add_parser("asof-features")
    asof.add_argument("file",type=Path)
    asof.add_argument("--decision-at",required=True)
    submit = subs.add_parser("submit")
    submit.add_argument("file",type=Path)
    submit.add_argument("--key",required=True)
    for name in ["status","report","cancel","evidence"]:
        subs.add_parser(name).add_argument("run_id",type=uuid.UUID)
    compare = subs.add_parser("compare")
    compare.add_argument("left",type=uuid.UUID)
    compare.add_argument("right",type=uuid.UUID)
    args = parser.parse_args(argv)
    if args.command.startswith("history-"):
        from .history_bundle import HistoryError
        try:
            from .config import Settings
            from .history_registry import HistoryRegistry
            registry = HistoryRegistry(Settings.load())
            match args.command:
                case "history-experiment":
                    from .service import Service
                    from .history_bundle import decode
                    with args.config_file.open("rb") as stream:
                        raw = stream.read(8193)
                    if len(raw) > 8192: raise HistoryError("DESCRIPTIVE_INVALID_CONFIG")
                    result = Service(Settings.load()).history_experiment_run(decode(raw))
                case "history-migrate": result = registry.migrate()
                case "history-register": result = registry.register(args.directory, args.manifest_sha256)
                case "history-catalog": result = registry.catalog(args.limit, args.cursor)
                case "history-revision": result = registry.revision(args.dataset_id, args.revision)
            print(json.dumps(result, default=str, sort_keys=True, allow_nan=False))
            if args.command == "history-experiment" and result["status"] != "COMPLETED":
                raise SystemExit(1)
        except Exception as exc:
            code = exc.code if isinstance(exc, HistoryError) else "HISTORY_DEPENDENCY_UNAVAILABLE"
            print(json.dumps({"status":"ERROR", "code":code}), file=sys.stderr)
            raise SystemExit(1)
        return
    if args.command == "asof-features":
        from .feature_view import MAX_INPUT_BYTES, FeatureViewError, asof_features
        try:
            with args.file.open("rb") as source:
                raw = source.read(MAX_INPUT_BYTES + 1)
            result = asof_features(raw,args.decision_at)
        except (OSError, FeatureViewError) as exc:
            code = exc.code if isinstance(exc, FeatureViewError) else "INPUT_READ_ERROR"
            print(json.dumps({"status":"ERROR","code":code}),file=sys.stderr)
            raise SystemExit(1)
        print(json.dumps(result,sort_keys=True,allow_nan=False))
        return
    if args.command == "inspect-dataset":
        from .data_quality import MAX_INPUT_BYTES, InspectionError, inspect_dataset
        try:
            # Bounded read, including for streams/files that grow after opening.
            with args.file.open("rb") as source:
                raw = source.read(MAX_INPUT_BYTES + 1)
            result = inspect_dataset(raw)
        except (OSError, InspectionError) as exc:
            code = exc.code if isinstance(exc, InspectionError) else "INPUT_READ_ERROR"
            print(json.dumps({"status":"ERROR","code":code}),file=sys.stderr)
            raise SystemExit(1)
        print(json.dumps(result,sort_keys=True,allow_nan=False))
        return
    try:
        from .config import Settings
        from .service import Service
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
            case "datasets": result = s.registry.datasets(args.limit,args.offset)
            case "dataset": result = s.dataset(args.dataset_id)
            case "submit":
                if args.file.stat().st_size > 1024**2: raise ValueError("INPUT_TOO_LARGE")
                if not 1 <= len(args.key) <= 128: raise ValueError("INVALID_KEY")
                result = s.registry.submit(args.key,RunConfig.model_validate_json(args.file.read_bytes()))
            case "runs": result = s.registry.search(args.limit,args.offset,args.dataset_id)
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
        from .registry import BudgetExceeded, NotFound
        from .service import DatasetIntegrityError
        code = type(exc).__name__
        if isinstance(exc, BudgetExceeded):
            code = "RETAINED_STORAGE_ADMISSION_LIMIT" if str(exc) == "RETAINED_STORAGE_ADMISSION_LIMIT" else "BUDGET_EXCEEDED"
        if args.command == "dataset":
            if isinstance(exc, DatasetIntegrityError): code = "DATASET_INTEGRITY_ERROR"
            elif isinstance(exc, NotFound): code = "DATASET_NOT_FOUND"
        print(json.dumps({"status":"ERROR","code":code}),file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()

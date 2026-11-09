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
    for name in ("hyp007-diagnostic-prepare", "hyp007-diagnostic-run"):
        subs.add_parser(name).add_argument("file", type=Path)
    subs.add_parser("hyp007-diagnostic-attempt").add_argument("attempt_id")
    subs.add_parser("hyp007-diagnostic-report").add_argument("experiment_id")
    for name in ("gym-preflight", "gym-run", "gym-replay"):
        gym = subs.add_parser(name)
        gym.add_argument("file", type=Path)
        if name == "gym-replay": gym.add_argument("experiment_id")
    subs.add_parser("gym-attempt").add_argument("attempt_id")
    subs.add_parser("gym-report").add_argument("experiment_id")
    subs.add_parser("obs158-code")
    for name in ("obs158-preflight","obs158-run","obs158-replay"):
        command=subs.add_parser(name)
        command.add_argument("file",type=Path)
        command.add_argument("--artifact-root",type=Path,required=True)
        command.add_argument("--storage-bytes",type=int,default=64*1024**3)
        if name=="obs158-replay":command.add_argument("experiment_id")
    for name,key in (("obs158-attempt","attempt_id"),("obs158-report","experiment_id")):
        command=subs.add_parser(name);command.add_argument(key)
        command.add_argument("--artifact-root",type=Path,required=True)
        command.add_argument("--storage-bytes",type=int,default=64*1024**3)
    partial = subs.add_parser("hyp003-prepare")
    partial.add_argument("config_file", type=Path)
    partial.add_argument("--output-dir", type=Path, required=True)
    partial = subs.add_parser("hyp003-preparation-report")
    partial.add_argument("preparation_id")
    partial.add_argument("--output-dir", type=Path, required=True)
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
    if args.command.startswith("hyp003-"):
        from .hyp003_preparation import prepare_partial_input, write_preparation, read_preparation
        from .hyp003_source import PreparationError, Sources, CONFIG_LIMIT, decode
        from .history_bundle import HistoryError
        try:
            if args.command == "hyp003-prepare":
                path=args.config_file.absolute()
                raw,_=Sources().read(path.parent,path.name,CONFIG_LIMIT)
                prepared=prepare_partial_input(decode(raw))
                import hashlib
                prepared['physical']['config_source_sha256']=hashlib.sha256(raw).hexdigest()
                result=write_preparation(prepared,args.output_dir)
            else:
                result=read_preparation(args.output_dir,args.preparation_id)
            print(json.dumps(result,sort_keys=True,allow_nan=False))
        except (PreparationError,HistoryError,OSError,ValueError,TypeError) as exc:
            code=exc.code if isinstance(exc,PreparationError) else "HYP003_INPUT_OR_OUTPUT_UNAVAILABLE"
            print(json.dumps({"schema":"polar.hyp003-preparation-error/1","status":"ERROR","code":code}),file=sys.stderr)
            raise SystemExit(1)
        return
    if args.command.startswith("obs158-"):
        from .obs158_contract import decode,source_code
        from .obs158_math import Obs158Error
        try:
            if args.command=="obs158-code":
                result={"schema":"polar.obs158-code/1","source_code":source_code()}
            else:
                from .obs158_service import Obs158Service
                from .obs158_store import Obs158Store
                if not 1<=args.storage_bytes<=64*1024**3:raise Obs158Error("INVALID_STORAGE_ALLOCATION")
                service=Obs158Service(Obs158Store(args.artifact_root,args.storage_bytes))
                operation=args.command.removeprefix("obs158-")
                if operation in ("preflight","run","replay"):
                    with args.file.open("rb") as stream:raw=stream.read(1024**2+1)
                    if len(raw)>1024**2:raise Obs158Error("OBS158_CONFIG_BOUND")
                    config=decode(raw)
                    result=(service.obs158_replay(config,args.experiment_id) if operation=="replay"
                            else getattr(service,"obs158_"+operation)(config))
                else:result=getattr(service,"obs158_"+operation)(
                    args.attempt_id if operation=="attempt" else args.experiment_id)
            print(json.dumps(result,sort_keys=True,allow_nan=False))
            if result.get("status") in ("FAILED","UNFINALIZED"):raise SystemExit(1)
        except Exception as exc:
            print(json.dumps({"schema":"polar.obs158-error/1","status":"ERROR",
                  "code":str(exc) if isinstance(exc,Obs158Error) else "OBS158_DEPENDENCY_OR_RECORD_INVALID"}),
                  file=sys.stderr)
            raise SystemExit(1)
        return
    if args.command.startswith("gym-"):
        from .gym_contract import GymError, MAX_BYTES, decode
        try:
            from .config import Settings
            from .service import Service
            service = Service(Settings.load())
            operation = args.command.removeprefix("gym-")
            if operation in ("preflight", "run", "replay"):
                with args.file.open("rb") as stream: raw = stream.read(MAX_BYTES+1)
                if len(raw) > MAX_BYTES: raise GymError("INPUT_LIMIT")
                config = decode(raw)
                result = (service.gym_replay(config, args.experiment_id) if operation == "replay"
                          else getattr(service, "gym_"+operation)(config))
            else:
                result = getattr(service, "gym_"+operation)(args.attempt_id if operation == "attempt" else args.experiment_id)
            print(json.dumps(result, sort_keys=True, allow_nan=False))
            if operation == "preflight" and not result["preflight"]["execution_allowed"]: raise SystemExit(1)
            if result.get("status") in ("FAILED", "UNFINALIZED"): raise SystemExit(1)
        except Exception as exc:
            print(json.dumps({"schema":"polar.gym-error/1", "status":"ERROR",
                              "code":str(exc) if isinstance(exc,GymError) else "GYM_DEPENDENCY_OR_RECORD_INVALID"}),file=sys.stderr)
            raise SystemExit(1)
        return
    if args.command.startswith("hyp007-diagnostic-"):
        from .hyp007_contract import DiagnosticError, MAX_FILE, decode
        try:
            from .config import Settings
            from .service import Service
            service = Service(Settings.load())
            operation = args.command.removeprefix("hyp007-diagnostic-")
            if operation in ("prepare", "run"):
                with args.file.open("rb") as stream:
                    raw = stream.read(MAX_FILE+1)
                if len(raw) > MAX_FILE:
                    raise DiagnosticError("HYP007_INPUT_LIMIT")
                argument = decode(raw)
            else:
                argument = args.attempt_id if operation == "attempt" else args.experiment_id
            result = getattr(service, "hyp007_diagnostic_"+operation)(argument)
            print(json.dumps(result, sort_keys=True, allow_nan=False))
            if result.get("status") == "NOT_BOUND":
                raise SystemExit(2)
            if result.get("status") in ("FAILED", "UNFINALIZED"):
                raise SystemExit(1)
        except Exception as exc:
            code = exc.code if isinstance(exc, DiagnosticError) else "HYP007_DEPENDENCY_OR_RECORD_INVALID"
            print(json.dumps({"schema": "polar.hyp007-error/1", "status": "ERROR", "code": code}), file=sys.stderr)
            raise SystemExit(1)
        return
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

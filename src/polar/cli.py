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
    subs.add_parser("import-plan").add_argument("file",type=Path)
    imp = subs.add_parser("import-cache-import")
    imp.add_argument("file",type=Path);imp.add_argument("--fixture",action="store_true")
    subs.add_parser("import-status").add_argument("plan_id")
    subs.add_parser("import-attempts").add_argument("plan_id")
    imp = subs.add_parser("import-attempt-path");imp.add_argument("plan_id");imp.add_argument("attempt_id")
    imp = subs.add_parser("import-result");imp.add_argument("plan_id");imp.add_argument("job_id")
    for name in ("import-execute","import-resume"):
        imp = subs.add_parser(name);imp.add_argument("plan_id")
        imp.add_argument("--attempt-id")
        imp.add_argument("--scope-file",type=Path)
        source = imp.add_mutually_exclusive_group(required=True)
        source.add_argument("--fixture",type=Path);source.add_argument("--network",action="store_true")
    imp = subs.add_parser("import-control")
    imp.add_argument("plan_id");imp.add_argument("action",choices=("pause","resume","stop"))
    for name in ("import-terminal","import-consume"):
        imp = subs.add_parser(name);imp.add_argument("plan_id");imp.add_argument("attempt_id")
        imp.add_argument("--manifest-sha256",required=True)
        if name=="import-consume": imp.add_argument("--assessment",type=Path,required=True)
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
    partial = subs.add_parser("hyp003-prepare")
    partial.add_argument("config_file", type=Path)
    partial.add_argument("--output-dir", type=Path, required=True)
    partial = subs.add_parser("hyp003-preparation-report")
    partial.add_argument("preparation_id")
    partial.add_argument("--output-dir", type=Path, required=True)
    partial = subs.add_parser("hyp003-availability")
    partial.add_argument("config_file",type=Path)
    partial.add_argument("--output-dir",type=Path,required=True)
    subs.add_parser("hyp003-availability-report").add_argument("output_dir",type=Path)
    partial = subs.add_parser("hyp003-observability")
    partial.add_argument("config_file",type=Path)
    partial.add_argument("--output-dir",type=Path,required=True)
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
    for operation in ("prepare","seal","run"):
        subs.add_parser("hyp008-s1-"+operation).add_argument("file",type=Path)
    for operation in ("attempt","report","verify-stored"):
        subs.add_parser("hyp008-s1-"+operation).add_argument("identifier")
    args = parser.parse_args(argv)
    if args.command.startswith("hyp008-s1-"):
        from .hyp008_s1_service import configured_operation
        from .hyp008_s1_contract import decode
        try:
            operation=args.command.removeprefix("hyp008-s1-").replace("-","_")
            if hasattr(args,"file"):
                from .hyp008_s1_contract import MAX_FILE
                with args.file.open("rb") as stream:value=decode(stream.read(MAX_FILE+1))
            else:value=args.identifier
            result=configured_operation(operation,value)
            print(json.dumps(result,sort_keys=True,allow_nan=False))
            if result.get("status") in ("NOT_BOUND","UNFINALIZED","PLANNED_FAMILY_UNAVAILABLE"):raise SystemExit(1)
        except (ValueError,KeyError,TypeError,OSError) as exc:
            print(json.dumps({"status":"NOT_BOUND","reason":str(exc)}),file=sys.stderr)
            raise SystemExit(1)
        return
    if args.command.startswith("import-"):
        import hashlib
        from .import_contract import ImportError, MAX_FILE, decode
        def bounded(path):
            with path.open("rb") as stream: value=stream.read(MAX_FILE+1)
            if len(value)>MAX_FILE: raise ImportError("IMPORT_INPUT_LIMIT")
            return decode(value)
        def scope_ref(path):
            if path is None:return None
            with path.open("rb") as stream:value=stream.read(MAX_FILE+1)
            if len(value)>MAX_FILE:raise ImportError("IMPORT_INPUT_LIMIT")
            return {"path":str(path.absolute()),"sha256":hashlib.sha256(value).hexdigest()}
        try:
            from .config import Settings
            from .service import Service
            service = Service(Settings.load())
            match args.command:
                case "import-plan": result=service.import_plan(bounded(args.file))
                case "import-cache-import": result=service.import_cache_import(bounded(args.file),args.fixture)
                case "import-status": result=service.import_status(args.plan_id)
                case "import-attempts": result=service.import_attempts(args.plan_id)
                case "import-attempt-path": result=service.import_attempt_path(args.plan_id,args.attempt_id)
                case "import-result": result=service.import_result(args.plan_id,args.job_id)
                case "import-execute" | "import-resume":
                    result=service.import_execute(args.plan_id,fixture=bounded(args.fixture) if args.fixture else None,
                                                  network=args.network,attempt_id=args.attempt_id,
                                                  scope=scope_ref(args.scope_file))
                case "import-control": result=service.import_control(args.plan_id,args.action)
                case "import-terminal": result=service.import_terminal(args.plan_id,args.attempt_id,args.manifest_sha256)
                case "import-consume": result=service.import_consume(args.plan_id,args.attempt_id,args.manifest_sha256,
                                                                     bounded(args.assessment))
            print(json.dumps(result,sort_keys=True,allow_nan=False))
            if result.get("status") in ("partial","failed","interrupted"): raise SystemExit(2)
        except Exception as exc:
            print(json.dumps({"schema":"polar.import-error/1","status":"ERROR",
                              "code":exc.code if isinstance(exc,ImportError) else "IMPORT_DEPENDENCY_OR_RECORD_INVALID"}),
                  file=sys.stderr)
            raise SystemExit(1)
        return
    if args.command.startswith("hyp003-"):
        from .hyp003_preparation import prepare_partial_input, write_preparation, read_preparation
        from .hyp003_source import PreparationError, Sources, CONFIG_LIMIT, decode
        from .history_bundle import HistoryError
        try:
            if args.command == "hyp003-observability":
                from .hyp003_observability import write_observability
                path=args.config_file.absolute()
                raw,_=Sources().read(path.parent,path.name,CONFIG_LIMIT)
                result=write_observability(decode(raw),args.output_dir)
            elif args.command in ("hyp003-availability","hyp003-availability-report"):
                from .hyp003_availability import write_availability,read_availability
                if args.command=="hyp003-availability":
                    path=args.config_file.absolute()
                    raw,_=Sources().read(path.parent,path.name,CONFIG_LIMIT)
                    result=write_availability(decode(raw),args.output_dir)
                else:result=read_availability(args.output_dir)
            elif args.command == "hyp003-prepare":
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

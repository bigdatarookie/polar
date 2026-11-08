"""One supported HYP007 Service operation, with explicit sealing/admission boundaries."""
import os
from pathlib import Path
import resource
import hashlib
import sys
import time
import uuid

from .history_bundle import read_file, safe_root
from .hyp007_contract import (PROTOCOL, MAX_FILE, MAX_OUTPUT, DiagnosticError, check, exact,
                              hexhash, canonical, decode, sha, utc, now, definitions)
from .hyp007_source import Source
from .hyp007_panel import Panel
from .hyp007_store import DiagnosticStore, FILES
from .hyp007_numeric import THREAD_ENV

BINDINGS = {"protocol", "source_projection", "accepted_tree", "build", "learner_defaults", "qa",
            "execution_assignment", "resource_policy"}
PROJECTION_FILES = {"service.py", "cli.py", "history_store.py", "history_bundle.py", "process_budget.py"}


def source_projection():
    root = Path(__file__).parent
    paths = PROJECTION_FILES | {p.name for p in root.glob("hyp007_*.py")}
    result = {name: sha((root/name).read_bytes()) for name in sorted(paths)}
    result["@build-reference"] = sha((root.parents[1]/"hyp007-build-reference.json").read_bytes())
    result["hyp007_schema.json"] = sha((root/"hyp007_schema.json").read_bytes())
    return result


def binding(ref):
    exact(ref, {"path", "sha256"})
    hexhash(ref["sha256"])
    check(type(ref["path"]) is str and Path(ref["path"]).is_absolute(), "HYP007_BINDING_PATH")
    path = Path(ref["path"])
    raw = read_file(safe_root(path.parent), path.name, limit=MAX_FILE)
    check(sha(raw) == ref["sha256"], "HYP007_BINDING_HASH")
    return raw


def verify_build(raw, defaults_raw):
    import importlib.metadata
    build = decode(raw)
    reference = decode((Path(__file__).parents[2]/"hyp007-build-reference.json").read_bytes())
    check(build["schema"] == "polar.hyp007-numeric-build/3" and
          sha(raw) == reference["artifacts"]["BUILD-LOCK.json"] and
          sha(defaults_raw) == reference["artifacts"]["learner-defaults.json"] and
          build["source_commit"] == "d02a01ac6f51d36c9e62388243bcb75c3b1b1774" and
          build["learner_defaults_sha256"] == sha(defaults_raw), "HYP007_BUILD_MISMATCH")
    check(build["runtime_files"] and build["runtime_packages"] and build["numeric_image_id"], "HYP007_BUILD_MISMATCH")
    for name, version in {**build["runtime_packages"], **build["legacy_packages"]}.items():
        check(importlib.metadata.version(name) == version, "HYP007_PACKAGE_MISMATCH")
    total = 0
    for path, expected in build["runtime_files"].items():
        check(Path(path).is_absolute(), "HYP007_BUILD_PATH")
        digest = hashlib.sha256()
        with Path(path).open("rb") as stream:
            while chunk := stream.read(1024**2):
                total += len(chunk)
                digest.update(chunk)
        check(digest.hexdigest() == expected, "HYP007_RUNTIME_FILE_HASH")
    return {"runtime_verified_bytes": total, "runtime_verified_files": len(build["runtime_files"])}


def validate_seal(seal):
    exact(seal, {"schema", "prepared", "sealed_at", "bindings", "seal_id"}, "polar.hyp007-seal/1")
    check(seal["seal_id"] == sha(canonical({k:v for k,v in seal.items() if k != "seal_id"})), "HYP007_SEAL_HASH")
    utc(seal["sealed_at"])
    check(utc(seal["sealed_at"]) <= utc(now()), "HYP007_FUTURE_SEAL")
    prepared = seal["prepared"]
    exact(prepared, {"schema", "status", "config", "inventory", "roster", "structural", "definitions", "prepare_id"},
          "polar.hyp007-prepare/1")
    check(prepared["prepare_id"] == sha(canonical({k:v for k,v in prepared.items() if k != "prepare_id"})) and
          prepared["definitions"] == definitions(), "HYP007_PREPARATION_HASH")
    check(type(seal["bindings"]) is dict and set(seal["bindings"]) <= BINDINGS, "HYP007_BINDING_FIELDS")
    return [key for key in sorted(BINDINGS) if not seal["bindings"].get(key)]


class DiagnosticService:
    def __init__(self, store):
        self.store = store

    def prepare(self, cfg):
        source = Source(decode(canonical(cfg)))
        prepared = source.preparation()
        panel = Panel(source, source.evidence)
        packets = panel.packets(compute=False)
        prepared["structural"] = {"instruments": prepared["structural"], "packets": packets,
                                  "opportunities": panel.structural(packets),
                                  "final_finite_masks": "NOT_COMPUTED"}
        prepared.pop("prepare_id")
        prepared["prepare_id"] = sha(canonical(prepared))
        check(len(canonical(prepared)) <= MAX_FILE, "HYP007_PREPARATION_SIZE")
        self.store.prepare(prepared)
        return prepared

    def run(self, seal):
        seal = decode(canonical(seal))
        started_wall = time.monotonic()
        started_cpu = resource.getrusage(resource.RUSAGE_SELF)
        missing = validate_seal(seal)
        authorization = self.store.root/"hyp007-authorizations"/(seal["seal_id"]+".json")
        if not authorization.exists():
            missing.append("LATER_NATIVE_EXECUTION_AUTHORIZATION")
        if missing:
            return {"schema": "polar.hyp007-admission/1", "status": "NOT_BOUND", "missing": missing,
                    "real_fits_started": 0, "labels_computed": False}
        values = {key: binding(ref) for key,ref in seal["bindings"].items()}
        cutoff = utc(seal["sealed_at"]).timestamp()
        check(all(Path(ref["path"]).stat().st_mtime <= cutoff for ref in seal["bindings"].values()),
              "HYP007_OBJECT_AFTER_SEAL")
        check(sha(values["protocol"]) == PROTOCOL, "HYP007_PROTOCOL_HASH")
        projection = decode(values["source_projection"])
        check(projection == source_projection(), "HYP007_SOURCE_PROJECTION")
        tree = decode(values["accepted_tree"])
        exact(tree, {"schema", "commit", "tree"}, "polar.hyp007-accepted-source/1")
        check(all(type(tree[k]) is str and len(tree[k]) == 40 and all(c in "0123456789abcdef" for c in tree[k])
                  for k in ("commit", "tree")), "HYP007_ACCEPTED_SOURCE")
        policy = decode(values["resource_policy"])
        check(policy == {"cpu_seconds": 600, "wall_seconds": 900, "logical_opportunity_limit": 100000,
                         "real_fit_limit": 9}, "HYP007_RESOURCE_POLICY")
        qa = decode(values["qa"])
        exact(qa, {"schema", "source_projection_sha256", "build_sha256", "verdicts", "proof_objects"},
              "polar.hyp007-qualification/1")
        check(qa["source_projection_sha256"] == sha(values["source_projection"]) and
              qa["build_sha256"] == sha(values["build"]) and
              qa["verdicts"] == {"code": "PASS", "system": "PASS", "numeric": "PASS"}, "HYP007_QA_NOT_BOUND")
        for proof in qa["proof_objects"]:
            binding(proof)
        check(len(qa["proof_objects"]) >= 3, "HYP007_QA_NOT_BOUND")
        assignment = decode(values["execution_assignment"])
        exact(assignment, {"schema", "native_qitem", "operation", "source_projection_sha256", "scope"},
              "polar.hyp007-execution-assignment/1")
        check(assignment["operation"] == "HYP007_SOURCE_COHORT_PREDICTOR_V1_1" and
              assignment["scope"] == "ONE_REAL_FAMILY_NINE_FITS" and
              assignment["source_projection_sha256"] == sha(values["source_projection"]) and
              assignment["native_qitem"].startswith("qitem-"), "HYP007_EXECUTION_NOT_ADMITTED")
        auth_raw = read_file(safe_root(authorization.parent), authorization.name, limit=65536)
        auth = decode(auth_raw)
        check(auth == {"schema": "polar.hyp007-local-authorization/1", "seal_id": seal["seal_id"],
                       "execution_assignment_sha256": sha(values["execution_assignment"]),
                       "accepted_commit": tree["commit"], "accepted_tree": tree["tree"]},
              "HYP007_EXECUTION_NOT_ADMITTED")
        # The later operator provisions this exact seal-specific record. No implementation CLI creates it.
        check(sys.platform == "linux", "HYP007_EXECUTABLE_BUILD_UNAVAILABLE")
        check(os.environ.get("POLAR_HYP007_BUILD_SHA256") == sha(values["build"]), "HYP007_BUILD_MISMATCH")
        # Native package verification is performed again by the budgeted child before numerical import.
        # Every source/qualification object must have been retained at sealing; verify exact objects again in child.
        prep = self.store.read_record("hyp007-preparations", seal["prepared"]["prepare_id"])
        check(prep == seal["prepared"], "HYP007_PREPARATION_CHANGED")
        check((self.store.root/"hyp007-preparations"/prep["prepare_id"]/"record.json").stat().st_mtime <= cutoff,
              "HYP007_OBJECT_AFTER_SEAL")
        aid = str(uuid.uuid4())
        self.store.begin(seal, aid)
        parent = "hyp007-attempts/"+aid
        self.store.record(parent, "request", seal)
        from .process_budget import supervise
        env = {**os.environ, **THREAD_ENV, "PYTHONDONTWRITEBYTECODE": "1"}
        elapsed = time.monotonic()-started_wall
        cpu = resource.getrusage(resource.RUSAGE_SELF)
        own_cpu = cpu.ru_utime+cpu.ru_stime-started_cpu.ru_utime-started_cpu.ru_stime
        try:
            resources = supervise([sys.executable, "-m", "polar.hyp007_worker", str(self.store.root), aid,
                                   str(self.store.limit)], env=env,
                                  output=self.store.root/parent/"worker.log",
                                  cpu_seconds=max(0,600-own_cpu), wall_seconds=max(0,900-elapsed))
            resources["preflight_cpu_seconds"] = own_cpu
            resources["preflight_wall_seconds"] = elapsed
            resources["cpu_seconds"] += own_cpu
            resources["wall_seconds"] += elapsed
            check(resources["failure"] is None and resources["exit_code"] == 0 and
                  resources["cleanup"] == "COMPLETE", "HYP007_EXECUTION_FAILED")
            files = {}
            for name in FILES-{"resources.json", "fit-slots.json"}:
                files[name] = read_file(self.store.root, parent+"/output/"+name, limit=MAX_FILE)
            files["resources.json"] = canonical(resources)
            files["fit-slots.json"] = canonical(self.store.slots(aid))
            check(all(s["status"] in ("SUCCESS", "SUCCESS_NATIVE_CONSTANT") for s in self.store.slots(aid)),
                  "HYP007_SLOT_INCOMPLETE")
            eid = "hyp007-"+seal["seal_id"]
            manifest = self.store.publish(eid, files)
            cpu = resource.getrusage(resource.RUSAGE_SELF)
            resources["finalization_cpu_seconds"] = cpu.ru_utime+cpu.ru_stime-started_cpu.ru_utime-started_cpu.ru_stime-own_cpu
            resources["total_wall_seconds"] = time.monotonic()-started_wall
            check(resources["cpu_seconds"]+resources["finalization_cpu_seconds"] <= 600 and
                  resources["total_wall_seconds"] <= 900, "HYP007_RESOURCE_LIMIT")
            self.store.finish(aid, "COMPLETED", None, resources, eid, sha(canonical(manifest)))
            return self.store.attempt(aid)
        except Exception as exc:
            resources = locals().get("resources", {"status": "UNAVAILABLE_AFTER_SUPERVISOR_FAILURE"})
            code = exc.code if isinstance(exc, DiagnosticError) else "HYP007_EXECUTION_FAILED"
            self.store.finish(aid, "FAILED", code, resources)
            return self.store.attempt(aid)

    def attempt(self, aid):
        return self.store.attempt(aid)

    def report(self, eid):
        result = self.store.report(eid)
        aid = result["report"]["attempt_id"]
        attempt = self.store.attempt(aid)
        check(attempt["status"] == "COMPLETED" and attempt["receipt"]["experiment_id"] == eid,
              "HYP007_REPORT_NOT_COMPLETE")
        check(attempt["receipt"]["manifest_sha256"] == sha(canonical(result["manifest"])), "HYP007_MANIFEST_HASH")
        return result

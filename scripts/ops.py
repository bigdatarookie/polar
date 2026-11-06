"""Explicit task-only backup / fresh-volume restore. SRE executes after review.

No cleanup, reset, prune or source-volume deletion exists here. Helpers leave
normal services stopped; an operator inspects and explicitly resumes them.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ["docker","compose","-p","polar","-f",str(ROOT/"compose.yaml")]


def run(args,**kwargs):
    return subprocess.run(args,check=True,**kwargs)


def check_ownership():
    result = run(COMPOSE+["ps","-aq"],capture_output=True,text=True)
    ids = result.stdout.split()
    if not ids:
        raise SystemExit("No task containers found; refuse ambiguous backup/restore")
    items = json.loads(run(["docker","inspect",*ids],capture_output=True,text=True).stdout)
    for item in items:
        labels = item["Config"]["Labels"]
        if labels.get("com.docker.compose.project") != "polar" or labels.get("com.docker.compose.project.working_dir") != str(ROOT):
            raise SystemExit("Container ownership mismatch")
    for var,default in [("POLAR_DB_VOLUME","polar_fixture_db"),("POLAR_ARTIFACT_VOLUME","polar_fixture_artifacts")]:
        name = os.environ.get(var,default)
        info = json.loads(run(["docker","volume","inspect",name],capture_output=True,text=True).stdout)[0]
        if info.get("Labels",{}).get("polar.scope") != "POL.0.4.0.1":
            raise SystemExit("Volume scope mismatch")


def stream_helper(code,output=None,input=None,environment=None):
    service = "snapshot" if output is not None else "restore-artifacts"
    args = COMPOSE+["run","--rm","--no-deps","-T","--entrypoint","python",service,"-c",code]
    run(args,stdout=output,stdin=input,env=environment)


def backup(target):
    check_ownership()
    target.mkdir(mode=0o700,parents=True,exist_ok=False)
    # Stop admission first; allow only a quiescent snapshot, never silently kill
    # an active job to make a backup appear successful.
    run(COMPOSE+["stop","api"])
    count = run(COMPOSE+["exec","-T","db","psql","-U","polar","-d","polar","-Atc",
                         "SELECT count(*) FROM runs WHERE state IN ('running','queued')"],capture_output=True,text=True).stdout.strip()
    if count != "0":
        raise SystemExit("Jobs still pending/running; API remains stopped. Drain explicitly before backup.")
    run(COMPOSE+["stop","worker"])
    running = run(COMPOSE+["ps","--status","running","--services"],capture_output=True,text=True).stdout.split()
    if "evaluator" in running:
        raise SystemExit("Evaluator must finish before backup")
    with (target/"metadata.dump").open("xb") as f:
        run(COMPOSE+["exec","-T","db","pg_dump","-U","polar","-d","polar","-Fc"],stdout=f)
    code = "import tarfile,sys; t=tarfile.open(fileobj=sys.stdout.buffer,mode='w|'); t.add('/data/artifacts',arcname='artifacts'); t.close()"
    with (target/"artifacts.tar").open("xb") as f:
        stream_helper(code,output=f)
    manifest = {"schema_version":1,"scope":"POL.0.4.0.1","code_revision":os.environ.get("POLAR_CODE_REVISION","UNRECORDED"),
                "files":{name:sha(target/name) for name in ["metadata.dump","artifacts.tar"]},
                "consistency":"QUIESCENT","restore_effect":"NOT_RUN"}
    (target/"backup-manifest.json").write_text(json.dumps(manifest,sort_keys=True,indent=2)+"\n")
    print("Snapshot created; API/worker remain stopped. Restore effect NOT RUN.")


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024**2),b""): h.update(chunk)
    return h.hexdigest()


def restore(source,suffix):
    if not suffix.isalnum() or not 6<=len(suffix)<=24:
        raise SystemExit("Use a unique 6-24 character alphanumeric restore suffix")
    check_ownership()
    count = run(COMPOSE+["exec","-T","db","psql","-U","polar","-d","polar","-Atc",
                         "SELECT count(*) FROM runs WHERE state IN ('running','queued')"],capture_output=True,text=True).stdout.strip()
    if count != "0": raise SystemExit("Source has unfinished jobs; refuse to stop it for restore")
    manifest = json.loads((source/"backup-manifest.json").read_bytes())
    if manifest.get("scope") != "POL.0.4.0.1" or set(manifest["files"]) != {"metadata.dump","artifacts.tar"}:
        raise SystemExit("Invalid snapshot manifest")
    for name,h in manifest["files"].items():
        if sha(source/name) != h: raise SystemExit("Snapshot checksum mismatch")
    prefix = "polar_restore_"+suffix
    env = {**os.environ,"POLAR_DB_VOLUME":prefix+"_db","POLAR_ARTIFACT_VOLUME":prefix+"_artifacts",
           "POLAR_EVALUATION_VOLUME":prefix+"_evaluations","POLAR_NETWORK":prefix+"_service","POLAR_API_PORT":"18081"}
    # Fresh names are a hard precondition. Never overwrite an existing volume.
    for name in [env["POLAR_DB_VOLUME"],env["POLAR_ARTIFACT_VOLUME"],env["POLAR_EVALUATION_VOLUME"]]:
        found = subprocess.run(["docker","volume","inspect",name],capture_output=True)
        if found.returncode == 0: raise SystemExit("Restore volume already exists")
        if b"no such volume" not in found.stderr.lower(): raise SystemExit("Cannot establish fresh-volume identity")
    # Same Compose project, separate names; source named volumes survive replacement.
    # Stay within the aggregate resource ceiling; no normal worker/evaluator runs.
    run(COMPOSE+["stop","api","worker","evaluator","db"])
    run(COMPOSE+["up","-d","--wait","db"],env=env)
    with (source/"metadata.dump").open("rb") as f:
        run(COMPOSE+["exec","-T","db","pg_restore","-U","polar","-d","polar","--exit-on-error","--no-owner"],stdin=f,env=env)
    code = "import tarfile,sys; t=tarfile.open(fileobj=sys.stdin.buffer,mode='r|'); t.extractall('/data',filter='data'); t.close()"
    with (source/"artifacts.tar").open("rb") as f:
        stream_helper(code,input=f,environment=env)
    # Explicit read-only API only: never recompute to conceal a bad restore.
    run(COMPOSE+["up","-d","--no-deps","api"],env=env)
    (source/("restore-"+suffix+".json")).write_text(json.dumps({k:v for k,v in env.items() if k in ["POLAR_DB_VOLUME","POLAR_ARTIFACT_VOLUME","POLAR_EVALUATION_VOLUME","POLAR_NETWORK","POLAR_API_PORT"]},indent=2)+"\n")
    print("Fresh restore imported. Verify the original report via 127.0.0.1:18081 without worker. Acceptance NOT RUN.")


def evaluate():
    check_ownership()
    running = run(COMPOSE+["ps","--status","running","--services"],capture_output=True,text=True).stdout.split()
    if any(s in running for s in ["worker","evaluator","snapshot","restore-artifacts","migrate"]):
        raise SystemExit("Stop the task worker and other helpers before isolated evaluator invocation")
    run(COMPOSE+["run","--rm","--no-deps","-T","evaluator"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers(dest="operation",required=True)
    subs.add_parser("backup").add_argument("directory",type=Path)
    p = subs.add_parser("restore")
    p.add_argument("directory",type=Path)
    p.add_argument("--suffix",required=True)
    subs.add_parser("evaluate")
    args = parser.parse_args()
    if args.operation == "backup": backup(args.directory)
    elif args.operation == "restore": restore(args.directory,args.suffix)
    else: evaluate()

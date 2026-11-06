"""Explicit task-only backup / fresh-volume restore. SRE executes after review.

No cleanup, reset, prune or source-volume deletion exists here. Helpers leave
normal services stopped; an operator inspects and explicitly resumes them.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ["docker","compose","-p","polar","-f",str(ROOT/"compose.yaml")]


def run(args,**kwargs):
    return subprocess.run(args,check=True,**kwargs)


def container_ownership(items):
    for item in items:
        labels = item["Config"]["Labels"]
        if labels.get("com.docker.compose.project") != "polar" or labels.get("com.docker.compose.project.working_dir") != str(ROOT):
            raise SystemExit("Container ownership mismatch")


def check_ownership():
    result = run(COMPOSE+["ps","-aq"],capture_output=True,text=True)
    ids = result.stdout.split()
    if not ids:
        raise SystemExit("No task containers found; refuse ambiguous backup/restore")
    items = json.loads(run(["docker","inspect",*ids],capture_output=True,text=True).stdout)
    container_ownership(items)
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
           "POLAR_EVALUATION_VOLUME":prefix+"_evaluations","POLAR_NETWORK":prefix+"_service",
           "POLAR_API_NETWORK":prefix+"_api","POLAR_API_PORT":"18081"}
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
    (source/("restore-"+suffix+".json")).write_text(json.dumps({k:v for k,v in env.items() if k in ["POLAR_DB_VOLUME","POLAR_ARTIFACT_VOLUME","POLAR_EVALUATION_VOLUME","POLAR_NETWORK","POLAR_API_NETWORK","POLAR_API_PORT"]},indent=2)+"\n")
    print("Fresh restore imported. Verify the original report via 127.0.0.1:18081 without worker. Acceptance NOT RUN.")


def evaluate():
    check_ownership()
    running = run(COMPOSE+["ps","--status","running","--services"],capture_output=True,text=True).stdout.split()
    if any(s in running for s in ["worker","evaluator","snapshot","restore-artifacts","migrate"]):
        raise SystemExit("Stop the task worker and other helpers before isolated evaluator invocation")
    run(COMPOSE+["run","--rm","--no-deps","-T","evaluator"])


class InventoryError(Exception):
    """Messages are fixed codes, never subprocess output or credential values."""


def inventory_read(args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=8)
    except (OSError, subprocess.TimeoutExpired):
        raise InventoryError("INVENTORY_COMMAND_UNAVAILABLE") from None
    if result.returncode or len(result.stdout.encode()) > 2 * 1024**2:
        raise InventoryError("INVENTORY_COMMAND_FAILED")
    return result.stdout


def identity(value, pattern):
    return value if isinstance(value, str) and re.fullmatch(pattern, value) else "UNKNOWN"


HEX = r"[a-f0-9]{64}"
REVISION = r"[a-f0-9]{40}"
RESOURCE = r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}"
SERVICES = ("db", "api", "worker")


def inventory_manifest(expected_revision=None, expected_image=None, backup_directory=None, read=inventory_read):
    """Read only fixed projections. Unknown fields and subprocess errors never escape."""
    now = lambda: datetime.now(timezone.utc).isoformat()
    if expected_revision is not None and identity(expected_revision, REVISION) == "UNKNOWN":
        raise InventoryError("INVENTORY_INVALID_REVISION")
    if expected_image is not None and identity(expected_image, "sha256:"+HEX) == "UNKNOWN":
        raise InventoryError("INVENTORY_INVALID_IMAGE")
    selected = {}
    for field, args, pattern in [
        ("commit", ["rev-parse", "HEAD"], REVISION),
        ("tree", ["rev-parse", "HEAD^{tree}"], REVISION),
    ]:
        try:
            selected[field] = identity(read(["git", "-C", str(ROOT), *args]).strip(), pattern)
        except InventoryError:
            selected[field] = "UNKNOWN"
    selected["ops_sha256"] = sha(Path(__file__))
    try:
        committed = read(["git", "-C", str(ROOT), "show", "HEAD:scripts/ops.py"])
        selected["ops_matches_commit"] = hashlib.sha256(committed.encode()).hexdigest() == selected["ops_sha256"]
    except InventoryError:
        selected["ops_matches_commit"] = "UNKNOWN"
    config = json.loads(read(COMPOSE+["config", "--format", "json"]))
    if config.get("name") != "polar":
        raise InventoryError("INVENTORY_PROJECT_MISMATCH")
    names = {"volumes": {}, "networks": {}}
    for kind, keys in [("volumes", ("db", "artifacts")), ("networks", ("service", "api_host"))]:
        for key in keys:
            name = identity(config[kind][key]["name"], RESOURCE)
            if name == "UNKNOWN":
                raise InventoryError("INVENTORY_INVALID_RESOURCE")
            names[kind][key] = name
    ids = read(COMPOSE+["ps", "-aq"]).split()
    if not 1 <= len(ids) <= 12 or any(identity(i, r"[a-f0-9]{12,64}") == "UNKNOWN" for i in ids):
        raise InventoryError("INVENTORY_AMBIGUOUS_CONTAINERS")
    # Intentionally do not request Config.Env, command, arbitrary labels, logs, or health output.
    projection = '{"Id":{{json .Id}},"Image":{{json .Image}},"Config":{"Labels":{'
    label_keys = ("com.docker.compose.project", "com.docker.compose.project.working_dir",
                  "com.docker.compose.service", "com.docker.compose.oneoff",
                  "com.docker.compose.config-hash", "org.opencontainers.image.revision")
    projection += ','.join(json.dumps(k)+':{{json (index .Config.Labels '+json.dumps(k)+')}}' for k in label_keys)
    projection += '}},"State":{"Status":{{json .State.Status}}},'
    projection += '"HostConfig":{"NanoCpus":{{json .HostConfig.NanoCpus}},"Memory":{{json .HostConfig.Memory}},"PidsLimit":{{json .HostConfig.PidsLimit}}},'
    projection += '"Mounts":{{json .Mounts}},"Networks":{{json .NetworkSettings.Networks}},"Ports":{{json .NetworkSettings.Ports}}}'
    items = [json.loads(line) for line in read(["docker", "inspect", "--format", projection, *ids]).splitlines()]
    if len(items) != len(ids):
        raise InventoryError("INVENTORY_AMBIGUOUS_CONTAINERS")
    try:
        container_ownership(items)
    except SystemExit:
        raise InventoryError("INVENTORY_OWNERSHIP_MISMATCH") from None
    chosen = {}
    for item in items:
        labels = item["Config"]["Labels"]
        service = labels.get("com.docker.compose.service")
        if service in SERVICES and labels.get("com.docker.compose.oneoff") == "False":
            if identity(item.get("Id"), HEX) == "UNKNOWN":
                raise InventoryError("INVENTORY_INVALID_CONTAINER")
            if service in chosen:
                raise InventoryError("INVENTORY_AMBIGUOUS_SERVICE")
            chosen[service] = item
    # Ownership of selected resources is checked separately from container labels.
    for kind, verb in [("volumes", "volume"), ("networks", "network")]:
        for name in names[kind].values():
            infos = json.loads(read(["docker", verb, "inspect", name]))
            if len(infos) != 1 or infos[0].get("Name") != name:
                raise InventoryError("INVENTORY_RESOURCE_MISMATCH")
            labels = infos[0].get("Labels") or {}
            if labels.get("com.docker.compose.project") != "polar":
                raise InventoryError("INVENTORY_RESOURCE_OWNERSHIP")
            if kind == "volumes" and labels.get("polar.scope") != "POL.0.4.0.1":
                raise InventoryError("INVENTORY_VOLUME_SCOPE")
    desired, observed, checks = {}, {}, {}
    for service in SERVICES:
        declaration = config["services"][service]
        caps = {"nano_cpus": int(float(declaration["cpus"]) * 10**9),
                "memory_bytes": int(declaration["mem_limit"]), "pids": int(declaration["pids_limit"])}
        desired[service] = {"caps": caps}
        if service not in chosen:
            observed[service] = {"status": "UNKNOWN", "schema_probe": "NOT_RUN"}
            checks[service] = "UNKNOWN"
            continue
        item = chosen[service]
        labels = item["Config"]["Labels"]
        mounts = {}
        expected_mounts = {"/var/lib/postgresql/data": (names["volumes"]["db"], True)} if service == "db" else {
            "/data/artifacts": (names["volumes"]["artifacts"], service == "worker")}
        for destination, (name, writable) in expected_mounts.items():
            matches = [m for m in item["Mounts"] if m.get("Destination") == destination]
            if len(matches) != 1 or matches[0].get("Type") != "volume" or matches[0].get("Name") != name or matches[0].get("RW") != writable:
                raise InventoryError("INVENTORY_MOUNT_MISMATCH")
            mounts[destination] = {"volume": name, "writable": writable}
        expected_networks = {names["networks"]["service"]}
        if service == "api":
            expected_networks.add(names["networks"]["api_host"])
        if set(item["Networks"]) != expected_networks:
            raise InventoryError("INVENTORY_NETWORK_MISMATCH")
        observed_caps = {"nano_cpus": item["HostConfig"].get("NanoCpus"), "memory_bytes": item["HostConfig"].get("Memory"), "pids": item["HostConfig"].get("PidsLimit")}
        for k, v in observed_caps.items():
            if not isinstance(v, int) or isinstance(v, bool) or not 0 <= v <= 2**63-1:
                observed_caps[k] = "UNKNOWN"
        record = {"container_id": identity(item["Id"], HEX), "image_id": identity(item["Image"], "sha256:"+HEX),
                  "revision_label": identity(labels.get("org.opencontainers.image.revision"), REVISION),
                  "compose_config_sha256": identity(labels.get("com.docker.compose.config-hash"), HEX),
                  "state": identity(item["State"].get("Status"), r"created|running|paused|restarting|removing|exited|dead"),
                  "caps": observed_caps, "mounts": mounts, "networks": sorted(expected_networks), "checked_at": now()}
        result = {"caps_equal_desired": observed_caps == caps, "maps_equal_desired": True,
                  "app_revision_equal_expected": "NOT_RUN", "image_equal_expected": "NOT_RUN"}
        if service != "db":
            result["app_revision_equal_expected"] = record["revision_label"] == expected_revision if expected_revision else "NOT_RUN"
            result["image_equal_expected"] = record["image_id"] == expected_image if expected_image else "NOT_RUN"
        if service == "api":
            ports = item["Ports"].get("8000/tcp") or []
            desired_ports = declaration.get("ports", [])
            if len(desired_ports) != 1 or desired_ports[0].get("host_ip") != "127.0.0.1":
                raise InventoryError("INVENTORY_LOOPBACK_REQUIRED")
            port = str(desired_ports[0]["published"])
            if not port.isdigit() or not 1 <= int(port) <= 65535 or ports != [{"HostIp": "127.0.0.1", "HostPort": port}]:
                raise InventoryError("INVENTORY_PORT_MISMATCH")
            record["loopback_api"] = {"host": "127.0.0.1", "port": int(port)}
        desired[service]["app_revision"] = (expected_revision or "UNKNOWN") if service != "db" else "NOT_RUN"
        observed[service], checks[service] = record, result
    database = {"status": "NOT_RUN", "schema_version": "UNKNOWN", "schema_sha256": "UNKNOWN", "counters": "UNKNOWN"}
    if "db" in chosen and observed["db"]["state"] == "running":
        sql = """BEGIN READ ONLY; SELECT json_build_object('schema_version',version,'schema_sha256',checksum,
          'datasets',(SELECT count(*) FROM datasets),'runs',(SELECT count(*) FROM runs),
          'attempts',(SELECT count(*) FROM attempts),'active',(SELECT count(*) FROM runs WHERE state IN ('running','queued')))
          FROM schema_version; ROLLBACK;"""
        try:
            rows = read(["docker", "exec", chosen["db"]["Id"], "psql", "-X", "-qAt", "-U", "polar", "-d", "polar", "-c", sql]).splitlines()
            if len(rows) != 1:
                raise InventoryError("INVENTORY_SCHEMA_AMBIGUOUS")
            row = json.loads(rows[0])
            if type(row["schema_version"]) is not int or not 0 <= row["schema_version"] <= 1000:
                raise InventoryError("INVENTORY_SCHEMA_INVALID")
            counts = {k:row[k] for k in ("datasets", "runs", "attempts", "active")}
            if any(type(v) is not int or not 0 <= v <= 2**63-1 for v in counts.values()):
                raise InventoryError("INVENTORY_COUNTER_INVALID")
            database = {"status": "OBSERVED", "schema_version": row["schema_version"], "schema_sha256": identity(row["schema_sha256"], HEX), "counters": counts}
        except (InventoryError, ValueError, KeyError, TypeError):
            database["status"] = "UNKNOWN"
    database["checked_at"] = now()
    database["selected_schema_sha256"] = sha(ROOT/"src/polar/schema.sql")
    database["selected_schema_version"] = 1
    database["schema_equal_selected"] = (database["schema_version"] == 1 and database["schema_sha256"] == database["selected_schema_sha256"]) if database["status"] == "OBSERVED" and database["schema_sha256"] != "UNKNOWN" else "UNKNOWN"
    backup = {"status": "NOT_RUN", "restore_effect": "NOT_RUN"}
    if backup_directory is not None:
        # Bind existing format metadata only; never open a dump, secret or dataset body.
        directory = backup_directory.resolve(strict=True)
        path = directory/"backup-manifest.json"
        if path.stat().st_size > 16384:
            raise InventoryError("INVENTORY_BACKUP_MANIFEST_LIMIT")
        m = json.loads(path.read_bytes())
        if m.get("scope") != "POL.0.4.0.1" or set(m.get("files", {})) != {"metadata.dump", "artifacts.tar"}:
            raise InventoryError("INVENTORY_BACKUP_FORMAT")
        backup = {"status": "METADATA_ONLY", "directory": str(directory), "manifest_sha256": sha(path),
                  "code_revision": identity(m.get("code_revision"), REVISION),
                  "files": {k:identity(v, HEX) for k,v in m["files"].items()}, "file_verification": "NOT_RUN", "restore_effect": "NOT_RUN",
                  "current_state_coverage": "UNKNOWN"}
    return {"schema": "polar.runtime-inventory/1", "checked_at": now(), "selected_tooling": selected,
            "desired": {"project": "polar", "compose_file_sha256": sha(ROOT/"compose.yaml"), "resources": names, "services": desired},
            "observed": {"services": observed, "database": database}, "checks": checks, "backup_handle": backup,
            "limits": {"hard_storage_quota": "NOT_ENFORCED", "blinding": "BLINDING_NOT_ENFORCED", "global_cpu_storage_accounting": "INCOMPLETE", "kernel_caps_verification": "NOT_RUN", "running_source_bytes_verification": "NOT_RUN"}}


def inventory(output, expected_revision=None, expected_image=None, backup_directory=None):
    try:
        # Resolve parents first, reject symlinks/existing files and any Git working tree.
        if not output.is_absolute() or output.exists() or output.is_symlink():
            raise InventoryError("INVENTORY_NEW_EXTERNAL_FILE_REQUIRED")
        target = output.parent.resolve(strict=True)/output.name
        if target.is_relative_to(ROOT.resolve()) or any((p/".git").exists() for p in [target.parent, *target.parent.parents]):
            raise InventoryError("INVENTORY_EXTERNAL_FILE_REQUIRED")
        probe = subprocess.run(["git", "-C", str(target.parent), "rev-parse", "--is-inside-work-tree"],capture_output=True,text=True,timeout=8)
        if probe.returncode == 0:
            raise InventoryError("INVENTORY_EXTERNAL_FILE_REQUIRED")
        if "not a git repository" not in probe.stderr.lower():
            raise InventoryError("INVENTORY_EXTERNAL_PATH_UNVERIFIED")
        manifest = inventory_manifest(expected_revision, expected_image, backup_directory)
        body = (json.dumps(manifest, sort_keys=True, indent=2)+"\n").encode()
        if len(body) > 65536:
            raise InventoryError("INVENTORY_OUTPUT_LIMIT")
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(body)
        print("Inventory written. Independent acceptance NOT_RUN.")
    except InventoryError as error:
        raise SystemExit(str(error)) from None
    except (OSError, ValueError, KeyError, TypeError, AttributeError, OverflowError, subprocess.SubprocessError):
        raise SystemExit("INVENTORY_UNAVAILABLE") from None


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers(dest="operation",required=True)
    subs.add_parser("backup").add_argument("directory",type=Path)
    p = subs.add_parser("restore")
    p.add_argument("directory",type=Path)
    p.add_argument("--suffix",required=True)
    subs.add_parser("evaluate")
    p = subs.add_parser("inventory", help="Read-only allowlisted inventory to a NEW file outside Git")
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--expected-app-revision")
    p.add_argument("--expected-image-id")
    p.add_argument("--backup-directory", type=Path)
    args = parser.parse_args()
    if args.operation == "backup": backup(args.directory)
    elif args.operation == "restore": restore(args.directory,args.suffix)
    elif args.operation == "evaluate": evaluate()
    else: inventory(args.output, args.expected_app_revision, args.expected_image_id, args.backup_directory)

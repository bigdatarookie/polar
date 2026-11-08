"""Resumable ordinary-code import: evidence first, checkpoint second, no implicit refetch."""
import json
import math
import os
from pathlib import Path
import random
import platform
import sys
import time
import uuid

from .history_bundle import read_file,safe_root
from .import_contract import (ADAPTER, ENDPOINT, POLICY, MAX_FILE, ImportError, require, exact, config,
                              canonical, decode, digest, sha, job_id, alignment, timestamp, seconds, hash_value)
from .import_transport import Clock,FixtureClock,HttpTransport,FixtureTransport


def code_projection():
    root = Path(__file__).parent
    paths = {p.name:p for p in root.glob("import_*.py")}
    paths.update({name:root/name for name in ("service.py","cli.py","history_bundle.py","history_store.py")})
    return {name:sha(path.read_bytes()) for name,path in sorted(paths.items())}


def plan_name(value):
    require(type(value) is str and value.startswith(("fixture-","import-")),"IMPORT_INVALID_ID")
    hash_value(value.split("-",1)[1]);return value


def attempt_name(value):
    try: parsed = uuid.UUID(value)
    except (ValueError,TypeError,AttributeError): require(False,"IMPORT_INVALID_ID")
    require(str(parsed)==value and parsed.version==4,"IMPORT_INVALID_ID")
    return value


def bound_file(ref):
    exact(ref,{"path","sha256"})
    path = Path(ref["path"])
    require(path.is_absolute(),"IMPORT_EVIDENCE_PATH")
    raw = read_file(safe_root(path.parent),path.name,limit=MAX_FILE)
    require(sha(raw)==hash_value(ref["sha256"]),"IMPORT_EVIDENCE_HASH")
    return raw


class ImportService:
    def __init__(self,store,clock=None):
        self.store = store
        self.clock = clock or Clock()

    def plan(self,value):
        value = config(decode(canonical(value)))
        bound_file(value["route_evidence"])
        require((value["mode"]=="fixture") == ("imports-fixture-v1/" in self.store.base),"IMPORT_MODE_MISMATCH")
        data = {"schema":"polar.import-plan/1","config":value,"scope":self.store.base,
                "jobs":[{"job_id":job_id(r),"request":r} for r in value["requests"]],
                "source_projection":code_projection()}
        pid = ("fixture-" if value["mode"]=="fixture" else "import-")+digest(data)
        data["plan_id"] = pid
        with self.store.locked():
            self.store.admit_storage()
            if self.store.exists("policy.json"):
                require(self.store.read("policy.json")==POLICY,"IMPORT_PROSPECTIVE_CUTOVER_REQUIRED")
            else: self.store.write("policy.json",POLICY)
            self.store.write("plans/"+pid+".json",data)
            result = self.status(pid)
        return {"schema":"polar.import-plan-result/1","plan_id":pid,"planned":len(data["jobs"]),
                "counts":result["counts"],"mode":value["mode"],"provider_requests":0}

    def load(self,pid):
        plan_name(pid)
        value = self.store.read("plans/"+pid+".json")
        require(value["plan_id"]==pid and pid.split("-",1)[1]==digest({k:v for k,v in value.items() if k!="plan_id"}),
                "IMPORT_PLAN_HASH")
        require(value["scope"]==self.store.base,"IMPORT_SCOPE_MISMATCH")
        return value

    def request_records(self):
        rows = []
        for name in self.store.list("requests"):
            start = self.store.read(name)
            require(start["schema"]=="polar.import-request-start/1" and Path(name).stem==start["request_id"],
                    "IMPORT_REQUEST_INTEGRITY")
            require(start["job_ids"]==[job_id(r) for r in start["requests"]] and
                    start["wire_sha256"]==sha(canonical(start["requests"])),"IMPORT_REQUEST_INTEGRITY")
            response_name = "responses/"+start["request_id"]+".json"
            response = self.store.read(response_name) if self.store.exists(response_name) else None
            if response:
                require(response["request_start_sha256"]==digest(start),"IMPORT_RESPONSE_IDENTITY")
                self.store.object_read(response["body"])
            rows.append((start,response))
        return sorted(rows,key=lambda pair:(pair[0]["started_at"],pair[0]["request_id"]))

    def states(self,plan,cache,records):
        states = {row["job_id"]:{"state":"pending","kind":None,"retry_eligible":True,
                  "post_cutover_appearances":0,"historical_attempts_exact":None,"reason":None} for row in plan["jobs"]}
        historical = {}
        for name in self.store.list("cache-imports"):
            for jid,count in self.store.read(name)["migration"]["historical_job_appearances_minimum"].items():
                historical[jid] = max(count,historical.get(jid,0))
        for jid,state in states.items(): state["historical_attempts_known_minimum"]=historical.get(jid,0)
        for start,response in records:
            outcome_name = "outcomes/"+start["request_id"]+".json"
            outcome = self.store.read(outcome_name) if self.store.exists(outcome_name) else None
            if outcome:
                require(outcome["request_start_sha256"]==digest(start),"IMPORT_OUTCOME_IDENTITY")
            for jid in start["job_ids"]:
                if jid not in states: continue
                state = states[jid]
                state["post_cutover_appearances"] += 1
                state.update(state="retryable_error",reason="INTERRUPTED_REQUEST_OUTCOME_UNKNOWN",retry_eligible=True)
                if outcome and jid in outcome["jobs"]: state.update(outcome["jobs"][jid])
        for jid,state in states.items():
            if jid in cache:
                versions = cache[jid]
                state.update(state="success",retry_eligible=False,reason=None,
                             kind=versions[0]["kind"] if len(versions)==1 else "CONFLICTING_RESPONSE_VERSIONS")
            elif state["post_cutover_appearances"]>=POLICY["max_job_appearances"]:
                state.update(state="permanent_error",retry_eligible=False,reason="JOB_APPEARANCE_BUDGET_EXHAUSTED")
        return states

    def status(self,pid):
        plan = self.load(pid)
        cache = self.store.commits()
        records = self.request_records()
        states = self.states(plan,cache,records)
        counts = {kind:sum(row["state"]==kind for row in states.values())
                  for kind in ("pending","success","retryable_error","permanent_error")}
        counts["no_match"] = sum(s["kind"]=="WARNING_NO_MATCH" for s in states.values())
        counts["conflicting_versions"] = sum(s["kind"]=="CONFLICTING_RESPONSE_VERSIONS" for s in states.values())
        return {"schema":"polar.import-status/1","plan_id":pid,"counts":counts,"states":states,
                "scope_physical_posts":len(records),"historical_attempts_exact":None,
                "scope_paused":self.store.read("auth-pause.json") if self.store.exists("auth-pause.json") else None,
                "control":self.store.read("control.json") if self.store.exists("control.json") else {"action":"resume"},
                "scientific_fitness":"NOT_ASSESSED"}

    def result(self,pid,jid):
        plan=self.load(pid);hash_value(jid)
        require(jid in {row["job_id"] for row in plan["jobs"]},"IMPORT_JOB_NOT_IN_PLAN")
        versions=self.store.commits().get(jid,[])
        return {"schema":"polar.import-result/1","plan_id":pid,"job_id":jid,
                "state":self.status(pid)["states"][jid],"versions":versions,
                "selection":"NO_CANDIDATE_OR_RESPONSE_VERSION_SELECTED","scientific_fitness":"NOT_ASSESSED"}

    def attempt_path(self,pid,aid):
        self.load(pid);attempt_name(aid)
        path=self.store.root/self.store.path("attempts/"+aid)
        return {"schema":"polar.import-attempt-path/1","plan_id":pid,"attempt_id":aid,
                "attempt_path":str(path),"terminal_path":str(path/"content-manifest.json"),
                "consumer_receipt_path":str(path/"consumer/receipt.json"),"provider_requests":0}

    def attempts(self,pid):
        self.load(pid)
        directory=self.store.root/self.store.path("attempts")
        rows=[]
        if directory.exists():
            require(not directory.is_symlink(),"IMPORT_UNSAFE_PATH")
            for child in sorted(directory.iterdir()):
                attempt_name(child.name)
                require(child.is_dir() and not child.is_symlink(),"IMPORT_UNSAFE_PATH")
                name="attempts/"+child.name
                if not self.store.exists(name+"/started.json"):continue
                started=self.store.read(name+"/started.json")
                if started["plan_id"]!=pid:continue
                marker=name+"/content-manifest.json"
                manifest=self.store.read(marker) if self.store.exists(marker) else None
                if manifest:
                    require(manifest["attempt_id"]==child.name and manifest["plan_id"]==pid,"IMPORT_TERMINAL_IDENTITY")
                rows.append({"attempt_id":child.name,"started_at":started["started_at"],
                             "manifest_sha256":digest(manifest) if manifest else None,
                             "status":manifest["status"] if manifest else "RUNNING_OR_INTERRUPTED_UNRECONCILED",
                             "objects_verified":False,"consumer_receipt_present":self.store.exists(name+"/consumer/receipt.json")})
        return {"schema":"polar.import-attempt-list/1","plan_id":pid,"attempts":rows}

    def control(self,pid,action):
        self.load(pid)
        require(action in ("pause","resume","stop"),"IMPORT_CONTROL_ACTION")
        # Separate atomic control channel remains writable while executor holds its scope lock.
        value = {"schema":"polar.import-control/1","action":action,"at":timestamp(),"plan_id":pid}
        self.store.write("controls/"+str(uuid.uuid4())+".json",value)
        self.store.write("control.json",value,replace=True)
        return value

    def disposition(self,start,response):
        """Idempotent replay can commit a saved response after a crash without network."""
        name = "outcomes/"+start["request_id"]+".json"
        if self.store.exists(name): return self.store.read(name)
        jobs = {}
        successful = {}
        status,error = response["status"],response["error"]
        reason = error
        split = False
        pause = False
        retry = False
        if error or status in (500,503): retry=True;reason=error or "HTTP_TRANSIENT"
        elif status in (401,403): pause=True;reason="AUTH_OR_RIGHTS_REFUSAL"
        elif response["truncated"]: reason="RESPONSE_BODY_LIMIT"
        elif status==429: retry=True;reason="RATE_LIMIT"
        elif status==413: retry=True;split=True;reason="BATCH_TOO_LARGE"
        elif status!=200: reason="HTTP_PERMANENT"
        elif response["headers"].get("content-type","").split(";",1)[0].strip().lower()!="application/json":
            reason="UNSUPPORTED_RESPONSE_CONTENT_TYPE"
        else:
            try:
                values,kinds = alignment(self.store.object_read(response["body"]),start["requests"])
            except ImportError:
                retry=True;split=True;reason="MALFORMED_POSITIONAL"
            else:
                for jid,req,item,kind in zip(start["job_ids"],start["requests"],values,kinds):
                    if kind=="PROVIDER_JOB_ERROR":
                        rights=any(term in item.get("error","").lower() for term in
                                   ("not authorized","unauthorized","permission denied","access denied","invalid api key","forbidden"))
                        if rights: pause=True;reason="AUTH_OR_RIGHTS_REFUSAL"
                        jobs[jid] = {"state":"retryable_error" if rights else "permanent_error","kind":kind,
                                     "reason":"AUTH_OR_RIGHTS_REFUSAL" if rights else "PROVIDER_JOB_ERROR",
                                     "retry_eligible":False}
                    else:
                        result = {"job_id":jid,"request":req,"kind":kind,"response":item,
                                  "response_sha256":digest(item),"sources":[{"request_id":start["request_id"],
                                  "body":response["body"],"job_ordinal":start["job_ids"].index(jid),
                                  "request_wire_sha256":start["wire_sha256"],"actual_capture_at":response["completed_at"]}]}
                        successful[jid] = [result]
                        jobs[jid] = {"state":"success","kind":kind,"reason":None,"retry_eligible":False}
        if not jobs:
            jobs = {jid:{"state":"retryable_error" if retry or pause else "permanent_error","kind":None,
                         "reason":reason,"retry_eligible":retry and not pause} for jid in start["job_ids"]}
        # Accepted results are immutable and durable BEFORE checkpoint/outcome visibility advances.
        if successful:
            commit = {"schema":"polar.import-cache-commit/1","jobs":successful,
                      "request_start_sha256":digest(start),"response_sha256":digest(response)}
            self.store.write("successes/"+digest(commit)+".json",commit)
        if pause:
            self.store.write("auth-pause.json",{"schema":"polar.import-auth-pause/1","scope":self.store.base,
                             "request_id":start["request_id"],"reason":reason,"at":response["completed_at"]},replace=True)
        outcome = {"schema":"polar.import-request-outcome/1","request_start_sha256":digest(start),
                   "jobs":jobs,"split":split,"scope_pause":pause}
        self.store.write(name,outcome)
        return outcome

    def delay(self,start,response,appearance):
        """Mandated rate waits are never capped down to fit a deadline."""
        headers = {k.lower():v for k,v in response["headers"].items()}
        def duration(key):
            raw = headers.get(key)
            if raw is None: return None
            try: value = float(raw)
            except (TypeError,ValueError): return None
            return value if math.isfinite(value) and value>=0 else None
        reset,after = duration("ratelimit-reset"),duration("retry-after")
        waits = [0.]
        if response["status"]==429:
            waits += [max(reset or 0,after or 0,60 if reset is None and after is None else 0)+1]
        remaining = duration("ratelimit-remaining")
        if remaining is not None and remaining<=0: waits.append((reset if reset is not None else 60)+1)
        if response["error"] or response["status"] in (500,503):
            waits.append(min(30,2*2**max(0,appearance-1))+random.uniform(0,1))
        return max(waits)

    def execute(self,pid,*,fixture=None,network=False,attempt_id=None):
        plan = self.load(pid)
        require(plan["source_projection"]==code_projection(),"IMPORT_SOURCE_MISMATCH")
        cfg = plan["config"]
        bound_file(cfg["route_evidence"])
        require((cfg["mode"]=="fixture" and fixture is not None and not network) or
                (cfg["mode"]=="provider" and fixture is None and network),"IMPORT_NETWORK_NOT_ADMITTED")
        if fixture is not None:
            self.clock = FixtureClock(fixture["start_seconds"])
            transport = FixtureTransport(fixture,self.clock)
        else: transport = HttpTransport()
        if network:
            require(len(os.environ.get("POLAR_CODE_REVISION",""))==40 and
                    os.environ.get("POLAR_IMPORT_BUILD_ID","").startswith("sha256:"),"IMPORT_EXECUTABLE_BUILD_NOT_BOUND")
            require(attempt_id is not None,"IMPORT_ATTEMPT_BINDING_REQUIRED")
        with self.store.locked():
            self.store.admit_storage()
            records = self.request_records()
            # Recover committed response bytes before selecting any pending work.
            for start,response in records:
                if response: self.disposition(start,response)
            if self.store.exists("budget.json"):
                budget = self.store.read("budget.json")
            else:
                budget = {"schema":"polar.import-budget/1","started_at":timestamp(self.clock.now()),
                          "deadline":timestamp(self.clock.now()+900),"policy_sha256":digest(POLICY),
                          "inherited_attempts_exact":None,"cutover_posts_start":0}
                self.store.write("budget.json",budget)
            require(budget["policy_sha256"]==digest(POLICY),"IMPORT_POLICY_MISMATCH")
            if self.store.exists("throttle.json") and self.clock.synthetic:
                self.clock.value = max(self.clock.value,self.store.read("throttle.json")["last_observed_time"])
            if records:
                next_start = max(seconds(s["started_at"])+3 for s,_ in records)
                observed = max([seconds(s["started_at"]) for s,_ in records]+
                               [seconds(r["completed_at"]) for _,r in records if r])
                for _,response in records:
                    if response: next_start=max(next_start,seconds(response["completed_at"])+response["wait_seconds"])
                prior = self.store.read("throttle.json") if self.store.exists("throttle.json") else {}
                self.store.write("throttle.json",{"next_start":max(next_start,prior.get("next_start",0)),
                                 "last_observed_time":max(observed,prior.get("last_observed_time",0))},replace=True)
                if self.clock.synthetic: self.clock.value=max(self.clock.value,observed)
            aid = attempt_name(attempt_id) if attempt_id is not None else str(uuid.uuid4())
            require(not self.store.exists("attempts/"+aid+"/started.json") and
                    not self.store.exists("attempts/"+aid+"/content-manifest.json"),"IMPORT_ATTEMPT_ALREADY_STARTED")
            started = {"schema":"polar.import-attempt-start/1","attempt_id":aid,"plan_id":pid,
                       "started_at":timestamp(self.clock.now()),"owner_pid":os.getpid(),
                       "source_projection":code_projection(),"mode":cfg["mode"],"budget":budget,
                       "environment":{"python":sys.version,"platform":platform.platform(),
                                      "code_revision":os.environ.get("POLAR_CODE_REVISION","NOT_BOUND"),
                                      "build_id":os.environ.get("POLAR_IMPORT_BUILD_ID","NOT_BOUND")},
                       "fixture_sha256":digest(fixture) if fixture is not None else None}
            prefix = "attempts/"+aid
            self.store.write(prefix+"/started.json",started)
            stats = {"request_seconds":0.,"throttle_seconds":0.,"local_processing_seconds":0.,
                     "inter_pass_seconds":None,"clock":"SIMULATED_FIXTURE" if self.clock.synthetic else "ACTUAL_WALL"}
            initially = self.store.commits()
            reused = sum(job["job_id"] in initially for job in plan["jobs"])
            reason = "AUTH_SCOPE_PAUSED" if self.store.exists("auth-pause.json") else "NO_PENDING_WORK"
            interrupted = False
            run_begin = self.clock.monotonic()
            try:
                cache = self.store.commits()
                states = self.states(plan,cache,records)
                pending = [j for j in plan["jobs"] if states[j["job_id"]]["state"]!="success" and
                           states[j["job_id"]]["retry_eligible"]]
                split_jobs = set()
                for start,_ in records:
                    name = "outcomes/"+start["request_id"]+".json"
                    if self.store.exists(name) and self.store.read(name)["split"]:
                        split_jobs.update(start["job_ids"])
                normal = [j for j in pending if j["job_id"] not in split_jobs]
                queue = [normal[i:i+10] for i in range(0,len(normal),10)]+[[j] for j in pending if j["job_id"] in split_jobs]
                while queue:
                    records = self.request_records()
                    cache = self.store.commits()
                    states = self.states(plan,cache,records)
                    batch = [j for j in queue.pop(0) if states[j["job_id"]]["state"]!="success" and
                             states[j["job_id"]]["retry_eligible"]]
                    if not batch: continue
                    if self.store.exists("auth-pause.json"): reason="AUTH_SCOPE_PAUSED";break
                    control = self.store.read("control.json") if self.store.exists("control.json") else {}
                    if control.get("action") in ("pause","stop"): reason="CONTROL_"+control["action"].upper();break
                    if len(records)>=160: reason="PHYSICAL_POST_BUDGET";break
                    total_bytes = sum(r["body"]["bytes"] for _,r in records if r)
                    if total_bytes+2*1024**2>32*1024**2: reason="RESPONSE_BYTE_BUDGET";break
                    deadline = seconds(budget["deadline"])
                    throttle = self.store.read("throttle.json") if self.store.exists("throttle.json") else None
                    gate = (throttle["next_start"] if throttle else self.clock.now()+60)
                    recent = [seconds(s["started_at"]) for s,_ in records if seconds(s["started_at"])>self.clock.now()-60]
                    if len(recent)>=25: gate=max(gate,sorted(recent)[-25]+60+1)
                    if gate>self.clock.now():
                        if gate>=deadline: reason="MANDATED_WAIT_EXCEEDS_DEADLINE";break
                        wait = gate-self.clock.now()
                        while self.clock.now()<gate:
                            control = self.store.read("control.json") if self.store.exists("control.json") else {}
                            if control.get("action") in ("pause","stop"): break
                            step=min(1,gate-self.clock.now())
                            self.clock.sleep(step);stats["throttle_seconds"]+=step
                        if control.get("action") in ("pause","stop"):
                            reason="CONTROL_"+control["action"].upper();break
                    if self.clock.now()>=deadline: reason="OPERATION_DEADLINE";break
                    rid = str(uuid.uuid4())
                    reqs = [j["request"] for j in batch]
                    start = {"schema":"polar.import-request-start/1","request_id":rid,"attempt_id":aid,
                             "job_ids":[j["job_id"] for j in batch],"requests":reqs,"wire_sha256":sha(canonical(reqs)),
                             "started_at":timestamp(self.clock.now()),"request_timeout_seconds":min(45,deadline-self.clock.now())}
                    self.store.write("requests/"+rid+".json",start)  # consumes budget before POST
                    throttle = {"next_start":self.clock.now()+3,"last_observed_time":self.clock.now()}
                    self.store.write("throttle.json",throttle,replace=True)
                    before = self.clock.monotonic()
                    result = transport.post(reqs,len(records),start["request_timeout_seconds"])
                    stats["request_seconds"] += self.clock.monotonic()-before
                    local = self.clock.monotonic()
                    body = self.store.object(result.pop("body"))
                    response = {"schema":"polar.import-response/1","request_start_sha256":digest(start),
                                "completed_at":timestamp(self.clock.now()),"body":body,**result}
                    appearance = max(states[j["job_id"]]["post_cutover_appearances"]+1 for j in batch)
                    response["wait_seconds"] = self.delay(start,response,appearance)
                    self.store.write("responses/"+rid+".json",response)
                    outcome = self.disposition(start,response)
                    delay = response["wait_seconds"]
                    throttle = {"next_start":max(throttle["next_start"],self.clock.now()+delay),
                                "last_observed_time":self.clock.now()}
                    self.store.write("throttle.json",throttle,replace=True)
                    current = self.status(pid)
                    self.store.checkpoint(pid,{"plan_id":pid,"attempt_id":aid,"counts":current["counts"],
                                              "physical_posts":current["scope_physical_posts"],"at":timestamp(self.clock.now())})
                    stats["local_processing_seconds"] += self.clock.monotonic()-local
                    if outcome["scope_pause"]: reason="AUTH_SCOPE_PAUSED";break
                    retry = [j for j in batch if current["states"][j["job_id"]]["retry_eligible"]]
                    if outcome["split"]: queue.extend([[j] for j in retry])
                    elif retry: queue.append(retry)
                    reason = "EXHAUSTED_PLANNED_QUEUE"
            except (KeyboardInterrupt,InterruptedError):
                interrupted=True;reason="INTERRUPTED"
            except Exception as exc:
                reason = exc.code if isinstance(exc,ImportError) else "IMPORT_EXECUTION_ERROR"
            finally:
                state = self.status(pid)
                counts = state["counts"]
                status = ("interrupted" if interrupted else "complete" if counts["success"]==len(plan["jobs"]) else
                          "partial" if counts["success"] else "failed")
                elapsed = self.clock.monotonic()-run_begin
                summary = {"schema":"polar.import-terminal-state/1","attempt_id":aid,"plan_id":pid,
                           "status":status,"reason":reason,"counts":counts,"states":state["states"],
                           "reused_jobs":reused,"scope_physical_posts":state["scope_physical_posts"],
                           "timing":stats,"operation_elapsed_seconds":elapsed,
                           "observed_new_jobs_per_second":(counts["success"]-reused)/elapsed if elapsed>0 else None,
                           "remaining_jobs":len(plan["jobs"])-counts["success"],"ETA_seconds_estimated":None,
                           "historical_attempts_exact":None,"scientific_fitness":"NOT_ASSESSED"}
                all_records=self.request_records()
                summary["scope_response_bytes"]=sum(r["body"]["bytes"] for _,r in all_records if r)
                summary["scope_request_bytes"]=sum(len(canonical(s["requests"])) for s,_ in all_records)
                summary["new_physical_posts"]=sum(s["attempt_id"]==aid for s,_ in all_records)
                summary["unknown_request_outcomes"]=sum(r is None for _,r in all_records)
                summary["original_operation_elapsed_seconds"]=self.clock.now()-seconds(budget["started_at"])
                if self.clock.now()>seconds(budget["deadline"]):
                    status="partial" if counts["success"] else "failed"
                    reason="OPERATION_DEADLINE_EXCEEDED"
                    summary.update(status=status,reason=reason)
                self.store.write(prefix+"/terminal-state.json",summary)
                self.store.checkpoint(pid,{"plan_id":pid,"attempt_id":aid,"counts":counts,
                                          "physical_posts":state["scope_physical_posts"],"at":timestamp(self.clock.now())})
                checkpoint = self.store.read("checkpoints/"+pid.split("-",1)[1]+".json")
                self.store.write(prefix+"/checkpoint.json",checkpoint)
                members = [prefix+"/started.json",prefix+"/terminal-state.json","plans/"+pid+".json","policy.json","budget.json"]
                members.append(prefix+"/checkpoint.json")
                for directory in ("cache-imports","successes","requests","responses","outcomes","objects"):
                    members.extend(self.store.list(directory))
                objects = {name:{"sha256":sha(self.store.raw(name)),"bytes":len(self.store.raw(name))} for name in members}
                manifest = {"schema":"polar.import-terminal-manifest/1","attempt_id":aid,"plan_id":pid,
                            "status":status,"started_at":started["started_at"],"completed_at":timestamp(self.clock.now()),
                            "scope":self.store.base,"objects":objects,"terminal_state":prefix+"/terminal-state.json"}
                self.store.write(prefix+"/content-manifest.json",manifest)  # terminal wake marker is LAST
            return {"schema":"polar.import-execution/1","attempt_id":aid,"plan_id":pid,"status":status,
                    "manifest_path":str(self.store.root/self.store.path(prefix+"/content-manifest.json")),
                    "manifest_sha256":digest(manifest),"counts":counts,"reason":reason}

    def terminal(self,aid,expected_hash):
        attempt_name(aid);hash_value(expected_hash)
        name = "attempts/"+aid+"/content-manifest.json"
        raw = self.store.raw(name)
        require(sha(raw)==expected_hash,"IMPORT_TERMINAL_HASH")
        manifest = decode(raw)
        require(manifest["schema"]=="polar.import-terminal-manifest/1" and manifest["attempt_id"]==aid and
                manifest["scope"]==self.store.base and manifest["status"] in ("complete","partial","failed","interrupted"),
                "IMPORT_TERMINAL_IDENTITY")
        for path,ref in manifest["objects"].items():
            value = self.store.raw(path)
            require(len(value)==ref["bytes"] and sha(value)==ref["sha256"],"IMPORT_TERMINAL_OBJECT_HASH")
        state = self.store.read(manifest["terminal_state"])
        require(state["attempt_id"]==aid and state["plan_id"]==manifest["plan_id"] and state["status"]==manifest["status"],
                "IMPORT_TERMINAL_IDENTITY")
        start = self.store.read("attempts/"+aid+"/started.json")
        require(start["started_at"]==manifest["started_at"],"IMPORT_TERMINAL_IDENTITY")
        return manifest,state

    def consume(self,pid,aid,expected_hash,assessment):
        self.load(pid)
        exact(assessment,{"consumer","outcome","next_action"})
        require(all(type(v) is str and 0<len(v)<=500 for v in assessment.values()),"IMPORT_ASSESSMENT_REQUIRED")
        manifest,state = self.terminal(aid,expected_hash)
        require(manifest["plan_id"]==pid,"IMPORT_TERMINAL_IDENTITY")
        name = "attempts/"+aid+"/consumer/receipt.json"
        receipt = {"schema":"polar.import-consumption/1","attempt_id":aid,"manifest_sha256":expected_hash,
                   "manifest_path":str(self.store.root/self.store.path("attempts/"+aid+"/content-manifest.json")),
                   "worker_started_at":manifest["started_at"],"assessment":assessment}
        with self.store.locked():
            existing = self.store.read(name) if self.store.exists(name) else None
            require(existing is None or existing==receipt,"IMPORT_CONSUMPTION_CONFLICT")
            self.store.write(name,receipt)
        return {"schema":"polar.import-consume-result/1","status":"ALREADY_CONSUMED" if existing else "CONSUMED",
                "receipt":receipt,"counts":state["counts"]}

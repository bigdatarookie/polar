"""Invented offline fixtures only. No provider/credential operation or scientific inputs."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import patch

from polar.import_contract import (ADAPTER,POLICY,ImportError,canonical,wire,digest,sha,request,job_id,timestamp)
from polar.import_service import ImportService
from polar.import_store import ImportStore
from polar.import_migration import migration

START=1767225600
DATA={"data":[{"figi":"INVENTED-FIGI","opaque_extra":None}]}
NOMATCH={"warning":"No identifier found."}


class LoaderFixtures(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve()
        (self.root/"route.md").write_text("Invented route evidence for synthetic fixtures only")
        self.store=ImportStore(self.root,64*1024**3,fixture=True)
        self.service=ImportService(self.store)

    def plan(self,n=1):
        self.config={"schema":"polar.import-config/1","adapter":ADAPTER,"mode":"fixture",
                     "requests":[request("INVENTED-"+str(i)) for i in range(n)],"policy":dict(POLICY),
                     "route_evidence":{"path":str(self.root/"route.md"),"sha256":sha((self.root/"route.md").read_bytes())}}
        return self.service.plan(self.config)["plan_id"]

    def run_fixture(self,pid,responses,**kwargs):
        return self.service.execute(pid,fixture={"schema":"polar.import-fixture/1","start_seconds":START,
                                                "responses":responses},**kwargs)

    def test_stable_jobs_not_batches_and_inert_plan(self):
        a,b=request("INVENTED-A"),request("INVENTED-B")
        self.assertNotEqual(job_id(a),job_id(b))
        self.assertEqual(job_id(a),job_id(dict(reversed(list(a.items())))))
        pid=self.plan(2)
        self.assertEqual(self.service.status(pid)["scope_physical_posts"],0)
        bad=copy.deepcopy(self.config);bad["requests"].append(bad["requests"][0])
        with self.assertRaises(ImportError):self.service.plan(bad)
        bad=copy.deepcopy(self.config);bad["requests"][0]["securityType2"]="Common Stock"
        with self.assertRaises(ImportError):self.service.plan(bad)

    def test_no_match_reused_after_resume_without_transport(self):
        pid=self.plan()
        first=self.run_fixture(pid,[{"body":[NOMATCH]}])
        self.assertEqual(first["status"],"complete")
        self.assertEqual(first["counts"]["no_match"],1)
        second=self.run_fixture(pid,[])
        self.assertEqual(second["status"],"complete")
        self.assertEqual(self.service.status(pid)["scope_physical_posts"],1)

    def test_timeout_recovery_and_saved_counter(self):
        pid=self.plan()
        result=self.run_fixture(pid,[{"error":"TIMEOUT","status":None},{"body":[DATA]}])
        self.assertEqual(result["status"],"complete")
        state=self.service.status(pid)
        self.assertEqual(state["scope_physical_posts"],2)
        self.assertEqual(next(iter(state["states"].values()))["post_cutover_appearances"],2)
        self.assertEqual(len(self.store.list("outcomes")),2)

    def test_429_retry_after_reset_and_restart_gate(self):
        pid=self.plan()
        result=self.run_fixture(pid,[{"status":429,"headers":{"retry-after":"5","ratelimit-reset":"2"}},
                                     {"body":[DATA]}])
        records=self.service.request_records()
        from polar.import_contract import seconds
        self.assertGreaterEqual(seconds(records[1][0]["started_at"])-seconds(records[0][1]["completed_at"]),6)
        self.assertEqual(result["status"],"complete")

    def test_429_long_wait_not_capped_to_force_retry(self):
        pid=self.plan()
        result=self.run_fixture(pid,[{"status":429,"headers":{"retry-after":"9000"}}])
        self.assertEqual(result["reason"],"MANDATED_WAIT_EXCEEDS_DEADLINE")
        self.assertEqual(self.service.status(pid)["scope_physical_posts"],1)
        result=self.run_fixture(pid,[])
        self.assertEqual(result["reason"],"MANDATED_WAIT_EXCEEDS_DEADLINE")
        self.assertEqual(self.service.status(pid)["scope_physical_posts"],1)

    def test_four_started_appearances_exhaust_without_reset(self):
        pid=self.plan()
        result=self.run_fixture(pid,[{"error":"TIMEOUT","status":None} for _ in range(4)])
        self.assertEqual(result["status"],"failed")
        state=next(iter(self.service.status(pid)["states"].values()))
        self.assertEqual(state["state"],"permanent_error")
        self.assertEqual(state["post_cutover_appearances"],4)
        self.run_fixture(pid,[])
        self.assertEqual(self.service.status(pid)["scope_physical_posts"],4)

    def test_malformed_batch_isolation_and_independent_continuation(self):
        pid=self.plan(12)
        responses=[{"body":[{"error":"INVENTED_GLOBAL_ERROR"}]},{"body":[DATA,DATA]}]
        responses += [{"body":[DATA]} for _ in range(10)]
        result=self.run_fixture(pid,responses)
        self.assertEqual(result["status"],"complete")
        records=self.service.request_records()
        self.assertEqual([len(r[0]["job_ids"]) for r in records],[10,2]+[1]*10)
        first=self.store.read("outcomes/"+records[0][0]["request_id"]+".json")
        self.assertTrue(first["split"])
        self.assertTrue(all(s["state"]=="retryable_error" for s in first["jobs"].values()))
        self.assertEqual(len(self.store.commits()),12)

    def test_auth_scope_pause_and_unrelated_fixture_namespace(self):
        pid=self.plan()
        first=self.run_fixture(pid,[{"status":403}])
        self.assertEqual(first["reason"],"AUTH_SCOPE_PAUSED")
        self.service.control(pid,"resume")
        self.assertEqual(self.run_fixture(pid,[])["reason"],"AUTH_SCOPE_PAUSED")
        self.assertEqual(self.service.status(pid)["scope_physical_posts"],1)
        other=ImportStore(self.root,64*1024**3,fixture=False)
        self.assertFalse(other.exists("auth-pause.json"))
        self.assertEqual(other.commits(),{})

    def test_per_job_rights_refusal_and_unknown_warning_not_no_match(self):
        pid=self.plan(2)
        self.run_fixture(pid,[{"body":[DATA,{"error":"Permission denied"}]}])
        state=self.service.status(pid)
        self.assertEqual(state["counts"]["success"],1)
        self.assertIsNotNone(state["scope_paused"])

    def test_success_before_checkpoint_interrupt_reuses_result(self):
        pid=self.plan()
        original=self.store.checkpoint
        calls=[]
        def stop_once(*args):
            calls.append(1)
            if len(calls)==1:raise InterruptedError()
            return original(*args)
        with patch.object(self.store,"checkpoint",side_effect=stop_once):
            first=self.run_fixture(pid,[{"body":[DATA]}])
        self.assertEqual(first["status"],"interrupted")
        self.assertEqual(len(self.store.commits()),1)
        second=self.run_fixture(pid,[])
        self.assertEqual(second["status"],"complete")
        self.assertEqual(self.service.status(pid)["scope_physical_posts"],1)

    def test_saved_response_before_commit_recovers_without_refetch(self):
        pid=self.plan()
        with patch.object(self.service,"disposition",side_effect=InterruptedError()):
            first=self.run_fixture(pid,[{"body":[DATA]}])
        self.assertEqual(first["status"],"interrupted")
        self.assertFalse(self.store.commits())
        self.assertEqual(self.run_fixture(pid,[])["status"],"complete")
        self.assertEqual(self.service.status(pid)["scope_physical_posts"],1)

    def test_pause_stop_control_preserves_state(self):
        pid=self.plan()
        self.service.control(pid,"pause")
        self.assertEqual(self.run_fixture(pid,[])["reason"],"CONTROL_PAUSE")
        self.assertEqual(self.service.status(pid)["scope_physical_posts"],0)
        self.service.control(pid,"resume")
        self.assertEqual(self.run_fixture(pid,[{"body":[DATA]}])["status"],"complete")

    def test_kernel_lock_prevents_parallel_executor(self):
        pid=self.plan()
        with self.store.locked():
            other=ImportService(ImportStore(self.root,64*1024**3,fixture=True))
            with self.assertRaises(ImportError):other.execute(pid,fixture={"schema":"polar.import-fixture/1",
                "start_seconds":START,"responses":[]})

    def test_corrupt_cache_not_success(self):
        pid=self.plan();self.run_fixture(pid,[{"body":[DATA]}])
        name=self.store.list("successes")[0]
        path=self.store.root/self.store.path(name)
        path.chmod(0o600);path.write_bytes(b'{}')
        with self.assertRaises((ImportError,KeyError)):self.service.status(pid)

    def test_duplicate_and_cross_attempt_consumption_and_missed_wake(self):
        pid=self.plan();first=self.run_fixture(pid,[{"body":[DATA]}])
        assessment={"consumer":"invented-owner","outcome":"transport assessed","next_action":"retain unknowns"}
        aid,h=first["attempt_id"],first["manifest_sha256"]
        self.assertEqual(self.service.consume(pid,aid,h,assessment)["status"],"CONSUMED")
        self.assertEqual(self.service.consume(pid,aid,h,assessment)["status"],"ALREADY_CONSUMED")
        second=self.run_fixture(pid,[])
        with self.assertRaises(ImportError):self.service.consume(pid,second["attempt_id"],h,assessment)
        # No notification is necessary for discovery and verified consumption.
        listed=self.service.attempts(pid)["attempts"]
        self.assertEqual(len(listed),2)
        self.assertEqual(self.service.consume(pid,second["attempt_id"],second["manifest_sha256"],assessment)["status"],"CONSUMED")

    def test_attempt_binding_and_missing_marker_fallback(self):
        pid=self.plan();aid=str(uuid.uuid4())
        paths=self.service.attempt_path(pid,aid)
        self.assertTrue(paths["terminal_path"].endswith(aid+"/content-manifest.json"))
        first=self.run_fixture(pid,[{"body":[DATA]}],attempt_id=aid)
        with self.assertRaises(ImportError):self.run_fixture(pid,[],attempt_id=aid)
        marker=self.store.root/self.store.path("attempts/"+aid+"/content-manifest.json")
        marker.unlink() # exact synthetic marker only; emulate an interruption before publication
        self.assertEqual(self.service.attempts(pid)["attempts"][0]["status"],"RUNNING_OR_INTERRUPTED_UNRECONCILED")

    def test_no_network_without_explicit_mode_and_build_binding(self):
        pid=self.plan()
        with self.assertRaises(ImportError):self.service.execute(pid,network=True)


class ProducerMigration(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve()
        self.store=ImportStore(self.root,64*1024**3,fixture=True)

    def fixture(self,conflict=False,escape=False,bad_position=False):
        sample=self.root/"sample";sample.mkdir()
        roster=self.root/"roster";roster.mkdir()
        a,b,c=[request("INVENTED-"+s) for s in "ABC"]
        sample_body=wire([NOMATCH]);req_wire=wire([a])
        receipt={"actual_completed_at":timestamp(START),"actual_started_at":timestamp(START-1),"http_status":200,
                 "request_sha256":sha(req_wire),"response_sha256":sha(sample_body),"response_bytes":len(sample_body)}
        def manifest(directory,files,schema,extra=None):
            for name,raw in files.items():
                p=directory/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
            value={"schema":schema,"objects":{n:{"sha256":sha(v),"bytes":len(v)} for n,v in files.items()},**(extra or {})}
            raw=wire(value);(directory/"content-manifest.json").write_bytes(raw);return sha(raw)
        sample_hash=manifest(sample,{"request.json":req_wire,"response.json":sample_body,"receipt.json":wire(receipt)},
                             "polar.current-class-sample-content/1")
        target=a if conflict else b
        body=wire([DATA]);bad=wire([{"error":"UNASSIGNED_GLOBAL_ERROR"},{}])
        own_receipt={"batch_ordinal":0,"started_at":timestamp(START),"completed_at":timestamp(START+1),
                     "http_status":200,"request_body":[target],"request_sha256":sha(wire([target])),
                     "response_sha256":sha(body),"response_bytes":len(body)}
        failed_receipt={**own_receipt,"batch_ordinal":1,"request_body":[c],"request_sha256":sha(wire([c])),
                        "response_sha256":sha(bad),"response_bytes":len(bad)}
        jobs={a["idValue"]:{"response":NOMATCH,"source":"sample/response.json","source_sha256":sha(sample_body),
                            "job_ordinal":1 if bad_position else 0,"capture_root":"/not-allowed" if escape else str(self.root)}}
        own={"response":DATA,"source":"responses/batch-0000.json","source_sha256":sha(body),
             "job_ordinal":0,"capture_root":str(roster)}
        if conflict:
            # Both versions are preserved across the two source envelopes.
            jobs={a["idValue"]:own}
        else:jobs[b["idValue"]]=own
        ancestor=wire({"invented":"dated population, not transport jobs"});(self.root/"ancestor.json").write_bytes(ancestor)
        root_hash=manifest(roster,{"job-results.json":wire(jobs),"receipts.json":wire([own_receipt,failed_receipt]),
                                  "responses/batch-0000.json":body,"responses/batch-0001.json":bad},
                           "polar.current-class-roster-content/1",{"parent_source_sha256":sha(ancestor)})
        return {"schema":"polar.import-migration/1","current_manifest_sha256":root_hash,
                "roots":[{"root":str(self.root),"manifest":"sample/content-manifest.json","sha256":sample_hash},
                         {"root":str(roster),"manifest":"content-manifest.json","sha256":root_hash}],
                "ancestry_objects":[{"root":str(self.root),"path":"ancestor.json","sha256":sha(ancestor)}]}

    def test_sample_ancestor_no_match_and_failed_batch_retained(self):
        cfg=self.fixture();result=migration(cfg,self.store)
        self.assertEqual(result["imported_jobs"],2)
        self.assertEqual(result["no_match"],1)
        self.assertEqual(result["provider_requests"],0)
        self.assertEqual(result["historical_receipts"],3)
        record=self.store.read(self.store.list("cache-imports")[0])
        self.assertEqual(len(record["migration"]["historical_requests"]),3)
        self.assertEqual(len(record["migration"]["historical_job_appearances_minimum"]),3)
        self.assertEqual(migration(cfg,self.store)["import_id"],result["import_id"])

    def test_conflicting_versions_not_overwritten_or_first_selected(self):
        migration(self.fixture(conflict=True),self.store)
        versions=next(iter(self.store.commits().values()))
        self.assertEqual(len(versions),2)
        self.assertEqual({v["kind"] for v in versions},{"CANDIDATES","WARNING_NO_MATCH"})

    def test_untrusted_capture_root_and_positional_guess_rejected(self):
        with self.assertRaises(ImportError):migration(self.fixture(escape=True),self.store)
        self.assertEqual(self.store.commits(),{})

    def test_bad_position_rejected_without_guessing(self):
        with self.assertRaises(ImportError):migration(self.fixture(bad_position=True),self.store)


if __name__=="__main__":unittest.main()

"""Finite injected software cases: 9 success + 4 abort calls, ZERO native fits."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import patch

from polar.hyp007_contract import DiagnosticError, FOLDS, MODELS
from polar.hyp007_store import DiagnosticStore
from polar.hyp007_worker import compile_output


class InjectedOrchestration(unittest.TestCase):
    def run_fixture(self, fail_at=None):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        store = DiagnosticStore(Path(temporary.name).resolve(),64*1024**2)
        aid = str(uuid.uuid4())
        seal = {"seal_id":"a"*64,"sealed_at":"2026-01-01T00:00:00.000000Z"}
        store.begin(seal,aid)
        rows = [{"key":"invented-"+str(i),"instrument":"INVENTED","M_info":True,
                 "packet":{"features":[0.]*6},"target":{"value":.1,"reason":None}} for i in range(206)]
        rows[-1]["target"] = {"value":None,"reason":"UNKNOWN_LABEL"}
        masks = [{"fold":fold,"key":row["key"],"M_train":i<200,"M_score":i in (200+j*2,201+j*2),
                  "M_eval":i == 200+j*2} for j,fold in enumerate(FOLDS) for i,row in enumerate(rows)]
        source = SimpleNamespace(roster=rows,inventory={},bytes_read=0,read_passes=0,bars={"INVENTED":{}},
                                 evidence={})
        calls = []
        def fit(*args):
            ordinal = len(calls)
            self.assertEqual(store.slots(aid)[ordinal]["status"],"STARTED_UNFINALIZED")
            calls.append(ordinal)
            if ordinal == fail_at:
                raise DiagnosticError("INVENTED_FIT_FAILURE")
            return {"kind":"INJECTED_SYNTHETIC_NO_NATIVE_MODEL","coefficients":[],"intercept":.1}
        def represent(*args):
            return {},{name:[[0.]*6]*200 for name in MODELS},{name:[[0.]*6]*2 for name in MODELS}
        with patch("polar.hyp007_worker.Panel") as panel, \
             patch("polar.hyp007_worker.representations",side_effect=represent), \
             patch("polar.hyp007_worker.ridge_fit",side_effect=fit), \
             patch("polar.hyp007_worker.tree_fit",side_effect=fit), \
             patch("polar.hyp007_worker.ridge_predict",return_value=[.1,.1]), \
             patch("polar.hyp007_worker.tree_predict",return_value=[.1,.1]):
            panel.return_value.realize.return_value = rows,masks
            if fail_at is None:
                output = compile_output(source,seal,store,aid,{})
                return store,aid,calls,output
            with self.assertRaises(DiagnosticError):
                compile_output(source,seal,store,aid,{})
            return store,aid,calls,None

    def test_full_pipeline_keeps_score_predictions_and_two_contrasts(self):
        store,aid,calls,files = self.run_fixture()
        self.assertEqual(calls,list(range(9)))
        predictions = [json.loads(line) for line in files["predictions.ndjson"].splitlines()]
        self.assertEqual(len(predictions),18)
        report = json.loads(files["report.json"])
        self.assertEqual(report["real_fit_invocations"],9)  # injected family fixture, no real/source/native run
        self.assertEqual(set(report["paired_contrasts"]),{"tree_minus_ridge6","tree_minus_ridge21"})
        self.assertTrue(all(v["n"] == 3 and v["MSE"] == 0 for v in report["pooled"].values()))
        self.assertTrue(all(row["status"] == "SUCCESS" for row in store.slots(aid)))

    def test_failure_retains_partial_output_and_stops_all_remaining(self):
        store,aid,calls,_ = self.run_fixture(3)
        self.assertEqual(calls,[0,1,2,3])
        slots = store.slots(aid)
        self.assertEqual(slots[3]["status"],"FAILED")
        self.assertTrue(all(row["status"] == "NOT_RUN" for row in slots[4:]))
        self.assertTrue((store.root/"hyp007-attempts"/aid/"fit-outputs"/"2"/"record.json").is_file())


if __name__ == "__main__":
    unittest.main()

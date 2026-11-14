"""Invented children only; bounded supervisor Linux checks, no financial inputs."""
import ast
import inspect
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from polar.hyp007_contract import DiagnosticError
from polar.process_budget import supervise


class BoundsValidation(unittest.TestCase):
    def test_selected_limits_are_strict_positive_finite(self):
        for name in ("rss_limit_bytes", "max_output_bytes", "max_journal_bytes"):
            for value in (True, False, 0, -1, .5, float("inf"), float("nan"), "10"):
                with self.subTest(name=name, value=value), self.assertRaises(DiagnosticError):
                    supervise([], env={}, output=Path("unused"), **{name: value})
        for name in ("cpu_seconds", "wall_seconds", "poll", "cleanup_seconds"):
            for value in (True, False, 0, -1, float("inf"), float("nan"), "10", 10**400):
                with self.subTest(name=name, value=value), self.assertRaises(DiagnosticError):
                    supervise([], env={}, output=Path("unused"), max_output_bytes=10,
                              **{name: value})

    def test_legacy_defaults_and_optional_signature(self):
        signature = inspect.signature(supervise)
        self.assertEqual(signature.parameters["cpu_seconds"].default, 600.)
        self.assertEqual(signature.parameters["wall_seconds"].default, 900.)
        self.assertEqual(signature.parameters["poll"].default, .05)
        for name in ("rss_limit_bytes", "max_output_bytes", "max_journal_bytes", "cleanup_seconds"):
            self.assertIsNone(signature.parameters[name].default)
        ast.parse(inspect.getsource(supervise))


@unittest.skipUnless(sys.platform == "linux", "requires Linux /proc and wait4")
class BoundedProcesses(unittest.TestCase):
    def run_case(self, code, **limits):
        selected = dict(cpu_seconds=5., wall_seconds=3., poll=.01,
                        max_output_bytes=4096, max_journal_bytes=65536,
                        cleanup_seconds=1.)
        selected.update(limits)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/"owned.log"
            result = supervise([sys.executable, "-c", code], env=dict(os.environ),
                               output=output, **selected)
            log = output.read_bytes()
            journal = output.with_suffix(".resources.ndjson").read_bytes()
        self.assertLessEqual(len(log), selected["max_output_bytes"])
        self.assertLessEqual(len(journal), selected["max_journal_bytes"])
        self.assertEqual(result["output_written_bytes"], len(log))
        self.assertEqual(result["journal_written_bytes"], len(journal))
        for line in journal.splitlines():
            json.loads(line)
        return result, log

    def assert_reaped(self, result):
        self.assertEqual(result["cleanup"], "COMPLETE")
        self.assertFalse(result["cleanup_timed_out"])
        self.assertEqual(result["remaining_owned_pids"], [])
        with self.assertRaises(ProcessLookupError):
            os.killpg(result["owned_process_group_id"], 0)

    def test_runaway_combined_output_exact_cap(self):
        result, log = self.run_case(
            "import os; os.fork(); exec('while True:\\n os.write(1,b\\\"x\\\"*8192)\\n os.write(2,b\\\"y\\\"*8192)')")
        self.assertEqual(result["failure"], "OUTPUT_LIMIT")
        self.assertEqual(len(log), 4096)
        self.assertTrue(result["output_truncated"])
        self.assertGreater(result["output_observed_bytes"], len(log))
        self.assert_reaped(result)

    def test_wall_limit_includes_forked_group(self):
        result, _ = self.run_case("import os,time; os.fork(); time.sleep(30)", wall_seconds=.12)
        self.assertEqual(result["failure"], "WALL_LIMIT")
        self.assert_reaped(result)

    def test_rss_limit_observes_allocated_child(self):
        result, _ = self.run_case("import time; x=bytearray(64*1024*1024); time.sleep(30)",
                                  rss_limit_bytes=24*1024*1024)
        self.assertEqual(result["failure"], "RSS_LIMIT")
        self.assertGreater(result["sampled_group_rss_peak_bytes"], 24*1024*1024)
        self.assert_reaped(result)

    def test_tiny_journal_cap_preserves_valid_ndjson(self):
        result, _ = self.run_case("import time; time.sleep(30)", max_journal_bytes=1)
        self.assertEqual(result["failure"], "JOURNAL_LIMIT")
        self.assertEqual(result["journal_written_bytes"], 0)
        self.assertTrue(result["journal_truncated"])
        self.assert_reaped(result)

    def test_cpu_limit_explicit_accounting(self):
        result, _ = self.run_case("import os; os.fork(); exec('while True: pass')",
                                  cpu_seconds=.15)
        self.assertEqual(result["failure"], "CPU_LIMIT")
        self.assertGreaterEqual(result["observed_cpu_seconds"], .15)
        self.assertGreater(result["child_cpu_seconds"], 0.)
        self.assertAlmostEqual(result["cpu_seconds"],
                               result["child_cpu_seconds"]+result["supervisor_cpu_seconds"])
        self.assert_reaped(result)

    def test_success_with_bounds(self):
        result, log = self.run_case("import os; os.write(1,b'out'); os.write(2,b'err')")
        self.assertEqual(log, b"outerr")
        self.assertIsNone(result["failure"])
        self.assertEqual(result["exit_code"], 0)
        self.assertFalse(result["output_truncated"])
        self.assertFalse(result["journal_truncated"])
        self.assertTrue(result["output_eof"])
        self.assert_reaped(result)

    def test_cleanup_timeout_preserves_uncertainty(self):
        # Deterministic instrument surrogate for an uncollectable group member;
        # actual child is still owned and killed/reaped by the real supervisor.
        started = time.monotonic()
        with patch("polar.process_budget.group_sample", return_value=(0., 0, [99999999])):
            result, _ = self.run_case("import time; time.sleep(30)",
                                      wall_seconds=.05, cleanup_seconds=.08)
        self.assertLess(time.monotonic()-started, 2.)
        self.assertEqual(result["failure"], "WALL_LIMIT")
        self.assertEqual(result["cleanup"], "INCOMPLETE")
        self.assertTrue(result["cleanup_timed_out"])
        self.assertEqual(result["remaining_owned_pids"], [99999999])
        self.assertIsNotNone(result["exit_code"])
        with self.assertRaises(ProcessLookupError):
            os.killpg(result["owned_process_group_id"], 0)

    def test_legacy_normal_case(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/"legacy.log"
            result = supervise([sys.executable, "-c", "print('legacy')"],
                               env=dict(os.environ), output=output,
                               cpu_seconds=5., wall_seconds=3.)
            self.assertEqual(output.read_bytes(), b"legacy\n")
        self.assertEqual(result["exit_code"], 0)
        self.assertIsNone(result["failure"])
        self.assertEqual(result["cleanup"], "COMPLETE")
        self.assertNotIn("max_output_bytes", result)


if __name__ == "__main__":
    unittest.main()

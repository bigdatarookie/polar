"""Three finite invented process trees, no models/data/production processes."""
import os
from pathlib import Path
import sys
import tempfile
import unittest

from polar.process_budget import supervise


@unittest.skipUnless(sys.platform == "linux", "exact Linux build required")
class OwnedProcesses(unittest.TestCase):
    def run_case(self, code, **limits):
        with tempfile.TemporaryDirectory() as directory:
            return supervise([sys.executable,"-c",code], env=dict(os.environ),
                             output=Path(directory)/"owned.log", **limits)

    def test_success_and_descendant_cpu(self):
        result = self.run_case("import os,time; p=os.fork(); "
            "exec('if p == 0:\\n t=time.process_time()\\n while time.process_time()-t < .03: pass\\n os._exit(0)\\nelse: os.waitpid(p,0)')",
            cpu_seconds=5,wall_seconds=5)
        self.assertEqual(result["exit_code"],0)
        self.assertIsNone(result["failure"])
        self.assertGreater(result["cpu_seconds"],.025)
        self.assertEqual(result["remaining_owned_pids"],[])

    def test_cpu_kill_reaps_owned_group(self):
        result = self.run_case("import os; p=os.fork(); exec('while True: pass')",cpu_seconds=.15,wall_seconds=5)
        self.assertEqual(result["failure"],"CPU_LIMIT")
        self.assertGreaterEqual(result["cpu_seconds"],.15)
        self.assertEqual(result["cleanup"],"COMPLETE")

    def test_wall_kill_reaps_owned_group(self):
        result = self.run_case("import os,time; os.fork(); time.sleep(30)",cpu_seconds=5,wall_seconds=.2)
        self.assertEqual(result["failure"],"WALL_LIMIT")
        self.assertEqual(result["cleanup"],"COMPLETE")


if __name__ == "__main__":
    unittest.main()

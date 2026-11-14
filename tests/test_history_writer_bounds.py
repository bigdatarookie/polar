"""Invented byte payloads only; prove rejection happens before staging writes."""
from pathlib import Path
import tempfile
import os
import sys
import unittest
from unittest.mock import patch

from polar.history_bundle import HistoryError
from polar.history_store import HistoryStore


class WriterBounds(unittest.TestCase):
    def test_oversized_later_member_never_writes_earlier_member(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = str(Path(directory).resolve())
            store = HistoryStore(directory, 100)
            original = Path.open
            writes = []
            def tracked(path, mode='r', *args, **kwargs):
                if mode == 'xb':
                    writes.append(str(path))
                return original(path, mode, *args, **kwargs)
            with patch.object(Path, 'open', tracked):
                with self.assertRaisesRegex(HistoryError, 'HISTORY_FILE_LIMIT'):
                    store._publish('invented', 'rejected',
                                   {'small': b'a', 'too-large': b'12345'}, file_limit=4)
            self.assertEqual(writes, [])
            self.assertEqual(list(Path(directory).rglob('.history-partial-*')), [])
            self.assertFalse((Path(directory)/'invented'/'rejected').exists())

    def test_root_quota_rejects_before_staging_and_preserves_completed(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = str(Path(directory).resolve())
            store = HistoryStore(directory, 5)
            with store.locked():
                store._publish('invented', 'completed', {'record': b'123'}, file_limit=3)
                with self.assertRaisesRegex(HistoryError, 'HISTORY_STORAGE_LIMIT'):
                    store._publish('invented', 'rejected', {'record': b'456'}, file_limit=3)
            self.assertEqual((Path(directory)/'invented/completed/record').read_bytes(), b'123')
            self.assertEqual(store.used(), 3)
            self.assertFalse((Path(directory)/'invented/rejected').exists())
            self.assertEqual(list(Path(directory).rglob('.history-partial-*')), [])

    def test_exact_per_file_and_root_boundary_remain_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = str(Path(directory).resolve())
            store = HistoryStore(directory, 8)
            files = {'one': b'1234', 'nested/two': b'5678'}
            with store.locked():
                store._publish('invented', 'completed', files, file_limit=4)
                store._publish('invented', 'completed', files, file_limit=4)
            self.assertEqual(store.used(), 8)
            self.assertEqual((Path(directory)/'invented/completed/nested/two').read_bytes(), b'5678')
            self.assertEqual(list(Path(directory).rglob('.history-partial-*')), [])


@unittest.skipUnless(sys.platform == 'linux', 'Linux supervised consumer')
class SupervisedWriter(unittest.TestCase):
    def test_store_quota_failure_under_bounded_outer_supervisor_preserves_prefix(self):
        from polar.process_budget import supervise
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)/'store'
            root.mkdir()
            log = Path(directory)/'operation.log'
            code = """from polar.history_store import HistoryStore
import sys
store=HistoryStore(sys.argv[1],96)
with store.locked():
    for i in range(4):
        store._publish('invented',str(i),{'record':b'x'*32},file_limit=32)
"""
            result = supervise([sys.executable, '-c', code, str(root)],
                               env=dict(os.environ), output=log,
                               cpu_seconds=5., wall_seconds=5., poll=.01,
                               rss_limit_bytes=256*1024**2, max_output_bytes=4096,
                               max_journal_bytes=65536, cleanup_seconds=1.)
            self.assertNotEqual(result['exit_code'], 0)
            self.assertEqual(result['cleanup'], 'COMPLETE')
            self.assertEqual(result['remaining_owned_pids'], [])
            self.assertIn(b'HISTORY_STORAGE_LIMIT', log.read_bytes())
            self.assertLessEqual(log.stat().st_size, 4096)
            self.assertLessEqual(log.with_suffix('.resources.ndjson').stat().st_size, 65536)
            self.assertEqual(HistoryStore(root,96).used(), 96)
            self.assertEqual(len(list(root.glob('invented/*/record'))), 3)
            self.assertFalse((root/'invented/3').exists())
            self.assertEqual(list(root.rglob('.history-partial-*')), [])


if __name__ == '__main__':
    unittest.main()

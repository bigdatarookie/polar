"""Invented source-grid and causality controls; no retained input or model fit."""
from pathlib import Path
import copy
import hashlib
import json
import tempfile
import unittest
from fractions import Fraction

from polar.research_reference import load_reference, trailing_return, BASIS, UNIT


def encoded(x):
    return (json.dumps(x, sort_keys=True, separators=(',', ':'))+'\n').encode()


class ReferenceInput(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name).resolve()
        self.days = ['2020-01-02', '2020-01-03', '2020-01-06']
        self.rows = [{'date': d, 'reference_open_utc': d+'T14:30:00+00:00',
                      'reference_close_utc': d+'T21:00:00+00:00',
                      'next_reference_date': self.days[i+1] if i+1 < 3 else None}
                     for i,d in enumerate(self.days)]
        self.quotes = [{'symbol': symbol, 'date': d, 'reference_quote': f'{10+i}.000000',
                        'source_adjusted_close_token': str(10+i),
                        'source_ref': {'normalized_member_sha256': 'a'*64, 'line_1based': i+1,
                                       'line_sha256': 'b'*64, 'raw_object_sha256': 'c'*64,
                                       'source_row_index': i}, 'observed_published_at': None,
                        'observed_historical_available_at': None}
                       for i,d in enumerate(self.days) for symbol in ['AAA', 'BBB']]

    def tearDown(self):
        self.temp.cleanup()

    def pin(self, name, raw):
        p = self.root/name; p.write_bytes(raw)
        return {'path': str(p), 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}

    def fixture(self):
        schedule = self.pin('schedule.json', encoded({'schema': 'polar.xnys-reference-schedule/1', 'rows': self.rows}))
        quotes = self.pin('quotes.ndjson', b''.join(encoded(row) for row in self.quotes))
        m = {'schema': 'polar.synthetic-reference-source-input/1', 'quote_basis': BASIS, 'unit_type': UNIT,
             'double_action_policy': 'NO_ADDITIONAL_SPLIT_DIVIDEND_CREDIT_IN_REFERENCE_UNIT_MODEL',
             'symbols': ['AAA', 'BBB'], 'dates': {'count': 3, 'start': self.days[0], 'end': self.days[-1]},
             'rows': 6, 'schedule': schedule, 'quotes': quotes, 'source_members': [{'sha256': 'a'*64}],
             'parent_dataset_revision': 'invented-revision', 'rights': 'INVENTED_PUBLIC_TEST'}
        return self.pin('manifest.json', encoded(m))

    def test_lossless_scale_grid_and_unknown_clocks(self):
        m = load_reference(self.fixture())
        self.assertEqual(m['prices_micro'][self.days[1]]['AAA'], 11000000)
        self.assertIsNone(m['source_evidence'][self.days[0]]['BBB']['observed_historical_available_at'])
        self.assertEqual((m['eligibility'], m['action_credit']), ('NOT_DERIVED', 'NONE'))
        self.assertEqual(trailing_return(m, 'AAA', 1, 1), Fraction(1,10))

    def test_future_quote_cannot_change_earlier_return(self):
        before = trailing_return(load_reference(self.fixture()), 'AAA', 1, 1)
        for row in self.quotes:
            if row['date'] == self.days[2]:
                row['reference_quote'] = '999.000000'; row['source_adjusted_close_token'] = '999'
        self.assertEqual(trailing_return(load_reference(self.fixture()), 'AAA', 1, 1), before)

    def test_reject_missing_reordered_and_scale_changed_cells(self):
        original = copy.deepcopy(self.quotes)
        for modify in ('missing', 'reorder', 'scale', 'precision', 'source'):
            with self.subTest(modify=modify):
                self.quotes = copy.deepcopy(original)
                if modify == 'missing': self.quotes.pop()
                if modify == 'reorder': self.quotes[0], self.quotes[1] = self.quotes[1], self.quotes[0]
                if modify == 'scale': self.quotes[0]['reference_quote'] = '0.010000'
                if modify == 'precision': self.quotes[0]['reference_quote'] = '10.0000001'
                if modify == 'source': self.quotes[0]['source_ref']['normalized_member_sha256'] = 'd'*64
                with self.assertRaises(ValueError): load_reference(self.fixture())

    def test_changed_bound_file_is_rejected_before_values_are_used(self):
        pin = self.fixture()
        with (self.root/'quotes.ndjson').open('ab') as f: f.write(b'\n')
        with self.assertRaisesRegex(ValueError, 'REFERENCE_FILE_SIZE'): load_reference(pin)

    def test_schedule_cannot_skip_next_session_or_lose_timezone(self):
        for field, value in [('next_reference_date', self.days[2]), ('reference_close_utc', self.days[0]+'T21:00:00')]:
            saved = self.rows[0][field]; self.rows[0][field] = value
            with self.assertRaises(ValueError): load_reference(self.fixture())
            self.rows[0][field] = saved

"""Invented operands only; never read the task's private AA close inputs."""
from copy import deepcopy
from datetime import date, timedelta
from decimal import localcontext
from fractions import Fraction
import json
from pathlib import Path
import subprocess
import sys

import pytest

from polar.conditional_reference import AAOI_MODEL, AAWW_MODEL, MODEL, STATUS, ReferenceError, build, construct
from polar.gym_contract import GymError, canonical, sha
from polar.history_bundle import HistoryError


def fixture():
    dates = [(date(2020, 1, 1) + timedelta(days=i)).isoformat() for i in range(253)]
    tokens = ['10.0000', '11.2500', '9.5000']
    rows = []
    for i, day in enumerate(dates):
        token = tokens[i % 3]
        raw_value = canonical({'c': token, 't': day})
        rows.append({'reference_date': day, 'raw_close_token': token, 'close_token_sha256': sha(token.encode()),
                     'prior_close_domain': 'VALID_POSITIVE_FINITE_PER_CONSUMED_FIELD_DELIVERY',
                     'record_id': 'listingrow-' + 'a' * 64, 'profile_id': 'b' * 64,
                     'source': {'manifest_sha256': 'c' * 64, 'member': 'bars.ndjson',
                                'member_previous_pin': {'sha256': sha(b'invented-original-member'), 'bytes': 24},
                                'row_ordinal': 10 + i, 'raw_line_sha256': sha(raw_value + b'\n'),
                                'raw_value_sha256': sha(raw_value),
                                'source_reference': {'group': 0, 'page': 0, 'raw_file': 'invented.json',
                                                     'source_array': 'bars.INVENTED', 'source_row_ordinal': i,
                                                     'source_body_sha256': sha(raw_value)}},
                     'raw_clock': {'estimated_K': day + 'T05:00:00+00:00',
                                   'observed_historical_K': None, 'label': 'INVENTED_RAW_ESTIMATE'},
                     **{k: None for k in ('entitlement_information_K', 'owner_model_information_K', 'combined_decision_use_K')},
                     **{k + '_status': 'UNBOUND' for k in ('entitlement_information_K', 'owner_model_information_K', 'combined_decision_use_K')}})
    descriptor = {'schema': 'polar.original-conditional-reference-input/1',
                  'model': MODEL.copy(), 'record_id': rows[0]['record_id'], 'profile_id': rows[0]['profile_id'],
                  'required_output': {'counts': {'closes': 253, 'adjacent_gross_factors': 252}, 'status': STATUS}}
    return descriptor, rows, {'dates': dates, 'role': 'Invented fixed chronology'}


def materialize(tmp_path):
    descriptor, rows, grid = fixture()
    for key, name, raw in [('close_operands', 'invented.ndjson', b''.join(canonical(r) for r in rows)),
                           ('date_grid', 'grid.json', canonical(grid))]:
        path = tmp_path / name
        path.write_bytes(raw)
        descriptor[key] = {'path': str(path), 'sha256': sha(raw), 'bytes': len(raw)}
    path = tmp_path / 'descriptor.json'
    path.write_bytes(canonical(descriptor))
    output = tmp_path / 'output'
    output.mkdir(mode=0o700)
    return {'path': str(path), 'sha256': sha(path.read_bytes())}, output


def test_full_order_exact_independent_ratios_and_endpoint_provenance():
    descriptor, rows, grid = fixture()
    original = deepcopy(rows)
    with localcontext() as ctx:
        ctx.prec = 2  # Decimal->Fraction and rational division must ignore context precision.
        result = build(descriptor, rows, grid)
    assert result['closes'] == original == rows
    assert result['counts'] == {'closes': 253, 'adjacent_gross_factors': 252, 'invalidated_factors': 0}
    factors = result['adjacent_gross_factors']
    assert [f['gross_factor'] for f in factors[:3]] == [
        {'numerator': '9', 'denominator': '8'}, {'numerator': '38', 'denominator': '45'},
        {'numerator': '20', 'denominator': '19'}]
    for i, f in enumerate(factors):
        assert f['left'] == original[i] and f['right'] == original[i+1]
        assert f['ordinal'] == i
        assert f['left']['source']['row_ordinal'] == 10 + i
        assert f['left']['source']['source_reference']['source_row_ordinal'] == i
    # Modifying caller memory after build cannot mutate persisted endpoint evidence.
    rows[0]['source']['member'] = 'changed'
    assert result['closes'][0] == original[0]


def test_long_exact_tokens_not_quantized():
    d, rows, g = fixture()
    rows[0]['raw_close_token'] = '123456789.01234567890123456789'
    rows[0]['close_token_sha256'] = sha(rows[0]['raw_close_token'].encode())
    factor = build(d, rows, g)['adjacent_gross_factors'][0]['gross_factor']
    assert Fraction(int(factor['numerator']), int(factor['denominator'])) == Fraction('11.2500') / Fraction('123456789.01234567890123456789')


@pytest.mark.parametrize('token', ['0', '-1', 'NaN', 'Infinity', '1_0', ' 10', '10\n', '1e999999', '1e-999999', 10.0, None])
def test_invalid_decimal_no_output(token):
    d, rows, g = fixture()
    rows[1]['raw_close_token'] = token
    with pytest.raises((ReferenceError, GymError)):
        build(d, rows, g)


def test_raw_k_maximum_is_not_information_k_and_missing_is_not_ignored():
    d, rows, g = fixture()
    # Lexical order differs from actual instant ordering; earlier source date has later K.
    rows[0]['raw_clock']['estimated_K'] = '2020-01-10T00:00:00+00:00'
    rows[1]['raw_clock']['estimated_K'] = '2020-01-10T01:00:00+02:00'
    result = build(d, rows, g)
    f = result['adjacent_gross_factors'][0]
    assert f['raw_clock']['estimated_K'] == rows[0]['raw_clock']['estimated_K']
    assert f['raw_clock']['observed_historical_K'] is None
    for k in ('entitlement_information_K', 'owner_model_information_K', 'combined_decision_use_K'):
        assert result[k] is None and f[k] is None and f[k + '_status'] == 'UNBOUND'
    rows[1]['raw_clock']['estimated_K'] = None
    f = build(d, rows, g)['adjacent_gross_factors'][0]
    assert f['raw_clock']['estimated_K'] is None
    assert f['raw_clock']['label'] == 'UNBOUND_ENDPOINT_ESTIMATE_MISSING'


@pytest.mark.parametrize('mutation', ['missing', 'duplicate', 'reorder', 'token_hash', 'identity', 'revision', 'clock', 'observed', 'information', 'model'])
def test_fail_closed_without_fill_or_semantic_promotion(mutation):
    d, rows, g = fixture()
    if mutation == 'missing': rows.pop(2)
    elif mutation == 'duplicate': rows[2] = deepcopy(rows[1])
    elif mutation == 'reorder': rows[1], rows[2] = rows[2], rows[1]
    elif mutation == 'token_hash': rows[2]['close_token_sha256'] = '0' * 64
    elif mutation == 'identity': rows[2]['profile_id'] = '0' * 64
    elif mutation == 'revision': rows[2]['source']['member_previous_pin']['sha256'] = '0' * 64
    elif mutation == 'clock': rows[2]['raw_clock']['estimated_K'] = '2020-01-10T00:00:00'
    elif mutation == 'observed': rows[2]['raw_clock']['observed_historical_K'] = '2020-01-10T00:00:00Z'
    elif mutation == 'information': rows[2]['combined_decision_use_K'] = '2020-01-10T00:00:00Z'
    elif mutation == 'model': d['model']['holder_multiplier'] = '2'
    with pytest.raises(ReferenceError): build(d, rows, g)


def test_contrary_evidence_invalidates_both_adjacent_edges_or_entire_series():
    d, rows, g = fixture()
    invalidation = {'reference_date': g['dates'][1], 'reason': 'QUALIFIED_CONTRARY_UNIT_EVIDENCE',
                    'evidence_ref': {'path': 'invented-evidence.json', 'sha256': 'e' * 64}}
    r = build(d, rows, g, [invalidation])
    assert r['counts']['invalidated_factors'] == 2
    assert all(f['gross_factor'] is None for f in r['adjacent_gross_factors'][:2])
    assert r['adjacent_gross_factors'][2]['gross_factor'] is not None
    invalidation['reference_date'] = None
    assert build(d, rows, g, [invalidation])['counts']['invalidated_factors'] == 252


def test_cli_immutable_roundtrip_and_idempotency(tmp_path):
    ref, root = materialize(tmp_path)
    command = [sys.executable, '-m', 'polar.conditional_reference', '--descriptor', ref['path'],
               '--descriptor-sha256', ref['sha256'], '--output-root', str(root)]
    p = subprocess.run(command, capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    first = json.loads(p.stdout)
    again = construct(ref, root)
    assert first == again
    directory = root / first['relative_path']
    assert set(p.name for p in directory.iterdir()) == {'report.json', 'manifest.json'}
    raw = (directory / 'report.json').read_bytes()
    assert sha(raw) == first['report_sha256']
    report = json.loads(raw)
    assert report['closes'][0]['raw_close_token'] == '10.0000'
    assert report['financial'] == 'NOT_RUN' and report['economic_N'] is None
    assert report['input_refs']['descriptor'] == ref
    assert len(report['builder_code_sha256']) == 4
    manifest = json.loads((directory / 'manifest.json').read_bytes())
    assert manifest['files']['report.json'] == {'sha256': sha(raw), 'bytes': len(raw)}
    (directory / 'report.json').chmod(0o600)
    (directory / 'report.json').write_bytes(b'changed')
    with pytest.raises(HistoryError, match='IMMUTABLE_CONFLICT'): construct(ref, root)


def test_hash_failure_and_symlink_read_do_not_publish(tmp_path):
    ref, root = materialize(tmp_path)
    original = Path(ref['path']).read_bytes()
    Path(ref['path']).write_bytes(original + b' ')
    with pytest.raises(GymError, match='REFERENCE_INTEGRITY'): construct(ref, root)
    assert list(root.iterdir()) == []
    Path(ref['path']).unlink()
    target = tmp_path / 'target.json'
    target.write_bytes(original)
    Path(ref['path']).symlink_to(target)
    with pytest.raises(GymError, match='UNSAFE_REFERENCE'): construct(ref, root)
    assert list(root.iterdir()) == []


@pytest.mark.parametrize('model', [AAOI_MODEL, AAWW_MODEL], ids=['AAOI', 'AAWW'])
def test_issue_label_preserved_through_immutable_publication_no_arithmetic_change(tmp_path, model):
    ref, root = materialize(tmp_path)
    d = json.loads(Path(ref['path']).read_bytes())
    d['model'] = model.copy()
    Path(ref['path']).write_bytes(canonical(d))
    ref['sha256'] = sha(Path(ref['path']).read_bytes())
    result = construct(ref, root)
    report = json.loads((root / result['relative_path'] / 'report.json').read_bytes())
    legacy_d, rows, grid = fixture()
    legacy = build(legacy_d, rows, grid)
    assert report['model'] == model and report['model'] != MODEL
    assert legacy['model'] == MODEL
    # Issue label support changes no factor, endpoint, clock, invalidation or evidence state.
    assert all(report[k] == v for k, v in legacy.items() if k != 'model')
    assert report['combined_decision_use_K'] is None
    assert report['combined_decision_use_K_status'] == 'UNBOUND'


@pytest.mark.parametrize('model', [AAOI_MODEL, AAWW_MODEL], ids=['AAOI', 'AAWW'])
@pytest.mark.parametrize('change', [
    {'unit_currency': 'ASSUMED_USD_PER_ASSUMED_UNKNOWN_COMMON_SHARE'},
    {'unit_currency': 'ASSUMED_USD_PER_ASSUMED_AAOI_PARENT_COMMON_SHARE '},
    {'unit_currency': 'USD'}, {'holder_multiplier': '2'}, {'common_cash': '1'},
    {'holder_multiplier': 1}, {'common_cash': 0},
    {'other_entitlements': 'PROVIDER_CERTIFIED_NONE'}, {'extra_assumption': 'allowed'},
])
def test_issue_support_keeps_closed_model_predicate(model, change):
    d, rows, grid = fixture()
    d['model'] = {**model, **change}
    with pytest.raises(ReferenceError, match='UNSUPPORTED_OWNER_MODEL'):
        build(d, rows, grid)

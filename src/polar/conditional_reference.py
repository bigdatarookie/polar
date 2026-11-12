"""Offline adjacent rational preparation; no decision-admissible or funded reference."""
import argparse
from datetime import date, datetime
from decimal import InvalidOperation
import json
from pathlib import Path
import re
import sys

from .gym_contract import canonical, decode, fraction, rational, read_ref, sha, GymError
from .history_bundle import HistoryError, read_file, safe_root
from .history_store import HistoryStore

STATUS = 'RETROSPECTIVE_CONDITIONAL_PREPARATION_REFERENCE'
LIMIT = 4 * 1024**2
K_FIELDS = ('entitlement_information_K', 'owner_model_information_K', 'combined_decision_use_K')
MODEL = {'holder_multiplier': '1', 'common_cash': '0',
         'other_entitlements': 'OWNER_EXPLICIT_NONE_FOR_LOCAL_PREPARATION',
         'unit_currency': 'ASSUMED_USD_PER_ASSUMED_POST_SEPARATION_COMMON_SHARE'}
AAOI_MODEL = {**MODEL, 'unit_currency': 'ASSUMED_USD_PER_ASSUMED_AAOI_PARENT_COMMON_SHARE'}
AAWW_MODEL = {**MODEL, 'unit_currency': 'ASSUMED_USD_PER_ASSUMED_AAWW_PARENT_COMMON_SHARE'}
MODEL_SEMANTICS = {'schema': 'polar.conditional-owner-model-semantics/1',
                   'currency': 'USD', 'quantity_unit': 'OWNER_ASSUMED_PARENT_COMMON_SHARE'}


class ReferenceError(ValueError):
    pass


def require(ok, code):
    if not ok:
        raise ReferenceError(code)


def hash_value(value):
    require(type(value) is str and re.fullmatch('[0-9a-f]{64}', value), 'INVALID_HASH')


def timestamp(value):
    require(type(value) is str and len(value) <= 64, 'INVALID_RAW_K')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        require(parsed.tzinfo is not None and parsed.utcoffset() is not None, 'INVALID_RAW_K')
        return parsed
    except ValueError:
        raise ReferenceError('INVALID_RAW_K') from None


def admit_descriptor(descriptor):
    """Validate the supported mechanism before any close operands are opened."""
    require(type(descriptor) is dict, 'INPUT_SCHEMA')
    version = descriptor.get('schema')
    require(version in ('polar.original-conditional-reference-input/1',
                        'polar.original-conditional-reference-input/2'), 'INPUT_SCHEMA')
    model = descriptor.get('model')
    if version.endswith('/1'):
        require(model in (MODEL, AAOI_MODEL, AAWW_MODEL), 'UNSUPPORTED_OWNER_MODEL')
    else:
        require(type(descriptor.get('model_semantics')) is dict and
                descriptor['model_semantics'] == MODEL_SEMANTICS, 'UNSUPPORTED_MODEL_SEMANTICS')
        require(type(model) is dict and set(model) == set(MODEL) and
                all(type(model[k]) is str and model[k] == MODEL[k]
                    for k in ('holder_multiplier', 'common_cash', 'other_entitlements')),
                'UNSUPPORTED_OWNER_MODEL')
        label = model['unit_currency']
        require(type(label) is str and 1 <= len(label) <= 256 and label.isprintable() and
                label == label.strip(), 'UNSUPPORTED_OWNER_MODEL')
        ref = descriptor.get('source_use_owner')
        require(type(ref) is dict and set(ref) == {'path', 'sha256', 'bytes'} and
                type(ref['path']) is str and Path(ref['path']).is_absolute() and
                type(ref['bytes']) is int and 0 < ref['bytes'] <= LIMIT,
                'OWNER_REFERENCE')
        hash_value(ref['sha256'])
    require(descriptor['required_output']['counts'] == {'closes': 253, 'adjacent_gross_factors': 252}, 'INPUT_COUNTS')
    require(descriptor['required_output']['status'] == STATUS, 'INPUT_STATUS')
    return version.endswith('/2')


def admit_owner(descriptor, owner):
    require(type(owner) is dict and owner.get('schema') ==
            'polar.quant-conditional-reference-owner-model/1', 'OWNER_SCHEMA')
    require(owner.get('record_id') == descriptor['record_id'], 'OWNER_RECORD')
    require(owner.get('owner_model') == descriptor['model'], 'OWNER_MODEL')
    interval = owner.get('interval')
    require(type(interval) is list and len(interval) == 2 and
            all(type(day) is str for day in interval), 'OWNER_INTERVAL')


def admit_grid(grid, owner=None):
    dates = grid['dates']
    require(type(dates) is list and len(dates) == 253 and all(type(d) is str for d in dates), 'GRID_COUNT')
    require(dates == sorted(set(dates)), 'GRID_NOT_STRICTLY_ORDERED')
    for day in dates:
        require(date.fromisoformat(day).isoformat() == day, 'INVALID_DATE')
    if owner is not None:
        require(owner['interval'] == [dates[0], dates[-1]], 'OWNER_INTERVAL')
    return dates


def build(descriptor, rows, grid, invalidations=(), *, owner=None):
    """Pure operation. V2 callers supply decoded owner metadata; no hidden reads."""
    v2 = admit_descriptor(descriptor)
    if v2:
        admit_owner(descriptor, owner)
    dates = admit_grid(grid, owner if v2 else None)
    require(type(rows) is list and len(rows) == 253, 'CLOSE_COUNT_NO_FILL')
    require([r['reference_date'] for r in rows] == dates, 'MISSING_DUPLICATE_OR_REORDERED_DATE_NO_FILL')
    prices = []
    ordinals = []
    source_versions = []
    for row in rows:
        require(row['record_id'] == descriptor['record_id'] and row['profile_id'] == descriptor['profile_id'], 'ROW_IDENTITY')
        require(row['prior_close_domain'] == 'VALID_POSITIVE_FINITE_PER_CONSUMED_FIELD_DELIVERY', 'UNQUALIFIED_CLOSE_DOMAIN')
        token = row['raw_close_token']
        require(type(token) is str and len(token) <= 256 and re.fullmatch(r'\+?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?', token), 'INVALID_DECIMAL_TOKEN')
        value = fraction(token)
        require(value > 0, 'NONPOSITIVE_CLOSE')
        require(row['close_token_sha256'] == sha(token.encode()), 'CLOSE_TOKEN_HASH')
        prices.append(value)
        source = row['source']
        for key in ('manifest_sha256', 'raw_line_sha256', 'raw_value_sha256'):
            hash_value(source[key])
        pin = source['member_previous_pin']
        hash_value(pin['sha256'])
        require(type(pin['bytes']) is int and pin['bytes'] > 0, 'SOURCE_MEMBER_SIZE')
        require(type(source['member']) is str and bool(source['member']), 'SOURCE_MEMBER')
        require(type(source['row_ordinal']) is int and source['row_ordinal'] >= 0, 'SOURCE_ROW_ORDINAL')
        ordinals.append(source['row_ordinal'])
        source_versions.append(canonical({k: source[k] for k in ('manifest_sha256', 'member', 'member_previous_pin')}))
        pointer = source['source_reference']
        require(type(pointer) is dict and bool(pointer), 'SOURCE_REFERENCE')
        # Distinct normalized-member and provider-array ordinal namespaces.
        require(type(pointer['source_row_ordinal']) is int and pointer['source_row_ordinal'] >= 0, 'PROVIDER_ROW_ORDINAL')
        hash_value(pointer['source_body_sha256'])
        clock = row['raw_clock']
        require(clock['observed_historical_K'] is None and type(clock['label']) is str and bool(clock['label']), 'RAW_CLOCK_EVIDENCE')
        if clock['estimated_K'] is not None:
            timestamp(clock['estimated_K'])
        for field in K_FIELDS:
            require(row[field] is None and row[field + '_status'] == 'UNBOUND', 'INFORMATION_K_MUST_STAY_UNBOUND')
    require(ordinals == sorted(set(ordinals)), 'SOURCE_ROW_ORDER')
    require(len(set(source_versions)) == 1, 'MIXED_SOURCE_REVISION')
    require(type(invalidations) in (list, tuple), 'INVALIDATION_SCHEMA')
    for item in invalidations:
        require(set(item) == {'reference_date', 'reason', 'evidence_ref'}, 'INVALIDATION_SCHEMA')
        require(item['reference_date'] is None or item['reference_date'] in dates, 'INVALIDATION_DATE')
        require(type(item['reason']) is str and bool(item['reason']) and type(item['evidence_ref']) is dict, 'INVALIDATION_EVIDENCE')
        hash_value(item['evidence_ref']['sha256'])
    factors = []
    for i in range(1, len(rows)):
        left, right = rows[i-1], rows[i]
        excluded = [x for x in invalidations if x['reference_date'] in (None, dates[i-1], dates[i])]
        clocks = [left['raw_clock']['estimated_K'], right['raw_clock']['estimated_K']]
        raw_k = max(clocks, key=timestamp) if all(x is not None for x in clocks) else None
        factors.append({'ordinal': i-1, 'left_close_ordinal': i-1, 'right_close_ordinal': i,
                        'left': left, 'right': right,
                        'status': 'INVALIDATED' if excluded else STATUS,
                        'gross_factor': None if excluded else rational(prices[i] / prices[i-1]),
                        'invalidations': excluded,
                        'raw_clock': {'estimated_K': raw_k, 'observed_historical_K': None,
                                      'label': 'MAX_ENDPOINT_RAW_ESTIMATE_ONLY' if raw_k else 'UNBOUND_ENDPOINT_ESTIMATE_MISSING'},
                        **{k: None for k in K_FIELDS}, **{k + '_status': 'UNBOUND' for k in K_FIELDS}})
    result = {'schema': 'polar.original-conditional-reference-output/' + ('2' if v2 else '1'), 'status': STATUS,
              'record_id': descriptor['record_id'], 'profile_id': descriptor['profile_id'],
              'model': descriptor['model'].copy(), 'closes': rows, 'adjacent_gross_factors': factors,
              'counts': {'closes': 253, 'adjacent_gross_factors': 252,
                         'invalidated_factors': sum(f['status'] == 'INVALIDATED' for f in factors)},
              'source_verification': 'BOUND_OPERAND_HASH_AND_POINTER_SHAPE_ONLY_ORIGINAL_SOURCE_NOT_REREAD',
              'contrary_evidence': 'SUPPLIED_INVALIDATIONS_APPLIED_NO_INDEPENDENT_EVENT_SEARCH',
              'decision_admissibility': 'NOT_ESTABLISHED_INFORMATION_K_UNBOUND',
              'economic_N': None, 'financial': 'NOT_RUN',
              **{k: None for k in K_FIELDS}, **{k + '_status': 'UNBOUND' for k in K_FIELDS}}
    if v2:
        result['model_semantics'] = descriptor['model_semantics'].copy()
        result['input_refs'] = {'source_use_owner': descriptor['source_use_owner'].copy()}
    # Detach from caller-owned objects; reject non-JSON values and binary floats.
    return decode(canonical(result))


def construct(descriptor_ref, output_root, invalidations_ref=None):
    """Read declared inputs (including the v2 owner), then publish immutably."""
    raw = read_ref(descriptor_ref)
    require(len(raw) <= LIMIT, 'DESCRIPTOR_LIMIT')
    descriptor = decode(raw)
    v2 = admit_descriptor(descriptor)
    owner = None
    if v2:
        owner_raw = read_ref(descriptor['source_use_owner'])
        require(len(owner_raw) <= LIMIT, 'OWNER_LIMIT')
        owner = decode(owner_raw)
        admit_owner(descriptor, owner)
    grid_raw = read_ref(descriptor['date_grid'])
    require(len(grid_raw) <= LIMIT, 'INPUT_LIMIT')
    admit_grid(decode(grid_raw), owner)
    operand_raw = read_ref(descriptor['close_operands'])
    require(len(operand_raw) <= LIMIT, 'INPUT_LIMIT')
    rows = [decode(line) for line in operand_raw.splitlines()]
    invalidations = decode(read_ref(invalidations_ref)) if invalidations_ref is not None else []
    report = build(descriptor, rows, decode(grid_raw), invalidations, owner=owner)
    report['input_refs'] = {'descriptor': descriptor_ref, 'close_operands': descriptor['close_operands'],
                            'date_grid': descriptor['date_grid'], 'invalidations': invalidations_ref}
    if v2:
        report['input_refs']['source_use_owner'] = descriptor['source_use_owner']
    code = ('conditional_reference.py', 'gym_contract.py', 'history_bundle.py', 'history_store.py')
    report['builder_code_sha256'] = {f: sha(Path(__file__).with_name(f).read_bytes()) for f in code}
    body = canonical(report)
    require(len(body) <= LIMIT, 'OUTPUT_LIMIT')
    identity = 'conditionalref-' + sha(body)
    root = Path(output_root)
    require(root.is_absolute(), 'ABSOLUTE_OUTPUT_ROOT_REQUIRED')
    require(not any((p / '.git').exists() for p in (root, *root.parents)), 'OUTPUT_INSIDE_REPOSITORY')
    root = safe_root(root)
    require(root.stat().st_mode & 0o077 == 0, 'OUTPUT_ROOT_NOT_PRIVATE')
    store = HistoryStore(root, 64 * 1024**2)
    manifest = canonical({'schema': 'polar.original-conditional-reference-manifest/1', 'id': identity,
                          'files': {'report.json': {'sha256': sha(body), 'bytes': len(body)}}})
    with store.locked():
        store._publish('conditional-references', identity, {'report.json': body, 'manifest.json': manifest}, file_limit=LIMIT)
    # Read back the exact immutable published bytes, not an in-memory-only result.
    prefix = 'conditional-references/' + identity
    require(read_file(root, prefix + '/report.json', LIMIT) == body and
            read_file(root, prefix + '/manifest.json', LIMIT) == manifest, 'PUBLISHED_READBACK_MISMATCH')
    return {'id': identity, 'status': STATUS, 'counts': report['counts'],
            'report_sha256': sha(body), 'manifest_sha256': sha(manifest),
            'relative_path': prefix, 'decision_admissibility': report['decision_admissibility']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--descriptor', type=Path, required=True)
    parser.add_argument('--descriptor-sha256', required=True)
    parser.add_argument('--output-root', type=Path, required=True, help='Existing private directory outside Git')
    parser.add_argument('--invalidations', type=Path)
    parser.add_argument('--invalidations-sha256')
    args = parser.parse_args(argv)
    try:
        hash_value(args.descriptor_sha256)
        require(bool(args.invalidations) == bool(args.invalidations_sha256), 'INVALIDATION_REFERENCE_PAIR')
        invalidation_ref = None
        if args.invalidations:
            hash_value(args.invalidations_sha256)
            invalidation_ref = {'path': str(args.invalidations.absolute()), 'sha256': args.invalidations_sha256}
        result = construct({'path': str(args.descriptor.absolute()), 'sha256': args.descriptor_sha256}, args.output_root, invalidation_ref)
        print(json.dumps(result, sort_keys=True, allow_nan=False))
    except (ReferenceError, GymError, HistoryError, InvalidOperation, OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        # Stable codes only; no operand values, source bodies or private paths.
        code = str(exc) if isinstance(exc, (ReferenceError, GymError)) else 'INPUT_OR_OUTPUT_INVALID'
        print(json.dumps({'status': 'ERROR', 'code': code}), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

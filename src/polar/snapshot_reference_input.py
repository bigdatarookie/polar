"""Offline single-symbol capture bridge and lossless native-input composition.

Source qualification stays a pinned declaration, never a new grant. Original
definitions and captures remain independently addressable in source relations.
No importer job, availability timestamp, action cashflow or native run is made.
"""
import json
import re
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from .ci_research import require
from .history_bundle import canonical, sha
from .history_store import HistoryStore
from .research_reference import decode, pinned_bytes, load_reference, microprice, MAX_BYTES
from .reference_input import project_schedule, BASIS
from .selected_reference_input import RIGHTS

SCHEMA = 'polar.reference-input-conversion-config/8'
PROFILE = 'CAPTURED-SINGLE-SYMBOL-REFERENCE-COMPOSITION-V1'
CONVERTER = 'polar.snapshot-reference-input/1'
POINTER = 'CAPTURED_SINGLE_SYMBOL_ALL_ADJUSTED_SOURCE'


def validate_pointer(value, members, relations):
    p = value['source_ref']
    require(type(p) is dict and set(p) == {'kind', 'capture_sha256', 'source_body_sha256',
            'source_pointer', 'source_row_index', 'selected_member_sha256', 'selected_line_1based',
            'selected_line_sha256', 'source_symbol'} and p['kind'] == POINTER,
            'REFERENCE_SNAPSHOT_POINTER')
    require(all(type(p[k]) is str and re.fullmatch('[a-f0-9]{64}', p[k]) for k in
            ('capture_sha256', 'source_body_sha256', 'selected_member_sha256', 'selected_line_sha256')),
            'REFERENCE_SNAPSHOT_HASH')
    relation = relations.get('single_symbol_captures', {}).get(p['capture_sha256'])
    require(type(relation) is dict and relation['receipt']['sha256'] == p['capture_sha256'] and
            relation['raw']['sha256'] == p['source_body_sha256'] in members and
            relation['selected']['sha256'] == p['selected_member_sha256'] in members and
            relation['symbol'] == p['source_symbol'] == value['symbol'] and
            relation['request']['adjustment'] == 'all' and relation['request']['timeframe'] == '1Day' and
            relation['quote_basis'] == BASIS, 'REFERENCE_SNAPSHOT_BINDING')
    i = p['source_row_index']
    require(type(i) is int and i >= 0 and type(p['selected_line_1based']) is int and
            p['selected_line_1based'] == i + 1 and p['source_pointer'] == f'/bars/{i}/c',
            'REFERENCE_SNAPSHOT_ORDINAL')


def _raw(raw):
    def pairs(items):
        out = {}
        for k, v in items:
            require(k not in out, 'REFERENCE_SNAPSHOT_DUPLICATE_FIELD')
            out[k] = v
        return out
    return json.loads(raw, parse_int=str, parse_float=str, object_pairs_hook=pairs,
                      parse_constant=lambda _: require(False, 'REFERENCE_SNAPSHOT_NONFINITE'))


def prepare_snapshot(config, root, limit):
    require(type(config) is dict and set(config) == {'schema', 'profile_id', 'namespace',
            'inputs', 'captures', 'qualification', 'consumer_question', 'schedule', 'date_range'} and
            config['schema'] == SCHEMA and config['profile_id'] == PROFILE and
            config['namespace'] in ('INVENTED', 'RETAINED'), 'REFERENCE_SNAPSHOT_CONFIG')
    require(type(config['inputs']) is list and len(config['inputs']) <= 16 and
            type(config['captures']) is list and 1 <= len(config['captures']) <= 16,
            'REFERENCE_SNAPSHOT_COMPONENTS')
    rights = 'INVENTED_PUBLIC_TEST' if config['namespace'] == 'INVENTED' else RIGHTS
    # These are source-use/definition evidence, not synthetic admission decisions.
    qualification = decode(pinned_bytes(config['qualification']))
    require(type(qualification) is dict and type(decode(pinned_bytes(config['consumer_question']))) is dict,
            'REFERENCE_SNAPSHOT_QUALIFICATION')
    basis = qualification.get('compatibility', {}).get('per_source_basis', {})
    require(basis.get('adjustment') == 'all' and basis.get('selected_field') == 'c' and
            basis.get('timeframe') == '1Day' and basis.get('feed') == 'sip' and
            basis.get('currency') == 'USD', 'REFERENCE_SNAPSHOT_QUALIFIED_BASIS')
    require(qualification.get('status') ==
            'COMPATIBLE_FOR_FROZEN_COHORT_VENDOR_REFERENCE_SEMANTICS_WITH_LIMITS',
            'REFERENCE_SNAPSHOT_QUALIFIED_STATUS')
    qualified = qualification.get('source_pins')
    require(type(qualified) is dict and qualified, 'REFERENCE_SNAPSHOT_QUALIFIED_SOURCES')
    qualified_hashes = set()
    for pin in qualified.values():
        require(type(pin) is dict and set(pin) == {'path', 'sha256'}, 'REFERENCE_SNAPSHOT_QUALIFIED_PIN')
        path = Path(pin['path'])
        if not path.is_absolute():
            path = (Path(config['qualification']['path']).parent / path).resolve()
        pinned_bytes({'path': str(path), 'sha256': pin['sha256']})
        qualified_hashes.add(pin['sha256'])
    require(all(p['sha256'] in qualified_hashes for p in config['inputs']) and
            all(c[k]['sha256'] in qualified_hashes for c in config['captures'] for k in
                ('receipt', 'raw', 'selected', 'source_definition')), 'REFERENCE_SNAPSHOT_QUALIFIED_BINDING')
    schedule = project_schedule(decode(pinned_bytes(config['schedule'])), config['date_range'])
    days = [r['date'] for r in schedule['rows']]
    quotes, members, jobs, parents, captures = {}, {}, {}, {}, {}
    records, coverage, components, symbols = [], [], [], []

    def merge(target, source):
        for k, v in source.items():
            require(k not in target or target[k] == v, 'REFERENCE_SNAPSHOT_RELATION_COLLISION')
            target[k] = v

    for pin in config['inputs']:
        manifest = decode(pinned_bytes(pin))
        require(manifest.get('schema') == 'polar.synthetic-reference-source-input/2' and
                manifest.get('quote_basis') == BASIS and manifest.get('rights') == rights,
                'REFERENCE_SNAPSHOT_PARENT_BASIS')
        invented = manifest.get('provenance', {}).get('kind') == 'DETERMINISTIC_INVENTED_FIXTURE'
        require(invented == (config['namespace'] == 'INVENTED'), 'REFERENCE_SNAPSHOT_NAMESPACE')
        market = load_reference(pin)
        require(set(days) <= set(market['dates']) and not set(symbols) & set(market['symbols']),
                'REFERENCE_SNAPSHOT_PARENT_GRID')
        parent_rows = {r['date']: r for r in market['schedule']}
        require(all(all(r[k] == parent_rows[r['date']][k] for k in
                ('reference_open_utc', 'reference_close_utc')) for r in schedule['rows']),
                'REFERENCE_SNAPSHOT_PARENT_CLOCK')
        symbols.extend(market['symbols'])
        relations = market['source_relations']
        merge(jobs, relations['jobs']); merge(parents, relations['parent_relations'])
        merge(captures, relations.get('captures', {}))
        require(not relations.get('single_symbol_captures'), 'REFERENCE_SNAPSHOT_NESTED_INPUT')
        merge(members, {p['sha256']: p for p in manifest['source_members']})
        records.extend(relations['records']); coverage.extend(relations['source_coverage_records'])
        for line in pinned_bytes(manifest['quotes']).splitlines(keepends=True):
            value = decode(line)
            if value['date'] in days:
                quotes[value['date'], value['symbol']] = line
        components.append({'input_ref': pin, 'symbols': market['symbols']})

    single = {}
    for capture in config['captures']:
        require(type(capture) is dict and set(capture) == {'symbol', 'plan', 'receipt', 'raw',
                'selected', 'source_definition'}, 'REFERENCE_SNAPSHOT_CAPTURE')
        symbol = capture['symbol']
        require(type(symbol) is str and re.fullmatch('[A-Z][A-Z0-9.]{0,31}', symbol) and
                symbol not in symbols, 'REFERENCE_SNAPSHOT_SYMBOL')
        plan = decode(pinned_bytes(capture['plan']))
        receipt = decode(pinned_bytes(capture['receipt']))
        definition = decode(pinned_bytes(capture['source_definition']))
        require(type(definition) is dict, 'REFERENCE_SNAPSHOT_DEFINITION')
        require((plan.get('mode') == 'INVENTED') == (config['namespace'] == 'INVENTED'),
                'REFERENCE_SNAPSHOT_NAMESPACE')
        url = urlparse(plan['request_url_without_credentials'])
        query = parse_qs(url.query, keep_blank_values=True)
        require(plan['method'] == 'GET' and url.scheme == 'https' and
                url.netloc == 'data.alpaca.markets' and url.path == f'/v2/stocks/{symbol}/bars' and
                not url.fragment and all(len(v) == 1 for v in query.values()) and
                set(query) <= {'timeframe', 'start', 'end', 'limit', 'adjustment', 'asof',
                               'feed', 'currency', 'sort'} and
                all(query.get(k) == [v] for k, v in {'adjustment': 'all', 'feed': 'sip',
                    'currency': 'USD', 'timeframe': '1Day', 'sort': 'asc'}.items()),
                'REFERENCE_SNAPSHOT_REQUEST')
        require(receipt.get('http_status') == 200 and receipt.get('body_complete_under_cap') is True and
                receipt.get('next_page_token_present') is False and receipt.get('transport_error_class') is None and
                receipt.get('plan_sha256') == capture['plan']['sha256'] and
                receipt.get('body_sha256') == capture['raw']['sha256'], 'REFERENCE_SNAPSHOT_RECEIPT')
        raw = _raw(pinned_bytes(capture['raw']))
        require(type(raw) is dict and raw.get('symbol') == symbol and type(raw.get('bars')) is list and
                raw.get('next_page_token') is None, 'REFERENCE_SNAPSHOT_RAW')
        lines = pinned_bytes(capture['selected']).splitlines(keepends=True)
        require(len(lines) == len(raw['bars']), 'REFERENCE_SNAPSHOT_SELECTED_COUNT')
        relation = {**capture, 'request': {k: v[0] for k, v in query.items()},
                    'quote_basis': BASIS, 'qualification': config['qualification'],
                    'historical_availability': 'UNKNOWN', 'investor_total_return': 'NOT_ESTABLISHED'}
        csha = capture['receipt']['sha256']
        require(csha not in single, 'REFERENCE_SNAPSHOT_CAPTURE_DUPLICATE')
        single[csha] = relation
        merge(members, {capture[k]['sha256']: capture[k] for k in ('raw', 'selected')})
        seen = set()
        for i, (bar, line) in enumerate(zip(raw['bars'], lines)):
            value = decode(line)
            require(type(value) is dict and set(value) == {'symbol', 'aggregation_label',
                    'adjusted_reference_close_token'} and line.endswith(b'\n') and
                    value['symbol'] == symbol and type(bar.get('t')) is str and
                    value['aggregation_label'] == bar['t'][:10] and
                    type(bar.get('c')) is str and value['adjusted_reference_close_token'] == bar['c'],
                    'REFERENCE_SNAPSHOT_EXACT_TOKEN')
            day = value['aggregation_label']
            require(day not in seen, 'REFERENCE_SNAPSHOT_DUPLICATE_DATE'); seen.add(day)
            price = microprice(bar['c'])
            if day not in days:
                continue
            projected = {'symbol': symbol, 'date': day,
                'reference_quote': f'{price//1000000}.{price%1000000:06d}',
                'source_adjusted_close_token': bar['c'], 'source_ref': {'kind': POINTER,
                    'capture_sha256': csha, 'source_body_sha256': capture['raw']['sha256'],
                    'source_pointer': f'/bars/{i}/c', 'source_row_index': i,
                    'selected_member_sha256': capture['selected']['sha256'],
                    'selected_line_1based': i + 1, 'selected_line_sha256': sha(line), 'source_symbol': symbol},
                'observed_published_at': None, 'observed_historical_available_at': None}
            quotes[day, symbol] = canonical(projected) + b'\n'
        symbols.append(symbol)
        records.append({'literal_alias': symbol, 'selected_for_purpose': True, 'capture_receipt': capture['receipt']})
    symbols.sort()
    require(set(quotes) == {(d, s) for d in days for s in symbols}, 'REFERENCE_SNAPSHOT_GRID')
    raw_quotes = b''.join(quotes[d, s] for d in days for s in symbols)
    require(len(raw_quotes) <= MAX_BYTES, 'REFERENCE_SNAPSHOT_BYTES')
    relations = {'schema': 'polar.reference-source-relations/1', 'records': records,
        'jobs': jobs, 'parent_relations': parents, 'source_coverage_records': coverage,
        'captures': captures, 'single_symbol_captures': single, 'source_components': components,
        'source_qualification': config['qualification'], 'consumer_question': config['consumer_question']}
    schedule_raw, relations_raw = canonical(schedule), canonical(relations)
    semantic = {'converter': CONVERTER, 'config': config, 'quotes_sha256': sha(raw_quotes),
                'schedule_sha256': sha(schedule_raw), 'relations_sha256': sha(relations_raw)}
    revision = 'reference-input-' + sha(canonical(semantic))
    destination = Path(root) / 'reference-inputs' / revision
    output = lambda name, raw: {'path': str(destination / name), 'sha256': sha(raw), 'bytes': len(raw)}
    provenance = {'converter': CONVERTER, 'profile': PROFILE, 'parent_schedule': config['schedule'],
                  'semantic': semantic, 'source_qualification': config['qualification'],
                  'historical_availability': 'UNKNOWN', 'investor_total_return': 'NOT_ESTABLISHED'}
    manifest = {'schema': 'polar.synthetic-reference-source-input/2', 'quote_basis': BASIS,
        'unit_type': 'SYNTHETIC_REFERENCE_UNIT_NOT_RAW_SHARE',
        'double_action_policy': 'NO_ADDITIONAL_SPLIT_DIVIDEND_CREDIT_IN_REFERENCE_UNIT_MODEL',
        'symbols': symbols, 'dates': config['date_range'], 'rows': len(quotes), 'rights': rights,
        'schedule': output('schedule.json', schedule_raw), 'quotes': output('quotes.ndjson', raw_quotes),
        'source_relations': output('source-relations.json', relations_raw), 'source_members': list(members.values()),
        'parent_dataset_revision': ('INVENTED-' if config['namespace'] == 'INVENTED' else '') + revision,
        'provenance': provenance}
    if config['namespace'] == 'INVENTED':
        manifest['conversion_metadata'] = provenance
        manifest['provenance'] = {'kind': 'DETERMINISTIC_INVENTED_FIXTURE',
                                  'producer': 'polar-public-tests', 'source_payloads': 'NONE'}
    files = {'manifest.json': canonical(manifest), 'quotes.ndjson': raw_quotes,
             'schedule.json': schedule_raw, 'source-relations.json': relations_raw,
             'quality.json': canonical({'status': 'LOSSLESS_SOURCE_ONLY', 'financial_operation': 'NOT_RUN',
                                        'clocks': 'UNKNOWN_PRESERVED', 'definitions': 'PINNED_NOT_REWRITTEN'})}
    # Validate pointer bindings before publication, so a failed adapter leaves no input behind.
    all_members = set(members)
    from .reference_input import validate_source
    for line in raw_quotes.splitlines():
        validate_source(decode(line), all_members, relations)
    store = HistoryStore(root, limit)
    with store.locked():
        store._publish('reference-inputs', revision, files, file_limit=MAX_BYTES)
    pin = output('manifest.json', files['manifest.json'])
    load_reference(pin)
    return {'schema': 'polar.reference-input-preparation/1', 'status': 'PREPARED_SOURCE_ONLY',
            'revision': revision, 'input_ref': pin, 'strategy_execution': 'NOT_RUN'}

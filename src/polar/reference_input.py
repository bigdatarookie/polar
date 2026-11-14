"""Offline, lossless all-adjusted source projection; no features, model or native call."""
from copy import deepcopy
from pathlib import Path
import hashlib
import re

from .ci_research import require
from .history_bundle import canonical
from .history_store import HistoryStore
from .research_reference import decode, pinned_bytes, microprice, load_reference, reference_schedule, MAX_BYTES

BASIS = 'VENDOR_ALL_ADJUSTED_REFERENCE_CLOSE'
VERSION = 'polar.reference-input-converter/1'
C = 'V033-C-BROAD-REFERENCE-INPUT-V1'
INVENTED = 'INVENTED-ALL-ADJUSTED-REFERENCE-INPUT-V1'
C_PINS = {'binding': 'ea17973d98b2501a327e58aefc3e09b5300cf9eb61704fd06096efae630976db',
          'definition_packet': '36564b0701a5d3f984f555c870df73f673eedae854a54fb7f2b87d57a041130c',
          'schedule': '67fcf8fd379eb8d2afd447eb5f2ec7085e44bcee41ee9d3958050c5978219098'}
SOURCE_FIELDS = {'raw_file', 'source_body_sha256', 'source_array', 'source_row_ordinal',
                 'job_id', 'request_id', 'page'}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _pin(path, digest):
    return {'path': str(path), 'sha256': digest}


def _member(root, relative):
    p = Path(relative)
    require(type(relative) is str and not p.is_absolute() and p.parts and
            all(v not in ('', '.', '..') for v in p.parts), 'REFERENCE_SOURCE_MEMBER_PATH')
    return root / p


def validate_source(value, members, relations):
    """v2 reader validation, deliberately separate from v1 EODHD pointer semantics."""
    p = value['source_ref']
    if type(p) is dict and p.get('kind')=='CAPTURED_ALL_ADJUSTED_SOURCE':
        from .captured_reference_input import validate_pointer
        return validate_pointer(value,members,relations)
    require(type(p) is dict and set(p) == {'normalized_member_sha256', 'line_1based', 'line_sha256',
                       'original_source_reference', 'query_symbol', 'source_symbol', 'parent_relation_sha256'},
            'REFERENCE_SOURCE_POINTER')
    s = p['original_source_reference']
    require(p['normalized_member_sha256'] in members and
            all(type(p[k]) is str and re.fullmatch('[a-f0-9]{64}', p[k]) for k in
                ('normalized_member_sha256', 'line_sha256', 'parent_relation_sha256')) and
            type(p['line_1based']) is int and p['line_1based'] > 0, 'REFERENCE_SOURCE_POINTER')
    require(type(s) is dict and set(s) == SOURCE_FIELDS and
            type(s['source_body_sha256']) is str and re.fullmatch('[a-f0-9]{64}', s['source_body_sha256']) and
            type(s['source_row_ordinal']) is int and s['source_row_ordinal'] >= 0 and
            type(s['page']) is int and s['page'] in (0, 1) and
            (s['request_id'] is None or type(s['request_id']) is str), 'REFERENCE_ORIGINAL_SOURCE_POINTER')
    require(type(s['raw_file']) is str and not Path(s['raw_file']).is_absolute() and
            '..' not in Path(s['raw_file']).parts and
            s['source_array'] == 'bars/' + value['symbol'] and
            p['query_symbol'] == p['source_symbol'] == value['symbol'], 'REFERENCE_SOURCE_SYMBOL')
    job = relations['jobs'].get(s['job_id'])
    parent = relations['parent_relations'].get(p['parent_relation_sha256'])
    require(type(job) is dict and type(parent) is dict and sha(canonical(parent)) == p['parent_relation_sha256']
            and job['parent_relation_sha256'] == p['parent_relation_sha256'] and
            job['request']['symbols'] == value['symbol'] and
            parent['job_id'] == job['source_plan_job_id'] and
            parent['source_record_ids'] == job['source_record_ids'], 'REFERENCE_PARENT_RELATION')


def project_schedule(parent_schedule,date_range):
    """Lossless calendar clipping only: preserve original metadata/session clocks."""
    schedule=deepcopy(parent_schedule)
    schedule['rows']=[r for r in schedule['rows'] if date_range['start']<=r['date']<=date_range['end']]
    days=[r['date'] for r in schedule['rows']]
    require(days==sorted(set(days)) and len(days)==date_range['count'] and days and
            days[0]==date_range['start'] and days[-1]==date_range['end'],'REFERENCE_CONVERSION_SCHEDULE')
    for i,row in enumerate(schedule['rows']):
        nxt=days[i+1] if i+1<len(days) else None
        row['next_reference_date']=nxt
        row['month_end_in_reference_range']=nxt[:7]!=days[i][:7] if nxt else None
    reference_schedule(schedule)
    return schedule


def schedule_binding_matches(manifest,calendar_schedule):
    if calendar_schedule['sha256']==manifest['schedule']['sha256']:return True
    if manifest['schema']!='polar.synthetic-reference-source-input/2':return False
    provenance=manifest.get('conversion_metadata',manifest.get('provenance',{}))
    parent=provenance.get('parent_schedule')
    if not isinstance(parent,dict) or parent.get('sha256')!=calendar_schedule['sha256']:return False
    original=decode(pinned_bytes(calendar_schedule))
    expected=project_schedule(original,manifest['dates'])
    actual=decode(pinned_bytes(manifest['schedule']))
    return canonical(expected)==canonical(actual)


def prepare_input(config, root, limit):
    """Called only by the owning source consumer after applicable qualification."""
    if type(config) is dict and config.get('schema')=='polar.reference-input-conversion-config/6':
        from .reference_composition import prepare_source_view
        return prepare_source_view(config,root,limit)
    if type(config) is dict and config.get('schema')=='polar.reference-input-conversion-config/4':
        from .captured_reference_input import prepare_capture
        return prepare_capture(config,root,limit)
    if type(config) is dict and config.get('schema') in ('polar.reference-input-conversion-config/3','polar.reference-input-conversion-config/5'):
        from .reference_composition import prepare_composition
        return prepare_composition(config,root,limit)
    selected=type(config) is dict and config.get('schema')=='polar.reference-input-conversion-config/2'
    if selected:
        from .selected_reference_input import PROFILE,metadata
        require(set(config)=={'schema','profile_id','namespace','binding','purpose','schedule','date_range'} and
                config['profile_id']==PROFILE,'REFERENCE_CONVERSION_CONFIG')
        require(type(config['date_range']) is dict and set(config['date_range'])=={'start','end','count'},'REFERENCE_CONVERSION_RANGE')
        binding,symbols,records,ledger,selected_dates=metadata(config)
    else:
        require(type(config) is dict and set(config) == {'schema', 'profile_id', 'binding',
                'definition_packet', 'schedule', 'date_range'} and
                config['schema'] == 'polar.reference-input-conversion-config/1' and
                config['profile_id'] in (C, INVENTED), 'REFERENCE_CONVERSION_CONFIG')
        require(config['date_range'].keys() == {'start', 'end', 'count'}, 'REFERENCE_CONVERSION_RANGE')
        if config['profile_id'] == C:
            require(all(config[k]['sha256'] == v for k, v in C_PINS.items()) and
                    config['date_range'] == {'start': '2016-01-04', 'end': '2026-11-06', 'count': 2728},
                    'REFERENCE_FROZEN_C_PINS')
        binding = decode(pinned_bytes(config['binding']))
        if config['profile_id'] == INVENTED:
            require(binding.get('rights') == 'INVENTED_PUBLIC_TEST' and
                    binding.get('provenance', {}).get('kind') == 'DETERMINISTIC_INVENTED_FIXTURE',
                    'REFERENCE_INVENTED_POSITIVE_PROVENANCE_REQUIRED')
        packet = decode(pinned_bytes(config['definition_packet']))
        definition = decode(pinned_bytes(packet['contract']))
        ledger = decode(pinned_bytes(packet['eligibility_ledger']))
        require(binding['schema'] == 'polar.C-source-consumer-metadata-binding/1' and
                packet['schema'] == 'polar.prospective-definition-packet/1' and
                definition['clock_binding']['schedule'] == config['schedule'], 'REFERENCE_CONVERSION_METADATA')
        symbols = binding['portfolio_symbol_order']; records = binding['records']
        require(type(symbols) is list and symbols == sorted(set(symbols)) and 1 <= len(symbols) <= 256
                and all(type(s) is str and re.fullmatch('[A-Z][A-Z0-9.]{0,31}', s) for s in symbols),
                'REFERENCE_CONVERSION_SYMBOLS')
        require(len(records) == len({r['literal_alias'] for r in records}) <= 100 and
                symbols == sorted(r['literal_alias'] for r in records if r['eligible_for_C'] is True) ==
                ledger['eligible_aliases_fixed_order'], 'REFERENCE_FROZEN_ELIGIBILITY')
        if config['profile_id'] == C:
            require(len(records) == 100 and len(symbols) == 54, 'REFERENCE_FROZEN_C_GRID')
    schedule=project_schedule(decode(pinned_bytes(config['schedule'])),config['date_range'])
    days=[r['date'] for r in schedule['rows']]
    if selected:require(days==selected_dates,'REFERENCE_SELECTED_DATE_GRID')
    if config['profile_id'] == C:
        require(sum(r['early_close_reference'] is True for r in schedule['rows']) == 21,
                'REFERENCE_C_EARLY_CLOSES')
    collection = decode(pinned_bytes(binding['source_collection']))
    if config['profile_id'] == INVENTED or selected and config['namespace']=='INVENTED':
        require(collection.get('rights') == 'INVENTED_PUBLIC_TEST' and
                collection.get('provenance', {}).get('kind') == 'DETERMINISTIC_INVENTED_FIXTURE',
                'REFERENCE_INVENTED_POSITIVE_PROVENANCE_REQUIRED')
    require(collection['schema'] == 'polar.vendor-all-adjusted-source-collection/1' and
            collection['source_plan_id'] == binding['source_plan_id'], 'REFERENCE_COLLECTION_IDENTITY')
    source_root = Path(binding['source_collection']['path']).parent
    day_set = set(days)
    cache, members, quotes, parents, jobs = {}, {}, {}, {}, {}
    # All100 parent relations survive, including failed/excluded aliases. These
    # are metadata ledgers, never a reason to open excluded bar payloads.
    coverage = []
    extra = {'canonical_job_id', 'global_job_ordinal', 'this_batch', 'this_batch_reason',
             'raw_data_state', 'raw_coverage_ref'}
    by_job = {r['canonical_job_id']: r for r in records}
    require(len(by_job) == len(records), 'REFERENCE_DUPLICATE_PARENT_JOB')
    for packet_ref in collection['packets']:
        rel = packet_ref['manifest']; entry = collection['objects'][rel]
        require(entry['sha256'] == packet_ref['sha256'], 'REFERENCE_PACKET_BINDING')
        path = _member(source_root, rel)
        partition = decode(pinned_bytes(_pin(path, entry['sha256'])))
        require(partition['schema'] == 'polar.vendor-all-adjusted-source-content/1' and
                partition['source_plan_id'] == binding['source_plan_id'], 'REFERENCE_PARTITION_BINDING')
        coverage_entry = partition['objects']['parent-coverage-ledger.ndjson']
        parent_rows = pinned_bytes(_pin(path.parent/'parent-coverage-ledger.ndjson', coverage_entry['sha256']))
        for line in parent_rows.splitlines():
            item = decode(line); jid = item['canonical_job_id']
            require(jid in by_job, 'REFERENCE_UNDECLARED_PARENT')
            record = by_job[jid]; parent = {k: v for k, v in item.items() if k not in extra}
            require(parent['job_id'] == record['source_plan_job_id'] and
                    parent['request'] == record['request'] and parent['source_records'] == record['source_records'] and
                    parent['source_record_ids'] == record['source_record_ids'], 'REFERENCE_PARENT_BINDING')
            parent_hash = sha(canonical(parent)); parents[parent_hash] = parent
            job = {'source_plan_job_id': record['source_plan_job_id'], 'source_record_ids': record['source_record_ids'],
                   'request': record['request'], 'parent_relation_sha256': parent_hash}
            require(jid not in jobs or jobs[jid] == job, 'REFERENCE_PARENT_CONFLICT')
            jobs[jid] = job; coverage.append(item)
    require(set(jobs) == set(by_job), 'REFERENCE_MISSING_PARENT')
    output_bytes = 0
    for record in records:
        if record['selected_for_purpose' if selected else 'eligible_for_C'] is not True:
            continue  # Preserve every excluded metadata record; never read its bar payload for the projection.
        symbol = record['literal_alias']; row_offset = 0
        require(record['request']['symbols'] == symbol and record['request']['adjustment'] == 'all',
                'REFERENCE_REQUEST_ALIAS')
        for segment in record['segments']:
            partition_path = Path(segment['partition_manifest']); member_path = Path(segment['normalized_member'])
            part_rel = str(partition_path.relative_to(source_root)); member_rel = str(member_path.relative_to(source_root))
            require(collection['objects'][part_rel]['sha256'] == segment['partition_manifest_sha256'] and
                    collection['objects'][member_rel]['sha256'] == segment['normalized_member_sha256'],
                    'REFERENCE_COLLECTION_MEMBER_BINDING')
            partition = decode(pinned_bytes(_pin(partition_path, segment['partition_manifest_sha256'])))
            require(partition['schema'] == 'polar.vendor-all-adjusted-source-content/1' and
                    partition['source_plan_id'] == binding['source_plan_id'] and
                    member_path == partition_path.parent/'bars.ndjson' and
                    partition['objects']['bars.ndjson']['sha256'] == segment['normalized_member_sha256'],
                    'REFERENCE_PARTITION_BINDING')
            if cache.get('path') != str(member_path):
                raw = pinned_bytes(_pin(member_path, segment['normalized_member_sha256']))
                cache = {'path': str(member_path), 'lines': raw.splitlines(keepends=True), 'raw_pages': {}}
            members[segment['normalized_member_sha256']] = _pin(member_path, segment['normalized_member_sha256'])
            start = segment['member_first_line_1based']-1; count = segment['rows']
            require(type(start) is int and type(count) is int and start >= 0 and count > 0 and
                    start+count <= len(cache['lines']) and segment['first_job_row_0based'] == row_offset,
                    'REFERENCE_SEGMENT_BOUND')
            for index in range(start, start+count):
                line = cache['lines'][index]; value = decode(line)
                require(line.endswith(b'\n') and value['query_symbol'] == value['source_symbol'] == symbol and
                        value['reference_date'] in day_set and value['source_reference']['job_id'] == record['canonical_job_id']
                        and value['adjustment'] == 'all', 'REFERENCE_NORMALIZED_ROW_IDENTITY')
                token = value['source_fields_exact_tokens']['c']
                require(type(token) is str and value['vendor_adjusted_close'] == token,
                        'REFERENCE_ADJUSTED_TOKEN_MISMATCH')
                price = microprice(token); quoted = f'{price//1000000}.{price%1000000:06d}'
                parent = value['parent_relation']; parent_hash = sha(canonical(parent))
                require(parent_hash in parents and jobs[record['canonical_job_id']]['parent_relation_sha256'] == parent_hash,
                        'REFERENCE_PARENT_CONFLICT')
                original = value['source_reference']; raw_file = original['raw_file']
                require(raw_file in partition['objects'] and
                        partition['objects'][raw_file]['sha256'] == original['source_body_sha256'],
                        'REFERENCE_SOURCE_BODY_BINDING')
                if raw_file not in cache['raw_pages']:
                    from .import_raw_sip import page
                    from .import_contract import ImportError as SourceError
                    source_raw = pinned_bytes(_pin(_member(partition_path.parent, raw_file), original['source_body_sha256']))
                    try:
                        cache['raw_pages'][raw_file] = page(source_raw, limit=MAX_BYTES)
                    except SourceError:
                        require(False, 'REFERENCE_SOURCE_BODY_INVALID')
                source_rows = cache['raw_pages'][raw_file]['bars'].get(symbol, [])
                ordinal = original['source_row_ordinal']
                require(type(ordinal) is int and 0 <= ordinal < len(source_rows) and
                        source_rows[ordinal] == value['source_fields_exact_tokens'] and
                        source_rows[ordinal].get('t', '')[:10] == value['reference_date'],
                        'REFERENCE_SOURCE_ROW_BINDING')
                projected = {'symbol': symbol, 'date': value['reference_date'], 'reference_quote': quoted,
                             'source_adjusted_close_token': token,
                             'source_ref': {'normalized_member_sha256': segment['normalized_member_sha256'],
                                 'line_1based': index+1, 'line_sha256': sha(line), 'original_source_reference': original,
                                 'query_symbol': value['query_symbol'], 'source_symbol': value['source_symbol'],
                                 'parent_relation_sha256': parent_hash},
                             'observed_published_at': value['observed_published_at'],
                             'observed_historical_available_at': value['observed_historical_available_at']}
                validate_source(projected, set(members), {'jobs': jobs, 'parent_relations': parents})
                key = (projected['date'], symbol); require(key not in quotes, 'REFERENCE_DUPLICATE_QUOTE')
                encoded = canonical(projected)+b'\n'; output_bytes += len(encoded)
                require(output_bytes <= MAX_BYTES, 'REFERENCE_PROJECTED_BYTES_BOUND')
                quotes[key] = encoded
            row_offset += count
        require(row_offset == len(days), 'REFERENCE_ELIGIBLE_GRID_MISSING')
    require(set(quotes) == {(d, s) for d in days for s in symbols}, 'REFERENCE_ELIGIBLE_GRID_MISSING')
    quote_raw = b''.join(quotes[d, s] for d in days for s in symbols)
    relations = {'schema': 'polar.reference-source-relations/1', 'records': records,
                 'eligibility_ledger': ledger, 'jobs': jobs, 'parent_relations': parents,
                 'source_coverage_records': coverage,
                 'source_binding': config['binding'], 'definition_packet': config.get('definition_packet')}
    if selected:
        relations.pop('definition_packet')
        relations['source_purpose']=config['purpose']
    version='polar.reference-input-converter/2' if selected else VERSION
    semantic = {'converter': version, 'profile_id': config['profile_id'], 'config': config,
                'quotes_sha256': sha(quote_raw), 'schedule_sha256': sha(canonical(schedule)),
                'relations_sha256': sha(canonical(relations))}
    revision = 'reference-input-'+sha(canonical(semantic)); destination = Path(root)/'reference-inputs'/revision
    def output_pin(name, raw):
        return {'path': str(destination/name), 'sha256': sha(raw), 'bytes': len(raw)}
    manifest = {'schema': 'polar.synthetic-reference-source-input/2', 'quote_basis': BASIS,
                'unit_type': 'SYNTHETIC_REFERENCE_UNIT_NOT_RAW_SHARE',
                'double_action_policy': 'NO_ADDITIONAL_SPLIT_DIVIDEND_CREDIT_IN_REFERENCE_UNIT_MODEL',
                'symbols': symbols, 'dates': config['date_range'], 'rows': len(quotes),
                'schedule': output_pin('schedule.json', canonical(schedule)),
                'quotes': output_pin('quotes.ndjson', quote_raw),
                'source_relations': output_pin('source-relations.json', canonical(relations)),
                'source_members': list(members.values()), 'parent_dataset_revision': binding['source_collection']['sha256'],
                'rights': 'INVENTED_PUBLIC_TEST' if config['profile_id'] == INVENTED else binding['rights'],
                'provenance': {'converter': version, 'profile': config['profile_id'], 'source_collection': binding['source_collection'],
                               'parent_schedule': config['schedule'], 'semantic': semantic,
                               'economic_distinct_count': 'NOT_ESTABLISHED', 'model_execution': 'UNSUPPORTED_BY_THIS_CONVERTER'}}
    if selected and config['namespace']=='INVENTED':
        manifest['parent_dataset_revision']='INVENTED-'+binding['source_collection']['sha256']
        manifest['conversion_metadata']=manifest['provenance']
        manifest['provenance']={'kind':'DETERMINISTIC_INVENTED_FIXTURE','producer':'polar-public-tests','source_payloads':'NONE'}
    files = {'manifest.json': canonical(manifest), 'quotes.ndjson': quote_raw,
             'schedule.json': canonical(schedule), 'source-relations.json': canonical(relations),
             'quality.json': canonical({'rows': len(quotes), 'symbols': len(symbols), 'dates': len(days),
                 'all_alias_metadata_records': len(records), 'output_quote_bytes': len(quote_raw),
                 'observed_clocks': 'PRESERVED_NOT_INFERRED', 'scale': 'LOSSLESS_1_TO_6DP',
                 'scientific_fitness': 'NOT_ASSESSED', 'model_features_returns_labels_native_calls': 0})}
    store = HistoryStore(root, limit)
    with store.locked():
        store._publish('reference-inputs', revision, files, file_limit=MAX_BYTES)
    pin = output_pin('manifest.json', files['manifest.json'])
    # Structural verification only; current A/B service profiles do not admit C.
    market = load_reference(pin)
    return {'schema': 'polar.reference-input-preparation/1', 'status': 'PREPARED_SOURCE_ONLY',
            'revision': revision, 'input_ref': pin, 'symbols': len(market['symbols']), 'rows': len(quotes),
            'quote_bytes': len(quote_raw), 'scientific_fitness': 'NOT_ASSESSED', 'strategy_execution': 'NOT_RUN'}


def preflight_input(pin):
    market = load_reference(pin)
    return {'status': 'STRUCTURALLY_VALID_SOURCE_ONLY', 'symbols': len(market['symbols']),
            'dates': len(market['dates']), 'quote_basis': market['quote_basis'],
            'rows': len(market['dates'])*len(market['symbols']), 'strategy_execution': 'NOT_RUN'}

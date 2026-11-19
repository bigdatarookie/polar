"""Selected-span source materialization; no parent-price validation or admission.

The owning closed consumer must authorize the exact spec/current source scope
before this callable, and enforce that scope when reading its output. Metadata
and member bytes may be hashed; excluded rows never enter the JSON decoder.
Original raw source bodies and mixed native parent quotes are never opened.
"""
from pathlib import Path

from .ci_research import require
from .history_bundle import canonical, sha
from .history_store import HistoryStore
from .research_reference import decode, pinned_bytes, reference_schedule, microprice, MAX_BYTES
from .reference_input import project_schedule, validate_source
from .selected_reference_input import RIGHTS

SCHEMA = 'polar.selected-component-materialization/1'
CONVERTER = 'polar.selected-component-materializer/1'


def _merge(target, source):
    for key, value in source.items():
        require(key not in target or target[key] == value, 'SELECTED_COMPONENT_RELATION_CONFLICT')
        target[key] = value


def prepare_selected_components(spec, root, limit, *, source_binding):
    """Materialize only caller-authorized singleton leaves/normalized spans.

    source_binding is the caller's already checked new native binding, not an
    uploaded proof or an authorization decision made by this source helper.
    There is intentionally no standalone CLI route to this callable.
    """
    require(type(spec) is dict and set(spec) == {'schema', 'namespace', 'leaf_inputs',
            'normalized_inputs', 'schedule', 'date_range', 'purpose_ref', 'qualification_refs'} and
            spec['schema'] == SCHEMA and spec['namespace'] in ('INVENTED', 'RETAINED'),
            'SELECTED_COMPONENT_CONFIG')
    require(type(source_binding) is dict and source_binding, 'SELECTED_COMPONENT_CALLER_BINDING')
    require(type(spec['leaf_inputs']) is list and type(spec['normalized_inputs']) is list and
            1 <= len(spec['leaf_inputs']) + len(spec['normalized_inputs']) <= 16,
            'SELECTED_COMPONENT_INPUTS')
    require(type(decode(pinned_bytes(spec['purpose_ref']))) is dict, 'SELECTED_COMPONENT_PURPOSE')
    refs = spec['qualification_refs']
    require(type(refs) is list and 1 <= len(refs) <= 16, 'SELECTED_COMPONENT_QUALIFICATIONS')
    for ref in refs:
        require(type(decode(pinned_bytes(ref))) is dict, 'SELECTED_COMPONENT_QUALIFICATIONS')
    schedule = project_schedule(decode(pinned_bytes(spec['schedule'])), spec['date_range'])
    days = [r['date'] for r in schedule['rows']]; day_set = set(days)
    rights = 'INVENTED_PUBLIC_TEST' if spec['namespace'] == 'INVENTED' else RIGHTS
    metadata = []; symbols = []
    inputs = {}
    input_paths = {}
    member_paths = {}
    member_spans = {}
    # All component metadata is checked before any price-member access.
    for kind, items in (('leaf', spec['leaf_inputs']), ('normalized', spec['normalized_inputs'])):
        for item in items:
            fields = {'input_ref', 'symbol'} | ({'binding_ref'} if kind == 'normalized' else set())
            require(type(item) is dict and set(item) == fields, 'SELECTED_COMPONENT_ITEM')
            symbol = item['symbol']
            import re
            require(type(symbol) is str and re.fullmatch('[A-Z][A-Z0-9.]{0,31}', symbol) and
                    symbol not in symbols,
                    'SELECTED_COMPONENT_DUPLICATE')
            input_ref = item['input_ref']
            parent_hash = input_ref['sha256']
            _merge(input_paths, {input_ref['path']: parent_hash})
            if parent_hash in inputs:
                require(kind == 'normalized' and
                        inputs[parent_hash] == (kind, input_ref, item['binding_ref']),
                        'SELECTED_COMPONENT_PARENT_AUTHORITY')
            manifest = decode(pinned_bytes(input_ref))
            require(manifest.get('schema') == 'polar.synthetic-reference-source-input/2' and
                    manifest.get('quote_basis') == 'VENDOR_ALL_ADJUSTED_REFERENCE_CLOSE' and
                    manifest.get('unit_type') == 'SYNTHETIC_REFERENCE_UNIT_NOT_RAW_SHARE' and
                    manifest.get('double_action_policy') == 'NO_ADDITIONAL_SPLIT_DIVIDEND_CREDIT_IN_REFERENCE_UNIT_MODEL' and
                    manifest.get('rights') == rights, 'SELECTED_COMPONENT_BASIS_RIGHTS')
            invented = manifest.get('provenance') == {'kind': 'DETERMINISTIC_INVENTED_FIXTURE',
                'producer': 'polar-public-tests', 'source_payloads': 'NONE'}
            require(invented == (spec['namespace'] == 'INVENTED') and
                    str(manifest.get('parent_dataset_revision', '')).startswith('INVENTED-') == invented,
                    'SELECTED_COMPONENT_NAMESPACE')
            require(manifest['symbols'] == [symbol] if kind == 'leaf' else symbol in manifest['symbols'],
                    'SELECTED_COMPONENT_LEAF_SCOPE')
            original_schedule = decode(pinned_bytes(manifest['schedule']))
            _, original_days = reference_schedule(original_schedule)
            require(manifest['dates'] == {'start': original_days[0], 'end': original_days[-1],
                    'count': len(original_days)} and type(manifest['rows']) is int and
                    manifest['rows'] == len(original_days) * len(manifest['symbols']),
                    'SELECTED_COMPONENT_PARENT_GRID')
            clipped = project_schedule(original_schedule, spec['date_range'])
            require(canonical(clipped['rows']) == canonical(schedule['rows']), 'SELECTED_COMPONENT_CALENDAR')
            relations = decode(pinned_bytes(manifest['source_relations']))
            require(relations.get('schema') == 'polar.reference-source-relations/1', 'SELECTED_COMPONENT_RELATIONS')
            records = [r for r in relations['records'] if r.get('literal_alias') == symbol]
            require(len(records) == 1 and records[0].get('selected_for_purpose') is True,
                    'SELECTED_COMPONENT_RECORD')
            record = records[0]
            component = {'kind': kind, 'item': item, 'manifest': manifest, 'relations': relations,
                         'record': record, 'original_days': original_days}
            if kind == 'normalized':
                binding = decode(pinned_bytes(item['binding_ref']))
                bound_records = [r for r in binding.get('records', []) if r.get('literal_alias') == symbol]
                require(binding.get('schema') == 'polar.selected-source-consumer-metadata-binding/1' and
                        binding.get('rights') == rights and bound_records == [record] and
                        record['request']['symbols'] == symbol and record['request']['adjustment'] == 'all',
                        'SELECTED_COMPONENT_BINDING')
                collection = decode(pinned_bytes(binding['source_collection']))
                require(collection.get('schema') == 'polar.vendor-all-adjusted-source-collection/1' and
                        collection['source_plan_id'] == binding['source_plan_id'], 'SELECTED_COMPONENT_COLLECTION')
                source_root = Path(binding['source_collection']['path']).parent
                spans = []; offset = 0
                for segment in record['segments']:
                    pp, mp = Path(segment['partition_manifest']), Path(segment['normalized_member'])
                    require(pp.is_relative_to(source_root) and mp.is_relative_to(source_root) and
                            pp.parent == mp.parent and mp.name == 'bars.ndjson', 'SELECTED_COMPONENT_MEMBER_PATH')
                    for path, digest in ((pp, segment['partition_manifest_sha256']),
                                         (mp, segment['normalized_member_sha256'])):
                        require(collection['objects'][str(path.relative_to(source_root))]['sha256'] == digest,
                                'SELECTED_COMPONENT_MEMBER_GRAPH')
                    part = decode(pinned_bytes({'path': str(pp), 'sha256': segment['partition_manifest_sha256']}))
                    require(part.get('schema') == 'polar.vendor-all-adjusted-source-content/1' and
                            part['source_plan_id'] == binding['source_plan_id'] and
                            part['objects']['bars.ndjson']['sha256'] == segment['normalized_member_sha256'] and
                            segment['normalized_member_sha256'] in {p['sha256'] for p in manifest['source_members']},
                            'SELECTED_COMPONENT_PARTITION')
                    first, count = segment['member_first_line_1based'], segment['rows']
                    job_start = segment['first_job_row_0based']
                    require(type(first) is int and type(count) is int and type(job_start) is int and
                            first > 0 and count > 0 and job_start == offset and offset + count <= len(original_days),
                            'SELECTED_COMPONENT_SEGMENT')
                    start = first - 1
                    digest = segment['normalized_member_sha256']
                    _merge(member_paths, {str(mp): digest})
                    member_spans.setdefault(digest, []).append((start, start + count, str(mp)))
                    spans.append((segment, part, start, count, offset)); offset += count
                require(offset == len(original_days), 'SELECTED_COMPONENT_SOURCE_GRID')
                component['spans'] = spans
            inputs[parent_hash] = (kind, input_ref, item.get('binding_ref'))
            metadata.append(component); symbols.append(symbol)
    for spans in member_spans.values():
        # Line ordinals belong to the pinned member, not to a selector. A
        # second alias may share that member only over a disjoint interval.
        require(len({path for _, _, path in spans}) == 1, 'SELECTED_COMPONENT_MEMBER_PIN_CONFLICT')
        ordered = sorted(spans)
        require(all(left[1] <= right[0] for left, right in zip(ordered, ordered[1:])),
                'SELECTED_COMPONENT_OVERLAPPING_SPANS')
    symbols.sort()
    require(len(symbols) <= 64, 'SELECTED_COMPONENT_SYMBOL_BOUND')
    jobs = {}; parents = {}; captures = {}; single_captures = {}; members = {}; selected = {}; records = []
    # Resolve every selected relation graph before opening the first price member.
    for component in metadata:
        symbol = component['item']['symbol']; record = component['record']; relations = component['relations']
        records.append(record)
        if 'canonical_job_id' in record:
            jid = record['canonical_job_id']; job = relations['jobs'][jid]
            _merge(jobs, {jid: job}); h = job['parent_relation_sha256']
            parent = relations['parent_relations'][h]
            require(sha(canonical(parent)) == h and job['request']['symbols'] == symbol and
                    job['request']['adjustment'] == 'all' and parent['job_id'] == job['source_plan_job_id'] and
                    parent['source_record_ids'] == job['source_record_ids'], 'SELECTED_COMPONENT_PARENT_BINDING')
            _merge(parents, {h: parent})
        elif 'capture_return' in record:
            h = record['capture_return']['sha256']
            capture = relations['captures'][h]
            require(capture['capture_return'] == record['capture_return'] and
                    capture['request']['symbols'] == symbol and capture['request']['adjustment'] == 'all',
                    'SELECTED_COMPONENT_CAPTURE_BINDING')
            _merge(captures, {h: capture})
        elif 'capture_receipt' in record:
            h = record['capture_receipt']['sha256']
            capture = relations['single_symbol_captures'][h]
            require(capture['receipt'] == record['capture_receipt'] and capture['symbol'] == symbol and
                    capture['request']['adjustment'] == 'all', 'SELECTED_COMPONENT_CAPTURE_BINDING')
            _merge(single_captures, {h: capture})
        else:
            require(False, 'SELECTED_COMPONENT_RECORD_KIND')
    for component in metadata:
        symbol = component['item']['symbol']; record = component['record']
        if component['kind'] == 'leaf':
            manifest = component['manifest']
            lines = pinned_bytes(manifest['quotes']).splitlines(keepends=True)
            require(len(lines) == len(component['original_days']), 'SELECTED_COMPONENT_LEAF_GRID')
            for day, line in zip(component['original_days'], lines):
                if day not in day_set:
                    continue  # No decoder access to off-scope date rows.
                value = decode(line)
                require(value.get('symbol') == symbol and value.get('date') == day and line.endswith(b'\n'),
                        'SELECTED_COMPONENT_LEAF_ROW')
                selected[day, symbol] = line
            _merge(members, {p['sha256']: p for p in manifest['source_members']})
            continue
        for segment, part, start, count, offset in component['spans']:
            pin = {'path': segment['normalized_member'], 'sha256': segment['normalized_member_sha256']}
            lines = pinned_bytes(pin).splitlines(keepends=True)
            require(start + count <= len(lines), 'SELECTED_COMPONENT_SEGMENT')
            members[pin['sha256']] = pin
            for ordinal in range(count):
                day = component['original_days'][offset + ordinal]
                if day not in day_set:
                    continue  # The source schedule fixes ordinals without inspecting values.
                index = start + ordinal; line = lines[index]; value = decode(line)
                require(line.endswith(b'\n') and value['query_symbol'] == value['source_symbol'] == symbol and
                        value['reference_date'] == day and value['adjustment'] == 'all' and
                        value['source_reference']['job_id'] == record['canonical_job_id'], 'SELECTED_COMPONENT_ROW')
                token = value['source_fields_exact_tokens']['c']
                require(type(token) is str and value['vendor_adjusted_close'] == token, 'SELECTED_COMPONENT_TOKEN')
                price = microprice(token); parent_hash = sha(canonical(value['parent_relation']))
                require(parent_hash == jobs[record['canonical_job_id']]['parent_relation_sha256'],
                        'SELECTED_COMPONENT_PARENT')
                original = value['source_reference']
                require(part['objects'][original['raw_file']]['sha256'] == original['source_body_sha256'],
                        'SELECTED_COMPONENT_RAW_POINTER')
                projected = {'symbol': symbol, 'date': day,
                    'reference_quote': f'{price//1000000}.{price%1000000:06d}', 'source_adjusted_close_token': token,
                    'source_ref': {'normalized_member_sha256': pin['sha256'], 'line_1based': index + 1,
                        'line_sha256': sha(line), 'original_source_reference': original, 'query_symbol': symbol,
                        'source_symbol': symbol, 'parent_relation_sha256': parent_hash},
                    'observed_published_at': value['observed_published_at'],
                    'observed_historical_available_at': value['observed_historical_available_at']}
                require((day, symbol) not in selected, 'SELECTED_COMPONENT_DUPLICATE_ROW')
                selected[day, symbol] = canonical(projected) + b'\n'
    require(set(selected) == {(day, symbol) for day in days for symbol in symbols}, 'SELECTED_COMPONENT_GRID')
    relations = {'schema': 'polar.reference-source-relations/1', 'records': records, 'jobs': jobs,
        'parent_relations': parents, 'source_coverage_records': [], 'source_purpose': spec['purpose_ref'],
        'source_qualifications': refs, 'eligibility_ledger': {'selected_aliases_fixed_order': symbols},
        **({'captures': captures} if captures else {}),
        **({'single_symbol_captures': single_captures} if single_captures else {})}
    fields = {'symbol', 'date', 'reference_quote', 'source_adjusted_close_token', 'source_ref',
              'observed_published_at', 'observed_historical_available_at'}
    for (day, symbol), line in selected.items():
        value = decode(line)
        require(set(value) == fields and value['symbol'] == symbol and value['date'] == day and
                microprice(value['reference_quote']) == microprice(value['source_adjusted_close_token']),
                'SELECTED_COMPONENT_QUOTE')
        validate_source(value, set(members), relations)
    raw = b''.join(selected[day, symbol] for day in days for symbol in symbols)
    require(len(raw) <= MAX_BYTES, 'SELECTED_COMPONENT_BYTES')
    provenance = {'converter': CONVERTER, 'spec': spec, 'private_root': str(root),
        'source_native_binding': source_binding, 'parent_schedule': spec['schedule'],
        'integrity_scope': 'SELECTED_MEMBERS_HASHED_SELECTED_ROWS_VALIDATED_EXCLUDED_VALUES_UNDECODED',
        'raw_source_bodies': 'POINTER_HASH_BINDING_ONLY_NOT_REOPENED'}
    semantic = {'converter': CONVERTER, 'spec': spec, 'source_native_binding': source_binding,
                'quotes_sha256': sha(raw), 'schedule_sha256': sha(canonical(schedule)),
                'relations_sha256': sha(canonical(relations))}
    revision = 'reference-input-' + sha(canonical(semantic)); destination = Path(root)/'reference-inputs'/revision
    output = lambda name, data: {'path': str(destination/name), 'sha256': sha(data), 'bytes': len(data)}
    schedule_raw, relation_raw = canonical(schedule), canonical(relations)
    manifest = {'schema': 'polar.synthetic-reference-source-input/2',
        'quote_basis': 'VENDOR_ALL_ADJUSTED_REFERENCE_CLOSE', 'unit_type': 'SYNTHETIC_REFERENCE_UNIT_NOT_RAW_SHARE',
        'double_action_policy': 'NO_ADDITIONAL_SPLIT_DIVIDEND_CREDIT_IN_REFERENCE_UNIT_MODEL',
        'symbols': symbols, 'dates': spec['date_range'], 'rows': len(selected), 'rights': rights,
        'source_members': list(members.values()), 'schedule': output('schedule.json', schedule_raw),
        'quotes': output('quotes.ndjson', raw), 'source_relations': output('source-relations.json', relation_raw),
        'parent_dataset_revision': ('INVENTED-' if spec['namespace'] == 'INVENTED' else '') + revision,
        'provenance': provenance}
    if spec['namespace'] == 'INVENTED':
        manifest['conversion_metadata'] = provenance
        manifest['provenance'] = {'kind': 'DETERMINISTIC_INVENTED_FIXTURE',
                                 'producer': 'polar-public-tests', 'source_payloads': 'NONE'}
    files = {'manifest.json': canonical(manifest), 'quotes.ndjson': raw, 'schedule.json': schedule_raw,
        'source-relations.json': relation_raw, 'quality.json': canonical({'status': 'SELECTED_SOURCE_ONLY',
            'excluded_value_decodes': 0, 'mixed_parent_quote_reads': 0, 'raw_source_body_reads': 0,
            'financial_or_provider_calls': 0, 'integrity_scope': provenance['integrity_scope']})}
    store = HistoryStore(root, limit)
    with store.locked():
        store._publish('reference-inputs', revision, files, file_limit=MAX_BYTES)
    return {'schema': 'polar.reference-input-preparation/1', 'status': 'PREPARED_SOURCE_ONLY',
            'revision': revision, 'input_ref': output('manifest.json', files['manifest.json']),
            'strategy_execution': 'NOT_RUN'}

"""Lossless union of existing selected projections; never reconstruct source payloads."""
from pathlib import Path
from .ci_research import require
from .history_bundle import canonical
from .history_store import HistoryStore
from .research_reference import decode, pinned_bytes, load_reference, MAX_BYTES
from .reference_input import sha, schedule_binding_matches
from .selected_reference_input import RIGHTS

PROFILE = 'COMPOSED-ALL-ADJUSTED-REFERENCE-INPUT-V1'
SELECTED_PROFILE = 'SELECTED-COMPOSED-ALL-ADJUSTED-REFERENCE-INPUT-V1'


def composition_metadata(config):
    """Validate purpose, namespaces and complete calendar before opening numeric rows."""
    selected=config.get('schema')=='polar.reference-input-conversion-config/5'
    require(set(config)=={'schema','profile_id','namespace','inputs','purpose','schedule','date_range'} and
            config['schema']==('polar.reference-input-conversion-config/5' if selected else 'polar.reference-input-conversion-config/3') and config['profile_id']==(SELECTED_PROFILE if selected else PROFILE) and
            config['namespace'] in ('INVENTED','RETAINED'),'REFERENCE_COMPOSITION_CONFIG')
    inputs=config['inputs']
    require(type(inputs) is list and 2<=len(inputs)<=16,'REFERENCE_COMPOSITION_INPUTS')
    if selected:
        require(len(inputs)==2 and all(type(x) is dict and set(x)=={'input_ref','symbols'} and
                type(x['symbols']) is list and x['symbols']==sorted(set(x['symbols'])) for x in inputs) and
                {tuple(x['symbols']) for x in inputs}=={('VTI',),('BIL','SHY')},'REFERENCE_COMPOSITION_SELECTION')
    pins=[x['input_ref'] for x in inputs] if selected else inputs
    manifests=[decode(pinned_bytes(pin)) for pin in pins]
    require(len({pin['sha256'] for pin in pins})==len(pins),'REFERENCE_COMPOSITION_DUPLICATE_INPUT')
    purpose=decode(pinned_bytes(config['purpose']))
    fields={'schema','inputs','symbols','schedule','date_range','consumer_protocol','source_acceptance','rights_source_refs','rights'}
    require(type(purpose) is dict and set(purpose)==fields and
            purpose['schema']==('polar.reference-input-composition-purpose/2' if selected else 'polar.reference-input-composition-purpose/1') and purpose['inputs']==inputs and
            purpose['schedule']==config['schedule'] and purpose['date_range']==config['date_range'],
            'REFERENCE_COMPOSITION_PURPOSE')
    rights='INVENTED_PUBLIC_TEST' if config['namespace']=='INVENTED' else RIGHTS
    require(purpose['rights']==rights,'REFERENCE_COMPOSITION_RIGHTS')
    for name in ('consumer_protocol','source_acceptance'):
        require(type(decode(pinned_bytes(purpose[name]))) is dict,'REFERENCE_COMPOSITION_PURPOSE_REF')
    if selected:
        wrapper=decode(pinned_bytes(purpose['consumer_protocol']))
        require(set(wrapper)=={'schema','protocol','packet'} and wrapper['schema']=='polar.captured-reference-protocol-binding/1',
                'REFERENCE_COMPOSITION_PROTOCOL_BINDING')
        pinned_bytes(wrapper['protocol'])  # Protocol is Markdown, not JSON.
        require(type(decode(pinned_bytes(wrapper['packet']))) is dict,'REFERENCE_COMPOSITION_PROTOCOL_PACKET')
    refs=purpose['rights_source_refs']
    require(type(refs) is list and 1<=len(refs)<=16,'REFERENCE_COMPOSITION_RIGHTS_REFS')
    for pin in refs:pinned_bytes(pin)
    symbols=[];collections=[];schedule_raw=None
    for index,manifest in enumerate(manifests):
        require(manifest.get('schema')=='polar.synthetic-reference-source-input/2' and
                manifest.get('quote_basis')=='VENDOR_ALL_ADJUSTED_REFERENCE_CLOSE' and
                manifest.get('unit_type')=='SYNTHETIC_REFERENCE_UNIT_NOT_RAW_SHARE' and
                manifest.get('double_action_policy')=='NO_ADDITIONAL_SPLIT_DIVIDEND_CREDIT_IN_REFERENCE_UNIT_MODEL' and
                manifest.get('rights')==rights,'REFERENCE_COMPOSITION_BASIS_RIGHTS')
        meta=manifest.get('conversion_metadata',manifest.get('provenance',{}))
        captured=meta.get('converter')=='polar.reference-input-converter/4' and meta.get('profile')=='CAPTURED-BIL-ADJUSTED-REFERENCE-INPUT-V1'
        composed=selected and meta.get('converter')=='polar.reference-input-composer/1' and meta.get('profile')==PROFILE
        require(composed or captured or meta.get('converter')=='polar.reference-input-converter/2' and
                meta.get('profile')=='SELECTED-ALL-ADJUSTED-REFERENCE-INPUT-V1',
                'REFERENCE_COMPOSITION_SELECTED_INPUT')
        if config['namespace']=='INVENTED':
            require(str(manifest.get('parent_dataset_revision','')).startswith('INVENTED-') and
                    manifest['provenance']=={'kind':'DETERMINISTIC_INVENTED_FIXTURE','producer':'polar-public-tests','source_payloads':'NONE'},
                    'REFERENCE_COMPOSITION_NAMESPACE')
        else:
            require(not str(manifest.get('parent_dataset_revision','')).startswith('INVENTED-') and
                    (not selected or manifest.get('provenance',{}).get('kind')!='DETERMINISTIC_INVENTED_FIXTURE'),'REFERENCE_COMPOSITION_NAMESPACE')
        require(manifest['dates']==config['date_range'] and schedule_binding_matches(manifest,config['schedule']),
                'REFERENCE_COMPOSITION_CALENDAR')
        raw=pinned_bytes(manifest['schedule'])
        require(schedule_raw is None or schedule_raw==raw,'REFERENCE_COMPOSITION_CALENDAR')
        schedule_raw=raw
        current=inputs[index]['symbols'] if selected else manifest['symbols']
        if selected:
            require(set(current)<=set(manifest['symbols']) and
                    (current==['VTI'] and meta.get('converter')=='polar.reference-input-converter/2' or
                     current==['BIL','SHY'] and composed and manifest['symbols']==current),
                    'REFERENCE_COMPOSITION_SELECTED_SOURCE')
        require(type(current) is list and current==sorted(set(current)) and current and
                not set(current)&set(symbols),'REFERENCE_COMPOSITION_SYMBOL_OVERLAP')
        symbols.extend(current);collections.append(pins[index] if selected else meta['source_capture'] if captured else meta['source_collection'])
    require(len({p['sha256'] for p in collections})==len(collections),'REFERENCE_COMPOSITION_COLLECTION_ALIAS')
    symbols.sort()
    require(symbols==purpose['symbols'] and len(symbols)<=64,'REFERENCE_COMPOSITION_SYMBOL_SET')
    return manifests,purpose,schedule_raw,symbols,collections


def prepare_composition(config,root,limit):
    manifests,purpose,schedule_raw,symbols,collections=composition_metadata(config)
    selected=config['schema']=='polar.reference-input-conversion-config/5'
    pins=[x['input_ref'] for x in config['inputs']] if selected else config['inputs']
    quotes={};members={};records=[];coverage=[];jobs={};parents={};components=[];captures={}
    days=None;total=0
    for index,(pin,manifest) in enumerate(zip(pins,manifests)):
        current=config['inputs'][index]['symbols'] if selected else manifest['symbols']
        market=load_reference(pin)  # Same accepted validation, no original raw/normalized re-extraction.
        require(days is None or days==market['dates'],'REFERENCE_COMPOSITION_CALENDAR')
        days=market['dates'];relations=market['source_relations']
        for target,source in ((jobs,relations['jobs']),(parents,relations['parent_relations']),(captures,relations.get('captures',{}))):
            for key,value in source.items():
                require(key not in target or target[key]==value,'REFERENCE_COMPOSITION_RELATION_COLLISION')
                target[key]=value
        for member in manifest['source_members']:
            if member['sha256'] not in members:members[member['sha256']]=member
        records.extend(r for r in relations['records'] if not selected or r['literal_alias'] in current)
        coverage.extend(relations['source_coverage_records'])
        for line in pinned_bytes(manifest['quotes']).splitlines(keepends=True):
            value=decode(line)
            if value['symbol'] not in current:continue
            key=(value['date'],value['symbol'])
            require(key not in quotes,'REFERENCE_COMPOSITION_DUPLICATE_QUOTE')
            quotes[key]=line;total+=len(line)
            require(total<=MAX_BYTES,'REFERENCE_COMPOSITION_BYTES_BOUND')
        meta=manifest.get('conversion_metadata',manifest['provenance'])
        origin='source_input' if selected else 'source_capture' if meta.get('converter')=='polar.reference-input-converter/4' else 'source_collection'
        components.append({'input_ref':pin,origin:collections[len(components)],
            'symbols':current,'source_relations':manifest['source_relations']})
    require(set(quotes)=={(d,s) for d in days for s in symbols},'REFERENCE_COMPOSITION_GRID')
    raw=b''.join(quotes[d,s] for d in days for s in symbols)
    relations={'schema':'polar.reference-source-relations/1','records':sorted(records,key=lambda r:r['literal_alias']),
        'eligibility_ledger':{'schema':'polar.selected-source-purpose-membership/1','selected_aliases_fixed_order':symbols},
        'jobs':jobs,'parent_relations':parents,'source_coverage_records':coverage,
        'source_components':components,'source_purpose':config['purpose'],**({'captures':captures} if captures else {})}
    semantic={'converter':'polar.reference-input-composer/2' if selected else 'polar.reference-input-composer/1','config':config,'quotes_sha256':sha(raw),
        'schedule_sha256':sha(schedule_raw),'relations_sha256':sha(canonical(relations))}
    revision='reference-input-'+sha(canonical(semantic));destination=Path(root)/'reference-inputs'/revision
    output_pin=lambda name,data:{'path':str(destination/name),'sha256':sha(data),'bytes':len(data)}
    provenance={'converter':'polar.reference-input-composer/2' if selected else 'polar.reference-input-composer/1','profile':SELECTED_PROFILE if selected else PROFILE,'parent_schedule':config['schedule'],
        'source_components':components,'semantic':semantic,'vintage_equivalence':'NOT_ESTABLISHED',
        'economic_distinct_count':'NOT_ESTABLISHED','model_execution':'UNSUPPORTED_BY_THIS_CONVERTER'}
    manifest={'schema':'polar.synthetic-reference-source-input/2','quote_basis':'VENDOR_ALL_ADJUSTED_REFERENCE_CLOSE',
        'unit_type':'SYNTHETIC_REFERENCE_UNIT_NOT_RAW_SHARE',
        'double_action_policy':'NO_ADDITIONAL_SPLIT_DIVIDEND_CREDIT_IN_REFERENCE_UNIT_MODEL',
        'symbols':symbols,'dates':config['date_range'],'rows':len(quotes),'rights':purpose['rights'],
        'schedule':output_pin('schedule.json',schedule_raw),'quotes':output_pin('quotes.ndjson',raw),
        'source_relations':output_pin('source-relations.json',canonical(relations)),
        'source_members':list(members.values()),'parent_dataset_revision':('INVENTED-' if config['namespace']=='INVENTED' else '')+'composed-'+sha(canonical(config['inputs'])),
        'provenance':provenance}
    if config['namespace']=='INVENTED':
        manifest['conversion_metadata']=provenance
        manifest['provenance']={'kind':'DETERMINISTIC_INVENTED_FIXTURE','producer':'polar-public-tests','source_payloads':'NONE'}
    files={'manifest.json':canonical(manifest),'quotes.ndjson':raw,'schedule.json':schedule_raw,
        'source-relations.json':canonical(relations),'quality.json':canonical({'components':len(components),'rows':len(quotes),
        'scale':'LOSSLESS_1_TO_6DP','observed_clocks':'PRESERVED_NOT_INFERRED','vintage_equivalence':'NOT_ESTABLISHED',
        'scientific_fitness':'NOT_ASSESSED','model_features_returns_labels_native_calls':0})}
    store=HistoryStore(root,limit)
    with store.locked():store._publish('reference-inputs',revision,files,file_limit=MAX_BYTES)
    pin=output_pin('manifest.json',files['manifest.json']);load_reference(pin)
    return {'schema':'polar.reference-input-preparation/1','status':'PREPARED_SOURCE_ONLY','revision':revision,
        'input_ref':pin,'symbols':len(symbols),'rows':len(quotes),'quote_bytes':len(raw),
        'scientific_fitness':'NOT_ASSESSED','strategy_execution':'NOT_RUN'}


VIEW_PROFILE = 'CALENDAR-VTI-BIL-SOURCE-VIEW-V1'


def source_view_metadata(config):
    """Closed source-view metadata checks before any quote/source value access."""
    from datetime import date
    from .reference_input import project_schedule
    from .research_reference import reference_schedule

    def fields(obj, expected, code):
        require(type(obj) is dict and set(obj) == set(expected.split()), code)

    fields(config, 'schema profile_id namespace input_ref purpose schedule date_range', 'REFERENCE_VIEW_CONFIG')
    require(config['schema'] == 'polar.reference-input-conversion-config/6' and
            config['profile_id'] == VIEW_PROFILE and config['namespace'] in ('INVENTED', 'RETAINED'),
            'REFERENCE_VIEW_CONFIG')
    fields(config['date_range'], 'start end count', 'REFERENCE_VIEW_DATES')
    require(type(config['date_range']['start']) is str and type(config['date_range']['end']) is str and
            type(config['date_range']['count']) is int and config['date_range']['count'] == 916,
            'REFERENCE_VIEW_DATES')
    manifest = decode(pinned_bytes(config['input_ref']))
    purpose = decode(pinned_bytes(config['purpose']))
    fields(purpose, 'schema input_ref symbols schedule date_range roles consumer_protocol source_acceptance '
                    'rights_source_refs rights event_panel date_association', 'REFERENCE_VIEW_PURPOSE')
    require(purpose['schema'] == 'polar.reference-input-selected-view-purpose/1' and
            canonical(purpose['input_ref']) == canonical(config['input_ref']) and canonical(purpose['schedule']) == canonical(config['schedule']) and
            canonical(purpose['date_range']) == canonical(config['date_range']) and
            purpose['symbols'] == ['BIL', 'VTI'], 'REFERENCE_VIEW_PURPOSE')
    rights = 'INVENTED_PUBLIC_TEST' if config['namespace'] == 'INVENTED' else RIGHTS
    require(purpose['rights'] == rights, 'REFERENCE_VIEW_RIGHTS')
    require(type(manifest) is dict and manifest.get('schema') == 'polar.synthetic-reference-source-input/2'
            and manifest.get('symbols') == ['BIL', 'SHY', 'VTI'] and
            manifest.get('quote_basis') == 'VENDOR_ALL_ADJUSTED_REFERENCE_CLOSE' and
            manifest.get('unit_type') == 'SYNTHETIC_REFERENCE_UNIT_NOT_RAW_SHARE' and
            manifest.get('double_action_policy') == 'NO_ADDITIONAL_SPLIT_DIVIDEND_CREDIT_IN_REFERENCE_UNIT_MODEL'
            and manifest.get('rights') == rights, 'REFERENCE_VIEW_PARENT_BASIS')
    meta = manifest.get('conversion_metadata', manifest.get('provenance'))
    require(type(meta) is dict and meta.get('converter') == 'polar.reference-input-composer/2'
            and meta.get('profile') == SELECTED_PROFILE, 'REFERENCE_VIEW_PARENT_PRODUCER')
    semantic = meta.get('semantic')
    require(type(semantic) is dict and type(semantic.get('config')) is dict and
            semantic['config'].get('namespace') == config['namespace'], 'REFERENCE_VIEW_NAMESPACE')
    parent_config = semantic['config']
    require(semantic.get('converter') == 'polar.reference-input-composer/2' and
            parent_config.get('schema') == 'polar.reference-input-conversion-config/5' and
            parent_config.get('profile_id') == SELECTED_PROFILE and
            canonical(parent_config.get('date_range')) == canonical(manifest.get('dates')) and
            semantic.get('quotes_sha256') == manifest.get('quotes', {}).get('sha256') and
            semantic.get('schedule_sha256') == manifest.get('schedule', {}).get('sha256') and
            semantic.get('relations_sha256') == manifest.get('source_relations', {}).get('sha256'),
            'REFERENCE_VIEW_PARENT_SEMANTIC')
    fixture = {'kind': 'DETERMINISTIC_INVENTED_FIXTURE', 'producer': 'polar-public-tests', 'source_payloads': 'NONE'}
    require(type(manifest.get('provenance')) is dict, 'REFERENCE_VIEW_NAMESPACE')
    parent_revision = manifest.get('parent_dataset_revision')
    require(type(parent_revision) is str, 'REFERENCE_VIEW_NAMESPACE')
    if config['namespace'] == 'INVENTED':
        require(parent_revision.startswith('INVENTED-') and manifest.get('provenance') == fixture,
                'REFERENCE_VIEW_NAMESPACE')
    else:
        require(not parent_revision.startswith('INVENTED-') and
                manifest.get('provenance', {}).get('kind') != fixture['kind'], 'REFERENCE_VIEW_NAMESPACE')
    require(schedule_binding_matches(manifest, config['schedule']), 'REFERENCE_VIEW_PARENT_SCHEDULE')
    parent_schedule = decode(pinned_bytes(manifest['schedule']))
    _, parent_days = reference_schedule(parent_schedule)
    fields(manifest.get('dates'), 'start end count', 'REFERENCE_VIEW_PARENT_GRID')
    require(type(manifest['dates']['count']) is int and manifest['dates'] ==
            {'start': parent_days[0], 'end': parent_days[-1], 'count': len(parent_days)} and
            type(manifest.get('rows')) is int and manifest['rows'] == len(parent_days) * 3,
            'REFERENCE_VIEW_PARENT_GRID')
    selected = project_schedule(parent_schedule, config['date_range'])
    _, days = reference_schedule(selected)
    roles = purpose['roles']
    fields(roles, 'nav_dates warmup_dates warmup_symbol context_symbol', 'REFERENCE_VIEW_ROLES')
    nav, warm = roles['nav_dates'], roles['warmup_dates']
    require(type(nav) is list and len(nav) == 716 and type(warm) is list and len(warm) == 200
            and roles['warmup_symbol'] == 'VTI' and roles['context_symbol'] == 'BIL', 'REFERENCE_VIEW_ROLES')
    for dates in (nav, warm):
        require(all(type(d) is str for d in dates), 'REFERENCE_VIEW_ROLE_DATES')
        try:
            require(all(date.fromisoformat(d).isoformat() == d for d in dates), 'REFERENCE_VIEW_ROLE_DATES')
        except ValueError:
            require(False, 'REFERENCE_VIEW_ROLE_DATES')
        require(dates == sorted(set(dates)), 'REFERENCE_VIEW_ROLE_DATES')
    require(warm + nav == days and warm[0] == '2023-03-16' and warm[-1] == '2023-12-29'
            and nav[0] == '2024-01-02' and nav[-1] == '2026-11-06', 'REFERENCE_VIEW_ROLE_MEMBERSHIP')
    wrapper = decode(pinned_bytes(purpose['consumer_protocol']))
    fields(wrapper, 'schema protocol packet', 'REFERENCE_VIEW_PROTOCOL')
    require(wrapper['schema'] == 'polar.captured-reference-protocol-binding/1', 'REFERENCE_VIEW_PROTOCOL')
    pinned_bytes(wrapper['protocol'])
    require(type(decode(pinned_bytes(wrapper['packet']))) is dict, 'REFERENCE_VIEW_PROTOCOL')
    for key in ('source_acceptance', 'event_panel', 'date_association'):
        require(type(decode(pinned_bytes(purpose[key]))) is dict, 'REFERENCE_VIEW_METADATA_REF')
    refs = purpose['rights_source_refs']
    require(type(refs) is list and 1 <= len(refs) <= 16, 'REFERENCE_VIEW_RIGHTS_REFS')
    for pin in refs: pinned_bytes(pin)
    return manifest, purpose, selected, days


def prepare_source_view(config, root, limit):
    """One lossless rectangle, explicit role support, unchanged accepted v2 reader."""
    from copy import deepcopy
    manifest, purpose, schedule, days = source_view_metadata(config)
    market = load_reference(config['input_ref'])
    require(set(days) <= set(market['dates']) and set(purpose['symbols']) <= set(market['symbols']),
            'REFERENCE_VIEW_PARENT_GRID')
    symbols = purpose['symbols']; selected_days = set(days); quotes = {}
    for line in pinned_bytes(manifest['quotes']).splitlines(keepends=True):
        row = decode(line)
        if row['date'] not in selected_days or row['symbol'] not in symbols: continue
        key = (row['date'], row['symbol'])
        require(key not in quotes, 'REFERENCE_VIEW_DUPLICATE_QUOTE')
        quotes[key] = line
    require(set(quotes) == {(d, s) for d in days for s in symbols}, 'REFERENCE_VIEW_RECTANGLE')
    raw = b''.join(quotes[d, s] for d in days for s in symbols)
    require(len(raw) <= MAX_BYTES, 'REFERENCE_VIEW_BYTES_BOUND')
    relations = deepcopy(market['source_relations'])
    relations['records'] = [r for r in relations['records'] if r['literal_alias'] in symbols]
    relations['eligibility_ledger'] = {'schema': 'polar.selected-source-purpose-membership/1',
                                     'selected_aliases_fixed_order': symbols}
    # Keep the original component graph; unselected metadata is not an economic row.
    relations['parent_source_relations'] = manifest['source_relations']
    relations['source_purpose'] = config['purpose']
    relations['source_view_parent'] = config['input_ref']
    membership = {'schema': 'polar.reference-source-date-roles/1', 'source_dates': days,
                  'symbols': symbols, 'NAV': {'dates': purpose['roles']['nav_dates'], 'symbols': symbols},
                  'WARMUP_CANDIDATE': {'dates': purpose['roles']['warmup_dates'], 'symbols': ['VTI']},
                  'UNUSED_WARMUP_CONTEXT': {'dates': purpose['roles']['warmup_dates'], 'symbols': ['BIL']},
                  'counts': {'source_dates': 916, 'source_rows': 1832, 'NAV_dates': 716,
                             'NAV_rows': 1432, 'VTI_warmup_rows': 200, 'BIL_unused_context_rows': 200},
                  'clock_eligibility': 'NOT_DERIVED', 'financial': 'NOT_RUN'}
    schedule_raw = canonical(schedule); role_raw = canonical(membership)
    semantic = {'converter': 'polar.reference-input-source-view/1', 'config': config,
                'quotes_sha256': sha(raw), 'schedule_sha256': sha(schedule_raw),
                'relations_sha256': sha(canonical(relations)), 'roles_sha256': sha(role_raw)}
    revision = 'reference-input-' + sha(canonical(semantic))
    destination = Path(root) / 'reference-inputs' / revision
    pin = lambda name, data: {'path': str(destination / name), 'sha256': sha(data), 'bytes': len(data)}
    provenance = {'converter': 'polar.reference-input-source-view/1', 'profile': VIEW_PROFILE,
                  'parent_input': config['input_ref'], 'parent_schedule': config['schedule'],
                  'source_purpose': config['purpose'], 'date_roles': pin('date-roles.json', role_raw),
                  'semantic': semantic, 'economic_distinct_count': 'NOT_ESTABLISHED',
                  'model_execution': 'UNSUPPORTED_BY_THIS_CONVERTER'}
    output = {'schema': 'polar.synthetic-reference-source-input/2',
              'quote_basis': manifest['quote_basis'], 'unit_type': manifest['unit_type'],
              'double_action_policy': manifest['double_action_policy'], 'symbols': symbols,
              'dates': config['date_range'], 'rows': len(quotes), 'rights': purpose['rights'],
              'schedule': pin('schedule.json', schedule_raw), 'quotes': pin('quotes.ndjson', raw),
              'source_relations': pin('source-relations.json', canonical(relations)),
              'source_members': manifest['source_members'],
              'parent_dataset_revision': ('INVENTED-' if config['namespace'] == 'INVENTED' else '') + 'source-view-' + sha(canonical(semantic)),
              'provenance': provenance}
    if config['namespace'] == 'INVENTED':
        output['conversion_metadata'] = provenance
        output['provenance'] = {'kind': 'DETERMINISTIC_INVENTED_FIXTURE', 'producer': 'polar-public-tests', 'source_payloads': 'NONE'}
    files = {'manifest.json': canonical(output), 'quotes.ndjson': raw, 'schedule.json': schedule_raw,
             'source-relations.json': canonical(relations), 'date-roles.json': role_raw,
             'quality.json': canonical({'scope': 'SOURCE_ONLY_EXPLICIT_ROLES_NOT_MODEL_MEMBERSHIP',
                 'rows': len(quotes), 'observed_clocks': 'PRESERVED_NOT_INFERRED',
                 'scale': 'LOSSLESS_ORIGINAL_LEXEMES', 'scientific_fitness': 'NOT_ASSESSED',
                 'native_calls': 0, 'financial': 'NOT_RUN'})}
    store = HistoryStore(root, limit)
    with store.locked():
        store._publish('reference-inputs', revision, files, file_limit=MAX_BYTES)
    result_pin = pin('manifest.json', files['manifest.json']); load_reference(result_pin)
    return {'schema': 'polar.reference-input-preparation/1', 'status': 'PREPARED_SOURCE_ONLY',
            'revision': revision, 'input_ref': result_pin, 'date_roles': pin('date-roles.json', role_raw),
            'symbols': len(symbols), 'rows': len(quotes), 'role_counts': membership['counts'],
            'scientific_fitness': 'NOT_ASSESSED', 'strategy_execution': 'NOT_RUN'}

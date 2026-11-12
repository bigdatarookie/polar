"""Lossless union of existing selected projections; never reconstruct source payloads."""
from pathlib import Path
from .ci_research import require
from .history_bundle import canonical
from .history_store import HistoryStore
from .research_reference import decode, pinned_bytes, load_reference, MAX_BYTES
from .reference_input import sha, schedule_binding_matches
from .selected_reference_input import RIGHTS

PROFILE = 'COMPOSED-ALL-ADJUSTED-REFERENCE-INPUT-V1'


def composition_metadata(config):
    """Validate purpose, namespaces and complete calendar before opening numeric rows."""
    require(set(config)=={'schema','profile_id','namespace','inputs','purpose','schedule','date_range'} and
            config['schema']=='polar.reference-input-conversion-config/3' and config['profile_id']==PROFILE and
            config['namespace'] in ('INVENTED','RETAINED'),'REFERENCE_COMPOSITION_CONFIG')
    inputs=config['inputs']
    require(type(inputs) is list and 2<=len(inputs)<=16,'REFERENCE_COMPOSITION_INPUTS')
    manifests=[decode(pinned_bytes(pin)) for pin in inputs]
    require(len({pin['sha256'] for pin in inputs})==len(inputs),'REFERENCE_COMPOSITION_DUPLICATE_INPUT')
    purpose=decode(pinned_bytes(config['purpose']))
    fields={'schema','inputs','symbols','schedule','date_range','consumer_protocol','source_acceptance','rights_source_refs','rights'}
    require(type(purpose) is dict and set(purpose)==fields and
            purpose['schema']=='polar.reference-input-composition-purpose/1' and purpose['inputs']==inputs and
            purpose['schedule']==config['schedule'] and purpose['date_range']==config['date_range'],
            'REFERENCE_COMPOSITION_PURPOSE')
    rights='INVENTED_PUBLIC_TEST' if config['namespace']=='INVENTED' else RIGHTS
    require(purpose['rights']==rights,'REFERENCE_COMPOSITION_RIGHTS')
    for name in ('consumer_protocol','source_acceptance'):
        require(type(decode(pinned_bytes(purpose[name]))) is dict,'REFERENCE_COMPOSITION_PURPOSE_REF')
    refs=purpose['rights_source_refs']
    require(type(refs) is list and 1<=len(refs)<=16,'REFERENCE_COMPOSITION_RIGHTS_REFS')
    for pin in refs:pinned_bytes(pin)
    symbols=[];collections=[];schedule_raw=None
    for manifest in manifests:
        require(manifest.get('schema')=='polar.synthetic-reference-source-input/2' and
                manifest.get('quote_basis')=='VENDOR_ALL_ADJUSTED_REFERENCE_CLOSE' and
                manifest.get('unit_type')=='SYNTHETIC_REFERENCE_UNIT_NOT_RAW_SHARE' and
                manifest.get('double_action_policy')=='NO_ADDITIONAL_SPLIT_DIVIDEND_CREDIT_IN_REFERENCE_UNIT_MODEL' and
                manifest.get('rights')==rights,'REFERENCE_COMPOSITION_BASIS_RIGHTS')
        meta=manifest.get('conversion_metadata',manifest.get('provenance',{}))
        require(meta.get('converter')=='polar.reference-input-converter/2' and
                meta.get('profile')=='SELECTED-ALL-ADJUSTED-REFERENCE-INPUT-V1',
                'REFERENCE_COMPOSITION_SELECTED_INPUT')
        if config['namespace']=='INVENTED':
            require(str(manifest.get('parent_dataset_revision','')).startswith('INVENTED-') and
                    manifest['provenance']=={'kind':'DETERMINISTIC_INVENTED_FIXTURE','producer':'polar-public-tests','source_payloads':'NONE'},
                    'REFERENCE_COMPOSITION_NAMESPACE')
        else:
            require(not str(manifest.get('parent_dataset_revision','')).startswith('INVENTED-'),'REFERENCE_COMPOSITION_NAMESPACE')
        require(manifest['dates']==config['date_range'] and schedule_binding_matches(manifest,config['schedule']),
                'REFERENCE_COMPOSITION_CALENDAR')
        raw=pinned_bytes(manifest['schedule'])
        require(schedule_raw is None or schedule_raw==raw,'REFERENCE_COMPOSITION_CALENDAR')
        schedule_raw=raw
        current=manifest['symbols']
        require(type(current) is list and current==sorted(set(current)) and current and
                not set(current)&set(symbols),'REFERENCE_COMPOSITION_SYMBOL_OVERLAP')
        symbols.extend(current);collections.append(meta['source_collection'])
    require(len({p['sha256'] for p in collections})==len(collections),'REFERENCE_COMPOSITION_COLLECTION_ALIAS')
    symbols.sort()
    require(symbols==purpose['symbols'] and len(symbols)<=64,'REFERENCE_COMPOSITION_SYMBOL_SET')
    return manifests,purpose,schedule_raw,symbols,collections


def prepare_composition(config,root,limit):
    manifests,purpose,schedule_raw,symbols,collections=composition_metadata(config)
    quotes={};members={};records=[];coverage=[];jobs={};parents={};components=[]
    days=None;total=0
    for pin,manifest in zip(config['inputs'],manifests):
        market=load_reference(pin)  # Same accepted validation, no original raw/normalized re-extraction.
        require(days is None or days==market['dates'],'REFERENCE_COMPOSITION_CALENDAR')
        days=market['dates'];relations=market['source_relations']
        for target,source in ((jobs,relations['jobs']),(parents,relations['parent_relations'])):
            for key,value in source.items():
                require(key not in target or target[key]==value,'REFERENCE_COMPOSITION_RELATION_COLLISION')
                target[key]=value
        for member in manifest['source_members']:
            if member['sha256'] not in members:members[member['sha256']]=member
        records.extend(relations['records']);coverage.extend(relations['source_coverage_records'])
        for line in pinned_bytes(manifest['quotes']).splitlines(keepends=True):
            value=decode(line);key=(value['date'],value['symbol'])
            require(key not in quotes,'REFERENCE_COMPOSITION_DUPLICATE_QUOTE')
            quotes[key]=line;total+=len(line)
            require(total<=MAX_BYTES,'REFERENCE_COMPOSITION_BYTES_BOUND')
        components.append({'input_ref':pin,'source_collection':collections[len(components)],
            'symbols':manifest['symbols'],'source_relations':manifest['source_relations']})
    require(set(quotes)=={(d,s) for d in days for s in symbols},'REFERENCE_COMPOSITION_GRID')
    raw=b''.join(quotes[d,s] for d in days for s in symbols)
    relations={'schema':'polar.reference-source-relations/1','records':sorted(records,key=lambda r:r['literal_alias']),
        'eligibility_ledger':{'schema':'polar.selected-source-purpose-membership/1','selected_aliases_fixed_order':symbols},
        'jobs':jobs,'parent_relations':parents,'source_coverage_records':coverage,
        'source_components':components,'source_purpose':config['purpose']}
    semantic={'converter':'polar.reference-input-composer/1','config':config,'quotes_sha256':sha(raw),
        'schedule_sha256':sha(schedule_raw),'relations_sha256':sha(canonical(relations))}
    revision='reference-input-'+sha(canonical(semantic));destination=Path(root)/'reference-inputs'/revision
    output_pin=lambda name,data:{'path':str(destination/name),'sha256':sha(data),'bytes':len(data)}
    provenance={'converter':'polar.reference-input-composer/1','profile':PROFILE,'parent_schedule':config['schedule'],
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

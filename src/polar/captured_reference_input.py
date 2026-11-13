"""Closed BIL capture bridge inside the existing offline reference converter.

Preserves the actual capture/plan/body and DE token pointers; creates no importer
job, collection, provider request, clock or financial calculation.
"""
from pathlib import Path
from .ci_research import require
from .gym_contract import sha
from .history_bundle import canonical
from .research_reference import decode,pinned_bytes,microprice,load_reference,MAX_BYTES
from .selected_reference_input import RIGHTS
from .history_store import HistoryStore

PROFILE='CAPTURED-BIL-ADJUSTED-REFERENCE-INPUT-V1'
CONVERTER='polar.reference-input-converter/4'
POINTER='CAPTURED_ALL_ADJUSTED_SOURCE'


def validate_pointer(value,members,relations):
    import re
    p=value['source_ref']
    require(type(p) is dict and set(p)=={'kind','capture_sha256','source_body_sha256','source_pointer',
            'source_row_index','exact_token_sha256','exact_token_pointer','source_symbol'} and
            p['kind']==POINTER,'REFERENCE_CAPTURE_POINTER')
    require(type(p['capture_sha256']) is str,'REFERENCE_CAPTURE_HASH')
    capture=relations.get('captures',{}).get(p['capture_sha256'])
    require(type(capture) is dict and p['source_body_sha256']==capture['source_body']['sha256'] in members and
            p['exact_token_sha256']==capture['exact_tokens']['sha256'] in members and
            p['source_symbol']==value['symbol']=='BIL' and type(p['source_row_index']) is int and p['source_row_index']>=0,
            'REFERENCE_CAPTURE_SOURCE_BINDING')
    i=p['source_row_index']
    require(p['source_pointer']==f'/bars/BIL/{i}/c' and p['exact_token_pointer']==f'/rows/{i}/tokens/c' and
            capture['request']['symbols']=='BIL' and capture['request']['adjustment']=='all',
            'REFERENCE_CAPTURE_SOURCE_POINTER')
    require(all(type(p[k]) is str and re.fullmatch('[a-f0-9]{64}',p[k]) for k in
            ('capture_sha256','source_body_sha256','exact_token_sha256')),'REFERENCE_CAPTURE_HASH')


def prepare_capture(config,root,limit):
    from .reference_input import project_schedule,BASIS
    require(type(config) is dict and set(config)=={'schema','profile_id','namespace','capture_return','exact_tokens',
            'purpose','schedule','date_range'} and config['schema']=='polar.reference-input-conversion-config/4' and
            config['profile_id']==PROFILE and config['namespace'] in ('INVENTED','RETAINED'),'REFERENCE_CAPTURE_CONFIG')
    rights='INVENTED_PUBLIC_TEST' if config['namespace']=='INVENTED' else RIGHTS
    purpose=decode(pinned_bytes(config['purpose']))
    require(type(purpose) is dict and set(purpose)=={'schema','capture_return','exact_tokens','symbols','schedule',
            'date_range','consumer_protocol','source_acceptance','rights_source_refs','rights'} and
            purpose['schema']=='polar.captured-reference-source-purpose/1' and purpose['rights']==rights and
            purpose['symbols']==['BIL'] and all(canonical(purpose[k])==canonical(config[k]) for k in
            ('capture_return','exact_tokens','schedule','date_range')),'REFERENCE_CAPTURE_PURPOSE')
    protocol=decode(pinned_bytes(purpose['consumer_protocol']))
    require(type(protocol) is dict and set(protocol)=={'schema','protocol','packet'} and
            protocol['schema']=='polar.captured-reference-protocol-binding/1','REFERENCE_CAPTURE_PROTOCOL_BINDING')
    pinned_bytes(protocol['protocol']);require(type(decode(pinned_bytes(protocol['packet']))) is dict,'REFERENCE_CAPTURE_PROTOCOL_PACKET')
    acceptance=decode(pinned_bytes(purpose['source_acceptance']));require(type(acceptance) is dict,'REFERENCE_CAPTURE_PURPOSE_REF')
    require(type(purpose['rights_source_refs']) is list and 1<=len(purpose['rights_source_refs'])<=16,'REFERENCE_CAPTURE_RIGHTS')
    for p in purpose['rights_source_refs']:pinned_bytes(p)
    capture=decode(pinned_bytes(config['capture_return']));plan=decode(pinned_bytes(capture['plan_ref']))
    require(capture.get('schema')=='polar.BIL-full-range-single-GET-capture-return/1' and
            capture.get('status')=='HTTP_RESPONSE_ARCHIVED' and plan.get('schema')=='polar.bounded-provider-full-range-source-plan/1' and
            plan.get('endpoint')=='https://data.alpaca.markets/v2/stocks/bars' and plan.get('method')=='GET','REFERENCE_CAPTURE_IDENTITY')
    if config['namespace']=='INVENTED':
        require(capture.get('provenance')=={'kind':'DETERMINISTIC_INVENTED_FIXTURE','source_payloads':'NONE'} and
                plan.get('mode')=='fixture','REFERENCE_CAPTURE_INVENTED_PROVENANCE')
    else:
        require(capture.get('rights')=='PRIVATE_SOLE_OWNER_NONCOMMERCIAL_NO_PUBLIC_REPO_OR_REDISTRIBUTION','REFERENCE_CAPTURE_RIGHTS')
        provenance=capture.get('provenance')
        require(plan.get('mode') in (None,'provider') and
                (provenance is None or type(provenance) is dict and
                 provenance.get('kind')!='DETERMINISTIC_INVENTED_FIXTURE' and provenance.get('source_payloads')!='NONE'),
                'REFERENCE_CAPTURE_RETAINED_NAMESPACE')
    query=plan['query'];require(type(query) is dict and all(query.get(k)==v for k,v in
            {'symbols':'BIL','timeframe':'1Day','feed':'sip','currency':'USD','adjustment':'all','sort':'asc'}.items()),
            'REFERENCE_CAPTURE_REQUEST_BASIS')
    http=capture['HTTP_metadata']
    require(type(http.get('status')) is int and http['status']==200 and http.get('complete_at_capture') is True and
            type(http.get('captured_body_bytes')) is int and http['captured_body_bytes']==capture['body_ref']['bytes'] and
            http.get('published_at') is None and http.get('historical_available_at') is None and http.get('source_version') is None,
            'REFERENCE_CAPTURE_HTTP')
    if config['namespace']=='RETAINED':
        require(acceptance.get('schema')=='polar.B9-exact-retained-source-date-basis-binding/1' and
            canonical(acceptance['selected_source_pins']['BIL_exact_tokens'])==canonical(config['exact_tokens']) and
            canonical(acceptance['selected_source_pins']['BIL_raw'])==canonical(capture['body_ref']) and
            canonical(acceptance['schedule'])==canonical(config['schedule']),'REFERENCE_CAPTURE_SOURCE_ACCEPTANCE')
    tokens=decode(pinned_bytes(config['exact_tokens']))
    require(type(tokens) is dict and tokens.get('schema')=='polar.selected-provider-full-snapshot-exact-tokens/1' and
            canonical(tokens['source'])==canonical(capture['body_ref']) and
            canonical(tokens['request_plan'])==canonical(capture['plan_ref']),'REFERENCE_CAPTURE_TOKEN_BINDING')
    # Original raw bytes, not a derived quote, are authoritative at this boundary.
    from .import_raw_sip import page
    body=pinned_bytes(capture['body_ref']);raw=page(body,limit=MAX_BYTES)
    require(set(raw['bars'])=={'BIL'} and raw.get('next_page_token') is None and
            tokens['original_top_level_other_fields'].get('next_page_token') is None,'REFERENCE_CAPTURE_COMPLETE')
    rows=raw['bars']['BIL'];require(type(tokens['rows']) is list and len(rows)==len(tokens['rows']),'REFERENCE_CAPTURE_TOKEN_COUNT')
    schedule=project_schedule(decode(pinned_bytes(config['schedule'])),config['date_range']);days=[r['date'] for r in schedule['rows']]
    selected={};csha=config['capture_return']['sha256']
    relation={'capture_return':config['capture_return'],'request_plan':capture['plan_ref'],'source_body':capture['body_ref'],
              'exact_tokens':config['exact_tokens'],'request':query,'basis':BASIS,'clocks':'HISTORICAL_UNKNOWN'}
    for i,(original,token) in enumerate(zip(rows,tokens['rows'])):
        require(token['source_pointer']==f'/bars/BIL/{i}' and token['quality']=='LEXICAL_DOMAIN_CHECKED' and
                canonical(token['tokens'])==canonical(original),'REFERENCE_CAPTURE_EXACT_TOKEN')
        day=original['t'][:10]
        if day not in days:continue  # Offrange source rows remain in the original preserved object.
        require(day not in selected and type(original['c']) is str,'REFERENCE_CAPTURE_DATE_DUPLICATE')
        from decimal import Decimal
        price=microprice(original['c']);require(Decimal(original['c']).as_tuple().exponent>=-2,'REFERENCE_CAPTURE_BIL_PRECISION')
        quoted=f'{price//1000000}.{price%1000000:06d}'
        value={'symbol':'BIL','date':day,'reference_quote':quoted,'source_adjusted_close_token':original['c'],
            'source_ref':{'kind':POINTER,'capture_sha256':csha,'source_body_sha256':capture['body_ref']['sha256'],
                'source_pointer':f'/bars/BIL/{i}/c','source_row_index':i,'exact_token_sha256':config['exact_tokens']['sha256'],
                'exact_token_pointer':f'/rows/{i}/tokens/c','source_symbol':'BIL'},
            'observed_published_at':None,'observed_historical_available_at':None}
        validate_pointer(value,{capture['body_ref']['sha256'],config['exact_tokens']['sha256']},{'captures':{csha:relation}})
        selected[day]=canonical(value)+b'\n'
    require(list(selected)==days,'REFERENCE_CAPTURE_SELECTED_GRID')
    quotes=b''.join(selected[d] for d in days);require(len(quotes)<=MAX_BYTES,'REFERENCE_CAPTURE_BYTES_BOUND')
    relations={'schema':'polar.reference-source-relations/1','records':[{'literal_alias':'BIL','selected_for_purpose':True,
        'capture_return':config['capture_return']}],'jobs':{},'parent_relations':{},'source_coverage_records':[],
        'captures':{csha:relation},'source_purpose':config['purpose']}
    semantic={'converter':CONVERTER,'config':config,'quotes_sha256':sha(quotes),'schedule_sha256':sha(canonical(schedule)),
              'relations_sha256':sha(canonical(relations))}
    revision='reference-input-'+sha(canonical(semantic));destination=Path(root)/'reference-inputs'/revision
    output=lambda n,b:{'path':str(destination/n),'sha256':sha(b),'bytes':len(b)}
    provenance={'converter':CONVERTER,'profile':PROFILE,'source_capture':config['capture_return'],'parent_schedule':config['schedule'],
                'semantic':semantic,'historical_availability':'UNKNOWN','model_execution':'UNSUPPORTED_BY_THIS_CONVERTER'}
    manifest={'schema':'polar.synthetic-reference-source-input/2','quote_basis':BASIS,'unit_type':'SYNTHETIC_REFERENCE_UNIT_NOT_RAW_SHARE',
        'double_action_policy':'NO_ADDITIONAL_SPLIT_DIVIDEND_CREDIT_IN_REFERENCE_UNIT_MODEL','symbols':['BIL'],
        'dates':config['date_range'],'rows':len(days),'rights':rights,'schedule':output('schedule.json',canonical(schedule)),
        'quotes':output('quotes.ndjson',quotes),'source_relations':output('source-relations.json',canonical(relations)),
        'source_members':[capture['body_ref'],config['exact_tokens']],
        'parent_dataset_revision':('INVENTED-' if config['namespace']=='INVENTED' else '')+csha,'provenance':provenance}
    if config['namespace']=='INVENTED':
        manifest['conversion_metadata']=provenance
        manifest['provenance']={'kind':'DETERMINISTIC_INVENTED_FIXTURE','producer':'polar-public-tests','source_payloads':'NONE'}
    files={'manifest.json':canonical(manifest),'quotes.ndjson':quotes,'schedule.json':canonical(schedule),
           'source-relations.json':canonical(relations),'quality.json':canonical({'rows':len(days),'scale':'LOSSLESS_1_TO_6DP',
            'original_capture_preserved':True,'fabricated_importer_jobs':0,'financial_native_model_calls':0})}
    store=HistoryStore(root,limit)
    with store.locked():store._publish('reference-inputs',revision,files,file_limit=MAX_BYTES)
    pin=output('manifest.json',files['manifest.json']);load_reference(pin)
    return {'schema':'polar.reference-input-preparation/1','status':'PREPARED_SOURCE_ONLY','revision':revision,'input_ref':pin,
            'symbols':1,'rows':len(days),'quote_bytes':len(quotes),'scientific_fitness':'NOT_ASSESSED','strategy_execution':'NOT_RUN'}

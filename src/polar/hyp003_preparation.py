"""Versioned offline partial-input preparation, not a financial algorithm/loader engine."""
from collections import Counter,defaultdict
from datetime import date,datetime,timezone
from decimal import Decimal,InvalidOperation
import hashlib
import os
from pathlib import Path
import re
import stat
import sys
import uuid

from .codec import canonical,digest
from .history_bundle import HistoryError,read_file,safe_root
from .history_store import HistoryStore
from .hyp003_source import (PreparationError,check,hash_value,decode,Sources,object_value,
                             member_stream,valid_clock,CONFIG_LIMIT,MANIFEST_LIMIT,NDJSON_LIMIT,RAW,METADATA)
from .hyp003_metadata import metadata_tables

TABLES=('raw_rows.ndjson','parent_relations.ndjson','source_parent_records.ndjson',
        'metadata_jobs.ndjson','transport_evidence.ndjson','source_metadata.ndjson')
OUTPUT_LIMIT=1024**3
TABLE_LIMIT=256*1024**2
OPTIONAL={'evidence_inputs','ancestry_objects','proposed_reconstruction_ref','qualified_universe_ref',
          'proposed_interval','proposed_grid','coverage_policy_ref'}

def config_value(value):
    check(type(value) is dict and {'schema','adapter_version','purpose','hypothesis_ref','definition_ref','inputs'}<=set(value) and
          set(value)<={'schema','adapter_version','purpose','hypothesis_ref','definition_ref','inputs'}|OPTIONAL)
    check(value['schema']=='polar.hyp003-preparation-config/1' and type(value['adapter_version']) is int and value['adapter_version']==1)
    check(value['purpose'] in ('DEVELOPMENT','EXPLORATORY','CONFIRMATORY_PREPARATION') and type(value['hypothesis_ref']) is str and 0<len(value['hypothesis_ref'])<=256)
    check(type(value['definition_ref']) in (str,dict) and bool(value['definition_ref']))
    check(type(value['inputs']) is list and type(value.get('evidence_inputs',[])) is list and len(value['inputs'])+len(value.get('evidence_inputs',[]))<=32)
    check(type(value.get('ancestry_objects',[])) is list and len(value.get('ancestry_objects',[]))<=32)
    check(len(canonical(value))<=CONFIG_LIMIT,'HYP003_CONFIG_LIMIT');return value

def quality(row):
    reasons=[];fields=row.get('raw_fields_exact_tokens',{})
    if not isinstance(fields,dict):fields={};reasons.append('RAW_FIELDS_NOT_OBJECT')
    values={}
    for long,key in (('open','o'),('high','h'),('low','l'),('close','c'),('volume','v')):
        value=row.get('raw_'+long,fields.get(key));required=key in ('o','c','v')
        if value is None:
            if required:reasons.append('RAW_'+long.upper()+'_MISSING')
            continue
        try:
            check(type(value) is str and len(value)<=1024,'HYP003_DECIMAL_TOKEN')
            number=Decimal(value)
            check(number.is_finite() and abs(number.as_tuple().exponent)<=1024 and len(number.as_tuple().digits)<=1024,'HYP003_DECIMAL_TOKEN')
            if number<0 or key!='v' and number==0:raise ValueError()
            values[key]=number
        except (PreparationError,InvalidOperation,ValueError,TypeError):reasons.append('RAW_'+long.upper()+'_INVALID')
    if all(k in values for k in ('o','h','l','c')) and not (values['l']<=min(values['o'],values['c'])<=max(values['o'],values['c'])<=values['h']):reasons.append('OHLC_RANGE_INVALID')
    day=row.get('reference_date')
    try:
        if type(day) is not str or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}',day) or date.fromisoformat(day).isoformat()!=day:raise ValueError()
    except ValueError:reasons.append('REFERENCE_DATE_INVALID')
    if row.get('adjustment')!='raw':reasons.append('RAW_PRICE_BASIS_UNQUALIFIED')
    if row.get('adjustment')!='raw' or row.get('volume_basis') not in (None,'RAW','RAW_SHARES','raw','UNADJUSTED'):reasons.append('RAW_VOLUME_BASIS_UNQUALIFIED')
    if row.get('currency') not in ('USD','USD_REQUEST_CONTRACT'):reasons.append('CURRENCY_UNRESOLVED')
    if not isinstance(row.get('feed'),str) or not row['feed']:reasons.append('FEED_UNRESOLVED')
    for field in ('event_open_at','event_close_at','observed_published_at','observed_historical_available_at','estimated_K'):
        if row.get(field) is not None and not valid_clock(row[field]):reasons.append(field.upper()+'_INVALID')
    if not isinstance(row.get('source_symbol'),str) or not row['source_symbol']:reasons.append('SOURCE_SYMBOL_MISSING')
    return {'status':'FIELDS_PARTIAL_OR_INVALID' if reasons else 'FIELDS_VALID_SOURCE_FITNESS_UNRESOLVED',
            'reasons':sorted(reasons),'observed_clock_status':'UNRESOLVED' if row.get('observed_historical_available_at') is None else 'SOURCE_DECLARED_NOT_QUALIFIED',
            'estimated_clock_status':'SOURCE_DECLARED_ESTIMATE' if row.get('estimated_K') is not None else 'ABSENT',
            'economic_identity':'UNRESOLVED'}

def _prepare(config):
    config=config_value(decode(canonical(config)));sources=Sources();primary=[]
    for entry in config['inputs']:primary.append(sources.add(entry,True))
    for entry in config.get('evidence_inputs',[]):sources.add(entry,False)
    tables={name:[] for name in TABLES};ancestry=[]
    for item in config.get('ancestry_objects',[]):
        check(type(item) is dict and set(item)=={'directory','path','sha256','role'} and item['role'] in ('SOURCE_PARENT_RECORDS','REFERENCE'),'HYP003_ANCESTRY_REFERENCE')
        root=Path(item['directory']);check(root.is_absolute(),'HYP003_ABSOLUTE_ROOT_REQUIRED')
        path=item['path'];limit=NDJSON_LIMIT if path.endswith('.ndjson') else MANIFEST_LIMIT
        body,ref=sources.read(root,path,limit,{'sha256':item['sha256']})
        ancestry.append({**ref,'role':item['role']})
        sources.physical.append({'ancestry_path':path,'directory':str(root),**ref})
        if item['role']=='SOURCE_PARENT_RECORDS':
            check(isinstance(body,list),'HYP003_PARENT_RECORDS_REQUIRE_NDJSON')
            for ordinal,row in enumerate(body):tables['source_parent_records.ndjson'].append({'source_sha256':ref['sha256'],'ordinal':ordinal,'row':row})
    seen=set()
    for info in primary:
        h=info['ref']['sha256'];check(h not in seen,'HYP003_DUPLICATE_PRIMARY_INPUT');seen.add(h)
        if info['manifest']['schema']==RAW:
            rows=object_value(info,'bars.ndjson');parents=object_value(info,'parent-coverage-ledger.ndjson')
            check(type(rows) is list and type(parents) is list,'HYP003_RAW_MEMBER_SCHEMA')
            for ordinal,row in enumerate(rows):tables['raw_rows.ndjson'].append({'source_manifest_sha256':h,'ordinal':ordinal,'row':row,'validation':quality(row)})
            for ordinal,row in enumerate(parents):tables['parent_relations.ndjson'].append({'source_manifest_sha256':h,'ordinal':ordinal,'row':row})
    metadata,batches=metadata_tables(sources.infos)
    tables['metadata_jobs.ndjson']=metadata;tables['transport_evidence.ndjson']=batches
    for info in sources.infos:
        tables['source_metadata.ndjson'].append({'source_manifest_sha256':info['ref']['sha256'],'member':'__manifest__','object':info['manifest']})
        for name in sorted(info['inventory']):
            if name in ('bars.ndjson','parent-coverage-ledger.ndjson','job-results.json','receipts.json','receipt.json','response.json') or name.startswith('responses/'):continue
            tables['source_metadata.ndjson'].append({'source_manifest_sha256':info['ref']['sha256'],'member':name,'object':object_value(info,name)})
    requested=set()
    for info in primary:
        if info['manifest']['schema']==RAW:
            plan=object_value(info,'source-plan.json')
            check(type(plan) is dict and type(plan.get('selected_symbols')) is list,'HYP003_RAW_PLAN_SCHEMA')
            requested.update(plan['selected_symbols'])
    duplicate=defaultdict(list)
    for record in tables['raw_rows.ndjson']:
        row=record['row'];key=(row.get('source_symbol'),row.get('reference_date'))
        if all(type(x) is str for x in key):duplicate[key].append(record)
    duplicate_groups=0
    for records in duplicate.values():
        if len(records)>1:
            duplicate_groups+=1
            hashes={digest(r['row'].get('raw_fields_exact_tokens')) for r in records}
            for record in records:
                record['validation']['reasons'].append('CONFLICTING_SOURCE_CELL' if len(hashes)>1 else 'DUPLICATE_SOURCE_CELL')
                record['validation']['status']='FIELDS_PARTIAL_OR_INVALID'
    blobs={}
    for name,rows in tables.items():
        blobs[name]=b''.join(canonical(row)+b'\n' for row in rows)
        check(len(blobs[name])<=TABLE_LIMIT,'HYP003_OUTPUT_TABLE_LIMIT')
    check(sum(map(len,blobs.values()))<=OUTPUT_LIMIT,'HYP003_OUTPUT_LIMIT')
    table_refs={name:{'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'rows':len(tables[name])} for name,raw in blobs.items()}
    versions=[{'manifest_sha256':info['ref']['sha256'],'schema':info['manifest']['schema'],'primary':info['primary'],
               'producer_status':info['manifest'].get('status'),'objects':info['inventory'],
               'parent_source_sha256':info['manifest'].get('parent_source_sha256'),
               'source_capture_content_sha256':info['manifest'].get('source_capture_content_sha256')} for info in sources.infos]
    verified_hashes={r['sha256'] for r in ancestry}|{i['ref']['sha256'] for i in sources.infos}|{v['sha256'] for i in sources.infos for v in i['inventory'].values()}
    for version in versions:
        version['reference_depth']={k:('VERIFIED_ADMITTED_OBJECT' if version[k] in verified_hashes else 'REFERENCED_ONLY') for k in ('parent_source_sha256','source_capture_content_sha256') if version[k] is not None}
    versions.sort(key=lambda r:(r['manifest_sha256'],r['primary']))
    rawrows=tables['raw_rows.ndjson'];symbols={r['row'].get('source_symbol') for r in rawrows if isinstance(r['row'].get('source_symbol'),str)}
    reason_counts=Counter(reason for r in rawrows for reason in r['validation']['reasons'])
    code={name:hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in ('hyp003_source.py','hyp003_metadata.py','hyp003_preparation.py')}
    declarations={k:config[k] for k in ('purpose','hypothesis_ref','definition_ref',*sorted(OPTIONAL-{'evidence_inputs','ancestry_objects'})) if k in config}
    report={'schema':'polar.hyp003-preparation-report/1','adapter':'polar.hyp003-partial-adapter/1','adapter_code':code,
            'declarations':declarations,'source_versions':versions,'ancestry':sorted(ancestry,key=lambda r:(r['sha256'],r['role'])),
            'tables':table_refs,'source_number_representation':'JSON_FRACTIONAL_TOKENS_AS_EXACT_STRINGS','parse_status':'SCHEMA_VALID','source_integrity':'VERIFIED_AT_DECLARED_DEPTH' if sources.infos or ancestry else 'NOT_RUN_NO_INPUTS',
            'depth':{'all_declared_members_hashed':True,'all_raw_and_parent_rows_parsed':True,'metadata_positions':{'status':'VERIFIED' if any(r['versions'] for r in metadata) else 'NOT_APPLICABLE_NO_RECEIVED_JOBS','received_jobs':sum(bool(r['versions']) for r in metadata)},
                     'unprovided_capture_envelope':'REFERENCED_ONLY','bytes_verified':sources.total-sources.physical_bytes},
            'counts':{'raw_rows':len(rawrows),'raw_source_symbols':len(symbols),'raw_requested_source_symbols':len(requested),'raw_unreceived_requested_symbols':len(requested-symbols),
                      'raw_parent_status_counts':dict(sorted(Counter(r['row'].get('raw_data_state','UNRESOLVED') for r in tables['parent_relations.ndjson']).items())),'raw_duplicate_cell_groups':duplicate_groups,
                      'raw_quality_reasons':dict(sorted(reason_counts.items())),'parent_relations':len(tables['parent_relations.ndjson']),
                      'source_parent_records':len(tables['source_parent_records.ndjson']),'metadata_jobs':len(metadata),
                      'metadata_states':dict(sorted(Counter(r['state'] for r in metadata).items())),
                      'metadata_reused_jobs':sum(any(s['reused_from_prior_capture'] for v in r['versions'] for s in v['sources']) for r in metadata),
                      'metadata_no_match_versions':sum(v['kind']=='WARNING_NO_MATCH' for r in metadata for v in r['versions']),
                      'metadata_candidates':sum(r['candidate_count'] for r in metadata),'known_receipts_minimum':len(batches),
                      'failed_unassigned_batches':sum(not r['assigned_by_length'] for r in batches),'historical_attempts_exact':None},
            'T':{'source_parent_tables':['parent_relations.ndjson','source_parent_records.ndjson'],'status':'SOURCE_FRAMES_NOT_ECONOMIC_UNIVERSE'},
            'R':{'reference':config.get('proposed_reconstruction_ref'),'status':'UNBOUND_OR_DECLARED_NOT_QUALIFIED'},
            'U':{'reference':config.get('qualified_universe_ref'),'status':'UNIVERSE_UNRESOLVED','eligible_N':None},
            'raw_data_status':'PARTIAL_DATA' if rawrows else 'ABSENT','metadata_status':'PARTIAL_DATA' if metadata else 'ABSENT',
            'identity':'UNRESOLVED','class':'UNRESOLVED','calendar':'UNRESOLVED','actions':'UNRESOLVED','coverage':'NOT_ASSESSED',
            'formation':'NOT_RUN','signal':'NOT_RUN','financial':'NOT_RUN','network_requests':0}
    check(len(canonical(report))<=MANIFEST_LIMIT,'HYP003_REPORT_LIMIT')
    report['preparation_id']='hyp003prep-'+digest(report)
    return {'report':report,'tables':blobs,'physical':{'config_sha256':digest(config),'inputs':sources.physical,
              'actual_prepared_at':datetime.now(timezone.utc).isoformat(),'python':sys.version,'adapter_code':code}}

def prepare_partial_input(config):
    try:return _prepare(config)
    except HistoryError:raise PreparationError('HYP003_UNSAFE_PATH') from None
    except (KeyError,TypeError,AttributeError,UnicodeError,RecursionError):raise PreparationError('HYP003_PRODUCER_SCHEMA') from None

def write_preparation(result,output_dir):
    root=Path(output_dir);check(root.is_absolute(),'HYP003_ABSOLUTE_OUTPUT_REQUIRED')
    check(all(not (p/'.git').exists() for p in (root,*root.parents)),'HYP003_OUTPUT_INSIDE_REPOSITORY')
    if not root.exists():safe_root(root.parent);root.mkdir(mode=0o700)
    root=safe_root(root);check(stat.S_IMODE(root.stat().st_mode)&0o077==0,'HYP003_OUTPUT_NOT_PRIVATE')
    report=result['report'];pid=report['preparation_id'];check(re.fullmatch(r'hyp003prep-[a-f0-9]{64}',pid),'HYP003_INVALID_ID')
    store=HistoryStore(root,64*1024**3);files={**result['tables'],'report.json':canonical(report)}
    check(set(result['tables'])==set(TABLES),'HYP003_OUTPUT_FILE_SET')
    aid=str(uuid.uuid4());receipt={'schema':'polar.hyp003-preparation-receipt/1','invocation_id':aid,'preparation_id':pid,**result['physical']}
    with store.locked():
        store._publish('hyp003-preparations',pid,files,file_limit=TABLE_LIMIT)
        store._publish('hyp003-preparation-receipts',aid,{'receipt.json':canonical(receipt)},file_limit=JSON_RECEIPT_LIMIT)
    return {'schema':'polar.hyp003-preparation-result/1','preparation_id':pid,'invocation_id':aid,'report':report,'financial':'NOT_RUN'}

JSON_RECEIPT_LIMIT=32*1024**2

def read_preparation(output_dir,pid):
    check(type(pid) is str and re.fullmatch(r'hyp003prep-[a-f0-9]{64}',pid),'HYP003_INVALID_ID')
    root=safe_root(output_dir);prefix='hyp003-preparations/'+pid
    raw=read_file(root,prefix+'/report.json',limit=MANIFEST_LIMIT);report=decode(raw)
    expected={k:v for k,v in report.items() if k!='preparation_id'}
    check(report.get('schema')=='polar.hyp003-preparation-report/1' and report.get('preparation_id')==pid and pid=='hyp003prep-'+digest(expected),'HYP003_REPORT_IDENTITY')
    check({p.name for p in (root/prefix).iterdir()}==set(TABLES)|{'report.json'} and set(report['tables'])==set(TABLES),'HYP003_OUTPUT_FILE_SET')
    total=0
    for name,ref in report['tables'].items():
        hasher=hashlib.sha256();size=0
        with member_stream(root,prefix+'/'+name,TABLE_LIMIT) as stream:
            while data:=stream.read(1024**2):hasher.update(data);size+=len(data)
        total+=size;check(total<=OUTPUT_LIMIT and size==ref['bytes'] and hasher.hexdigest()==ref['sha256'],'HYP003_OUTPUT_HASH')
    return report

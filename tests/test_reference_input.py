"""Public invented source graph: no retained vendor rows, feature/model/native calls."""
from copy import deepcopy
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import subprocess
import os

import pytest
from polar.history_bundle import canonical
from polar.import_adjusted_sip import source_row
from polar.reference_input import prepare_input, preflight_input, INVENTED
from polar.research_reference import load_reference


def sha(raw): return hashlib.sha256(raw).hexdigest()


def put(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not isinstance(raw, bytes): raw = canonical(raw)
    path.write_bytes(raw)
    return {'path': str(path), 'sha256': sha(raw), 'bytes': len(raw)}


def fixture(tmp_path, mutate=None, *, selected_unit_value=None, selected_plan_id=None):
    root = tmp_path.resolve(); source = root/'source'; store = root/'store'; store.mkdir()
    days = ['2024-01-31', '2024-02-01', '2024-02-02']; aliases = ['AAA', 'BBB', 'CCC']
    request = lambda s: {'symbols': s, 'adjustment': 'all', 'start': days[0]+'T00:00:00Z', 'end': '2024-02-03T00:00:00Z'}
    parents = {s: {'job_id': 'plan-'+s, 'request': request(s), 'source_records': [{'population_record_id': 'listing-'+s}],
                   'source_record_ids': ['listing-'+s], 'frozen_alias_ordinal': i,
                   'population_record_id': None, 'economic_identity_admission': 'NOT_ISSUED'} for i,s in enumerate(aliases)}
    source_plan_id=selected_plan_id or 'INVENTED-PLAN'
    if selected_unit_value is not None:
        parents={j['request']['symbols']:j for j in selected_unit_value['jobs']}
        aliases=sorted(parents)
        request=lambda symbol:parents[symbol]['request']
    active=aliases if selected_unit_value is not None else aliases[:2]
    source_plan_jobs={s:parents[s]['job_id'] for s in aliases}
    originals = {s: {'bars': {s: [{'c': '1.234567' if s=='AAA' else '20.1', 't': d+'T00:00:00Z'} for d in days]}}
                 for s in active}
    rows = {}
    for s in active:
        rows[s] = []
        for i,d in enumerate(days):
            page = 0 if i == 0 else 1
            raw = canonical({'bars': {s: originals[s]['bars'][s][:1] if page == 0 else originals[s]['bars'][s][1:]}})
            raw_file = 'objects/'+sha(raw)+'.json'
            token = originals[s]['bars'][s][i]['c']
            row = source_row({'query_symbol': s, 'source_symbol': s, 'reference_date': d,
                'raw_fields_exact_tokens': originals[s]['bars'][s][i],
                **{'raw_'+f: token for f in ['open','high','low','close','volume']},
                'parent_relation': parents[s], 'observed_published_at': None,
                'observed_historical_available_at': None,
                'source_reference': {'raw_file': raw_file,'source_body_sha256': sha(raw),'source_array': 'bars/'+s,
                    'source_row_ordinal': 0 if page == 0 else i-1, 'job_id': 'canonical-'+s,
                    'request_id': 'request-'+s+'-'+str(page), 'page': page}})
            if mutate: mutate(s,i,row)
            rows[s].append(canonical(row)+b'\n')
    records = [{'literal_alias':s,'source_records':parents[s]['source_records'],
        'source_record_ids':parents[s]['source_record_ids'],'eligible_for_C':s!='CCC',
        'canonical_job_id':'canonical-'+s,'source_plan_job_id':source_plan_jobs[s],'request':request(s),
        'segments':[], 'source_flags':{'missingness':'INVENTED_EXCLUDED' if s=='CCC' else 'COMPLETE'}} for s in aliases]
    objects = {}; packets = []
    for part in [0,1]:
        rel = f'parts/{part:05d}/'; directory=source/rel; members = {}
        lines = b''.join(rows[s][0] if part==0 else b''.join(rows[s][1:]) for s in active)
        m = put(directory/'bars.ndjson', lines); members['bars.ndjson']={k:m[k] for k in ['sha256','bytes']}
        cover = b''.join(canonical({**parents[s], 'canonical_job_id':'canonical-'+s,'global_job_ordinal':i,
            'this_batch':'success','this_batch_reason':None,'raw_data_state':'RECEIVED_COMPLETE',
            'raw_coverage_ref':'canonical-'+s})+b'\n' for i,s in enumerate(aliases))
        m=put(directory/'parent-coverage-ledger.ndjson',cover);members['parent-coverage-ledger.ndjson']={k:m[k] for k in ['sha256','bytes']}
        for s in active:
            raw=canonical({'bars': {s: originals[s]['bars'][s][:1] if part == 0 else originals[s]['bars'][s][1:]}})
            name='objects/'+sha(raw)+'.json';m=put(directory/name,raw);members[name]={k:m[k] for k in ['sha256','bytes']}
        partition={'schema':'polar.vendor-all-adjusted-source-content/1','source_plan_id':source_plan_id,'objects':members}
        pin=put(directory/'content-manifest.json',partition)
        for key,v in members.items():objects[rel+key]=v
        objects[rel+'content-manifest.json']={k:pin[k] for k in ['sha256','bytes']}
        packets.append({'manifest':rel+'content-manifest.json',**{k:pin[k] for k in ['sha256','bytes']}})
        for n,s in enumerate(active):
            records[n]['segments'].append({'partition_manifest':str(directory/'content-manifest.json'),
                'partition_manifest_sha256':pin['sha256'],'normalized_member':str(directory/'bars.ndjson'),
                'normalized_member_sha256':members['bars.ndjson']['sha256'],
                'member_first_line_1based':n*(1 if part==0 else 2)+1,
                'rows':1 if part==0 else 2,'first_job_row_0based':0 if part==0 else 1})
    collection=put(source/'content-manifest.json',{'schema':'polar.vendor-all-adjusted-source-collection/1',
        'source_plan_id':source_plan_id,'objects':objects,'packets':packets,
        'rights':'INVENTED_PUBLIC_TEST','provenance':{'kind':'DETERMINISTIC_INVENTED_FIXTURE'}})
    all_days=['2024-01-30']+days
    schedule=put(root/'schedule.json',{'schema':'polar.xnys-reference-schedule/1','time_status':'MODELED_NOT_OBSERVED',
        'rows':[{'date':d,'reference_open_utc':d+'T14:30:00+00:00','reference_close_utc':d+'T21:00:00+00:00',
            'reference_open_ny':d+'T09:30:00-05:00','reference_close_ny':d+'T16:00:00-05:00',
            'early_close_reference':False,'observed_open_at':None,'observed_close_at':None,
            'clock_status':'MODELED_NOT_OBSERVED','next_reference_date':all_days[i+1] if i+1<len(all_days) else None,
            'month_end_in_reference_range':False if i+1<len(all_days) else None} for i,d in enumerate(all_days)]})
    binding=put(root/'binding.json',{'schema':'polar.C-source-consumer-metadata-binding/1','source_collection':collection,
        'source_plan_id':source_plan_id,'portfolio_symbol_order':active,'records':records,'rights':'INVENTED_PUBLIC_TEST',
        'provenance':{'kind':'DETERMINISTIC_INVENTED_FIXTURE'}})
    contract=put(root/'definition.json',{'clock_binding':{'schedule':schedule}})
    ledger=put(root/'ledger.json',{'eligible_aliases_fixed_order':active,'all_records':records})
    packet=put(root/'packet.json',{'schema':'polar.prospective-definition-packet/1','contract':contract,'eligibility_ledger':ledger})
    cfg={'schema':'polar.reference-input-conversion-config/1','profile_id':INVENTED,'binding':binding,
         'definition_packet':packet,'schedule':schedule,'date_range':{'start':days[0],'end':days[-1],'count':3}}
    return store,cfg,records,rows


def test_projection_preserves_original_token_all_relations_clocks_and_date_major_order(tmp_path):
    store,cfg,records,rows=fixture(tmp_path);result=prepare_input(cfg,store,10**8)
    manifest=json.loads(Path(result['input_ref']['path']).read_text());quotes=[json.loads(v) for v in Path(manifest['quotes']['path']).read_bytes().splitlines()]
    assert [(q['date'],q['symbol']) for q in quotes]==[(d,s) for d in ['2024-01-31','2024-02-01','2024-02-02'] for s in ['AAA','BBB']]
    assert quotes[0]['reference_quote']=='1.234567' and quotes[0]['source_adjusted_close_token']=='1.234567'
    assert quotes[1]['reference_quote']=='20.100000' and quotes[1]['source_adjusted_close_token']=='20.1'
    assert quotes[0]['source_ref']['line_sha256']==sha(rows['AAA'][0])
    assert quotes[0]['source_ref']['line_sha256']!=sha(rows['AAA'][0].rstrip(b'\n'))
    assert quotes[0]['source_ref']['original_source_reference']['source_row_ordinal']==0
    assert quotes[0]['source_ref']['original_source_reference']['page']==0
    assert quotes[2]['source_ref']['original_source_reference']['page']==1
    assert quotes[2]['source_ref']['original_source_reference']['source_row_ordinal']==0
    assert quotes[0]['source_ref']['original_source_reference']['source_array']=='bars/AAA'
    assert all(q['observed_published_at'] is None and q['observed_historical_available_at'] is None for q in quotes)
    relations=json.loads(Path(manifest['source_relations']['path']).read_text())
    assert relations['records']==records and len(relations['parent_relations'])==3
    assert relations['records'][2]['source_flags']=={'missingness':'INVENTED_EXCLUDED'}
    projected=json.loads(Path(manifest['schedule']['path']).read_text())['rows']
    assert len(projected)==3 and projected[0]['month_end_in_reference_range'] is True
    assert projected[-1]['next_reference_date'] is None and projected[-1]['month_end_in_reference_range'] is None
    assert projected[0]['reference_close_ny']=='2024-01-31T16:00:00-05:00' and projected[0]['observed_close_at'] is None
    market=load_reference(result['input_ref']);assert market['quote_basis']=='VENDOR_ALL_ADJUSTED_REFERENCE_CLOSE'
    assert market['prices_micro']['2024-01-31']=={'AAA':1234567,'BBB':20100000}
    assert preflight_input(result['input_ref'])['strategy_execution']=='NOT_RUN'
    assert prepare_input(cfg,store,10**8)==result  # immutable repeat, no second conversion revision


@pytest.mark.parametrize('mutation,error',[
    (lambda s,i,r:r.update(vendor_adjusted_close='9') if s=='AAA' and i==0 else None,'REFERENCE_ADJUSTED_TOKEN_MISMATCH'),
    (lambda s,i,r:r['source_fields_exact_tokens'].update(c='1.1234567') or r.update(vendor_adjusted_close='1.1234567') if s=='AAA' and i==0 else None,'LOSSLESS_6DP_REQUIRED'),
    (lambda s,i,r:r.update(reference_date='2024-01-31') if s=='AAA' and i==1 else None,'REFERENCE_SOURCE_ROW_BINDING'),
    (lambda s,i,r:r.update(source_symbol='WRONG') if s=='AAA' and i==0 else None,'REFERENCE_NORMALIZED_ROW_IDENTITY'),
    (lambda s,i,r:r['source_reference'].update(source_body_sha256='0'*64) if s=='AAA' and i==0 else None,'REFERENCE_SOURCE_BODY_BINDING'),
    (lambda s,i,r:r['source_reference'].update(source_row_ordinal=999) if s=='AAA' and i==0 else None,'REFERENCE_SOURCE_ROW_BINDING'),
    (lambda s,i,r:r['source_reference'].update(page=-1) if s=='AAA' and i==0 else None,'REFERENCE_ORIGINAL_SOURCE_POINTER'),
    (lambda s,i,r:r['source_reference'].update(page=True) if s=='AAA' and i==0 else None,'REFERENCE_ORIGINAL_SOURCE_POINTER'),
    (lambda s,i,r:r['source_reference'].update(page='0') if s=='AAA' and i==0 else None,'REFERENCE_ORIGINAL_SOURCE_POINTER'),
    (lambda s,i,r:r['source_reference'].update(page=2) if s=='AAA' and i==0 else None,'REFERENCE_ORIGINAL_SOURCE_POINTER'),
    (lambda s,i,r:r['parent_relation'].update(job_id='wrong') if s=='AAA' and i==0 else None,'REFERENCE_PARENT_BINDING'),
])
def test_rejects_actual_loss_or_conflict_without_publishing(tmp_path,mutation,error):
    store,cfg,_,_=fixture(tmp_path,mutation)
    with pytest.raises(ValueError,match=error):prepare_input(cfg,store,10**8)
    assert not (store/'reference-inputs').exists()


def test_missing_segment_and_corrupt_member_fail_closed(tmp_path):
    store,cfg,_,_=fixture(tmp_path)
    b=json.loads(Path(cfg['binding']['path']).read_text());b['records'][0]['segments'].pop();cfg['binding']=put(Path(cfg['binding']['path']),b)
    with pytest.raises(ValueError,match='REFERENCE_ELIGIBLE_GRID_MISSING'):prepare_input(cfg,store,10**8)


def test_normalized_member_hash_not_replaced_by_declared_metadata(tmp_path):
    store,cfg,records,_=fixture(tmp_path)
    member=Path(records[0]['segments'][0]['normalized_member']);member.write_bytes(member.read_bytes().replace(b'1.234567',b'1.234568'))
    with pytest.raises(ValueError,match='REFERENCE_FILE_HASH'):prepare_input(cfg,store,10**8)
    assert not (store/'reference-inputs').exists()


def test_file_hash_corruption_and_immutable_collision(tmp_path):
    store,cfg,_,_=fixture(tmp_path);result=prepare_input(cfg,store,10**8)
    p=Path(result['input_ref']['path']);p.chmod(0o600);p.write_bytes(p.read_bytes().replace(b'VENDOR_ALL', b'XENDOR_ALL', 1))
    with pytest.raises(ValueError,match='REFERENCE_FILE_HASH'):load_reference(result['input_ref'])
    with pytest.raises(ValueError,match='HISTORY_IMMUTABLE_CONFLICT'):prepare_input(cfg,store,10**8)


def test_file_only_service_and_cli_without_database_credential(tmp_path,monkeypatch):
    store,cfg,_,_=fixture(tmp_path);monkeypatch.setenv('POLAR_ARTIFACT_ROOT',str(store));monkeypatch.setenv('POLAR_DB_PASSWORD_FILE','/does/not/exist')
    from polar.config import Settings
    from polar.service import Service
    result=Service(Settings.load_artifacts()).research_input_prepare(cfg)
    pinfile=tmp_path/'manifest-pin.json';pinfile.write_bytes(canonical(result['input_ref']))
    run=subprocess.run(['python','-B','-m','polar.cli','research-input-preflight',str(pinfile)],capture_output=True,text=True)
    assert run.returncode==0,run.stderr
    assert json.loads(run.stdout)['status']=='STRUCTURALLY_VALID_SOURCE_ONLY'


def test_invalid_calendar_does_not_publish_a_revision(tmp_path):
    store,cfg,_,_=fixture(tmp_path)
    schedule=json.loads(Path(cfg['schedule']['path']).read_text())
    schedule['rows'][1]['reference_close_utc']='2024-01-31T12:00:00+00:00'
    cfg['schedule']=put(Path(cfg['schedule']['path']),schedule)
    packet=json.loads(Path(cfg['definition_packet']['path']).read_text())
    definition=json.loads(Path(packet['contract']['path']).read_text())
    definition['clock_binding']['schedule']=cfg['schedule']
    packet['contract']=put(Path(packet['contract']['path']),definition)
    cfg['definition_packet']=put(Path(cfg['definition_packet']['path']),packet)
    with pytest.raises(ValueError,match='REFERENCE_SESSION_CLOCK'):prepare_input(cfg,store,10**8)
    assert not (store/'reference-inputs').exists()


@pytest.mark.parametrize('field,value',[('rights','PRIVATE_RESEARCH'),('provenance',{}),('provenance',{'kind':'RETAINED_SOURCE'})])
def test_invented_profile_never_relabels_retained_source_as_public(tmp_path,field,value):
    store,cfg,_,_=fixture(tmp_path);binding=json.loads(Path(cfg['binding']['path']).read_text())
    binding[field]=value;cfg['binding']=put(Path(cfg['binding']['path']),binding)
    # Remove normalized payloads: the positive-rights rejection must precede numeric reads.
    for path in (tmp_path/'source').rglob('bars.ndjson'):path.unlink()
    with pytest.raises(ValueError,match='REFERENCE_INVENTED_POSITIVE_PROVENANCE_REQUIRED'):prepare_input(cfg,store,10**8)
    assert not (store/'reference-inputs').exists()

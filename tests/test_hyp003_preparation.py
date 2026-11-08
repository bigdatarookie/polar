"""Frozen tiny producer controls; zero provider/financial/native learner calls."""
from copy import deepcopy
from datetime import datetime,timezone
from decimal import getcontext,setcontext
import hashlib
import json
from pathlib import Path

import pytest
from polar.codec import canonical
from polar.hyp003_source import PreparationError,RAW,METADATA,decode
from polar.hyp003_preparation import prepare_partial_input,write_preparation,read_preparation


def h(raw):return hashlib.sha256(raw).hexdigest()
def write(p,value,ndjson=False):
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_bytes(b''.join(canonical(v)+b'\n' for v in value) if ndjson else canonical(value))
    return p

def envelope(root,schema,files):
    refs={}
    for name,value in files.items():
        p=write(root/name,value,name.endswith('.ndjson'));refs[name]={'sha256':h(p.read_bytes()),'bytes':p.stat().st_size}
    p=write(root/'content-manifest.json',{'schema':schema,'objects':refs,'status':'PARTIAL_STOP_INVENTED'})
    return {'adapter':schema,'directory':str(root.resolve()),'manifest_sha256':h(p.read_bytes())}

def metadata(root,responses=None,symbols=('A','B'),context=None):
    context=context or {'idType':'TICKER','exchCode':'US','includeUnlistedEquities':True}
    requests=[{**context,'idValue':s} for s in symbols]
    if responses is None:responses=[{'data':[{'figi':'INVENTED1'},{'figi':'INVENTED2'}]},{'warning':'No identifier found.'}]
    body=canonical(responses);wire=canonical(requests)+b'\n'
    receipt={'batch_ordinal':0,'request_body':requests,'request_sha256':h(wire),'response_sha256':h(body),
             'response_bytes':len(body),'http_status':200,'started_at':'2026-11-08T00:00:00Z','completed_at':'2026-11-08T00:00:01Z'}
    entries={s:{'source':'responses/batch-0000.json','source_sha256':h(body),'job_ordinal':i,
                'capture_root':str(root.resolve()),'response':responses[i]} for i,s in enumerate(symbols)} if len(responses)==len(symbols) else {}
    return envelope(root,METADATA,{'plan.json':{'request_context':context},'selected-symbols.json':list(symbols),
                    'job-results.json':entries,'receipts.json':[receipt],'responses/batch-0000.json':responses,'failure.json':{'reason':'INVENTED_STOP'}})

def row(s='A',day='2020-01-02',o='1.000000000000000001',c='2.00',v='0'):
    return {'source_symbol':s,'reference_date':day,'raw_open':o,'raw_close':c,'raw_volume':v,
            'raw_fields_exact_tokens':{'o':o,'c':c,'v':v,'h':'2.00','l':'1.00'},'adjustment':'raw',
            'feed':'sip','currency':'USD_REQUEST_CONTRACT','estimated_K':'2020-01-06T05:00:00Z',
            'K_label':'ESTIMATED_NOT_PROVIDER_SLA','observed_published_at':None,'observed_historical_available_at':None}

def raw(root,rows=None):
    rows=[row(),row('B')] if rows is None else rows
    return envelope(root,RAW,{'bars.ndjson':rows,'parent-coverage-ledger.ndjson':[
        {'dated_source_record_id':'P1','literal_symbol':'A','raw_data_state':'RECEIVED'},
        {'dated_source_record_id':'P2','literal_symbol':'A','raw_data_state':'OUTSIDE'},
        {'dated_source_record_id':'P3','literal_symbol':'C','raw_data_state':'UNRECEIVED'}],
        'source-plan.json':{'selected_symbols':['A','B','C'],'class_projection_sha256':'1'*64},'quality.json':{'scope':'INVENTED_PARTIAL'}})

def config(*refs):
    return {'schema':'polar.hyp003-preparation-config/1','adapter_version':1,'purpose':'DEVELOPMENT',
            'hypothesis_ref':'HYP003','definition_ref':'1'*64,'inputs':list(refs)}

def rows(result,name):return [json.loads(line) for line in result['tables'][name].splitlines()]

def test_metadata_only_preserves_multiple_candidates_and_full_parents(tmp_path):
    ref=metadata(tmp_path/'metadata');p=write(tmp_path/'parents.ndjson',[{'id':'P1','symbol':'A'},{'id':'P2','symbol':'A'},{'id':'P3','symbol':'B'}],True)
    cfg=config(ref);cfg['ancestry_objects']=[{'directory':str(tmp_path.resolve()),'path':p.name,'sha256':h(p.read_bytes()),'role':'SOURCE_PARENT_RECORDS'}]
    result=prepare_partial_input(cfg);report=result['report'];counts=report['counts']
    assert (counts['source_parent_records'],counts['metadata_jobs'],counts['metadata_candidates'],counts['metadata_no_match_versions'])==(3,2,2,1)
    assert report['raw_data_status']=='ABSENT' and report['U']['eligible_N'] is None and report['financial']=='NOT_RUN'
    assert len(rows(result,'source_parent_records.ndjson'))==3

def test_partial_raw_exact_zero_and_clocks(tmp_path):
    result=prepare_partial_input(config(raw(tmp_path/'raw')));report=result['report'];r=rows(result,'raw_rows.ndjson')[0]['row']
    assert r['raw_open']=='1.000000000000000001' and r['raw_close']=='2.00' and r['raw_volume']=='0'
    assert r['observed_published_at'] is None and r['estimated_K']=='2020-01-06T05:00:00Z'
    assert report['counts']['raw_rows']==2 and report['counts']['raw_unreceived_requested_symbols']==1
    assert report['counts']['parent_relations']==3 and report['R']['reference'] is None and report['U']['eligible_N'] is None

def test_invalid_rows_stay_named_and_do_not_change_with_decimal_context(tmp_path):
    bad=row(day='invalid-date',c=None,v='-1');bad['volume_basis']='split-adjusted';bad['raw_open']='NaN'
    cfg=config(raw(tmp_path/'raw',[bad]));first=prepare_partial_input(cfg)
    r=rows(first,'raw_rows.ndjson')[0]
    assert {'RAW_OPEN_INVALID','RAW_CLOSE_MISSING','RAW_VOLUME_INVALID','RAW_VOLUME_BASIS_UNQUALIFIED','REFERENCE_DATE_INVALID'}<=set(r['validation']['reasons'])
    assert r['row']['raw_close'] is None and r['row']['raw_volume']=='-1'
    ctx=getcontext().copy()
    try:
        getcontext().prec=2;assert prepare_partial_input(cfg)['report']==first['report']
    finally:setcontext(ctx)

def test_duplicate_success_alias_and_conflicting_versions_not_selected(tmp_path):
    a=metadata(tmp_path/'a');b=metadata(tmp_path/'b')
    duplicate=prepare_partial_input(config(a,b));jobs=rows(duplicate,'metadata_jobs.ndjson')
    assert len(jobs)==2 and all(len(j['versions'])==1 for j in jobs)
    assert all(len(j['versions'][0]['sources'])==2 for j in jobs)
    c=metadata(tmp_path/'c',[{'data':[{'figi':'DIFFERENT'}]},{'warning':'No identifier found.'}])
    conflicting=rows(prepare_partial_input(config(a,c)),'metadata_jobs.ndjson')
    changed=next(j for j in conflicting if j['identity']['request']['idValue']=='A')
    assert changed['state']=='CONFLICTING_SUCCESS' and len(changed['versions'])==2 and changed['economic_id_selection'] is None

def test_different_request_contexts_are_not_ticker_merged(tmp_path):
    a=metadata(tmp_path/'a');context={'idType':'TICKER','exchCode':'US','includeUnlistedEquities':True,'asof':'2020-01-01'}
    b=metadata(tmp_path/'b',context=context)
    assert prepare_partial_input(config(a,b))['report']['counts']['metadata_jobs']==4

def test_generic_failed_batch_remains_unassigned_and_later_singleton_scoped(tmp_path):
    failed=metadata(tmp_path/'failed',[{'error':'INVENTED_GENERIC_ERROR'}])
    later=metadata(tmp_path/'later',[{'data':[{'figi':'INVENTED'}]}],symbols=('A',))
    result=prepare_partial_input(config(failed,later));report=result['report']
    assert report['counts']['failed_unassigned_batches']==1
    jobs=rows(result,'metadata_jobs.ndjson');a=next(j for j in jobs if j['identity']['request']['idValue']=='A');b=next(j for j in jobs if j['identity']['request']['idValue']=='B')
    assert a['state']=='RECEIVED' and b['state']=='UNRECEIVED' and b['versions']==[]

def test_receipts_change_physical_identity_only_and_repeat_is_immutable(tmp_path):
    ref=raw(tmp_path/'input');receipt=write(tmp_path/'input'/'receipt.json',{'actual_received_at':'2026-11-08T00:00:00Z'})
    ref['receipt']={'path':'receipt.json','sha256':h(receipt.read_bytes())}
    first=prepare_partial_input(config(ref));out=tmp_path/'output';one=write_preparation(first,out.resolve())
    write(receipt,{'actual_received_at':'2026-11-08T00:00:01Z','extra':'different-length'})
    ref['receipt']['sha256']=h(receipt.read_bytes());second=prepare_partial_input(config(ref))
    assert first['report']==second['report'] and first['physical']!=second['physical']
    two=write_preparation(second,out.resolve());assert one['preparation_id']==two['preparation_id'] and one['invocation_id']!=two['invocation_id']
    assert read_preparation(out.resolve(),one['preparation_id'])==first['report']

@pytest.mark.parametrize('bad',['hash','length','schema','duplicate','depth','symlink','traversal'])
def test_integrity_failures_have_no_success_artifact(tmp_path,bad):
    ref=raw(tmp_path/'raw');root=Path(ref['directory']);manifest=root/'content-manifest.json';m=json.loads(manifest.read_text())
    if bad=='hash':(root/'quality.json').write_bytes(b'{}')
    elif bad=='length':m['objects']['quality.json']['bytes']+=1
    elif bad=='schema':m['schema']='unsupported'
    elif bad=='duplicate':
        b=b'{"a":1,"a":2}';(root/'quality.json').write_bytes(b);m['objects']['quality.json']={'bytes':len(b),'sha256':h(b)}
    elif bad=='depth':
        b=('['*66+'0'+']'*66).encode();(root/'quality.json').write_bytes(b);m['objects']['quality.json']={'bytes':len(b),'sha256':h(b)}
    elif bad=='symlink':
        outside=write(tmp_path/'outside.json',{});(root/'quality.json').unlink();(root/'quality.json').symlink_to(outside)
    else:m['objects']['../outside.json']={'bytes':2,'sha256':h(b'{}')}
    if bad!='hash':manifest.write_bytes(canonical(m));ref['manifest_sha256']=h(manifest.read_bytes())
    with pytest.raises(PreparationError):prepare_partial_input(config(ref))
    assert not (tmp_path/'output').exists()

def test_cli_dispatch_precedes_settings_and_db(tmp_path,monkeypatch,capsys):
    from polar.cli import main
    from polar.config import Settings
    monkeypatch.setattr(Settings,'load',classmethod(lambda cls:(_ for _ in ()).throw(AssertionError('DB_OR_SECRET_LOAD_FORBIDDEN'))))
    p=write(tmp_path/'config.json',config(raw(tmp_path/'input')));out=tmp_path/'output'
    main(['hyp003-prepare',str(p),'--output-dir',str(out.resolve())]);result=json.loads(capsys.readouterr().out)
    main(['hyp003-preparation-report',result['preparation_id'],'--output-dir',str(out.resolve())]);r=json.loads(capsys.readouterr().out)
    assert r['preparation_id']==result['preparation_id'] and r['financial']=='NOT_RUN'


@pytest.mark.parametrize('tokens,different',[(False,True),(True,True),(False,False),(True,False)])
def test_raw_cell_classification_preserves_supplied_values(tmp_path,tokens,different):
    first=row(c='1.5000');second=row(c='1.5001' if different else '1.5000')
    if not tokens:
        first.pop('raw_fields_exact_tokens');second.pop('raw_fields_exact_tokens')
    originals=deepcopy([first,second])
    result=prepare_partial_input(config(raw(tmp_path/'raw',[first,second])))
    actual=rows(result,'raw_rows.ndjson')
    expected='CONFLICTING_SOURCE_CELL' if different else 'DUPLICATE_SOURCE_CELL'
    other='DUPLICATE_SOURCE_CELL' if different else 'CONFLICTING_SOURCE_CELL'
    assert [r['row'] for r in actual]==originals and [first,second]==originals
    assert all(expected in r['validation']['reasons'] and other not in r['validation']['reasons'] for r in actual)


def test_raw_cell_direct_difference_not_hidden_by_identical_token_map(tmp_path):
    first=row(c='1.5000');second=deepcopy(first);second['raw_close']='1.5001'
    originals=deepcopy([first,second])
    actual=rows(prepare_partial_input(config(raw(tmp_path/'raw',[first,second]))),'raw_rows.ndjson')
    assert [r['row'] for r in actual]==originals
    assert all('CONFLICTING_SOURCE_CELL' in r['validation']['reasons'] and
               'DUPLICATE_SOURCE_CELL' not in r['validation']['reasons'] for r in actual)

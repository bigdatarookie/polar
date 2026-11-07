"""Frozen original literals and deterministic/physical identity separation, invented sessions only."""
import copy
import json
import uuid
from datetime import date,timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from polar.api import create_app
from polar.config import Settings
from polar.descriptive import compile_files, configuration
from polar.descriptive_service import DescriptiveService
from polar.descriptive_store import DescriptiveStore
from polar.history_bundle import BASES, HistoryError, canonical, decode, sha
from polar.history_queries import HistoryQueries
from polar.service import Service

REV='histrev-'+'1'*64


class Retained:
    def __init__(self,root):
        self.store=SimpleNamespace(root=root,limit=64*1024**3)
        self.sessions=[(date(2024,1,1)+timedelta(days=i)).isoformat() for i in range(30)]
        self.sources={k:[{'session_date':s,'close':v} for s in self.sessions] for k,v in [('a','10.00'),('b','100')]}
        self.summary={'dataset_id':'invented','dataset_revision':REV,'import_receipt_id':'2'*64,'manifest_sha256':'3'*64,
            'basis':dict(BASES),'fitness':{'rights_status':'ADMITTED'},'instruments':[{'instrument_id':k,'currency':'USD'} for k in self.sources]}
    def load_revision(self,dataset,revision):
        assert dataset=='invented' and revision==REV
        return copy.deepcopy(self.summary),SimpleNamespace(files={'bars/'+k+'.ndjson':b''.join(canonical(r)+b'\n' for r in rows)
                                                                 for k,rows in self.sources.items()})
    def config(self,**updates):
        return {'dataset_id':'invented','dataset_revision':REV,'import_receipt_id':'2'*64,'manifest_sha256':'3'*64,
                'instrument_ids':['a'],'benchmark_instrument_id':'b','start':self.sessions[0],
                'end':(date(2024,1,1)+timedelta(days=30)).isoformat(),**updates}
    def calendar(self):
        return {'status':'QUALIFIED_REFERENCE_DATES_ONLY','calendar_sha256':'4'*64,'binding_sha256':'5'*64,
                'scope':'COMMON_US_EQUITY_REFERENCE','close_utc':'UNRESOLVED','listing_PIT':'UNQUALIFIED'}
    def compile(self,**updates):
        summary,bundle=self.load_revision('invented',REV)
        return compile_files(configuration(self.config(**updates)),summary,bundle,self.sessions,self.calendar())


@pytest.fixture
def retained(tmp_path):return Retained(tmp_path)


def rows(values,name):return [decode(line) for line in values[name+'.ndjson'].splitlines()]


def test_original_flat30_population_counts_and_observed_zero(retained):
    _,values=retained.compile()
    counts=decode(values['counts.json'])['assets']['a']
    assert {k:v for k,v in counts.items() if k!='reason_counts'}=={
        'candidate_expected':30,'observed_candidate':30,'feature_valid':11,'target_valid':25,
        'paired_valid':6,'unique_excluded':24,'reference_valid':30}
    features,labels=rows(values,'features'),rows(values,'labels')
    assert features[18]['value'] is None and features[18]['reasons']==['WARMUP']
    assert features[19]['value']=='0' and features[19]['status']=='VALID'
    assert labels[24]['value']=='0' and labels[25]['reasons']==['TAIL_ENDPOINT_UNAVAILABLE']
    assert labels[25]['target_session'] is None
    assert all(r['asset_value']=='1E+2' for r in rows(values,'reference'))
    assert counts['candidate_expected']==counts['paired_valid']+counts['unique_excluded']


def test_window_does_not_redefine_revision_tail_or_seed(retained):
    _,full=retained.compile()
    _,narrow=retained.compile(start=retained.sessions[20],end=retained.sessions[22])
    labels=rows(narrow,'labels')
    assert [r['target_session'] for r in labels]==retained.sessions[25:27]
    assert all(r['status']=='VALID' for r in labels)
    assert rows(narrow,'features')==rows(full,'features')[20:22]
    assert rows(narrow,'reference')==rows(full,'reference')[20:22]


@pytest.mark.parametrize('invalid',[False,True])
def test_every_interior_session_required_and_overlapping_masks(retained,invalid):
    if invalid:retained.sources['a'][22]['close']='0'
    else:del retained.sources['a'][22]
    _,values=retained.compile();counts=decode(values['counts.json'])['assets']['a']
    assert counts['candidate_expected']==30 and counts['observed_candidate']==(30 if invalid else 29)
    assert (counts['feature_valid'],counts['target_valid'],counts['paired_valid'],counts['reference_valid'])==(3,19,0,29)
    labels=rows(values,'labels');prefix='INVALID_' if invalid else 'MISSING_'
    assert labels[17]['reasons']==[prefix+'ENDPOINT']
    assert labels[19]['reasons']==[prefix+'INTERIOR']
    assert labels[22]['reasons']==[prefix+'START']
    assert sum(counts['reason_counts']['feature'].values())+sum(counts['reason_counts']['label'].values())>counts['unique_excluded']


def test_reference_mask_not_filtered_to_paired_cohort_and_no_rebase(retained):
    del retained.sources['b'][0]
    del retained.sources['b'][9]  # original session10 after removal
    _,values=retained.compile(start=retained.sessions[20],end=retained.sessions[28])
    meta=decode(values['reference-metadata.json'])['assets']['a']
    assert meta['anchor_session']==retained.sessions[1]
    assert len(rows(values,'reference'))==8
    assert decode(values['counts.json'])['assets']['a']['reference_valid']==8
    assert decode(values['counts.json'])['assets']['a']['paired_valid']==5


def test_same_content_different_selected_receipt_changes_ids(retained):
    original,files1=retained.compile()
    retained.summary['import_receipt_id']='9'*64
    changed,files2=retained.compile(import_receipt_id='9'*64)
    assert changed!=original and files2['features.ndjson']==files1['features.ndjson']
    assert decode(files2['feature-view.json'])['view_id']!=decode(files1['feature-view.json'])['view_id']


def test_config_mismatch_and_calendar_unresolved_refuse(retained):
    summary,bundle=retained.load_revision('invented',REV)
    with pytest.raises(HistoryError,match='DESCRIPTIVE_CALENDAR_UNRESOLVED'):
        compile_files(configuration(retained.config()),summary,bundle,None,{'status':'UNRESOLVED_GAPS'})
    with pytest.raises(HistoryError,match='DESCRIPTIVE_INPUT_IDENTITY'):
        retained.compile(manifest_sha256='9'*64)


@pytest.fixture
def operation(retained,monkeypatch):
    monkeypatch.setattr('polar.descriptive_service.reference_calendar',lambda *args:(retained.sessions,retained.calendar()))
    return DescriptiveService(retained,retained.store.root/'unused-calendar')


def test_identical_replay_matches_all_semantic_bytes_distinct_attempts(operation,retained):
    first=operation.run(retained.config());assert first['status']=='COMPLETED',first
    one=operation.store.verify(first['experiment_id'])
    second=operation.run(retained.config());assert second['status']=='COMPLETED'
    assert first['experiment_id']==second['experiment_id'] and first['manifest_sha256']==second['manifest_sha256']
    assert first['attempt_id']!=second['attempt_id'] and first['receipt_sha256']!=second['receipt_sha256']
    assert operation.store.verify(second['experiment_id'])==one
    a,b=(operation.store.attempt(x['attempt_id']) for x in (first,second))
    assert a['started']['started_at']!=b['started']['started_at']
    assert a['receipt']['completed_at']!=b['receipt']['completed_at']


def test_failed_interrupted_and_unfinalized_attempts_retained(operation,retained,monkeypatch):
    monkeypatch.setattr('polar.descriptive_service.reference_calendar',lambda *args:(None,{'status':'UNRESOLVED_GAPS'}))
    failed=operation.run(retained.config());assert failed['status']=='FAILED' and failed['code']=='DESCRIPTIVE_CALENDAR_UNRESOLVED'
    assert operation.store.attempt(failed['attempt_id'])['receipt']['status']=='FAILED'
    monkeypatch.setattr('polar.descriptive_service.reference_calendar',lambda *args:(_ for _ in ()).throw(KeyboardInterrupt()))
    stopped=operation.run(retained.config());assert stopped['status']=='INTERRUPTED'
    assert operation.store.attempt(stopped['attempt_id'])['receipt']['status']=='INTERRUPTED'
    monkeypatch.setattr(operation.store,'finish_attempt',lambda *args:(_ for _ in ()).throw(OSError()))
    unknown=operation.run(retained.config());assert unknown['status']=='UNFINALIZED'
    assert operation.store.attempt(unknown['attempt_id'])['status']=='UNFINALIZED'
    assert len(list((retained.store.root/'history-experiment-attempts').iterdir()))==3


def test_storage_refusal_preserves_attempt_and_prior_completed_outputs(operation,retained):
    result=operation.run(retained.config());before=operation.store.verify(result['experiment_id'])
    operation.store.limit=operation.store.used()+5000
    failed=operation.run(retained.config(start=retained.sessions[1]))
    assert failed['status']=='FAILED' and failed['code']=='HISTORY_STORAGE_LIMIT'
    assert operation.store.attempt(failed['attempt_id'])['status']=='FAILED'
    assert operation.store.verify(result['experiment_id'])==before


def test_integrity_and_path_refusal(operation,retained,tmp_path):
    result=operation.run(retained.config());eid=result['experiment_id']
    table=tmp_path/'history-experiments'/eid/'features.ndjson';table.chmod(0o600);table.write_bytes(table.read_bytes()+b' ')
    with pytest.raises(HistoryError,match='DESCRIPTIVE_OBJECT_INTEGRITY'):operation.store.verify(eid)
    with pytest.raises(HistoryError,match='DESCRIPTIVE_INVALID_ID'):operation.store.verify('../outside')
    with pytest.raises(HistoryError,match='DESCRIPTIVE_INVALID_ID'):operation.store.attempt('../outside')


def test_api_paging_exact_identity_and_no_table_in_metadata(operation,retained,tmp_path):
    result=operation.run(retained.config());assert result['status']=='COMPLETED'
    key=tmp_path/'test.key';key.write_bytes(bytes(range(32)))
    service=Service(Settings('unused',tmp_path,history_cursor_key_file=key));service.history_registry=retained
    client=TestClient(create_app(service));eid=result['experiment_id']
    response=client.get('/v1/history/experiments/'+eid);assert response.status_code==200,response.text
    meta=response.json();assert 'rows' not in meta and meta['config']['dataset_revision']==REV
    vid=meta['feature_view_id'];query={'limit':'7'};allrows=[]
    while True:
        response=client.get('/v1/history/views/'+vid+'/rows',params=query);assert response.status_code==200,response.text
        page=response.json();assert page['row_count']<=7 and len(response.content)<=1024**2
        allrows.extend(page['rows'])
        if page['next_cursor'] is None:break
        query['cursor']=page['next_cursor']
    assert len(allrows)==30
    first=client.get('/v1/history/views/'+vid+'/rows',params={'limit':'7'}).json()
    assert client.get('/v1/history/views/'+meta['label_view_id']+'/rows',params={'limit':'7','cursor':first['next_cursor']}).status_code==422
    assert client.get('/v1/history/attempts/'+result['attempt_id']).json()['status']=='COMPLETED'
    assert client.get('/v1/history/views/'+vid+'?extra=1').status_code==422


def test_hostile_decimal_context_and_input_order_are_not_semantics(retained):
    from decimal import localcontext,ROUND_DOWN
    for i,row in enumerate(retained.sources['a']):row['close']=str(i+1)+'.123456789012345678'
    baseline=retained.compile()
    with localcontext() as ambient:
        ambient.prec=2;ambient.rounding=ROUND_DOWN
        for signal in ambient.traps:ambient.traps[signal]=True
        before=ambient.copy()
        assert retained.compile()==baseline
        assert ambient.flags==before.flags and ambient.prec==2
    retained.sources['a'].append(retained.sources['a'][0])
    with pytest.raises(HistoryError,match='HISTORY_AMBIGUOUS_SERIES'):retained.compile()


def test_window_tail_and_missing_start_masks_both_retained(retained):
    del retained.sources['a'][-1]
    _,values=retained.compile(start=retained.sessions[-1])
    label=rows(values,'labels')[0]
    assert label['reasons']==['MISSING_START','TAIL_ENDPOINT_UNAVAILABLE']
    assert decode(values['counts.json'])['assets']['a']['candidate_expected']==1


def test_parent_symlink_never_reads_experiment_payload(operation,retained,tmp_path):
    result=operation.run(retained.config());assert result['status']=='COMPLETED'
    parent=tmp_path/'history-experiments';renamed=tmp_path/'owned-elsewhere';parent.rename(renamed);parent.symlink_to(renamed,target_is_directory=True)
    with pytest.raises(HistoryError,match='HISTORY_UNSAFE_OR_MISSING_FILE'):operation.store.verify(result['experiment_id'])


def test_cli_delegates_same_operation_prints_only_ids_and_failure_code(operation,retained,tmp_path,monkeypatch,capsys):
    from polar.cli import main
    monkeypatch.setattr(Settings,'load',lambda:Settings('unused',tmp_path))
    monkeypatch.setattr(Service,'history_experiment_run',lambda self,config:operation.run(config))
    config_file=tmp_path/'request.json';config_file.write_bytes(canonical(retained.config()))
    main(['history-experiment',str(config_file)])
    success=json.loads(capsys.readouterr().out);assert success['status']=='COMPLETED' and 'rows' not in success
    wrong=retained.config(manifest_sha256='9'*64);config_file.write_bytes(canonical(wrong))
    with pytest.raises(SystemExit) as stop:main(['history-experiment',str(config_file)])
    assert stop.value.code==1
    failed=json.loads(capsys.readouterr().out);assert failed['status']=='FAILED' and failed['attempt_id']!=success['attempt_id']
    assert operation.store.attempt(failed['attempt_id'])['receipt']['status']=='FAILED'


def test_oversized_cli_config_refuses_before_service(operation,retained,tmp_path,monkeypatch,capsys):
    from polar.cli import main
    monkeypatch.setattr(Settings,'load',lambda:Settings('unused',tmp_path))
    called=[];monkeypatch.setattr(Service,'history_experiment_run',lambda *args:called.append(True))
    config_file=tmp_path/'request.json';config_file.write_bytes(b'x'*8193)
    with pytest.raises(SystemExit):main(['history-experiment',str(config_file)])
    assert not called and 'DESCRIPTIVE_INVALID_CONFIG' in capsys.readouterr().err

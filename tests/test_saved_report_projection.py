"""Invented sealed report inputs only; no original run/evaluator/native needed."""
from copy import deepcopy
import json
from pathlib import Path
import pytest

from test_scheduled_model_price import model_fixture
from test_scheduled_service import snapshot
from polar.gym_contract import canonical,sha
from polar.saved_report_projection import project_saved_report,write_artifact


def graph(tmp_path,monkeypatch):
    source=tmp_path/'source';source.mkdir()
    _,cfg,p,_=model_fixture(source,monkeypatch)
    p['additional_limitations']=[['INVENTED_'+str(i),'Invented supplied limitation '+str(i)] for i in range(3)]
    cfg={**cfg,'code':{'old_producer.py':'a'*64},'code_revision':'a'*40,'runtime_image_id':'sha256:'+'a'*64}
    nav=[{'nominal_ns':1577998800000000000+i*86400*10**9,'cash_cents':10000000,'exposure_cents':0,
          'flat_cents':0,'bps_cents':0,'positions':{},'nav_cents':10000000} for i in range(2)]
    token=lambda:{'value':'0','status':'OK','reason':None}
    simulation={'legs':[{'id':x['id'],'nav':deepcopy(nav)} for x in p['legs']]}
    evaluation={'legs':[{'id':x['id'],'returns':[{'decimal':'0'}],
                 'metrics':{k:token() for k in ('terminal_nav_usd','flat_fee_usd','bps_cost_usd')}} for x in p['legs']],
                 'comparisons':[],'criteria':[],'point_interpretation':'Invented supplied scalars only'}
    segment={'first_return_date':'2020-01-03','last_return_date':'2020-01-03','initial_date':'2020-01-02','intervals':1,
       'metrics':{k:token() for k in ('net_total_return','sharpe_252_rf0','max_drawdown','net_cagr_act36525','annual_vol_252')},
       'costs':{**{k:token() for k in ('total_fee_usd','gross_exact_notional_usd','gross_settled_notional_usd','positive_fill_count','gross_notional_over_initial')},'normalization_initial_nav_cents':10000000}}
    diagnostic={'daily_tail':{**{k:token() for k in ('actual_tail_fraction','lower_tail_mean_return','lower_return_threshold','expected_shortfall_loss')},'k':1},
       'drawdown':{'status':'NO_DRAWDOWN','time_underwater_fraction':token(),'peak':None,'trough':None,'recovery':None,'peak_to_trough_intervals':None,'peak_to_recovery_intervals':None,'censored_peak_to_terminal_intervals':None},
       'calendar_months':{'complete_count':0,'partial_count':1,'worst_full_month':{'net_return':token()}},
       'worst_horizons':{k:{'net_return':token()} for k in ('1','21','63')},'subperiods':[deepcopy(segment),deepcopy(segment)]}
    files={'profile.json':p,'bindings.json':cfg,'calendar.json':{'phases':{'FINAL':{'nav_dates':['2020-01-02','2020-01-03'],'nav_points':2,'return_count':1}}},
           'phases.json':{'FINAL':{'simulation':simulation,'evaluation':evaluation}},
           'diagnostics.json':{'FINAL':{x['id']:deepcopy(diagnostic) for x in p['legs']}}}
    root=tmp_path/'readonly-store';root.mkdir();sid=pack(root,files)
    # Delete every invented source file/quote/model input before projection.
    import shutil
    shutil.rmtree(source)
    return root,sid,files,cfg


def pack(root,files):
    raw={k:canonical(v) for k,v in files.items()}
    manifest={'schema':'polar.scheduled-reference-semantic-manifest/1','files':{k:{'sha256':sha(v),'bytes':len(v)} for k,v in raw.items()}}
    body=canonical(manifest);sid='scheduled-reference-experiment-'+sha(body)
    folder=root/'reference-research-experiments'/sid;folder.mkdir(parents=True,exist_ok=True)
    for k,v in {**raw,'manifest.json':body}.items():(folder/k).write_bytes(v)
    return sid


def call(root,sid,cfg,**kw):
    return project_saved_report(root,sid,candidate_id=cfg['candidate_id'],experiment_id=cfg['experiment_id'],report_revision='b'*40,runtime_image_id='sha256:'+'b'*64,**kw)


def forbid(monkeypatch):
    import polar.scheduled_service as scheduled
    import polar.reference_service as reference
    from polar.history_store import HistoryStore
    from polar.research_results import ResearchResults
    def no(*a,**kw):raise AssertionError('FORBIDDEN_EXECUTION_OR_STORE_WRITE')
    for name in ('run','recompute','load_market','load_reference','bounded_native','evaluate_policy','diagnose_phase','plan_phase'):
        monkeypatch.setattr(scheduled,name,no)
    monkeypatch.setattr(reference.ReferenceResearchService,'run',no)
    monkeypatch.setattr(reference.ReferenceResearchService,'recompute',no)
    monkeypatch.setattr(HistoryStore,'_publish',no);monkeypatch.setattr(HistoryStore,'locked',no)
    monkeypatch.setattr(ResearchResults,'publish',no)


def test_complete_graph_source_absent_readonly_deterministic_no_forbidden_calls(tmp_path,monkeypatch):
    root,sid,files,cfg=graph(tmp_path,monkeypatch);forbid(monkeypatch)
    for path in root.rglob('*'):path.chmod(0o555 if path.is_dir() else 0o444)
    root.chmod(0o555);before=snapshot(root)
    first=call(root,sid,cfg);second=call(root,sid,cfg)
    assert first==second and first['status']=='REPORT_SCHEMA_VALID'
    record=first['records']['FINAL'];assert len(record['limitations'])==31
    assert len([x for x in record['limitations'] if x['code'].startswith('SEGMENT_')])==10
    assert record['bindings']['code_revision']=='a'*40 and first['report_source']['declared_revision']=='b'*40
    assert record['bindings']['runtime_id']=='sha256:'+'a'*64
    assert all(first[k]==0 for k in ('input_store_writes','native_calls','policy_calls','evaluation_recomputations','diagnostic_recomputations','source_loads','publications','registry_writes'))
    assert snapshot(root)==before
    outside=tmp_path/'technical-output';outside.mkdir();out=outside/'projection.json'
    write_artifact(out,first,input_store_root=root)
    assert json.loads(out.read_bytes())==first and out.stat().st_mode & 0o777==0o600
    with pytest.raises(FileExistsError):write_artifact(out,first,input_store_root=root)
    with pytest.raises(ValueError,match='SAVED_REPORT_OUTPUT_LOCATION'):write_artifact(root/'forbidden.json',first,input_store_root=root)
    assert snapshot(root)==before


@pytest.mark.parametrize('mutation',['missing_member','missing_diagnostic','missing_value','wrong_candidate','profile_binding','bad_member_hash','bad_manifest_id','unsafe_member','symlink','calendar_grid','diagnostic_token','evaluation_identity','malformed_json'])
def test_incomplete_and_conflicting_graphs_never_execute(tmp_path,monkeypatch,mutation):
    root,sid,files,cfg=graph(tmp_path,monkeypatch);forbid(monkeypatch)
    folder=root/'reference-research-experiments'/sid
    expected='INVALID_INPUT'
    if mutation=='missing_member':(folder/'diagnostics.json').unlink();expected='INCOMPLETE_INPUT'
    if mutation=='missing_diagnostic':
        del files['diagnostics.json']['FINAL'][files['profile.json']['legs'][0]['id']]['drawdown'];sid=pack(root,files);expected='INCOMPLETE_INPUT'
    if mutation=='missing_value':
        del files['phases.json']['FINAL']['simulation']['legs'][0]['nav'][0]['cash_cents'];sid=pack(root,files);expected='INCOMPLETE_INPUT'
    if mutation=='calendar_grid':files['calendar.json']['phases']['FINAL']['nav_dates'][0]='2020-01-01';sid=pack(root,files)
    if mutation=='diagnostic_token':
        del files['diagnostics.json']['FINAL'][files['profile.json']['legs'][0]['id']]['daily_tail']['actual_tail_fraction']['value'];sid=pack(root,files);expected='INCOMPLETE_INPUT'
    if mutation=='evaluation_identity':files['phases.json']['FINAL']['evaluation']['legs'][0]['id']='CONFLICT';sid=pack(root,files)
    if mutation=='malformed_json':(folder/'manifest.json').write_bytes(b'not-json')
    if mutation=='wrong_candidate':cfg={**cfg,'candidate_id':'WRONG-CANDIDATE'}
    if mutation=='profile_binding':files['profile.json']['input_sha256']='0'*64;sid=pack(root,files)
    if mutation=='bad_member_hash':(folder/'diagnostics.json').write_bytes(b'{}')
    if mutation=='bad_manifest_id':(folder/'manifest.json').write_bytes(b'{}')
    if mutation=='unsafe_member':
        f=folder/'manifest.json';m=json.loads(f.read_bytes());m['files']['../source']=m['files'].pop('diagnostics.json');raw=canonical(m);new='scheduled-reference-experiment-'+sha(raw);folder.rename(folder.with_name(new));folder=folder.with_name(new);(folder/'manifest.json').write_bytes(raw);sid=new
    if mutation=='symlink':
        f=folder/'diagnostics.json';target=tmp_path/'not-followed';f.rename(target);f.symlink_to(target)
    before=snapshot(root) if mutation!='symlink' else None
    result=call(root,sid,cfg);assert result['status']==expected and 'records' not in result
    if before is not None:assert snapshot(root)==before


def test_invalid_semantic_path_rejects_before_any_read(tmp_path):
    with pytest.raises(ValueError,match='SAVED_REPORT_SEMANTIC_ID'):
        project_saved_report(tmp_path,'../escape',candidate_id='x',experiment_id='y',report_revision='a'*40,runtime_image_id='sha256:'+'a'*64)



def test_empty_store_returns_explicit_incomplete_and_output_cannot_follow_symlink(tmp_path,monkeypatch):
    root=tmp_path/'empty';root.mkdir()
    cfg={'candidate_id':'INVENTED','experiment_id':'INVENTED'}
    result=call(root,'scheduled-reference-experiment-'+'0'*64,cfg)
    assert result['status']=='INCOMPLETE_INPUT' and result['missing']==['semantic_directory']
    target=tmp_path/'outside';target.mkdir();link=tmp_path/'link';link.symlink_to(target,target_is_directory=True)
    with pytest.raises(ValueError):write_artifact(link/'unsafe.json',result,input_store_root=root)
    assert not list(target.iterdir())

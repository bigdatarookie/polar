"""Invented sealed report inputs only; no original run/evaluator/native needed."""
from copy import deepcopy
import json
from pathlib import Path
import pytest

from test_scheduled_model_price import model_fixture
from test_scheduled_service import snapshot
from polar.gym_contract import canonical,sha
from polar.saved_report_projection import project_saved_report,write_artifact


def graph(tmp_path,monkeypatch,*,fixed=False):
    source=tmp_path/'source';source.mkdir()
    _,cfg,p,calendar=model_fixture(source,monkeypatch)
    if fixed:
        manifest=json.loads(Path(cfg['input_ref']['path']).read_bytes())
        schedule=json.loads(Path(manifest['schedule']['path']).read_bytes())['rows']
    p['additional_limitations']=[['INVENTED_'+str(i),'Invented supplied limitation '+str(i)] for i in range(3)]
    cfg={**cfg,'code':{'old_producer.py':'a'*64},'code_revision':'a'*40,'runtime_image_id':'sha256:'+'a'*64}
    nav=[{'nominal_ns':1577998800000000000+i*86400*10**9,'cash_cents':10000000,'exposure_cents':0,
          'flat_cents':0,'bps_cents':0,'positions':{},'nav_cents':10000000} for i in range(2)]
    if fixed:
        from datetime import datetime
        from polar.reference_ridge_plan import nanoseconds
        by_date={r['date']:r for r in schedule}
        nav=[{**nav[0],'date':day,'nominal_ns':nanoseconds(datetime.fromisoformat(by_date[day]['reference_close_utc'].replace('Z','+00:00')))} for day in calendar['dates']]
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
    if fixed:
        files['calendar.json']={**calendar,'source_schedule_rows':schedule}
        simulation['quantity_unit']=p['model_price_mapping']['active_unit']
        for leg in evaluation['legs']:leg['returns']=[{'decimal':'0'} for _ in nav[1:]]
        for d in files['diagnostics.json']['FINAL'].values():d['schema']='polar.fixed-allocation-saved-diagnostics/1'
        plan_grid=[{'date':r['date'],'nominal_ns':r['nominal_ns'],'sample_ns':r['nominal_ns']+1000,
                    'initial':i==0,'terminal':i==len(nav)-1} for i,r in enumerate(nav)]
        decisions=[]
        for i,event in enumerate(calendar['annual_targets']+[calendar['terminal_EXIT']]):
            instructions={leg['id']:({'kind':'EXIT'} if i==len(calendar['annual_targets']) else
                {'kind':'HOLD'} if leg['rule']=='CASH' else {'kind':'TARGET','weights':leg['weights'],
                'signal':{'kind':'FIXED_DECLARED_WEIGHTS'}}) for leg in p['legs']}
            decisions.append({'day':event['execution_date'],'formation':event['formation_date'],
                'known_ns':nanoseconds(datetime.fromisoformat(event['K'])),
                'decision_ns':nanoseconds(datetime.fromisoformat(event['D'])),
                'open_ns':nanoseconds(datetime.fromisoformat(event['reference_execution_close_utc'])),
                'kind':'REFERENCE','instructions':instructions})
        files['phases.json']['FINAL']['plan']={'grid':plan_grid,'decisions':decisions,
            'quantity_unit':simulation['quantity_unit'],'model_price_mapping':p['model_price_mapping'],
            'prices':{'NOT_USED_BY_REPORT':'No quote valuation in this adapter'},
            'source_prices_micro':{'NOT_USED_BY_REPORT':'No source-price mapping recomputation'}}
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
    import polar.reference_model_price as model
    import polar.scheduled_fixed as fixed
    for name in ('view','verify_plan'):monkeypatch.setattr(model,name,no)
    for name in ('plan_phase','diagnose_fixed'):monkeypatch.setattr(fixed,name,no)


@pytest.mark.parametrize('fixed',[False,True])
def test_complete_graph_source_absent_readonly_deterministic_no_forbidden_calls(tmp_path,monkeypatch,fixed):
    root,sid,files,cfg=graph(tmp_path,monkeypatch,fixed=fixed);forbid(monkeypatch)
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
    with pytest.raises(ValueError,match='SAVED_REPORT_OUTPUT_LOCATION'):write_artifact(outside/'..'/'readonly-store'/'traversal.json',first,input_store_root=root)
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



def test_cli_and_changed_artifact_id_are_private_and_closed(tmp_path,monkeypatch,capsys):
    root,sid,files,cfg=graph(tmp_path,monkeypatch);forbid(monkeypatch)
    import polar.saved_report_projection as module
    out=tmp_path/'cli-technical.json'
    monkeypatch.setattr('sys.argv',['saved-report-projection','--store-root',str(root),'--semantic-id',sid,
        '--candidate-id',cfg['candidate_id'],'--experiment-id',cfg['experiment_id'],'--report-revision','b'*40,
        '--runtime-image-id','sha256:'+'b'*64,'--output',str(out)])
    before=snapshot(root);assert module.main()==0 and snapshot(root)==before
    emitted=json.loads(capsys.readouterr().out);artifact=json.loads(out.read_bytes())
    assert set(emitted)=={'status','technical_artifact_id'} and emitted['technical_artifact_id']==artifact['technical_artifact_id']
    artifact['status']='MUTATED'
    with pytest.raises(ValueError,match='SAVED_REPORT_ARTIFACT_ID'):write_artifact(tmp_path/'tampered.json',artifact,input_store_root=root)
    assert not (tmp_path/'tampered.json').exists()


@pytest.mark.parametrize('mutation',['shift_ns','shift_day','reverse_grid','extra_return','missing_return'])
def test_every_saved_leg_grid_and_return_count_checked_before_formatter(tmp_path,monkeypatch,mutation):
    root,sid,files,cfg=graph(tmp_path,monkeypatch);forbid(monkeypatch)
    simulation=files['phases.json']['FINAL']['simulation']['legs']
    evaluation=files['phases.json']['FINAL']['evaluation']['legs']
    if mutation=='shift_ns':simulation[1]['nav'][0]['nominal_ns']+=1
    if mutation=='shift_day':
        for row in simulation[1]['nav']:row['nominal_ns']+=86400*10**9
    if mutation=='reverse_grid':simulation[1]['nav'].reverse()
    if mutation=='extra_return':evaluation[1]['returns'].append({'decimal':'0'})
    if mutation=='missing_return':evaluation[1]['returns'].clear()
    sid=pack(root,files);before=snapshot(root)
    import polar.saved_report_projection as module
    def no_formatter(*a,**kw):raise AssertionError('CONFLICT_MUST_REJECT_BEFORE_COMPOSITION')
    monkeypatch.setattr(module,'public_reference',no_formatter)
    result=call(root,sid,cfg)
    assert result['status']=='INVALID_INPUT' and 'records' not in result
    assert result['reason']==('SAVED_REPORT_RETURN_COUNT' if 'return' in mutation else 'SAVED_REPORT_LEG_GRID')
    assert snapshot(root)==before


@pytest.mark.parametrize('mutation',['initial','terminal','nav_count','return_count','annual_missing','annual_clock','exit_clock','unsupported','conflicting_form','source_close','all_leg_time','missing_plan','plan_clock','plan_initial','plan_mapping','unit','diagnostic_schema'])
def test_fixed_producer_calendar_and_plan_metadata_conflicts_are_not_hidden(tmp_path,monkeypatch,mutation):
    root,sid,files,cfg=graph(tmp_path,monkeypatch,fixed=True);forbid(monkeypatch)
    calendar=files['calendar.json'];phase=files['phases.json']['FINAL'];plan=phase['plan']
    if mutation=='initial':calendar['initial_date']=calendar['dates'][1]
    if mutation=='terminal':calendar['terminal_date']=calendar['dates'][-2]
    if mutation=='nav_count':calendar['nav_points']+=1
    if mutation=='return_count':calendar['returns']+=1
    if mutation=='annual_missing':calendar['annual_targets'].pop()
    if mutation=='annual_clock':calendar['annual_targets'][0]['D']=calendar['annual_targets'][0]['K']
    if mutation=='exit_clock':calendar['terminal_EXIT']['execution_date']=calendar['dates'][-2]
    if mutation=='unsupported':calendar['schema']='polar.UNKNOWN/1'
    if mutation=='conflicting_form':calendar['phases']={'FINAL':{'nav_dates':['2000-01-01']}}
    if mutation=='source_close':calendar['source_schedule_rows'][0]['reference_close_utc']=calendar['dates'][0]+'T20:00:00Z'
    if mutation=='all_leg_time':
        for leg in phase['simulation']['legs']:leg['nav'][0]['nominal_ns']+=1
    if mutation=='missing_plan':del phase['plan']
    if mutation=='plan_clock':plan['decisions'][0]['decision_ns']+=1
    if mutation=='plan_initial':plan['grid'][0]['initial']=False
    if mutation=='plan_mapping':plan['model_price_mapping']={**plan['model_price_mapping'],'lot_size':2}
    if mutation=='unit':phase['simulation']['quantity_unit']='PHYSICAL_SHARE'
    if mutation=='diagnostic_schema':files['diagnostics.json']['FINAL'][files['profile.json']['legs'][0]['id']]['schema']='UNKNOWN'
    sid=pack(root,files);before=snapshot(root)
    result=call(root,sid,cfg)
    assert result['status']==('INCOMPLETE_INPUT' if mutation=='missing_plan' else 'INVALID_INPUT')
    assert 'records' not in result and snapshot(root)==before


def test_opaque_fixed_calendar_annotations_are_bound_not_followed_or_inferred(tmp_path,monkeypatch):
    root,sid,files,cfg=graph(tmp_path,monkeypatch,fixed=True);forbid(monkeypatch)
    files['calendar.json']['parent_schedule']={'opaque':'INVENTED original producer annotation; not a source lookup'}
    files['calendar.json']['clock_scope']={'K':'descriptive only','not_an_execution_grant':True}
    sid=pack(root,files);before=snapshot(root)
    result=call(root,sid,cfg)
    assert result['status']=='REPORT_SCHEMA_VALID' and snapshot(root)==before
    assert result['verified_members']['calendar.json']['sha256']==sha(canonical(files['calendar.json']))

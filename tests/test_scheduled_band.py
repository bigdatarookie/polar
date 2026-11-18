"""Invented actual cost-account callbacks and immutable source-absent evidence."""
from copy import deepcopy
from datetime import datetime
from fractions import Fraction
from hashlib import sha256
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo, TZPATH

import pytest
from polar import scheduled_band as band
from polar.band_contract import QUESTION,POLICY_SHA,CONTRACT_SHA,PROTOCOL_SHA,IDS,COSTS,author
from polar.gym_contract import canonical
from polar.reference_service import ReferenceResearchService
from polar.research_results import ResearchResults
from polar.scheduled_service import config_from_seed
from polar.candidate_binding import loaded_revision
from polar.research_reference import load_reference
from reference_fixture import fixture as reference_fixture,write


def fixture(tmp_path,monkeypatch,*,distress=False,zero_buy=False):
    root,cfg=reference_fixture(tmp_path,monkeypatch)
    manifest=json.loads(Path(cfg['input_ref']['path']).read_bytes())
    schedule=json.loads(Path(manifest['schedule']['path']).read_bytes())['rows']
    rows=[json.loads(line) for line in Path(manifest['quotes']['path']).read_text().splitlines()]
    selected=[]
    for row in rows:
        if row['symbol'] not in ('AAA','BBB'):continue
        symbol={'AAA':'BIL','BBB':'VTI'}[row['symbol']];day=row['date']
        token='1.000000' if distress else '100000.000000' if zero_buy else '100.000000'
        if not distress and not zero_buy and symbol=='VTI' and day.endswith('-31'):token='67.100000'
        if distress and day=='2018-02-04':token='0.000001'
        selected.append({**row,'symbol':symbol,'reference_quote':token,'source_adjusted_close_token':token})
    qp=Path(manifest['quotes']['path']);qp.write_bytes(b''.join(canonical(row) for row in selected))
    manifest.update(symbols=['BIL','VTI'],rows=len(selected),quotes=dict(path=str(qp),sha256=sha256(qp.read_bytes()).hexdigest(),bytes=qp.stat().st_size))
    mp=write(tmp_path/'band-input.json',manifest)
    def grid(first,last):
        days=[r['date'] for r in schedule if first<=r['date']<=last]
        formation=list(dict.fromkeys([first]+[r['date'] for r in schedule if first<=r['date']<last and r['month_end_in_reference_range']]))
        events=[]
        for day in formation:
            entry=next(r['next_reference_date'] for r in schedule if r['date']==day)
            if entry<last:events.append(band.event(day,entry,schedule,first=day==first))
        before=next(r['date'] for r in schedule if r['next_reference_date']==last)
        return dict(initial=first,terminal=last,nav_dates=days,nav_points=len(days),return_count=len(days)-1,
                    decisions=events,decision_count=len(events),terminal_exit=band.event(before,last,schedule,terminal=True))
    calendar=dict(schema=band.CALENDAR,source_schedule=manifest['schedule'],phases={
        'VALIDATION':grid('2018-01-01','2018-02-04'),'FINAL':grid('2018-03-01','2018-04-04')})
    cp=write(tmp_path/'band-calendar.json',calendar)
    tzpath=next((Path(p)/'UTC' for p in TZPATH if (Path(p)/'UTC').is_file()),None)
    tz=tmp_path/'UTC';tz.write_bytes(tzpath.read_bytes() if tzpath else __import__('importlib.resources',fromlist=['files']).files('tzdata').joinpath('zoneinfo/UTC').read_bytes())
    p=dict(schema=band.SCHEMA,protocol_id=QUESTION,protocol_sha256=PROTOCOL_SHA,input_sha256=mp['sha256'],
        calendar_sha256=cp['sha256'],timezone_sha256=sha256(tz.read_bytes()).hexdigest(),symbols=['BIL','VTI'],
        policy=dict(kind=band.KIND,policy_sha256=POLICY_SHA,contract_sha256=CONTRACT_SHA),
        legs=[dict(id=leg,label=leg,rule=leg,scale=[1,1]) for leg in IDS],primary_strategy='BAND_HALF',primary_benchmark='MONTHLY_HALF',
        decision_delay_seconds=60,cost_scenarios=COSTS,
        criteria=[dict(id='C'+str(i),description='Frozen invented criterion '+str(i),left_id='BAND_HALF',**spec) for i,spec in enumerate(band.SPECS)],
        question_label='Invented native account band',question_summary='Fixed actual cent-mark band versus monthly and static controls.',
        clock_description='Modeled UTC midnight plus60seconds; first common close strictly later.',partition_description='Two independent invented fresh-capital phases.',
        additional_limitations=[],subperiods=[])
    pp=write(tmp_path/'band-profile.json',p)
    protocol=Path(__file__).resolve().parents[1]/'research_candidates/quant_a_vti_bil_band/protocol.md'
    config=config_from_seed(dict(schema='polar.band-reference-seed/1',namespace='INVENTED',profile_path=pp['path'],
        protocol_path=str(protocol),input_path=mp['path'],calendar_path=cp['path'],timezone_path=str(tz),
        code_revision=loaded_revision(),runtime_image_id=os.environ['POLAR_CI_RUNTIME_IMAGE_ID'],
        candidate_id='INVENTED-BAND',experiment_id='INVENTED-BAND-ORIGINAL',consumer_task='qitem-INVENTED-BAND'))
    return root,config,p,calendar


def test_actual_cost_account_divergence_and_source_absent_saved_verification(tmp_path,monkeypatch):
    root,cfg,p,c=fixture(tmp_path,monkeypatch);service=ReferenceResearchService(root,128*1024**2)
    ready=service.preflight(cfg);assert ready['expected_native_accounts']==20
    result=service.run(cfg);assert result['status']=='SUCCESS'
    directory=root/'reference-research-experiments'/result['semantic_id']
    phases=json.loads((directory/'phases.json').read_bytes());calendar=json.loads((directory/'calendar.json').read_bytes())
    assert set(phases)=={'VALIDATION','VALIDATION_COST_STRESS','FINAL','FINAL_COST_STRESS'}
    from polar.model_price_consumed import verify
    for name,data in phases.items():
        assert len(data['simulation']['legs'])==5
        verify(data['plan'],data['simulation'],p,calendar)
        for leg in data['simulation']['legs']:
            assert not any(leg['nav'][0]['positions'].values()) and not any(leg['nav'][-1]['positions'].values())
            assert leg['nav'][-1]['cash_cents']==leg['nav'][-1]['nav_cents']
            for intent in leg['intents']:
                obs=intent['native_formation_observation']
                assert obs['leg']==leg['id'] and obs['account_id']==leg['native_account_id']
                assert obs['nav_cents']==sum(obs['marked_values_cents'].values())+obs['cash_cents']
                assert obs['formation_close_ns']+1000==obs['observed_sample_ns']<intent['known_ns']<intent['decision_ns']
    base=phases['VALIDATION']['simulation']['legs'][0];stress=phases['VALIDATION_COST_STRESS']['simulation']['legs'][0]
    assert base['intents'][1]['native_policy_instruction']['kind']=='HOLD'
    assert stress['intents'][1]['native_policy_instruction']['kind']=='TARGET'
    assert base['intents'][1]['native_formation_observation']['quantities']!=stress['intents'][1]['native_formation_observation']['quantities']
    assert base['intents'][1]['native_formation_observation']['prices_micro']['VTI']==67100000
    assert base['intents'][1]['sizing_witness'] is None and stress['intents'][1]['sizing_witness'] is not None
    # Every other fixed control follows its actual native account and frozen startup/monthly semantics.
    monthly=phases['VALIDATION']['simulation']['legs'][1];static=phases['VALIDATION']['simulation']['legs'][2]
    assert monthly['intents'][1]['native_policy_instruction']['kind']=='TARGET'
    assert static['intents'][1]['native_policy_instruction']['kind']=='HOLD'
    for pub in result['results'].values():
        record=ResearchResults(root,128*1024**2).read(pub['result_id'])['record']
        assert len(record['series'])==5
        assert any(x['code']=='ACTUAL_COST_ACCOUNT_BAND' for x in record['limitations'])
    for mutation in ('cash','account','clock','source','decision','mark'):
        data=deepcopy(phases['VALIDATION']);intent=data['simulation']['legs'][0]['intents'][1];obs=intent['native_formation_observation']
        if mutation=='cash':obs['cash_cents']+=1
        elif mutation=='account':obs['account_id']='FOREIGN'
        elif mutation=='clock':obs['observed_sample_ns']+=1
        elif mutation=='source':obs['source_input_sha256']='0'*64
        elif mutation=='decision':intent['native_policy_instruction']['kind']='TARGET'
        else:obs['marked_values_cents']['VTI']+=1
        with pytest.raises(ValueError):verify(data['plan'],data['simulation'],p,calendar)
    with pytest.raises(ValueError,match='SCHEDULED_ORIGINAL_ALREADY_RECORDED'):service.run(cfg)
    source=json.loads(Path(cfg['input_ref']['path']).read_bytes())
    for ref in (source['quotes'],source['schedule'],cfg['input_ref'],cfg['profile_ref'],cfg['calendar_ref'],cfg['timezone_ref']):
        Path(ref['path']).unlink()
    before={str(f):sha256(f.read_bytes()).hexdigest() for f in root.rglob('*') if f.is_file()}
    def forbidden(*a,**k):raise AssertionError('SAVED_SOURCE_POLICY_NATIVE_WRITE')
    import polar.scheduled_service as module
    for name in ('load_reference','load_market','plan_phase','bounded_native','read_ref'):monkeypatch.setattr(module,name,forbidden)
    monkeypatch.setattr(author,'decide',forbidden);monkeypatch.setattr(service.store,'_publish',forbidden)
    reproduced=service.recompute(result['semantic_id'])
    assert reproduced['status']=='REPRODUCED' and reproduced['native_calls']==reproduced['store_writes']==0
    assert before=={str(f):sha256(f.read_bytes()).hexdigest() for f in root.rglob('*') if f.is_file()}


def test_genuine_terminal_fee_distress_keeps_partial_and_unstarted_cases(tmp_path,monkeypatch):
    root,cfg,p,c=fixture(tmp_path,monkeypatch,distress=True);service=ReferenceResearchService(root,128*1024**2)
    from polar.ci_research_service import NativeFailure
    with pytest.raises(NativeFailure):service.run(cfg)
    finishpath=next(root.glob('scheduled-reference-attempts/*/*/finish/record.json'))
    finish=json.loads(finishpath.read_bytes());events=json.loads(finishpath.with_name('diagnostics.json').read_bytes())
    assert finish['status']=='ECONOMIC_DISTRESS_UNFINALIZED' and finish['scientific_status']=='NOT_EVALUABLE'
    assert finish['refund'] is False and finish['automatic_retry'] is False
    assert finish['case_statuses']['VALIDATION']=='ECONOMIC_DISTRESS_UNFINALIZED'
    assert all(v=='NOT_RUN' for k,v in finish['case_statuses'].items() if k!='VALIDATION')
    witness=next(e['witness'] for e in events if e['phase']=='ECONOMIC_DISTRESS')
    assert witness['kind']=='MANDATORY_SALE_FEE_SHORTFALL'
    assert witness['cash_cents']+witness['settled_cents']-witness['fee_cents']<0
    assert not list((root/'research-results').glob('*'))
    with pytest.raises(ValueError,match='SCHEDULED_ORIGINAL_ALREADY_RECORDED'):service.run(cfg)


def test_ordinary_zero_buy_is_actual_funded_path_not_distress(tmp_path,monkeypatch):
    root,cfg,_,_=fixture(tmp_path,monkeypatch,zero_buy=True)
    result=ReferenceResearchService(root,128*1024**2).run(cfg);assert result['status']=='SUCCESS'
    phases=json.loads((root/'reference-research-experiments'/result['semantic_id']/'phases.json').read_bytes())
    for data in phases.values():
        for leg in data['simulation']['legs']:
            assert leg['fills']==[]
            assert all(r['flat_cents']==r['bps_cents']==0 for r in leg['nav'])
            assert leg['intents'][0]['native_policy_instruction']['kind']=='TARGET'
            assert any(o['reason']=='FEE_AWARE_BUDGET_CAP' and o['routed_quantity']==0 for o in leg['orders'])


def test_missing_actual_formation_snapshot_is_invalid_integration_not_distress(tmp_path,monkeypatch):
    root,cfg,p,c=fixture(tmp_path,monkeypatch)
    import polar.scheduled_service as module
    original=module.bounded_native
    def invalid(plan):
        plan=deepcopy(plan);plan['grid']=[g for g in plan['grid'] if g['date']!=plan['decisions'][1]['formation']]
        return original(plan)
    monkeypatch.setattr(module,'bounded_native',invalid)
    from polar.ci_research_service import NativeFailure
    with pytest.raises(NativeFailure):ReferenceResearchService(root,128*1024**2).run(cfg)
    finish=json.loads(next(root.glob('scheduled-reference-attempts/*/*/finish/record.json')).read_bytes())
    assert finish['status']=='INVALID_SOURCE_OR_INTEGRATION' and finish['scientific_status']=='NOT_EVALUABLE'


@pytest.mark.parametrize('field',['question','candidate','runtime','root','source','first_close'])
def test_native_plan_binding_negatives_before_account_entry(tmp_path,monkeypatch,field):
    _,cfg,p,c=fixture(tmp_path,monkeypatch);market=load_reference(cfg['input_ref'])
    plan=band.plan_phase(market,p,c['phases']['VALIDATION'],ZoneInfo('UTC'))
    plan['cost_profile']=COSTS[0]['cost_profile']
    plan['native_policy'].update(namespace='INVENTED',candidate_sha=cfg['code_revision'],runtime_image_id=cfg['runtime_image_id'],
        artifact_root_identity=cfg['artifact_root_identity'],phase='VALIDATION',cost_scenario='BASE')
    if field=='question':plan['native_policy']['question_id']='FOREIGN'
    elif field=='candidate':plan['native_policy']['candidate_sha']='0'*40
    elif field=='runtime':plan['native_policy']['runtime_image_id']='sha256:'+'0'*64
    elif field=='root':plan['native_policy']['artifact_root_identity']['inode']='0'
    elif field=='source':plan['native_policy']['input_sha256']='0'*64
    else:plan['decisions'][0]['day']=plan['decisions'][1]['day']
    events=[]
    from polar.ci_research_native import simulate
    with pytest.raises(ValueError):simulate(plan,events.append)
    assert events==[]


def test_official_source_projection_then_band_config_native_and_saved(tmp_path,monkeypatch):
    """Both official stages use actual frozen assets and the same generated source."""
    import polar.band_source as source
    import polar.candidate_binding as candidate
    import polar.offline_author_binding as offline
    from test_band_source import fixture as source_fixture
    from reference_fixture import write
    from test_reference_input import put
    from polar.reference_input import prepare_input
    from polar.gym_service import code_binding
    from polar.ci_research_service import root_identity
    original_method=source.method_binding;original_revision=candidate.loaded_revision;original_runtime=offline.pair_runtime
    source_dir=tmp_path/'source';source_dir.mkdir()
    root,source_config,spec,parent=source_fixture(source_dir,monkeypatch)
    monkeypatch.setattr(source,'method_binding',original_method)
    monkeypatch.setattr(candidate,'loaded_revision',original_revision)
    monkeypatch.setattr(offline,'pair_runtime',original_runtime)
    repo=Path(__file__).resolve().parents[1]
    contract=repo/'research_candidates/quant_a_vti_bil_band/author_contract.json'
    protocol=repo/'research_candidates/quant_a_vti_bil_band/protocol.md'
    source_config.update(contract_ref=put(source_dir/'actual-contract.json',contract.read_bytes()),
        protocol_ref=put(source_dir/'actual-protocol.md',protocol.read_bytes()),
        code_revision=loaded_revision(),runtime_image_id=os.environ['POLAR_CI_RUNTIME_IMAGE_ID'],code=code_binding())
    domain={'start':'2024-01-31','end':'2024-02-02','count':3}
    purpose=json.loads(Path(spec['purpose_ref']['path']).read_bytes())
    from polar.band_contract import AUTHOR_CANDIDATE
    purpose.update(candidate_revision=AUTHOR_CANDIDATE,author_contract=source_config['contract_ref'],
        protocol=source_config['protocol_ref'],intended_reference_domain_private=domain)
    spec.update(date_range=domain,purpose_ref=put(source_dir/'current-purpose.json',purpose))
    source_config['spec_ref']=put(source_dir/'current-spec.json',spec)
    prepared=prepare_input(source_config,root,128*1024**2)
    account_dir=tmp_path/'account';account_dir.mkdir()
    _,cfg,p,_=fixture(account_dir,monkeypatch)
    manifest=json.loads(Path(prepared['input_ref']['path']).read_bytes())
    schedule=json.loads(Path(manifest['schedule']['path']).read_bytes())['rows'];days=[r['date'] for r in schedule]
    def grid():
        return dict(initial=days[0],terminal=days[-1],nav_dates=days,nav_points=3,return_count=2,
            decisions=[band.event(days[0],days[1],schedule,first=True)],decision_count=1,
            terminal_exit=band.event(days[1],days[2],schedule,terminal=True))
    calendar=dict(schema=band.CALENDAR,source_schedule=parent['schedule'],phases={'VALIDATION':grid(),'FINAL':grid()})
    cfg['calendar_ref']=write(account_dir/'source-calendar.json',calendar);cfg['input_ref']=prepared['input_ref']
    cfg['artifact_root_identity']=root_identity(root)
    p.update(input_sha256=prepared['input_ref']['sha256'],calendar_sha256=cfg['calendar_ref']['sha256'])
    cfg['profile_ref']=write(account_dir/'source-profile.json',p)
    service=ReferenceResearchService(root,128*1024**2)
    assert service.preflight(cfg)['policy_execution']=='NOT_RUN'
    result=service.run(cfg);assert result['status']=='SUCCESS'
    assert service.recompute(result['semantic_id'])['status']=='REPRODUCED'

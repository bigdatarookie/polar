"""Invented source reader, charged Service lifecycle and private saved-only read."""
from dataclasses import replace,asdict
from pathlib import Path
from copy import deepcopy
from datetime import datetime,timezone
import json,os
import pytest
from polar.gym_contract import canonical,sha
from polar.history_bundle import canonical as source_canonical
from polar.gym_service import code_binding
from polar.ci_research_service import root_identity
from polar.reference_service import ReferenceResearchService
from polar.event_study import StudyBinding,plain,DEFINITION,DEFINITION_PINS,QUESTION,PROTOCOL
from polar.event_native import LEGS,COSTS,EventInstruction
from polar.scheduled_event_controller import request_from_event,digest
from test_event_study import study_inputs,iso


def put(path,value):
    raw=value if type(value) is bytes else canonical(value);path.write_bytes(raw)
    return {'path':str(path),'sha256':sha(raw),'bytes':len(raw)}


def fixture(tmp_path,*,full=False):
    tmp_path.mkdir(parents=True,exist_ok=True);p,side,roles,b=full_study_inputs() if full else study_inputs()
    # Same caller-owned synthetic locator recipe as the real metadata contract,
    # not invented provider IDs or source prices reconstructed from results.
    input_id='INVENTED-source-view/'+sha(b'INVENTED CALENDAR STUDY SOURCE')
    source=tuple(replace(r,source_id=input_id+'/'+r.symbol+'/'+r.date) for r in p.source)
    roles['input_id']=input_id;roles['source_rows']=plain([{k:v for k,v in asdict(r).items() if k!='price_micro'} for r in source])
    for name in ('baseline','conditional'):
        for row in side[name]['events']:
            if row['cancelled']:continue
            # January NY14:00 cutoff plus60s, still before21:00 close.
            from zoneinfo import ZoneInfo
            day=datetime.fromtimestamp(row['decision_ns']//10**9,timezone.utc).date()
            row['decision_ns']=int(datetime(day.year,day.month,day.day,14,1,tzinfo=ZoneInfo('America/New_York')).timestamp())*10**9
            clock=json.loads(row['clock_json']);clock['decision_at']=iso(row['decision_ns']);row['clock_json']=json.dumps(clock,sort_keys=True,separators=(',',':'));row['clock_pin']=digest(clock)
    sidepin=put(tmp_path/'sidecar.json',side);rolepin=put(tmp_path/'roles.json',roles)
    b=replace(b,input_id=input_id,roles_sha256=sha(canonical(roles)),calendar_sha256=sha(canonical(side)))
    bp=put(tmp_path/'binding.json',plain(asdict(b)))
    dates=sorted({r.date for r in source});rows=[]
    for i,d in enumerate(dates):rows.append({'date':d,'reference_open_utc':d+'T14:30:00Z','reference_close_utc':d+'T21:00:00Z',
        'next_reference_date':dates[i+1] if i+1<len(dates) else None,'month_end_in_reference_range':False})
    sp=put(tmp_path/'schedule.json',{'schema':'polar.xnys-reference-schedule/1','rows':rows})
    members=[];jobs={};parents={};source_rows=[];selected={(r.symbol,r.date):r for r in source}
    for n in ('BIL','VTI'):
        parent={'job_id':'INVENTED-JOB/'+n,'source_record_ids':['INVENTED-RECORD/'+n]};ph=sha(source_canonical(parent));parents[ph]=parent
        jobs['INVENTED-CAPTURE/'+n]={'parent_relation_sha256':ph,'source_plan_job_id':parent['job_id'],
            'request':{'symbols':n},'source_record_ids':parent['source_record_ids']}
        members.append({'sha256':sha(('INVENTED-NORMALIZED/'+n).encode())})
    relations=put(tmp_path/'relations.json',{'schema':'polar.reference-source-relations/1','jobs':jobs,'parent_relations':parents})
    for i,d in enumerate(dates):
        for n in ('BIL','VTI'):
            r=selected[n,d];ph=next(k for k,v in parents.items() if v['job_id']=='INVENTED-JOB/'+n)
            price=f'{r.price_micro//10**6}.{r.price_micro%10**6:06d}'
            source_ref={'normalized_member_sha256':sha(('INVENTED-NORMALIZED/'+n).encode()),'line_1based':i+1,
                'line_sha256':sha((n+d).encode()),'original_source_reference':{'raw_file':'INVENTED/'+n+'.json',
                'source_body_sha256':sha(('INVENTED-RAW/'+n).encode()),'source_array':'bars/'+n,'source_row_ordinal':i,
                'job_id':'INVENTED-CAPTURE/'+n,'request_id':None,'page':0},'query_symbol':n,'source_symbol':n,'parent_relation_sha256':ph}
            source_rows.append({'symbol':n,'date':d,'reference_quote':price,'source_adjusted_close_token':price,
                'source_ref':source_ref,'observed_published_at':None,'observed_historical_available_at':None})
    quotes=put(tmp_path/'quotes.ndjson',b''.join(canonical(v) for v in source_rows))
    original_roles=put(tmp_path/'original-date-roles.json',{'schema':'polar.reference-source-date-roles/1','source_dates':dates,'symbols':['BIL','VTI'],
        'NAV':{'dates':roles['nav_dates'],'symbols':['BIL','VTI']},
        'WARMUP_CANDIDATE':{'dates':[r.date for r in source if r.symbol=='VTI' and r.role!='NAV'],'symbols':['VTI']},
        'UNUSED_WARMUP_CONTEXT':{'dates':[r.date for r in source if r.symbol=='BIL' and r.role!='NAV'],'symbols':['BIL']}})
    ip=put(tmp_path/'input.json',{'schema':'polar.synthetic-reference-source-input/2','parent_dataset_revision':input_id,
        'symbols':['BIL','VTI'],'quote_basis':'VENDOR_ALL_ADJUSTED_REFERENCE_CLOSE','unit_type':'SYNTHETIC_REFERENCE_UNIT_NOT_RAW_SHARE',
        'double_action_policy':'NO_ADDITIONAL_SPLIT_DIVIDEND_CREDIT_IN_REFERENCE_UNIT_MODEL','rights':'INVENTED_PUBLIC_TEST',
        'provenance':{'kind':'DETERMINISTIC_INVENTED_FIXTURE','producer':'polar-public-tests','source_payloads':'NONE'},
        'dates':{'count':len(dates),'start':dates[0],'end':dates[-1]},'rows':len(source),
        'conversion_metadata':{'date_roles':original_roles},'schedule':sp,'quotes':quotes,'source_members':members,'source_relations':relations})
    loc=put(tmp_path/'locators.json',{'schema':'polar.source-date-role-metadata-locators/1','rows':[{'source_id':r.source_id,
        'identity_kind':'CALLER_METADATA_LOCATOR_NOT_PROVIDER_PERMANENT_ID','input_manifest':ip,
        'original_role_pin':original_roles,'original_schedule_row_date':r.date,'symbol':r.symbol,'observed_quote_K':None,
        'modeled_quote_K':r.available_ns} for r in source],'source_values_read':False,'observed_quote_K':None,
        'source_id_contract':'input_id/symbol/date CALLER METADATA NOT PROVIDER PERMANENT ID'})
    refs={'protocol':put(tmp_path/'protocol.json',{'id':PROTOCOL,'invented':True}),
        'input':ip,'sidecar':sidepin,'roles':rolepin,'study_binding':bp,'locators':loc,
        'timezone':put(tmp_path/'New_York',Path('/usr/share/zoneinfo/America/New_York').read_bytes())}
    profile={'schema':'polar.calendar-study-profile/1','protocol_id':PROTOCOL,'question_id':QUESTION,'definition':DEFINITION,
        'definition_pins':DEFINITION_PINS,'legs':list(LEGS),'cost_scenarios':plain(COSTS),'capital_cents':10000000,
        'file_pins':{k:v['sha256'] for k,v in refs.items()},'daily_clock':'FIXED_UTC00_01_NEXT_ELIGIBLE_CLOSE','public_projection':'PRIVATE_STUDY_ONLY'}
    refs['profile']=put(tmp_path/'profile.json',profile)
    root=tmp_path/'artifacts';root.mkdir();service=ReferenceResearchService(root,(1024 if full else 256)*1024**2)
    config={'schema':'polar.calendar-study-config/1','namespace':'INVENTED',**{k+'_ref':v for k,v in refs.items()},
        'code':code_binding(),'code_revision':'a'*40,'runtime_image_id':'sha256:'+'b'*64,
        'candidate_id':'INVENTED-CANDIDATE','experiment_id':'INVENTED-EXPERIMENT','artifact_root_identity':root_identity(root),
        'execution_authority_ref':None}
    return service,config,quotes


def test_metadata_preflight_does_not_read_prices_or_debit(tmp_path,monkeypatch):
    import polar.calendar_study_service as module
    service,cfg,quotes=fixture(tmp_path)
    def forbidden(*a,**k):raise AssertionError('SOURCE_VALUES_OR_NATIVE_FORBIDDEN')
    monkeypatch.setattr(module,'load_reference',forbidden);monkeypatch.setattr(module,'bounded_native',forbidden)
    r=service.preflight(cfg)
    assert r['scientific_starts']==r['source_values_read']==0 and r['native_accounts']==10
    assert not (service.store.root/'scheduled-reference-attempts').exists()


def test_actual_service_original10_and_source_absent_success_only_read(tmp_path,record_property):
    from polar.event_native_witness import encode
    service,cfg,quotes=fixture(tmp_path)
    result=service.run(cfg);assert result['status']=='SUCCESS' and result['native_accounts']==10
    diag=json.loads(next((service.store.root/'scheduled-reference-attempts').glob('*/*/finish/diagnostics.json')).read_text())
    assert sum(v['phase']=='ACCOUNT_SAVED_WITNESS' for v in diag)==10
    before={str(p):(sha(p.read_bytes()),p.stat().st_mtime_ns) for p in service.store.root.rglob('*') if p.is_file()}
    Path(quotes['path']).unlink()
    replay=service.recompute(result['semantic_id'])
    assert replay['status']=='REPRODUCED' and replay['native_calls']==replay['source_reads']==replay['writes']==0
    assert before=={str(p):(sha(p.read_bytes()),p.stat().st_mtime_ns) for p in service.store.root.rglob('*') if p.is_file()}
    # Fresh process refuses native imports, source access and all write opens.
    import subprocess,sys
    code=r"""
import sys,json,os,importlib.abc,builtins,io
class NoNative(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname.startswith('nautilus_trader'):raise RuntimeError('NATIVE_IMPORT_FORBIDDEN')
sys.meta_path.insert(0,NoNative())
from polar.reference_service import ReferenceResearchService
import polar.calendar_study_service as module
service=ReferenceResearchService(sys.argv[1],int(sys.argv[3]))
def forbidden(*a,**k):raise RuntimeError('SOURCE_NATIVE_FORBIDDEN')
module.load_reference=forbidden;module.bounded_native=forbidden
old=os.open
def ro(p,flags,*a,**kw):
 if flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_APPEND|os.O_TRUNC):raise RuntimeError('WRITE_OPEN_FORBIDDEN')
 return old(p,flags,*a,**kw)
os.open=ro
def guard(fn):
 def wrapped(p,mode='r',*a,**kw):
  if any(c in mode for c in 'wa+x'):raise RuntimeError('WRITE_OPEN_FORBIDDEN')
  return fn(p,mode,*a,**kw)
 return wrapped
builtins.open=guard(builtins.open);io.open=guard(io.open)
r=service.recompute(sys.argv[2]);print(json.dumps({k:r[k] for k in ('status','native_calls','source_reads','writes')}))
"""
    proof=subprocess.run([sys.executable,'-c',code,str(service.store.root),result['semantic_id'],str(service.store.limit)],
        env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'},capture_output=True,text=True,timeout=30)
    assert proof.returncode==0,proof.stderr
    assert json.loads(proof.stdout)=={'status':'REPRODUCED','native_calls':0,'source_reads':0,'writes':0}
    assert before=={str(p):(sha(p.read_bytes()),p.stat().st_mtime_ns) for p in service.store.root.rglob('*') if p.is_file()}
    with pytest.raises(Exception):service.run(cfg)
    record_property('invented_calendar_service' ,json.dumps({'finish':encode(result),'reproduction':replay},sort_keys=True))


@pytest.mark.parametrize('change',['root','code','sidecar','roles','binding','profile','locators','namespace','runtime','authority'])
def test_malformed_current_binding_refused_before_debit(tmp_path,monkeypatch,change):
    import polar.calendar_study_service as module
    service,cfg,_=fixture(tmp_path)
    if change=='root':cfg['artifact_root_identity']['inode']='wrong'
    elif change=='code':cfg['code']={}
    elif change=='runtime':cfg['runtime_image_id']='not-an-image'
    elif change=='namespace':cfg['namespace']='RETAINED'
    elif change=='authority':cfg['execution_authority_ref']=put(tmp_path/'bad-authority.json',{'schema':'NOT_OPERATIVE'})
    else:
        ref=cfg[('study_binding' if change=='binding' else change)+'_ref']
        data=json.loads(Path(ref['path']).read_text());data['unbound_extra']='corrupt'
        Path(ref['path']).write_bytes(canonical(data))
    def forbidden(*a,**k):raise AssertionError('SOURCE_OR_NATIVE_BEFORE_DEBIT')
    monkeypatch.setattr(module,'load_reference',forbidden);monkeypatch.setattr(module,'bounded_native',forbidden)
    with pytest.raises(Exception):service.run(cfg)
    assert not (service.store.root/'scheduled-reference-attempts').exists()


def test_failed_after_debit_preserved_and_duplicate_does_not_retry(tmp_path,monkeypatch):
    import polar.calendar_study_service as module
    from polar.ci_research_service import NativeFailure
    service,cfg,_=fixture(tmp_path)
    def failure(*args,**kwargs):raise NativeFailure('INVENTED_NATIVE_INTERRUPTION',[{'phase':'NATIVE_RUN_ENTERED','leg':'FULL_VTI'}])
    monkeypatch.setattr(module,'bounded_native',failure)
    with pytest.raises(NativeFailure):service.run(cfg)
    families=list((service.store.root/'scheduled-reference-attempts').iterdir());attempts=list(families[0].iterdir())
    assert len(families)==len(attempts)==1
    finish=json.loads((attempts[0]/'finish/record.json').read_text())
    assert finish['status']=='FAILED_UNFINALIZED' and finish['native_entry_count']==1 and finish['completed_native_accounts']==0
    assert finish['refund'] is finish['automatic_retry'] is False
    with pytest.raises(Exception,match='ALREADY_RECORDED'):service.run(cfg)
    assert len(list(families[0].iterdir()))==1


def test_service_facade_and_cli_metadata_entrypoint(tmp_path,monkeypatch):
    from polar.service import Service
    from polar.config import Settings
    import subprocess,sys
    service,cfg,_=fixture(tmp_path)
    facade=Service(Settings('unused-file-only',service.store.root,storage_bytes=service.store.limit))
    assert facade.research_preflight(cfg)['native_accounts']==10
    path=tmp_path/'config.json';path.write_bytes(canonical(cfg))
    r=subprocess.run([sys.executable,'-m','polar.cli','research-preflight',str(path)],
        env={**os.environ,'POLAR_ARTIFACT_ROOT':str(service.store.root),'POLAR_STORAGE_BYTES':str(service.store.limit)},capture_output=True,text=True)
    assert r.returncode==0,r.stderr
    assert json.loads(r.stdout)['source_values_read']==0


def authority_fixture(tmp_path,service,cfg):
    from polar.calendar_study_service import binding,family,prepare
    p,b,*_=prepare(service,cfg)
    method=put(tmp_path/'method.json',{'schema':'polar.prospective-method-disposition/1','method_verdict':'PASS',
        'protocol':{'sha256':cfg['protocol_ref']['sha256']},'candidate_id':cfg['candidate_id'],'scope':'INVENTED_ONLY'})
    card=put(tmp_path/'card.json',{'schema':'polar.native-hypothesis-reservation/1','state':'RESERVED',
        'candidate_id':cfg['candidate_id'],'experiment_registration_id':cfg['experiment_id'],'scope':'INVENTED_ONLY'})
    qual=put(tmp_path/'qa.json',{'schema':'polar.ci-result/1','status':'PASS','candidate_sha':cfg['code_revision'],
        'selection':['tests'],'scope':'INVENTED_FIXTURE_NOT_ACTUAL_QUALIFICATION'})
    value={'schema':'polar.scheduled-reference-operation/1','action':'ORIGINAL','binding_sha256':sha(canonical(binding(cfg))),
        'allowed_fit_calls':0,'allowed_predict_calls':0,'allowed_model_calls':0,'allowed_score_calls':0,
        'allowed_rank_calls':0,'allowed_estimator_calls':0,'allowed_optimizer_calls':0,'allowed_bootstrap_samples':0,
        'allowed_native_accounts':10,'allowed_sma_observations':2*(len(b.nav_ns)-2),
        'method_ref':method,'candidate_ref':card,'qualification_ref':qual,'family':family(cfg,p),'expected_prior_attempts':[],
        'artifact_root_identity':root_identity(service.store.root),'actor_uid':os.getuid(),'actor_gid':os.getgid(),
        'resources':{'native_wall_seconds':60,'stored_wall_seconds':60,'cleanup_wall_seconds':10,
            'remaining_family_wall_seconds':130,'storage_upper_bound_bytes':200*1024**2}}
    return value


@pytest.mark.parametrize('field',['valid','wrong_method','wrong_card','wrong_qa','wrong_actor','wrong_family','missing_resources','wall','storage','boolean_count'])
def test_explicit_invented_authority_metadata_and_resources_before_debit(tmp_path,monkeypatch,field):
    import polar.calendar_study_service as module
    service,cfg,_=fixture(tmp_path);grant=authority_fixture(tmp_path,service,cfg)
    if field=='wrong_method':grant['method_ref']['sha256']='0'*64
    elif field=='wrong_card':grant['candidate_ref']['sha256']='0'*64
    elif field=='wrong_qa':grant['qualification_ref']['sha256']='0'*64
    elif field=='wrong_actor':grant['actor_uid']+=1
    elif field=='wrong_family':grant['family']='0'*64
    elif field=='missing_resources':grant.pop('resources')
    elif field=='wall':grant['resources']['remaining_family_wall_seconds']=1
    elif field=='storage':grant['resources']['storage_upper_bound_bytes']=service.store.limit+1
    elif field=='boolean_count':grant['allowed_model_calls']=False
    cfg['execution_authority_ref']=put(tmp_path/'authority.json',grant)
    def forbidden(*a,**k):raise AssertionError('NO_PRICE_OR_NATIVE_IN_PREFLIGHT')
    monkeypatch.setattr(module,'load_reference',forbidden);monkeypatch.setattr(module,'bounded_native',forbidden)
    if field=='valid':
        r=service.preflight(cfg);assert r['namespace']=='INVENTED' and r['execution_authority'] is True and r['scientific_starts']==0
    else:
        with pytest.raises(Exception):service.preflight(cfg)
    assert not (service.store.root/'scheduled-reference-attempts').exists()


def full_study_inputs():
    """Independent invented calendar, no retained dates/tokens or metadata copied."""
    from datetime import date,timedelta
    from polar.event_native import ReferenceClose,DecisionPoint
    from polar.event_study import make_sidecar,cluster_intervals
    from polar.scheduled_event_controller import Calendar
    p,side,roles,b=study_inputs();days=[];d=date(2024,1,2)
    while len(days)<716:
        if d.weekday()<5:days.append(d.isoformat())
        d+=timedelta(days=1)
    warm=[(date(2024,1,2)-timedelta(days=i)).isoformat() for i in range(200,0,-1)]
    def at(day,h=21,m=0):return int(datetime.fromisoformat(day).replace(hour=h,minute=m,tzinfo=timezone.utc).timestamp())*10**9
    source=[]
    for symbol in ('BIL','VTI'):
        for i,day in enumerate(warm+days):
            source.append(ReferenceClose(symbol,day,at(day),at((date.fromisoformat(day)+timedelta(days=1)).isoformat(),0),
                10000000+(i*1000 if symbol=='VTI' else i*10),f'INVENTED_FULL/{symbol}/{day}',
                'NAV' if i>=200 else 'VTI_WARMUP_CANDIDATE' if symbol=='VTI' else 'BIL_UNUSED_WARMUP_CONTEXT'))
    baseline=[];conditional=[];members=[]
    for n in range(32):
        i=2+21*n;eid=f'INVENTED_EVENT_{n:02}'
        for name,out,status in [('baseline',baseline,'NOT_EXECUTABLE'),('conditional',conditional,'CONDITIONALLY_MODELED')]:
            row=deepcopy(side[name]['events'][0]);row.update(event_id=eid,anchor_ns=at(days[i]),decision_ns=at(days[i],19,1),
                candidate_ns=at(days[i]),expiry_ns=at(days[i+2]),reentry_decision_ns=at(days[i+3],0,1),reentry_candidate_ns=at(days[i+3]))
            clock=json.loads(row['clock_json']);clock.update(event_id=eid,prior_reference_date=days[i],decision_at=iso(row['decision_ns']),
                execution_candidate_at=iso(row['candidate_ns']),expiry_at=iso(row['expiry_ns']),
                reentry_decision_at=iso(row['reentry_decision_ns']),reentry_candidate_at=iso(row['reentry_candidate_ns']))
            row.update(clock_pin=digest(clock),clock_json=json.dumps(clock,sort_keys=True,separators=(',',':')))
            from polar.scheduled_event_controller import CalendarEvent
            row['reasons']=tuple(row['reasons']);out.append(CalendarEvent(**row))
        members.append({'event_id':eid,'status':'REVISED' if n<3 else 'SCHEDULED','provenance':'INVENTED_CALENDAR_SOURCE','source_ref':'INVENTED/'+eid})
    from polar.scheduled_event_controller import CalendarEvent
    cancelled=CalendarEvent('INVENTED_CANCELLED',True,None,None,None,None,None,None,'CANCELLED',None,None,'INVENTED_CANCELLED',(),False)
    baseline.append(cancelled);conditional.append(cancelled)
    members.append({'event_id':cancelled.event_id,'status':'CANCELLED','provenance':'INVENTED_CALENDAR_SOURCE','source_ref':'INVENTED/CANCELLED'})
    def cal(rows):return Calendar(tuple(rows),tuple(c['members'] for c in cluster_intervals(rows)),())
    side=make_sidecar(members,cal(baseline),cal(conditional),side['assumptions'])
    roles.update(nav_ns=[at(d) for d in days],nav_dates=days,
        daily_decisions=[{'decision_ns':at(d,0,1),'q_ns':at(d)} for d in days[1:]],
        source_rows=plain([{k:v for k,v in asdict(r).items() if k!='price_micro'} for r in source]))
    b=replace(b,calendar_sha256=sha(canonical(side)),roles_sha256=sha(canonical(roles)),
        member_statuses=tuple((r['event_id'],r['status']) for r in members),nav_ns=tuple(roles['nav_ns']),nav_dates=tuple(days))
    return replace(p,source=tuple(source),nav_closes=b.nav_ns),side,roles,b


def test_full716_nav916_source33_metadata_service_capacity(tmp_path,record_property):
    service,cfg,quotes=fixture(tmp_path,full=True)
    pre=service.preflight(cfg);assert pre['sma_observations']==1428
    result=service.run(cfg);assert result['native_accounts']==10
    used=service.store.used();largest=max(p.stat().st_size for p in service.store.root.rglob('*') if p.is_file())
    Path(quotes['path']).unlink();r=service.recompute(result['semantic_id'])
    assert r['status']=='REPRODUCED' and r['native_calls']==r['writes']==r['source_reads']==0
    record_property('invented_full_service_capacity',json.dumps({'NAV':716,'source_dates':916,'metadata_members':33,
        'native_accounts':10,'stored_bytes':used,'largest_member_bytes':largest,'store_limit':service.store.limit,'status':r['status']}))



def test_typed_partial_native_evidence_is_saved_before_failed_finish(tmp_path,monkeypatch):
    import polar.calendar_study_service as module
    from polar.ci_research_service import NativeFailure
    from fractions import Fraction
    service,cfg,_=fixture(tmp_path)
    def interrupted(*a,diagnostics_callback,**kw):
        summary=diagnostics_callback({'phase':'ACCOUNT_PARTIAL','leg':'SMA200','cost_id':'BASE','error':'INVENTED_FAILURE',
            'evidence':{'status':'FAILED_UNFINALIZED','exact':Fraction(1,3),'positions':{'VTI':2}}})
        raise NativeFailure('INVENTED_NATIVE_INTERRUPTION',[{'phase':'NATIVE_RUN_ENTERED','leg':'SMA200'},summary])
    monkeypatch.setattr(module,'bounded_native',interrupted)
    with pytest.raises(NativeFailure):service.run(cfg)
    attempt=next((service.store.root/'scheduled-reference-attempts').glob('*/*'))
    diagnostics=json.loads((attempt/'finish/diagnostics.json').read_text())
    ref=diagnostics[-1]['evidence_ref'];raw=(service.store.root/ref['path']).read_bytes()
    assert sha(raw)==ref['sha256'] and len(raw)==ref['bytes']
    assert json.loads(raw)['exact']=={'$fraction':[1,3]}
    assert json.loads((attempt/'finish/record.json').read_text())['native_entry_count']==1


@pytest.mark.parametrize('axis',['known_at_close','known_null','daily_previous_day'])
def test_rehashed_closed_clock_mutants_refused_before_source_or_debit(tmp_path,monkeypatch,axis):
    import polar.calendar_study_service as module
    service,cfg,_=fixture(tmp_path)
    roles=json.loads(Path(cfg['roles_ref']['path']).read_text())
    loc=json.loads(Path(cfg['locators_ref']['path']).read_text())
    if axis=='daily_previous_day':
        # Monday close with an otherwise ordered Sunday00:01 decision.
        daily=next(d for d in roles['daily_decisions'] if iso(d['q_ns'])[:10]=='2024-01-08')
        daily['decision_ns']-=86400*10**9
        reason='CALENDAR_FIXED_UTC_DAILY_SCOPE'
    else:
        row=roles['source_rows'][0]
        row['available_ns']=row['close_ns'] if axis=='known_at_close' else None
        next(v for v in loc['rows'] if v['source_id']==row['source_id'])['modeled_quote_K']=row['available_ns']
        reason='CALENDAR_NEXT_CIVIL_MIDNIGHT'
    cfg['roles_ref']=put(Path(cfg['roles_ref']['path']),roles)
    cfg['locators_ref']=put(Path(cfg['locators_ref']['path']),loc)
    binding=json.loads(Path(cfg['study_binding_ref']['path']).read_text());binding['roles_sha256']=sha(canonical(roles))
    cfg['study_binding_ref']=put(Path(cfg['study_binding_ref']['path']),binding)
    profile=json.loads(Path(cfg['profile_ref']['path']).read_text())
    profile['file_pins']={k:cfg[k+'_ref']['sha256'] for k in module.REFS if k!='profile'}
    cfg['profile_ref']=put(Path(cfg['profile_ref']['path']),profile)
    def forbidden(*a,**k):raise AssertionError('SOURCE_OR_NATIVE_FORBIDDEN')
    monkeypatch.setattr(module,'load_reference',forbidden);monkeypatch.setattr(module,'bounded_native',forbidden)
    with pytest.raises(Exception,match=reason):service.preflight(cfg)
    assert not (service.store.root/'scheduled-reference-attempts').exists()

from dataclasses import replace
from datetime import datetime,timezone,timedelta
from fractions import Fraction as F
import pytest
from polar.signed_pair_input import PairInput,Quote,Formation,decision_targets,preflight
from polar.signed_pair_producer import produce_account,factor


def fixture(nav_count=27,formations=2):
    start=datetime(2022,1,1,21,tzinfo=timezone.utc);dates=[start+timedelta(days=i) for i in range(252+nav_count)]
    clocks=tuple(int(d.timestamp())*10**9 for d in dates)
    quotes=tuple(Quote(n,d.date().isoformat(),t,t+3*3600*10**9,'10','10' if n=='AAPL' else '9',
        f'/raw/{i}/c',f'/signal/{i}/c','INVENTED_RAW_'+n,'INVENTED_SIGNAL_'+n,'INVENTED/'+n+'/'+str(i))
        for n in ('AAPL','AMZN') for i,(t,d) in enumerate(zip(clocks,dates)))
    nav=clocks[252:]
    chosen=[252+i for i in range(formations)]
    fs=tuple(Formation('formation-'+str(i),g,clocks[g]+(3*3600+60)*10**9,clocks[g+1],g-21,g-252) for i,g in enumerate(chosen))
    return PairInput('INVENTED','INVENTED_INPUT','INVENTED_PURPOSE',(('source','a'*64),),quotes,nav,fs,(),
        nav[-2]+(3*3600+60)*10**9,nav[-1])


def test_exact_ranking_negative_and_tie_and_own_d_nav_no_q_argument():
    args=({'AAPL':'10','AMZN':'20'},{'AAPL':'5','AMZN':'6'},{'AAPL':'10','AMZN':'10'})
    r=decision_targets('DYNAMIC_SPREAD',100000,*args)
    assert r['long']=='AMZN' and r['short']=='AAPL' and all(v<0 for v in r['scores'].values())
    assert r['targets']=={'AAPL':-50,'AMZN':25} and not r['Q_price_consumed']
    tie=decision_targets('DYNAMIC_SPREAD',100000,{'AAPL':'10','AMZN':'10'},{'AAPL':'1','AMZN':'1'},{'AAPL':'1','AMZN':'1'})
    assert tie['long']=='AAPL'
    smaller=decision_targets('DYNAMIC_SPREAD',50000,*args)
    assert smaller['targets']=={'AAPL':-25,'AMZN':12}
    with pytest.raises(TypeError):decision_targets('DYNAMIC_SPREAD',100000,*args,future_quote={'AAPL':'1'})


@pytest.fixture(scope='module')
def accounts():
    data=fixture()
    return data,[produce_account(data,c,'BASE') for c in ('DYNAMIC_SPREAD','DYNAMIC_HALF_LONG','RF0_CASH')]


def test_actual_causal_d_book_and_half_long_no_locate_and_cash(accounts,record_property):
    from polar.signed_event_saved import encode
    import json
    data,outputs=accounts
    for out in outputs:
        assert len(out['NAV'])==27 and len(out['D_receipts'])==2
        for d in out['D_receipts']:
            records=out['packet']['records'];end=records[d['actual_D_END_sequence']]
            assert end['kind']=='END' and end['state']==d['actual_D_state']
            assert d['sizing']['own_D_equity_cents']==d['own_D_report']['equity_cents']
        assert not any(q for _,q in out['packet']['final_state'].positions)
    half,cash=outputs[1:]
    assert not any(r['kind']=='LOCATE_RESERVED' for r in half['packet']['records'])
    assert not any(r['kind']=='FILL' for r in cash['packet']['records'])
    assert all(q>=0 for row in half['NAV'] for _,q in row['state'].positions)
    record_property('invented_pair_accounts',json.dumps(encode(outputs),sort_keys=True))



def test_private_saved_account_has_no_source_native_or_write_replay(accounts,tmp_path):
    from polar.signed_pair_saved import binding_for,verify_account,publish_account,verify_stored_account
    from polar.signed_pair_metrics import metrics
    from polar.gym_store import GymStore
    from copy import deepcopy
    data,outputs=accounts;b=binding_for(data);store=GymStore(tmp_path,128*1024**2)
    for a in outputs:
        assert verify_account(a,b)['status']=='VERIFIED_PRIVATE_PAIR_ACCOUNT'
        ref=publish_account(store,a,b);assert verify_stored_account(tmp_path,ref,b)==a
        report=metrics(a)
        assert report['n']==26 and report['terminal_cents']<=10000000
    a=deepcopy(outputs[0]);a['D_receipts'][0]['sizing']['targets']['AAPL']+=1
    with pytest.raises(Exception,match='FLOOR'):verify_account(a,b)


def test_metric_zero_negative_economic_failure_not_shortened(accounts):
    from polar.signed_pair_metrics import metrics
    from copy import deepcopy
    _,outputs=accounts;a=deepcopy(outputs[0])
    a['NAV'][5]['nav_cents']=-1;a['NAV'][5]['default_ever']=True
    r=metrics(a)
    assert r['n']==26 and r['maximum_deficit_cents']==1
    assert r['drawdown']['maximum']>1 and not r['survival']
    assert r['variance']['reason']=='INAPPLICABLE_NONPOSITIVE_NAV_OR_DEFAULT'


def test_d50_ambient_context_does_not_change_metrics(accounts):
    from polar.signed_pair_metrics import metrics
    from decimal import localcontext
    _,outputs=accounts;expected=metrics(outputs[0])
    with localcontext() as c:
        c.prec=6
        assert metrics(outputs[0])==expected


@pytest.mark.parametrize('control',['DYNAMIC_HALF_LONG','DYNAMIC_SPREAD'])
def test_fullshape_967marks47formations15actions_saved_account(tmp_path,record_property,control):
    from polar.signed_event_driver import Action
    from polar.signed_pair_saved import binding_for,verify_account,publish_account,verify_stored_account
    from polar.signed_event_saved import encode
    from polar.gym_store import GymStore
    import json
    data=fixture(nav_count=967,formations=47)
    # Explicit invented source-only census; not actual dates or an allocation.
    actions=tuple(Action('INVENTED_DIV_'+str(i),'AAPL','CASH_DISTRIBUTION',F(1,100),
        data.quotes[252+100+i*40].date,data.quotes[252+102+i*40].date,'USD','INVENTED_ACTION/'+str(i)) for i in range(15))
    data=replace(data,actions=actions,nominal_action_tokens=tuple((a.id,'0.01') for a in actions))
    account=produce_account(data,control,'BASE');binding=binding_for(data)
    assert len(account['NAV'])==967 and len(account['D_receipts'])==47
    assert len(account['packet']['final_state'].claims)==15
    assert all(c.paid_at is not None for c in account['packet']['final_state'].claims)
    ref=publish_account(GymStore(tmp_path,512*1024**2),account,binding)
    restored=verify_stored_account(tmp_path,ref,binding)
    assert restored==account
    record_property('invented_fullshape_pair_capacity',json.dumps({'control':control,'NAV':967,
        'formations':47,'captured_actions':15,'account_ref':ref,'packet_record_count':len(account['packet']['records']),
        'not_full_48_native_campaign':True},sort_keys=True))


@pytest.mark.parametrize('case',['SHORT_1P5','RECALL_BLACKOUT2','SHORT_5','LOCATE_DENIED'])
def test_actual_prebound_candidate_activation_failure_and_comparator_scope(case,record_property,tmp_path):
    from polar.signed_pair_metrics import metrics
    from polar.signed_pair_saved import binding_for,verify_account
    from polar.signed_event_saved import encode
    import json
    data=fixture();candidate=produce_account(data,'DYNAMIC_SPREAD',case)
    half=produce_account(data,'DYNAMIC_HALF_LONG',case,activation=candidate['activation'])
    assert half['activation']==candidate['activation']
    verify_account(candidate,binding_for(data));verify_account(half,binding_for(data),candidate)
    records=candidate['packet']['records'];activation=candidate['activation']
    if case=='LOCATE_DENIED':
        assert activation['status']=='ACTIVATED' and activation['kind']=='DENIED_VALID_SHORT_ENTRY_ATTEMPT'
        assert activation['witnesses']
        assert not any(r['kind']=='FILL' for r in records)
        assert any(r['kind']=='FILL' for r in half['packet']['records'])
    else:
        assert activation['status']=='ACTIVATED' and activation['short']=='AMZN' and activation['long']=='AAPL'
        assert not activation['candidate_prefix_repeated']
    if case=='RECALL_BLACKOUT2':
        from polar.signed_pair_saved import publish_account,verify_stored_account
        from polar.gym_store import GymStore
        with pytest.raises(Exception,match='STANDALONE_CONTROL_REQUIRES_CANDIDATE'):verify_account(half,binding_for(data))
        ref=publish_account(GymStore(tmp_path,128*1024**2),half,binding_for(data),candidate)
        assert verify_stored_account(tmp_path,ref,binding_for(data))==half
        shock=data.nav_closes.index(activation['shock_ns'])
        fills=[r for r in records if r['kind']=='FILL' and r['command'].name=='AMZN' and r['command'].side=='BUY' and r['native_clock']['execution_ns']>=activation['shock_ns']]
        assert fills and fills[0]['native_clock']['execution_ns']>=data.nav_closes[shock+3]
        assert not any(r['kind']=='FLATTEN_QUEUED' and 'RECALL' in r['flatten']['reasons'] for r in half['packet']['records'])
    if case=='SHORT_5':
        report=metrics(candidate)
        assert report['default_ever'] and not report['survival'] and report['variance']['status']=='UNAVAILABLE'
        assert all(r['kind']!='ORDER_COMMAND' or not r['command'].phase.startswith('NEW_') for r in
            records[next(i for i,r in enumerate(records) if r['kind']=='MARK' and r['reconciliation']['core']['equity_cents']<=0):])
    record_property('invented_pair_scenario',json.dumps(encode({'candidate':candidate,'comparator':half}),sort_keys=True))


def test_partial_study_keeps_prior_accounts_and_unknown_entry_not_zero(monkeypatch):
    import polar.signed_pair_producer as producer
    seen=[]
    def partial(data,c,p,**kwargs):
        if seen:raise RuntimeError('INVENTED_PRE_NATIVE_TRANSPORT_ERROR')
        seen.append((c,p));return {'control':c,'case':p,'activation':None}
    monkeypatch.setattr(producer,'produce_account',partial)
    with pytest.raises(producer.PairStudyFailure) as exc:producer.produce_pair_study(fixture())
    e=exc.value.evidence
    assert e['actual_completed']==1 and len(e['completed_accounts'])==1
    assert e['actual_total_entries'] is None and e['entry_count_status']=='UNKNOWN_NOT_ASSUMED_ZERO'


def test_saved_account_fresh_process_no_native_import_write_open(accounts,tmp_path):
    from polar.signed_pair_saved import binding_for,publish_account
    from polar.signed_event_saved import encode
    from polar.gym_contract import canonical,sha
    from polar.gym_store import GymStore
    import os,subprocess,sys,json
    data,outputs=accounts;binding=binding_for(data);ref=publish_account(GymStore(tmp_path,128*1024**2),outputs[0],binding)
    before={str(p):(sha(p.read_bytes()),p.stat().st_mtime_ns) for p in tmp_path.rglob('*') if p.is_file()}
    code=r'''
import sys,importlib.abc,json,builtins,io,os
class Guard(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname.startswith('nautilus_trader'):raise RuntimeError('NATIVE_IMPORT_FORBIDDEN')
sys.meta_path.insert(0,Guard())
from polar.signed_pair_saved import verify_stored_account
from polar.signed_event_saved import restore
old=os.open
def ro(path,flags,*args,**kwargs):
 if flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND):raise RuntimeError('WRITE_OPEN_FORBIDDEN')
 return old(path,flags,*args,**kwargs)
os.open=ro
def guard(fn):
 def wrapped(path,mode='r',*args,**kwargs):
  if any(v in mode for v in 'wa+x'):raise RuntimeError('WRITE_OPEN_FORBIDDEN')
  return fn(path,mode,*args,**kwargs)
 return wrapped
builtins.open=guard(builtins.open);io.open=guard(io.open)
x=json.loads(sys.argv[2]);a=verify_stored_account(sys.argv[1],x['ref'],restore(x['binding']))
print(json.dumps({'status':'VERIFIED','native_calls':0,'writes':0,'rows':len(a['NAV'])}))
'''
    child=subprocess.run([sys.executable,'-c',code,str(tmp_path),json.dumps({'ref':ref,'binding':encode(binding)})],
        capture_output=True,text=True,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
    assert child.returncode==0,child.stderr
    assert json.loads(child.stdout)['rows']==27
    assert before=={str(p):(sha(p.read_bytes()),p.stat().st_mtime_ns) for p in tmp_path.rglob('*') if p.is_file()}


def test_full_48_declared_graph_census_without_inventing_accounts():
    from polar.signed_pair_input import CONTROLS,CASES
    from polar.signed_pair_saved import member_census
    identities=[(c,p) for p in CASES for c in CONTROLS]
    assert member_census(identities)['native_acceptance_inferred'] is False
    for bad in (identities[:-1],identities+[identities[0]],identities[:-1]+[('UNKNOWN',CASES[-1])]):
        with pytest.raises(Exception,match='48_MEMBER'):member_census(bad)


def test_fixed_overlay_factors_keep_original_signal_and_price_source_immutable():
    from polar.signed_pair_input import CASES
    active={'status':'ACTIVATED','shock_ns':100,'long':'AAPL','short':'AMZN'}
    for case in CASES:
        assert factor(case,'AAPL',99,active)==factor(case,'AMZN',99,active)==1
    assert factor('LONG_0P7_SHORT_1P5','AAPL',100,active)==F(7,10)
    assert factor('LONG_0P7_SHORT_1P5','AMZN',100,active)==F(3,2)
    assert factor('SHORT_2','AMZN',100,active)==2
    assert factor('SHORT_5','AMZN',100,active)==5
    assert factor('BORROW_50','AMZN',100,active)==factor('ADVERSE_100BPS','AMZN',100,active)==1
    assert factor('SHORT_5','AMZN',100,{'status':'NOT_ACTIVATED'})==1


def test_exact_scalar_hand_values_latest_peak_and_known_failure_precedence(accounts):
    from polar.signed_pair_metrics import metrics,evaluate
    from copy import deepcopy
    _,outputs=accounts;a=deepcopy(outputs[0]);a['NAV']=a['NAV'][:3]
    for row,value in zip(a['NAV'],[10000000,11000000,10000000]):row['nav_cents']=value
    r=metrics(a)
    assert r['mean']['value']==F(1,220) and r['variance']['value']==F(441,24200)
    assert r['ES']['value']==F(1,11) and r['ES']['k']==1 and r['drawdown']['maximum']==F(1,11)
    assert F(r['CAGR']['value'])==0
    b=deepcopy(outputs[0]);b['NAV']=b['NAV'][:5]
    for row,value in zip(b['NAV'],[10000000,12000000,12000000,6000000,12000000]):row['nav_cents']=value
    d=metrics(b)['drawdown'];assert (d['peak_index'],d['trough_index'],d['recovery_index'],d['maximum'])==(2,3,4,F(1,2))
    # Original actual baseline strategy loses charged fees. Absence of a
    # comparator must not hide that independently known growth failure.
    e=evaluate([outputs[0]])
    assert e['producer_screen']=='NOT_SUPPORTED' and e['missing_accounts']
    assert next(c for c in e['clauses'] if c['id']=='BASE/GROWTH')['status']=='NOT_MET'



def test_saved_source_original_token_and_endpoint_mutants_reject_semantically(accounts):
    from polar.signed_pair_saved import binding_for,verify_account
    from copy import deepcopy
    data,outputs=accounts;binding=binding_for(data)
    a=deepcopy(outputs[0]);a['D_receipts'][0]['source_members']['AAPL'][1]['adjusted_signal_token']='123.456'
    with pytest.raises(Exception,match='SOURCE_ENDPOINT_COMMITMENT'):verify_account(a,binding)
    # Rehash the caller's selected input commitment too, so this second mutant
    # tests original-versus-consumed arithmetic, not an outer checksum alone.
    target=a['D_receipts'][0]['source_members']['AAPL'][1]['local_id']
    changed=replace(data,quotes=tuple(replace(q,adjusted_signal_token='123.456') if q.local_id==target else q for q in data.quotes))
    with pytest.raises(Exception,match='ORIGINAL_CONSUMED_TOKEN_FACTOR_JOIN'):verify_account(a,binding_for(changed))
    b=deepcopy(outputs[0]);selected=list(b['D_receipts'][0]['source_members']['AAPL']);selected[1]=deepcopy(selected[2]);b['D_receipts'][0]['source_members']['AAPL']=tuple(selected)
    b['D_receipts'][0]['source_ids']['AAPL']=tuple(v['local_id'] for v in b['D_receipts'][0]['source_members']['AAPL'])
    with pytest.raises(Exception,match='SOURCE_ENDPOINT_COMMITMENT'):verify_account(b,binding)


def test_saved_actual_candidate_activation_refuses_copied_status_or_issuer():
    from polar.signed_pair_saved import binding_for,verify_account,verify_study
    from copy import deepcopy
    data=fixture();a=produce_account(data,'DYNAMIC_SPREAD','RECALL_BLACKOUT2');binding=binding_for(data)
    for change in ('status','issuer','prefix'):
        mutant=deepcopy(a)
        if change=='status':mutant['activation']['status']='NOT_ACTIVATED'
        elif change=='issuer':mutant['activation']['short']='AAPL'
        else:mutant['activation']['pre_shock_positions']['AMZN']=0
        with pytest.raises(Exception,match='CANDIDATE_ACTIVATION_ACTUAL_WITNESS_JOIN'):verify_account(mutant,binding)
    graph={'schema':'polar.private-fixed-pair-study/1','input_id':data.input_id,'protocol_sha256':data.protocol_sha256,
        'accounts':[deepcopy(a)],'actual_native_completed':1,'activations':{'RECALL_BLACKOUT2':deepcopy(a['activation'])},
        'retained_dispatch_authority':False}
    graph['accounts'][0]['activation']['status']='NOT_ACTIVATED';graph['activations']['RECALL_BLACKOUT2']['status']='NOT_ACTIVATED'
    with pytest.raises(Exception,match='CANDIDATE_ACTIVATION_ACTUAL_WITNESS_JOIN'):verify_study(graph,binding,complete=False)


@pytest.mark.parametrize('case,kind',[('ADVERSE_100BPS','ACTUAL_ALL_FILL_ADVERSE_EXECUTION'),
    ('BORROW_50','POSITIVE_ACTUAL_POST_SHOCK_BORROW_BASE'),('MAINTENANCE_160','ACTUAL_SHORT_CHECKPOINT_OR_CHANGED_REQUIREMENT_PROPOSAL')])
def test_intervention_specific_actual_candidate_coverage(case,kind):
    from polar.signed_pair_saved import verify_account,binding_for
    data=fixture();a=produce_account(data,'DYNAMIC_SPREAD',case)
    assert a['activation']['status']=='ACTIVATED' and a['activation']['kind']==kind and a['activation']['witnesses']
    verify_account(a,binding_for(data))
    if case=='ADVERSE_100BPS':
        assert len(a['activation']['witnesses'])==len([r for r in a['packet']['records'] if r['kind']=='FILL'])
        assert a['activation']['witnesses'][0]['sequence']<next(r['sequence'] for r in a['packet']['records'] if r['kind']=='BEGIN' and r['event'].at_ns==a['activation']['shock_ns'])



def test_exact_fractional_micro_overlay_preserves_original_source_and_d_join():
    from polar.signed_pair_saved import verify_account,binding_for
    data=fixture(formations=1);data=replace(data,quotes=tuple(replace(q,raw_usd_token='1.234567') for q in data.quotes))
    g=274;t=[q for q in data.quotes if q.name=='AAPL'][g].close_ns
    f=Formation('post-shock',g,t+(3*3600+60)*10**9,t+86400*10**9,g-21,g-252)
    data=replace(data,formations=(*data.formations,f))
    a=produce_account(data,'DYNAMIC_SPREAD','SHORT_1P5')
    assert all(q.raw_usd_token=='1.234567' for q in data.quotes)
    assert a['activation']['status']=='ACTIVATED'
    d=a['D_receipts'][-1]
    assert d['sizing']['raw_g_prices']['AMZN']==F('1.234567')*F(3,2)
    assert (d['sizing']['raw_g_prices']['AMZN']*10**6).denominator!=1
    verify_account(a,binding_for(data))



def test_actual_reconciled_breach_terminates_ordinary_event_and_is_not_hidden():
    from polar.signed_pair_metrics import metrics
    data=fixture();data=replace(data,quotes=tuple(replace(q,raw_usd_token='1.234567') for q in data.quotes))
    a=produce_account(data,'DYNAMIC_SPREAD','SHORT_1P5');records=a['packet']['records']
    terminations=[r for r in records if r['kind']=='CONSTRUCTION_TERMINATED_ACTUAL_EXECUTION_BREACH']
    assert terminations and a['activation']['status']=='NOT_ACTIVATED'
    first=terminations[0]
    assert not any(r['kind']=='SUBMIT' and r['event']==first['event'] and r['sequence']>first['sequence'] and
                   not r['command'].forced for r in records)
    assert any(r['kind']=='FILL' and r['command'].forced and r['event']!=first['event'] and r['sequence']>first['sequence'] for r in records)
    report=metrics(a)
    assert report['confirmed_execution_breach_ever'] and not report['survival']
    assert len(a['NAV'])==len(data.nav_closes)

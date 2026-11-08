"""Public invented controls; independent private accounting oracle is not included."""
import copy
import os
from decimal import getcontext, Decimal
from pathlib import Path
import pytest
from polar.gym_contract import *
from polar.gym_data import convert,preflight_experiment,load_inputs
from polar.gym_evaluation import evaluate_strategy,evaluate
from polar.gym_strategy import intents
from polar.gym_service import GymService,code_binding
from polar.gym_store import GymStore

TZ=Path('/usr/share/zoneinfo/America/New_York')

def rows():
    output=[]
    for day in DATES:
        for i,s in enumerate(SYMBOLS):
            p=str((i+1)*10)
            row={'reference_date':day,'source_symbol':s,'aggregation_label':day+'T05:00:00Z',
                 'adjustment':'raw','feed':'sip','currency':'USD_REQUEST_CONTRACT','requested_asof':'2020-09-02',
                 'raw_fields_exact_tokens':{'o':p,'h':p,'l':p,'c':p,'v':'0'},
                 **{k:None for k in ('event_open_at','event_close_at','observed_published_at','observed_historical_available_at','economic_security_id')}}
            output.append(row)
    return output

@pytest.fixture
def data():return rows(),TZ.read_bytes()

def test_complete_and_missing(data):
    r,tz=data
    assert preflight_experiment(r,DATES,tz)['execution_allowed']
    result=preflight_experiment(r[:-1],DATES,tz)
    assert not result['execution_allowed']
    assert result['checks'][0]['scope']['missing']==[(DATES[-1],SYMBOLS[-1])]

@pytest.mark.parametrize('field,value',[('v',None),('v','-1'),('v','0.1'),('c','NaN'),('o','0'),('l','999'),('h','9.99999')])
def test_domains(data,field,value):
    r,tz=data
    if value is None:del r[0]['raw_fields_exact_tokens'][field]
    else:r[0]['raw_fields_exact_tokens'][field]=value
    assert not preflight_experiment(r,DATES,tz)['execution_allowed']

def test_high_precision_and_lossy_conversion(data):
    r,tz=data;r[0]['raw_fields_exact_tokens']['h']='10.0001'
    converted=convert(r,tz)
    assert preflight_experiment(r,DATES,tz,converted)['execution_allowed']
    bar=next(e for e in converted['events'] if e['kind']=='ELIGIBLE_BAR')
    bar['ohlcv']['h']='10.00'
    assert not preflight_experiment(r,DATES,tz,converted)['execution_allowed']

def test_duplicate_clock_and_basis(data):
    r,tz=data
    assert not preflight_experiment(r+[r[0]],DATES,tz)['execution_allowed']
    r[0]['event_open_at']='2026-01-01'
    assert not preflight_experiment(r,DATES,tz)['execution_allowed']
    r[0]['event_open_at']=None;r[0]['adjustment']='adjusted'
    assert not preflight_experiment(r,DATES,tz)['execution_allowed']

def test_positive_actions_and_no_model(data):
    r,tz=data
    assert not preflight_experiment(r,DATES,tz,model_no_actions=False)['execution_allowed']
    a={'subject_candidate_from_source_role':'AAPL','subject_date_candidate_from_source_field':DATES[2],'source_id':'INVENTED'}
    assert not preflight_experiment(r,DATES,tz,action_rows=[a])['execution_allowed']
    a['subject_date_candidate_from_source_field']='2019-02-08'
    assert preflight_experiment(r,DATES,tz,action_rows=[a])['execution_allowed']

def test_terminal_and_phase_roster(data):
    r,tz=data;c=convert(r,tz)
    assert len([e for e in c['events'] if e['kind']=='ELIGIBLE_BAR'])==18
    assert len([e for e in c['events'] if e['kind']=='MODELED_OPEN'])==9
    assert all(e['kind']=='MODELED_OPEN' and set(e)=={'kind','symbol','date','ts_event','ts_init','price','quote_size'} for e in c['events'] if e['date']==DATES[-1])
    assert c['nav_grid'][-1]['sample_ns']==1549314000000000100
    assert c['decisions'][0]['decision_ns']==1548478860000000000
    c['events'][0]['ts_init']+=1
    assert not preflight_experiment(r,DATES,tz,c)['execution_allowed']

def test_exact_sizing_no_recurring_intermediate():
    obs={'nav':'100000','date':DATES[0],'known_by_ns':1,'closes':dict.fromkeys(SYMBOLS,'3')}
    r=intents(STRATEGIES[0],obs,dict.fromkeys(SYMBOLS,0),2,DATES[1])
    assert all(x['target']==11111 and x['sell_quantity']==0 and x['buy_quantity']==11111 for x in r)
    r=intents(STRATEGIES[0],obs,dict.fromkeys(SYMBOLS,1),2,DATES[-1],True)
    assert all(x['sell_quantity']==1 and x['buy_quantity']==0 for x in r)

def tape(values):
    return {'strategy_id':STRATEGIES[0],'fills':[],
            'nav':[{'date':str(i),'nominal_ns':i*86400*10**9,'sample_ns':i*86400*10**9+100,
                    'cash':v,'nav':v,'positions':dict.fromkeys(SYMBOLS,0),'marks':dict.fromkeys(SYMBOLS,None)} for i,v in enumerate(values)]}

def test_zero_variance_and_ambient_context():
    t=tape(['100','100','100'])
    expected=evaluate_strategy(t)
    assert expected['metrics']['sample_variance']['value']=='0'
    assert expected['metrics']['annualized_volatility']['status']=='OK'
    assert expected['metrics']['Sharpe_252']['reason']=='ZERO_EXCESS_VARIANCE'
    old=getcontext().copy()
    try:
        getcontext().prec=2;getcontext().Emax=9
        assert evaluate_strategy(t)==expected
    finally:
        from decimal import setcontext
        setcontext(old)

@pytest.mark.parametrize('v,reason',[(['100',None,'101'],'MISSING_NAV_ENDPOINT'),(['100','0','101'],'INVALID_NAV'),(['100','NaN','101'],'INVALID_NAV')])
def test_missing_invalid_no_zero(v,reason):
    r=evaluate_strategy(tape(v));assert r['metrics']['total_return']['value'] is None
    assert r['metrics']['total_return']['reason']==reason
    assert len(r['daily_returns'])==2

def test_exact_returns_tail_and_drawdown():
    result=evaluate_strategy(tape(['100','90','100','100']))
    assert result['daily_returns'][0]['exact_fraction']=={'numerator':'-1','denominator':'10'}
    assert result['daily_returns'][1]['exact_fraction']=={'numerator':'1','denominator':'9'}
    assert result['metrics']['ES95']['value']=='0.1'
    assert result['metrics']['maximum_drawdown']['value']=='0.1'
    assert result['details']['drawdown']['recovery_ns']==2*86400*10**9
    assert result['details']['worst_period']==result['daily_returns'][0]

def test_concentration_full_nav():
    t=tape(['100','100','100']);t['nav'][1]['positions']['AAPL']=1;t['nav'][1]['marks']['AAPL']='10'
    assert evaluate_strategy(t)['metrics']['maximum_close_name_concentration']['value']=='0.1'

def test_ref_hash_and_duplicate_json(tmp_path):
    p=tmp_path/'x';p.write_bytes(b'{}')
    with pytest.raises(GymError):read_ref({'path':str(p.resolve()),'sha256':'0'*64})
    with pytest.raises(GymError):decode(b'{"a":1,"a":2}')
    with pytest.raises(GymError):decode(b'{"a":1.2}')

def test_store_replay_tamper_and_unfinalized(tmp_path):
    root=tmp_path.resolve();store=GymStore(root,1024**2)
    files={name:{} for name in SEMANTIC_FILES};bindings={'fixture':'invented'}
    started=store.begin({'namespace':'fixture'},bindings)
    assert store.attempt(started['attempt_id'])['status']=='UNFINALIZED'
    eid=store.publish(files,bindings);assert store.publish(files,bindings)==eid
    assert store.report(eid)['files']==files
    p=root/'gym-experiments'/eid/'simulation.json';p.chmod(0o600);p.write_bytes(b'[]\n')
    with pytest.raises(GymError):store.report(eid)
    with pytest.raises(GymError):store.report('../x')

def test_retained_budget_no_reset(tmp_path):
    store=GymStore(tmp_path.resolve(),1024**2)
    started=store.begin({'namespace':'retained'},{'same':1})
    with pytest.raises(GymError,match='EXACT_REPLAY'):store.begin({'namespace':'retained'},{'same':1})
    store.finish(started['attempt_id'],{'status':'SUCCESS','experiment_id':'gym-'+'a'*64})
    store.begin({'namespace':'retained'},{'same':1},replay_of='gym-'+'a'*64)
    with pytest.raises(GymError,match='BUDGET'):store.begin({'namespace':'retained'},{})

def test_huge_exponent_is_bounded_before_fraction_expansion():
    with pytest.raises(GymError,match='BOUND'):fraction('1e999999999')
    with pytest.raises(GymError,match='BOUND'):fraction('1e-999999999')

def test_pinned_runtime_metadata_float_timings_are_not_finance(monkeypatch,tmp_path):
    import polar.gym_service as service
    proof={'packages':{},'runtime_files':{},'wall_seconds':1.5}
    raw=canonical(proof);p=tmp_path/'proof';p.write_bytes(raw)
    monkeypatch.setattr(service,'COMPOSITION_SHA',sha(raw))
    monkeypatch.setattr(service.platform,'machine',lambda:'aarch64')
    monkeypatch.setattr(service.platform,'system',lambda:'Linux')
    result=GymService(GymStore(tmp_path.resolve(),1024**2)).runtime({'path':str(p.resolve()),'sha256':sha(raw)})
    assert result['sha256']==sha(raw)
    with pytest.raises(GymError):decode(raw)

# Native author tests are opt-in, bounded in PREINVOCATION.md; no retained source input.
@pytest.mark.skipif(os.environ.get('POLAR_GYM_NATIVE_TEST')!='1',reason='requires pinned isolated native image')
def test_native_invented_pair_and_fresh_replay(data):
    from polar.gym_nautilus import simulate
    r,tz=data
    c=convert(r,tz)
    first=simulate(c);second=simulate(c)
    assert first==second
    for t in first['strategies']:
        assert len(t['nav'])==7 and len(t['observations'])==6
        assert all(e['quantity']>0 and e['fee']=='1' for e in t['fills'])
        assert t['nav'][-1]['positions']==dict.fromkeys(SYMBOLS,0)
        assert t['nav'][-1]['nav']==t['nav'][-1]['cash']
        assert all(x['order_date']!=DATES[0] for x in t['intents'])
    assert evaluate(first)==evaluate(second)

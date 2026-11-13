"""Invented B9 admission and mixed-metric status; no retained inputs."""
from copy import deepcopy
import pytest
from polar.scheduled_policy import profile_value, evaluate_policy
from polar.scheduled_parking import COSTS, point_status


def profile():
    criteria=[('TERMINAL_SCALED_GE',{'right_id':'SHY_FULL','factor':[9,10]}),
              ('SR_GE',{'threshold':'0'}),
              ('DRAWDOWN_SCALED_LE',{'right_id':'SHY_FULL','factor':[1,2]}),
              ('VOL_SCALED_LE',{'right_id':'SHY_FULL','factor':[1,2]}),
              ('POSITIVE_GROWTH',{})]
    return {'schema':'polar.scheduled-reference-profile/12','protocol_id':'INVENTED-B9',
        **{k:'a'*64 for k in ('protocol_sha256','input_sha256','calendar_sha256','timezone_sha256')},
        'symbols':['BIL','SHY'],'policy':{'kind':'FIXED_ANNUAL_RATIONAL_WEIGHTS'},
        'legs':[{'id':i,'label':i,'rule':'CASH' if i=='CASH' else 'FIXED_WEIGHTS',
                 'weights':{'BIL':[int(i=='BIL_FULL'),1],'SHY':[int(i=='SHY_FULL'),1]}}
                for i in ('BIL_FULL','SHY_FULL','CASH')],
        'primary_strategy':'BIL_FULL','primary_benchmark':'SHY_FULL','decision_delay_seconds':60,
        'criteria':[{'id':str(n),'description':kind,'kind':kind,'left_id':'BIL_FULL',**fields}
                    for n,(kind,fields) in enumerate(criteria)],'cost_scenarios':deepcopy(COSTS),
        'question_label':'Invented parking','question_summary':'Invented source-only controls',
        'clock_description':'UTC midnight plus sixty seconds',
        'partition_description':'Invented FINAL only','additional_limitations':[],'subperiods':[]}


def test_closed_profile_and_legacy_direct_sharpe_not_admitted():
    p=profile(); assert profile_value(p)==p
    for mutate in (lambda x:x.update(schema='polar.scheduled-reference-profile/8'),
                   lambda x:x['criteria'][1].update(threshold='0.01'),
                   lambda x:x['legs'][0]['weights'].update(BIL=[True,1]),
                   lambda x:x['cost_scenarios'][1]['cost_profile'].update(bps=10),
                   lambda x:x['criteria'][2].update(factor=[3,4])):
        bad=deepcopy(p);mutate(bad)
        with pytest.raises(ValueError):profile_value(bad)


@pytest.mark.parametrize('statuses,expected',[
    (['MET']*5,'SUPPORTIVE_ON_THIS_LIMITED_SCREEN'),
    (['MET','UNAVAILABLE','MET','MET','MET'],'INDETERMINATE'),
    (['NOT_MET','UNAVAILABLE','MET','MET','MET'],'NOT_SUPPORTIVE_ON_THIS_LIMITED_SCREEN')])
def test_frozen_mixed_status_precedence(statuses,expected):
    assert point_status(statuses)==expected


@pytest.mark.parametrize('statuses',[[],['MET']*4,['INVALID']*5])
def test_status_census_never_vacuous_support(statuses):
    with pytest.raises(ValueError):point_status(statuses)


def test_structural_invalid_precedes_scalar_screen(monkeypatch):
    def forbidden(*args):raise AssertionError('SCALAR_SCREEN_BEFORE_STRUCTURAL_VALIDATION')
    monkeypatch.setattr('polar.scheduled_policy.evaluate_legs',forbidden)
    with pytest.raises(ValueError,match='PARKING_ACCOUNT_SET'):
        evaluate_policy({'legs':[]},profile(),'FINAL')


def invented_market_calendar():
    from datetime import datetime,timedelta,timezone
    days=['2020-01-02','2020-01-03','2020-01-06','2020-01-07','2020-01-08']
    schedule=[{'date':d,'reference_close_utc':d+'T21:00:00+00:00',
               'next_reference_date':days[i+1] if i+1<len(days) else None} for i,d in enumerate(days)]
    def event(index):
        k=datetime.fromisoformat(days[index]+'T00:00:00+00:00')+timedelta(days=1)
        return {'formation_date':days[index],'K':k.isoformat(),'D':(k+timedelta(seconds=60)).isoformat(),
                'execution_date':days[index+1],'reference_execution_close_utc':schedule[index+1]['reference_close_utc']}
    calendar={'schema':'polar.prospective-fixed-allocation-calendar/1','parent_schedule':{},'dates':days,
              'initial_date':days[0],'terminal_date':days[-1],'nav_points':5,'returns':4,
              'annual_targets':[event(0)],'terminal_EXIT':event(3),'clock_scope':'UTC_MIDNIGHT_PLUS_60S'}
    # Higher execution prices require actual fee-aware clipping below the D floor.
    prices={d:{'BIL':(100+i)*1000000,'SHY':(110+i*2)*1000000} for i,d in enumerate(days)}
    return {'symbols':['BIL','SHY'],'schedule':schedule,'prices_micro':prices},calendar


def test_scale1_native_witnesses_and_true_two_cost_accounts(monkeypatch):
    from polar.scheduled_policy import calendar_value,plan_phase
    from polar.ci_research_native import simulate
    from polar.model_price_consumed import verify
    market,cal=invented_market_calendar();p=profile();grid=calendar_value(cal,market['schedule'])['FINAL']
    plan=plan_phase(market,p,grid,None);saved={**cal,'source_schedule_rows':market['schedule']}
    assert 'model_price_mapping' not in plan and plan['price_evidence'][grid['initial']]['price_scale']==[1,1]
    simulations=[]
    for scenario in COSTS:
        current={**plan,'cost_profile':scenario['cost_profile']};sim=simulate(current);simulations.append(sim)
        def forbidden(*args):raise AssertionError('POLICY_CALL_DURING_SAVED_VERIFICATION')
        with monkeypatch.context() as scoped:
            scoped.setattr('polar.scheduled_fixed.plan_phase',forbidden)
            result=verify(current,sim,p,saved)
        assert result['status']=='VERIFIED_NEW_FIXED_CONSUMED_OPERANDS' and result['native_calls']==result['source_reads']==0
        cash=sim['legs'][-1]
        assert not cash['fills'] and all(i['sizing_witness'] is None for i in cash['intents'])
        first=sim['legs'][0]['intents'][0]['sizing_witness']
        assert first['quantity_unit']=='WHOLE_SYNTHETIC_REFERENCE_UNIT_NOT_RAW_SHARE'
        assert 'model_mapping_sha256' not in first
        assert first['nav_cents']==10000000 and first['targets']['BIL']==1000
        assert sim['legs'][0]['fills'][0]['q']<1000
        bad=deepcopy(sim);bad['legs'][0]['intents'][0]['sizing_witness']['cash_cents']+=1
        with pytest.raises(ValueError,match='D_OPERANDS_FLOOR'):verify(current,bad,p,saved)
        bad=deepcopy(sim);bad['legs'][0]['nav'][1]['date']='2099-01-01'
        with pytest.raises(ValueError,match='NATIVE_MARK'):verify(current,bad,p,saved)
        # The captured native ledger fields feed the accepted eighteen scalars.
        # They must be bound as well as cash/positions/total NAV.
        for field in ('exposure_cents','position_cents','flat_cents','bps_cents','exact_notional_micro'):
            bad=deepcopy(sim)
            if field=='exact_notional_micro':bad['legs'][0]['fills'][0][field]+=1
            elif field=='position_cents':bad['legs'][0]['nav'][1][field]['BIL']+=1
            else:bad['legs'][0]['nav'][1][field]+=1
            with pytest.raises(ValueError,match='PARKING_CONSUMED_METRIC_BINDING'):verify(current,bad,p,saved)

    assert simulations[0]['legs'][0]['fills'][0]['fee_cents']!=simulations[1]['legs'][0]['fills'][0]['fee_cents']


def test_real_zero_risk_scalars_keep_unavailable_sharpe_and_known_growth_failure():
    from polar.scheduled_policy import calendar_value,plan_phase
    from polar.ci_research_native import simulate
    market,cal=invented_market_calendar();p=profile()
    market['prices_micro']={d:{'BIL':10**16,'SHY':10**16} for d in market['prices_micro']}
    grid=calendar_value(cal,market['schedule'])['FINAL'];plan=plan_phase(market,p,grid,None)
    sim=simulate(plan);result=evaluate_policy(sim,p,'FINAL')
    assert [c['status'] for c in result['criteria']]==['MET','UNAVAILABLE','MET','MET','NOT_MET']
    assert result['point_interpretation']=='NOT_SUPPORTIVE_ON_THIS_LIMITED_SCREEN'
    assert all(len(l['metrics'])==18 for l in result['legs'])
    for leg in result['legs']:
        assert leg['metrics']['sharpe_252_rf0']['value'] is None
        assert leg['metrics']['max_drawdown']['value']=='0'
        assert leg['metrics']['annual_vol_252']['value']=='0'
        assert leg['metrics']['gross_notional_over_initial']['value']=='0'

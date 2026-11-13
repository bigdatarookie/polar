"""Invented immutable-calendar validation scale; no native/source/Service use."""
from datetime import date,timedelta
import json
from pathlib import Path
import time

from polar.distribution_claims import Action,Claim,State,Phase,valuation


def test_repeated_valuation_does_not_reparse_every_claim_calendar(monkeypatch):
    import polar.distribution_claims as module
    dates=tuple((date(2000,1,1)+timedelta(days=i)).isoformat() for i in range(2728))
    claims=tuple(Claim(Action('INVENTED-'+str(i),'INVENTED','INVENTED','/'+str(i),dates[0],dates[-2],
        '0.01',dates),0,0,(0,1),dates[-1]) for i in range(43))
    state=State(dates[-1],Phase.CLOSE_SETTLED,10000000,(('INVENTED',0),),claims)
    original=module.day;calls=[]
    def counted(value):calls.append(None);return original(value)
    monkeypatch.setattr(module,'day',counted)
    start=time.monotonic_ns()
    for _ in range(8):
        result=valuation(state,{'INVENTED':0},terminal=True)
        assert result['nav_cents']==10000000 and result['cash_only_terminal'] is True
    observation={'scope':'INVENTED PURE VALIDATION ONLY, not actual retained timeout cause or SLO',
        'dates':len(dates),'claims':len(claims),'valuation_samples':8,'day_validation_calls':len(calls),
        'wall_ns':time.monotonic_ns()-start,'native_calls':0,'source_calls':0,'service_calls':0}
    if Path('/reports').is_dir():Path('/reports/calendar-scaling.json').write_text(json.dumps(observation,indent=2)+'\n')
    assert len(calls)<10000,observation



def test_cached_calendar_keeps_strict_domains_and_event_specific_guards():
    import pytest
    from polar.distribution_claims import ClaimError
    dates=('2020-01-01','2020-01-02','2020-01-03')
    def action(calendar=dates,ex='2020-01-01',pay='2020-01-02'):
        return Action('INVENTED','INVENTED','INVENTED','/0',ex,pay,'0.01',calendar)
    assert action().availability_date=='2020-01-03'
    class Alias(str):pass
    for calendar,reason in [(list(dates),'CLAIM_CALENDAR'),((True,*dates[1:]),'CLAIM_DATE'),
            ((Alias(dates[0]),*dates[1:]),'CLAIM_DATE'),(([dates[0]],*dates[1:]),'CLAIM_DATE'),
            (('2020-02-30',*dates[1:]),'CLAIM_DATE'),((dates[0],dates[0],dates[-1]),'CLAIM_CALENDAR'),
            (tuple(reversed(dates)),'CLAIM_CALENDAR')]:
        with pytest.raises(ClaimError,match=reason):action(calendar)
    with pytest.raises(ClaimError,match='CLAIM_CALENDAR'):action(ex='2019-12-31')
    with pytest.raises(ClaimError,match='CLAIM_AVAILABILITY_UNMAPPED'):action(pay=dates[-1])
    assert action(pay=dates[0]).availability_date==dates[1]
    assert action().availability_date==dates[-1]


def test_invented_full_size_four_leg_native_phase_preserves_cash_and_q0_lifecycle():
    import time
    from polar.raw_action_input import calendar
    from polar.ci_research_service import bounded_native
    from polar.raw_action_native import LEGS
    from polar.gym_contract import canonical
    dates=[(date(2000,1,3)+timedelta(days=i)).isoformat() for i in range(2728)]
    rows=[{'date':d,'reference_open_utc':d+'T14:30:00Z','reference_close_utc':d+'T21:00:00Z',
        'next_reference_date':dates[i+1] if i+1<len(dates) else None,
        'month_end_in_reference_range':False} for i,d in enumerate(dates)]
    actions=[Action('INVENTED-'+str(i),'INVENTED','INVENTED','/'+str(i),dates[20+i*60],
        dates[20+i*60],'0.01',tuple(dates)) for i in range(43)]
    from dataclasses import asdict
    descriptor={'event_dates':[{'event_id':a.event_id,'ex_date':a.ex_date,'payment_date':a.payment_date,
        'availability_date':a.availability_date} for a in actions]}
    grid=calendar(descriptor,dates,rows)
    plan={'profile':{'kind':'RAW_ACTION_REINVEST'},'instrument':'INVENTED','dates':dates,
        'schedule':rows,'events':grid['events'],'prices':{d:{'close_micro':100000000} for d in dates},
        'actions':[asdict(a) for a in actions],'cost_profile':{'flat_cents':100,'bps':10}}
    start=time.monotonic_ns();result=bounded_native(plan);wall=time.monotonic_ns()-start
    assert len(result['legs'])==4 and [leg['id'] for leg in result['legs']]==list(LEGS)
    assert all(len(leg['nav'])==2728 and leg['component_counts']['recognize']==leg['component_counts']['pay']==43 for leg in result['legs'])
    cash=result['legs'][-1]
    assert not cash['orders'] and not cash['fills'] and cash['component_counts']['native_positive_balance_updates']==0
    assert len([e for e in cash['claim_events'] if e['operation']=='recognize'])==43
    assert len([e for e in cash['claim_events'] if e['operation']=='pay'])==43
    assert all(r['positions']['INVENTED']==0 and r['nav_cents']==10000000 for r in cash['nav'])
    assert all(c['entitled_quantity']==0 and c['paid_at'] is not None for c in cash['final_claim_state']['claims'])
    events=result['physical_native_events']
    assert sum(e['phase']=='NATIVE_RUN_ENTERED' for e in events)==sum(e['phase']=='ACCOUNT_COMPLETED' for e in events)==4
    if Path('/reports').is_dir():Path('/reports/full-size-native.json').write_bytes(canonical({
        'scope':'INVENTED ONLY; not retained execution or exclusive historical timeout cause',
        'dates':2728,'actions':43,'native_accounts':4,'wall_ns':wall,'native_guard_seconds':300,
        'events':events,'cash_q0_recognitions':43,'cash_q0_payments':43,'cash_orders':0,'cash_fills':0}))

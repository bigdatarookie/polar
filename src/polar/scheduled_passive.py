"""Versioned fixed-event TARGET/HOLD schedules and saved executed-state control."""
from copy import deepcopy
from datetime import datetime

from .ci_research import require
from .gym_contract import canonical, sha
from .reference_ridge_plan import nanoseconds
from .scheduled_fixed import validate_legs, plan_phase as fixed_plan, calendar_value

SCHEMA = 'polar.scheduled-reference-profile/9'


class InitialStateMismatch(ValueError):
    def __init__(self,pair,day,states):
        super().__init__('SCHEDULED_INITIAL_STATE_MISMATCH_INVALID')
        self.events={'pair':pair,'execution_date':day,'actual_states':states}



def validate_profile(profile):
    require(profile['policy']=={'kind':'FIXED_ANNUAL_WITH_PASSIVE_CONTROLS'} and
            profile['decision_delay_seconds']==60,'SCHEDULED_PASSIVE_POLICY')
    legs=profile['legs']
    require(type(legs) is list and 2<=len(legs)<=5 and all(type(x) is dict and
            set(x)=={'id','label','rule','weights'} and type(x['id']) is str and
            x['rule'] in ('FIXED_WEIGHTS','INITIAL_TARGET_ONLY','CASH') for x in legs),
            'SCHEDULED_PASSIVE_LEGS')
    # Retain the legacy exact rational domain, including CASH zero weights.
    normalized=[{**x,'rule':'FIXED_WEIGHTS' if x['rule']=='INITIAL_TARGET_ONLY' else x['rule']} for x in legs]
    validate_legs(normalized,profile['symbols'])
    pair=[next((x for x in legs if x['id']==profile[k]),None)
          for k in ('primary_strategy','primary_benchmark')]
    require(all(pair) and pair[0]['rule']=='FIXED_WEIGHTS' and
            pair[1]['rule']=='INITIAL_TARGET_ONLY' and pair[0]['weights']==pair[1]['weights'],
            'SCHEDULED_INITIAL_PAIR_PROFILE')


def _instructions(profile,initial):
    return {x['id']:({'kind':'HOLD'} if x['rule']=='CASH' or
                    x['rule']=='INITIAL_TARGET_ONLY' and not initial else
                    {'kind':'TARGET','weights':x['weights'],'signal':{'kind':'FIXED_DECLARED_WEIGHTS'}})
            for x in profile['legs']}


def plan_phase(market,profile,grid):
    plan=fixed_plan(market,profile,grid)
    for i,event in enumerate(plan['decisions'][:-1]):
        event['instructions']=_instructions(profile,i==0)
    return plan


def verify_saved_plan(plan,profile,calendar):
    """Metadata and saved instructions only; no source, allocator or native call."""
    schedule=calendar['source_schedule_rows'];grid=calendar_value(
        {k:v for k,v in calendar.items() if k!='source_schedule_rows'},schedule)['FINAL']
    events=plan['decisions'];require(len(events)==len(grid['decisions'])+1,'SCHEDULED_PASSIVE_EVENT_COUNT')
    close={r['date']:nanoseconds(datetime.fromisoformat(r['reference_close_utc'].replace('Z','+00:00')))
           for r in schedule}
    for i,(event,expected) in enumerate(zip(events,[*grid['decisions'],grid['terminal_exit']])):
        terminal=i==len(events)-1
        wanted={x['id']:{'kind':'EXIT'} for x in profile['legs']} if terminal else _instructions(profile,i==0)
        require(event['instructions']==wanted and event['day']==expected['execution_date'] and
                event['formation']==expected['signal_date'] and event['known_ns']==expected['known_ns'] and
                event['decision_ns']==expected['decision_ns'] and event['open_ns']==close[event['day']] and
                event['kind']=='REFERENCE','SCHEDULED_PASSIVE_SAVED_INSTRUCTIONS')
    require(plan['signals']==[] and [x['date'] for x in plan['grid']]==grid['nav_dates'] and
            plan['profile']=={'kind':'REFERENCE_TARGETS','legs':[x['id'] for x in profile['legs']],
                             'end':grid['terminal']},'SCHEDULED_PASSIVE_SAVED_GRID')


def matched_initial_state(simulation,profile,plan):
    """Fail before evaluation/publication if the actual primary pair differs."""
    day=plan['decisions'][0]['day'];nominal=plan['decisions'][0]['open_ns']
    ids=[profile['primary_strategy'],profile['primary_benchmark']]
    by_id={x['id']:x for x in simulation['legs']}
    signatures=[]
    for key in ids:
        tape=by_id[key];marks=[r for r in tape['nav'] if r['date']==day]
        require(len(marks)==1,'SCHEDULED_INITIAL_STATE_MARK')
        mark=marks[0]
        require(mark['nominal_ns']==nominal and mark['sample_ns']>nominal and
                set(mark['positions'])==set(profile['symbols']) and
                all(k in mark for k in ('cash_cents','nav_cents','flat_cents','bps_cents','position_cents')),
                'SCHEDULED_INITIAL_STATE_MARK')
        def rows(name):
            # Logical order identity is account-specific; execution data is not.
            return [{k:v for k,v in row.items() if k!='id'} for row in tape[name]
                    if nominal<=row['at_ns']<mark['sample_ns']]
        signatures.append({'mark':deepcopy(mark),'orders':rows('orders'),'fills':rows('fills')})
    if signatures[0]!=signatures[1]:raise InitialStateMismatch(ids,day,signatures)
    return {'schema':'polar.matched-initial-state-control/1','status':'PASS','pair':ids,
            'execution_date':day,'logical_nominal_ns':str(nominal),
            'signature_sha256':sha(canonical(signatures[0])),
            'state':signatures[0], 'scope':'WITHIN_THIS_FRESH_COST_SCENARIO_NO_CROSS_COST_EQUALITY'}

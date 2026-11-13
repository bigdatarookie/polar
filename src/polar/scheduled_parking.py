"""Closed B9 scale1 fixed parking point screen; no source reads or native calls."""
from .ci_research import INITIAL_CENTS,require
from .gym_contract import canonical

SCHEMA='polar.scheduled-reference-profile/12'
COSTS=[{'id':'BASE','cost_profile':{'flat_cents':100,'bps':10}},
       {'id':'COST_STRESS','cost_profile':{'flat_cents':200,'bps':20}}]


def validate_profile(p):
    require(p['schema']==SCHEMA and p['symbols']==['BIL','SHY'] and
            p['policy']=={'kind':'FIXED_ANNUAL_RATIONAL_WEIGHTS'} and p['decision_delay_seconds']==60 and
            canonical(p['cost_scenarios'])==canonical(COSTS),'PARKING_PROFILE')
    require(p['primary_strategy']=='BIL_FULL' and p['primary_benchmark']=='SHY_FULL' and
            [x['id'] for x in p['legs']]==['BIL_FULL','SHY_FULL','CASH'],'PARKING_LEGS')
    expected=[('FIXED_WEIGHTS',{'BIL':[1,1],'SHY':[0,1]}),
              ('FIXED_WEIGHTS',{'BIL':[0,1],'SHY':[1,1]}),('CASH',{'BIL':[0,1],'SHY':[0,1]})]
    require(all(canonical({'rule':l['rule'],'weights':l['weights']})==canonical({'rule':rule,'weights':weights})
                for l,(rule,weights) in zip(p['legs'],expected)),'PARKING_WEIGHTS')
    specs=[('TERMINAL_SCALED_GE',{'right_id':'SHY_FULL','factor':[9,10]}),
           ('SR_GE',{'threshold':'0'}),('DRAWDOWN_SCALED_LE',{'right_id':'SHY_FULL','factor':[1,2]}),
           ('VOL_SCALED_LE',{'right_id':'SHY_FULL','factor':[1,2]}),('POSITIVE_GROWTH',{})]
    require(len(p['criteria'])==5 and all(canonical({k:v for k,v in c.items() if k not in ('id','description')})==
            canonical({'kind':kind,'left_id':'BIL_FULL',**fields}) for c,(kind,fields) in zip(p['criteria'],specs)),
            'PARKING_FROZEN_CRITERIA')
    return p


def structural(simulation):
    legs=simulation['legs'];require([l['id'] for l in legs]==['BIL_FULL','SHY_FULL','CASH'],'PARKING_ACCOUNT_SET')
    require(len(legs[0]['nav'])>=2,'PARKING_GRID')
    clocks=[(r['date'],r['nominal_ns'],r['sample_ns']) for r in legs[0]['nav']]
    for leg in legs:
        nav=leg['nav'];require([(r['date'],r['nominal_ns'],r['sample_ns']) for r in nav]==clocks,'PARKING_ACCOUNT_GRID')
        require(nav[0]['nav_cents']==nav[0]['cash_cents']==INITIAL_CENTS and
                not any(nav[0]['positions'].values()) and nav[0]['exposure_cents']==0,'PARKING_INITIAL_STATE')
        require(not any(nav[-1]['positions'].values()) and nav[-1]['exposure_cents']==0 and
                nav[-1]['cash_cents']==nav[-1]['nav_cents'],'PARKING_TERMINAL_NOT_CASH')


def point_status(statuses):
    require(type(statuses) is list and len(statuses)==5 and all(x in ('MET','NOT_MET','UNAVAILABLE') for x in statuses),'PARKING_CRITERION_STATUS')
    return ('NOT_SUPPORTIVE_ON_THIS_LIMITED_SCREEN' if 'NOT_MET' in statuses else
            'INDETERMINATE' if 'UNAVAILABLE' in statuses else 'SUPPORTIVE_ON_THIS_LIMITED_SCREEN')



UNIT='WHOLE_SYNTHETIC_REFERENCE_UNIT_NOT_RAW_SHARE'
WITNESS='polar.fixed-reference-consumed-operands/1'


def bind_plan(plan,profile):
    """Capture existing scale1 sizing/clip call sites, with no model-price transform."""
    clocks={r['date']:r['nominal_ns'] for r in plan['grid']}
    return {**plan,'decisions':[{**d,'formation_close_ns':clocks[d['formation']]} for d in plan['decisions']],
        'capture_consumed_sizing':True,'consumed_witness_schema':WITNESS,'quantity_unit':UNIT,
        'price_evidence':{d:{'source_input_sha256':profile['input_sha256'],'source_date':d,
                            'quote_basis':'SYNTHETIC_VENDOR_ADJUSTED_REFERENCE_UNIT','price_scale':[1,1]}
                          for d in plan['prices']}}


def verify_plan(plan,profile,calendar):
    from .scheduled_policy import calendar_value
    require(calendar is not None,'PARKING_SAVED_CALENDAR_REQUIRED')
    schedule=calendar['source_schedule_rows']
    grid=calendar_value({k:v for k,v in calendar.items() if k!='source_schedule_rows'},schedule)['FINAL']
    # Saved prices are checked for shape/domain, never reconstructed from a source.
    days=grid['nav_dates'];symbols=profile['symbols']
    require(list(plan['prices'])==days and all(set(row)==set(symbols) for row in plan['prices'].values()),
            'PARKING_SAVED_PRICE_GRID')
    prices={}
    for d,row in plan['prices'].items():
        prices[d]={}
        for symbol,value in row.items():
            require(type(value) is dict and set(value)=={'close_micro'} and
                    type(value['close_micro']) is int and 0<value['close_micro']<=10**24,'PARKING_SAVED_PRICE_DOMAIN')
            prices[d][symbol]=value['close_micro']
    from datetime import datetime
    from .reference_ridge_plan import nanoseconds
    closes={r['date']:nanoseconds(datetime.fromisoformat(r['reference_close_utc'].replace('Z','+00:00'))) for r in schedule}
    expected_grid=[{'date':d,'nominal_ns':closes[d],'sample_ns':closes[d]+1000,
                    'initial':i==0,'terminal':d==grid['terminal']} for i,d in enumerate(days)]
    require(canonical(plan['grid'])==canonical(expected_grid),'PARKING_SAVED_GRID')
    events=grid['decisions']+[grid['terminal_exit']]
    require(len(plan['decisions'])==len(events),'PARKING_SAVED_EVENT_COUNT')
    decisions=[]
    for i,event in enumerate(events):
        instructions={l['id']:({'kind':'EXIT'} if i==len(events)-1 else {'kind':'HOLD'} if l['rule']=='CASH' else
            {'kind':'TARGET','weights':l['weights'],'signal':{'kind':'FIXED_DECLARED_WEIGHTS'}}) for l in profile['legs']}
        decisions.append({'day':event['execution_date'],'formation':event['signal_date'],
            'known_ns':event['known_ns'],'decision_ns':event['decision_ns'],'open_ns':closes[event['execution_date']],
            'kind':'REFERENCE','instructions':instructions,'formation_close_ns':closes[event['signal_date']]})
    expected={'profile':{'kind':'REFERENCE_TARGETS','legs':[l['id'] for l in profile['legs']],'end':grid['terminal']},
        'symbols':symbols,'prices':plan['prices'],'grid':expected_grid,'decisions':decisions,'signals':[],
        'quote_basis':'SYNTHETIC_VENDOR_ADJUSTED_REFERENCE_UNIT','clock_policy':'PINNED_REFERENCE_EARLY_CLOSE',
        'capture_consumed_sizing':True,'consumed_witness_schema':WITNESS,'quantity_unit':UNIT,
        'price_evidence':{d:{'source_input_sha256':profile['input_sha256'],'source_date':d,
            'quote_basis':'SYNTHETIC_VENDOR_ADJUSTED_REFERENCE_UNIT','price_scale':[1,1]} for d in days}}
    if 'cost_profile' in plan:expected['cost_profile']=plan['cost_profile']
    require(canonical(plan)==canonical(expected),'PARKING_SAVED_PLAN_BINDING')

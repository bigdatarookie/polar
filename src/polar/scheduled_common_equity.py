"""Closed B10 nominal one-third equity comparison; no new execution engine."""
from .ci_research import require
from .gym_contract import canonical
from .scheduled_parking import COSTS, structural as parking_structural

SCHEMA='polar.scheduled-reference-profile/13'
IDS=['VTI_BIL','VTI_SHY','VTI_FULL','CASH']


def validate_profile(p):
    require(p['schema']==SCHEMA and p['symbols']==['BIL','SHY','VTI'] and
            p['policy']=={'kind':'FIXED_ANNUAL_RATIONAL_WEIGHTS'} and
            p['decision_delay_seconds']==60 and canonical(p['cost_scenarios'])==canonical(COSTS) and
            p['subperiods']==[], 'COMMON_EQUITY_PROFILE')
    require(p['primary_strategy']=='VTI_BIL' and p['primary_benchmark']=='VTI_SHY' and
            [l['id'] for l in p['legs']]==IDS,'COMMON_EQUITY_LEGS')
    weights=[{'BIL':[2,3],'SHY':[0,1],'VTI':[1,3]},
             {'BIL':[0,1],'SHY':[2,3],'VTI':[1,3]},
             {'BIL':[0,1],'SHY':[0,1],'VTI':[1,1]},
             {'BIL':[0,1],'SHY':[0,1],'VTI':[0,1]}]
    require(all(canonical({'rule':l['rule'],'weights':l['weights']})==
                canonical({'rule':'CASH' if l['id']=='CASH' else 'FIXED_WEIGHTS','weights':w})
                for l,w in zip(p['legs'],weights)),'COMMON_EQUITY_WEIGHTS')
    specs=[('TERMINAL_SCALED_GE',{'right_id':'VTI_SHY','factor':[9,10]}),
           ('SR_GE',{'threshold':'0'}),
           ('DRAWDOWN_SCALED_LE',{'right_id':'VTI_SHY','factor':[9,10]}),
           ('VOL_SCALED_LE',{'right_id':'VTI_SHY','factor':[9,10]}),('POSITIVE_GROWTH',{})]
    require(len(p['criteria'])==5 and all(canonical({k:v for k,v in c.items() if k not in ('id','description')})==
            canonical({'kind':kind,'left_id':'VTI_BIL',**fields}) for c,(kind,fields) in zip(p['criteria'],specs)),
            'COMMON_EQUITY_FROZEN_CRITERIA')
    return p


def structural(simulation):
    parking_structural(simulation, expected_ids=IDS)

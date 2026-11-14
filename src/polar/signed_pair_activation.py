"""Saved actual intervention applicability, not an economic-survival decision.

Consumes the already-verified candidate event prefix/callbacks. No source scan,
portfolio rebuild, ranking, native invocation or favorable date selection.
"""
from fractions import Fraction as F
from dataclasses import replace
from .signed_pair_input import CASES,NAMES
from .signed_event_saved import encode
from .signed_native_bridge import require
from .signed_event_driver import maintenance
from .gym_contract import canonical,sha

SIDE_CASES={'SHORT_1P5','LONG_0P7_SHORT_1P5','RECALL_BLACKOUT2','LONG_0P7_SHORT_1P5_RECALL','SHORT_2','SHORT_5'}
JOINT_CASES={'LONG_0P7_SHORT_1P5','LONG_0P7_SHORT_1P5_RECALL'}


def scenario_factor(case,name,close_ns,activation):
    if activation is None or activation['status']!='ACTIVATED' or close_ns<activation['shock_ns']:return F(1)
    if name==activation['short']:
        if case in ('SHORT_1P5','LONG_0P7_SHORT_1P5','LONG_0P7_SHORT_1P5_RECALL'):return F(3,2)
        if case=='SHORT_2':return F(2)
        if case=='SHORT_5':return F(5)
    if name==activation['long'] and case in JOINT_CASES:return F(7,10)
    return F(1)


def held_activation(context,case,input_id,shock_ns,positions,previous_event,*,begin_sequence=None,state_sha256=None):
    shorts=[n for n in NAMES if positions.get(n,0)<0];longs=[n for n in NAMES if positions.get(n,0)>0]
    active=len(shorts)==1 and (case not in JOINT_CASES or len(longs)==1)
    return {'schema':'polar.fixed-pair-activation/1','kind':'FIXED_PRE_SHOCK_HELD_PREFIX','case':case,'input_id':input_id,
        'shock_ns':shock_ns,'status':'ACTIVATED' if active else 'NOT_ACTIVATED',
        'short':shorts[0] if len(shorts)==1 else None,'long':longs[0] if len(longs)==1 else None,
        'pre_shock_positions':positions,'actual_candidate_account':context.account,'prior_event':previous_event,
        'begin_sequence':begin_sequence,'prefix_state_sha256':state_sha256,'candidate_prefix_repeated':False}


def evidence(packet,binding):
    ctx=packet['context'];case=ctx.path;records=packet['records'];begins={r['event'].id:r for r in records if r['kind']=='BEGIN'}
    shock=binding['nav_closes'][21] if len(binding['nav_closes'])>21 else None
    if case in CASES[:2]:return None
    witnesses=[];kind=None;short=long=None
    if case in SIDE_CASES:
        begin=next((r for r in begins.values() if r['event'].at_ns==shock and r['event'].kind=='CLOSE'),None)
        require(begin is not None or shock is None,'PAIR_ACTIVATION_FIXED_SHOCK_MISSING')
        result=held_activation(ctx,case,binding['input_id'],shock,{} if begin is None else dict(begin['before'].positions),
            None if begin is None else begin['previous_event'],begin_sequence=None if begin is None else begin['sequence'],
            state_sha256=None if begin is None else sha(canonical(encode(begin['before']))))
    elif case=='LOCATE_DENIED':
        kind='DENIED_VALID_SHORT_ENTRY_ATTEMPT'
        for r in records:
            if r['kind']!='SHORT_ENTRY_ATTEMPT' or not r['one_unit_admissible']:continue
            e=begins[r['event']]['event'];attempt=r['frozen_quantity']
            cancellations=[v for v in records if v['kind']=='PAIR_CANCELLED' and v['event']==e.id and
                v['reason']=='MISSING_FAILED_EXPIRED_OR_REUSED_LOCATE' and v.get('frozen_short_quantity')==attempt and
                any(not c.success and c.cap>=attempt and c.execution_event==e.id for c in v.get('candidates',()))]
            if not cancellations:continue
            require(not any(v['kind'] in ('SUBMIT','FILL') and v['event']==e.id and v['command'].phase.startswith('NEW_') for v in records),
                    'PAIR_DENIAL_ZERO_NEW_RISK_EFFECTS')
            witnesses.append({'attempt_sequence':r['sequence'],'event':e.id,'formation':e.formation,'name':r['name'],
                'frozen_quantity':attempt,'one_unit_proposal':r['one_unit_proposal'],
                'cancellation_sequences':[v['sequence'] for v in cancellations],'new_risk_submissions':0,'new_risk_fills':0})
    elif case=='ADVERSE_100BPS':
        kind='ACTUAL_ALL_FILL_ADVERSE_EXECUTION'
        for r in records:
            if r['kind']!='FILL':continue
            e=begins[r['event']]['event'];c=r['command'];q=next(v for v in e.side_quotes if v.name==c.name)
            expected=dict(e.marks)[c.name]*(F(101,100) if c.side=='BUY' else F(99,100))
            require(q.price(c.side)==c.price==r['transition'].operands['price_usd']==expected,'PAIR_ADVERSE_ACTUAL_FILL_JOIN')
            witnesses.append({'sequence':r['sequence'],'event':e.id,'order':r['order_id'],'trade':r['trade_id'],
                'name':c.name,'side':c.side,'reference':q.reference,'execution':expected,'fee_cents':r['transition'].operands['fee_cents']})
    elif case=='BORROW_50':
        kind='POSITIVE_ACTUAL_POST_SHOCK_BORROW_BASE'
        for r in records:
            if r['kind']!='EXTERNAL' or r['transition'].kind!='ACCRUAL_RECOGNITION':continue
            operands=r['transition'].operands;begin=begins[r['event']];previous=begins.get(begin['previous_event'])
            if previous is None or shock is None or previous['event'].at_ns<shock:continue
            if operands['component']=='BORROW' and operands['previous_event_start_base_cents']>0 and operands['elapsed_civil_seconds']>0:
                require(operands['annual_scenario_rate']==F(1,2),'PAIR_BORROW50_ACTUAL_RATE')
                witnesses.append({'sequence':r['sequence'],'event':r['event'],'previous_event':begin['previous_event'],'operands':operands})
    elif case=='MAINTENANCE_160':
        kind='ACTUAL_SHORT_CHECKPOINT_OR_CHANGED_REQUIREMENT_PROPOSAL'
        for r in records:
            e=begins.get(r.get('event'),{}).get('event')
            if e is None or shock is None or e.at_ns<shock:continue
            if r['kind']=='MARK' and any(q<0 for _,q in r['state'].positions):
                require(e.maintenance_short==F(3,5),'PAIR_MAINTENANCE160_COEFFICIENT')
                witnesses.append({'sequence':r['sequence'],'event':e.id,'stage':'ACTUAL_MARK',
                    'changed':maintenance(r['state'],dict(e.marks),e),
                    'baseline':maintenance(r['state'],dict(e.marks),replace(e,maintenance_short=F(3,10)))})
            elif r['kind']=='SHORT_ENTRY_ATTEMPT' and r['one_unit_proposal'].status=='ADMITTED_PROPOSAL_NOT_EXECUTION':
                require(e.maintenance_short==F(3,5),'PAIR_MAINTENANCE160_PROPOSAL_COEFFICIENT')
                witnesses.append({'sequence':r['sequence'],'event':e.id,'stage':'ADMISSION_PROPOSAL',
                    'changed':r['one_unit_maintenance'],'baseline':r['baseline_one_unit_maintenance']})
    else:require(False,'PAIR_UNKNOWN_INTERVENTION')
    if case not in SIDE_CASES:
        result={'schema':'polar.fixed-pair-activation/1','kind':kind,'case':case,'input_id':binding['input_id'],'shock_ns':shock,
            'status':'ACTIVATED' if witnesses else 'NOT_ACTIVATED','short':None,'long':None,
            'actual_candidate_account':ctx.account,'witnesses':witnesses,'candidate_prefix_repeated':False}
    result['evidence_sha256']=sha(canonical(encode(result)))
    return result


def verify_candidate(account,binding):
    require(account['control']=='DYNAMIC_SPREAD','PAIR_ACTIVATION_REQUIRES_CANDIDATE')
    expected=evidence(account['packet'],binding)
    require(account['activation']==expected,'PAIR_CANDIDATE_ACTIVATION_ACTUAL_WITNESS_JOIN')
    return expected



def account_effect(packet,binding,activation):
    ctx=packet['context']
    if ctx.path in CASES[:2]:return {'account':ctx.account,'status':'BASELINE_NOT_REQUIRED'}
    if ctx.path not in SIDE_CASES:
        result=evidence(packet,binding)
        result['actual_account']=result.pop('actual_candidate_account')
        result['status']='AFFECTED' if result['status']=='ACTIVATED' else 'NO_APPLICABLE_EXPOSURE_ATTEMPT_OR_FILL'
        result.pop('evidence_sha256');return result
    begins={r['event'].id:r['event'] for r in packet['records'] if r['kind']=='BEGIN'}
    affected={activation[k] for k in ('short','long') if activation is not None and activation.get(k) is not None
        and (k=='short' or ctx.path in JOINT_CASES)}
    rows=[]
    if activation is not None and activation['status']=='ACTIVATED':
        for r in packet['records']:
            e=begins.get(r.get('event'))
            if e is None or e.at_ns<activation['shock_ns']:continue
            if r['kind']=='MARK' and any(dict(r['state'].positions).get(n,0) for n in affected):rows.append(r['sequence'])
            elif r['kind'] in ('FILL','EXECUTION_UNAVAILABLE'):
                n=r['command'].name if r['kind']=='FILL' else r['name']
                if n in affected:rows.append(r['sequence'])
    return {'account':ctx.account,'status':'AFFECTED' if rows else 'NO_APPLICABLE_HOLDING_OR_EXECUTION',
        'candidate_activation_sha256':None if activation is None else activation['evidence_sha256'],
        'same_candidate_affected_names':sorted(affected),'record_sequences':rows}

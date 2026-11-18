"""Closed native account callback for the unchanged Band policy, and saved checks."""
from datetime import date,datetime,time,timedelta,timezone
from fractions import Fraction
import re

from .band_contract import author,policy_binding,QUESTION,POLICY_SHA,CONTRACT_SHA,PROTOCOL_SHA,IDS,COSTS
from .ci_research import require
from .reference_ridge_plan import nanoseconds
from .gym_contract import canonical

SCHEMA='polar.scheduled-reference-profile/17'
CALENDAR='polar.monthly-native-account-calendar/1'
KIND='QUANT_A_VTI_BIL_NATIVE_BAND'
SPECS=[dict(kind='FEES_LT',right_id='MONTHLY_HALF'),
       dict(kind='TERMINAL_SCALED_GE',right_id='MONTHLY_HALF',factor=[19,20]),
       dict(kind='DRAWDOWN_SCALED_LE',right_id='MONTHLY_HALF',factor=[11,10]),
       dict(kind='POSITIVE_GROWTH'),dict(kind='VTI_FRACTION_MAX_LE',threshold='0.75')]


def validate_profile(p):
    policy_binding()
    require(p['schema']==SCHEMA and p['protocol_id']==QUESTION and p['symbols']==['BIL','VTI'] and
            p['policy']==dict(kind=KIND,policy_sha256=POLICY_SHA,contract_sha256=CONTRACT_SHA) and
            p['protocol_sha256']==PROTOCOL_SHA and p['decision_delay_seconds']==60 and p['cost_scenarios']==COSTS,
            'BAND_CLOSED_PROFILE')
    require([l['id'] for l in p['legs']]==list(IDS) and all(l['rule']==l['id'] and l['scale']==[1,1] for l in p['legs'])
            and p['primary_strategy']=='BAND_HALF' and p['primary_benchmark']=='MONTHLY_HALF' and p['subperiods']==[],
            'BAND_LEGS')
    require(len(p['criteria'])==5 and all({k:v for k,v in c.items() if k not in ('id','description')}==
            dict(left_id='BAND_HALF',**spec) for c,spec in zip(p['criteria'],SPECS)),'BAND_FROZEN_CRITERIA')


def _close(row):
    return nanoseconds(datetime.fromisoformat(row['reference_close_utc'].replace('Z','+00:00')))


def event(formation,execution,schedule,*,first=False,terminal=False):
    rows={r['date']:r for r in schedule}
    known=datetime.combine(date.fromisoformat(formation)+timedelta(days=1),time(),tzinfo=timezone.utc)
    decision=known+timedelta(seconds=60)
    eligible=next((r['date'] for r in schedule if r['date']>formation and _close(r)>nanoseconds(decision)),None)
    require(execution==eligible and _close(rows[formation])+1000<nanoseconds(known)<nanoseconds(decision)<_close(rows[execution]),
            'BAND_FIRST_ELIGIBLE_CLOCK')
    return dict(day=execution,formation=formation,formation_close_ns=_close(rows[formation]),known_ns=nanoseconds(known),
                decision_ns=nanoseconds(decision),open_ns=_close(rows[execution]),kind='REFERENCE',
                band_flags=dict(first=first,month_end_formation=rows[formation]['month_end_in_reference_range'] is True,terminal=terminal))


def calendar_value(calendar,schedule):
    require(calendar.get('schema')==CALENDAR and set(calendar['phases'])=={'VALIDATION','FINAL'},'BAND_CALENDAR')
    days=[r['date'] for r in schedule];rows={r['date']:r for r in schedule}
    require(days==sorted(set(days)),'BAND_SOURCE_DATES')
    for g in calendar['phases'].values():
        require(g['initial'] in rows and g['terminal'] in rows and g['initial']<g['terminal'],'BAND_BOUNDARIES')
        selected=[d for d in days if g['initial']<=d<=g['terminal']]
        require(g['nav_dates']==selected and g['nav_points']==len(selected) and g['return_count']==len(selected)-1,'BAND_GRID')
        formations=list(dict.fromkeys([g['initial']]+[d for d in selected[:-1] if rows[d]['month_end_in_reference_range'] is True]))
        expected=[]
        for formation in formations:
            known=datetime.combine(date.fromisoformat(formation)+timedelta(days=1),time(),tzinfo=timezone.utc)+timedelta(seconds=60)
            execution=next((r['date'] for r in schedule if r['date']>formation and _close(r)>nanoseconds(known)),None)
            if execution is not None and execution<g['terminal']:
                expected.append(event(formation,execution,schedule,first=formation==g['initial']))
        require(expected and expected[0]['band_flags']['first'] and canonical(g['decisions'])==canonical(expected) and
                g['decision_count']==len(expected),'BAND_FORMATION_EVENTS')
        terminal=event(days[days.index(g['terminal'])-1],g['terminal'],schedule,terminal=True)
        require(canonical(g['terminal_exit'])==canonical(terminal),'BAND_TERMINAL_OVERRIDE')
    return calendar['phases']


def plan_phase(market,profile,grid,tz):
    validate_profile(profile)
    require(market['symbols']==['BIL','VTI'],'BAND_MARKET_SYMBOLS')
    rows={r['date']:r for r in market['schedule']}
    decisions=[{**e,'instructions':{leg:dict(kind='NATIVE_BAND_POLICY') for leg in IDS}}
               for e in grid['decisions']+[grid['terminal_exit']]]
    nav=[dict(date=d,nominal_ns=_close(rows[d]),sample_ns=_close(rows[d])+1000,initial=i==0,terminal=d==grid['terminal'])
         for i,d in enumerate(grid['nav_dates'])]
    return dict(profile=dict(kind='REFERENCE_TARGETS',legs=list(IDS),end=grid['terminal']),symbols=['BIL','VTI'],
        prices={d:{s:dict(close_micro=market['prices_micro'][d][s]) for s in ('BIL','VTI')} for d in grid['nav_dates']},
        grid=nav,decisions=decisions,signals=[],quote_basis='SYNTHETIC_VENDOR_ADJUSTED_REFERENCE_UNIT',
        clock_policy='PINNED_REFERENCE_EARLY_CLOSE',capture_consumed_sizing=True,
        consumed_witness_schema='polar.fixed-reference-consumed-operands/1',quantity_unit='WHOLE_SYNTHETIC_REFERENCE_UNIT_NOT_RAW_SHARE',
        price_evidence={d:dict(source_input_sha256=profile['input_sha256'],source_date=d,
            quote_basis='SYNTHETIC_VENDOR_ADJUSTED_REFERENCE_UNIT',price_scale=[1,1]) for d in grid['nav_dates']},
        band_schedule=market['schedule'],native_policy=dict(kind=KIND,question_id=QUESTION,policy_sha256=POLICY_SHA,
            contract_sha256=CONTRACT_SHA,input_sha256=profile['input_sha256']))


def qualify_native_plan(plan):
    policy_binding();p=plan['native_policy']
    require(p['kind']==KIND and p['question_id']==QUESTION and p['policy_sha256']==POLICY_SHA and
            p['contract_sha256']==CONTRACT_SHA and plan['symbols']==['BIL','VTI'] and plan['profile']['legs']==list(IDS),
            'BAND_NATIVE_POLICY_BINDING')
    require(p['cost_scenario'] in ('BASE','COST_STRESS') and p['phase'] in ('VALIDATION','FINAL') and
            plan['cost_profile']==next(c['cost_profile'] for c in COSTS if c['id']==p['cost_scenario']),'BAND_NATIVE_COST_SCOPE')
    from .ci_research_service import root_identity
    from .offline_author_binding import pair_runtime
    from .candidate_binding import loaded_revision
    from pathlib import Path
    require(p['candidate_sha']==loaded_revision() and root_identity(Path(p['artifact_root_identity']['path']))==p['artifact_root_identity']
            and pair_runtime(p['namespace'])==p['runtime_image_id'],'BAND_NATIVE_RUNTIME_ROOT')
    require(re.fullmatch('[a-f0-9]{64}',p['input_sha256']) is not None and
            plan['price_evidence']=={d:dict(source_input_sha256=p['input_sha256'],source_date=d,
                quote_basis='SYNTHETIC_VENDOR_ADJUSTED_REFERENCE_UNIT',price_scale=[1,1]) for d in plan['prices']},
            'BAND_NATIVE_SOURCE_BINDING')
    schedule=plan['band_schedule'];dates=[r['date'] for r in schedule]
    for i,d in enumerate(plan['decisions']):
        expected=event(d['formation'],d['day'],schedule,first=i==0,terminal=i==len(plan['decisions'])-1)
        require(canonical({k:v for k,v in d.items() if k!='instructions'})==canonical(expected) and
                set(d['instructions'])==set(IDS) and all(x==dict(kind='NATIVE_BAND_POLICY') for x in d['instructions'].values()),
                'BAND_NATIVE_EVENT_BINDING')
        require(d['formation'] in dates,'BAND_NATIVE_FORMATION')


def observation(plan,leg,account_id,nav):
    """Called only with the actual adapter's reconciled saved formation row."""
    day=nav['date'];prices={s:plan['prices'][day][s]['close_micro'] for s in ('BIL','VTI')}
    return dict(schema='polar.native-band-formation-observation/1',account_id=account_id,leg=leg,
        phase=plan['native_policy']['phase'],cost_scenario=plan['native_policy']['cost_scenario'],
        source_input_sha256=plan['native_policy']['input_sha256'],source_date=day,formation_close_ns=nav['nominal_ns'],
        observed_sample_ns=nav['sample_ns'],quantities=dict(nav['positions']),cash_cents=nav['cash_cents'],
        prices_micro=prices,marked_values_cents=dict(nav['position_cents']),nav_cents=nav['nav_cents'])


def native_instruction(plan,leg,d,obs):
    """The engine supplies the saved native observation; caller Frames attest nothing."""
    require(obs['leg']==leg and obs['source_date']==d['formation'] and obs['formation_close_ns']==d['formation_close_ns']
            and obs['observed_sample_ns']<d['known_ns'] and obs['source_input_sha256']==plan['native_policy']['input_sha256']
            and obs['phase']==plan['native_policy']['phase'] and obs['cost_scenario']==plan['native_policy']['cost_scenario'],
            'BAND_NATIVE_OBSERVATION_BINDING')
    dt=lambda ns:datetime(1970,1,1,tzinfo=timezone.utc)+timedelta(microseconds=ns//1000)
    frame=author.Frame(date.fromisoformat(d['formation']),dt(d['formation_close_ns']),dt(d['known_ns']),
                       dt(d['decision_ns']),dt(d['open_ns']))
    mark=author.FormationMark(frame,obs['marked_values_cents']['VTI'],obs['marked_values_cents']['BIL'],
                              obs['cash_cents'],obs['nav_cents'])
    decision=author.decide(leg,frame=frame,mark=mark,**d['band_flags'])
    instruction={'kind':decision.kind}
    if decision.weights is not None:instruction['weights']={s:[w.numerator,w.denominator] for s,w in decision.weights}
    observed=decision.observed_vti_weight
    instruction['signal']=dict(kind=KIND,reason=decision.reason,observed_vti_weight=None if observed is None else [observed.numerator,observed.denominator])
    return instruction


def bind_execution_plan(plan,simulation):
    decisions=[]
    for i,d in enumerate(plan['decisions']):
        instructions={leg['id']:leg['intents'][i]['native_policy_instruction'] for leg in simulation['legs']}
        decisions.append({**d,'instructions':instructions})
    return {**plan,'decisions':decisions}


def _expected_instruction(leg,d,obs):
    first,monthly,terminal=(d['band_flags'][k] for k in ('first','month_end_formation','terminal'))
    observed=None;weights=None
    if terminal:kind,reason='EXIT','COMMON_TERMINAL'
    elif first:kind,reason='TARGET','INITIAL'
    elif not monthly:kind,reason='HOLD','NO_MONTH_END_FORMATION'
    elif leg=='MONTHLY_HALF':kind,reason='TARGET','MONTH_END_FORMATION'
    elif leg!='BAND_HALF':kind,reason='HOLD','STATIC_CONTROL'
    else:
        values=obs['marked_values_cents'];total=obs['nav_cents']
        require(total==sum(values.values())+obs['cash_cents'],'BAND_SAVED_MARK_NAV')
        require(total>0,'BAND_SAVED_NONPOSITIVE_MARK')
        observed=Fraction(values['VTI'],total)
        kind='TARGET' if observed<Fraction(2,5) or observed>Fraction(3,5) else 'HOLD'
        reason='OUTSIDE_CLOSED_BAND' if kind=='TARGET' else 'INSIDE_OR_EQUAL_BAND'
    if kind=='TARGET':
        weights={'BIL':[0,1] if leg=='FULL_VTI' else [1,1] if leg=='FULL_BIL' else [1,2],
                 'VTI':[1,1] if leg=='FULL_VTI' else [0,1] if leg=='FULL_BIL' else [1,2]}
    return dict(kind=kind,**({'weights':weights} if weights is not None else {}),
        signal=dict(kind=KIND,reason=reason,observed_vti_weight=None if observed is None else [observed.numerator,observed.denominator]))


def verify_plan(plan,profile,calendar):
    """Saved evidence and inequalities only; never invokes the author callback."""
    validate_profile(profile)
    grids=calendar_value(calendar,calendar['source_schedule_rows'])
    phase=plan['native_policy']['phase'];grid=grids[phase]
    schedule=calendar['source_schedule_rows'];rows={r['date']:r for r in schedule}
    require(plan['band_schedule']==schedule and plan['symbols']==['BIL','VTI'] and
            plan['profile']==dict(kind='REFERENCE_TARGETS',legs=list(IDS),end=grid['terminal']) and
            sorted(plan['prices'])==grid['nav_dates'],'BAND_SAVED_PLAN_GRID')
    require(plan['grid']==[dict(date=d,nominal_ns=_close(rows[d]),sample_ns=_close(rows[d])+1000,
            initial=i==0,terminal=d==grid['terminal']) for i,d in enumerate(grid['nav_dates'])],'BAND_SAVED_NAV_CLOCKS')
    expected=grid['decisions']+[grid['terminal_exit']]
    require(len(plan['decisions'])==len(expected) and all(canonical({k:v for k,v in d.items() if k!='instructions'})==canonical(e)
            for d,e in zip(plan['decisions'],expected)),'BAND_SAVED_DECISION_CLOCKS')
    p=plan['native_policy']
    require(p['kind']==KIND and p['question_id']==QUESTION and p['policy_sha256']==POLICY_SHA and
            p['contract_sha256']==CONTRACT_SHA and p['input_sha256']==profile['input_sha256'] and
            plan['cost_profile']==next(c['cost_profile'] for c in COSTS if c['id']==p['cost_scenario']),'BAND_SAVED_POLICY_SCOPE')
    for d,row in plan['prices'].items():
        require(set(row)=={'BIL','VTI'} and all(set(v)=={'close_micro'} and type(v['close_micro']) is int and v['close_micro']>0
                for v in row.values()),'BAND_SAVED_PRICE_DOMAIN')
    require(plan.get('capture_consumed_sizing') is True and plan.get('consumed_witness_schema')=='polar.fixed-reference-consumed-operands/1'
            and plan.get('quantity_unit')=='WHOLE_SYNTHETIC_REFERENCE_UNIT_NOT_RAW_SHARE','BAND_SAVED_WITNESSES')
    require(plan['price_evidence']=={d:dict(source_input_sha256=profile['input_sha256'],source_date=d,
            quote_basis='SYNTHETIC_VENDOR_ADJUSTED_REFERENCE_UNIT',price_scale=[1,1]) for d in plan['prices']},'BAND_SAVED_SOURCE')


def verify_observations(plan,simulation):
    require([leg['id'] for leg in simulation['legs']]==list(IDS),'BAND_SAVED_ACCOUNT_SET')
    accounts=[]
    for leg in simulation['legs']:
        account=leg['native_account_id'];accounts.append(account);nav={r['date']:r for r in leg['nav']}
        require(len(leg['intents'])==len(plan['decisions']),'BAND_SAVED_OBSERVATION_COUNT')
        for intent,d in zip(leg['intents'],plan['decisions']):
            expected=observation(plan,leg['id'],account,nav[d['formation']])
            require(canonical(intent['native_formation_observation'])==canonical(expected),'BAND_SAVED_ACTUAL_OBSERVATION')
            instruction=_expected_instruction(leg['id'],d,expected)
            require(canonical(intent['native_policy_instruction'])==canonical(instruction) and
                    canonical(d['instructions'][leg['id']])==canonical(instruction),'BAND_SAVED_INSTRUCTION')
    require(len(accounts)==len(set(accounts)),'BAND_SAVED_DISTINCT_ACCOUNTS')


def failure_disposition(error,plan):
    """A demonstrated native checkpoint distinguishes distress from integration failure."""
    from .ci_research import INITIAL_CENTS,fee_cents
    from .obs158_math import cent_round_micro
    events=getattr(error,'events',[])
    if plan is None or not isinstance(events,list):return 'INVALID_SOURCE_OR_INTEGRATION'
    witnesses=[e['witness'] for e in events if isinstance(e,dict) and e.get('phase')=='ECONOMIC_DISTRESS']
    if len(witnesses)!=1:return 'INVALID_SOURCE_OR_INTEGRATION'
    w=witnesses[0]
    try:
        require(w['schema']=='polar.native-band-economic-distress/1' and w['leg'] in IDS and
                w['source_input_sha256']==plan['native_policy']['input_sha256'] and
                w['cost_profile']==plan['cost_profile'],'BAND_DISTRESS_SCOPE')
        partials=[e['partial'] for e in events if isinstance(e,dict) and e.get('phase')=='ACCOUNT_PARTIAL' and e.get('id')==w['leg']]
        require(len(partials)==1 and canonical(partials[0]['economic_distress'])==canonical(w) and
                partials[0]['native_account_id']==w['account_id'],'BAND_DISTRESS_NATIVE_PARTIAL')
        partial=partials[0];held={'BIL':0,'VTI':0};cash=INITIAL_CENTS
        for fill in partial['fills']:
            sign=1 if fill['side']=='BUY' else -1
            held[fill['symbol']]+=sign*fill['q'];cash-=sign*fill['settled_cents']+fill['fee_cents']
        require(w['quantities']==held and w['cash_cents']==cash and cash>=0,'BAND_DISTRESS_NATIVE_STATE')
        if w['kind']=='MANDATORY_SALE_FEE_SHORTFALL':
            symbol=w['symbol'];q=w['quantity'];price=plan['prices'][w['day']][symbol]['close_micro']
            require(type(q) is int and 0<q<=held[symbol] and w['price_micro']==price and
                    w['fee_cents']==fee_cents(q,price,cost_profile=plan['cost_profile']) and
                    w['settled_cents']==cent_round_micro(q*price) and cash+w['settled_cents']-w['fee_cents']<0,
                    'BAND_DISTRESS_SALE')
            orders=[o for o in partial['orders'] if o['at_ns']==w['at_ns'] and o['symbol']==symbol and o['side']=='SELL']
            require(len(orders)==1 and orders[0]['routed_quantity']==q,'BAND_DISTRESS_SALE_ORDER')
        else:
            require(w['kind']=='NONPOSITIVE_NATIVE_NAV','BAND_DISTRESS_KIND')
            amounts={s:cent_round_micro(held[s]*plan['prices'][w['day']][s]['close_micro']) for s in held}
            require(w['marked_values_cents']==amounts and w['nav_cents']==cash+sum(amounts.values())<=0,
                    'BAND_DISTRESS_NAV')
        return 'ECONOMIC_DISTRESS_UNFINALIZED'
    except (ValueError,KeyError,TypeError,ArithmeticError):
        return 'INVALID_SOURCE_OR_INTEGRATION'


def verify_execution_binding(plan,config):
    p=plan['native_policy']
    require(all(p[k]==config[v] for k,v in [('namespace','namespace'),('candidate_sha','code_revision'),
            ('runtime_image_id','runtime_image_id'),('artifact_root_identity','artifact_root_identity')]) and
            p['input_sha256']==config['input_ref']['sha256'],'BAND_EXECUTION_CONFIG_BINDING')


def shared_inputs(plan):
    """Only static inputs and event clocks are shared, never resolved actions."""
    return {**{k:v for k,v in plan.items() if k not in ('cost_profile','native_policy','decisions')},
            'native_policy':{k:v for k,v in plan['native_policy'].items() if k!='cost_scenario'},
            'decisions':[{k:v for k,v in d.items() if k!='instructions'} for d in plan['decisions']]}

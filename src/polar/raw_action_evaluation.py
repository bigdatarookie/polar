"""Saved raw-cash/receivable accounting and frozen descriptive evaluation.

No source mounts, policy execution, native calls or store writes. Receipt replay
proves saved internal consistency, not the authenticity of a rewritten graph.
"""
from fractions import Fraction
from copy import deepcopy

from .ci_research import require, INITIAL_CENTS, fee_cents
from .gym_contract import canonical, sha
from .obs158_math import cent_round_micro
from .distribution_claims import restore
from .raw_action_native import LEGS, replay_event, expand_state, terminal_check
from .raw_action_input import instant
from .scheduled_policy import evaluate_policy
from .scheduled_diagnostics import (_daily_tail, _calendar_months, _metric, _statistics, _costs, _unavailable)
from .scheduled_fixed import _fixed_drawdown


def criteria():
    a,b=LEGS[:2]
    return [{'id':key,'description':key,'left_id':a,**extra} for key,extra in [
        ('WEALTH_11_10',{'kind':'TERMINAL_SCALED_GE','right_id':b,'factor':[11,10]}),
        ('SHARPE_NOT_WORSE',{'kind':'SR_DELTA_GE','right_id':b,'threshold':'0'}),
        ('DRAWDOWN_6_5',{'kind':'DRAWDOWN_SCALED_LE','right_id':b,'factor':[6,5]}),
        ('VOLATILITY_6_5',{'kind':'VOL_SCALED_LE','right_id':b,'factor':[6,5]}),
        ('POSITIVE_GROWTH',{'kind':'POSITIVE_GROWTH'})]]


def evaluate(simulation):
    return evaluate_policy(simulation,{'schema':'polar.raw-action-profile/1','legs':[{'id':x} for x in LEGS],
        'primary_strategy':LEGS[0],'primary_benchmark':LEGS[1],'criteria':criteria()},'FINAL')


def exposure(nav):
    r=nav[1:];require(r,'RAW_EXPOSURE_INTERVALS')
    def mean(key):return _metric(sum((Fraction(x[key],x['nav_cents']) for x in r),Fraction())/len(r))
    return {'status':'OK','intervals':len(r),'mean_raw_position_fraction':mean('exposure_cents'),
        'mean_cash_fraction':mean('cash_cents'),'mean_receivable_fraction':mean('receivable_cents'),
        'maximum_raw_position_fraction':_metric(max(Fraction(x['exposure_cents'],x['nav_cents']) for x in r)),
        'scope':'POSTINITIAL_MARKS_TERMINAL_INCLUDED_NO_MATCHED_RISK_CLAIM'}


def diagnose(tape, schedule, *, base):
    nav=tape['nav']; n=len(nav)-1; horizons={}
    for h in (1,21,63):
        points=[(Fraction(nav[i]['nav_cents'],nav[i-h]['nav_cents'])-1,i) for i in range(h,len(nav))]
        if not points:horizons[str(h)]=_unavailable('INSUFFICIENT_RETURN_INTERVALS');continue
        lo=min(points,key=lambda x:(x[0],x[1]));hi=min(points,key=lambda x:(-x[0],x[1]))
        horizons[str(h)]={'status':'OK','windows':len(points),'minimum':_metric(lo[0]),'maximum':_metric(hi[0]),
            'minimum_end_date':nav[lo[1]]['date'],'maximum_end_date':nav[hi[1]]['date'],'ties':'EARLIEST_RIGHT_ENDPOINT'}
    eras=[]
    if base:
        anchor=next((i for i in reversed(range(len(nav))) if nav[i]['date'].startswith('2020-')),None)
        if anchor is None or anchor in (0,len(nav)-1):
            eras=[{'status':'UNAVAILABLE','reason':'FROZEN_2020_ANCHOR_NOT_INTERIOR'}]
        else:
            for lo,hi in ((0,anchor),(anchor,len(nav)-1)):
                subset=nav[lo:hi+1]
                eras.append({'status':'OK','initial_date':subset[0]['date'],'first_return_date':subset[1]['date'],
                    'last_return_date':subset[-1]['date'],'intervals':len(subset)-1,
                    'initial_state':{k:subset[0][k] for k in ('cash_cents','receivable_cents','positions','position_cents')},
                    'terminal_state':{k:subset[-1][k] for k in ('cash_cents','receivable_cents','positions','position_cents')},
                    'metrics':_statistics(subset),'costs':_costs(tape,subset[0],subset[-1]),
                    'exposure':exposure(subset),'drawdown':_fixed_drawdown(subset),
                    'scope':'CARRIED_NAV_ANCHORS_NO_RESET_NO_DOUBLE_COUNT_NO_EXTRA_LIQUIDATION'})
    # The frozen B7 terminal month is explicitly partial. A range-end marker is
    # not proof that the month ended; never count truncated November as complete.
    month_rows=[{**r,'month_end_in_reference_range':False} if r['date'][:7]==nav[-1]['date'][:7]
        else r for r in schedule]
    return {'schema':'polar.raw-action-saved-diagnostics/1','daily_tail':_daily_tail(nav),
        'rolling_extrema':horizons,'calendar_months':_calendar_months(nav,month_rows),
        'drawdown':_fixed_drawdown(nav),'exposure':exposure(nav),'subperiods':eras,
        'subperiod_status':'BASE_CARRIED_2020_ANCHOR' if base else 'NOT_REQUESTED',
        'uncertainty':'NOT_REQUESTED','robustness':'INSUFFICIENT_EVIDENCE'}


def initial_control(simulation):
    legs=simulation['legs'][:3]; signatures=[]
    for tape in legs:
        intent=tape['intents'][0];day=intent['execution_date']
        fills=[{k:f[k] for k in ('side','q','price_micro','fee_cents','settled_cents','at_ns',
            'exact_notional_micro','settlement_epsilon_micro')} for f in tape['fills']
            if next(r['date'] for r in tape['nav'] if r['sample_ns']>=f['at_ns'])==day]
        row=next(r for r in tape['nav'] if r['date']==day)
        signatures.append({'fills':fills,'mark':{k:row[k] for k in ('nominal_ns','sample_ns','cash_cents',
            'positions','position_cents','receivable_cents','flat_cents','bps_cents','nav_cents')}})
    require(signatures[0]==signatures[1]==signatures[2],'RAW_INITIAL_STATE_MISMATCH')
    return {'status':'PASS','signature':signatures[0],'scope':'WITHIN_COST_LOGICAL_TIMES_NO_ACCOUNT_IDS_OR_WALLCLOCK'}


def verify_tape(tape, plan):
    actions={a['event_id']:a for a in plan['actions']}; previous=None; recognizes=[]; paid=[]
    for e in tape['claim_events']:
        evidence=replay_event(e,actions)
        if previous is not None:require(e['before']==previous,'RAW_CLAIM_TRACE_CHAIN')
        previous=e['after']
        if e['operation']=='recognize':recognizes.append(e['inputs']['action']['event_id'])
        if e['operation']=='pay':paid.append(e['inputs']['event_id'])
    require(previous==tape['final_claim_state'] and set(recognizes)==set(paid)==set(actions) and
        len(recognizes)==len(paid)==len(actions),'RAW_CLAIM_TRACE_COMPLETENESS')
    state=restore(expand_state(previous,actions));require(terminal_check(state,len(actions))==tape['terminal'],'RAW_TERMINAL_REPLAY')
    receipts=tape['settlements'];require(len(receipts)==len(actions) and
        {r['event_id'] for r in receipts}==set(actions),'RAW_SETTLEMENT_COMPLETENESS')
    for r in receipts:
        evidence=replay_event(r['claim_evidence'],actions)
        before=restore(expand_state(r['claim_evidence']['before'],actions));after=restore(expand_state(r['claim_evidence']['after'],actions))
        delta=after.available_cash_cents-before.available_cash_cents
        require(r['claim_evidence'] in tape['claim_events'] and r['event_id']==r['claim_evidence']['inputs']['event_id'] and
            r['external_cash_flow_cents']==0 and r['claim_decrease_cents']==delta and
            r['before']=={'total':before.available_cash_cents,'free':before.available_cash_cents,'locked':0} and
            r['after']=={'total':after.available_cash_cents,'free':after.available_cash_cents,'locked':0} and
            r['nav_before_cents']==r['nav_after_cents'] and r['native_balance_updates']==int(delta>0),
            'RAW_SETTLEMENT_TRANSFER_REPLAY')
        observed=r['native_account_event']
        if delta:
            from dataclasses import asdict
            require(observed['balances']==r['after'] and observed['ts_event']==r['at_ns'] and
                observed['info']=={'kind':'INTERNAL_DISTRIBUTION_RECEIVABLE_SETTLEMENT',
                    'event_id':r['event_id'],'claim_evidence_sha256':sha(canonical(asdict(evidence))),
                    'external_cash_flow_cents':0,'claim_decrease_cents':delta},'RAW_NATIVE_ACCOUNT_EVENT_REPLAY')
        else:require(observed is None,'RAW_ZERO_NATIVE_EVENT')
    require([r['date'] for r in tape['nav']]==plan['dates'],'RAW_SAVED_NAV_DATES')
    q=0;cash=INITIAL_CENTS;flat=bps=0;recognized={};settled=set();cost=plan['cost_profile']
    events=plan['events'];require(len(tape['intents'])==len(events),'RAW_INTENT_COUNT')
    for i,event in enumerate(events):
        intent=tape['intents'][i]
        require(all(intent[k]==v for k,v in event.items()) and intent['known_ns']<intent['decision_ns']<intent['close_ns'],
                'RAW_INTENT_CLOCK_BINDING')
    for row in tape['nav']:
        day=row['date']
        for a in plan['actions']:
            if a['ex_date']==day:
                matched=next(e for e in tape['claim_events'] if e['operation']=='recognize' and e['inputs']['action']['event_id']==a['event_id'])
                s=restore(expand_state(matched['after'],actions));c=next(c for c in s.claims if c.action.event_id==a['event_id'])
                require(c.entitled_quantity==q,'RAW_SAVED_PRIOR_HOLDER');recognized[a['event_id']]=c.cents
        for r in receipts:
            if r['claim_evidence']['inputs']['session_date']==day:
                require(r['at_ns']==instant(next(x for x in plan['schedule'] if x['date']==day)['reference_close_utc'])+10,
                        'RAW_SAVED_PAY_CLOCK')
                cash+=r['claim_decrease_cents'];settled.add(r['event_id'])
        for fill in tape['fills']:
            if not row['nominal_ns']<=fill['at_ns']<row['sample_ns']:continue
            side=fill['side'];amount=fill['q'];p=plan['prices'][day]['close_micro']
            require(type(amount) is int and amount>0 and fill['price_micro']==p and
                fill['fee_cents']==fee_cents(amount,p,cost_profile=cost) and
                fill['exact_notional_micro']==amount*p and fill['settled_cents']==cent_round_micro(amount*p),
                'RAW_FILL_MONEY_REPLAY')
            intent=next(v for v in tape['intents'] if v['execution_date']==day)
            desired=max(q-intent['target'],0) if side=='SELL' else max(intent['target']-q,0)
            require(fill['intended_quantity']==desired and 0<amount<=desired and
                fill['at_ns']==row['nominal_ns']+(100 if side=='SELL' else 200),'RAW_FROZEN_TARGET_FILL')
            q+=amount if side=='BUY' else -amount
            cash+=(fill['settled_cents'] if side=='SELL' else -fill['settled_cents'])-fill['fee_cents']
            require(q>=0 and cash>=0 and cash==fill['cash_after_cents'],'RAW_SAVED_CASH_HOLDINGS')
            flat+=cost['flat_cents'];bps+=fill['fee_cents']-cost['flat_cents']
        receivable=sum(v for k,v in recognized.items() if k not in settled)
        mark=cent_round_micro(q*plan['prices'][day]['close_micro'])
        require(row['positions']=={plan['instrument']:q} and row['position_cents']=={plan['instrument']:mark} and
            row['cash_cents']==cash and row['receivable_cents']==receivable and
            row['exposure_cents']==mark and row['nav_cents']==cash+mark+receivable and
            row['flat_cents']==flat and row['bps_cents']==bps and
            row['pending_claim_count']==len(set(recognized)-settled),'RAW_SAVED_LEDGER_RECONCILIATION')
    require(q==0 and not (set(recognized)-settled),'RAW_SAVED_TERMINAL')
    return {'status':'VERIFIED_SAVED_CONSISTENCY','source_or_native_authenticity':'NOT_DERIVED_BY_PURE_REPLAY'}

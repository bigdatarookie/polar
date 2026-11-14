"""Fixed source-aware paired-policy producer, not a Service or run grant."""
from dataclasses import dataclass,asdict
from datetime import datetime,timezone
from fractions import Fraction as F
from copy import deepcopy
from .signed_pair_input import PairInput,Quote,preflight,price,decision_targets,NAMES,CONTROLS,CASES
from .signed_pair_native import run_pair_timeline
from .signed_event_driver import AccountContext,PairEvent,Rate,Locate,NS
from .signed_native_bridge import MarkEvent,MarkIdentity,require
from .signed_account_core import mark
from .signed_execution_terms import execution_quote


def decimal_token(value):
    require(type(value) is F,'PAIR_EXACT_TOKEN')
    n,d=value.numerator,value.denominator;k=0
    while d>1 and d%2==0:d//=2;k+=1
    j=0
    while d>1 and d%5==0:d//=5;j+=1
    require(d==1,'PAIR_NONDECIMAL_OVERLAY')
    scale=max(k,j);raw=n*10**scale//value.denominator
    return str(raw) if not scale else f'{raw//10**scale}.{raw%10**scale:0{scale}d}'


def epoch_date(day):return int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp())*NS


from .signed_pair_activation import scenario_factor as factor


def produce_account(data,control,case,*,activation=None,observer=None):
    """Explicit caller invocation on supplied values. No retained permission."""
    preflight(data)
    for a in data.actions:
        nominal=F(dict(data.nominal_action_tokens)[a.id]);require(nominal>=0 and nominal==a.nominal_usd,'PAIR_NOMINAL_TOKEN_CORRESPONDENCE')
    require(control in CONTROLS and case in CASES,'PAIR_DECLARED_ACCOUNT')
    require(control=='DYNAMIC_SPREAD' or case in CASES[:2] or activation is not None,'PAIR_CONTROL_NEEDS_CANDIDATE_ACTIVATION')
    rows={n:tuple(q for q in data.quotes if q.name==n) for n in NAMES};closes=tuple(q.close_ns for q in rows[NAMES[0]])
    navindex={t:i for i,t in enumerate(data.nav_closes)}
    shock_ns=data.nav_closes[21] if len(data.nav_closes)>21 else None
    if activation is not None:
        require(activation['case']==case and activation['input_id']==data.input_id and activation['shock_ns']==shock_ns,
                'PAIR_SHARED_ACTIVATION_JOIN')
    state={'activation':deepcopy(activation),'decisions':{},'D_receipts':[],'NAV':[],'slots':[]}
    source_context='INVENTED/' if data.namespace=='INVENTED' else ''
    ctx=AccountContext(source_context+data.input_id+'/'+case+'/'+control,case,data.protocol_sha256,data.input_id,NAMES)
    dmap={f.decision_ns:f for f in data.formations};qmap={f.execution_ns:f for f in data.formations}
    require(len(dmap)==len(qmap)==len(data.formations),'PAIR_FORMATION_COLLISION')
    exmap={}
    for a in data.actions:
        require(a.ex_date is not None and a.payment_date is not None,'PAIR_ACTION_CLOCK_UNKNOWN')
        t=epoch_date(a.ex_date)
        if data.nav_closes[0]<t<=data.nav_closes[-1]:exmap.setdefault(t,[]).append(a)
    times=tuple(sorted(set(data.nav_closes)|set(dmap)|set(exmap)|{data.terminal_decision_ns}))
    require(not(set(dmap)&set(data.nav_closes)) and not(set(exmap)&set(data.nav_closes)),'PAIR_CLOSED_SLOT_COLLISION')
    def factory(index,driver):
        t=times[index]
        from .signed_pair_activation import SIDE_CASES,held_activation
        if t==shock_ns and case in SIDE_CASES and control=='DYNAMIC_SPREAD':
            state['activation']=held_activation(ctx,case,data.input_id,shock_ns,dict(driver.bridge.state.positions),
                None if driver.previous is None else driver.previous.id)
        active=state['activation'];eid=ctx.account+':'+str(t)
        prior=max(i for i,q in enumerate(rows[NAMES[0]]) if q.close_ns<=t)
        marks={n:price(rows[n][prior].raw_usd_token,raw=True)*factor(case,n,closes[prior],active) for n in NAMES}
        identities=tuple(MarkIdentity(n,rows[n][prior].local_id,rows[n][prior].raw_source_ref,
            closes[prior],None,'PRE_EX_CUM_MARK_WITH_NEW_CLAIM' if t in exmap else 'MODELED',
            'CURRENT_VINTAGE_RAW_USD_CONDITIONAL_NOT_PIT') for n in NAMES)
        kind='EX' if t in exmap else 'CLOSE' if t in navindex else 'OBSERVATION'
        instruction='HOLD';targets=();formation=None;decision_ns=None;locates=()
        f=qmap.get(t)
        if f is not None and f.id in state['decisions']:
            decision=state['decisions'][f.id]
            if decision['status']=='SIZED':
                instruction='TARGET';targets=tuple(sorted(decision['sizing']['targets'].items()));formation=f.id;decision_ns=f.decision_ns
        if t==data.terminal_execution_ns:
            instruction='EXIT';targets=tuple((n,0) for n in NAMES);formation='TERMINAL_EXIT';decision_ns=data.terminal_decision_ns
        stressed=case=='TRADING_2X_BORROW_5X_DEBIT_1P5X'
        after_shock=shock_ns is not None and t>=shock_ns
        borrow=F(1,2) if after_shock and case=='BORROW_50' else F(15 if stressed else 3,100)
        rates=tuple(Rate('BORROW',n,borrow,'MODELED_CONDITIONAL_BORROW') for n in NAMES)+(
            Rate('DEBIT_INTEREST',None,F(12 if stressed else 8,100),'MODELED_CONDITIONAL_DEBIT'),)
        affected=active['short'] if after_shock and active is not None and active['status']=='ACTIVATED' else None
        recall=after_shock and affected is not None and case in ('RECALL_BLACKOUT2','LONG_0P7_SHORT_1P5_RECALL')
        blacked=(recall and t in navindex and 1<=navindex[t]-navindex[active['shock_ns']]<=2)
        quotes=tuple(execution_quote(n,eid,case,marks[n],adverse=case=='ADVERSE_100BPS') for n in NAMES
            if kind=='CLOSE' and not(blacked and n==affected))
        if instruction=='TARGET' and control in ('DYNAMIC_SPREAD','STATIC_SPREAD'):
            short=next((n for n,q in targets if q<0),None)
            if short is not None:
                # Reserve the frozen incremental short cap, separately per actual
                # account/event, never candidate token reuse or Q-sized increase.
                old=dict(driver.bridge.state.positions).get(short,0)
                cap=max(0,abs(dict(targets)[short])-abs(min(old,0)))
                locates=(Locate(eid+':locate',case,ctx.account,formation,short,'SHORT',eid,cap,
                    case!='LOCATE_DENIED','MODELED_INVENTED_OR_CONDITIONAL_INVENTORY_NOT_OBSERVED'),)
        return PairEvent(eid,t,kind,tuple(sorted(marks.items())),MarkEvent(eid+':mark',t,identities),
            instruction,formation,decision_ns,targets,locates=locates,actions=tuple(exmap.get(t,())),rates=rates,
            recalled=(affected,) if recall and t==active['shock_ns'] else (),
            maintenance_short=F(3,5) if after_shock and case=='MAINTENANCE_160' else F(3,10),
            flat_fee_cents=200 if stressed else 100,fee_bps=20 if stressed else 10,
            terminal=t==data.terminal_execution_ns,side_quotes=quotes,
            portfolio_role='PAIRED' if control in ('DYNAMIC_SPREAD','STATIC_SPREAD') else 'HALF_LONG' if control=='DYNAMIC_HALF_LONG' else 'CASH',
            exposure_response=control in ('DYNAMIC_SPREAD','STATIC_SPREAD'))
    def completed(driver,record):
        e=driver.previous # not yet assigned until finish returns? use END->BEGIN lookup below
        begin=next(r for r in reversed(driver.records) if r['kind']=='BEGIN')['event']
        t=begin.at_ns
        if t in navindex:
            report=mark(driver.bridge.state,dict(begin.marks))
            state['NAV'].append({'nominal_ns':t,'date':datetime.fromtimestamp(t//NS,timezone.utc).date().isoformat(),
                'nav_cents':report['equity_cents'],'state':driver.bridge.state,'report':report,
                'default_ever':driver.default_ever,'overdue_ever':driver.overdue_ever,
                'pending_flatten':deepcopy(driver.flatten),'event_id':begin.id})
        if t in dmap:
            if observer:observer('DECISION_ENTRY',{'formation_id':dmap[t].id})
            f=dmap[t];report=mark(driver.bridge.state,dict(begin.marks))
            witness={'status':'UNAVAILABLE_DEFAULT_OR_NONPOSITIVE_D_NAV' if report['equity_cents']<=0 or driver.default_ever else 'SIZED',
                'formation':asdict(f),'actual_D_event':begin.id,'actual_D_mark':begin.mark_event,
                'actual_D_END_sequence':next(r['sequence'] for r in reversed(driver.records) if r['kind']=='END'),
                'actual_D_state':driver.bridge.state,'own_D_report':report}
            if witness['status']=='SIZED':
                if observer:observer('FEATURE_ENTRY',{'formation_id':f.id})
                raw={n:decimal_token(price(rows[n][f.g_index].raw_usd_token,raw=True)*factor(case,n,closes[f.g_index],state['activation'])) for n in NAMES}
                lag21={n:decimal_token(price(rows[n][f.endpoint21_index].adjusted_signal_token,raw=False)*factor(case,n,closes[f.endpoint21_index],state['activation'])) for n in NAMES}
                lag252={n:decimal_token(price(rows[n][f.endpoint252_index].adjusted_signal_token,raw=False)*factor(case,n,closes[f.endpoint252_index],state['activation'])) for n in NAMES}
                require(dict(begin.marks)=={n:price(raw[n],raw=False) for n in NAMES},'PAIR_ACTUAL_D_RAW_G_MARK_JOIN')
                witness['consumed_tokens']={'raw_g':raw,'signal21':lag21,'signal252':lag252}
                witness['source_members']={n:tuple(asdict(rows[n][i]) for i in (f.g_index,f.endpoint21_index,f.endpoint252_index)) for n in NAMES}
                witness['sizing']=decision_targets(control,report['equity_cents'],raw,lag21,lag252)
                witness['source_ids']={n:tuple(rows[n][i].local_id for i in (f.g_index,f.endpoint21_index,f.endpoint252_index)) for n in NAMES}
            state['decisions'][f.id]=witness;state['D_receipts'].append(witness)
    def observe_native(kind,driver=None,details=None):
        if observer is None:return
        def snapshot():
            return {'schema':'polar.private-pair-active-prefix/1','control':control,'case':case,
                'native':driver.failure_evidence(RuntimeError('PERIODIC_PREFIX_NOT_COMPLETED')) if driver else None,
                'D_receipts':deepcopy(state['D_receipts']),'NAV':deepcopy(state['NAV']),
                'activation':deepcopy(state['activation']),'frontier':'OBSERVED_PREFIX_ONLY_NOT_COMPLETE'}
        observer(kind,{'details':details or {},'snapshot':snapshot})
    out=run_pair_timeline(ctx,times,factory,on_completed=completed,observer=observe_native if observer else None)
    from .signed_pair_saved import binding_for
    from .signed_pair_activation import evidence,account_effect
    actual_binding=binding_for(data)
    if control=='DYNAMIC_SPREAD':state['activation']=evidence(out['packet'],actual_binding)
    own_effect=account_effect(out['packet'],actual_binding,state['activation'])
    return {'schema':'polar.private-fixed-pair-account/1','context':ctx,'control':control,'case':case,
        'input_id':data.input_id,'protocol_sha256':data.protocol_sha256,'packet':out['packet'],
        'D_receipts':state['D_receipts'],'NAV':state['NAV'],'activation':state['activation'],
        'intervention_effect':own_effect,
        'source_access':'UNQUALIFIED','execution_authority':False,'financial_assessment':'NOT_ISSUED'}


class PairStudyFailure(RuntimeError):
    def __init__(self,error,evidence):
        super().__init__(str(error));self.evidence=evidence


def produce_pair_study(data):
    """48 native accounts if explicitly invoked. Not authorized on retained data."""
    preflight(data);accounts=[];activations={};current=None
    try:
        for case in CASES:
            current=('DYNAMIC_SPREAD',case)
            candidate=produce_account(data,'DYNAMIC_SPREAD',case);accounts.append(candidate)
            activations[case]=candidate['activation']
            for control in CONTROLS[1:]:
                current=(control,case)
                accounts.append(produce_account(data,control,case,activation=activations[case]))
    except Exception as exc:
        entered=getattr(exc,'pair_native_entry',None)
        raise PairStudyFailure(exc,{'status':'TECHNICAL_UNFINALIZED','completed_accounts':accounts,
            'actual_completed':len(accounts),'active_account':current,'active_partial':getattr(exc,'pair_partial',None),
            'actual_active_entry':entered,'actual_total_entries':len(accounts)+1 if entered is not None else None,
            'entry_count_status':'OBSERVED' if entered is not None else 'UNKNOWN_NOT_ASSUMED_ZERO',
            'activations':activations,'successful_complete_study':False,'retained_dispatch_authority':False}) from exc
    from .signed_pair_metrics import evaluate
    result={'schema':'polar.private-fixed-pair-study/1','input_id':data.input_id,'protocol_sha256':data.protocol_sha256,
        'accounts':accounts,'activations':activations,'actual_native_completed':len(accounts),
        'retained_dispatch_authority':False,'financial_assessment':'NOT_ISSUED'}
    from .signed_pair_saved import verify_study,binding_for
    result['evaluation']=verify_study(result,binding_for(data))
    return result

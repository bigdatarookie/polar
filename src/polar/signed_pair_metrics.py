"""Fixed signed pair saved scalar definitions; no source/native/policy calls."""
from fractions import Fraction as F
from decimal import (Context,localcontext,ROUND_HALF_EVEN,Decimal,DecimalException,
    InvalidOperation,DivisionByZero,Overflow,Underflow,Subnormal,Clamped,FloatOperation,Inexact,Rounded)
from .signed_native_bridge import require
from .signed_pair_input import CASES,CONTROLS


def context():
    c=Context(prec=50,rounding=ROUND_HALF_EVEN,Emin=-999999,Emax=999999,capitals=1,clamp=0)
    for signal in c.traps:c.traps[signal]=signal in (InvalidOperation,DivisionByZero,Overflow,Underflow,Subnormal,Clamped,FloatOperation)
    c.traps[Inexact]=c.traps[Rounded]=False;c.clear_flags();return c


def project(x):return Decimal(x.numerator)/Decimal(x.denominator)


def numeric(fn):
    with localcontext(context()) as c:
        c.clear_flags()
        try:value=fn();result={'status':'OK','value':str(value),'reason':None}
        except DecimalException as exc:result={'status':'NUMERICAL_ERROR','value':None,'reason':type(exc).__name__}
        return {**result,'flags':[k.__name__ for k,v in c.flags.items() if v],
                'definition':'D50_HALF_EVEN_EMIN-999999_EMAX999999_NO_AMBIENT'}


def unavailable(reason,**operands):return {'status':'UNAVAILABLE','reason':reason,'value':None,**operands}


def metrics(account):
    nav=account['NAV'];require(nav and nav[0]['nav_cents']==10000000 and
        all(type(r['nav_cents']) is int for r in nav) and
        all(a['nominal_ns']<b['nominal_ns'] for a,b in zip(nav,nav[1:])),'PAIR_SAVED_NAV_CENSUS')
    values=[r['nav_cents'] for r in nav];n=len(values)-1;peak=values[0];peak_i=0;depth=F();trough=0;episode_peak=0
    for i,value in enumerate(values):
        if value>=peak:peak=value;peak_i=i
        dd=1-F(value,peak)
        if dd>depth:depth=dd;trough=i;episode_peak=peak_i
    recovery=next((i for i in range(trough+1,len(values)) if values[i]>=values[episode_peak]),None) if depth else None
    dd={'maximum':depth,'peak_index':episode_peak if depth else None,'trough_index':trough if depth else None,
        'recovery_index':recovery,'recovery_status':'NO_DRAWDOWN' if not depth else 'RECOVERED' if recovery is not None else 'CENSORED',
        'censored_elapsed_sessions':len(values)-1-episode_peak if depth and recovery is None else None,'tie_rule':'LATEST_EQUAL_PEAK_FIRST_MAXIMUM_TROUGH'}
    default=any(r['default_ever'] or r['nav_cents']<=0 for r in nav)
    result={'initial_cents':values[0],'terminal_cents':values[-1],'simple_growth':F(values[-1],values[0])-1,
        'n':n,'default_ever':default,'drawdown':dd,'minimum_equity_cents':min(values),
        'maximum_deficit_cents':max(0,-min(values))}
    if default or not n:
        result.update({key:unavailable('INAPPLICABLE_NONPOSITIVE_NAV_OR_DEFAULT' if default else 'INSUFFICIENT_INTERVALS',
            full_census_intervals=n) for key in ('mean','variance','volatility','sharpe','ES','CAGR','worst_day','worst20')})
    else:
        returns=[F(b,a)-1 for a,b in zip(values,values[1:])];mean=sum(returns,F())/n
        variance=sum(((r-mean)**2 for r in returns),F())/(n-1) if n>1 else None
        k=(n+19)//20;ordered=sorted(enumerate(returns),key=lambda v:(-(-v[1]),nav[v[0]+1]['date']))
        es=-sum((r for _,r in ordered[:k]),F())/k
        worst=ordered[0]
        windows=[(F(values[i+20],values[i])-1,i) for i in range(len(values)-20)]
        w=min(windows,key=lambda v:(v[0],v[1])) if windows else None
        result.update(mean={'status':'OK','value':mean},variance={'status':'OK','value':variance} if variance is not None else unavailable('INSUFFICIENT_INTERVALS'),
            volatility=numeric(lambda:project(252*variance).sqrt()) if variance is not None else unavailable('INSUFFICIENT_INTERVALS'),
            sharpe=numeric(lambda:Decimal(252).sqrt()*project(mean)/project(variance).sqrt()) if variance else unavailable('ZERO_VARIANCE_OR_INSUFFICIENT'),
            ES={'status':'OK','value':es,'k':k,'n':n,'selected_dates':[nav[i+1]['date'] for i,_ in ordered[:k]],'signed_losses':True},
            CAGR=numeric(lambda:(project(F(values[-1],values[0])).ln()*project(F(252,n))).exp()-1),
            worst_day={'return':worst[1],'date':nav[worst[0]+1]['date']},
            worst20=unavailable('INSUFFICIENT_INTERVALS') if w is None else {'return':w[0],'start_date':nav[w[1]]['date'],'end_date':nav[w[1]+20]['date']})
    fills=[r['transition'].operands for r in account['packet']['records'] if r['kind']=='FILL']
    result['costs']={'actual_commission_cents':sum(f['fee_cents'] for f in fills),
        'gross_settled_notional_cents':sum(f['settled_notional_cents'] for f in fills),
        'turnover_initial':F(sum(f['settled_notional_cents'] for f in fills),values[0]),'actual_fill_count':len(fills),
        'borrow_and_debit_recognition':[(a.component,a.recognized_cents,a.settled_cents,a.exact_cents)
            for a in account['packet']['final_state'].accruals]}
    exposures=[]
    for row in nav:
        e=row['nav_cents'];marks=row['report']['position_marks_cents'];gross=sum(abs(v) for v in marks.values());net=sum(marks.values())
        exposures.append({'date':row['date'],'equity_cents':e,'position_marks_cents':marks,'gross_cents':gross,'net_cents':net,
            'gross_fraction':F(gross,e) if e>0 else None,'net_fraction':F(net,e) if e>0 else None,
            'name_fractions':{n:F(v,e) for n,v in marks.items()} if e>0 else None,
            'status':'OK' if e>0 else 'INAPPLICABLE_NONPOSITIVE_EQUITY'})
    positive=exposures[1:];defined=[r for r in positive if r['equity_cents']>0]
    result['exposure']={'rows':exposures,'postinitial_count':len(positive),'excluded_nonpositive':len(positive)-len(defined),
        'mean_gross':sum((r['gross_fraction'] for r in defined),F())/len(defined) if defined else None,
        'mean_net':sum((r['net_fraction'] for r in defined),F())/len(defined) if defined else None,
        'maximum_gross':max((r['gross_fraction'] for r in defined),default=None),
        'maximum_absolute_net':max((abs(r['net_fraction']) for r in defined),default=None),
        'maximum_absolute_name':max((abs(v) for r in exposures if r['name_fractions'] is not None for v in r['name_fractions'].values()),default=None)}
    records=account['packet']['records'];events={r['event'].id:r['event'] for r in records if r['kind']=='BEGIN'}
    from .signed_event_driver import maintenance
    margins=[]
    for r in records:
        if r['kind'] not in ('MARK','FILL','END'):continue
        e=events[r['event']];state=r['transition'].after if r['kind']=='FILL' else r['state']
        risk=maintenance(state,dict(e.marks),e)
        margins.append({'sequence':r['sequence'],'event':e.id,'stage':r['kind'],
            'equity_cents':risk['report']['equity_cents'],'requirement_cents':risk['equity_requirement_cents'],
            'buffer_ratio':risk['buffer_ratio'],'restriction_deficits_cents':risk['restriction_deficits_cents'],
            'passes':risk['passes']})
    result['margin']={'checkpoints':margins,'minimum_defined_buffer_ratio':min((r['buffer_ratio'] for r in margins if r['buffer_ratio'] is not None),default=None),
        'undefined_nonpositive_equity_count':sum(r['buffer_ratio'] is None for r in margins),
        'breach_count':sum(not r['passes'] for r in margins),
        'flatten_queued':sum(r['kind']=='FLATTEN_QUEUED' for r in records),
        'forced_fill_count':sum(r['kind']=='FILL' and r['command'].forced for r in records),
        'locate_reserved':sum(r['kind']=='LOCATE_RESERVED' for r in records),
        'locate_or_pair_cancellations':sum(r['kind']=='PAIR_CANCELLED' for r in records),
        'recall_of_actual_short_count':sum(r['kind']=='FLATTEN_QUEUED' and 'RECALL' in r['flatten']['reasons'] for r in records)}
    fee_rows=[r['fee'] for r in records if r['kind']=='ACTUAL_ORDER_FEE_CENSUS']
    result['costs'].update(flat_cents=sum(r['flat_cents'] for r in fee_rows),bps_cents=sum(r['bps_cents'] for r in fee_rows),
        distribution_receivable_cents=sum(c.cents for c in account['packet']['final_state'].claims if c.kind=='RECEIVABLE'),
        distribution_payable_cents=sum(c.cents for c in account['packet']['final_state'].claims if c.kind=='PAYABLE'))
    require(sum(r['total_cents'] for r in fee_rows)==result['costs']['actual_commission_cents'],'PAIR_FEE_COMPONENT_CENSUS')
    unqualified_funding=any(r['kind']=='FILL' and r['transition'].operands['funding_mode']!='NO_CREDIT' for r in records)
    result['confirmed_execution_breach_ever']=any(r['kind']=='FILL' and r['transition'].status=='CONFIRMED_EXECUTION_BREACH' for r in records)
    result['survival']=(not result['confirmed_execution_breach_ever'] and not default and not unqualified_funding and not any(r['overdue_ever'] for r in nav) and
        not any(q for _,q in account['packet']['final_state'].positions) and
        not any(r['kind'] in ('UNSUPPORTED_ACTION','MODEL_OVERDUE_PAYMENT_EPISODE') for r in account['packet']['records']))
    return result


def evaluate(accounts):
    lookup={(a['control'],a['case']):a for a in accounts}
    require(len(lookup)==len(accounts),'PAIR_DUPLICATE_ACCOUNT')
    missing=[(c,p) for p in CASES for c in CONTROLS if (c,p) not in lookup]
    report={c+'/'+p:metrics(a) for (c,p),a in lookup.items()}
    return evaluate_reports(report,{p:a['activation'] for (c,p),a in lookup.items() if c=='DYNAMIC_SPREAD'})


def evaluate_reports(report,activations):
    """Same closed clauses on independently verified per-account scalar reports.

    Allows a streaming reader to evict each full tape before the next member.
    This function does not authenticate scalar reports or candidate activation.
    """
    missing=[(c,p) for p in CASES for c in CONTROLS if c+'/'+p not in report]
    clauses=[]
    def add(id,value,**operands):clauses.append({'id':id,'status':'UNAVAILABLE' if value is None else 'MET' if value else 'NOT_MET','operands':operands})
    for p in CASES[:2]:
        s=report.get('DYNAMIC_SPREAD/'+p);b=report.get('DYNAMIC_HALF_LONG/'+p)
        if s is None:
            for id in ('WEALTH','GROWTH','SHARPE','DD','VOL','ES'):add(p+'/'+id,None)
            continue
        add(p+'/WEALTH',100*s['terminal_cents']>=101*b['terminal_cents'] if b is not None else None)
        add(p+'/GROWTH',s['terminal_cents']>10000000)
        valid=s['variance'].get('status')=='OK' and s['variance'].get('value') not in (None,0)
        add(p+'/SHARPE',s['mean']['value']>=0 if valid else None)
        add(p+'/DD',s['drawdown']['maximum']<=F(1,5))
        valid=b is not None and s['variance'].get('status')==b['variance'].get('status')=='OK'
        add(p+'/VOL',16*s['variance']['value']<=25*b['variance']['value'] if valid else None)
        valid=b is not None and s['ES'].get('status')==b['ES'].get('status')=='OK'
        add(p+'/ES',(4*s['ES']['value']<=5*b['ES']['value'] if b['ES']['value']>0 else s['ES']['value']<=b['ES']['value']) if valid else None)
    for p in CASES[:10]:
        r=report.get('DYNAMIC_SPREAD/'+p);activation=activations.get(p)
        activated=p in CASES[:2] or activation is not None and activation['status']=='ACTIVATED'
        add(p+'/SURVIVAL',r['survival'] if r is not None and activated else None,activation=activated)
    statuses=[c['status'] for c in clauses]
    return {'schema':'polar.private-fixed-pair-evaluation/1','metrics':report,'clauses':clauses,'missing_accounts':missing,
        'producer_screen':'NOT_SUPPORTED' if 'NOT_MET' in statuses else 'INSUFFICIENT_EVIDENCE' if missing or 'UNAVAILABLE' in statuses else 'CONDITIONAL_POINT_SCREEN_MET',
        'independent_financial_assessment':'NOT_ISSUED','adoption':'INSUFFICIENT_EVIDENCE','native_calls':0,'writes':0}

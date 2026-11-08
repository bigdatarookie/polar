"""Frozen exact-rational/Decimal50 evaluation, independent of native reports."""
from decimal import Decimal, localcontext
from fractions import Fraction
from .gym_contract import (GymError, context, decimal_fraction as D, decimal_string as S,
                           fraction, rational, metric, STRATEGIES, SYMBOLS)

def evaluate_strategy(tape):
    with localcontext(context()):
        return _evaluate(tape)

def _evaluate(tape):
    rows=tape['nav'];returns=[];unavailable=None;values=[]
    for row in rows:
        try:
            if row.get('nav') is None:
                unavailable=metric(None,'INSUFFICIENT_EVIDENCE','MISSING_NAV_ENDPOINT');values.append(None)
            else:
                nav=fraction(row['nav']);values.append(nav)
                if nav<=0: unavailable=metric(None,'INVALID','INVALID_NAV')
        except (GymError,ArithmeticError,ValueError):
            values.append(None);unavailable=metric(None,'INVALID','INVALID_NAV')
    if not rows: unavailable=metric(None,'INSUFFICIENT_EVIDENCE','MISSING_NAV_ENDPOINT')
    for i in range(1,len(rows)):
        a,b=values[i-1:i+1];status='OK';reason=None;r=None
        if a is None or b is None: status='INSUFFICIENT_EVIDENCE';reason='MISSING_NAV_ENDPOINT'
        elif a<=0 or b<=0: status='INVALID';reason='INVALID_NAV'
        else: r=b/a-1
        returns.append({'start_nominal_ns':rows[i-1]['nominal_ns'],'end_nominal_ns':rows[i]['nominal_ns'],
                        'exact_fraction':rational(r) if r is not None else None,
                        'decimal50':S(D(r)) if r is not None else None,'status':status,'reason':reason})
    names=('total_return','CAGR','ES95','Sharpe_252','annualized_volatility','maximum_drawdown',
           'maximum_close_name_concentration','fees_USD','final_NAV_USD','turnover_over_initial',
           'gross_executed_notional','mean_return','sample_variance')
    metrics={name:metric(None,'INSUFFICIENT_EVIDENCE','NO_RETURN_INTERVALS') for name in names}
    details={'worst_period':None,'drawdown':None,'concentration':None,'ES95_intervals':[]}
    if unavailable:
        metrics={name:dict(unavailable) for name in names}
        return {'strategy_id':tape['strategy_id'],'daily_returns':returns,'metrics':metrics,'details':details}
    def put(name,v): metrics[name]=metric(S(D(v)))
    put('total_return',values[-1]/values[0]-1);put('final_NAV_USD',values[-1])
    elapsed=rows[-1]['nominal_ns']-rows[0]['nominal_ns']
    if elapsed<=0: metrics['CAGR']=metric(None,'INVALID','NONPOSITIVE_ELAPSED_TIME')
    else: metrics['CAGR']=metric(S(D(values[-1]/values[0]).__pow__(D(Fraction(31557600*10**9,elapsed)))-Decimal(1)))
    fees=sum((fraction(f['fee']) for f in tape['fills']),Fraction())
    notional=sum((fraction(f['price'])*f['quantity'] for f in tape['fills']),Fraction())
    put('fees_USD',fees);put('gross_executed_notional',notional);put('turnover_over_initial',notional/values[0])
    peak=values[0];peak_i=0;maxdd=Fraction();trough=0;selected_peak=0
    maxconc=Fraction();conc_i=0;conc_s=SYMBOLS[0];missing_mark=False
    for i,(row,v) in enumerate(zip(rows,values)):
        if v>peak: peak=v;peak_i=i
        dd=1-v/peak
        if dd>maxdd: maxdd=dd;trough=i;selected_peak=peak_i
        for s in SYMBOLS:
            qty=row['positions'][s]
            if qty and row['marks'].get(s) is None: missing_mark=True;continue
            c=Fraction() if qty==0 else qty*fraction(row['marks'][s])/v
            if c>maxconc: maxconc=c;conc_i=i;conc_s=s
    put('maximum_drawdown',maxdd)
    recovery=next((r['nominal_ns'] for i,r in enumerate(rows) if i>trough and values[i]>=values[selected_peak]),None) if maxdd else None
    details['drawdown']={'peak_ns':rows[selected_peak]['nominal_ns'],'trough_ns':rows[trough]['nominal_ns'],
                         'recovery_ns':recovery,'recovery_status':('RECOVERED' if recovery is not None else 'NOT_RECOVERED_BY_END') if maxdd else 'NOT_APPLICABLE',
                         'exact_fraction':rational(maxdd)}
    if missing_mark: metrics['maximum_close_name_concentration']=metric(None,'INSUFFICIENT_EVIDENCE','MISSING_POSITION_MARK')
    else:
        put('maximum_close_name_concentration',maxconc)
        details['concentration']={'nominal_ns':rows[conc_i]['nominal_ns'],'symbol':conc_s,'exact_fraction':rational(maxconc)}
    n=len(returns)
    if n:
        rs=[values[i]/values[i-1]-1 for i in range(1,len(values))]
        mean=sum(rs,Fraction())/n;put('mean_return',mean)
        worst=min(range(n),key=lambda i:(rs[i],returns[i]['end_nominal_ns'],returns[i]['start_nominal_ns']))
        details['worst_period']=returns[worst]
        tail=sorted(range(n),key=lambda i:(-(-rs[i]),returns[i]['end_nominal_ns'],returns[i]['start_nominal_ns']))[:(n+19)//20]
        put('ES95',sum((-rs[i] for i in tail),Fraction())/len(tail));details['ES95_intervals']=[returns[i] for i in tail]
        if n<2:
            for name in ('sample_variance','annualized_volatility','Sharpe_252'):
                metrics[name]=metric(None,'INSUFFICIENT_EVIDENCE','FEWER_THAN_TWO_RETURNS')
        else:
            variance=sum(((r-mean)**2 for r in rs),Fraction())/(n-1);put('sample_variance',variance)
            metrics['annualized_volatility']=metric(S((Decimal(252)*D(variance)).sqrt()))
            if variance==0: metrics['Sharpe_252']=metric(None,'INSUFFICIENT_EVIDENCE','ZERO_EXCESS_VARIANCE')
            else: metrics['Sharpe_252']=metric(S((Decimal(252).sqrt()*D(mean))/D(variance).sqrt()))
    return {'strategy_id':tape['strategy_id'],'daily_returns':returns,'metrics':metrics,'details':details}

def evaluate(simulation):
    results=[evaluate_strategy(t) for t in simulation['strategies']]
    byid={r['strategy_id']:r for r in results}
    b,m=(byid[s] for s in STRATEGIES);deltas={}
    fields=('CAGR','ES95','Sharpe_252','annualized_volatility','fees_USD','final_NAV_USD',
            'maximum_close_name_concentration','maximum_drawdown','total_return','turnover_over_initial')
    priority={'INVALID':0,'NOT_RUN':1,'INSUFFICIENT_EVIDENCE':2,'NOT_APPLICABLE':3}
    with localcontext(context()):
        for name in fields:
            a,z=b['metrics'][name],m['metrics'][name]
            if a['status']==z['status']=='OK': deltas['delta_'+name]=metric(S(Decimal(z['value'])-Decimal(a['value'])))
            else:
                bad=min((v for v in (a,z) if v['status']!='OK'),key=lambda v:priority[v['status']])
                deltas['delta_'+name]=metric(None,bad['status'],'DEPENDENCY_'+bad['reason'])
        paired=[]
        for a,z in zip(b['daily_returns'],m['daily_returns']):
            if a['start_nominal_ns']!=z['start_nominal_ns'] or a['end_nominal_ns']!=z['end_nominal_ns']: raise GymError('UNPAIRED_GRID')
            if a['status']==z['status']=='OK':
                def f(row):
                    v=row['exact_fraction'];return Fraction(int(v['numerator']),int(v['denominator']))
                r=f(z)-f(a)
                paired.append(dict(start_nominal_ns=a['start_nominal_ns'],end_nominal_ns=a['end_nominal_ns'],exact_fraction=rational(r),decimal50=S(D(r)),status='OK',reason=None))
            else: paired.append(dict(start_nominal_ns=a['start_nominal_ns'],end_nominal_ns=a['end_nominal_ns'],exact_fraction=None,decimal50=None,status='INSUFFICIENT_EVIDENCE',reason='DEPENDENCY_RETURN'))
    return {'schema':'polar.gym-evaluation/1','strategies':results,
            'benchmark_relative':{'order':'MONTHLY_MINUS_BUYHOLD','metrics':deltas,'paired_return_differences':paired},
            'financial_verdict':'INSUFFICIENT_EVIDENCE_ENGINEERING_DEMONSTRATION'}

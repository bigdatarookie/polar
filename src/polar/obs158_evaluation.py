"""OBS158 exact model-account evaluation; no native analytics or source reads."""
from decimal import Decimal,localcontext
from fractions import Fraction
import re

from .gym_contract import context,decimal_fraction as D,decimal_string as S
from .obs158_math import require,Obs158Error,microprice,cent_round_micro,fraction_record

STRATEGIES=('OBS158_EW_BH_V1','OBS158_EW_MONTHLY_V1')
SCOPE='PRICE_ONLY_PARTIAL_ACTION_EXECUTION_MODEL'
POINTS=('initial_price_ledger_value_USD','final_price_ledger_value_USD','price_ledger_change_fraction',
        'price_ledger_cagr_act365_25','price_ledger_sharpe_model_f0_252',
        'price_ledger_annualized_volatility_252','price_ledger_maximum_drawdown','price_ledger_ES95')
CONCENTRATIONS=('maximum_close_balance_sheet_name_weight',
                'maximum_close_exact_mark_exposure_over_rounded_value')
FILL_FIELDS=('gross_exact_executed_notional_USD','gross_exact_turnover_over_initial',
             'gross_settled_executed_notional_USD','gross_settled_turnover_over_initial',
             'model_fees_USD','signed_settlement_rounding_cash_adjustment_USD')
PRIORITY={'INVALID':0,'NOT_RUN':1,'INSUFFICIENT_EVIDENCE':2,'NOT_APPLICABLE':3}


def integer(value,*,signed=False):
    require(type(value) is str and len(value)<=40 and re.fullmatch(
            r'-?(?:0|[1-9][0-9]*)' if signed else r'(?:0|[1-9][0-9]*)',value),'INVALID_INTEGER_FIELD')
    return int(value)


def metric(value=None,status='OK',reason=None):
    require(status in ('OK',*PRIORITY) and (reason is None if status=='OK' else reason is not None),
            'INVALID_METRIC_STATUS')
    return {'value':S(D(Fraction(value))) if status=='OK' else None,'status':status,'reason':reason,
            'evidence_scope':SCOPE}


def dependency(*records):
    bad=[v for v in records if v['status']!='OK']
    return min(bad,key=lambda v:PRIORITY[v['status']]) if bad else None


def _fill_metrics(tape,initial):
    rows=tape.get('fills');bad={};totals={'exact':Fraction(),'settled':Fraction(),
                                        'fees':Fraction(),'rounding':Fraction()}
    if type(rows) is not list:
        return {n:metric(None,'INSUFFICIENT_EVIDENCE','MISSING_FILL_LEDGER') for n in FILL_FIELDS}
    def flag(key,status,reason):
        new=metric(None,status,reason)
        if key not in bad or PRIORITY[status]<PRIORITY[bad[key]['status']]:bad[key]=new
    for row in rows:
        if type(row) is not dict:
            for k in totals:flag(k,'INVALID','INVALID_FILL_RECORD')
            continue
        # Fee inputs are independent of missing notional/valuation inputs.
        try:
            if row.get('fee_cents') is None:flag('fees','INSUFFICIENT_EVIDENCE','MISSING_FILL_FEE')
            else:
                fee=integer(row['fee_cents']);require(fee==100,'INVALID_FILL_FEE')
                totals['fees']+=Fraction(fee,100)
        except (Obs158Error,ValueError):flag('fees','INVALID','INVALID_FILL_FEE')
        exact=None;settled=None
        try:
            if row.get('filled_quantity') is None or row.get('raw_open') is None:
                flag('exact','INSUFFICIENT_EVIDENCE','MISSING_FILL_NOTIONAL')
            else:
                qty=integer(row['filled_quantity']);require(0<qty<=1000000,'INVALID_FILL_QUANTITY')
                exact=Fraction(qty*microprice(row['raw_open']),1000000);totals['exact']+=exact
        except (Obs158Error,ValueError):flag('exact','INVALID','INVALID_FILL_NOTIONAL')
        try:
            if row.get('settled_notional_cents') is None:
                flag('settled','INSUFFICIENT_EVIDENCE','MISSING_SETTLED_NOTIONAL')
            else:
                cents=integer(row['settled_notional_cents']);settled=Fraction(cents,100)
                if exact is not None:
                    require(cents==cent_round_micro(int(exact*1000000)),'SETTLEMENT_MODEL_MISMATCH')
                totals['settled']+=settled
        except (Obs158Error,ValueError):
            settled=None;flag('settled','INVALID','INVALID_SETTLED_NOTIONAL')
        if exact is None:
            failure=bad['exact'];flag('settled',failure['status'],'DEPENDENCY_'+failure['reason'])
        if exact is None or settled is None:
            failure=dependency(*(bad[k] for k in ('exact','settled') if k in bad))
            flag('rounding',failure['status'],'DEPENDENCY_'+failure['reason'])
        else:
            try:
                require(row.get('side') in ('BUY','SELL'),'INVALID_SIDE')
                residual=settled-exact
                totals['rounding']+=-residual if row['side']=='BUY' else residual
            except Obs158Error:flag('rounding','INVALID','INVALID_ROUNDING_SIDE')
    def result(key):return bad[key] if key in bad else metric(totals[key])
    exact=result('exact');settled=result('settled')
    def turnover(key,record):
        failure=dependency(record,initial)
        return metric(None,failure['status'],'DEPENDENCY_'+failure['reason']) if failure else metric(
            totals[key]/Fraction(initial['value']))
    return dict(zip(FILL_FIELDS,(exact,turnover('exact',exact),settled,turnover('settled',settled),
                                 result('fees'),result('rounding'))))


def _endpoint(row,aliases):
    if row is None or row.get('price_ledger_value_cents') is None:
        return None,metric(None,'INSUFFICIENT_EVIDENCE','MISSING_ACCOUNT_ENDPOINT'),None
    try:
        value=integer(row['price_ledger_value_cents'],signed=True)
        require(value>0,'INVALID_ACCOUNT_VALUE')
    except (Obs158Error,ValueError):return None,metric(None,'INVALID','INVALID_ACCOUNT_VALUE'),None
    try:
        if row.get('cash_cents') is None:
            return None,metric(None,'INSUFFICIENT_EVIDENCE','MISSING_ACCOUNT_CASH'),None
        cash=integer(row['cash_cents']);positions=row['positions'];marks=row.get('marks')
        if marks is None:marks={}
        require(type(marks) is dict,'INVALID_MARK_RECORD')
        require(type(positions) is dict and set(positions)==set(aliases),'POSITION_ALIAS_MISMATCH')
        components=[];rounded_total=cash
        for alias in aliases:
            qty=integer(positions[alias])
            if qty:
                if marks.get(alias) is None:
                    return None,metric(None,'INSUFFICIENT_EVIDENCE','MISSING_POSITION_MARK'),None
                exact_micro=qty*microprice(marks[alias])
            else:exact_micro=0
            rounded=cent_round_micro(exact_micro);rounded_total+=rounded
            components.append((alias,Fraction(rounded,value),Fraction(exact_micro,10000*value)))
        require(rounded_total==value,'ACCOUNT_VALUE_RECONCILIATION')
        return Fraction(value,100),metric(Fraction(value,100)),components
    except (Obs158Error,KeyError,TypeError,ValueError):
        return None,metric(None,'INVALID','INVALID_ACCOUNT_COMPONENTS'),None


def _account(tape,grid,aliases):
    supplied=tape.get('samples',[])
    require(type(supplied) is list,'INVALID_SAMPLE_LEDGER')
    bytime={}
    for row in supplied:
        require(type(row) is dict and type(row.get('nominal_ns')) is int
                and row['nominal_ns'] not in bytime,'DUPLICATE_OR_INVALID_SAMPLE')
        bytime[row['nominal_ns']]=row
    require(set(bytime)<={g['nominal_ns'] for g in grid},'OUTSIDE_SAMPLE_GRID')
    endpoints=[_endpoint(bytime.get(g['nominal_ns']),aliases) for g in grid]
    values=[e[0] for e in endpoints];records=[e[1] for e in endpoints]
    metrics={n:metric(None,'INSUFFICIENT_EVIDENCE','MISSING_ACCOUNT_ENDPOINT') for n in (*POINTS,*CONCENTRATIONS)}
    metrics[POINTS[0]]=records[0];metrics[POINTS[1]]=records[-1]
    if values[0] is not None and values[0]!=100000:
        records[0]=metrics[POINTS[0]]=metric(None,'INVALID','INVALID_INITIAL_ACCOUNT_VALUE');values[0]=None
    ledger_metrics=_fill_metrics(tape,metrics[POINTS[0]])
    intervals=[];exact_returns=[]
    for i in range(1,len(grid)):
        failure=dependency(records[i-1],records[i]);change=None if failure else values[i]/values[i-1]-1
        intervals.append({'start_nominal_ns':grid[i-1]['nominal_ns'],'end_nominal_ns':grid[i]['nominal_ns'],
                          'exact_fraction':fraction_record(change) if change is not None else None,
                          'decimal50':S(D(change)) if change is not None else None,
                          'status':failure['status'] if failure else 'OK',
                          'reason':failure['reason'] if failure else None})
        exact_returns.append(change)
    failure=dependency(*records);details={'drawdown':None,'concentration':None,'exact_exposure':None,
                                         'worst_interval':None,'ES95_intervals':[]}
    if failure:
        for n in (*POINTS[2:],*CONCENTRATIONS):metrics[n]=dict(failure)
    else:
        metrics[POINTS[2]]=metric(values[-1]/values[0]-1)
        elapsed=grid[-1]['nominal_ns']-grid[0]['nominal_ns']
        metrics[POINTS[3]]=metric(D(values[-1]/values[0]).__pow__(D(Fraction(31557600*10**9,elapsed)))-Decimal(1))
        n=len(exact_returns);mean=sum(exact_returns,Fraction())/n
        variance=sum(((r-mean)**2 for r in exact_returns),Fraction())/(n-1)
        metrics[POINTS[4]]=(metric(None,'INSUFFICIENT_EVIDENCE','ZERO_EXCESS_VARIANCE') if variance==0
                           else metric(Decimal(252).sqrt()*D(mean)/D(variance).sqrt()))
        metrics[POINTS[5]]=metric((Decimal(252)*D(variance)).sqrt())
        peak=values[0];peak_i=0;maximum=Fraction();peak_selected=trough=0
        primary=(Fraction(),0,aliases[0]);diagnostic=(Fraction(),0,aliases[0])
        for i,(value,endpoint) in enumerate(zip(values,endpoints)):
            if value>peak:peak=value;peak_i=i
            loss=1-value/peak
            if loss>maximum:maximum=loss;peak_selected=peak_i;trough=i
            for alias,rounded,exposure in endpoint[2]:
                require(0<=rounded<=1,'INVALID_BALANCE_SHEET_WEIGHT')
                if rounded>primary[0]:primary=(rounded,i,alias)
                if exposure>diagnostic[0]:diagnostic=(exposure,i,alias)
        metrics[POINTS[6]]=metric(maximum)
        recovery=next((grid[i]['nominal_ns'] for i in range(trough+1,len(grid))
                       if values[i]>=values[peak_selected]),None) if maximum else None
        details['drawdown']={'peak_ns':grid[peak_selected]['nominal_ns'],'trough_ns':grid[trough]['nominal_ns'],
                             'recovery_ns':recovery,'recovery_status':('RECOVERED' if recovery is not None else
                             'NOT_RECOVERED_BY_END') if maximum else 'NOT_APPLICABLE',
                             'exact_fraction':fraction_record(maximum)}
        for name,best,key in ((CONCENTRATIONS[0],primary,'concentration'),
                              (CONCENTRATIONS[1],diagnostic,'exact_exposure')):
            metrics[name]=metric(best[0]);details[key]={'nominal_ns':grid[best[1]]['nominal_ns'],
                                                      'alias':best[2],'exact_fraction':fraction_record(best[0])}
        ordering=sorted(range(n),key=lambda i:(exact_returns[i],intervals[i]['end_nominal_ns'],
                                              intervals[i]['start_nominal_ns']))
        tail=ordering[:(n+19)//20]
        metrics[POINTS[7]]=metric(sum((-exact_returns[i] for i in tail),Fraction())/len(tail))
        details['worst_interval']=intervals[ordering[0]]
        details['ES95_intervals']=[intervals[i] for i in tail]
    metrics.update(ledger_metrics)
    return {'strategy_id':tape['strategy_id'],'price_ledger_interval_changes':intervals,
            'metrics':metrics,'details':details}


def evaluate_obs158(simulation,converted,aliases):
    """Only the two fixed account tapes and all253nominal endpoints are admitted."""
    grid=converted['sample_grid']
    require(len(aliases)==158 and list(aliases)==sorted(set(aliases)) and len(grid)==253
            and len({g['nominal_ns'] for g in grid})==253
            and all(a['nominal_ns']<b['nominal_ns'] for a,b in zip(grid,grid[1:])),
            'INVALID_FIXED_EVALUATION_GRID')
    tapes=simulation['strategies']
    require(type(tapes) is list and [t['strategy_id'] for t in tapes]==list(STRATEGIES),
            'INVALID_STRATEGY_PAIR')
    with localcontext(context()):
        results=[_account(t,grid,aliases) for t in tapes];base,monthly=results
        deltas={}
        for name in (*POINTS,*CONCENTRATIONS,*FILL_FIELDS):
            a,b=base['metrics'][name],monthly['metrics'][name];failure=dependency(a,b)
            deltas['delta_'+name]=(metric(None,failure['status'],'DEPENDENCY_'+failure['reason']) if failure
                                   else metric(Decimal(b['value'])-Decimal(a['value'])))
        paired=[]
        for a,b in zip(base['price_ledger_interval_changes'],monthly['price_ledger_interval_changes']):
            bad=[v for v in (a,b) if v['status']!='OK'];change=None
            if bad:failure=min(bad,key=lambda v:PRIORITY[v['status']])
            else:
                failure=None
                def f(v):return Fraction(int(v['exact_fraction']['numerator']),int(v['exact_fraction']['denominator']))
                change=f(b)-f(a)
            paired.append({'start_nominal_ns':a['start_nominal_ns'],'end_nominal_ns':a['end_nominal_ns'],
                           'exact_fraction':fraction_record(change) if change is not None else None,
                           'decimal50':S(D(change)) if change is not None else None,
                           'status':failure['status'] if failure else 'OK',
                           'reason':'DEPENDENCY_'+failure['reason'] if failure else None})
        return {'schema':'polar.obs158-evaluation/1','metric_order':list((*POINTS,*CONCENTRATIONS,*FILL_FIELDS)),
                'strategies':results,
                'paired':{'order':'OBS158_EW_MONTHLY_V1_MINUS_OBS158_EW_BH_V1',
                          'metrics':deltas,'price_ledger_interval_change_differences':paired},
                'financial_status':'INSUFFICIENT_EVIDENCE','evidence_scope':SCOPE,
                'financial_reasons':['DIVIDENDS_EXCLUDED_PRICE_ONLY','INCOMPLETE_ACTION_COVERAGE',
                                     'MODELED_EXECUTION_NOT_CAPACITY_PROOF','CONDITIONAL_SOURCE_ALIASES_CURRENCY_CLOCKS']}

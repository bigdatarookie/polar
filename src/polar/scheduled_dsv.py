"""Closed downside allocation adapter and independent saved arithmetic checks."""
from decimal import Decimal, ROUND_HALF_EVEN, localcontext
from fractions import Fraction
import hashlib
import math
from pathlib import Path

from . import qb_downside_semideviation_prototype as author
from . import scheduled_erc as erc
from .ci_research import require
from .scheduled_signals import AllocationError, sample_covariance

SCHEMA='polar.scheduled-reference-profile/18'
KIND='COMMON_RISK_DOWNSIDE_SEMIDEVIATION'
IDS=('DSV','EW','INV')
SYMBOLS=('BIL','SHY','TLT','VTI')
PROTOTYPE_SHA256='2910ba001833da2766fac5b286db1bfe141f85847a0b6b4b4d48a6332e15fb90'
DEPENDENCY_SHA256=erc.PROTOTYPE_SHA256
QUESTION_SHA256='884f017dd96a783ade9db82540022c927150ce91eaf7f355f47a1b1de4077376'
POLICY=dict(kind=KIND,lookback=60,annual_cap='0.10',shrinkage=[1,2],
            downside_threshold=[0,1],downside_denominator=60,scalar_precision=80,
            scalar_rounding='ROUND_HALF_EVEN',weight_units=10**12,
            prototype_sha256=PROTOTYPE_SHA256,dependency_sha256=DEPENDENCY_SHA256,question_sha256=QUESTION_SHA256)
SPECS=erc.SPECS
PROTOTYPE_KEYS=('completed_covariance_admissions','downside_return_operands',
                'completed_downside_moments','scalar_root_reciprocal_calls',
                'risk_scale_evaluations','completed_target_legs')
COUNT_KEYS=('estimator_calls','completed_estimates','return_ratio_attempts','completed_return_ratios',
            'prototype_calls','completed_prototypes',*PROTOTYPE_KEYS)


def policy_binding():
    path=Path(__file__).with_name('qb_downside_semideviation_prototype.py')
    require(not path.is_symlink() and Path(author.__file__).resolve()==path.resolve() and
            hashlib.sha256(path.read_bytes()).hexdigest()==PROTOTYPE_SHA256,'DSV_PROTOTYPE_BINDING')
    erc.policy_binding()


def validate_profile(p):
    policy_binding()
    require(p['schema']==SCHEMA and p['protocol_id']==author.PROTOCOL_ID and
            p['symbols']==list(SYMBOLS) and p['policy']==POLICY and p['decision_delay_seconds']==1,
            'DSV_CLOSED_POLICY')
    require([l['id'] for l in p['legs']]==list(IDS) and all(l['rule']==l['id'] and l['scale']==[1,1] for l in p['legs'])
            and p['primary_strategy']=='DSV' and p['primary_benchmark']=='EW','DSV_ROLES')
    require(p['cost_scenarios']==[{'id':'BASE','cost_profile':{'flat_cents':100,'bps':10}},
            {'id':'COST_STRESS','cost_profile':{'flat_cents':200,'bps':20}}] and
            p['uncertainty']==dict(kind='BASE_ONLY_PAIRED_SAVED_RETURN_CONDITIONAL_DESCRIPTIVE',
                                  block=63,replicates=1000,seed=37006),'DSV_SCENARIOS')
    require(len(p['criteria'])==9 and all(
        {k:v for k,v in c.items() if k not in ('id','description')}==dict(left_id='DSV',**spec)
        for c,spec in zip(p['criteria'],SPECS)),'DSV_CRITERIA')
    return p


def counts(signals):
    # Missing/partially reported work is unknown, never inferred to be zero.
    return {k:(sum(s['actual_counts'][k] for s in signals)
               if all(type(s.get('actual_counts',{}).get(k)) is int for s in signals) else None)
            for k in COUNT_KEYS}


def expected_work(n):
    return {'estimator_calls':n,'prototype_calls':n,'return_ratio_attempts':240*n,
            'completed_downside_moments':4*n,'completed_target_legs':3*n,
            'scalar_root_reciprocal_calls_range':[4*n,8*n],
            'grid_evaluations_method_upper_bound':3*(10**12).bit_length()*n,
            'scope':'METHOD_DERIVED_EXPECTATION_NOT_A_NEW_RESOURCE_OR_INVOCATION_QUOTA'}


def targets(prices,symbols):
    policy_binding();actual=counts([]);converted=[];returns=[]
    try:
        require(symbols==list(SYMBOLS),'DSV_SYMBOLS')
        actual['estimator_calls']+=1
        converted,_,covariance=sample_covariance(prices,symbols,window=60)
        actual['completed_estimates']+=1
        require(len(converted)==61 and all(len(row)==4 for row in converted),'DSV_CONVERTED_SHAPE')
        for t in range(1,61):
            row=[]
            for i in range(4):
                actual['return_ratio_attempts']+=1
                value=converted[t][i]/converted[t-1][i]-1
                require(type(value) is float and math.isfinite(value),'DSV_RETURN_DOMAIN')
                actual['completed_return_ratios']+=1;row.append(value)
            returns.append(row)
        actual['prototype_calls']+=1
        # The frozen prototype reports its own real call-site counters.
        for k in PROTOTYPE_KEYS:actual[k]=None
        rule=author.downside_targets(covariance,returns)
        actual['completed_prototypes']+=1
        actual.update(rule['actual_counts'])
        return {'weights':{leg:{s:Fraction(*v) for s,v in row.items()} for leg,row in rule['weights'].items()},
                'diagnostics':dict(kind=KIND,prototype_sha256=PROTOTYPE_SHA256,dependency_sha256=DEPENDENCY_SHA256,
                    converted_prices_binary64=[[repr(v) for v in row] for row in converted],
                    return_rows_binary64=[[repr(v) for v in row] for row in returns],
                    sample_covariance_binary64=[[repr(v) for v in row] for row in covariance],
                    rule=rule,actual_counts=actual)}
    except (ValueError,OverflowError,ZeroDivisionError) as error:
        events=getattr(error,'events',{})
        if isinstance(events,dict) and isinstance(events.get('actual_counts'),dict):
            actual.update(events['actual_counts'])
            # Interrupted pure helpers can report completed work, not their
            # unobserved partial search evaluations. Do not call that total0.
            if actual.get('completed_downside_moments')==4 and (type(actual.get('completed_target_legs')) is not int or actual['completed_target_legs']<3):
                actual['risk_scale_evaluations']=None
        raise AllocationError('DSV_INVALID',dict(status='INVALID',reason=str(error)[:120],
            actual_counts=actual,prototype_events=events,
            count_scope='OBSERVED_CALLS_AND_REPORTED_COMPLETIONS_UNOBSERVED_PARTIAL_WORK_UNKNOWN')) from None


def _binary(rows,n):
    require(type(rows) is list and len(rows)==n and all(type(r) is list and len(r)==4 for r in rows),'DSV_BINARY64_SHAPE')
    result=[]
    for row in rows:
        values=[]
        for token in row:
            require(type(token) is str,'DSV_BINARY64_LITERAL')
            value=float(token)
            require(math.isfinite(value) and repr(value)==token,'DSV_BINARY64_LITERAL')
            values.append(value)
        result.append(values)
    return result


def _inverse_root(values):
    with localcontext() as ctx:
        ctx.prec=80;ctx.rounding=ROUND_HALF_EVEN
        scores=[Fraction(1/(Decimal(v.numerator)/Decimal(v.denominator)).sqrt()) for v in values]
    return [v/sum(scores) for v in scores]


def verify_signal(signal,prices=None):
    """Certify stored arithmetic; no estimator, author, grid search or IO."""
    require(signal['kind']==KIND and signal['prototype_sha256']==PROTOTYPE_SHA256 and
            signal['dependency_sha256']==DEPENDENCY_SHA256,'DSV_SAVED_BINDING')
    rule=signal['rule'];c=rule['certificate']
    require(set(rule)=={'schema','protocol_id','status','raw_weights','weights','certificate','actual_counts'} and
            rule['schema']=='polar.downside-semideviation-prototype/1' and rule['protocol_id']==author.PROTOCOL_ID and
            rule['status']=='EXACT_LOWER_PARTIAL_MOMENT_AND_COMMON_GRID_CERTIFIED','DSV_SAVED_HEADER')
    require(set(c)=={'sample_covariance','shrunk_covariance','shrunk_ldl_pivots','return_operands',
        'lower_partial_second_moments','downside_denominator','zero_downside_indices','downside_branch',
        'scalar_convention','annual_common_target_variance','scales'},'DSV_SAVED_CERTIFICATE_FIELDS')
    converted=_binary(signal['converted_prices_binary64'],61)
    require(all(x>0 for row in converted for x in row),'DSV_SAVED_PRICE_DOMAIN')
    if prices is not None:
        expected=[[repr(float(f'{row[s]//1000000}.{row[s]%1000000:06d}')) for s in SYMBOLS] for row in prices]
        require(signal['converted_prices_binary64']==expected,'DSV_SAVED_PRICE_LITERAL_BINDING')
    returns=_binary(signal['return_rows_binary64'],60)
    require(all(returns[t][i]==converted[t+1][i]/converted[t][i]-1 for t in range(60) for i in range(4)),
            'DSV_SAVED_RETURN_RATIO')
    require(type(c['return_operands']) is list and len(c['return_operands'])==60 and
            all(type(row) is list and len(row)==4 for row in c['return_operands']),'DSV_SAVED_RETURN_SHAPE')
    exact=[[erc.rational(v) for v in row] for row in c['return_operands']]
    require(exact==[[Fraction.from_float(x) for x in row] for row in returns],'DSV_SAVED_RETURN_OPERANDS')
    sample=erc._matrix(c['sample_covariance']);binary=_binary(signal['sample_covariance_binary64'],4)
    require(sample==[[Fraction.from_float(x) for x in row] for row in binary],'DSV_SAVED_COVARIANCE_BINARY')
    # Arithmetic checks on saved literals, not a call to the estimator.
    means=[math.fsum(row[i] for row in returns)/60 for i in range(4)]
    require(binary==[[math.fsum((row[i]-means[i])*(row[j]-means[j]) for row in returns)/59
                      for j in range(4)] for i in range(4)],'DSV_SAVED_COVARIANCE_RETURN_BINDING')
    require(all(sample[i][i]>0 for i in range(4)),'DSV_SAVED_POSITIVE_DIAGONAL')
    erc._pivots(sample,False)
    cov=erc._matrix(c['shrunk_covariance'])
    require(cov==[[sample[i][j] if i==j else sample[i][j]/2 for j in range(4)] for i in range(4)] and
            [erc.rational(p) for p in c['shrunk_ldl_pivots']]==erc._pivots(cov,True),'DSV_SAVED_SHRINKAGE_SPD')
    moments=[sum((min(row[i],0)**2 for row in exact),Fraction())/60 for i in range(4)]
    require(type(c['downside_denominator']) is int and c['downside_denominator']==60 and
            [erc.rational(v) for v in c['lower_partial_second_moments']]==moments,'DSV_SAVED_MOMENTS')
    zeros=[i for i,v in enumerate(moments) if v==0]
    require(type(c['zero_downside_indices']) is list and all(type(i) is int for i in c['zero_downside_indices']) and
            c['zero_downside_indices']==zeros and c['downside_branch']==(
                'EQUAL_WEIGHT_EXACT_ZERO_DOWNSIDE_ASSETS' if zeros else 'INVERSE_LOWER_PARTIAL_ROOT_DECIMAL80') and
            c['scalar_convention']==dict(precision=80,rounding='ROUND_HALF_EVEN',
                score_conversion='EXACT_FINITE_DECIMAL_FRACTION'),'DSV_SAVED_SCALAR_CONVENTION')
    expected={'DSV':[Fraction(int(i in zeros),len(zeros)) for i in range(4)] if zeros else _inverse_root(moments),
              'EW':[Fraction(1,4)]*4,'INV':_inverse_root([cov[i][i] for i in range(4)])}
    require(set(rule['raw_weights'])==set(rule['weights'])==set(c['scales'])==set(IDS),'DSV_SAVED_LEGS')
    raw={}
    for leg in IDS:
        require(set(rule['raw_weights'][leg])==set(SYMBOLS),'DSV_SAVED_SYMBOLS')
        raw[leg]=[erc.rational(rule['raw_weights'][leg][s]) for s in SYMBOLS]
        require(raw[leg]==expected[leg] and all(v>=0 for v in raw[leg]) and sum(raw[leg])==1,'DSV_SAVED_RAW')
    annual={leg:252*erc._quadratic(w,cov) for leg,w in raw.items()}
    require(all(v>0 for v in annual.values()),'DSV_SAVED_RAW_RISK')
    target=min(Fraction(1,100),*annual.values())
    require(erc.rational(c['annual_common_target_variance'])==target,'DSV_SAVED_COMMON_TARGET')
    targets={}
    for leg in IDS:
        scale=c['scales'][leg];k=scale['index'];n=10**12
        require(set(scale)=={'index','units','cash','annual_raw_variance','annual_selected_variance',
                            'annual_next_grid_variance'} and type(k) is int and 0<=k<=n and scale['units']==n,
                'DSV_SAVED_GRID')
        selected=annual[leg]*Fraction(k,n)**2
        require(erc.rational(scale['annual_raw_variance'])==annual[leg] and
                erc.rational(scale['annual_selected_variance'])==selected<=target and
                (scale['annual_next_grid_variance'] is None if k==n else
                 erc.rational(scale['annual_next_grid_variance'])==annual[leg]*Fraction(k+1,n)**2>target) and
                erc.rational(scale['cash'])==1-Fraction(k,n),'DSV_SAVED_MAXIMUM')
        targets[leg]={s:Fraction(k,n)*v for s,v in zip(SYMBOLS,raw[leg])}
        require(set(rule['weights'][leg])==set(SYMBOLS) and
                {s:erc.rational(v) for s,v in rule['weights'][leg].items()}==targets[leg],'DSV_SAVED_TARGETS')
    work=rule['actual_counts']
    require(set(work)==set(PROTOTYPE_KEYS) and all(type(v) is int and v>=0 for v in work.values()) and
            work['completed_covariance_admissions']==1 and work['downside_return_operands']==240 and
            work['completed_downside_moments']==4 and work['scalar_root_reciprocal_calls']==(4 if zeros else 8) and
            work['completed_target_legs']==3 and 0<work['risk_scale_evaluations']<=120 and
            signal['actual_counts']==dict(estimator_calls=1,completed_estimates=1,return_ratio_attempts=240,
                completed_return_ratios=240,prototype_calls=1,completed_prototypes=1,**work),
            'DSV_SAVED_ACTUAL_COUNTS')
    return targets


def bind_plan(plan,profile):
    return erc.bind_plan(plan,profile)


def verify_plan(plan,profile,calendar,tz=None):
    from .scheduled_priced_reserve import verify_plan as monthly
    from .scheduled_parking import UNIT,WITNESS
    import io
    from zoneinfo import ZoneInfo
    from .gym_contract import sha
    validate_profile(profile)
    require(plan.get('capture_consumed_sizing') is True and plan.get('consumed_witness_schema')==WITNESS and
            plan.get('quantity_unit')==UNIT,'DSV_SAVED_CONSUMED_REQUIRED')
    require(plan.get('price_evidence')=={d:dict(source_input_sha256=profile['input_sha256'],source_date=d,
        quote_basis='SYNTHETIC_VENDOR_ADJUSTED_REFERENCE_UNIT',price_scale=[1,1]) for d in plan['prices']},
        'DSV_SAVED_SOURCE')
    clocks={row['date']:row['nominal_ns'] for row in plan['grid']}
    require(all(d.get('formation_close_ns')==clocks[d['formation']] for d in plan['decisions']),'DSV_SAVED_FORMATION_CLOCK')
    base={k:v for k,v in plan.items() if k not in (
        'capture_consumed_sizing','consumed_witness_schema','quantity_unit','price_evidence')}
    base['decisions']=[{k:v for k,v in d.items() if k!='formation_close_ns'} for d in plan['decisions']]
    days=sorted(plan['prices'])
    def verify(signal):
        index=days.index(signal['formation'])
        require(index>=60,'DSV_SAVED_ELIGIBLE_PREFIX')
        prices=[{s:plan['prices'][d][s]['close_micro'] for s in SYMBOLS} for d in days[index-60:index+1]]
        return verify_signal(signal,prices)
    if tz is None:
        raw=bytes.fromhex(calendar['timezone_tzif_hex'])
        require(sha(raw)==profile['timezone_sha256'],'DSV_SAVED_TIMEZONE')
        tz=ZoneInfo.from_file(io.BytesIO(raw),key='America/New_York')
    return monthly(base,profile,calendar,tz,signal_verifier=verify,ids=IDS,kind=KIND)

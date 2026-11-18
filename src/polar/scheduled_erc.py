"""Closed ERC adapter and exact saved witnesses; no solver calls in verification."""
from decimal import Decimal, ROUND_HALF_EVEN, localcontext
from fractions import Fraction
import hashlib
import math
from pathlib import Path

from . import qb_equal_risk_contribution_prototype as author
from .ci_research import require
from .scheduled_signals import AllocationError, sample_covariance

SCHEMA = 'polar.scheduled-reference-profile/16'
KIND = 'COMMON_RISK_EQUAL_CONTRIBUTION'
IDS = ('ERC', 'EW', 'INV')
SYMBOLS = ('BIL', 'SHY', 'TLT', 'VTI')
PROTOTYPE_SHA256 = 'd42421a4a920f925e3bfb783d09322058d7213d6aee2129650887d41b3ed23db'
POLICY = dict(kind=KIND, lookback=60, annual_cap='0.10', shrinkage=[1,2],
              solver='DECIMAL80_CYCLIC_EXACT_BUDGET', relative_budget_tolerance=[1,10**8],
              weight_units=10**12, prototype_sha256=PROTOTYPE_SHA256)
SPECS = [dict(kind=kind,right_id=other,**fields) for other in ('EW','INV') for kind,fields in (
    ('TERMINAL_GT',{}), ('SR_DELTA_GE',{'threshold':'0.10'}), ('DRAWDOWN_LE',{}),
    ('VOL_RATIO_BETWEEN',{'lower':'0.8','upper':'1.25'}))] + [dict(kind='POSITIVE_GROWTH')]
WORK_KEYS = ('coordinate_sweeps','coordinate_update_attempts','coordinate_updates',
             'exact_budget_checks','risk_scale_evaluations')


def policy_binding():
    path=Path(__file__).with_name('qb_equal_risk_contribution_prototype.py')
    require(not path.is_symlink() and Path(author.__file__).resolve()==path.resolve() and
            hashlib.sha256(path.read_bytes()).hexdigest()==PROTOTYPE_SHA256,'ERC_PROTOTYPE_BINDING')


def validate_profile(p):
    policy_binding()
    require(p['schema']==SCHEMA and p['protocol_id']==author.PROTOCOL_ID and p['symbols']==list(SYMBOLS)
            and p['policy']==POLICY and p['decision_delay_seconds']==1,'ERC_CLOSED_POLICY')
    require([l['id'] for l in p['legs']]==list(IDS) and all(l['rule']==l['id'] and l['scale']==[1,1] for l in p['legs'])
            and p['primary_strategy']=='ERC' and p['primary_benchmark']=='EW','ERC_ROLES')
    require(p['cost_scenarios']==[{'id':'BASE','cost_profile':{'flat_cents':100,'bps':10}},
            {'id':'COST_STRESS','cost_profile':{'flat_cents':200,'bps':20}}] and p['uncertainty']==dict(
            kind='BASE_ONLY_PAIRED_SAVED_RETURN_CONDITIONAL_DESCRIPTIVE',block=63,replicates=1000,seed=37005),
            'ERC_SCENARIOS')
    require(len(p['criteria'])==9 and all({k:v for k,v in c.items() if k not in ('id','description')}==dict(
            left_id='ERC',**spec) for c,spec in zip(p['criteria'],SPECS)),'ERC_CRITERIA')
    return p


def counts(signals):
    return {k:sum(s.get('actual_counts',{}).get(k,0) for s in signals)
            for k in ('estimator_calls','completed_estimates','prototype_calls','completed_prototypes',*WORK_KEYS)}


def targets(prices,symbols):
    policy_binding(); actual=counts([])
    try:
        require(symbols==list(SYMBOLS),'ERC_SYMBOLS')
        actual['estimator_calls']=1
        _,_,covariance=sample_covariance(prices,symbols,window=60)
        actual['completed_estimates']=1
        actual['prototype_calls']=1
        result=author.equal_risk_targets(covariance)
        actual['completed_prototypes']=1
        actual.update(result['actual_counts'])
        return {'weights':{leg:{s:Fraction(*v) for s,v in row.items()} for leg,row in result['weights'].items()},
                'diagnostics':dict(kind=KIND,prototype_sha256=PROTOTYPE_SHA256,
                    sample_covariance_binary64=[[repr(v) for v in row] for row in covariance],
                    rule=result,actual_counts=actual)}
    except (ValueError,OverflowError) as error:
        events=getattr(error,'events',{})
        if isinstance(events,dict):actual.update(events.get('actual_counts',{}))
        raise AllocationError('ERC_INVALID',dict(status='INVALID',reason=str(error)[:120],actual_counts=actual,
                              prototype_events=events)) from None


def rational(pair):
    require(type(pair) is list and len(pair)==2 and all(type(x) is int for x in pair) and pair[1]>0,'ERC_RATIONAL')
    value=Fraction(*pair)
    require(pair==[value.numerator,value.denominator],'ERC_RATIONAL_CANONICAL')
    return value


def _matrix(rows):
    require(type(rows) is list and len(rows)==4 and all(type(row) is list and len(row)==4 for row in rows),'ERC_MATRIX')
    return [[rational(x) for x in row] for row in rows]


def _pivots(matrix,strict):
    """Arithmetic elimination of stored operands, not weight selection."""
    require(all(matrix[i][j]==matrix[j][i] for i in range(4) for j in range(4)),'ERC_SYMMETRY')
    work=[row[:] for row in matrix];pivots=[]
    for k in range(4):
        pivot=work[k][k];pivots.append(pivot)
        require(pivot>0 if strict else pivot>=0,'ERC_GEOMETRY')
        if pivot==0:
            require(all(work[k][j]==0 for j in range(k+1,4)),'ERC_GEOMETRY')
        else:
            for i in range(k+1,4):
                for j in range(k+1,4):work[i][j]-=work[i][k]*work[k][j]/pivot
    return pivots


def _quadratic(w,c):
    return sum((w[i]*c[i][j]*w[j] for i in range(4) for j in range(4)),Fraction())


def verify_signal(signal):
    """Check immutable witnesses without estimation, coordinates or grid search."""
    require(signal['kind']==KIND and signal['prototype_sha256']==PROTOTYPE_SHA256,'ERC_SAVED_BINDING')
    r=signal['rule'];cert=r['certificate']
    require(r['schema']=='polar.equal-risk-contribution-prototype/1' and r['protocol_id']==author.PROTOCOL_ID and
            r['status']=='EXACT_RISK_BUDGET_AND_COMMON_GRID_CERTIFIED','ERC_SAVED_HEADER')
    sample=_matrix(cert['sample_covariance']);binary=signal['sample_covariance_binary64']
    require(type(binary) is list and len(binary)==4 and all(type(row) is list and len(row)==4 for row in binary), 'ERC_BINARY64')
    for i in range(4):
        for j in range(4):
            token=binary[i][j];value=float(token)
            require(type(token) is str and math.isfinite(value) and repr(value)==token and
                    Fraction.from_float(value)==sample[i][j],'ERC_BINARY64')
    require(all(sample[i][i]>0 for i in range(4)),'ERC_POSITIVE_DIAGONAL')
    _pivots(sample,False)
    c=_matrix(cert['shrunk_covariance'])
    require(c==[[sample[i][j] if i==j else sample[i][j]/2 for j in range(4)] for i in range(4)],'ERC_SHRINKAGE')
    require(type(cert['shrunk_ldl_pivots']) is list and
            [rational(p) for p in cert['shrunk_ldl_pivots']]==_pivots(c,True),'ERC_LDL')
    require(set(r['raw_weights'])==set(IDS) and set(r['weights'])==set(IDS) and
            set(cert['scales'])==set(IDS),'ERC_WEIGHT_LEGS')
    raw={}
    for leg,row in r['raw_weights'].items():
        require(set(row)==set(SYMBOLS),'ERC_WEIGHT_SYMBOLS')
        raw[leg]=[rational(row[s]) for s in SYMBOLS]
        require(all(w>0 for w in raw[leg]) and sum(raw[leg])==1,'ERC_RAW_WEIGHT_DOMAIN')
    require(raw['EW']==[Fraction(1,4)]*4,'ERC_EW_CONSTRUCTION')
    # INV construction uses the frozen scalar square-root convention only.
    # This does not iterate coordinates, estimate covariance or select weights.
    with localcontext() as ctx:
        ctx.prec=80;ctx.rounding=ROUND_HALF_EVEN
        inverse=[Fraction(1/(Decimal(c[i][i].numerator)/Decimal(c[i][i].denominator)).sqrt()) for i in range(4)]
    require(raw['INV']==[x/sum(inverse) for x in inverse],'ERC_INV_CONSTRUCTION')
    w=raw['ERC'];variance=_quadratic(w,c)
    contributions=[w[i]*sum((c[i][j]*w[j] for j in range(4)),Fraction()) for i in range(4)]
    require(variance>0,'ERC_BUDGET_VARIANCE')
    errors=[abs(4*x/variance-1) for x in contributions]
    require(rational(cert['erc_variance'])==variance and
            [rational(x) for x in cert['erc_contributions']]==contributions and
            [rational(x) for x in cert['erc_relative_budget_errors']]==errors and
            rational(cert['relative_budget_tolerance'])==Fraction(1,10**8) and max(errors)<=Fraction(1,10**8),
            'ERC_EXACT_BUDGET')
    annual={leg:252*_quadratic(row,c) for leg,row in raw.items()}
    tau=min(Fraction(1,100),*annual.values())
    require(rational(cert['annual_common_target_variance'])==tau>0,'ERC_COMMON_TARGET')
    targets={}
    for leg in IDS:
        scale=cert['scales'][leg];k=scale['index'];n=10**12
        require(type(k) is int and 0<=k<=n and scale['units']==n,'ERC_SCALE_GRID')
        selected=annual[leg]*Fraction(k,n)**2
        require(rational(scale['annual_raw_variance'])==annual[leg] and
                rational(scale['annual_selected_variance'])==selected<=tau and
                (scale['annual_next_grid_variance'] is None if k==n else
                 rational(scale['annual_next_grid_variance'])==annual[leg]*Fraction(k+1,n)**2>tau) and
                rational(scale['cash'])==1-Fraction(k,n),'ERC_SCALE_MAXIMUM')
        expected={s:Fraction(k,n)*x for s,x in zip(SYMBOLS,raw[leg])}
        require(set(r['weights'][leg])==set(SYMBOLS) and all(
                rational(r['weights'][leg][s])==v for s,v in expected.items()),'ERC_TARGET_WEIGHTS')
        targets[leg]=expected
    work=r['actual_counts']
    require(set(work)==set(WORK_KEYS) and all(type(v) is int and v>=0 for v in work.values()) and
            work['coordinate_sweeps']>=1 and work['coordinate_update_attempts']==work['coordinate_updates']==4*work['coordinate_sweeps'] and
            work['exact_budget_checks']==work['coordinate_sweeps'] and work['risk_scale_evaluations']>0 and
            signal['actual_counts']==dict(estimator_calls=1,completed_estimates=1,prototype_calls=1,completed_prototypes=1,**work),
            'ERC_PRIVATE_WORK_COUNTS')
    return targets


def bind_plan(plan,profile):
    from .scheduled_parking import bind_plan as capture_existing_operands
    return capture_existing_operands(plan,profile)


def verify_plan(plan,profile,calendar,tz=None):
    import io
    from zoneinfo import ZoneInfo
    from .gym_contract import sha
    from .scheduled_priced_reserve import verify_plan as monthly_certificates
    from .scheduled_parking import UNIT,WITNESS
    require(plan.get('capture_consumed_sizing') is True and plan.get('consumed_witness_schema')==WITNESS and
            plan.get('quantity_unit')==UNIT,'ERC_CONSUMED_WITNESS_REQUIRED')
    expected={d:dict(source_input_sha256=profile['input_sha256'],source_date=d,
                    quote_basis='SYNTHETIC_VENDOR_ADJUSTED_REFERENCE_UNIT',price_scale=[1,1]) for d in plan['prices']}
    require(plan.get('price_evidence')==expected,'ERC_SOURCE_IDENTITY')
    closes={row['date']:row['nominal_ns'] for row in plan['grid']}
    require(all(d.get('formation_close_ns')==closes[d['formation']] for d in plan['decisions']), 'ERC_FORMATION_CLOCK')
    base={k:v for k,v in plan.items() if k not in ('capture_consumed_sizing','consumed_witness_schema','quantity_unit','price_evidence')}
    base['decisions']=[{k:v for k,v in d.items() if k!='formation_close_ns'} for d in plan['decisions']]
    if tz is None:
        raw=bytes.fromhex(calendar['timezone_tzif_hex'])
        require(sha(raw)==profile['timezone_sha256'],'ERC_TIMEZONE_BINDING')
        tz=ZoneInfo.from_file(io.BytesIO(raw),key='America/New_York')
    return monthly_certificates(base,profile,calendar,tz,signal_verifier=verify_signal,ids=IDS,kind=KIND)

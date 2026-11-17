"""Closed adapter and arithmetic-only saved certificates for the frozen author rule."""
from datetime import date, datetime, time, timedelta
from fractions import Fraction
import math
import hashlib
from pathlib import Path

from . import qb_priced_reserve_prototype as author
from .ci_research import require
from .gym_contract import canonical
from .scheduled_signals import AllocationError, sample_covariance

KIND = 'RISK_MATCHED_PRICED_RESERVE'
SCHEMA = 'polar.scheduled-reference-profile/15'
IDS = ('SWEPT', 'CASH_TARGET', 'BIL_ONLY')
PROTOTYPE_SHA256 = '172525eaa40a2b61048ef0ce0d77680773084854f567992a30cb544c6d1278bb'
SPECS = [dict(kind='TERMINAL_GT', right_id='CASH_TARGET'),
         dict(kind='TERMINAL_GT', right_id='BIL_ONLY'),
         dict(kind='SR_DELTA_GE', right_id='CASH_TARGET', threshold='0.10'),
         dict(kind='DRAWDOWN_LE', right_id='CASH_TARGET'),
         dict(kind='VOL_RATIO_BETWEEN', right_id='CASH_TARGET', lower='0.8', upper='1.25'),
         dict(kind='POSITIVE_GROWTH')]


def policy_binding():
    path=Path(__file__).with_name('qb_priced_reserve_prototype.py')
    require(not path.is_symlink() and Path(author.__file__).resolve()==path.resolve() and
            hashlib.sha256(path.read_bytes()).hexdigest()==PROTOTYPE_SHA256, 'PRICED_RESERVE_PROTOTYPE_BINDING')


def validate_profile(p):
    policy_binding()
    require(p['symbols'] == ['BIL', 'VTI'] and p['protocol_id'] == author.PROTOCOL_ID and
            p['policy'] == dict(kind=KIND, lookback=60, annual_cap='0.10', weight_units=1_000_000,
                               prototype_sha256=PROTOTYPE_SHA256) and
            p['decision_delay_seconds'] == 1, 'PRICED_RESERVE_POLICY')
    require([l['id'] for l in p['legs']] == list(IDS) and
            all(l['rule'] == l['id'] and l['scale'] == [1, 1] for l in p['legs']) and
            p['primary_strategy'] == 'SWEPT' and p['primary_benchmark'] == 'CASH_TARGET',
            'PRICED_RESERVE_ROLES')
    require(p['cost_scenarios'] == [{'id':'BASE','cost_profile':{'flat_cents':100,'bps':10}},
            {'id':'COST_STRESS','cost_profile':{'flat_cents':200,'bps':20}}] and
            p['uncertainty'] == dict(kind='PAIRED_CIRCULAR_SAVED_RETURNS', block=63, replicates=1000, seed=37004),
            'PRICED_RESERVE_SCENARIOS')
    require(len(p['criteria']) == len(SPECS) and all(
        {k:v for k,v in c.items() if k not in ('id','description')} == dict(left_id='SWEPT', **spec)
        for c,spec in zip(p['criteria'], SPECS)), 'PRICED_RESERVE_CRITERIA')
    return p


def counts(signals):
    keys = ('estimator_calls','completed_estimates','rule_calls','completed_rules','risk_evaluations')
    return {k:sum(s.get('actual_counts', {}).get(k,0) for s in signals) for k in keys}


def targets(prices, symbols):
    policy_binding()
    actual = counts([])
    actual['estimator_calls'] = 1
    try:
        require(symbols == ['BIL','VTI'], 'PRICED_RESERVE_SYMBOLS')
        _, _, covariance = sample_covariance(prices, symbols, window=60)
        actual['completed_estimates'] = 1
        annual = [[252*x for x in row] for row in covariance]
        actual['rule_calls'] = 1
        selected = author.reserve_targets(annual)
        actual['completed_rules'] = 1
        actual['risk_evaluations'] = selected['certificate']['priced_reserve_risk_evaluations']
        diagnostic = dict(kind=KIND, prototype_sha256=PROTOTYPE_SHA256,
                          annual_covariance_binary64=[[repr(x) for x in row] for row in annual],
                          rule=selected, actual_counts=actual)
        return {'weights': {leg:{s:Fraction(*w) for s,w in row.items()}
                            for leg,row in selected['weights'].items()}, 'diagnostics':diagnostic}
    except (ValueError, OverflowError) as exc:
        raise AllocationError('PRICED_RESERVE_INVALID', {'actual_counts':actual,
                              'status':'INVALID', 'reason':str(exc)[:120]}) from None


def _fraction(pair):
    require(type(pair) is list and len(pair)==2 and all(type(x) is int for x in pair)
            and pair[1]>0, 'PRICED_RESERVE_CERTIFICATE_PAIR')
    value=Fraction(*pair)
    require(pair==[value.numerator,value.denominator], 'PRICED_RESERVE_CERTIFICATE_CANONICAL')
    return value


def verify_signal(signal):
    """Check supplied witnesses by arithmetic, without estimating or searching weights."""
    require(signal['kind']==KIND and signal['prototype_sha256']==PROTOTYPE_SHA256,
            'PRICED_RESERVE_BINDING')
    r=signal['rule']; c=r['certificate']; n=author.WEIGHT_UNITS
    require(r['schema']=='polar.priced-reserve-rule-prototype/1' and r['protocol_id']==author.PROTOCOL_ID
            and c['weight_units']==n and _fraction(c['annual_cap'])==author.ANNUAL_CAP,
            'PRICED_RESERVE_CERTIFICATE_HEADER')
    require(type(c['covariance']) is list and len(c['covariance'])==2 and
            all(type(row) is list and len(row)==2 for row in c['covariance']), 'PRICED_RESERVE_COVARIANCE')
    q=[[_fraction(x) for x in row] for row in c['covariance']]
    binary=signal['annual_covariance_binary64']
    require(type(binary) is list and len(binary)==2 and all(type(row) is list and len(row)==2 for row in binary),
            'PRICED_RESERVE_BINARY64')
    for i in range(2):
        for j in range(2):
            value=float(binary[i][j])
            require(type(binary[i][j]) is str and math.isfinite(value) and repr(value)==binary[i][j]
                    and Fraction.from_float(value)==q[i][j], 'PRICED_RESERVE_BINARY64')
    b,cov,v=q[0][0],q[0][1],q[1][1]
    require(cov==q[1][0] and b>=0 and v>=0 and b*v>=cov*cov, 'PRICED_RESERVE_PSD')
    k,j=c['cash_grid_index'],c['swept_equity_grid_index']
    require(type(k) is int and type(j) is int and 0<=k<=n and 0<=j<=n,'PRICED_RESERVE_GRID')
    target=_fraction(c['target_variance']); selected=_fraction(c['selected_variance'])
    def f(index):
        x=Fraction(index,n)
        return v*x*x+b*(1-x)**2+2*cov*x*(1-x)
    if v==0:
        require(k==j==0 and target==selected==0 and
                r['status']=='ZERO_EQUITY_FORECAST_FALLBACK_CASH' and
                c['grid_minimum_index'] is c['grid_minimum_variance'] is c['next_grid_variance'] is None,
                'PRICED_RESERVE_ZERO')
    else:
        require(target==v*Fraction(k,n)**2 and target<=author.ANNUAL_CAP**2 and
                (k==n or v*Fraction(k+1,n)**2>author.ANNUAL_CAP**2), 'PRICED_RESERVE_CASH_MAXIMUM')
        curvature=b+v-2*cov
        vertex=(b-cov)*n/curvature if curvature else Fraction()
        floor=min(n,max(0,vertex.numerator//vertex.denominator))
        adjacent=min(n,floor+1)
        # Only the two analytic vertex witnesses; no enumeration or risk search.
        minimum=adjacent if f(adjacent)<=f(floor) else floor
        require(c['grid_minimum_index']==minimum and _fraction(c['grid_minimum_variance'])==f(minimum),
                'PRICED_RESERVE_MINIMUM')
        if f(minimum)>target:
            require(r['status']=='RISK_INFEASIBLE_GRID_FALLBACK_CASH_TARGET' and j==k and selected==target
                    and c['next_grid_variance'] is None, 'PRICED_RESERVE_FALLBACK')
        else:
            require(r['status']=='PRICED_RESERVE_GRID_FEASIBLE' and j>=minimum and selected==f(j)
                    and selected<=target and (c['next_grid_variance'] is None if j==n else
                    _fraction(c['next_grid_variance'])==f(j+1)>target), 'PRICED_RESERVE_MAXIMUM')
    feasible=r['status']=='PRICED_RESERVE_GRID_FEASIBLE'
    weights={'SWEPT':{'BIL':1-Fraction(j,n) if feasible else Fraction(), 'VTI':Fraction(j,n)},
             'CASH_TARGET':{'BIL':Fraction(), 'VTI':Fraction(k,n)},
             'BIL_ONLY':{'BIL':Fraction(1), 'VTI':Fraction()}}
    require(set(r['weights'])==set(IDS) and set(r['unremunerated_cash'])==set(IDS), 'PRICED_RESERVE_WEIGHT_LEGS')
    for leg,row in weights.items():
        require(set(r['weights'][leg])==set(row) and
                all(_fraction(r['weights'][leg][s])==w for s,w in row.items()) and
                _fraction(r['unremunerated_cash'][leg])==1-sum(row.values()), 'PRICED_RESERVE_WEIGHTS')
    a=signal['actual_counts']; evaluations=c['priced_reserve_risk_evaluations']
    require(type(evaluations) is int and (evaluations==0 if v==0 else evaluations>0) and
            a==dict(estimator_calls=1,completed_estimates=1,rule_calls=1,completed_rules=1,risk_evaluations=evaluations),
            'PRICED_RESERVE_PRIVATE_COUNTS')
    return weights


def verify_plan(plan, profile, calendar, tz):
    from .scheduled_policy import calendar_value
    from .reference_ridge_plan import nanoseconds
    schedule=calendar['source_schedule_rows']; days=[r['date'] for r in schedule]
    grid=calendar_value(calendar,schedule)['FINAL']
    rows={r['date']:r for r in schedule}
    close=lambda d:nanoseconds(datetime.fromisoformat(rows[d]['reference_close_utc']))
    require(plan['symbols']==profile['symbols'] and list(sorted(plan['prices']))==days and all(
        set(row)==set(profile['symbols']) and all(type(x) is dict and set(x)=={'close_micro'} and
        type(x['close_micro']) is int and x['close_micro']>0 for x in row.values()) for row in plan['prices'].values()),
        'PRICED_RESERVE_SAVED_PRICES')
    require(plan['grid']==[dict(date=d,nominal_ns=close(d),sample_ns=close(d)+1000,initial=i==0,
                terminal=d==grid['terminal']) for i,d in enumerate(grid['nav_dates'])], 'PRICED_RESERVE_SAVED_GRID')
    require(len(plan['signals'])==len(grid['decisions']) and len(plan['decisions'])==len(plan['signals'])+1,
            'PRICED_RESERVE_SAVED_EVENTS')
    events=[(x['signal_date'],x['execution_date']) for x in grid['decisions']]
    events.append((days[days.index(grid['terminal'])-1],grid['terminal']))
    for index,((formation,execution),decision) in enumerate(zip(events,plan['decisions'])):
        known=datetime.combine(date.fromisoformat(formation)+timedelta(days=1),time(),tzinfo=tz)
        instant=known+timedelta(seconds=1)
        require(nanoseconds(known)<nanoseconds(instant)<close(execution), 'PRICED_RESERVE_SAVED_CLOCK')
        if index==len(events)-1:
            instructions={leg:dict(kind='EXIT') for leg in IDS}
        else:
            signal=plan['signals'][index]; weights=verify_signal(signal)
            require(signal['formation']==formation and signal['execution']==execution, 'PRICED_RESERVE_SAVED_JOIN')
            instructions={leg:dict(kind='TARGET',weights={s:[w.numerator,w.denominator] for s,w in row.items()},
                signal={'kind':KIND,'certificate_signal_index':index}) for leg,row in weights.items()}
        require(decision==dict(day=execution,formation=formation,known_ns=nanoseconds(known),
                decision_ns=nanoseconds(instant),open_ns=close(execution),kind='REFERENCE',instructions=instructions),
                'PRICED_RESERVE_SAVED_INSTRUCTION')
    require(plan['profile']==dict(kind='REFERENCE_TARGETS',legs=list(IDS),end=grid['terminal']) and
            plan['quote_basis']=='SYNTHETIC_VENDOR_ADJUSTED_REFERENCE_UNIT' and
            plan['clock_policy']=='PINNED_REFERENCE_EARLY_CLOSE','PRICED_RESERVE_SAVED_PROFILE')

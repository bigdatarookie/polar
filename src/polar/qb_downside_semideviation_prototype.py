"""Frozen lower-partial-moment strategy arithmetic on supplied eligible operands.

Pure author strategy: no source, native engine, model, account, store or IO calls.
Covariance admission and maximal risk grid reuse accepted ERC pure primitives;
no ERC coordinate solver is called. Binary64 returns are literal operands.
"""
from decimal import Decimal, DecimalException, ROUND_HALF_EVEN, localcontext
from fractions import Fraction
import math

from .qb_equal_risk_contribution_prototype import (
    RiskBudgetError, matrix, _ldl, _scale, pair, quadratic,
)

PROTOCOL_ID = 'QB-DOWNSIDE-SEMIDEVIATION-20261118-V1'
SYMBOLS = ('BIL', 'SHY', 'TLT', 'VTI')
IDS = ('DSV', 'EW', 'INV')
WINDOW = 60
UNITS = 10**12


def require(ok, reason):
    if not ok:
        raise RiskBudgetError(reason)


def _inverse_root(values, actual):
    scores=[]
    with localcontext() as ctx:
        ctx.prec=80
        ctx.rounding=ROUND_HALF_EVEN
        for value in values:
            require(value>0, 'DSV_INVERSE_ROOT_DOMAIN')
            actual['scalar_root_reciprocal_calls']+=1
            score=1/(Decimal(value.numerator)/Decimal(value.denominator)).sqrt()
            require(score.is_finite() and score>0, 'DSV_INVERSE_ROOT_INVALID')
            scores.append(Fraction(score))
    total=sum(scores,Fraction())
    return [v/total for v in scores]


def downside_targets(sample_covariance, return_rows):
    actual={'completed_covariance_admissions':0,'downside_return_operands':0,
            'completed_downside_moments':0,'scalar_root_reciprocal_calls':0,
            'risk_scale_evaluations':0,'completed_target_legs':0}
    try:
        return _construct(sample_covariance, return_rows, actual)
    except (RiskBudgetError, DecimalException, OverflowError) as error:
        failure=RiskBudgetError(str(error) if isinstance(error,RiskBudgetError)
                                else 'DSV_DECIMAL_ARITHMETIC_INVALID')
        failure.events={'status':'INVALID','actual_counts':dict(actual)}
        raise failure from None


def _construct(sample_covariance, return_rows, actual):
    original=matrix(sample_covariance)
    covariance=[[original[i][j] if i==j else original[i][j]/2
                 for j in range(4)] for i in range(4)]
    pivots=_ldl(covariance,strict=True)
    actual['completed_covariance_admissions']+=1
    require(type(return_rows) is list and len(return_rows)==WINDOW and
            all(type(row) is list and len(row)==4 for row in return_rows), 'DSV_RETURN_SHAPE')
    exact=[]
    moments=[Fraction() for _ in SYMBOLS]
    for row in return_rows:
        values=[]
        for i,value in enumerate(row):
            require(type(value) is float and math.isfinite(value), 'DSV_BINARY64_RETURN_DOMAIN')
            actual['downside_return_operands']+=1
            fraction=Fraction.from_float(value)
            values.append(fraction)
            moments[i]+=min(fraction,0)**2
        exact.append(values)
    moments=[v/WINDOW for v in moments]
    actual['completed_downside_moments']+=len(moments)
    zeros=[i for i,v in enumerate(moments) if v==0]
    if zeros:
        dsv=[Fraction(int(i in zeros),len(zeros)) for i in range(4)]
        branch='EQUAL_WEIGHT_EXACT_ZERO_DOWNSIDE_ASSETS'
    else:
        dsv=_inverse_root(moments,actual)
        branch='INVERSE_LOWER_PARTIAL_ROOT_DECIMAL80'
    inverse=_inverse_root([covariance[i][i] for i in range(4)],actual)
    raw={'DSV':dsv,'EW':[Fraction(1,4)]*4,'INV':inverse}
    require(all(all(w>=0 for w in v) and sum(v)==1 for v in raw.values()), 'DSV_RAW_WEIGHT_DOMAIN')
    annual={leg:252*quadratic(w,covariance) for leg,w in raw.items()}
    require(all(v>0 for v in annual.values()), 'DSV_NONPOSITIVE_RAW_RISK')
    target=min(Fraction(1,100),*annual.values())
    weights={};scales={}
    for leg in IDS:
        k,selected,next_variance,count=_scale(annual[leg],target)
        actual['risk_scale_evaluations']+=count
        scale=Fraction(k,UNITS)
        weights[leg]={s:pair(scale*w) for s,w in zip(SYMBOLS,raw[leg])}
        scales[leg]={'index':k,'units':UNITS,'cash':pair(1-scale),
                     'annual_raw_variance':pair(annual[leg]),
                     'annual_selected_variance':pair(selected),
                     'annual_next_grid_variance':pair(next_variance) if next_variance is not None else None}
        actual['completed_target_legs']+=1
    return {'schema':'polar.downside-semideviation-prototype/1','protocol_id':PROTOCOL_ID,
            'status':'EXACT_LOWER_PARTIAL_MOMENT_AND_COMMON_GRID_CERTIFIED',
            'raw_weights':{leg:{s:pair(w) for s,w in zip(SYMBOLS,row)} for leg,row in raw.items()},
            'weights':weights,'certificate':{
                'sample_covariance':[[pair(v) for v in row] for row in original],
                'shrunk_covariance':[[pair(v) for v in row] for row in covariance],
                'shrunk_ldl_pivots':[pair(v) for v in pivots],
                'return_operands':[[pair(v) for v in row] for row in exact],
                'lower_partial_second_moments':[pair(v) for v in moments],
                'downside_denominator':WINDOW,'zero_downside_indices':zeros,'downside_branch':branch,
                'scalar_convention':{'precision':80,'rounding':'ROUND_HALF_EVEN','score_conversion':'EXACT_FINITE_DECIMAL_FRACTION'},
                'annual_common_target_variance':pair(target),'scales':scales},
            'actual_counts':dict(actual)}

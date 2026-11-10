"""Frozen reference-model point screens over the accepted exact scalar evaluator."""
from decimal import Decimal, localcontext
from .ci_research import INITIAL_CENTS, require
from .ci_research_evaluation import evaluate_legs, metric
from .gym_contract import context, decimal_string


def evaluate_reference(simulation, *, kind, strategy, benchmark, simple=None, phase='FINAL'):
    require(kind in ('RIDGE', 'PPO') and phase in ('FINAL', 'VALIDATION', 'DEVELOPMENT'), 'REFERENCE_EVALUATION_KIND')
    legs, exact = evaluate_legs(simulation); by_id = {v['id']:v for v in legs}
    require(strategy in by_id and benchmark in by_id and strategy != benchmark and
            (kind != 'RIDGE' or simple in by_id and simple not in (strategy,benchmark)), 'REFERENCE_EVALUATION_LEGS')
    comparisons = []
    for other in ([simple,benchmark] if kind == 'RIDGE' else [benchmark]):
        for name in ('terminal_nav_usd','net_cagr_act36525','sharpe_252_rf0','max_drawdown','total_cost_usd'):
            av=by_id[strategy]['metrics'][name]['value'];bv=by_id[other]['metrics'][name]['value']
            with localcontext(context()):
                diff=decimal_string(Decimal(av)-Decimal(bv)) if av is not None and bv is not None else None
            comparisons.append({'metric_id':name,'left_id':strategy,'right_id':other,
                                'result':metric(diff,None if diff is not None else 'PAIRED_METRIC_UNAVAILABLE')})
    delta=lambda other:next(c['result']['value'] for c in comparisons if c['metric_id']=='sharpe_252_rf0' and c['right_id']==other)
    conditions=[]
    if phase == 'FINAL':
        if kind == 'RIDGE':
            for other,label in [(simple,'RIDGE_SHARPE_GT_MOM'),(benchmark,'RIDGE_SHARPE_GT_EW')]:
                d=delta(other);conditions.append((label, Decimal(d)>0 if d is not None else None))
            conditions.append(('POSITIVE_CAGR',exact[strategy]['terminal']>INITIAL_CENTS))
        else:
            d=delta(benchmark);conditions.extend([('SHARPE_DELTA_GE_0P10',Decimal(d)>=Decimal('0.10') if d is not None else None),
                         ('TERMINAL_NAV_GT_EW',exact[strategy]['terminal']>exact[benchmark]['terminal'])])
        conditions.append(('DRAWDOWN_NOT_WORSE_THAN_EW',exact[strategy]['max_drawdown']<=exact[benchmark]['max_drawdown']))
    criteria=[{'id':name,'description':name,'status':'UNAVAILABLE' if v is None else 'MET' if v else 'NOT_MET',
               'reason':'REQUIRED_METRIC_UNAVAILABLE' if v is None else None} for name,v in conditions]
    outcome=('DIAGNOSTIC_PHASE_NO_POINT_SCREEN' if phase!='FINAL' else 'INDETERMINATE' if any(v is None for _,v in conditions)
             else 'SUPPORTIVE_ON_THIS_LIMITED_SCREEN' if all(v for _,v in conditions) else 'NOT_SUPPORTIVE_ON_THIS_LIMITED_SCREEN')
    return {'schema':'polar.reference-evaluation/1','phase':phase,'legs':legs,'comparisons':comparisons,
            'criteria':criteria,'point_interpretation':outcome,'financial_acceptance':'NOT_REVIEWED',
            'exposure_denominator':len(simulation['legs'][0]['nav'])-1}

"""Exact descriptive common-P evaluation; no scientific interpretation or fallback."""
from fractions import Fraction as F
import struct
from .hyp008_s1_numeric import dyadic,wire
from .empirical_tenth import lower_empirical_tenth

METHODS=('TREE','LINEAR','HISTORICAL')


class EvaluationUnavailable(ValueError):pass


def require(ok,reason):
    if not ok:raise EvaluationUnavailable(reason)


def historical(window_ids,window_bits):
    require(type(window_ids) is tuple and len(window_ids)==52
            and len(set(window_ids))==52 and type(window_bits) is tuple and len(window_bits)==52,
            'FIXED_HISTORY_WINDOW_REQUIRED')
    for b in window_bits:dyadic(b)
    result=lower_empirical_tenth(tuple(struct.unpack('>d',bytes.fromhex(b))[0] for b in window_bits),
                                 expected_count=52,max_rows=52)
    require(result.status=='STATISTIC_DEFINED' and result.selected_rank==6,'HISTORICAL_UNAVAILABLE')
    return {'bits':struct.pack('>d',result.q).hex(),'rank':6,'window_ids':list(window_ids)}


def evaluate_common(masks,forecasts,targets):
    require(type(masks) is dict and masks.get('schema')=='polar.hyp008-s1-masks/1','FIXED_MASKS_REQUIRED')
    I=masks['I'];P=masks['P']
    require(type(I) is list and type(P) is list and len(set(I))==len(I)
            and len(set(P))==len(P) and set(P)<=set(I),'MASK_DOMAIN')
    require(type(forecasts) is dict and set(forecasts)==set(METHODS)
            and all(type(forecasts[k]) is dict for k in METHODS),'METHOD_SET')
    complete=all(set(forecasts[k])==set(I) for k in METHODS)
    if not complete:return {'schema':'polar.hyp008-s1-evaluation/1','status':'PLANNED_FAMILY_UNAVAILABLE',
        'reason':'REQUIRED_FORECAST_MISSING','I':I,'P':P,'rows':[],'aggregate':None}
    require(type(targets) is dict and set(targets)==set(P),'COMMON_P_TARGETS')
    rows=[];totals={k:F(0) for k in METHODS};breaches={k:0 for k in METHODS};ties={k:0 for k in METHODS}
    for identity in I:
        for k in METHODS:dyadic(forecasts[k][identity])
    for identity in P:
        y=dyadic(targets[identity]);losses={};flags={}
        for k in METHODS:
            q=dyadic(forecasts[k][identity]);r=y-q;loss=r/10 if r>=0 else -9*r/10
            losses[k]=wire(loss);totals[k]+=loss
            breaches[k]+=int(y<q);ties[k]+=int(y==q)
            flags[k]={'strict_breach':y<q,'tie':y==q}
        rows.append({'opportunity_id':identity,'target_bits':targets[identity],
            'forecast_bits':{k:forecasts[k][identity] for k in METHODS},'losses':losses,'flags':flags})
    aggregate=None if not P else {'count':len(P),'mean_losses':{k:wire(v/len(P)) for k,v in totals.items()},
            'mean_linear_minus_tree':wire((totals['LINEAR']-totals['TREE'])/len(P)),
            'strict_breaches':breaches,'ties':ties}
    return {'schema':'polar.hyp008-s1-evaluation/1','status':'OK' if P else 'INSUFFICIENT_EVIDENCE',
            'reason':None if P else 'EMPTY_COMMON_P','I':I,'P':P,'rows':rows,'aggregate':aggregate,
            'financial':'NOT_ASSESSED'}

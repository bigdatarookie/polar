"""Chronological supervised adapter over the existing fixed ridge kernel.

No source reads, fit or finance occurs on import. Protocol callers supply frozen
cycles, fit event and timezone. No scoring rows enter preprocessing or fitting.
"""
from datetime import datetime, timedelta, time
from decimal import Decimal, localcontext
from fractions import Fraction
import math

from .ci_research import require
from .gym_contract import context
from .research_reference import trailing_return

FEATURES = ('RET21', 'RET63', 'MOM252_21', 'VOL21')


def eligible_at(day, tz):
    return datetime.combine(datetime.fromisoformat(day).date()+timedelta(days=1), time(), tzinfo=tz)


def feature_row(market, symbol, index):
    require(type(index) is int and 252 <= index < len(market['dates']), 'RIDGE_FEATURE_WARMUP')
    ret21 = float(trailing_return(market, symbol, index, 21))
    ret63 = float(trailing_return(market, symbol, index, 63))
    momentum = float(trailing_return(market, symbol, index-21, 231))
    values = [float(trailing_return(market, symbol, j, 1)) for j in range(index-20, index+1)]
    mean = math.fsum(values)/21
    vol = math.sqrt(math.fsum((v-mean)**2 for v in values)/20)
    row = [ret21, ret63, momentum, vol]
    require(all(math.isfinite(x) for x in row), 'RIDGE_FEATURE_NONFINITE')
    return row


def training_rows(market, cycles, fit_event, tz):
    require(type(cycles) is list and cycles and isinstance(fit_event, datetime) and
            fit_event.utcoffset() is not None, 'RIDGE_TRAINING_CONTRACT')
    days, symbols = market['dates'], market['symbols']
    indices = {day:i for i,day in enumerate(days)}
    require([c['signal'] for c in cycles] == sorted({c['signal'] for c in cycles}), 'RIDGE_CYCLE_ORDER')
    rows = []
    for cycle in cycles:
        signal, entry, exit = (cycle[k] for k in ('signal', 'entry', 'label_exit'))
        require(signal in indices and entry in indices and exit in indices and
                signal < entry < exit and indices[entry] == indices[signal]+1 and
                cycle['signal_index'] == indices[signal], 'RIDGE_CYCLE_GRID')
        # Refuse future labels before reading features/targets or invoking any learner.
        require(eligible_at(exit, tz) <= fit_event and eligible_at(signal, tz) <= fit_event,
                'RIDGE_LABEL_NOT_MATURE')
        for symbol in symbols:
            features = feature_row(market, symbol, indices[signal])
            y = float(Fraction(market['prices_micro'][exit][symbol], market['prices_micro'][entry][symbol])-1)
            require(math.isfinite(y), 'RIDGE_LABEL_NONFINITE')
            rows.append({'signal': signal, 'entry': entry, 'label_exit': exit, 'symbol': symbol,
                         'features': features, 'label': y})
    return rows


def fit_ridge(market, cycles, fit_event, tz):
    """Exactly one unchanged mean-loss lambda1 kernel fit; persist its full provenance."""
    rows = training_rows(market, cycles, fit_event, tz)
    from .hyp007_numeric import numpy, array, moments, standardize, ridge_fit
    np = numpy(); require(np.__version__ == '2.2.6', 'RIDGE_NUMPY_VERSION')
    x = array([r['features'] for r in rows], columns=4)
    transform = moments(x)
    standardized = standardize(x, transform)
    model = ridge_fit(standardized, [r['label'] for r in rows])
    require(model['lambda'] == 1 and model['sum_loss_alpha'] == len(rows), 'RIDGE_OBJECTIVE_BINDING')
    return {'schema': 'polar.chronological-ridge/1', 'feature_order': list(FEATURES),
            'transform': transform, 'model': model, 'fit_event': fit_event.isoformat(),
            'dataset_revision': market['dataset_revision'], 'manifest_ref': market['manifest_ref'],
            'training_rows': rows, 'fit_calls': 1, 'numpy': np.__version__,
            'kernel': 'polar.hyp007_numeric.moments/standardize/ridge_fit/ridge_predict',
            'precision': 'IEEE754_BINARY64', 'selection': 'FIXED_NO_REFIT_OR_TUNING'}


def quantized_prediction(value):
    require(type(value) is float and math.isfinite(value), 'RIDGE_PREDICTION_NONFINITE')
    with localcontext(context()):
        # The rounding is prospective strategy policy, never a metric/display shortcut.
        result = Decimal(repr(value)).quantize(Decimal('0.000000000001'))
    require(result.is_finite(), 'RIDGE_QUANTIZER_NONFINITE')
    return result


def score_ridge(market, fitted, signal, decision, tz):
    require(fitted['schema'] == 'polar.chronological-ridge/1' and
            fitted['feature_order'] == list(FEATURES) and fitted['manifest_ref'] == market['manifest_ref'],
            'RIDGE_MODEL_SOURCE_BINDING')
    require(datetime.fromisoformat(fitted['fit_event']) < decision and eligible_at(signal, tz) <= decision,
            'RIDGE_SCORING_CHRONOLOGY')
    from .hyp007_numeric import array, standardize, ridge_predict
    index = market['dates'].index(signal)
    features = [feature_row(market, s, index) for s in market['symbols']]
    values = ridge_predict(fitted['model'], standardize(array(features, columns=4), fitted['transform']))
    scores = [{'symbol': s, 'prediction_repr': repr(v), 'prediction_bits': v.hex(),
               'rank_value': str(quantized_prediction(v)), 'features': f}
              for s,v,f in zip(market['symbols'], values, features)]
    winner = max(range(len(scores)), key=lambda i:(Decimal(scores[i]['rank_value']), -i))
    return {'signal': signal, 'decision': decision.isoformat(), 'scores': scores,
            'selected_symbol': scores[winner]['symbol'] if Decimal(scores[winner]['rank_value']) > 0 else None}


def diagnostic_mse(market, fitted, cycles):
    """A-v1.2 diagnostic only: fixed unrounded binary64 pairs, never model selection."""
    from .hyp007_numeric import array, standardize, ridge_predict
    samples=[]
    for cycle in cycles:
        for symbol in market['symbols']:
            row=feature_row(market,symbol,cycle['signal_index'])
            y=float(Fraction(market['prices_micro'][cycle['label_exit']][symbol],
                             market['prices_micro'][cycle['entry']][symbol])-1)
            require(math.isfinite(y),'RIDGE_DIAGNOSTIC_INPUT_NONFINITE')
            samples.append((cycle,symbol,row,y))
    require(samples,'RIDGE_DIAGNOSTIC_EMPTY')
    predictions=ridge_predict(fitted['model'],standardize(array([s[2] for s in samples],columns=4),fitted['transform']))
    records=[{'signal':c['signal'],'entry':c['entry'],'label_exit':c['label_exit'],'symbol':s,
              'prediction_repr':repr(p),'label_repr':repr(y)} for (c,s,_,y),p in zip(samples,predictions)]
    return diagnostic_from_records(records)


def diagnostic_from_records(records):
    require(type(records) is list and records,'RIDGE_DIAGNOSTIC_EMPTY')
    pairs=[(float(r['prediction_repr']),float(r['label_repr'])) for r in records]
    require(all(math.isfinite(p) and math.isfinite(y) for p,y in pairs),'RIDGE_DIAGNOSTIC_INPUT_NONFINITE')
    try:
        sse=math.fsum((p-y)**2 for p,y in pairs);mse=sse/len(records)
        require(math.isfinite(sse) and math.isfinite(mse),'RIDGE_DIAGNOSTIC_OVERFLOW')
    except (ArithmeticError,ValueError):
        return {'status':'UNAVAILABLE','reason':'NUMERICAL_OVERFLOW','n':len(records),'sse_repr':None,'mse_repr':None,'rows':records}
    return {'status':'OK','reason':None,'n':len(records),'sse_repr':repr(sse),'mse_repr':repr(mse),'rows':records}

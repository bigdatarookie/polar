"""Pure witnessed single-asset temporal volatility, with no source or execution I/O."""
from copy import deepcopy
from datetime import date
from fractions import Fraction
import math

from .gym_contract import canonical, sha

SCHEMA = 'polar.temporal-volatility-witness/1'
WINDOWS = {'ROLLING_60': 60, 'STATIC_CALIBRATION': 1258}
SCALE = 1000000000000


class TemporalEstimationError(ValueError):
    """A failed estimator call retains its partial evidence and actual counters."""
    def __init__(self, reason, witness):
        super().__init__(reason)
        self.witness = witness
        self.events = witness


def _require(value, reason):
    if not value:
        raise ValueError(reason)


def _finite(value, reason):
    _require(type(value) is float and math.isfinite(value), reason)
    return value


def _rational(value):
    return {'numerator':str(value.numerator),'denominator':str(value.denominator)}


def _sealed(witness):
    result=deepcopy(witness)
    result['witness_sha256']=sha(canonical(result))
    return result


def estimate_temporal(prices_micro, labels, *, kind, source_ref=None):
    """Estimate one declared window; caller owns eligible prefixes and source pins.

    The fixed kinds take61 or1259 positive integer-microprice closes. No dates,
    input values, means or weights are selected/tuned by this helper. Call only
    after the original's durable scientific start. Failures never return a target.
    """
    counts={'estimator_calls':1,'calibration_estimates':int(kind=='STATIC_CALIBRATION'),
            'rolling_estimates':int(kind=='ROLLING_60'),'completed_estimates':0}
    witness={'schema':SCHEMA,'kind':kind,'status':'INVALID','reason':None,
             'actual_counts':counts,'source_ref':deepcopy(source_ref),
             'labels':deepcopy(labels),'price_scale_micro_per_usd':1000000,
             'annual_sessions':252,'annual_cap_binary64':repr(.10),'weight_decimal_places':12}
    try:
        _require(type(kind) is str and kind in WINDOWS,'TEMPORAL_KIND')
        n=WINDOWS[kind];witness['return_count']=n
        _require(type(source_ref) is dict or source_ref is None,'TEMPORAL_SOURCE_REF')
        # Validate public metadata representation without opening any reference.
        canonical(source_ref)
        _require(type(labels) is list and len(labels)==n+1 and
                 all(type(d) is str and date.fromisoformat(d).isoformat()==d for d in labels) and
                 labels==sorted(set(labels)),'TEMPORAL_LABELS')
        _require(type(prices_micro) is list and len(prices_micro)==n+1,'TEMPORAL_PRICE_COUNT')
        _require(all(type(v) is int and v>0 for v in prices_micro),'TEMPORAL_PRICE_DOMAIN')
        witness.update(first_label=labels[0],last_label=labels[-1],
                       price_operands_sha256=sha(canonical(prices_micro)))
        prices=[]
        for value in prices_micro:
            token=f'{value//1000000}.{value%1000000:06d}'
            prices.append(_finite(float(token),'TEMPORAL_NONFINITE_PRICE'))
            _require(prices[-1]>0,'TEMPORAL_NONPOSITIVE_PRICE')
        witness['prices_binary64']=[repr(v) for v in prices]
        returns=[]
        for left,right in zip(prices,prices[1:]):
            ratio=_finite(right/left,'TEMPORAL_NONFINITE_RATIO')
            returns.append(_finite(ratio-1,'TEMPORAL_NONFINITE_RETURN'))
        witness['returns_binary64']=[repr(v) for v in returns]
        total=_finite(math.fsum(returns),'TEMPORAL_NONFINITE_RETURN_SUM')
        mean=_finite(total/n,'TEMPORAL_NONFINITE_MEAN')
        witness.update(return_sum_binary64=repr(total),mean_binary64=repr(mean))
        squares=[]
        for value in returns:
            centered=_finite(value-mean,'TEMPORAL_NONFINITE_CENTERED_RETURN')
            squares.append(_finite(centered*centered,'TEMPORAL_NONFINITE_CENTERED_SQUARE'))
        square_sum=_finite(math.fsum(squares),'TEMPORAL_NONFINITE_SQUARE_SUM')
        variance=_finite(square_sum/(n-1),'TEMPORAL_NONFINITE_VARIANCE')
        witness.update(centered_squares_binary64=[repr(v) for v in squares],
                       centered_square_sum_binary64=repr(square_sum),
                       sample_variance_binary64=repr(variance),variance_denominator=n-1)
        _require(variance>0,'TEMPORAL_NONPOSITIVE_VARIANCE')
        annual_variance=_finite(252.0*variance,'TEMPORAL_NONFINITE_ANNUAL_VARIANCE')
        sigma=_finite(math.sqrt(annual_variance),'TEMPORAL_NONFINITE_SIGMA')
        _require(sigma>0,'TEMPORAL_NONPOSITIVE_SIGMA')
        uncapped=_finite(.10/sigma,'TEMPORAL_NONFINITE_WEIGHT')
        raw=min(1.0,uncapped)
        exact=Fraction.from_float(raw)
        weight=Fraction((exact*SCALE).numerator//(exact*SCALE).denominator,SCALE)
        _require(0<=weight<=1,'TEMPORAL_WEIGHT_DOMAIN')
        witness.update(annual_variance_binary64=repr(annual_variance),annual_sigma_binary64=repr(sigma),
            uncapped_weight_binary64=repr(uncapped),raw_weight_binary64=repr(raw),
            raw_weight_exact=_rational(exact),weight=_rational(weight),cash_weight=_rational(1-weight),
            status='OK')
        counts['completed_estimates']=1
        return {'weight':weight,'witness':_sealed(witness)}
    except (ValueError,ArithmeticError,TypeError) as exc:
        witness['reason']=str(exc) if isinstance(exc,ValueError) else 'TEMPORAL_ARITHMETIC_FAILURE'
        # Invalid caller shapes can be non-JSON; retain only a bounded shape marker.
        try: sealed=_sealed(witness)
        except (ValueError,TypeError):
            witness.update(labels=None,source_ref=None,metadata_status='INVALID_NON_JSON_CALLER_METADATA')
            sealed=_sealed(witness)
        raise TemporalEstimationError(witness['reason'],sealed) from exc


def verify_temporal_witness(witness):
    """Validate saved envelope/domain/projection identities, with zero estimation.

    Deliberately does NOT recompute prices->returns, centered observations,
    either fsum reduction, sample variance, sqrt, or the exposure policy. The
    estimator's reduction witnesses remain attributed original evidence; this
    integrity/identity check is not an independent re-estimation certificate.
    """
    answer={'status':'INVALID','reason':None,'estimator_calls':0,'policy_calls':0,
            'source_reads':0,'native_calls':0,'store_writes':0}
    try:
        _require(type(witness) is dict,'TEMPORAL_WITNESS_SCHEMA')
        body={k:v for k,v in witness.items() if k!='witness_sha256'}
        _require(witness.get('witness_sha256')==sha(canonical(body)),'TEMPORAL_WITNESS_HASH')
        _require(witness.get('schema')==SCHEMA and witness.get('status')=='OK' and
                 witness.get('reason') is None,'TEMPORAL_WITNESS_NOT_SUCCESSFUL')
        kind=witness['kind'];_require(kind in WINDOWS,'TEMPORAL_KIND');n=WINDOWS[kind]
        _require(witness['actual_counts']=={'estimator_calls':1,'calibration_estimates':int(kind=='STATIC_CALIBRATION'),
                 'rolling_estimates':int(kind=='ROLLING_60'),'completed_estimates':1},'TEMPORAL_WITNESS_COUNTS')
        labels=witness['labels']
        _require(type(labels) is list and len(labels)==n+1 and labels==sorted(set(labels)) and
                 all(type(d) is str and date.fromisoformat(d).isoformat()==d for d in labels) and
                 witness['first_label']==labels[0] and witness['last_label']==labels[-1], 'TEMPORAL_WITNESS_LABELS')
        _require(witness['return_count']==n and witness['variance_denominator']==n-1 and
                 witness['annual_sessions']==252 and witness['price_scale_micro_per_usd']==1000000 and
                 witness['weight_decimal_places']==12 and witness['annual_cap_binary64']==repr(.10), 'TEMPORAL_WITNESS_DEFINITION')
        def number(key,positive=False):
            token=witness[key];value=float(token)
            _require(type(token) is str and repr(value)==token and math.isfinite(value) and
                     (not positive or value>0),'TEMPORAL_WITNESS_BINARY64')
            return value
        for key,count,positive in [('prices_binary64',n+1,True),('returns_binary64',n,False),('centered_squares_binary64',n,False)]:
            values=witness[key];_require(type(values) is list and len(values)==count,'TEMPORAL_WITNESS_VECTOR')
            for token in values:
                value=float(token)
                _require(type(token) is str and repr(value)==token and math.isfinite(value) and
                         (not positive or value>0) and (key!='centered_squares_binary64' or value>=0),'TEMPORAL_WITNESS_BINARY64')
        total=number('return_sum_binary64');mean=number('mean_binary64')
        squares=number('centered_square_sum_binary64',True);variance=number('sample_variance_binary64',True)
        annual=number('annual_variance_binary64',True);number('annual_sigma_binary64',True)
        uncapped=number('uncapped_weight_binary64',True);raw=number('raw_weight_binary64',True)
        # Check only scalar algebraic links, without reducing saved observations.
        _require(total/n==mean and squares/(n-1)==variance and 252.0*variance==annual,
                 'TEMPORAL_WITNESS_SCALAR_IDENTITY')
        _require(raw<=1 and raw<=uncapped and (raw==1 or raw==uncapped),'TEMPORAL_WITNESS_CAP')
        exact=Fraction.from_float(raw)
        def fraction(value):
            _require(type(value) is dict and set(value)=={'numerator','denominator'},'TEMPORAL_WITNESS_RATIONAL')
            v=Fraction(int(value['numerator']),int(value['denominator']))
            _require(_rational(v)==value,'TEMPORAL_WITNESS_RATIONAL');return v
        weight=fraction(witness['weight']);cash=fraction(witness['cash_weight'])
        _require(fraction(witness['raw_weight_exact'])==exact and weight.denominator<=SCALE and
                 weight*SCALE==(exact*SCALE).numerator//(exact*SCALE).denominator and
                 0<=weight<=1 and cash==1-weight,'TEMPORAL_WITNESS_FLOOR')
        answer['status']='OK'
    except (ValueError,ArithmeticError,TypeError,KeyError) as exc:
        answer['reason']=str(exc) if isinstance(exc,ValueError) else 'TEMPORAL_WITNESS_MALFORMED'
    return answer

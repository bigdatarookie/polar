"""Invented temporal-volatility witnesses only; no source or account operations."""
from copy import deepcopy
from datetime import date,timedelta
from fractions import Fraction
import math

import pytest
from polar.gym_contract import canonical,sha
from polar.scheduled_temporal import estimate_temporal,verify_temporal_witness,TemporalEstimationError


def labels(n):
    return [(date(2000,1,1)+timedelta(days=i)).isoformat() for i in range(n)]


def alternating(n):
    return [1000000 if i%2==0 else 2000000 for i in range(n)]


def reseal(witness):
    witness['witness_sha256']=sha(canonical({k:v for k,v in witness.items() if k!='witness_sha256'}))


def test_literal_60_return_reduction_and_exact_binary_floor():
    #30 returns+1 and30 returns-1/2. Mean1/4; each centered square9/16.
    #Square sum135/4, sample variance135/236, annual variance8505/59.
    result=estimate_temporal(alternating(61),labels(61),kind='ROLLING_60',source_ref={'member_id':'invented-member','sha256':'a'*64})
    w=result['witness']
    assert w['returns_binary64']==['1.0','-0.5']*30
    assert w['mean_binary64']=='0.25' and w['return_sum_binary64']=='15.0'
    assert w['centered_squares_binary64']==['0.5625']*60
    assert w['centered_square_sum_binary64']=='33.75'
    assert w['sample_variance_binary64']=='0.5720338983050848'
    assert w['annual_sigma_binary64']=='12.006354249849592'
    assert w['raw_weight_binary64']=='0.008328922995192545'
    assert result['weight']==Fraction(8328922995,10**12)
    assert w['weight']=={'numerator':'1665784599','denominator':'200000000000'}
    raw=Fraction.from_float(float(w['raw_weight_binary64']))
    assert result['weight']<=raw<result['weight']+Fraction(1,10**12)
    assert w['actual_counts']=={'estimator_calls':1,'calibration_estimates':0,'rolling_estimates':1,'completed_estimates':1}
    assert verify_temporal_witness(w)['status']=='OK'


def test_one_static_1258_return_witness_and_47_rolling_call_accounting():
    result=estimate_temporal(alternating(1259),labels(1259),kind='STATIC_CALIBRATION')
    witness=result['witness']
    assert witness['return_count']==1258 and witness['variance_denominator']==1257
    assert witness['mean_binary64']=='0.25' and witness['centered_square_sum_binary64']=='707.625'
    assert witness['actual_counts']['calibration_estimates']==1 and verify_temporal_witness(witness)['status']=='OK'
    calls=[estimate_temporal(alternating(61),labels(61),kind='ROLLING_60')['witness'] for _ in range(47)]
    calls.append(witness)
    assert sum(w['actual_counts']['estimator_calls'] for w in calls)==48
    assert sum(w['actual_counts']['rolling_estimates'] for w in calls)==47
    assert sum(w['actual_counts']['calibration_estimates'] for w in calls)==1


def test_cap_and_detached_evidence_without_future_access():
    prices=[1000000000000+i%2 for i in range(61)];dates=labels(61);source={'member_id':'invented'}
    r=estimate_temporal(prices,dates,kind='ROLLING_60',source_ref=source)
    assert r['weight']==1 and r['witness']['cash_weight']=={'numerator':'0','denominator':'1'}
    assert r['witness']['raw_weight_binary64']=='1.0'
    dates[0]='changed';source['member_id']='changed';prices[0]=1
    assert r['witness']['labels'][0]=='2000-01-01' and r['witness']['source_ref']['member_id']=='invented'
    assert verify_temporal_witness(r['witness'])['status']=='OK'


@pytest.mark.parametrize('kind,count',[('ROLLING_60',60),('ROLLING_60',62),('STATIC_CALIBRATION',1258),('STATIC_CALIBRATION',1260)])
def test_no_short_window_or_future_suffix_substitution(kind,count):
    with pytest.raises(TemporalEstimationError,match='TEMPORAL_PRICE_COUNT') as e:
        estimate_temporal(alternating(count),labels(61 if kind=='ROLLING_60' else 1259),kind=kind)
    assert e.value.witness['actual_counts']['completed_estimates']==0


@pytest.mark.parametrize('value',[True,False,0,-1,1.0,float('nan'),float('inf'),'1',None])
def test_invalid_quote_fails_with_partial_counters_no_target(value):
    prices=alternating(61);prices[5]=value
    with pytest.raises(TemporalEstimationError,match='TEMPORAL_PRICE_DOMAIN') as e:
        estimate_temporal(prices,labels(61),kind='ROLLING_60')
    w=e.value.witness
    assert w['status']=='INVALID' and 'weight' not in w
    assert w['actual_counts']['estimator_calls']==1 and w['actual_counts']['completed_estimates']==0


@pytest.mark.parametrize('change',['missing','duplicate','reverse','bad_date'])
def test_label_geometry_failures(change):
    dates=labels(61)
    if change=='missing':dates.pop()
    elif change=='duplicate':dates[1]=dates[0]
    elif change=='reverse':dates.reverse()
    else:dates[0]='not-a-date'
    with pytest.raises(TemporalEstimationError):estimate_temporal(alternating(61),dates,kind='ROLLING_60')


def test_zero_variance_failure_retains_reductions_and_has_no_fallback():
    with pytest.raises(TemporalEstimationError,match='TEMPORAL_NONPOSITIVE_VARIANCE') as e:
        estimate_temporal([1000000]*61,labels(61),kind='ROLLING_60')
    w=e.value.witness
    assert w['sample_variance_binary64']=='0.0' and w['returns_binary64']==['0.0']*60
    assert w['actual_counts']['estimator_calls']==1 and w['actual_counts']['completed_estimates']==0
    assert verify_temporal_witness(w)['status']=='INVALID'


def test_nonfinite_conversion_and_unknown_kind_are_witnessed():
    with pytest.raises(TemporalEstimationError,match='TEMPORAL_NONFINITE_PRICE'):
        estimate_temporal([10**320]*61,labels(61),kind='ROLLING_60')
    with pytest.raises(TemporalEstimationError,match='TEMPORAL_KIND'):
        estimate_temporal(alternating(61),labels(61),kind='OTHER')


def test_saved_verifier_never_calls_estimator_reductions_or_policy(monkeypatch):
    w=estimate_temporal(alternating(61),labels(61),kind='ROLLING_60')['witness']
    import polar.scheduled_temporal as module
    def forbidden(*a,**k):raise AssertionError('SAVED_VERIFICATION_REESTIMATED')
    monkeypatch.setattr(module,'estimate_temporal',forbidden)
    monkeypatch.setattr(math,'fsum',forbidden)
    monkeypatch.setattr(math,'sqrt',forbidden)
    answer=verify_temporal_witness(w)
    assert answer=={'status':'OK','reason':None,'estimator_calls':0,'policy_calls':0,'source_reads':0,'native_calls':0,'store_writes':0}


@pytest.mark.parametrize('change',['hash','mean','floor','counts','last_label','definition','nonfinite'])
def test_saved_tampering_and_scalar_identity_failures(change):
    w=deepcopy(estimate_temporal(alternating(61),labels(61),kind='ROLLING_60')['witness'])
    if change=='hash':w['mean_binary64']='0.5'
    elif change=='mean':w['mean_binary64']='0.5';reseal(w)
    elif change=='floor':w['weight']={'numerator':'0','denominator':'1'};reseal(w)
    elif change=='counts':w['actual_counts']['estimator_calls']=2;reseal(w)
    elif change=='last_label':w['last_label']='2099-01-01';reseal(w)
    elif change=='definition':w['annual_sessions']=365;reseal(w)
    else:w['annual_sigma_binary64']='inf';reseal(w)
    assert verify_temporal_witness(w)['status']=='INVALID'

"""Fresh pure/mocked controls; no actual native fit/LP or real rows."""
from fractions import Fraction as F
from types import SimpleNamespace as N
import pytest
from polar.hyp008_s1_linear import Arithmetic,LinearUnavailable,sparse_equations,generate,predict_linear
from polar.hyp008_s1_numeric import round_binary64,ratio
from polar.hyp008_s1_evaluation import evaluate_common
import polar.hyp008_s1_models as models

bits=lambda v:round_binary64(F(v))['bits']
Z=tuple(bits(0) for _ in range(5))


def fake_sparse(args,**kwargs):return (args,kwargs)


def test_new_mocked_candidate_passes_full_row_exact_certificate():
    calls=[]
    def lp(cost,**kwargs):
        calls.append(kwargs)
        return N(status=0,success=True,nit=4,eqlin=N(marginals=[-.1,.1]))
    result=generate(('new-a','new-b'),(Z,Z),(bits(0),bits(2)),lp,fake_sparse)
    assert len(calls)==1 and calls[0]['method']=='highs-ds'
    assert result['proof']['status']=='EXACT_REPRESENTED_INPUT_CERTIFIED'
    assert result['proof']['primary_objective']==('1','5')
    assert result['theta']==[('0','1')]*6
    assert len(result['certificate_request']['row_ids'])==2


def test_generalized_sparse_10000_rows_is_linear_allocation_not_dense():
    A=[(F(1),F(1),F(2),F(3),F(4),F(5))]*10000
    args,kwargs=sparse_equations(A,fake_sparse)
    data,indices,indptr=args
    assert kwargs['shape']==(10000,20006)
    assert len(data)==len(indices)==80000 and len(indptr)==10001
    assert indices[-2:]==[10005,20005]


def test_growth_guard_precedes_large_product_and_sum():
    m=Arithmetic();a=F(2**3000)
    with pytest.raises(LinearUnavailable,match='INTEGER_GROWTH'):m.mul(a,a)
    with pytest.raises(LinearUnavailable,match='INTEGER_GROWTH'):m.add(a,F(1,2**3000))
    with pytest.raises(LinearUnavailable,match='DEPENDENT'):m.solve([[F(0)]],[F(1)])


def test_bad_reconstruction_does_not_retry_or_return_approximate_theta():
    calls=[]
    def lp(*args,**kwargs):
        calls.append(1)
        return N(status=0,success=True,nit=1,eqlin=N(marginals=[.2,.2]))
    with pytest.raises(LinearUnavailable,match='DUAL_RECONSTRUCTION'):
        generate(('x','y'),(Z,Z),(bits(0),bits(2)),lp,fake_sparse)
    assert len(calls)==1


def test_linear_dot_is_exact_before_one_round():
    theta=[('9007199254740993','1'),('-9007199254740992','1')]+[('0','1')]*4
    result=predict_linear(theta,(bits(1),)+Z[:4])
    assert result['bits']==bits(1) and ratio(result['residual'])==0


def masks():
    return {'schema':'polar.hyp008-s1-masks/1','I':['q'],'E':['q'],'P':['q'],
            'C':[{'opportunity_id':'q','history_window':[f'w{i}' for i in range(52)]}],
            'training':[{'opportunity_id':'a','admitted':True},{'opportunity_id':'b','admitted':True}]}


def test_common_p_exact_loss_breach_and_tie():
    forecast={'TREE':{'q':bits(0)},'LINEAR':{'q':bits(2)},'HISTORICAL':{'q':bits(1)}}
    result=evaluate_common(masks(),forecast,{'q':bits(1)})
    a=result['aggregate']
    assert ratio(a['mean_linear_minus_tree'])==F(4,5)
    assert a['strict_breaches']=={'TREE':0,'LINEAR':1,'HISTORICAL':0}
    assert a['ties']=={'TREE':0,'LINEAR':0,'HISTORICAL':1}


def test_missing_required_forecast_is_family_failure_and_empty_p_is_no_ratio():
    forecast={'TREE':{'q':bits(0)},'LINEAR':{},'HISTORICAL':{'q':bits(1)}}
    assert evaluate_common(masks(),forecast,{'q':bits(1)})['status']=='PLANNED_FAMILY_UNAVAILABLE'
    m=masks();m['P']=[]
    forecast['LINEAR']={'q':bits(0)}
    result=evaluate_common(m,forecast,{})
    assert result['status']=='INSUFFICIENT_EVIDENCE' and result['aggregate'] is None


def test_linear_failure_stops_history_and_all_predictions(monkeypatch):
    calls=[]
    monkeypatch.setattr(models,'fit_tree',lambda *a:(object(),{'partial':'tree'}))
    def fail(*a):raise LinearUnavailable('INVENTED_LINEAR_FAILURE')
    monkeypatch.setattr(models,'fit_linear',fail)
    monkeypatch.setattr(models,'historical',lambda *a:pytest.fail('historical must not start'))
    result=models.fixed_family(('a','b'),(Z,Z),(bits(0),bits(2)),{'q':Z},
        {'q':{'ids':[f'w{i}' for i in range(52)],'bits':[bits(0)]*52}},
        {'q':bits(1)},masks(),object(),calls.append)
    assert calls==['TREE_START','LINEAR_START']
    assert result['status']=='PLANNED_FAMILY_UNAVAILABLE'
    assert result['stages']['HISTORICAL_PASS']=='NOT_RUN'
    assert result['artifacts']=={'tree':{'partial':'tree'}} and result['evaluation'] is None


def test_empty_issue_set_does_not_start_or_convert():
    m=masks();m.update(I=[],P=[])
    result=models.fixed_family((),(),(),{},{},{},m,object(),lambda *a:pytest.fail('no charge'))
    assert result['status']=='NOT_STARTED'


def test_stored_certificate_readback_never_uses_lp():
    from polar.hyp008_s1_linear import verify_saved_linear
    def lp(*a,**k):return N(status=0,success=True,nit=1,eqlin=N(marginals=[-.1,.1]))
    result=generate(('stored-a','stored-b'),(Z,Z),(bits(0),bits(2)),lp,fake_sparse)
    assert verify_saved_linear(result)['proof_id']==result['proof']['proof_id']
    result['theta'][0]=('1','1')
    with pytest.raises(LinearUnavailable,match='STORED_CERTIFICATE_MISMATCH'):verify_saved_linear(result)

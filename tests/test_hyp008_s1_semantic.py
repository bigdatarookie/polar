"""Stored model-structure inspection and call-boundary doubles; no native imports."""
from types import SimpleNamespace as N
import json
import pytest

from polar.hyp008_s1_semantic import tree_structure
import polar.hyp008_s1_models as models


def test_model_structure_is_observed_from_text_and_not_a_two_leaf_gate():
    tree={'actual_iterations':2,'model_text':'Tree=0\nnum_leaves=1\nsplit_feature=\nTree=1\nnum_leaves=3\nsplit_feature=2 4\n'}
    result=tree_structure(tree)
    assert result['status']=='OBSERVED_SERIALIZED_MODEL'
    assert [r['leaves'] for r in result['trees']]==[1,3]
    assert [r['splits'] for r in result['trees']]==[0,2]
    assert result['training_metadata_upper_bound']==245
    assert result['upper_bound_is_not_actual_training_count'] is True
    assert tree_structure(None)['status']=='NOT_OBSERVED'


def test_tree_witness_is_before_mock_fit_and_completed_only_after_model_return(monkeypatch):
    calls=[];parameters={'max_depth':{'origin':'invented','value':2}}
    booster=N(model_to_string=lambda:'invented model',current_iteration=lambda:1)
    class Fake:
        def __init__(self,**kwargs):assert kwargs=={'max_depth':2};self.booster_=booster
        def get_params(self,**kwargs):return {'max_depth':2}
        def fit(self,*args):calls.append('mock-fit')
    monkeypatch.setitem(__import__('sys').modules,'numpy',N(__file__='/usr/local/lib/python3.13/site-packages/numpy/__init__.py',
        array=lambda values,**kwargs:values,float64='invented-tag'))
    monkeypatch.setitem(__import__('sys').modules,'lightgbm',N(__file__='/usr/local/lib/python3.13/site-packages/lightgbm/__init__.py',
        LGBMRegressor=Fake,Booster=lambda **kwargs:booster))
    def observe(stage,state,record):calls.append(state)
    zero='0000000000000000'
    _,record=models.fit_tree(((zero,)*5,),(zero,),N(verify=lambda:{'TREE-DEFAULTS.json':{'wrapper_effective_parameters':parameters}}),observe=observe)
    assert calls==['CALL_BOUNDARY_OBSERVED','mock-fit','COMPLETED']
    assert record['parameter_provenance']==parameters


def test_linear_call_witness_surrounds_only_injected_lp_and_successful_generation(monkeypatch):
    calls=[]
    monkeypatch.setitem(__import__('sys').modules,'scipy',N(__file__='/usr/local/lib/python3.13/site-packages/scipy/__init__.py'))
    monkeypatch.setitem(__import__('sys').modules,'scipy.optimize',N(linprog=lambda *a,**k:calls.append('mock-lp')))
    monkeypatch.setitem(__import__('sys').modules,'scipy.sparse',N(csr_matrix='invented-sparse'))
    def generate(ids,z,y,lp,sparse):
        lp('invented');return {'proof':{'proof_id':'invented-proof'}}
    monkeypatch.setattr(models,'generate',generate)
    models.fit_linear((),(),(),N(verify=lambda:{}),observe=lambda s,state,r:calls.append(state))
    assert calls==['CALL_BOUNDARY_OBSERVED','mock-lp','COMPLETED']


def test_failed_durable_intent_prevents_any_model_work(monkeypatch):
    def forbidden(*args,**kwargs):pytest.fail('model must not start')
    monkeypatch.setattr(models,'fit_tree',forbidden)
    masks={'schema':'polar.hyp008-s1-masks/1','I':['q'],'P':[],
           'training':[{'opportunity_id':'t','admitted':True}]}
    zero='0000000000000000';z=(zero,)*5
    def start(stage):raise OSError('invented durable write failure')
    result=models.fixed_family(('t',),(z,),(zero,),{'q':z},{'q':{}},{},masks,N(verify=lambda:{}),start)
    assert result['status']=='PLANNED_FAMILY_UNAVAILABLE'
    assert result['stages']=={'TREE':'NOT_RUN','LINEAR':'NOT_RUN','HISTORICAL_PASS':'NOT_RUN'}

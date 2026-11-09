"""Invented injected doubles only: no installed NumPy/LightGBM or native model."""
import copy
from types import SimpleNamespace as N

import polar.hyp008_s1_models as models


def test_tree_constructor_gets_values_and_artifact_keeps_locked_provenance(monkeypatch):
    provenance = {
        'max_depth': {'origin':'invented explicit override','value':2},
        'n_estimators': {'origin':'invented explicit override','value':50},
        'alpha': {'origin':'invented explicit override','value':0.1},
        'class_weight': {'origin':'invented wrapper default','value':None},
        'deterministic': {'origin':'invented explicit override','value':True},
        'objective': {'origin':'invented explicit override','value':'quantile'},
    }
    original = copy.deepcopy(provenance)
    values = {'max_depth':2, 'n_estimators':50, 'alpha':0.1,
              'class_weight':None, 'deterministic':True, 'objective':'quantile'}
    calls = []
    booster = N(model_to_string=lambda:'invented model text', current_iteration=lambda:1)
    class FakeRegressor:
        def __init__(self, **kwargs):
            assert kwargs == values and type(kwargs['max_depth']) is int
            calls.append(('constructor',kwargs)); self.booster_ = booster
        def get_params(self, deep):
            assert deep is False
            return dict(values)
        def fit(self, X, y):
            calls.append(('mock-fit',X,y))
    def restore(*, model_str):
        assert model_str == 'invented model text'
        calls.append(('readback',model_str))
        return booster
    monkeypatch.setitem(__import__('sys').modules, 'numpy', N(
        __file__='/usr/local/lib/python3.13/site-packages/numpy/__init__.py',
        array=lambda values,**kwargs:values, float64='invented-float64-tag'))
    monkeypatch.setitem(__import__('sys').modules, 'lightgbm', N(
        __file__='/usr/local/lib/python3.13/site-packages/lightgbm/__init__.py',
        LGBMRegressor=FakeRegressor, Booster=restore))
    binding = N(verify=lambda:{'TREE-DEFAULTS.json':{'wrapper_effective_parameters':provenance}})
    zero = '0000000000000000'; one = '3ff0000000000000'
    restored, artifact = models.fit_tree(((zero,)*5,), (one,), binding)
    assert restored is booster
    assert [call[0] for call in calls] == ['constructor','mock-fit','readback']
    assert artifact['parameters'] == values
    assert artifact['parameter_provenance'] == original == provenance
    assert artifact['default_hashes'] == models.DEFAULT_HASHES
    assert artifact['nominal_estimators'] == 50 and artifact['actual_iterations'] == 1

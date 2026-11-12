"""Prospective scope wording from profile metadata, no retained inputs or finance."""
from copy import deepcopy
import pytest

from test_reference_cost_profiles import projection_inputs
from scheduled_fixture import fixture
from polar.scheduled_service import public_config
import polar.reference_projection as projection


def project(monkeypatch,config,simulation,evaluation):
    monkeypatch.setattr(projection,'validate_result',lambda x:x)
    return projection.public_reference(config,simulation,evaluation,semantic_id='INVENTED',semantic_hash='a'*64,phase='FINAL')


@pytest.mark.parametrize('symbols',[['VTI'],['GLD','IEF','VTI'],['AAA','BBB','CCC','DDD']])
def test_scheduled_scope_uses_declared_policy_alias_count_not_inherited_four(tmp_path,monkeypatch,symbols):
    _,config,profile,_=fixture(tmp_path,monkeypatch)
    profile=deepcopy(profile);profile['symbols']=symbols
    profile['partition_description']='FINAL-only fixed targets, no training or development selection.'
    wire=public_config(config,profile)
    _,sim,evaluation=projection_inputs()
    # Literal formatter inputs use two leg IDs; role bindings are independent of
    # the declared source-alias dimension being tested here.
    wire.update(primary_strategy='STRATEGY',primary_benchmark='BENCHMARK')
    record=project(monkeypatch,wire,sim,evaluation)
    limits={l['code']:l for l in record['limitations']}
    assert 'SURVIVOR_CONDITIONED_FOUR_ASSETS' not in limits and 'TRAIN_DEVELOPMENT_TEST' not in limits
    cohort=limits['DECLARED_SOURCE_UNIVERSE_SCOPE']
    assert cohort['text'].startswith(f'Fixed declared cohort of {len(symbols)} source aliases,')
    assert 'not a broad-universe sample' in cohort['text'] and 'independent economic bets' in cohort['text']
    assert limits['NO_ML_FIT_EVALUATION_PHASES']['text']==profile['partition_description']
    # Existing renderer includes both in Data & Design, without a frontend change.
    assert 'UNIVERSE' in cohort['code'] and 'PHASE' in 'NO_ML_FIT_EVALUATION_PHASES'
    assert record['bindings']==wire['bindings'] and record['criteria']==evaluation['criteria']
    assert record['metrics'][0]['values']=={'STRATEGY':evaluation['legs'][0]['metrics']['flat_fee_usd'],
                                           'BENCHMARK':evaluation['legs'][1]['metrics']['flat_fee_usd']}


def test_non_scheduled_fallback_and_explicit_override_preserve_legacy(monkeypatch):
    config,sim,evaluation=projection_inputs();before=deepcopy((config,sim,evaluation))
    legacy=project(monkeypatch,config,sim,evaluation)
    explicit=project(monkeypatch,{**config,'partition_limitation':('TRAIN_DEVELOPMENT_TEST',config['partition_description'])},sim,evaluation)
    assert legacy==explicit
    limits={l['code']:l for l in legacy['limitations']}
    assert limits['SURVIVOR_CONDITIONED_FOUR_ASSETS']['text']=='Four fixed known survivors/ETF; distinct from the mission broad-data target, no full-universe claim.'
    assert limits['TRAIN_DEVELOPMENT_TEST']['text']=='Invented phase'
    assert (config,sim,evaluation)==before


def test_metadata_wording_override_does_not_change_nonlimitation_result_fields(monkeypatch):
    config,sim,evaluation=projection_inputs()
    old=project(monkeypatch,config,sim,evaluation)
    new=project(monkeypatch,{**config,'cohort_limitation':('DECLARED_SOURCE_UNIVERSE_SCOPE','Three declared source aliases, not economic independence.'),
        'partition_limitation':('NO_ML_FIT_EVALUATION_PHASES','FINAL only, no learned fit.')},sim,evaluation)
    assert {k:v for k,v in old.items() if k!='limitations'}=={k:v for k,v in new.items() if k!='limitations'}
    assert len(old['limitations'])==len(new['limitations'])

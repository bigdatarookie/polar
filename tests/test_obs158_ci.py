"""The new lifecycle never weakens retained admission or the public fixture."""
import pytest
from polar.obs158_ci import inputs, runtime


def test_retained_cannot_enter_public_ci_input_path():
    with pytest.raises(ValueError, match='OBS158_CI_INPUT_SCHEMA'):
        inputs({'source_class':'RETAINED','input_config':{}})


def test_retained_cannot_enter_public_ci_runtime_path():
    with pytest.raises(ValueError, match='OBS158_CI_PUBLIC_ONLY'):
        runtime({'source_class':'RETAINED','input_config':{}}, {})


def test_public_ci_requires_exact_closed_input_schema():
    with pytest.raises(ValueError, match='OBS158_CI_INPUT_SCHEMA'):
        inputs({'source_class':'INVENTED','input_config':{'schema':'polar.obs158-ci-input-config/1'}})

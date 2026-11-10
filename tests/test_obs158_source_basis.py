"""Pure invented metadata operands only: no input loader, preflight or native call."""
import pytest
from polar.obs158_data import source_basis_matches, RETAINED_ASOF


def row(token=RETAINED_ASOF):
    return {'adjustment':'raw','feed':'sip','currency':'USD_REQUEST_CONTRACT','asof':token}


def test_exact_retained_qualifier_preserved_without_mutation():
    value=row();before=dict(value)
    assert source_basis_matches(value,'RETAINED')
    assert value==before and value['asof']=='2020-09-02_ENTITY_MAPPING_NOT_VINTAGE;FALLBACK_UNVERIFIED'


@pytest.mark.parametrize('token',[
    '2020-09-02','2020-09-03_ENTITY_MAPPING_NOT_VINTAGE;FALLBACK_UNVERIFIED',
    '2020-09-02_ENTITY_MAPPING_NOT_VINTAGE','2020-09-02_ENTITY_MAPPING_VERIFIED;FALLBACK_UNVERIFIED',
    '2020-09-02_ENTITY_MAPPING_NOT_VINTAGE;FALLBACK_VERIFIED',
    RETAINED_ASOF+';EXTRA',RETAINED_ASOF+' ',RETAINED_ASOF+'\n',None])
def test_no_changed_date_prefix_wildcard_or_qualifier_promotion(token):
    assert not source_basis_matches(row(token),'RETAINED')


@pytest.mark.parametrize('field,value',[('adjustment','all'),('feed','iex'),('currency','USD'),
    ('currency',None),('asof',None)])
def test_other_source_basis_guards_remain_independent(field,value):
    operands=row();operands[field]=value
    assert not source_basis_matches(operands,'RETAINED')


def test_public_fixture_token_is_separate_and_source_class_is_closed():
    assert source_basis_matches(row('2020-09-02'),'INVENTED')
    assert not source_basis_matches(row(),'INVENTED')
    assert not source_basis_matches(row(),'UNKNOWN')

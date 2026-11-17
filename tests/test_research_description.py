"""Invented descriptive controls; no financial execution or production writes."""
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from polar.api import create_app
from polar.config import Settings
from polar.history_bundle import canonical, sha
from polar.research_results import ResearchError, ResearchResults, validate_result
from polar.research_delivery import validate_delivery
from polar.service import Service
from test_research_results import invented_result


def description():
    old = invented_result()
    return {
        **{k: deepcopy(old[k]) for k in ('question', 'limitations', 'provenance',
           'evidence_level', 'financial_claim', 'criteria', 'point_interpretation')},
        'schema_version': 'polar.research-description/1',
        'bindings': {**old['bindings'], 'code_revision': None, 'evaluator_revision': None,
                     'runtime_id': None, 'candidate_id': None, 'config_sha256': None},
        'basis': {'kind': 'PROSPECTIVE_DESCRIPTIVE', 'investor_metrics': 'NOT_APPLICABLE',
                  'portfolio_series': 'NOT_APPLICABLE', 'orders': 'NOT_APPLICABLE'},
        'observations': [{'id': 'invented-label', 'label': 'Invented label', 'status': 'PASS',
                          'description': 'Synthetic status, not an independent assessment'},
                         {'id': 'invented-pilot', 'label': 'Invented pilot', 'status': 'INCOMPLETE',
                          'description': 'Future labels not run'}],
    }


def test_reader_floor_writer_gate_restart_and_applicability(tmp_path):
    floor = ResearchResults(tmp_path, 10**8)
    old = invented_result()
    old_pub = floor.publish(old)
    raw_old = (tmp_path/'research-results'/old_pub['result_id']/'result.json').read_bytes()
    new = description()
    assert validate_result(new) == new
    with pytest.raises(ResearchError, match='RESEARCH_DESCRIPTIVE_WRITER_DISABLED'):
        floor.publish(new)
    assert floor.catalog()['total'] == 1
    enabled = ResearchResults(tmp_path, 10**8, descriptive_writer_enabled=True)
    pub = enabled.publish(new)
    assert enabled.publish(new) == pub
    assert pub['review_status'] == 'NOT_REVIEWED'
    # Roll back the writer switch, retain the dualreader and all subsequent data.
    service = Service(Settings('unused', tmp_path))
    client = TestClient(create_app(service))
    detail = client.get('/v1/research/results/'+pub['result_id']).json()
    assert detail['record'] == new
    assert detail['assessment']['financial'] == 'NOT_REVIEWED'
    items = client.get('/v1/research/results').json()['items']
    assert {r['result_schema_version'] for r in items} == {
        'polar.research-result/1', 'polar.research-description/1'}
    orders = service.research_executions(pub['result_id'])
    assert orders['status'] == 'NOT_APPLICABLE' and orders['items'] == []
    assert orders['total'] is None and orders['series_id'] is None
    with pytest.raises(ResearchError, match='RESEARCH_EXECUTION_SERIES'):
        service.research_executions(pub['result_id'], 'invented-strategy')
    with pytest.raises(ResearchError, match='RESEARCH_DESCRIPTIVE_WRITER_DISABLED'):
        service.research_publish(new)
    assert floor.read(old_pub['result_id'])['record'] == old
    assert (tmp_path/'research-results'/old_pub['result_id']/'result.json').read_bytes() == raw_old


@pytest.mark.parametrize('mutate', [
    lambda x: x.update(series=[]),
    lambda x: x['basis'].update(investor_metrics='OK'),
    lambda x: x['bindings'].update(code_revision='unknown'),
    lambda x: x['observations'].append(x['observations'][0]),
    lambda x: x['observations'][0].update(description='Private /Users/owner/file'),
])
def test_description_rejects_invented_portfolio_and_invalid_bindings(mutate):
    new = description()
    mutate(new)
    with pytest.raises(ResearchError, match='RESEARCH_INVALID_RESULT'):
        validate_result(new)


def test_delivery_preserves_canonical_description():
    new = description()
    body = {'schema_version': 'polar.research-delivery/1', 'kind': 'RESULT',
            'display_scope': 'OWNER_LOCAL', 'content_sha256': sha(canonical(new)), 'payload': new}
    accepted, rid = validate_delivery(body)
    assert accepted == body and rid == 'research-'+sha(canonical(new))

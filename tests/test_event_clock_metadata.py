"""Invented clock metadata, no prices, source calls or portfolio evaluation."""
from copy import deepcopy
from datetime import datetime, timezone

import pytest

from polar.scheduled_fixed import event_clock_metadata


def availability(known=None, basis='UNKNOWN'):
    return {'known_by': known, 'basis': basis, 'provenance': 'INVENTED_METADATA'}


def fixture():
    days = ['2024-02-09', '2024-02-12', '2024-02-13', '2024-02-14', '2024-02-15']
    return {'schema': 'polar.event-clock-metadata/1', 'event_id': 'invented-event',
            'reference_period': '2024-01', 'release_at': '2024-02-13T08:30:00-05:00',
            'release_zone': 'America/New_York', 'calendar_availability': availability(),
            'event_observation_availability': availability(),
            'reference_provenance': {'basis': 'MODELED', 'provenance': 'INVENTED_REFERENCE_NOT_VENUE'},
            'sessions': [{'date': d, 'open_at': d+'T14:30:00Z', 'close_at': d+'T21:00:00Z'} for d in days],
            'quotes': [{'close_at': days[0]+'T21:00:00Z', 'availability': availability()}]}


def qualified(value, basis='OBSERVED'):
    for name in ('calendar_availability', 'event_observation_availability'):
        value[name] = availability('2024-02-01T12:00:00Z', basis)
    value['quotes'][0]['availability'] = availability('2024-02-09T21:00:01Z', basis)
    return value


def test_winter_conditional_example_unknown_k_and_input_unchanged():
    v=fixture(); before=deepcopy(v); r=event_clock_metadata(v)
    assert v == before
    assert (r['cutoff_at'],r['decision_at'],r['execution_candidate_at']) == (
        '2024-02-12T19:00:00Z','2024-02-12T19:01:00Z','2024-02-12T21:00:00Z')
    assert r['latest_completed_candidate_at']=='2024-02-09T21:00:00Z'
    assert r['qualified_quote'] is None and r['status']=='NOT_EXECUTABLE'
    assert r['latest_completed_candidate_availability']['known_by'] is None
    assert (r['release_close_1_at'],r['expiry_at'],r['reentry_decision_at'],r['reentry_candidate_at']) == (
        '2024-02-13T21:00:00Z','2024-02-14T21:00:00Z','2024-02-15T00:01:00Z','2024-02-15T21:00:00Z')
    r['calendar_availability']['provenance']='mutated-output'
    assert v == before


def test_weekend_quote_has_no_invented_age_limit():
    r=event_clock_metadata(qualified(fixture()))
    assert r['qualified_quote']['close_at']=='2024-02-09T21:00:00Z'
    assert r['status']=='CONDITIONALLY_MODELED' and not r['execution_authority']


def test_observed_metadata_not_execution_authority():
    v=qualified(fixture());v['reference_provenance']['basis']='OBSERVED'
    assert event_clock_metadata(v)['status']=='OBSERVED_METADATA_ELIGIBLE'
    assert event_clock_metadata(v)['execution_authority'] is False


def test_explicit_modeled_availability_never_observed_pit():
    r=event_clock_metadata(qualified(fixture(),'MODELED'))
    assert r['status']=='CONDITIONALLY_MODELED'
    assert r['qualified_quote']['availability']['basis']=='MODELED'


@pytest.mark.parametrize('field', ['calendar_availability','event_observation_availability'])
def test_availability_clocks_independent(field):
    v=qualified(fixture());v[field]=availability()
    r=event_clock_metadata(v)
    assert r['status']=='NOT_EXECUTABLE' and r['qualified_quote'] is not None
    assert r[field]['known_by'] is None


@pytest.mark.parametrize('known,reason', [
    ('2024-02-12T19:01:01Z','QUOTE_KNOWN_AFTER_DECISION'),
    ('2024-02-09T20:59:59Z','QUOTE_KNOWN_BEFORE_COMPLETION'),
    (None,'QUOTE_KNOWN_BY_UNKNOWN')])
def test_quote_availability_failures(known,reason):
    v=qualified(fixture());v['quotes'][0]['availability']=availability(known,'OBSERVED' if known else 'UNKNOWN')
    r=event_clock_metadata(v)
    assert r['status']=='NOT_EXECUTABLE' and r['qualified_quote'] is None
    assert r['quote_checks'][0]['reason']==reason
    assert r['latest_completed_candidate_at']=='2024-02-09T21:00:00Z'


def test_known_by_equal_decision_allowed_and_unfinished_quote_not_used():
    v=qualified(fixture());v['quotes'][0]['availability']=availability('2024-02-12T19:01:00Z','OBSERVED')
    v['quotes'].append({'close_at':'2024-02-12T21:00:00Z','availability':availability('2024-02-12T21:00:00Z','OBSERVED')})
    r=event_clock_metadata(v)
    assert r['qualified_quote']['close_at']=='2024-02-09T21:00:00Z'
    assert r['quote_checks'][1]['reason']=='QUOTE_NOT_COMPLETED_BEFORE_DECISION'


def test_latest_temporal_candidate_separate_from_older_available_quote():
    v=qualified(fixture());v['sessions'].insert(0,{'date':'2024-02-08','open_at':'2024-02-08T14:30:00Z','close_at':'2024-02-08T21:00:00Z'})
    v['quotes'][0]['availability']=availability()
    v['quotes'].append({'close_at':'2024-02-08T21:00:00Z','availability':availability('2024-02-08T21:01:00Z','OBSERVED')})
    r=event_clock_metadata(v)
    assert r['latest_completed_candidate_at']=='2024-02-09T21:00:00Z'
    assert r['qualified_quote']['close_at']=='2024-02-08T21:00:00Z'


def test_early_close_and_strict_equality_do_not_backdate():
    for close in ['2024-02-12T18:00:00Z','2024-02-12T19:01:00Z']:
        v=fixture();v['sessions'][1]['close_at']=close
        r=event_clock_metadata(v)
        assert r['decision_at']=='2024-02-12T19:01:00Z'
        assert r['execution_candidate_at']=='2024-02-13T21:00:00Z'
        assert 'UNPROTECTED_EARLY_EXECUTION_UNAVAILABLE' in r['warnings']
        assert 'PRIOR_REFERENCE_CLOSE_ALREADY_ELAPSED' in r['warnings']


def test_summer_dst_and_release_equality():
    v=fixture();days=['2024-07-05','2024-07-08','2024-07-09','2024-07-10','2024-07-11']
    v['release_at']='2024-07-09T16:00:00-04:00'
    v['sessions']=[{'date':d,'open_at':d+'T13:30:00Z','close_at':d+'T20:00:00Z'} for d in days]
    v['quotes']=[]
    r=event_clock_metadata(v)
    assert r['cutoff_at']=='2024-07-08T18:00:00Z'
    assert r['decision_at']=='2024-07-08T18:01:00Z'
    assert r['release_close_1_at']=='2024-07-09T20:00:00Z'
    assert r['release_close_2_at']=='2024-07-10T20:00:00Z'


@pytest.mark.parametrize('keep,missing', [(0,'PRIOR_REFERENCE_SESSION_UNAVAILABLE'),
    (2,'SECOND_RELEASE_CLOSE_UNAVAILABLE'),(4,'REENTRY_CLOSE_UNAVAILABLE')])
def test_missing_horizon_not_extended(keep,missing):
    v=fixture();v['sessions']=v['sessions'][:keep];v['quotes']=[]
    r=event_clock_metadata(v)
    assert r['status']=='UNAVAILABLE' and missing in r['unavailable_reasons']


def test_no_fabricated_session_for_weekend_release():
    v=fixture();v['release_at']='2024-02-11T08:30:00-05:00'
    r=event_clock_metadata(v)
    assert r['prior_reference_date']=='2024-02-09'
    assert r['release_close_1_at']=='2024-02-12T21:00:00Z'


@pytest.mark.parametrize('mutate', [
    lambda v:v.update(schema='other'),
    lambda v:v.update(weights={}),
    lambda v:v.update(release_at='2024-02-13T08:30:00'),
    lambda v:v.update(release_zone='bad/zone'),
    lambda v:v['sessions'].reverse(),
    lambda v:v['sessions'].append(deepcopy(v['sessions'][0])),
    lambda v:v['sessions'][0].update(date='2024-02-30'),
    lambda v:v['sessions'][0].update(close_at='2024-02-09T13:00:00Z'),
    lambda v:v['calendar_availability'].update(basis='OBSERVED'),
    lambda v:v['calendar_availability'].update(known_by='2024-02-01T00:00:00Z'),
    lambda v:v['quotes'][0].update(close_at='2024-01-01T21:00:00Z'),
])
def test_closed_metadata_rejects_malformed(mutate):
    v=fixture();mutate(v)
    with pytest.raises(Exception,match='EVENT_CLOCK_INVALID_METADATA'):
        event_clock_metadata(v)


@pytest.mark.parametrize('field', ['calendar_availability','event_observation_availability'])
def test_known_after_cutoff_does_not_become_eligible_at_decision(field):
    v=qualified(fixture());v[field]=availability('2024-02-12T19:00:01Z','OBSERVED')
    r=event_clock_metadata(v)
    assert r['status']=='NOT_EXECUTABLE'
    assert any(x.endswith('_KNOWN_AFTER_CUTOFF') for x in r['ineligibility_reasons'])


def test_unknown_reference_basis_blocks_otherwise_complete_metadata():
    v=qualified(fixture());v['reference_provenance']['basis']='UNKNOWN'
    assert event_clock_metadata(v)['status']=='NOT_EXECUTABLE'


def test_temporal_candidate_preserved_without_quote_metadata():
    v=fixture();v['quotes']=[]
    r=event_clock_metadata(v)
    assert r['latest_completed_candidate_at']=='2024-02-09T21:00:00Z'
    assert r['latest_completed_candidate_availability']['basis']=='UNKNOWN'
    assert r['qualified_quote'] is None

"""Invented exact controls for legacy/default and explicit 2x cost profiles."""
from copy import deepcopy
from datetime import timezone
from fractions import Fraction

import pytest

from polar.ci_research import fee_cents, maximum_buy, instant
from polar.ci_research_native import simulate
from polar.research_allocation import ReferenceLedger

BASE = {'flat_cents': 100, 'bps': 10}
STRESS = {'flat_cents': 200, 'bps': 20}


def test_literal_fee_and_cent_ceiling_controls():
    assert fee_cents(100, 10000000) == 200
    assert fee_cents(100, 10000000, cost_profile=BASE) == 200
    assert fee_cents(100, 10000000, cost_profile=STRESS) == 400
    assert fee_cents(1, 1) == 101
    assert fee_cents(1, 1, cost_profile=STRESS) == 201
    assert fee_cents(10000000, 1) == 101
    assert fee_cents(10000000, 1, cost_profile=STRESS) == 202
    assert fee_cents(0, 10000000, cost_profile=STRESS) == 0


@pytest.mark.parametrize('q,p', [(0, 1), (1, 1), (3, 3333333),
                                (100, 10000000), (1000000000, 123456789)])
def test_default_and_explicit_base_preserve_original_integer_formula(q, p):
    expected = 100 + (q*p + 9999999)//10000000 if q else 0
    assert fee_cents(q, p) == expected
    assert fee_cents(q, p, cost_profile=BASE) == expected


def test_affordability_recomputed_under_stress_including_budget():
    assert maximum_buy(100, 10000000, 100200) == 100
    assert maximum_buy(100, 10000000, 100200, cost_profile=BASE) == 100
    assert maximum_buy(100, 10000000, 100200, cost_profile=STRESS) == 99
    assert maximum_buy(100, 10000000, 999999, 100200, cost_profile=STRESS) == 99
    assert maximum_buy(10, 1000000, 1000) == 8
    assert maximum_buy(10, 1000000, 1000, cost_profile=STRESS) == 7


@pytest.mark.parametrize('bad', [
    {}, {'flat_cents': 100}, {'flat_cents': 100, 'bps': 20},
    {'flat_cents': 200, 'bps': 10}, {'flat_cents': 0, 'bps': 0},
    {'flat_cents': 200, 'bps': 20, 'extra': 1},
    {'flat_cents': '200', 'bps': 20}, {'flat_cents': 200, 'bps': 20.0},
    {'flat_cents': True, 'bps': 10}, [], 'stress',
])
def test_unsupported_cost_profiles_fail_closed_even_for_zero_quantity(bad):
    with pytest.raises(ValueError, match='COST_PROFILE'):
        fee_cents(0, 1, cost_profile=bad)
    with pytest.raises(ValueError, match='COST_PROFILE'):
        maximum_buy(0, 1, 0, cost_profile=bad)
    with pytest.raises(ValueError, match='COST_PROFILE'):
        ReferenceLedger(['AAA'], cost_profile=bad)


def test_native_cost_profile_rejected_before_native_setup(monkeypatch):
    import polar.ci_research_native as native
    def forbidden(*args, **kwargs):
        raise AssertionError('NATIVE_SETUP_REACHED_FOR_INVALID_COST_PROFILE')
    monkeypatch.setattr(native.importlib.metadata, 'version', forbidden)
    with pytest.raises(ValueError, match='COST_PROFILE'):
        simulate({'cost_profile': {'flat_cents': 200, 'bps': 10}})
    with pytest.raises(ValueError, match='COST_PROFILE'):
        simulate({'cost_profile': None})


def test_stress_cash_changes_executed_quantities_not_posthoc_fees():
    default = ReferenceLedger(['AAA'])
    explicit_base = ReferenceLedger(['AAA'], cost_profile=BASE)
    supplied = STRESS.copy()
    stress = ReferenceLedger(['AAA'], cost_profile=supplied)
    supplied.update(BASE)  # Constructor snapshot cannot change with caller metadata.
    for ledger in (default, explicit_base, stress):
        intent = ledger.intent({'AAA': 10000000}, {'AAA': Fraction(1)})
        assert intent['targets']['AAA'] == 10000  # Frozen formation price10, futurefill20.
        ledger.execute(intent, {'AAA': 20000000}, date='2020-01-03')
    assert default.fills == explicit_base.fills
    assert default.mark({'AAA': 20000000}) == explicit_base.mark({'AAA': 20000000})
    assert default.fills[0]['q'] == 4994 and default.cash == 1912
    assert stress.fills[0]['q'] == 4989 and stress.cash == 1844
    assert stress.flat_cents == 200 and stress.bps_cents == 19956
    assert stress.fills[0]['fee_cents'] == 20156


def reference_plan(cost_profile):
    symbols = ['AAA', 'BBB']
    days = ['2020-01-02', '2020-01-03', '2020-01-06', '2020-01-07']
    prices = [{'AAA': 10000000, 'BBB': 10000000},
              {'AAA': 20000000, 'BBB': 10000000},
              {'AAA': 21000000, 'BBB': 5000000},
              {'AAA': 22000000, 'BBB': 6000000}]
    grid = [{'date': d, 'nominal_ns': instant(d, 21, 0, timezone.utc),
             'sample_ns': instant(d, 21, 0, timezone.utc) + 1000,
             'initial': i == 0, 'terminal': i == 3} for i, d in enumerate(days)]
    instructions = [{'kind': 'TARGET', 'weights': {'AAA': [1, 1], 'BBB': [0, 1]}},
                    {'kind': 'TARGET', 'weights': {'AAA': [0, 1], 'BBB': [1, 1]}},
                    {'kind': 'EXIT'}]
    decisions = [{'day': days[i+1], 'formation': days[i],
                  'known_ns': instant(days[i+1], 0, 0, timezone.utc),
                  'decision_ns': instant(days[i+1], 0, 1, timezone.utc),
                  'open_ns': grid[i+1]['nominal_ns'], 'kind': 'REFERENCE',
                  'instructions': {'REFERENCE_TEST': instruction}}
                 for i, instruction in enumerate(instructions)]
    return {'symbols': symbols, 'cost_profile': cost_profile,
            'profile': {'kind': 'REFERENCE_TARGETS', 'legs': ['REFERENCE_TEST'], 'end': days[-1]},
            'grid': grid, 'decisions': decisions,
            'prices': {d: {s: {'close_micro': p[s]} for s in symbols} for d, p in zip(days, prices)}}, prices, instructions


def test_native_stress_trace_matches_shared_ledger_and_literal_first_fill():
    plan, prices, instructions = reference_plan(STRESS.copy())
    native_result = simulate(plan)
    assert native_result['cost_profile'] == STRESS
    native = native_result['legs'][0]
    ledger = ReferenceLedger(plan['symbols'], cost_profile=STRESS)
    expected = [ledger.mark(prices[0])]
    for i, instruction in enumerate(instructions):
        intent = ({'targets': {s: 0 for s in plan['symbols']}, 'terminal': True}
                  if instruction['kind'] == 'EXIT' else
                  ledger.intent(prices[i], {s: Fraction(*v) for s, v in instruction['weights'].items()}))
        expected.append(ledger.execute(intent, prices[i+1], date=plan['grid'][i+1]['date']))
    assert native['intents'][0]['targets']['AAA'] == 10000
    assert native['fills'][0]['q'] == 4989
    assert native['fills'][0]['fee_cents'] == 20156
    assert native['fills'][0]['cash_after_cents'] == 1844
    for actual, wanted in zip(native['nav'], expected):
        assert {k: actual[k] for k in wanted} == wanted
    assert [(f['symbol'], f['side'], f['q'], f['fee_cents'], f['settled_cents'], f['cash_after_cents'])
            for f in native['fills']] == [
        (f['symbol'], f['side'], f['q'], f['fee_cents'], f['settled_cents'], f['cash_after_cents'])
        for f in ledger.fills]
    assert not any(native['nav'][-1]['positions'].values())


def projection_inputs():
    metric = {'value': '0', 'status': 'OK', 'reason': None}
    nav = [{'nominal_ns': 1, 'cash_cents': 10000000, 'exposure_cents': 0,
            'flat_cents': 0, 'bps_cents': 0, 'positions': {'AAA': 0}, 'nav_cents': 10000000},
           {'nominal_ns': 1000000001, 'cash_cents': 10000000, 'exposure_cents': 0,
            'flat_cents': 0, 'bps_cents': 0, 'positions': {'AAA': 0}, 'nav_cents': 10000000}]
    simulation = {'legs': [{'id': s, 'nav': deepcopy(nav)} for s in ('STRATEGY', 'BENCHMARK')]}
    evaluation = {'legs': [{'id': s, 'returns': [{'decimal': '0'}],
                            'metrics': {'flat_fee_usd': metric.copy(), 'bps_cost_usd': metric.copy()}}
                           for s in ('STRATEGY', 'BENCHMARK')],
                  'comparisons': [], 'criteria': [], 'point_interpretation': 'INVENTED_ONLY'}
    config = {'primary_strategy': 'STRATEGY', 'primary_benchmark': 'BENCHMARK',
              'clock_description': 'Invented clock', 'partition_description': 'Invented phase',
              'protocol_id': 'INVENTED', 'question_label': 'Invented comparison',
              'question_summary': 'Formatter control only', 'bindings': {},
              'provenance': [], 'evidence_level': 'INVENTED_PUBLIC_TEST'}
    return config, simulation, evaluation


def test_public_cost_descriptions_match_uniform_profile_without_default_delta(monkeypatch):
    import polar.reference_projection as projection
    # Isolate formatter output; full closed-wire validation is covered by the
    # existing service tests and the parent's integrated B qualification.
    monkeypatch.setattr(projection, 'validate_result', lambda value: value)
    config, simulation, evaluation = projection_inputs()
    def projected(cfg):
        return projection.public_reference(cfg, simulation, evaluation,
                                           semantic_id='INVENTED', semantic_hash='a'*64, phase='FINAL')
    legacy = projected(config)
    base = projected({**config, 'cost_profile': BASE})
    assert base == legacy
    assert legacy['costs'][0]['description'] == 'Model USD1 per positive fill, charged once.'
    assert legacy['costs'][1]['label'] == 'Modeled 10bps commission'
    stress = projected({**config, 'cost_profile': STRESS})
    assert stress['costs'][0]['description'] == 'Model USD2 per positive fill, charged once.'
    assert stress['costs'][1]['label'] == 'Modeled 20bps commission'
    assert stress['costs'][1]['description'] == 'Ceiling-cent 20bps exact notional, charged once; no additional spread or slippage debit.'
    with pytest.raises(ValueError, match='COST_PROFILE'):
        projected({**config, 'cost_profile': {'flat_cents': 100, 'bps': 20}})

"""Public no-fit service path in the existing CI lifecycle; no retained inputs."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pytest
from scheduled_fixture import fixture
from polar.reference_service import ReferenceResearchService
from polar.research_results import ResearchResults
import polar.scheduled_service as implementation


def execute(report):
    phases = []
    value = {'schema': 'polar.synthetic-scenario/1', 'scenario': 'scheduled-policy',
             'classification': 'PUBLIC_DETERMINISTIC_SYNTHETIC', 'phases': phases,
             'compute_status': 'NOT_RUN', 'cleanup_status': 'NOT_RUN', 'financial': 'NOT_ASSESSED'}
    temporary = None
    @contextmanager
    def phase(name):
        item = {'name': name, 'status': 'RUNNING'}; phases.append(item); started = time.monotonic()
        try:
            yield item
            item['status'] = 'PASS'
        except BaseException as exc:
            item.update(status='FAIL', error=type(exc).__name__, reason=str(exc)[:500]); raise
        finally:
            item['seconds'] = round(time.monotonic()-started, 6)
    def snapshot(root):
        return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in root.rglob('*') if p.is_file()}
    expected = json.loads((Path(__file__).parents[1]/'fixtures/reference_ridge_expected.json').read_bytes())
    simulations = []
    try:
        with tempfile.TemporaryDirectory(prefix='polar-ci-scheduled-') as temporary, pytest.MonkeyPatch.context() as patch:
            with phase('public_fixture_profile_and_zero_fit_preparation') as item:
                root, config, profile, calendar = fixture(Path(temporary), patch)
                service = ReferenceResearchService(root, 128*1024**2)
                ready = service.preflight(config)
                assert ready['fit_calls'] == ready['predict_calls'] == ready['scientific_starts'] == 0
                assert ready['expected_native_accounts'] == 10
                assert not (root/'scheduled-reference-attempts').exists()
                item.update(input_rows=1600, symbols=4, dates=400, expected_native_accounts=10, fit_calls=0)
            original_native, original_plan = implementation.bounded_native, implementation.plan_phase
            def plan(*args, **kwargs):
                starts = list((root/'scheduled-reference-attempts').rglob('start.json'))
                assert len(starts) == 1 and json.loads(starts[0].read_bytes())['status'] == 'FIRST_START_CONSERVATIVE_DEBIT'
                result = original_plan(*args, **kwargs)
                assert all(d['known_ns'] < d['decision_ns'] < d['open_ns'] for d in result['decisions'])
                first = result['decisions'][0]['instructions']
                assert first['EW_HALF']['weights'] == {s:[1,8] for s in profile['symbols']}
                assert first['CASH'] == {'kind':'HOLD'}
                return result
            def native(plan):
                with phase('native_five_accounts_'+str(len(simulations)+1)) as item:
                    simulation = original_native(plan)
                    name = next(k for k,g in calendar['phases'].items() if g['initial'] == plan['grid'][0]['date'])
                    simulations.append((name, simulation))
                    assert len(simulation['legs']) == 5
                    item.update(native_accounts=5, engine=simulation['engine'])
                    return simulation
            patch.setattr(implementation, 'plan_phase', plan); patch.setattr(implementation, 'bounded_native', native)
            with phase('original_durable_start_native_evaluation_and_publication') as item:
                output = service.run(config)
                assert output['status'] == 'SUCCESS' and output['native_accounts'] == 10
                assert all(output[k] == 0 for k in ('fit_calls','predict_calls','model_calls'))
                item.update(semantic_id=output['semantic_id'], native_accounts=10, fit_calls=0, predict_calls=0)
            with phase('literal_allocation_cost_and_terminal_controls') as item:
                for name, sim in simulations:
                    controls = expected['independently_recomputed_allocation_controls'][name]
                    legs = {t['id']: t for t in sim['legs']}
                    assert all(len(t['nav']) == calendar['phases'][name]['nav_points'] and
                               t['nav'][0]['nav_cents'] == 10000000 and
                               not any(t['nav'][-1]['positions'].values()) for t in legs.values())
                    fill = next(f for f in legs['MOM']['fills'] if f['side'] == 'BUY')
                    assert fill['symbol'] == controls['momentum_winner']
                    for field, key in [('q','filled_quantity'),('fee_cents','fee_cents'),
                                       ('settled_cents','settled_cents'),('cash_after_cents','ending_cash_cents')]:
                        assert fill[field] == controls[key], (name, field)
                    assert all(n['nav_cents'] == 10000000 for n in legs['CASH']['nav'])
                item.update(expected_source='existing frozen reference_ridge_expected.json applicable MOM allocation controls',
                            terminal_all_cash=True, accounts=10)
            with phase('immutable_common_result_and_saved_diagnostics_readback') as item:
                ids = {}
                for name, publication in output['results'].items():
                    detail = ResearchResults(root,128*1024**2).read(publication['result_id']); record = detail['record']
                    assert len(record['series']) == 5 and len(record['criteria']) == (5 if name == 'FINAL' else 0)
                    assert record['basis']['wealth_basis'] == 'SYNTHETIC_VENDOR_ADJUSTED_REFERENCE_UNIT'
                    assert detail['assessment']['financial'] == 'NOT_REVIEWED'
                    assert not any(x['role'] == 'trained_model' for x in record['provenance'])
                    assert any(x['id'] == 'empirical_tail_mean' for x in record['metrics'])
                    ids[name] = publication['result_id']
                item.update(result_ids=ids, finite_common_wire=True, financial='NOT_REVIEWED')
            with phase('stored_only_zero_calls_zero_writes_and_duplicate_rejection') as item:
                before = snapshot(root)
                def forbidden(*args, **kwargs): raise AssertionError('STORED_ONLY_SOURCE_POLICY_MODEL_NATIVE_CALL')
                for key in ('bounded_native','plan_phase','load_reference'): patch.setattr(implementation,key,forbidden)
                reproduced = service.recompute(output['semantic_id'])
                assert reproduced['status'] == 'REPRODUCED'
                assert all(reproduced[k] == 0 for k in ('fit_calls','predict_calls','model_calls','native_calls','store_writes'))
                try: service.run(config)
                except ValueError as exc: assert str(exc) == 'SCHEDULED_ORIGINAL_ALREADY_RECORDED'
                else: raise AssertionError('DUPLICATE_ACCEPTED')
                assert snapshot(root) == before
                item.update(recompute='REPRODUCED', fit_calls=0,predict_calls=0,native_calls=0,store_writes=0,duplicate='REJECTED')
            value['compute_status'] = 'PASS'
    except BaseException:
        if value['compute_status'] != 'PASS': value['compute_status'] = 'FAIL'
        raise
    finally:
        value['cleanup_status'] = ('PASS_TASK_DIRECTORY_REMOVED' if temporary is not None and not Path(temporary).exists()
            else 'FAIL_TASK_DIRECTORY_REMAINS' if temporary is not None else 'NOT_CREATED')
        value['status'] = 'PASS' if value['compute_status'] == 'PASS' and value['cleanup_status'].startswith('PASS') else 'FAIL'
        report.write_text(json.dumps(value,indent=2)+'\n')

if __name__ == '__main__': execute(Path(sys.argv[1]))

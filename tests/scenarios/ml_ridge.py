"""PUBLIC synthetic Service end-to-end, run by the shared CI lifecycle.

Fixture is the existing deterministic 4-symbol/400-date control; never opens
retained data. Spies observe real model/native calls, never supply results.
"""
from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from reference_fixture import fixture
import pytest
from polar.reference_service import ReferenceResearchService
from polar.research_results import ResearchResults
from polar.research_learning import training_rows, eligible_at


def execute(report):
    phases = []
    @contextmanager
    def phase(name):
        item = {'name': name, 'status': 'RUNNING'}
        phases.append(item); started = time.monotonic()
        try:
            yield item
            item['status'] = 'PASS'
        except BaseException as exc:
            item.update(status='FAIL', error=type(exc).__name__, reason=str(exc)[:500])
            raise
        finally:
            item['seconds'] = round(time.monotonic() - started, 6)
    value = {'schema': 'polar.synthetic-scenario/1', 'scenario': 'ml-ridge',
             'classification': 'PUBLIC_DETERMINISTIC_SYNTHETIC', 'phases': phases,
             'compute_status': 'NOT_RUN', 'cleanup_status': 'NOT_RUN', 'financial': 'NOT_ASSESSED'}
    try:
        with tempfile.TemporaryDirectory(prefix='polar-ci-ridge-') as temporary:
            with pytest.MonkeyPatch.context() as patch:
                with phase('fixture_preparation_and_admission') as item:
                    root, config = fixture(Path(temporary), patch)
                    service = ReferenceResearchService(root, 64 * 1024**2)
                    ready = service.preflight(config)
                    assert ready['scientific_starts'] == 0
                    assert ready['input_rows'] == 1600 and ready['training_rows'] == 8
                    item.update(input_rows=1600, symbols=4, dates=400, training_rows=8)
                    market, calendar, timezone, fit_event = service.prepare(config)
                with phase('fit_cutoff_and_leak_rejection') as item:
                    rows = training_rows(market, calendar['training_cycles'], fit_event, timezone)
                    assert len(rows) == 8
                    assert all(eligible_at(r['label_exit'], timezone) <= fit_event for r in rows)
                    future = dict(calendar['training_cycles'][-1], label_exit=market['dates'][-1])
                    try:
                        training_rows(market, [future], fit_event, timezone)
                    except ValueError as exc:
                        assert str(exc) == 'RIDGE_LABEL_NOT_MATURE'
                    else:
                        raise AssertionError('FUTURE_LABEL_ACCEPTED')
                    item.update(mature_rows=len(rows), future_label='REJECTED_BEFORE_LEARNER')
                import polar.reference_service as implementation
                actual_fit, actual_native = implementation.fit_ridge, implementation.bounded_native
                calls = {'fit': 0, 'native': 0}
                def fit(*args, **kwargs):
                    with phase('preprocessing_fit_predict_model_persistence') as item:
                        calls['fit'] += 1
                        model = actual_fit(*args, **kwargs)
                        assert model['fit_calls'] == 1 and len(model['training_rows']) == 8
                        item.update(fit_calls=1, fit_event=model['fit_event'], feature_count=4,
                                    kernel=model['kernel'], objective_lambda=model['model']['lambda'])
                        return model
                def native(plan):
                    with phase('chronological_native_baselines_costs_' + str(calls['native'] + 1)) as item:
                        calls['native'] += 1
                        simulation = actual_native(plan)
                        assert len(simulation['legs']) == 4
                        item.update(native_accounts=len(simulation['legs']), engine=simulation['engine'])
                        return simulation
                patch.setattr(implementation, 'fit_ridge', fit)
                patch.setattr(implementation, 'bounded_native', native)
                with phase('service_original_evaluation_and_immutable_publication') as item:
                    output = service.run(config)
                    assert output['status'] == 'SUCCESS' and output['fit_calls'] == 1
                    assert calls == {'fit': 1, 'native': 2}
                    assert set(output['results']) == {'VALIDATION', 'FINAL'}
                    item.update(fit_calls=1, native_accounts=8, phase_count=2,
                                semantic_id=output['semantic_id'])
                with phase('saved_result_and_model_readback') as item:
                    records = {}
                    for name, published in output['results'].items():
                        detail = ResearchResults(root, 64 * 1024**2).read(published['result_id'])
                        record = detail['record']; records[name] = published['result_id']
                        assert record['basis']['wealth_basis'] == 'SYNTHETIC_VENDOR_ADJUSTED_REFERENCE_UNIT'
                        assert record['primary_benchmark_id'] == 'EW4_MONTHLY'
                        assert len(record['criteria']) == (4 if name == 'FINAL' else 0)
                        assert len(record['series']) == 4
                    item.update(result_ids=records)
                before = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in root.rglob('*') if p.is_file()}
                def forbidden(*args, **kwargs):
                    raise AssertionError('STORED_ONLY_CALLED_FIT_OR_NATIVE')
                patch.setattr(implementation, 'fit_ridge', forbidden)
                patch.setattr(implementation, 'bounded_native', forbidden)
                with phase('stored_only_reproduction_and_duplicate_rejection') as item:
                    reproduced = service.recompute(output['semantic_id'])
                    assert reproduced['status'] == 'REPRODUCED'
                    assert all(reproduced[k] == 0 for k in ['model_calls', 'native_calls', 'store_writes'])
                    try:
                        service.run(config)
                    except ValueError as exc:
                        assert str(exc) == 'REFERENCE_ORIGINAL_ALREADY_RECORDED'
                    else:
                        raise AssertionError('DUPLICATE_ORIGINAL_ACCEPTED')
                    after = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                             for p in root.rglob('*') if p.is_file()}
                    assert before == after
                    item.update(recompute='REPRODUCED', model_calls=0, native_calls=0,
                                store_writes=0, immutable_files=len(before), duplicate='REJECTED')
                value['compute_status'] = 'PASS'
        value['cleanup_status'] = 'PASS_TASK_DIRECTORY_REMOVED'
        assert not Path(temporary).exists()
    except BaseException:
        value['compute_status'] = 'FAIL'
        raise
    finally:
        value['status'] = 'PASS' if value['compute_status'] == 'PASS' and value['cleanup_status'].startswith('PASS') else 'FAIL'
        report.write_text(json.dumps(value, indent=2) + '\n')


if __name__ == '__main__':
    execute(Path(sys.argv[1]))

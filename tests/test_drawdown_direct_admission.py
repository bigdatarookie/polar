"""Direct shared-entry rejection over invented files; no retained data or run."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from polar.config import Settings
from polar.service import Service
from polar import candidate_binding, native_selected_input as selected
from polar.ci_research_service import root_identity
from test_scheduled_drawdown import fixture as scheduled_fixture
from test_native_selected_input import fixture as selected_fixture, Queue
from test_reference_input import put


def forbid_values(monkeypatch, config, manifest):
    from polar import research_reference, scheduled_service
    original = research_reference.pinned_bytes
    blocked = {manifest[k]['path'] for k in ('quotes', 'schedule', 'source_relations') if k in manifest}
    def read(pin):
        assert pin['path'] not in blocked, 'source value or schedule read before required admission'
        return original(pin)
    monkeypatch.setattr(research_reference, 'pinned_bytes', read)
    monkeypatch.setattr(scheduled_service, 'pinned_bytes', read)
    monkeypatch.setattr(scheduled_service, 'bounded_native', lambda *a: pytest.fail('native run reached'))
    monkeypatch.setattr(candidate_binding, 'verify_candidate', lambda _: None)


@pytest.mark.parametrize('method', ['research_preflight', 'research_run'])
def test_direct_service_nonselected_retained_input_rejects_without_start_or_member_read(tmp_path, monkeypatch, method):
    root, config, _, _ = scheduled_fixture(tmp_path, monkeypatch)
    manifest = json.loads(Path(config['input_ref']['path']).read_bytes())
    config['namespace'] = 'RETAINED'
    forbid_values(monkeypatch, config, manifest)
    with pytest.raises(ValueError, match='NATIVE_SELECTED_PROFILE_INPUT_REQUIRED'):
        getattr(Service(Settings('unused-file-only', root)), method)(config)
    assert not (root/'scheduled-reference-attempts').exists()


@pytest.mark.parametrize('method', ['research_preflight', 'research_run'])
@pytest.mark.parametrize('problem', ['missing', 'stale', 'foreign_build'])
def test_direct_service_selected_admission_rejects_before_start_and_value_read(tmp_path, monkeypatch, method, problem):
    root, source, queue, _, _ = selected_fixture(tmp_path/'source', monkeypatch)
    out = selected.prepare_selected(source, root, 10**8, queue=queue)
    manifest = json.loads(Path(out['input_ref']['path']).read_bytes())
    runtime_dir = tmp_path/'runtime'; runtime_dir.mkdir()
    _, config, profile, _ = scheduled_fixture(runtime_dir, monkeypatch)
    config.update(namespace='RETAINED', artifact_root_identity=root_identity(root))
    source.update(namespace='RETAINED', code_revision=config['code_revision'], code=config['code'],
                  protocol_ref=config['protocol_ref'], runtime_image_id=config['runtime_image_id'])
    manifest['provenance'] = {**manifest.pop('conversion_metadata'), 'config': source}
    if problem == 'missing':source['source_admission_ref'] = None
    elif problem == 'foreign_build':source['code_revision'] = '0'*40
    queue = Queue(source)
    if problem == 'stale':queue.row['claimedByGeneration'] = 'previous-generation'
    monkeypatch.setattr(selected, 'current_queue', lambda: queue)
    monkeypatch.setattr(candidate_binding, 'loaded_revision', lambda: config['code_revision'])
    monkeypatch.setattr(selected.platform, 'system', lambda: 'Linux')
    monkeypatch.setattr(selected.platform, 'python_version', lambda: '3.13.18')
    monkeypatch.setenv('POLAR_RUNTIME_IMAGE_ID', config['runtime_image_id'])
    config['input_ref'] = put(tmp_path/'selected-manifest.json', manifest)
    profile['input_sha256'] = config['input_ref']['sha256']
    config['profile_ref'] = put(runtime_dir/'profile.json', profile)
    forbid_values(monkeypatch, config, manifest)
    error = 'NATIVE_SELECTED_AUTHOR_BINDING' if problem == 'foreign_build' else 'NATIVE_SELECTED_SOURCE_ADMISSION'
    with pytest.raises(ValueError, match=error):
        getattr(Service(Settings('unused-file-only', root)), method)(config)
    assert not (root/'scheduled-reference-attempts').exists()


@pytest.mark.parametrize('command', ['research-preflight', 'research-run'])
def test_ordinary_cli_generic_retained_manifest_rejects_before_debit(tmp_path, monkeypatch, command):
    root, config, _, _ = scheduled_fixture(tmp_path, monkeypatch)
    # Clean pinned candidate is required by the actual CLI before shared prepare.
    config.update(namespace='RETAINED', code_revision=candidate_binding.loaded_revision())
    manifest = json.loads(Path(config['input_ref']['path']).read_bytes())
    Path(manifest['quotes']['path']).unlink()  # A value read would yield the wrong error.
    cfg = put(tmp_path/'ordinary-cli-config.json', config)
    env = {**os.environ, 'POLAR_ARTIFACT_ROOT': str(root)}
    result = subprocess.run([sys.executable, '-m', 'polar.cli', command, cfg['path']],
                            env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 1
    assert json.loads(result.stderr)['code'] == 'NATIVE_SELECTED_PROFILE_INPUT_REQUIRED'
    assert not (root/'scheduled-reference-attempts').exists()

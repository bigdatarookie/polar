"""Pure source-boundary controls; no defaults, imports of native libs or models."""
import hashlib
import json
from pathlib import Path

import pytest
import polar.hyp008_s1_models as models


@pytest.mark.parametrize('extra_entry', [False, True])
def test_packaged_source_map_requires_exact_path_set(tmp_path, monkeypatch, extra_entry):
    package = tmp_path/'package'; package.mkdir()
    (package/'module.py').write_text('# invented source\n')
    (package/'schema.json').write_text('{}\n')
    actual = {str(path): {'bytes':path.stat().st_size,
              'sha256':hashlib.sha256(path.read_bytes()).hexdigest()} for path in package.iterdir()}
    observed_files = dict(actual)
    if extra_entry:
        observed_files[str(package/'absent-stale.py')] = {'bytes':0,'sha256':hashlib.sha256(b'').hexdigest()}
    candidate = {'commit':'invented', 'tree':'invented'}
    image = 'sha256:'+'a'*64
    prep = {'preparation':'PREPARED','scenario_started':False,
        'expected':{'candidate':candidate,'image_id':image},
        'observed':{'image_id':image,'os':'linux','architecture':'arm64',
                    'matches':{'source':True},'container_id':'invented-container'},
        'source_binding':{'packaged_source_independently_observed':True,
                         'observed_container_id':'invented-container','observed_files':observed_files}}
    preparation = tmp_path/'preparation.json'; preparation.write_text(json.dumps(prep))
    monkeypatch.setattr(models, 'Path', lambda value: preparation if str(value)=='/polar-launch/preparation.json' else Path(value))
    monkeypatch.setattr(models, '__file__', str(package/'module.py'))
    monkeypatch.setattr(models.os, 'geteuid', lambda:10001)
    monkeypatch.setattr(models.sys, 'platform', 'linux')
    monkeypatch.setattr(models.sys, 'version_info', (3,13,18))
    def forbidden(*args):pytest.fail('source-boundary control must stop before default/native checks')
    monkeypatch.setattr(models, 'read_lock', forbidden)
    # Exact map passes the source-map boundary then rejects this invented origin.
    # An extra absent entry must fail earlier, even though every actual file matches.
    reason = 'LOADED_SOURCE_BYTES' if extra_entry else 'SOURCE_ORIGIN'
    binding = models.NativeBinding(candidate,image,'/polar-launch/preparation.json',str(tmp_path/'unused-defaults'))
    with pytest.raises(models.FamilyUnavailable, match='^'+reason+'$'):
        binding.verify()

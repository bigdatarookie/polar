"""Actual isolated git controls; never invoke a scientific engine."""
from pathlib import Path
import subprocess

import pytest

from polar import candidate_binding
from polar.research_results import ResearchError


def test_loaded_checkout_rejects_wrong_worker_dirty_and_untracked_source(tmp_path, monkeypatch):
    source = tmp_path/'src/polar/candidate_binding.py'
    source.parent.mkdir(parents=True)
    source.write_text('# invented candidate control\n')
    def git(*args):
        return subprocess.check_output(['git', '-C', str(tmp_path), *args], text=True).strip()
    git('init', '-q'); git('add', '.')
    git('-c', 'user.name=Invented Control', '-c', 'user.email=invented@example.invalid',
        'commit', '-qm', 'Invented source')
    monkeypatch.setattr(candidate_binding, '__file__', str(source))
    expected = git('rev-parse', 'HEAD')
    assert candidate_binding.loaded_revision() == expected
    candidate_binding.verify_candidate({'namespace': 'RETAINED', 'code_revision': expected})
    with pytest.raises(ResearchError, match='REVISION_MISMATCH'):
        candidate_binding.verify_candidate({'namespace': 'RETAINED', 'code_revision': '0'*40})
    source.write_text('# changed candidate\n')
    with pytest.raises(ResearchError, match='CHECKOUT_UNVERIFIED'):
        candidate_binding.loaded_revision()
    git('checkout', '--', '.')
    (source.parent/'shadow.py').write_text('# untracked import\n')
    with pytest.raises(ResearchError, match='CHECKOUT_UNVERIFIED'):
        candidate_binding.loaded_revision()


def test_registered_external_policy_dirtiness_rejected(tmp_path, monkeypatch):
    source = tmp_path/'src/polar/candidate_binding.py'
    source.parent.mkdir(parents=True)
    source.write_text('# invented loaded source\n')
    policy = tmp_path/'research_candidates/quant_a_drawdown_gate/policy.py'
    policy.parent.mkdir(parents=True); policy.write_text('# invented registered policy\n')
    def git(*args):
        return subprocess.check_output(['git', '-C', str(tmp_path), *args], text=True).strip()
    git('init', '-q'); git('add', '.')
    git('-c', 'user.name=Invented Control', '-c', 'user.email=invented@example.invalid', 'commit', '-qm', 'Invented policy')
    monkeypatch.setattr(candidate_binding, '__file__', str(source))
    assert candidate_binding.loaded_revision() == git('rev-parse', 'HEAD')
    policy.write_text('# changed external candidate\n')
    with pytest.raises(ResearchError, match='CHECKOUT_UNVERIFIED'):candidate_binding.loaded_revision()
    git('checkout', '--', '.')
    (policy.parent/'shadow.py').write_text('# untracked external import\n')
    with pytest.raises(ResearchError, match='CHECKOUT_UNVERIFIED'):candidate_binding.loaded_revision()

"""Bind retained execution to the clean checkout containing the loaded module.

No checkout, build, dynamic import or execution occurs here. Authors invoke the
existing CLI inside their isolated exact candidate and accepted runtime image.
"""
from pathlib import Path
import re
import subprocess

from .research_results import ResearchError


def loaded_revision():
    source = Path(__file__).resolve()
    root = source.parents[2]
    try:
        def git(*args):
            return subprocess.check_output(['git', '-C', str(root), *args],
                stderr=subprocess.DEVNULL, text=True, timeout=10).strip()
        if Path(git('rev-parse', '--show-toplevel')).resolve() != root:
            raise ValueError()
        revision = git('rev-parse', 'HEAD')
        if not re.fullmatch('[a-f0-9]{40}', revision):
            raise ValueError()
        # Tracked changes and untracked Python modules can both change imports.
        if git('status', '--porcelain', '--untracked-files=all', '--', 'src/polar', 'pyproject.toml', 'requirements.lock'):
            raise ValueError()
        tracked = git('ls-files', '--error-unmatch', str(source.relative_to(root)))
        if tracked != str(source.relative_to(root)):
            raise ValueError()
        return revision
    except (OSError, ValueError, subprocess.SubprocessError):
        raise ResearchError('RESEARCH_CANDIDATE_CHECKOUT_UNVERIFIED', 409) from None


def verify_candidate(config):
    if config.get('namespace') == 'RETAINED' and config.get('code_revision') != loaded_revision():
        raise ResearchError('RESEARCH_CANDIDATE_REVISION_MISMATCH', 409)

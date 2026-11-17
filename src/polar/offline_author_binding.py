"""Automatic offline execution intent; never a permission or scientific verdict."""
import os
import platform

from .candidate_binding import loaded_revision
from .gym_contract import canonical, sha
from .research_results import ResearchError


def create(config, profile, grids):
    from .scheduled_service import account_count, binding
    if config.get('namespace') != 'RETAINED' or config.get('schema') != 'polar.scheduled-reference-config/1':
        raise ResearchError('RESEARCH_OFFLINE_AUTHOR_BINDING_UNSUPPORTED', 422)
    candidate = loaded_revision()
    if config.get('code_revision') != candidate:
        raise ResearchError('RESEARCH_CANDIDATE_REVISION_MISMATCH', 409)
    runtime = os.environ.get('POLAR_RUNTIME_IMAGE_ID')
    if not runtime or runtime != config.get('runtime_image_id'):
        raise ResearchError('RESEARCH_OFFLINE_AUTHOR_RUNTIME_MISMATCH', 409)
    # prepare() has already checked actual platform/Python/dependencies, every
    # content pin, source rights and frozen profile before this binding or debit.
    return {'schema': 'polar.offline-author-binding/1', 'action': 'ORIGINAL',
            'binding_sha256': sha(canonical(binding(config))),
            'candidate_sha': candidate, 'config_sha256': sha(canonical(binding(config))),
            'data_revision': config['input_ref']['sha256'], 'runtime_image_id': runtime,
            'python_version': platform.python_version(), 'platform': platform.system(),
            'runtime_provenance': 'RUN_CONTEXT_WITH_CHECKED_PROFILE_DEPENDENCIES',
            'expected_native_accounts': account_count(profile, grids),
            'expected_prior_attempts': [], 'scientific_acceptance': 'NOT_REVIEWED'}

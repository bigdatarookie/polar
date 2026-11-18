"""Automatic offline execution intent; never a permission or scientific verdict."""
import os
import platform
import re

from .candidate_binding import loaded_revision
from .gym_contract import canonical, sha
from .research_results import ResearchError


def create(config, profile, grids):
    from .scheduled_service import account_count, binding
    if config.get('namespace') != 'RETAINED' or config.get('schema') not in ('polar.scheduled-reference-config/1','polar.band-reference-config/1'):
        raise ResearchError('RESEARCH_OFFLINE_AUTHOR_BINDING_UNSUPPORTED', 422)
    if config.get('schema')=='polar.band-reference-config/1' and profile.get('schema')!='polar.scheduled-reference-profile/17':
        raise ResearchError('RESEARCH_OFFLINE_AUTHOR_BINDING_UNSUPPORTED',422)
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
            'data_content_sha256': config['input_ref']['sha256'], 'runtime_image_id': runtime,
            'python_version': platform.python_version(), 'platform': platform.system(),
            'runtime_provenance': 'RUN_CONTEXT_WITH_CHECKED_PROFILE_DEPENDENCIES',
            'expected_native_accounts': account_count(profile, grids),
            'expected_prior_attempts': [], 'scientific_acceptance': 'NOT_REVIEWED'}


def pair_runtime(namespace):
    """Observed image identity; CI's image label is only an invented-test route."""
    runtime = os.environ.get('POLAR_RUNTIME_IMAGE_ID')
    if namespace == 'INVENTED' and runtime is None:
        runtime = os.environ.get('POLAR_CI_RUNTIME_IMAGE_ID')
    if not runtime or not re.fullmatch(r'sha256:[a-f0-9]{64}', runtime):
        raise ResearchError('RESEARCH_OFFLINE_AUTHOR_RUNTIME_MISMATCH', 409)
    return runtime


def create_pair(config, input_binding, *, prior=None, original_run_id=None, run_id=None):
    """Intent for the existing closed pair operation, after full preparation.

    Source/method/resource/registry checks remain with prepare(). An explicit
    legacy grant never enters this route. SAVED inherits only a successful
    automatic ORIGINAL and still passes its separate existing charge/limits.
    """
    from .signed_pair_operation import CONFIG, MERGED, binding, family
    if (config.get('schema') != CONFIG or config.get('namespace') not in ('INVENTED', 'RETAINED')
            or config.get('stage') not in ('ORIGINAL', 'SAVED') or config.get('authority_ref') is not None):
        raise ResearchError('RESEARCH_OFFLINE_AUTHOR_BINDING_UNSUPPORTED', 422)
    candidate = loaded_revision()
    if config.get('code_revision') != candidate:
        raise ResearchError('RESEARCH_CANDIDATE_REVISION_MISMATCH', 409)
    runtime = pair_runtime(config['namespace'])
    if runtime != config.get('runtime_image_id'):
        raise ResearchError('RESEARCH_OFFLINE_AUTHOR_RUNTIME_MISMATCH', 409)
    common = {'namespace': config['namespace'], 'candidate_id': config['candidate_id'],
              'experiment_id': config['experiment_id'], 'candidate_sha': candidate,
              'protocol_sha256': MERGED, 'family': family(config),
              'data_content_sha256': input_binding['input_content_sha256'],
              'selection_sha256': config['selection_ref']['sha256'],
              'method_sha256': config['method_ref']['sha256'],
              'custody_sha256': config['custody_ref']['sha256'],
              'runtime_image_id': runtime, 'artifact_root_identity': config['artifact_root_identity']}
    if config['stage'] == 'SAVED':
        if (not isinstance(prior, dict) or prior.get('schema') != 'polar.offline-pair-author-binding/1'
                or prior.get('action') != 'ORIGINAL' or not original_run_id
                or prior.get('run_id') != original_run_id
                or any(prior.get(k) != v for k, v in common.items())):
            raise ResearchError('RESEARCH_OFFLINE_PAIR_SAVED_LINEAGE_REQUIRED', 409)
    return {'schema': 'polar.offline-pair-author-binding/1', **common,
            'action': config['stage'], 'run_id': run_id, 'original_run_id': original_run_id,
            'config_sha256': sha(canonical(binding(config))),
            'resources_sha256': config['resources_ref']['sha256'],
            'method_sha256': config['method_ref']['sha256'],
            'custody_sha256': config['custody_ref']['sha256'],
            'source_manifest_sha256': (config['source_manifest_ref']['sha256']
                                       if config['stage'] == 'ORIGINAL' else None),
            'python_version': platform.python_version(), 'platform': platform.system(),
            'actor_uid': os.getuid(), 'actor_gid': os.getgid(),
            'expected_native_accounts': 48 if config['stage'] == 'ORIGINAL' else 0,
            'expected_saved_verifications': 1, 'execution_intent_only': True,
            'scientific_acceptance': 'NOT_REVIEWED'}

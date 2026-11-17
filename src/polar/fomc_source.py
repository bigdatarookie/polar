"""Address-only current native custody for the new closed FOMC source scope."""
import re
import os, platform, sys
from .ci_research import require
from .gym_contract import decode
from .history_bundle import canonical, sha
from .native_selected_input import consumer_custody, live_generation, current_queue


def scope(config):
    return {k: v for k, v in config.items() if k != 'source_admission_ref'}


def actual_runtime(config):
    from .offline_author_binding import pair_runtime
    require(platform.system() == 'Linux' and platform.python_version() == '3.13.18' and
            os.getuid() == 10001 and sys.pycache_prefix is not None and
            os.environ.get('PYTHONDONTWRITEBYTECODE') == '1' and
            pair_runtime('RETAINED') == config.get('runtime_image_id'), 'FOMC_SOURCE_ACTUAL_RUNTIME')


def authorize(config, root, *, queue=None):
    from .candidate_binding import loaded_revision
    from .ci_research_service import root_identity
    from .gym_service import code_binding
    from .fomc_calendar import QUESTION
    require(config.get('schema') in ('polar.fomc-calendar-config/1', 'polar.reference-input-conversion-config/10') and
            config.get('question_id') == QUESTION and config.get('namespace') == 'RETAINED' and
            config.get('artifact_root_identity') == root_identity(root) and
            config.get('code_revision') == loaded_revision() and config.get('code') == code_binding(),
            'FOMC_NATIVE_SOURCE_SCOPE')
    actual_runtime(config)
    queue = queue or current_queue()
    actor, generation, task = consumer_custody(config['consumer_task'], queue=queue)
    ref = config['source_admission_ref']
    require(type(ref) is str and re.fullmatch(r'qitem-[A-Za-z0-9_.:-]+#[1-9][0-9]*', ref),
            'FOMC_NATIVE_SOURCE_ADMISSION_REQUIRED')
    qid, transition = ref.rsplit('#', 1); transition = int(transition)
    row = queue.read('queue', 'show', qid, '--full')
    events = queue.read('queue', 'transitions', qid, '--full')
    closing = [x for x in events if x.get('transitionId') == transition]
    require(row.get('state') == 'done' and row.get('destinationSession') == actor and
            row.get('claimedByGeneration') == generation and
            row.get('closingTransition', {}).get('transitionId') == transition and len(closing) == 1 and
            closing[0].get('state') == 'done' and closing[0].get('actorSession') == actor and
            closing[0].get('identityProvenance') == 'transport:v1', 'FOMC_NATIVE_SOURCE_ADMISSION')
    try:
        decision = decode(row['resolution'])
    except (ValueError, TypeError, KeyError):
        require(False, 'FOMC_NATIVE_SOURCE_DECISION')
    require(decision == {'schema': 'polar.fomc-source-admission/1', 'status': 'ADMITTED_WITH_LIMITS',
            'consumer_task': config['consumer_task'], 'claimed_generation': generation,
            'scope_sha256': sha(canonical(scope(config))), 'symbols': ['BIL', 'VTI'],
            'scientific_verdict': 'NOT_REVIEWED'}, 'FOMC_NATIVE_SOURCE_BINDING')
    for q, original in [(config['consumer_task'], task), (qid, row)]:
        current = queue.read('queue', 'show', q, '--full')
        require(all(current.get(k) == original.get(k) for k in ('state', 'destinationSession',
                'claimedByGeneration', 'claimedAt', 'closingTransition', 'resolution')), 'FOMC_NATIVE_CUSTODY_CHANGED')
    require(live_generation(queue, actor) == generation, 'FOMC_NATIVE_CUSTODY_CHANGED')
    return {'actor': actor, 'generation': generation, 'source_admission_ref': ref,
            'scope_sha256': sha(canonical(scope(config)))}


SOURCE_SCHEMA = 'polar.reference-input-conversion-config/10'
SOURCE_PROFILE = 'FOMC-CALENDAR-SELECTED-INPUT-V1'
SOURCE_FIELDS = {'schema', 'profile_id', 'namespace', 'question_id', 'candidate_id', 'experiment_id',
                 'code', 'code_revision', 'runtime_image_id', 'artifact_root_identity', 'consumer_task',
                 'source_admission_ref', 'spec_ref', 'contract_ref', 'protocol_ref', 'method_ref'}


def prepare_source_input(config, root, limit, *, queue=None):
    from .gym_contract import read_ref
    from .fomc_calendar import author_policy, QUESTION, CONTRACT_SHA, PROPOSAL_SHA, POLICY_SHA
    from .offline_author_binding import pair_runtime
    from .ci_research_service import root_identity
    from .gym_service import code_binding
    require(type(config) is dict and set(config) == SOURCE_FIELDS and config['schema'] == SOURCE_SCHEMA and
            config['profile_id'] == SOURCE_PROFILE and config['question_id'] == QUESTION and
            config['namespace'] in ('INVENTED', 'RETAINED'), 'FOMC_SELECTED_INPUT_CONFIG')
    require(config['code'] == code_binding() and config['artifact_root_identity'] == root_identity(root) and
            config['runtime_image_id'] == pair_runtime(config['namespace']), 'FOMC_SELECTED_CURRENT_BINDING')
    if config['namespace'] == 'RETAINED':
        proof = authorize(config, root, queue=queue)
    else:
        require(config['candidate_id'].startswith('INVENTED') and config['source_admission_ref'] is None,
                'FOMC_SELECTED_INVENTED_NAMESPACE')
        proof = {'status': 'INVENTED_TEST_ONLY', 'scope_sha256': sha(canonical(scope(config)))}
    require(sha(read_ref(config['contract_ref'])) == CONTRACT_SHA and
            sha(read_ref(config['protocol_ref'])) == PROPOSAL_SHA, 'FOMC_SELECTED_METHOD_PINS')
    author_policy()
    method = decode(read_ref(config['method_ref']))
    require(method.get('question_id') == QUESTION and method.get('policy_sha256') == POLICY_SHA and
            method.get('status') == 'ACCEPTED_WITH_LIMITS' and method.get('namespace') == config['namespace'],
            'FOMC_SELECTED_METHOD')
    spec = decode(read_ref(config['spec_ref']))
    require(spec['namespace'] == config['namespace'], 'FOMC_SELECTED_SPEC_NAMESPACE')
    wanted = [r['symbol'] for r in spec['leaf_inputs']+spec['normalized_inputs']]
    require(sorted(wanted) == ['BIL', 'VTI'], 'FOMC_SELECTED_SYMBOL_SCOPE')
    from .selected_component_input import prepare_selected_components
    return prepare_selected_components(spec, root, limit, source_binding={**proof, 'config': config})


def prepared_authorization(manifest, *, queue=None):
    metadata = manifest.get('conversion_metadata', manifest.get('provenance', {}))
    if metadata.get('converter') != 'polar.selected-component-materializer/1':
        return None
    proof = metadata.get('source_native_binding', {})
    config = proof.get('config')
    if not isinstance(config, dict) or config.get('schema') != SOURCE_SCHEMA:
        return None  # Generic invented materializer is not a FOMC source claim.
    from .fomc_calendar import QUESTION
    from .gym_service import code_binding
    from .ci_research_service import root_identity
    from .offline_author_binding import pair_runtime
    require(config.get('question_id') == QUESTION and config.get('code') == code_binding() and manifest['symbols'] == ['BIL', 'VTI'] and
            metadata.get('private_root') == config['artifact_root_identity']['path'] and
            root_identity(__import__('pathlib').Path(config['artifact_root_identity']['path'])) == config['artifact_root_identity'] and
            config['runtime_image_id'] == pair_runtime(config['namespace']), 'FOMC_PREPARED_SOURCE_BINDING')
    current = authorize(config, __import__('pathlib').Path(config['artifact_root_identity']['path']), queue=queue) if config['namespace'] == 'RETAINED' else None
    from .gym_contract import read_ref
    spec = decode(read_ref(config['spec_ref']))
    require(metadata.get('spec') == spec and manifest['dates'] == spec['date_range'] and
            metadata.get('parent_schedule') == spec['schedule'] and
            sorted(x['symbol'] for x in spec['leaf_inputs']+spec['normalized_inputs']) == ['BIL', 'VTI'],
            'FOMC_PREPARED_SPEC_BINDING')
    if config['namespace'] == 'RETAINED':
        require(all(proof.get(k) == current.get(k) for k in current), 'FOMC_PREPARED_NATIVE_PROVENANCE')
        return current
    require(manifest['rights'] == 'INVENTED_PUBLIC_TEST', 'FOMC_PREPARED_INVENTED_NAMESPACE')
    return proof


def validate_prepared_input(config, manifest, root):
    metadata = manifest.get('conversion_metadata', manifest.get('provenance', {}))
    require(metadata.get('converter') == 'polar.selected-component-materializer/1', 'FOMC_SELECTED_SOURCE_REQUIRED')
    source = metadata.get('source_native_binding', {}).get('config', {})
    require(source.get('schema') == SOURCE_SCHEMA and all(source.get(k) == config[k] for k in
            ('namespace', 'question_id', 'code', 'code_revision', 'runtime_image_id', 'artifact_root_identity',
             'consumer_task', 'contract_ref', 'protocol_ref', 'method_ref')), 'FOMC_PREPARED_EXECUTION_SCOPE')
    return prepared_authorization(manifest)

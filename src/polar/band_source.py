"""Closed Band source preparation and durable producer provenance.

No source-admission grant, policy evaluation, provider request or financial
operation. The existing selected-component reader remains the only normalizer.
"""
from pathlib import Path
import os
import platform
import re
import sys

from .ci_research import require
from .gym_contract import decode, read_ref
from .history_bundle import canonical, sha
from .research_native_review import current_queue

SOURCE_SCHEMA = 'polar.reference-input-conversion-config/11'
SOURCE_PROFILE = 'BAND-SELECTED-INPUT-V1'
DR_FIT_SHA = 'd7c926a63d4370bb510406b57bad8aece82c2024c1c30510defa581f32e8cd6d'
VTI_PARENT_SHA = '4729427820455eaa87c774cb51a9e4dbe2694db06a08b2b8955f02f2c620876a'
SOURCE_FIELDS = {'schema', 'profile_id', 'namespace', 'question_id', 'candidate_id', 'experiment_id',
                 'code', 'code_revision', 'runtime_image_id', 'artifact_root_identity', 'consumer_task',
                 'actor_session', 'spec_ref', 'contract_ref', 'protocol_ref', 'source_fit_ref'}
ACTORS = {'quant-a@polar-rig': ('polar-rig', 'quant.a'),
          'engineering-data@engineering-rig': ('engineering-rig', 'engineering.data')}
TAGS = {'project:polar', 'mission:03-competitive-strategies', 'slice:vti-bil-no-trade-band'}
TASK_FIELDS = ('qitemId', 'state', 'destinationSession', 'claimedByGeneration', 'claimedAt',
               'closureReason', 'closureTarget', 'handedOffTo', 'tags', 'resolution')


def method_binding():
    from .band_contract import QUESTION, CONTRACT_SHA, PROTOCOL_SHA, AUTHOR_CANDIDATE, policy_binding
    policy_binding()
    return QUESTION, CONTRACT_SHA, PROTOCOL_SHA, AUTHOR_CANDIDATE


def generation_read(actor, *, actors=ACTORS):
    require(actor in actors, 'BAND_SOURCE_ACTOR')
    return ('ps', '--nodes', '--rig', actors[actor][0], '--session', actor, '--fields',
            'rigName,logicalId,canonicalSessionName,sessionStatus,agentActivity')


def live_generation(queue, actor, *, actors=ACTORS):
    if actor == 'quant-a@polar-rig':
        from .native_selected_input import live_generation as quant_generation
        return quant_generation(queue, actor)
    snapshot = queue.read(*generation_read(actor, actors=actors))
    rows = snapshot.get('entries') if isinstance(snapshot, dict) else snapshot
    require(type(rows) is list and len(rows) == 1, 'BAND_SOURCE_GENERATION')
    row = rows[0]; activity = row.get('agentActivity', {})
    require(row.get('rigName') == actors[actor][0] and row.get('logicalId') == actors[actor][1] and
            row.get('canonicalSessionName') == actor and row.get('sessionStatus') == 'running' and
            activity.get('generationProvenance') == 'resolved' and
            activity.get('evidenceSource') in ('native_owner', 'runtime_hook') and
            activity.get('stale') is not True and activity.get('fallback') is not True and
            type(activity.get('generation')) is str and bool(activity['generation']), 'BAND_SOURCE_GENERATION')
    return activity['generation']


def current_actor(queue, *, actors=ACTORS):
    identity = queue.read('whoami').get('identity', {})
    actor = identity.get('sessionName')
    require(actor in actors and bool(identity.get('nodeId')) and
            (identity.get('rigName'), identity.get('logicalId')) == actors[actor], 'BAND_SOURCE_ACTOR')
    seat = queue.read('seat', 'status', actor)
    require(seat.get('current_occupant') == actor and
            (seat.get('rig_name'), seat.get('logical_id')) == actors[actor], 'BAND_SOURCE_ACTOR')
    return actor, live_generation(queue, actor, actors=actors)


def task_custody(config, queue, *, prior=None, terminal_result=None, require_terminal=False,
                 actors=ACTORS, tags=TAGS, dispatcher=None, terminal_readers=('quant-a@polar-rig',),
                 terminal_targets=('engineering-platform@engineering-rig', 'quant-a@polar-rig')):
    """A current producer claim, or its unchanged native terminal provenance.

    Terminal custody does not authorize finance or a new source operation. A
    later Quant consumer must pass its own service's current execution binding.
    """
    actor, current = current_actor(queue, actors=actors)
    producer = config['actor_session']; task_id = config['consumer_task']
    require(actor == producer or (prior is not None and actor in terminal_readers),
            'BAND_SOURCE_ACTOR')
    row = queue.read('queue', 'show', task_id, '--full')
    require(row.get('qitemId') == task_id and row.get('destinationSession') == producer and
            row.get('claimedByGeneration') and tags <= set(row.get('tags', [])) and
            (dispatcher is None or row.get('sourceSession') == dispatcher), 'BAND_SOURCE_CURRENT_TASK')
    events = queue.read('queue', 'transitions', task_id, '--full')
    claims = [e for e in events if e.get('state') == 'in-progress' and e.get('transitionNote') == 'claimed']
    require(bool(claims), 'BAND_SOURCE_CLAIM')
    claim = max(claims, key=lambda e: e['transitionId'])
    require(claim.get('actorSession') == producer and claim.get('identityProvenance') == 'transport:v1',
            'BAND_SOURCE_CLAIM')
    if row.get('state') == 'in-progress':
        require(not require_terminal, 'BAND_SOURCE_TERMINAL_CUSTODY')
        require(actor == producer and row['claimedByGeneration'] == current, 'BAND_SOURCE_GENERATION')
    else:
        require(terminal_result is not None and prior is not None and row.get('state') == 'done' and
                row.get('closureReason') in ('handed_off_to', 'no-follow-on'), 'BAND_SOURCE_TERMINAL_CUSTODY')
        if row['closureReason'] == 'handed_off_to':
            require(row.get('handedOffTo') in terminal_targets,
                    'BAND_SOURCE_TERMINAL_CUSTODY')
        terminals = [e for e in events if e.get('state') == 'done']
        require(bool(terminals), 'BAND_SOURCE_TERMINAL_CUSTODY')
        closing = max(terminals, key=lambda e: e['transitionId'])
        require(closing['transitionId'] > claim['transitionId'] and closing.get('actorSession') == producer and
                closing.get('identityProvenance') == 'transport:v1', 'BAND_SOURCE_TERMINAL_CUSTODY')
        try:
            resolution = decode(row['resolution'])
        except (KeyError, ValueError, TypeError):
            require(False, 'BAND_SOURCE_TERMINAL_RESULT')
        require(resolution == terminal_result, 'BAND_SOURCE_TERMINAL_RESULT')
    proof = {'actor': producer, 'generation': row['claimedByGeneration'],
             'consumer_task': task_id, 'claim_transition': claim['transitionId'],
             'claimed_at': row.get('claimedAt'),
             'scope_sha256': sha(canonical(config))}
    require(prior is None or all(prior.get(k) == v for k, v in proof.items()), 'BAND_SOURCE_PRODUCER_BINDING')
    again = queue.read('queue', 'show', task_id, '--full')
    require(all(again.get(k) == row.get(k) for k in TASK_FIELDS) and
            live_generation(queue, actor, actors=actors) == current, 'BAND_SOURCE_CUSTODY_CHANGED')
    return proof


def actual_runtime(config):
    from .offline_author_binding import pair_runtime
    require(pair_runtime(config['namespace']) == config['runtime_image_id'], 'BAND_SOURCE_RUNTIME')
    if config['namespace'] == 'RETAINED':
        require(platform.system() == 'Linux' and platform.python_version() == '3.13.18' and
                os.getuid() == 10001 and sys.pycache_prefix is not None and
                os.environ.get('PYTHONDONTWRITEBYTECODE') == '1', 'BAND_SOURCE_RUNTIME')


def current_binding(config, root, *, historical=False):
    from .candidate_binding import loaded_revision
    from .ci_research_service import root_identity
    from .gym_service import code_binding
    question, _, _, _ = method_binding()
    require(type(config) is dict and set(config) == SOURCE_FIELDS and config['schema'] == SOURCE_SCHEMA and
            config['profile_id'] == SOURCE_PROFILE and config['question_id'] == question and
            config['namespace'] in ('INVENTED', 'RETAINED') and config['actor_session'] in ACTORS and
            type(config['consumer_task']) is str and re.fullmatch(r'qitem-[A-Za-z0-9_.:-]+', config['consumer_task']) and
            all(type(config[k]) is str and re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', config[k])
                for k in ('candidate_id', 'experiment_id')), 'BAND_SOURCE_CONFIG')
    require(Path(root).is_absolute() and Path(root).resolve() == Path(root) and
            config['artifact_root_identity'] == root_identity(root), 'BAND_SOURCE_CURRENT_BINDING')
    if historical:
        # Producer build/runtime stay immutable; the current financial build is
        # checked separately. Only a native terminal result can enter here.
        require(type(config['code']) is dict and
                {'band_source.py', 'selected_component_input.py'} <= set(config['code']) and
                all(type(k) is str and type(v) is str and re.fullmatch('[a-f0-9]{64}', v)
                    for k, v in config['code'].items()) and
                re.fullmatch('[a-f0-9]{40}', config['code_revision']) and
                re.fullmatch('sha256:[a-f0-9]{64}', config['runtime_image_id']), 'BAND_SOURCE_PRODUCER_BUILD')
    else:
        require(config['code'] == code_binding() and config['code_revision'] == loaded_revision(),
                'BAND_SOURCE_CURRENT_BINDING')
        actual_runtime(config)


def authorize(config, root, *, queue=None, prior=None, terminal_result=None, historical=False):
    # No caller-selected private ref or member is opened before these checks.
    require(not historical or (prior is not None and terminal_result is not None), 'BAND_SOURCE_PRODUCER_BINDING')
    current_binding(config, root, historical=historical)
    if config['namespace'] == 'INVENTED':
        require(config['candidate_id'].startswith('INVENTED') and config['consumer_task'].startswith('qitem-INVENTED'),
                'BAND_SOURCE_INVENTED_SCOPE')
        proof = {'status': 'INVENTED_TEST_ONLY', 'scope_sha256': sha(canonical(config))}
        require(prior is None or all(prior.get(k) == v for k, v in proof.items()), 'BAND_SOURCE_PRODUCER_BINDING')
        return proof
    return task_custody(config, queue or current_queue(), prior=prior, terminal_result=terminal_result,
                        require_terminal=historical)


def checked_spec(config, *, read=None):
    """Question-specific source metadata contract; never a substitute grant."""
    read = read or read_ref
    question, contract, protocol, candidate = method_binding()
    require(config['contract_ref'].get('sha256') == contract and
            config['protocol_ref'].get('sha256') == protocol, 'BAND_SOURCE_METHOD_PINS')
    require(sha(read(config['contract_ref'])) == contract and sha(read(config['protocol_ref'])) == protocol,
            'BAND_SOURCE_METHOD_PINS')
    if config['namespace'] == 'RETAINED':
        require(config['source_fit_ref'].get('sha256') == DR_FIT_SHA, 'BAND_SOURCE_FIT_PIN')
    fit_raw = read(config['source_fit_ref'])
    fit = decode(fit_raw)
    require(sha(fit_raw) == DR_FIT_SHA if config['namespace'] == 'RETAINED' else
            fit == {'schema': 'polar.band-invented-source-fit/1', 'namespace': 'INVENTED',
                    'source_payloads': 'NONE'}, 'BAND_SOURCE_FIT_PIN')
    spec = decode(read(config['spec_ref']))
    require(spec.get('schema') == 'polar.selected-component-materialization/1' and
            spec.get('namespace') == config['namespace'], 'BAND_SOURCE_SPEC')
    require(len(spec.get('leaf_inputs', [])) == len(spec.get('normalized_inputs', [])) == 1 and
            spec['leaf_inputs'][0].get('symbol') == 'BIL' and spec['normalized_inputs'][0].get('symbol') == 'VTI',
            'BAND_SOURCE_SPEC_SYMBOLS')
    purpose = decode(read(spec['purpose_ref']))
    from .selected_reference_input import RIGHTS
    require(purpose.get('schema') == 'polar.band-selected-source-purpose-metadata/1' and
            purpose.get('question_id') == question and purpose.get('candidate_revision') == candidate and
            purpose.get('author_contract') == config['contract_ref'] and purpose.get('protocol') == config['protocol_ref'] and
            purpose.get('DR_fit') == config['source_fit_ref'] and purpose.get('symbols') == ['BIL', 'VTI'] and
            purpose.get('rights') == (RIGHTS if config['namespace'] == 'RETAINED' else 'INVENTED_PUBLIC_TEST') and
            purpose.get('reference_schedule') == spec['schedule'] and
            purpose.get('intended_reference_domain_private') == spec['date_range'] and
            purpose.get('source_qualification_refs') == spec['qualification_refs'] and
            config['source_fit_ref'] in spec['qualification_refs'], 'BAND_SOURCE_PURPOSE')
    if config['namespace'] == 'RETAINED':
        bil = next(p for p in fit['inputs']['BIL']['pins'] if Path(p['path']).name == 'manifest.json')
        vti = next(p for p in fit['inputs']['VTI']['pins'] if Path(p['path']).name == 'selected-source-binding-v1.json')
        require(spec['leaf_inputs'][0]['input_ref'] == bil and spec['normalized_inputs'][0]['binding_ref'] == vti and
                spec['normalized_inputs'][0]['input_ref']['sha256'] == VTI_PARENT_SHA,
                'BAND_SOURCE_RETAINED_COMPONENTS')
        from .research_reference import reference_schedule
        _, days = reference_schedule(decode(read(spec['schedule'])))
        phases = fit['phase_geometry']
        first = min(p['startup_formation_session'] for p in phases)
        last = max(p['last_session'] for p in phases)
        require(purpose.get('phase_geometry_private') == phases and
                spec['date_range'] == {'start': first, 'end': last,
                                       'count': sum(first <= d <= last for d in days)},
                'BAND_SOURCE_FROZEN_DOMAIN')
    return spec


def prepare_source_input(config, root, limit, *, queue=None):
    proof = authorize(config, root, queue=queue)
    spec = checked_spec(config)
    from .selected_component_input import prepare_selected_components
    result = prepare_selected_components(spec, root, limit, source_binding={**proof, 'config': config})
    # A concurrent reassign/close fails acceptance; it cannot mint a stale input.
    authorize(config, root, queue=queue, prior=proof)
    manifest = decode(read_ref(result['input_ref']))
    return {**result, 'producer_terminal_result': producer_result(config, manifest)}


def producer_result(config, manifest):
    """Ordinary typed source task result, never a permission/admission decision.

    Before terminal consumption, the producer closes its real source task with
    this exact result. This binds completion to the returned immutable input;
    a task closing concurrently with preparation cannot endorse other output.
    """
    return {'schema': 'polar.band-source-result/1', 'status': 'SOURCE_ONLY_PREPARED_WITH_LIMITS',
            'consumer_task': config['consumer_task'], 'scope_sha256': sha(canonical(config)),
            'spec_sha256': config['spec_ref']['sha256'],
            'input_manifest_sha256': sha(canonical(manifest)),
            'source_revision': manifest['parent_dataset_revision']}


def prepared_authorization(manifest, *, queue=None, reconciliation_ref=None):
    if reconciliation_ref is not None:
        from .band_reconciliation import authorize_existing
        return authorize_existing(manifest, reconciliation_ref, queue=queue)
    metadata = manifest.get('conversion_metadata', manifest.get('provenance', {}))
    proof = metadata.get('source_native_binding', {})
    config = proof.get('config')
    if not isinstance(config, dict) or config.get('schema') != SOURCE_SCHEMA:
        return None
    root = Path(config['artifact_root_identity']['path'])
    authorize(config, root, queue=queue, prior=proof, terminal_result=producer_result(config, manifest),
              historical=config['namespace'] == 'RETAINED')
    spec = checked_spec(config)
    require(metadata.get('converter') == 'polar.selected-component-materializer/1' and
            metadata.get('private_root') == str(root) and metadata.get('spec') == spec and
            manifest.get('symbols') == ['BIL', 'VTI'] and manifest.get('dates') == spec['date_range'] and
            metadata.get('parent_schedule') == spec['schedule'] and
            Path(manifest['quotes']['path']).is_relative_to(root/'reference-inputs'),
            'BAND_PREPARED_SOURCE_BINDING')
    return proof


def authorize_financial(config, profile, manifest, root, *, queue=None):
    """Current Quant consumer check, independent of the terminal source build.

    This supplies neither finance resource fit nor a financial grant. Existing
    native account, method, first-start and saved-result checks remain required.
    """
    from .candidate_binding import loaded_revision
    from .ci_research_service import root_identity
    from .gym_service import code_binding
    from .native_selected_input import consumer_custody
    question, contract, protocol, _ = method_binding()
    require(config.get('schema') == 'polar.band-reference-config/1' and config.get('namespace') == 'RETAINED' and
            config.get('execution_authority_ref') is None and
            profile.get('schema') == 'polar.scheduled-reference-profile/17' and
            profile.get('protocol_id') == question and profile.get('protocol_sha256') == protocol and
            profile.get('policy', {}).get('contract_sha256') == contract, 'BAND_FINANCIAL_SCOPE')
    require(config.get('artifact_root_identity') == root_identity(root) and
            config.get('code') == code_binding() and config.get('code_revision') == loaded_revision(),
            'BAND_FINANCIAL_CURRENT_BINDING')
    actual_runtime(config)
    queue = queue or current_queue()
    actor, generation, task = consumer_custody(config['consumer_task'], queue=queue)
    require(TAGS <= set(task.get('tags', [])), 'BAND_FINANCIAL_CURRENT_TASK')
    source = manifest.get('provenance', {}).get('source_native_binding', {}).get('config', {})
    require(source.get('schema') == SOURCE_SCHEMA and source.get('namespace') == 'RETAINED' and
            source.get('question_id') == question and
            source.get('artifact_root_identity') == config['artifact_root_identity'] and
            source.get('protocol_ref', {}).get('sha256') == protocol and
            source.get('contract_ref', {}).get('sha256') == contract and
            sha(read_ref(config['protocol_ref'])) == protocol, 'BAND_FINANCIAL_SOURCE_BINDING')
    reference = config.get('input_ref', {}).get('reconciliation_ref')
    proof = prepared_authorization(manifest, queue=queue, **(
        {'reconciliation_ref': reference} if reference is not None else {}))
    require(proof is not None, 'BAND_FINANCIAL_SOURCE_BINDING')
    again = consumer_custody(config['consumer_task'], queue=queue)
    require(again[:2] == (actor, generation) and
            all(again[2].get(k) == task.get(k) for k in TASK_FIELDS), 'BAND_FINANCIAL_CUSTODY_CHANGED')
    return {'actor': actor, 'generation': generation, 'consumer_task': config['consumer_task'],
            'source_producer': proof, 'consumer_config_sha256': sha(canonical(config)),
            'financial_permission_or_verdict': 'NOT_ISSUED'}

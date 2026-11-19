"""Native source-only input for the frozen IEF/BIL monthly question."""
from datetime import datetime, timedelta
from pathlib import Path

from .band_source import actual_runtime, task_custody
from .ci_research import require
from .history_bundle import canonical, sha
from .research_native_review import current_queue
from .research_reference import decode, pinned_bytes, reference_schedule
from .selected_reference_input import RIGHTS

SOURCE_SCHEMA = 'polar.reference-input-conversion-config/12'
MANIFEST_SCHEMA = 'polar.ief-bil-month-end-source-input/1'
PURPOSE_SCHEMA = 'polar.ief-bil-month-end-source-purpose/1'
QUESTION = 'IEF-BIL-EQUITY-DOWN-MONTH-01'
PRODUCER = 'engineering-data@engineering-rig'
DISPATCHER = 'engineering-platform@engineering-rig'
TASK = 'qitem-engineering-data-ief-bil-native-source-production-20261120'
READERS = {PRODUCER: ('engineering-rig', 'engineering.data'),
           'data-researcher@polar-rig': ('polar-rig', 'data.researcher'),
           'quant-a@polar-rig': ('polar-rig', 'quant.a')}
TAGS = {'project:polar', 'mission:03-competitive-strategies', 'slice:ief-bil-equity-down-month'}
SYMBOLS = ['BIL', 'IEF', 'VTI']
PROTOCOL_SHA = 'ff300c9b1e19e4193474d2d57a193fa7660e1f81d5a22c35db56cd7734d36040'
FIT_SHA = '568335f5ebf1778631c036ae30fdeed1e42af450cd730b423bb8c8e0102024dc'
CALENDAR_SHA = '94c92b6437accafbfdb97ffc272ce93fe1dd52169a060fb21847a39f5681e20e'
PARENT_SHA = '4729427820455eaa87c774cb51a9e4dbe2694db06a08b2b8955f02f2c620876a'
BINDING_SHA = 'f556c660a7610bb4712563f78023ba01c8f0673c3846387b9f6b7ab931d8b06b'
BIL_SHA = 'b413e6aceeeba10884ab1c3dca77c3ef85c758d680a9af254d26fcc69d8a6d30'
FIRST = '2020-12-31'
PHASE_ANCHOR = '2022-12-30'
LAST = '2026-10-30'
FIELDS = {'schema', 'namespace', 'question_id', 'purpose', 'code', 'code_revision',
          'runtime_image_id', 'artifact_root_identity', 'consumer_task', 'actor_session',
          'spec_ref', 'protocol_ref', 'source_fit_ref'}


def check_scope(config):
    require(type(config) is dict and set(config) == FIELDS and config['schema'] == SOURCE_SCHEMA and
            config['question_id'] == QUESTION and config['purpose'] == PURPOSE_SCHEMA and
            config['actor_session'] == PRODUCER and
            ((config['namespace'] == 'RETAINED' and config['consumer_task'] == TASK) or
             (config['namespace'] == 'INVENTED' and config['consumer_task'] == 'qitem-INVENTED-IEF-BIL')),
            'IEF_BIL_SOURCE_SCOPE')


def authorize(config, root, *, queue=None, prior=None, terminal_result=None):
    from .candidate_binding import loaded_revision
    from .ci_research_service import root_identity
    from .gym_service import code_binding

    check_scope(config)
    require(root is not None and config['artifact_root_identity'] == root_identity(root) and
            config['code'] == code_binding() and config['code_revision'] == loaded_revision(),
            'IEF_BIL_SOURCE_CURRENT_BINDING')
    actual_runtime(config)
    if config['namespace'] == 'INVENTED':
        proof = {'status': 'INVENTED_TEST_ONLY', 'scope_sha256': sha(canonical(config))}
        require(prior is None or all(prior.get(k) == v for k, v in proof.items()), 'IEF_BIL_SOURCE_BINDING')
        return proof
    return producer_custody(config, queue, prior=prior, terminal_result=terminal_result)


def producer_custody(config, queue, *, prior=None, terminal_result=None, require_terminal=False):
    return task_custody(config, queue or current_queue(), prior=prior, terminal_result=terminal_result,
                        require_terminal=require_terminal, actors=READERS, tags=TAGS, dispatcher=DISPATCHER, terminal_readers=READERS,
                        terminal_targets=(DISPATCHER,))


def month_ends(schedule, *, retained):
    rows, days = reference_schedule(schedule)
    require(all(datetime.fromisoformat(row[f'reference_{edge}_utc']).utcoffset() == timedelta(0)
                for row in rows for edge in ('open', 'close')), 'IEF_BIL_CALENDAR_UTC')
    endpoints = [day for day, next_day in zip(days, days[1:]) if day[:7] != next_day[:7]]
    if retained:
        endpoints = [day for day in endpoints if FIRST <= day <= LAST]
        months = ['2020-12', *(f'{year}-{month:02d}' for year in range(2021, 2027)
                              for month in range(1, (11 if year == 2026 else 13)))]
        require([day[:7] for day in endpoints] == months and endpoints[0] == FIRST and
                endpoints[-1] == LAST and PHASE_ANCHOR in endpoints, 'IEF_BIL_FROZEN_ENDPOINTS')
    require(bool(endpoints), 'IEF_BIL_FROZEN_ENDPOINTS')
    return endpoints


def purpose_metadata(config, spec):
    return {'schema': PURPOSE_SCHEMA, 'question_id': QUESTION, 'symbols': SYMBOLS,
            'rights': RIGHTS if config['namespace'] == 'RETAINED' else 'INVENTED_PUBLIC_TEST',
            'protocol': config['protocol_ref'], 'source_fit': config['source_fit_ref'],
            'calendar': spec['schedule'], 'endpoints': spec['date_range']}


def checked_spec(config):
    from .selected_component_input import SCHEMA

    retained = config['namespace'] == 'RETAINED'
    if retained:
        require(config['protocol_ref']['sha256'] == PROTOCOL_SHA and
                config['source_fit_ref']['sha256'] == FIT_SHA, 'IEF_BIL_SOURCE_AUTHORITY_PINS')
    pinned_bytes(config['protocol_ref'])
    require(type(decode(pinned_bytes(config['source_fit_ref']))) is dict, 'IEF_BIL_SOURCE_FIT')
    spec = decode(pinned_bytes(config['spec_ref']))
    require(type(spec) is dict and spec.get('schema') == SCHEMA and
            spec.get('namespace') == config['namespace'] and spec.get('qualification_refs') == [config['source_fit_ref']],
            'IEF_BIL_SOURCE_SPEC')
    leaves, normalized = spec['leaf_inputs'], spec['normalized_inputs']
    require(type(leaves) is list and [item['symbol'] for item in leaves] == ['BIL'] and
            type(normalized) is list and sorted(item['symbol'] for item in normalized) == ['IEF', 'VTI'] and
            normalized[0]['input_ref'] == normalized[1]['input_ref'] and
            normalized[0]['binding_ref'] == normalized[1]['binding_ref'], 'IEF_BIL_SOURCE_COMPONENTS')
    if retained:
        require(leaves[0]['input_ref']['sha256'] == BIL_SHA and
                normalized[0]['input_ref']['sha256'] == PARENT_SHA and
                normalized[0]['binding_ref']['sha256'] == BINDING_SHA and
                spec['schedule']['sha256'] == CALENDAR_SHA, 'IEF_BIL_SOURCE_COMPONENT_PINS')
    require(decode(pinned_bytes(spec['purpose_ref'])) == purpose_metadata(config, spec), 'IEF_BIL_SOURCE_PURPOSE')
    calendar = decode(pinned_bytes(spec['schedule']))
    endpoints = month_ends(calendar, retained=retained)
    require(spec['date_range'] == {'start': endpoints[0], 'end': endpoints[-1], 'count': len(endpoints)},
            'IEF_BIL_SOURCE_ENDPOINT_SCOPE')
    return spec, calendar, endpoints


def prepare_source_input(config, root, limit, *, queue=None):
    from .selected_component_input import prepare_selected_components

    proof = authorize(config, root, queue=queue)
    spec, _, endpoints = checked_spec(config)
    result = prepare_selected_components(spec, root, limit, source_binding={**proof, 'config': config},
                                         endpoints=endpoints, source_only_schema=MANIFEST_SCHEMA)
    authorize(config, root, queue=queue, prior=proof)
    return result


def source_config(manifest):
    metadata = manifest.get('conversion_metadata', manifest.get('provenance', {}))
    binding = metadata.get('source_native_binding') if isinstance(metadata, dict) else None
    config = binding.get('config') if isinstance(binding, dict) else None
    return config if isinstance(config, dict) else {}


def is_source_manifest(manifest):
    return isinstance(manifest, dict) and (manifest.get('schema') == MANIFEST_SCHEMA or
                                           source_config(manifest).get('schema') == SOURCE_SCHEMA)


def prepared_binding(pin, manifest):
    metadata = manifest.get('conversion_metadata', manifest.get('provenance', {}))
    proof = metadata.get('source_native_binding', {})
    config = source_config(manifest)
    require(manifest.get('schema') == MANIFEST_SCHEMA and sha(canonical(manifest)) == pin['sha256'],
            'IEF_BIL_SOURCE_MANIFEST')
    check_scope(config)
    receipt = {'schema': 'polar.ief-bil-source-result/1', 'status': 'STRUCTURALLY_VALID_SOURCE_ONLY',
               'question_id': QUESTION, 'consumer_task': config['consumer_task'],
               'input_manifest_sha256': pin['sha256'], 'scope_sha256': sha(canonical(config))}
    return metadata, proof, config, receipt


def prepared_endpoints(pin, manifest, root, metadata, proof, config):
    from .reference_input import project_schedule
    from .selected_component_input import CONVERTER

    spec, calendar, endpoints = checked_spec(config)
    schedule = project_schedule(calendar, spec['date_range'], endpoints=endpoints)
    revision = 'reference-input-' + sha(canonical({
        'converter': CONVERTER, 'spec': spec, 'source_native_binding': proof,
        'quotes_sha256': manifest['quotes']['sha256'], 'schedule_sha256': sha(canonical(schedule)),
        'relations_sha256': manifest['source_relations']['sha256'],
    }))
    directory = Path(root) / 'reference-inputs' / revision
    prefix = 'INVENTED-' if config['namespace'] == 'INVENTED' else ''
    rights = 'INVENTED_PUBLIC_TEST' if prefix else RIGHTS
    require(metadata.get('converter') == CONVERTER and metadata.get('spec') == spec and
            metadata.get('parent_schedule') == spec['schedule'] and metadata.get('private_root') == str(root) and
            manifest.get('symbols') == SYMBOLS and manifest.get('dates') == spec['date_range'] and
            manifest.get('rights') == rights and manifest['parent_dataset_revision'] == prefix + revision and
            manifest['schedule']['sha256'] == sha(canonical(schedule)) and
            pin['path'] == str(directory / 'manifest.json') and
            all(manifest[key]['path'] == str(directory / name) for key, name in
                (('schedule', 'schedule.json'), ('quotes', 'quotes.ndjson'), ('source_relations', 'source-relations.json'))),
            'IEF_BIL_SOURCE_PREPARED_BINDING')
    return endpoints


def preflight_source_input(pin, manifest, root, *, queue=None):
    from .research_reference import _load_reference_values

    metadata, proof, config, receipt = prepared_binding(pin, manifest)
    authorize(config, root, queue=queue, prior=proof, terminal_result=receipt)
    prepared_endpoints(pin, manifest, root, metadata, proof, config)
    result = _load_reference_values(pin, manifest, source_only=True)
    authorize(config, root, queue=queue, prior=proof, terminal_result=receipt)
    return {**result, 'producer_terminal_result': receipt}

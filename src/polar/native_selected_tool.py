"""Inherited native context for the closed Quant A offline CLI in its build.

Reuses the existing bounded host/stdin adapter, not a service or financial
engine. No native identity is cached or installed in the container. The CLI's
ordinary input/profile/runtime/store/duplicate checks still decide readiness.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

from .research_results import ResearchError
from .research_native_review import NativeQueue, inherited_queue
from .research_native_tool import ToolPipe, source_identity, pipe_bridge, MAX_LINE

OPERATIONS = ('research-input-prepare', 'research-input-preflight', 'research-preflight', 'research-run')


def selected_config(operation, value):
    from .research_reference import decode, pinned_bytes
    from .native_selected_input import SCHEMA, CONVERTER
    from .scheduled_drawdown import SCHEMA as PROFILE_SCHEMA
    if operation == 'research-input-prepare':
        config = value
    else:
        if operation in ('research-preflight', 'research-run'):
            # Closed registered strategy only, never an arbitrary code loader.
            if decode(pinned_bytes(value['profile_ref']))['schema'] != PROFILE_SCHEMA:
                raise ResearchError('NATIVE_SELECTED_PROFILE', 409)
            manifest = decode(pinned_bytes(value['input_ref']))
        else:
            manifest = decode(pinned_bytes(value))
        provenance = manifest.get('conversion_metadata', manifest.get('provenance', {}))
        if provenance.get('converter') != CONVERTER:
            raise ResearchError('NATIVE_SELECTED_MANIFEST', 409)
        config = provenance['config']
    if config.get('schema') != SCHEMA:
        raise ResearchError('NATIVE_SELECTED_CONFIG', 422)
    return config


def permitted(args, config):
    qid = config['source_admission_ref'].rsplit('#', 1)[0]
    return args in (['whoami'], ['seat', 'status', 'quant-a@polar-rig'],
        ['queue', 'show', config['consumer_task'], '--full'],
        ['queue', 'claim', config['consumer_task']],
        ['queue', 'transitions', config['consumer_task'], '--full'],
        ['queue', 'show', qid, '--full'], ['queue', 'transitions', qid, '--full'])


def consume(operation, value, expected_source):
    if operation not in OPERATIONS or source_identity() != expected_source:
        raise ResearchError('RESEARCH_NATIVE_CONSUMER_SOURCE_MISMATCH', 409)
    from .config import Settings
    from .service import Service
    from .native_selected_input import authorize
    config = selected_config(operation, value)
    settings = Settings.load_artifacts()
    queue = ToolPipe()
    authorize(config, settings.artifacts, queue=queue)
    # All nested reads, including ordinary load_reference and custody rereads,
    # use this same live host adapter. No caller field can supply this context.
    with inherited_queue(queue):
        return getattr(Service(settings, native_queue=queue), operation.replace('-', '_'))(value)


def bridge(container, operation, value, *, queue=None):
    if not re.fullmatch('[a-f0-9]{12,64}', container) or operation not in OPERATIONS:
        raise ResearchError('RESEARCH_NATIVE_TOOL_OPERATION', 422)
    config = selected_config(operation, value)
    command = ['docker', 'exec', '-i', container, 'python', '-u', '-m', 'polar.native_selected_tool',
               '--stdio-consumer', '--operation', operation, '--source-sha256', source_identity()]
    return pipe_bridge(command, lambda args: permitted(args, config), queue or NativeQueue(),
                       initial={'value': value}, timeout=600)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--container')
    p.add_argument('--operation', choices=OPERATIONS, required=True)
    p.add_argument('file', type=Path, nargs='?')
    p.add_argument('--stdio-consumer', action='store_true', help=argparse.SUPPRESS)
    p.add_argument('--source-sha256', help=argparse.SUPPRESS)
    args = p.parse_args()
    try:
        if args.stdio_consumer:
            raw = sys.stdin.buffer.readline(MAX_LINE+1)
            if len(raw) > MAX_LINE:raise ValueError()
            value = json.loads(raw)['value']
            result = consume(args.operation, value, args.source_sha256)
            print(json.dumps({'result': result}), flush=True)
        else:
            if args.file is None:raise ValueError()
            raw = args.file.read_bytes()
            if len(raw) > MAX_LINE:raise ValueError()
            print(json.dumps(bridge(args.container or '', args.operation, json.loads(raw))))
    except (ResearchError, OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as exc:
        code = exc.code if isinstance(exc, ResearchError) else str(exc)
        if not re.fullmatch('[A-Z][A-Z0-9_]{0,127}', code):code = 'NATIVE_SELECTED_OPERATION_FAILED'
        print(json.dumps({'error_code': code}), flush=True)
        raise SystemExit(1)


if __name__ == '__main__':
    main()

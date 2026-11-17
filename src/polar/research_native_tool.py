"""One bounded native-tool call into the existing product container/store.

No service or identity is installed in the container. Its resolver requests each
native read over this process's private stdio; the host executes the real inherited
rig tool for every read, including the current-custody reread. No proof upload or
cached actor assertion can enter the API. Deployment remains with its owner.
"""
import argparse
import json
import os
import re
import selectors
import subprocess
import sys
import time

from .history_bundle import canonical, sha
from .research_native_review import DecisionRequest, NativeQueue, resolve
from .research_results import ResearchError

MAX_LINE = 2*1024**2


def source_identity():
    from .gym_service import code_binding
    return sha(canonical(code_binding()))


class ToolPipe:
    def read(self, *args):
        print(json.dumps({'native_read': list(args)}), flush=True)
        raw = sys.stdin.buffer.readline(MAX_LINE+1)
        if not raw or len(raw) > MAX_LINE:
            raise ResearchError('RESEARCH_NATIVE_TOOL_UNAVAILABLE', 503)
        reply = json.loads(raw)
        if set(reply) != {'value'}:
            raise ResearchError('RESEARCH_NATIVE_TOOL_UNAVAILABLE', 503)
        return reply['value']


def consume(operation, decision_ref, expected_source):
    from .config import Settings
    from .service import Service
    from .worker import work_research_delivery_once
    if expected_source != source_identity():
        raise ResearchError('RESEARCH_NATIVE_CONSUMER_SOURCE_MISMATCH', 409)
    settings = Settings.load()
    queue = ToolPipe()
    if not settings.artifacts.is_dir():
        raise ResearchError('RESEARCH_NATIVE_PRODUCT_STORE_UNAVAILABLE', 503)
    if operation == 'probe':
        review, _ = resolve(decision_ref, queue)
        with Service(settings).registry.connect() as db:
            db.execute('SELECT 1')
        return {'operation': operation, 'source_sha256': expected_source,
                'native_adapter': 'ACTUAL_HOST_TOOL', 'product_store_exists': True,
                'registry_connected': True, 'result_id': review['result_id'], 'writer': 'NOT_CALLED'}
    if not settings.native_review_writer_enabled:
        raise ResearchError('RESEARCH_NATIVE_REVIEW_WRITER_DISABLED', 409)
    if operation == 'submit':
        receipt = Service(settings, native_queue=queue).research_delivery_submit({'decision_ref': decision_ref})
    elif operation == 'work-once':
        from .codec import digest
        review, _ = resolve(decision_ref, queue)
        body = {'schema_version': 'polar.research-delivery/1', 'kind': 'ASSESSMENT',
                'display_scope': 'OWNER_LOCAL', 'content_sha256': review['content_sha256'],
                'payload': {'decision_ref': decision_ref}}
        receipt = work_research_delivery_once(settings, native_queue=queue,
                                              delivery_id='delivery-'+digest(body))
    else:
        raise ResearchError('RESEARCH_NATIVE_TOOL_OPERATION', 422)
    return {'operation': operation, 'source_sha256': expected_source, 'receipt': receipt}


def permitted(args, decision_ref):
    qid = decision_ref.rsplit('#', 1)[0]
    return args in (['whoami'], ['queue', 'show', qid, '--full'],
                    ['queue', 'transitions', qid, '--full'],
                    ['seat', 'status', 'quant-validator@polar-rig'])


def bridge(container, operation, decision_ref, *, queue=None):
    DecisionRequest.model_validate({'decision_ref': decision_ref})
    if not re.fullmatch(r'[a-f0-9]{12,64}', container) or operation not in ('probe', 'submit', 'work-once'):
        raise ResearchError('RESEARCH_NATIVE_TOOL_OPERATION', 422)
    queue = queue or NativeQueue()
    command = ['docker', 'exec', '-i', container, 'python', '-u', '-m',
               'polar.research_native_tool', '--stdio-consumer', '--operation', operation,
               '--decision-ref', decision_ref, '--source-sha256', source_identity()]
    return pipe_bridge(command, lambda args: permitted(args, decision_ref), queue)


def pipe_bridge(command, allow_read, queue, *, initial=None, timeout=60, max_reads=32):
    """Private bounded stdio transport shared by the closed native consumers."""
    if type(max_reads) is not int or not 1 <= max_reads <= 128:
        raise ResearchError('RESEARCH_NATIVE_TOOL_PROTOCOL', 409)
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL)
    if initial is not None:
        process.stdin.write(canonical(initial)+b'\n'); process.stdin.flush()
    deadline = time.monotonic()+timeout
    pending = bytearray(); reads = 0
    selector = selectors.DefaultSelector(); selector.register(process.stdout, selectors.EVENT_READ)
    try:
        while time.monotonic() < deadline:
            if not selector.select(max(0, deadline-time.monotonic())):
                break
            chunk = os.read(process.stdout.fileno(), 65536)
            if not chunk:
                break
            pending.extend(chunk)
            if len(pending) > MAX_LINE:
                raise ResearchError('RESEARCH_NATIVE_TOOL_PROTOCOL', 409)
            while b'\n' in pending:
                line, _, rest = pending.partition(b'\n'); pending = bytearray(rest)
                message = json.loads(line)
                if set(message) == {'native_read'}:
                    args = message['native_read']; reads += 1
                    if reads > max_reads or not allow_read(args):
                        raise ResearchError('RESEARCH_NATIVE_TOOL_PROTOCOL', 409)
                    value = queue.read(*args)
                    process.stdin.write(canonical({'value': value})+b'\n'); process.stdin.flush()
                elif set(message) == {'result'}:
                    process.stdin.close()
                    if process.wait(timeout=max(.1, deadline-time.monotonic())) != 0:
                        raise ResearchError('RESEARCH_NATIVE_CONSUMER_FAILED', 409)
                    return message['result']
                elif set(message) == {'error_code'}:
                    code = message['error_code']
                    if not isinstance(code, str) or not re.fullmatch(r'[A-Z][A-Z0-9_]{0,127}', code):
                        code = 'RESEARCH_NATIVE_CONSUMER_FAILED'
                    raise ResearchError(code, 409)
                else:
                    raise ResearchError('RESEARCH_NATIVE_TOOL_PROTOCOL', 409)
        raise ResearchError('RESEARCH_NATIVE_TOOL_UNAVAILABLE', 503)
    finally:
        selector.close()
        if not process.stdin.closed: process.stdin.close()
        if process.poll() is None:
            process.terminate()
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
        process.stdout.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--container')
    parser.add_argument('--operation', choices=['probe', 'submit', 'work-once'], required=True)
    parser.add_argument('--decision-ref', required=True)
    parser.add_argument('--stdio-consumer', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--source-sha256', help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        if args.stdio_consumer:
            result = consume(args.operation, args.decision_ref, args.source_sha256)
            print(json.dumps({'result': result}, default=str), flush=True)
        else:
            print(json.dumps(bridge(args.container or '', args.operation, args.decision_ref), default=str))
    except (ResearchError, OSError, ValueError, TypeError, subprocess.SubprocessError) as exc:
        code = exc.code if isinstance(exc, ResearchError) else 'RESEARCH_NATIVE_TOOL_UNAVAILABLE'
        print(json.dumps({'error_code': code}), flush=True)
        raise SystemExit(1)


if __name__ == '__main__':
    main()

"""Resolve a decision address through the inherited native queue tool.

The producer supplies no reviewer, verdict or proof. The assigned Validator's
terminal resolution must bind the exact canonical projection and name every
native author/coauthor. Historical prose is never parsed into a trusted verdict.
"""
import json
from contextlib import contextmanager
from contextvars import ContextVar
import re
import subprocess
from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import Field, ValidationError

from .history_bundle import canonical, sha
from .research_results import Closed, Hash, ResearchError, ResearchReview, public_text

Actor = Annotated[str, Field(pattern=r'^[A-Za-z0-9_.:-]+@[A-Za-z0-9_.:-]+$')]
DecisionRef = Annotated[str, Field(pattern=r'^qitem-[A-Za-z0-9_.:-]+#[1-9][0-9]*$')]


class DecisionRequest(Closed):
    decision_ref: DecisionRef


class NativeDecision(Closed):
    schema_version: Literal['polar.native-research-decision/1']
    result_id: Annotated[str, Field(pattern=r'^research-[a-f0-9]{64}$')]
    content_sha256: Hash
    bindings: dict
    author_sessions: Annotated[list[Actor], Field(min_length=1, max_length=20)]
    claimed_generation: Annotated[str, Field(min_length=1, max_length=100)]
    review: dict


def require(ok, code='RESEARCH_NATIVE_DECISION_BINDING'):
    if not ok:
        raise ResearchError(code, 409)


class NativeQueue:
    def read(self, *args):
        try:
            # Inherit this tool's actual managed transport; no actor/env override,
            # private queue database, shell interpolation or caller-supplied URL.
            result = subprocess.run(['rig', *args, '--json'], capture_output=True,
                                    timeout=15, check=True)
            if len(result.stdout) > 2*1024**2:
                raise ValueError()
            return json.loads(result.stdout)
        except (OSError, ValueError, subprocess.SubprocessError):
            raise ResearchError('RESEARCH_NATIVE_TOOL_UNAVAILABLE', 503) from None


_native_context = ContextVar('polar_inherited_native_tool', default=None)


def current_queue():
    return _native_context.get() or NativeQueue()


@contextmanager
def inherited_queue(queue):
    """Internal stdio tool context; never obtained from a request or environment."""
    token = _native_context.set(queue)
    try:
        yield
    finally:
        _native_context.reset(token)


def resolve(decision_ref, queue=None):
    try:
        DecisionRequest.model_validate({'decision_ref': decision_ref})
        qid, transition = decision_ref.rsplit('#', 1)
        transition = int(transition)
        queue = queue or NativeQueue()
        identity = queue.read('whoami').get('identity', {})
        require(bool(identity.get('sessionName') and identity.get('nodeId')),
                'RESEARCH_NATIVE_IDENTITY_UNVERIFIED')
        row = queue.read('queue', 'show', qid, '--full')
        journal = queue.read('queue', 'transitions', qid, '--full')
        actor = row.get('destinationSession')
        seat = queue.read('seat', 'status', actor)
        require(seat.get('current_occupant') == actor and seat.get('logical_id') == 'quant.validator'
                and seat.get('rig_name') == 'polar-rig', 'RESEARCH_NATIVE_VALIDATOR_UNASSIGNED')
        require(row.get('qitemId') == qid and row.get('state') == 'done'
                and row.get('closureReason') in ('no-follow-on', 'handed_off_to'))
        require(isinstance(journal, list) and 1 <= len(journal) <= 1000)
        closing = row.get('closingTransition', {})
        terminals = [x for x in journal if x.get('transitionId') == transition]
        require(len(terminals) == 1 and closing.get('transitionId') == transition)
        terminal = terminals[0]
        require(terminal.get('state') == 'done' and terminal.get('actorSession') == actor
                and terminal.get('identityProvenance') == 'transport:v1')
        claims = [x for x in journal if x.get('transitionId', transition) < transition
                  and x.get('state') == 'in-progress' and x.get('transitionNote') == 'claimed']
        require(bool(claims))
        claim = max(claims, key=lambda x: x['transitionId'])
        require(claim.get('actorSession') == actor and claim.get('identityProvenance') == 'transport:v1'
                and bool(row.get('claimedByGeneration')))
        claim_time = datetime.fromisoformat(claim['ts'].replace('Z', '+00:00'))
        row_time = datetime.fromisoformat(row['claimedAt'].replace('Z', '+00:00'))
        # Queue row and its transition are stamped separately (observed 1ms).
        require(0 <= (claim_time-row_time).total_seconds() <= 1)
        decision = NativeDecision.model_validate(json.loads(row['resolution'])).model_dump(mode='json')
        require(decision['claimed_generation'] == row['claimedByGeneration'])
        authors = decision['author_sessions']
        require(len(set(authors)) == len(authors) and actor not in authors
                and row.get('sourceSession') in authors, 'RESEARCH_NATIVE_SELF_OR_COAUTHOR')
        require(decision['result_id'] == 'research-'+decision['content_sha256'])
        # Re-read current custody to reject a concurrent reopen/reassignment.
        current = queue.read('queue', 'show', qid, '--full')
        require(all(current.get(k) == row.get(k) for k in
                    ('state', 'destinationSession', 'claimedAt', 'claimedByGeneration',
                     'closingTransition', 'resolution')))
        stamp = datetime.fromisoformat(terminal['ts'].replace('Z', '+00:00')).astimezone(timezone.utc)
        alias = 'native-'+sha(actor.encode())[:40]
        proof = {'schema_version': 'polar.native-review-provenance/1',
                 'decision_ref': decision_ref, 'validator_session': actor,
                 'claimed_generation': row['claimedByGeneration'], 'claim_transition': claim['transitionId'],
                 'terminal_transition': transition, 'identity_provenance': 'transport:v1',
                 'author_sessions': authors, 'result_id': decision['result_id'],
                 'content_sha256': decision['content_sha256'], 'bindings': decision['bindings'],
                 'decision_sha256': sha(canonical(decision))}
        # Review content comes only from this Validator's terminal resolution.
        review = ResearchReview.model_validate({**decision['review'],
            'schema_version': 'polar.research-review/1', 'result_id': decision['result_id'],
            'content_sha256': decision['content_sha256'], 'reviewer_id': alias,
            'recorded_at': stamp.strftime('%Y-%m-%dT%H:%M:%SZ')}).model_dump(mode='json')
        require(set(decision['review']) == {'scope', 'verdict', 'scope_description', 'reference',
                                           'evidence_status', 'reason'})
        # Bind proof bytes into the immutable review, with the assessment retained
        # separately inside the proof rather than a mutable adjacent assertion.
        proof['assessment_reference'] = review['reference']
        review['reference'] = {'role': 'verified_native_decision', 'id': qid,
                               'sha256': sha(canonical(proof))}
        public_text(review)
        public_text(proof)
        return review, proof
    except (ValidationError, ValueError, TypeError, KeyError, AttributeError):
        raise ResearchError('RESEARCH_NATIVE_DECISION_INVALID', 422) from None

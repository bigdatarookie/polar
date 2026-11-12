"""Delivery of canonical saved output only; no producer or scientific runner imports."""
from typing import Literal

from pydantic import ValidationError

from .codec import digest
from .history_bundle import canonical, sha
from .research_results import (Closed, Hash, MAX_RESULT, ResearchError,
                               ResearchReview, public_text, validate_result)


class Delivery(Closed):
    schema_version: Literal["polar.research-delivery/1"]
    kind: Literal["RESULT", "ASSESSMENT"]
    display_scope: Literal["OWNER_LOCAL"]
    content_sha256: Hash
    payload: dict


def validate_delivery(value):
    try:
        body = Delivery.model_validate(value).model_dump(mode="json")
        if body["kind"] == "RESULT":
            payload = validate_result(body["payload"])
            if payload != body["payload"] or sha(canonical(payload)) != body["content_sha256"]:
                raise ResearchError("RESEARCH_DELIVERY_CONTENT_BINDING", 409)
            rid = "research-"+body["content_sha256"]
            limit = MAX_RESULT
        else:
            payload = ResearchReview.model_validate(body["payload"]).model_dump(mode="json")
            public_text(payload)
            rid = payload["result_id"]
            if payload["content_sha256"] != body["content_sha256"] or rid != "research-"+body["content_sha256"]:
                raise ResearchError("RESEARCH_DELIVERY_CONTENT_BINDING", 409)
            limit = 16384
        if len(canonical(payload)) > limit:
            raise ResearchError("RESEARCH_DELIVERY_TOO_LARGE", 413)
        body["payload"] = payload
        return body, rid
    except (ValidationError, ValueError, TypeError):
        raise ResearchError("RESEARCH_INVALID_DELIVERY", 422) from None


def delivery_status(row):
    # Never echo a public projection body, local paths, DB credentials, or lease token.
    fields = ("id", "kind", "result_id", "payload_hash", "state", "delivery_attempt_count",
              "queued_at", "started_at", "last_started_at", "delivered_at", "finished_at",
              "updated_at", "receipt", "error_code")
    return {"schema_version": "polar.research-delivery-status/1",
            **{k: row[k] for k in fields}}


def submit(registry, value):
    body, rid = validate_delivery(value)
    h = digest(body)
    return delivery_status(registry.submit_research_delivery("delivery-"+h, body["kind"], rid, h, body))


def deliver_once(registry, results):
    row = registry.claim_research_delivery()
    if row is None:
        return None
    # A process loss before finish leaves only a lease to reclaim. Publication is
    # atomic/idempotent, so retry delivers the same bytes without spending a run.
    try:
        body, rid = validate_delivery(row["body"])
        if (rid != row["result_id"] or digest(body) != row["payload_hash"] or
                row["id"] != "delivery-"+digest(body) or row["kind"] != body["kind"]):
            raise ResearchError("RESEARCH_DELIVERY_CONTENT_BINDING", 409)
        operation = results.publish if body["kind"] == "RESULT" else results.review
        receipt = operation(body["payload"])
        detail = results.read(rid)
        receipt = {**receipt, "assessment": detail["assessment"],
                   "observed_content_sha256": detail["content_sha256"]}
        state, code = "DELIVERED", None
    except ResearchError as exc:
        receipt = None
        if exc.code == "RESEARCH_NOT_FOUND" and row["kind"] == "ASSESSMENT":
            state, code = "WAITING_FOR_RESULT", "RESEARCH_NOT_FOUND"
        else:
            state, code = "REJECTED", exc.code
    # OSError/DB/process loss deliberately does not complete/reject the lease.
    return delivery_status(registry.finish_research_delivery(
        row["id"], row["lease_token"], state, receipt, code))

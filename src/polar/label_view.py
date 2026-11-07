"""Pure supplied-label maturity, separate from feature and training eligibility."""
import hashlib
import re
from datetime import datetime, timedelta
from decimal import Context, Decimal, InvalidOperation
from typing import Annotated, Literal

from pydantic import BeforeValidator, Field, ValidationError, model_validator

from .codec import canonical, digest
from .models import Strict

MAX_INPUT_BYTES = 1024**2
MAX_RECORDS = 1000
KEY_FIELDS = ("instrument_id", "label_id", "definition_version", "decision_at",
              "target_start_at", "target_end_at")
_UTC_TEXT = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
                       r"(?:\.[0-9]{1,6})?(?:Z|\+00:00)\Z")


class LabelViewError(ValueError):
    """Code-only diagnostics; never expose supplied payloads."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _utc(value):
    if not isinstance(value, str) or not _UTC_TEXT.fullmatch(value):
        raise ValueError("UTC_STRING_REQUIRED")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError("UTC_REQUIRED")
    return parsed


UTC = Annotated[datetime, BeforeValidator(_utc)]
Identifier = Annotated[str, Field(min_length=1, max_length=64)]


def _label_decimal(value):
    """Exact admission without caller-context arithmetic or conversion flags."""
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError("DECIMAL_STRING_REQUIRED")
    number = Decimal(value, context=Context(traps=[InvalidOperation]))
    if (not number.is_finite() or number.copy_abs() > Decimal("1e12")
            or number.as_tuple().exponent < -12):
        raise ValueError("DECIMAL_OUT_OF_BOUNDS")
    return number


LabelNumber = Annotated[Decimal, BeforeValidator(_label_decimal)]


class LabelRecord(Strict):
    instrument_id: Identifier
    label_id: Identifier
    definition_version: Identifier
    decision_at: UTC
    target_start_at: UTC
    target_end_at: UTC
    source_revision: Identifier
    published_at: UTC
    available_at: UTC
    ingested_at: UTC
    value_unit: Identifier
    value: LabelNumber

    @model_validator(mode="after")
    def clocks(self):
        if not self.decision_at <= self.target_start_at < self.target_end_at:
            raise ValueError("INVALID_TARGET_INTERVAL")
        if not self.published_at <= self.available_at <= self.ingested_at:
            raise ValueError("INVALID_RELEASE_ORDER")
        return self


class LabelEnvelope(Strict):
    schema_version: Literal["polar.synthetic-label-input/1"]
    synthetic: Literal[True]
    timing_model: Literal["synthetic_replay"]
    labels: list[LabelRecord] = Field(max_length=MAX_RECORDS)

    @model_validator(mode="before")
    @classmethod
    def explicit_synthetic(cls, value):
        if isinstance(value, dict) and value.get("synthetic") is not True:
            raise ValueError("SYNTHETIC_TRUE_REQUIRED")
        return value


def _key(record):
    return tuple(getattr(record, field) for field in KEY_FIELDS)


def _release(record):
    return max(record.published_at, record.available_at, record.ingested_at)


def label_maturity_view(raw_bytes: bytes, fit_cutoff: str, *, limit: int) -> dict:
    """Audit supplied revisions at fit time, without computing or fitting targets."""
    if not isinstance(raw_bytes, bytes):
        raise LabelViewError("INVALID_INPUT_TYPE")
    if len(raw_bytes) > MAX_INPUT_BYTES:
        raise LabelViewError("INPUT_TOO_LARGE")
    if type(limit) is not int or not 1 <= limit <= MAX_RECORDS:
        raise LabelViewError("INVALID_LIMIT")
    try:
        cutoff = _utc(fit_cutoff)
    except (ValueError, OverflowError):
        raise LabelViewError("INVALID_FIT_CUTOFF") from None
    try:
        envelope = LabelEnvelope.model_validate_json(raw_bytes)
    except (ValidationError, ValueError, ArithmeticError, RecursionError):
        raise LabelViewError("INVALID_LABEL_INPUT") from None
    if len(envelope.labels) > limit:
        raise LabelViewError("RECORD_LIMIT_EXCEEDED")

    groups, seen = {}, set()
    for record in envelope.labels:
        key = _key(record)
        revision_key = (*key, record.source_revision)
        if revision_key in seen:
            raise LabelViewError("DUPLICATE_REVISION")
        seen.add(revision_key)
        groups.setdefault(key, []).append(record)

    selected, diagnostics = [], []
    for key in sorted(groups):
        records = sorted(groups[key], key=lambda r: r.source_revision)
        mature = [r for r in records if max(r.target_end_at, _release(r)) <= cutoff]
        winner = None
        if mature:
            latest = max(_release(r) for r in mature)
            winners = [r for r in mature if _release(r) == latest]
            if len(winners) != 1:
                raise LabelViewError("AMBIGUOUS_REVISION")
            winner = winners[0]
            selected.append(winner.model_dump(mode="json"))
        for record in records:
            body = record.model_dump(mode="json")
            reason = ("SELECTED" if record is winner else
                      "SUPERSEDED" if max(record.target_end_at, _release(record)) <= cutoff
                      else "NOT_MATURE")
            diagnostics.append({"observation_key": {f: body[f] for f in KEY_FIELDS},
                                "source_revision": record.source_revision,
                                "reason": reason, "record": body})

    body = envelope.model_dump(mode="json")
    body["labels"] = sorted(body["labels"], key=canonical)
    input_hash = digest(body)
    normalized_cutoff = cutoff.isoformat().replace("+00:00", "Z")
    return {
        "schema_version": "polar.label-maturity-view/1",
        "synthetic": True,
        "timing_model": "synthetic_replay",
        "fit_cutoff": normalized_cutoff,
        "request_limit": limit,
        "source_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "canonical_input_hash": input_hash,
        "request_hash": digest({"canonical_input_hash": input_hash,
                                "fit_cutoff": normalized_cutoff, "limit": limit}),
        "status": ("NO_DATA" if not envelope.labels else
                   "SELECTED" if selected else "NO_MATURE_LABELS"),
        "selected": selected,
        "diagnostics": diagnostics,
        "label_value_qualification": "UNVERIFIED",
        "training_eligibility": "NOT_ASSESSED",
        "financial_verdict": "NOT_RUN",
    }

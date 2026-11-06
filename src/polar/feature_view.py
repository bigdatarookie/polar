"""Bounded synthetic revision selection, independent of the runtime Dataset."""
import hashlib
from datetime import datetime, timedelta
from typing import Literal

from pydantic import Field, ValidationError, model_validator

from .codec import canonical, digest
from .models import Feature, Strict

MAX_INPUT_BYTES = 1024**2
MAX_RECORDS = 1000


class FeatureViewError(ValueError):
    """Public diagnostics contain codes only, never validation payloads."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


class ViewFeature(Feature):
    instrument_id: str = Field(min_length=1, max_length=64)
    feature_id: str = Field(min_length=1, max_length=64)


class FeatureEnvelope(Strict):
    schema_version: Literal["polar.synthetic-feature-view-input/1"]
    synthetic: Literal[True]
    timing_model: Literal["synthetic_replay"]
    features: list[ViewFeature] = Field(max_length=MAX_RECORDS)

    @model_validator(mode="before")
    @classmethod
    def explicit_synthetic(cls, value):
        if isinstance(value, dict) and value.get("synthetic") is not True:
            raise ValueError("SYNTHETIC_TRUE_REQUIRED")
        return value


def _cutoff(value):
    try:
        if not isinstance(value, str) or len(value) > 64:
            raise ValueError
        result = datetime.fromisoformat(value)
        if result.tzinfo is None or result.utcoffset() != timedelta(0):
            raise ValueError
        return result
    except (ValueError, OverflowError):
        raise FeatureViewError("INVALID_DECISION_AT") from None


def _key(feature):
    return (feature.instrument_id, feature.feature_id,
            feature.event_time, feature.effective_time)


def _clock(feature):
    return max(feature.published_at, feature.available_at, feature.ingested_at)


def asof_features(raw_bytes: bytes, decision_at: str) -> dict:
    """Return a pure deterministic audited view, with no I/O or clock reads.

    Canonical input identity ignores feature-list order but preserves every
    validated revision. Source identity always hashes the exact original bytes.
    """
    if not isinstance(raw_bytes, bytes):
        raise FeatureViewError("INVALID_INPUT_TYPE")
    if len(raw_bytes) > MAX_INPUT_BYTES:
        raise FeatureViewError("INPUT_TOO_LARGE")
    cutoff = _cutoff(decision_at)
    try:
        envelope = FeatureEnvelope.model_validate_json(raw_bytes)
    except (ValidationError, ValueError, ArithmeticError, RecursionError):
        raise FeatureViewError("INVALID_FEATURE_INPUT") from None

    groups = {}
    seen = set()
    for feature in envelope.features:
        key = _key(feature)
        revision_key = (*key, feature.source_revision)
        if revision_key in seen:
            raise FeatureViewError("DUPLICATE_REVISION")
        seen.add(revision_key)
        groups.setdefault(key, []).append(feature)

    selected, diagnostics = [], []
    for key in sorted(groups):
        revisions = sorted(groups[key], key=lambda f: f.source_revision)
        eligible = [f for f in revisions
                    if max(f.event_time, f.effective_time, _clock(f)) <= cutoff]
        winner = None
        if eligible:
            latest = max(_clock(f) for f in eligible)
            winners = [f for f in eligible if _clock(f) == latest]
            if len(winners) != 1:
                raise FeatureViewError("AMBIGUOUS_REVISION")
            winner = winners[0]
            selected.append(winner.model_dump(mode="json"))
        for feature in revisions:
            record = feature.model_dump(mode="json")
            reason = ("SELECTED" if feature is winner else
                      "SUPERSEDED" if max(feature.event_time, feature.effective_time,
                                          _clock(feature)) <= cutoff else
                      "NOT_AVAILABLE_AT_DECISION")
            diagnostics.append({
                "observation_key": {k: record[k] for k in
                                    ("instrument_id", "feature_id", "event_time", "effective_time")},
                "source_revision": feature.source_revision,
                "reason": reason,
            })

    body = envelope.model_dump(mode="json")
    body["features"] = sorted(body["features"], key=canonical)
    return {
        "schema_version": "polar.asof-feature-view/1",
        "synthetic": True,
        "timing_model": "synthetic_replay",
        "decision_at": cutoff.isoformat().replace("+00:00", "Z"),
        "source_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "canonical_input_hash": digest(body),
        "status": ("NO_DATA" if not envelope.features else
                   "SELECTED" if selected else "NO_ELIGIBLE_FEATURES"),
        "selected": selected,
        "diagnostics": diagnostics,
        "source_qualification": "SYNTHETIC_ONLY",
        "investment_evaluation": "NOT_RUN",
    }

"""Pure, bounded inspection of the existing synthetic Dataset contract."""
import hashlib
from decimal import Context, Decimal, localcontext

from pydantic import ValidationError

from .codec import digest
from .models import Dataset

MAX_INPUT_BYTES = 1024**2
SCHEMA_VERSION = "polar.dataset-quality/1"


class InspectionError(ValueError):
    """Stable public diagnostic; never contains source bytes or validation details."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def inspect_dataset(raw_bytes: bytes) -> dict:
    """Validate without I/O; report canonical identity and source-byte identity.

    No source rows or prices are returned. JSON output is bounded by six times
    the input limit plus 4 KiB (including Unicode escaping). Fractions use decimal strings and a
    fixed local precision, independent of the caller's decimal context.
    """
    if not isinstance(raw_bytes, bytes):
        raise InspectionError("INVALID_INPUT_TYPE")
    if len(raw_bytes) > MAX_INPUT_BYTES:
        raise InspectionError("INPUT_TOO_LARGE")
    try:
        data = Dataset.model_validate_json(raw_bytes)
    except (ValidationError, ValueError, ArithmeticError, RecursionError):
        raise InspectionError("INVALID_DATASET") from None

    expected = len(data.sessions)
    observed = sum(b.price_status == "OBSERVED" for b in data.bars)
    settlement = sum(b.price_status == "SETTLEMENT_ONLY" for b in data.bars)
    missing = expected - observed - settlement
    with localcontext(Context(prec=28)):
        fraction = str(Decimal(observed) / Decimal(expected)) if expected else None
        missing_fraction = str(Decimal(missing) / Decimal(expected)) if expected else None
    body = data.model_dump(mode="json")
    content_hash = digest(body)
    return {
        "schema_version": SCHEMA_VERSION,
        "dataset_id": "ds-" + content_hash,
        "content_hash": content_hash,
        "source_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "dataset_schema_version": data.schema_version,
        "synthetic": data.synthetic,
        "timing_model": data.timing_model,
        "price_basis": data.price_basis,
        "market_profile": body["market_profile"],
        "status": "NO_DATA" if not data.bars else "INSPECTED",
        "counts": {
            "expected_sessions": expected,
            "present_bars": len(data.bars),
            "observed_bars": observed,
            "settlement_only_bars": settlement,
            "missing_price_sessions": missing,
            "actions_by_kind": {
                kind: sum(a.kind == kind for a in data.actions)
                for kind in ("split", "dividend", "delisting_cash_settlement")
            },
            "features": len({f.feature_id for f in data.features}),
            "feature_revisions": len(data.features),
        },
        "observed_fraction": fraction,
        "missing_fraction": missing_fraction,
        "source_qualification": "SYNTHETIC_ONLY",
        "investment_evaluation": "NOT_RUN",
    }

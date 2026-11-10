"""Public saved research projections; immutable publication, no financial calculation.

Licensed source objects and physical execution receipts stay outside this wire.
The producer supplies every value. Recorded independent assessments bind the
content ID; absent assessments are explicitly NOT_REVIEWED.
"""
import re
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .history_bundle import HistoryError, canonical, decode, read_file, safe_root, sha
from .history_store import HistoryStore

MAX_RESULT = 8 * 1024**2
Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")]
Hash = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Revision = Annotated[str, Field(pattern=r"^[a-f0-9]{40}$")]
Text = Annotated[str, Field(min_length=1, max_length=1000)]
Token = Annotated[str, Field(pattern=r"^-?(?:0|[1-9][0-9]{0,255})(?:\.[0-9]{1,4096})?$")]


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Value(Closed):
    value: Token | None
    status: Literal["OK", "UNAVAILABLE", "INVALID", "NOT_APPLICABLE", "NOT_RUN"]
    reason: Identifier | None

    @model_validator(mode="after")
    def availability(self):
        if self.status == "OK":
            if self.value is None or self.reason is not None:
                raise ValueError("OK_REQUIRES_VALUE")
        elif self.value is not None or self.reason is None:
            raise ValueError("UNAVAILABLE_REQUIRES_NULL_REASON")
        return self


class Identity(Closed):
    id: Identifier
    label: Text


class Question(Identity):
    summary: Text


class Bindings(Closed):
    protocol_id: Identifier
    protocol_sha256: Hash
    data_revision: Identifier
    data_sha256: Hash
    code_revision: Revision
    evaluator_revision: Revision
    runtime_id: Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]
    producer_id: Identifier
    candidate_id: Identifier
    experiment_id: Identifier


class Basis(Closed):
    currency: Identifier
    frequency: Literal["DAILY"]
    timezone: Annotated[str, Field(pattern=r"^(?:UTC|[A-Za-z_]+/[A-Za-z_]+(?:/[A-Za-z_]+)?)$")]
    wealth_basis: Literal["PRICE_ONLY", "TOTAL_RETURN", "SYNTHETIC_VENDOR_ADJUSTED_REFERENCE_UNIT"]
    cost_basis: Literal["NET", "GROSS_SAME_TAPE"]
    cash_basis: Text
    risk_free_basis: Text


class LedgerPoint(Closed):
    cash: Token | None
    exposure: Token | None
    cumulative_flat_fees: Token | None
    cumulative_bps_fees: Token | None
    positions: dict[Identifier, Annotated[int, Field(ge=0, le=1000000000)]]
    net_return: Value


class Series(Identity):
    role: Literal["STRATEGY", "BENCHMARK", "CONTROL"]
    unit: Literal["USD"]
    values: Annotated[list[Value], Field(min_length=1, max_length=10000)]
    ledger: Annotated[list[LedgerPoint], Field(min_length=1, max_length=10000)]


class Metric(Identity):
    unit: Identifier
    values: dict[Identifier, Value]


class Comparison(Closed):
    metric_id: Identifier
    left_id: Identifier
    right_id: Identifier
    unit: Identifier
    result: Value
    interpretation: Text


class Cost(Identity):
    kind: Literal["CHARGED_FEES", "MODELED_SPREAD", "MODELED_SLIPPAGE", "UNMODELED"]
    unit: Identifier
    values: dict[Identifier, Value]
    description: Text


class Limitation(Closed):
    code: Identifier
    text: Text
    scope: Text


class Provenance(Closed):
    role: Identifier
    id: Identifier
    sha256: Hash


class Criterion(Closed):
    id: Identifier
    description: Text
    status: Literal["MET", "NOT_MET", "UNAVAILABLE"]
    reason: Identifier | None


class ResearchResult(Closed):
    schema_version: Literal["polar.research-result/1"]
    question: Question
    bindings: Bindings
    basis: Basis
    grid: Annotated[list[str], Field(min_length=1, max_length=10000)]
    series: Annotated[list[Series], Field(min_length=2, max_length=5)]
    primary_benchmark_id: Identifier
    metrics: Annotated[list[Metric], Field(min_length=1, max_length=40)]
    comparisons: Annotated[list[Comparison], Field(max_length=40)]
    costs: Annotated[list[Cost], Field(min_length=1, max_length=20)]
    limitations: Annotated[list[Limitation], Field(min_length=1, max_length=30)]
    provenance: Annotated[list[Provenance], Field(min_length=1, max_length=30)]
    evidence_level: Literal["INVENTED_CONTROL", "RETAINED_DESCRIPTIVE", "HISTORICAL_RESEARCH"]
    financial_claim: Text
    criteria: Annotated[list[Criterion], Field(max_length=20)]
    point_interpretation: Text

    @model_validator(mode="after")
    def aligned(self):
        ids = [s.id for s in self.series]
        if len(set(ids)) != len(ids) or sum(s.role == "STRATEGY" for s in self.series) != 1:
            raise ValueError("SERIES_IDENTITY")
        if not any(s.id == self.primary_benchmark_id and s.role == "BENCHMARK" for s in self.series):
            raise ValueError("PRIMARY_BENCHMARK")
        parsed = []
        for stamp in self.grid:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z", stamp):
                raise ValueError("NOMINAL_UTC_GRID")
            # Values are nominal observation instants, not source publication clocks.
            parsed.append(datetime.fromisoformat(stamp.replace("Z", "+00:00")))
        if any(b <= a for a, b in zip(parsed, parsed[1:])):
            raise ValueError("GRID_ORDER")
        if any(len(s.values) != len(self.grid) or len(s.ledger) != len(self.grid) for s in self.series):
            raise ValueError("EXPLICIT_COMMON_GRID_REQUIRED")
        if len({m.id for m in self.metrics}) != len(self.metrics):
            raise ValueError("DUPLICATE_METRIC")
        for item in [*self.metrics, *self.costs]:
            if set(item.values) != set(ids):
                raise ValueError("METRIC_LEG_SET")
        for item in self.comparisons:
            if item.left_id not in ids or item.right_id not in ids or item.metric_id not in {m.id for m in self.metrics}:
                raise ValueError("COMPARISON_IDENTITY")
        return self


class ResearchReview(Closed):
    schema_version: Literal["polar.research-review/1"]
    result_id: Annotated[str, Field(pattern=r"^research-[a-f0-9]{64}$")]
    content_sha256: Hash
    reviewer_id: Identifier
    scope: Literal["TECHNICAL", "PRODUCT", "FINANCIAL"]
    verdict: Literal["PASS", "FAIL", "HOLD", "SUPPORTED_WITH_LIMITS", "NOT_SUPPORTED", "INDETERMINATE"]
    scope_description: Text
    reference: Provenance
    recorded_at: Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")]
    evidence_status: Literal["NOT_APPLICABLE", "NOT_RUN", "INVALID", "INSUFFICIENT_EVIDENCE", "ASSESSED_WITH_LIMITS"]
    reason: Identifier | None

    @model_validator(mode="after")
    def scope_verdict(self):
        datetime.fromisoformat(self.recorded_at.replace("Z", "+00:00"))
        allowed = ({"SUPPORTED_WITH_LIMITS", "NOT_SUPPORTED", "INDETERMINATE"}
                   if self.scope == "FINANCIAL" else {"PASS", "FAIL", "HOLD"})
        if self.verdict not in allowed:
            raise ValueError("REVIEW_SCOPE_VERDICT")
        if self.scope == "FINANCIAL":
            if self.evidence_status == "NOT_APPLICABLE" or (self.evidence_status != "ASSESSED_WITH_LIMITS" and self.reason is None):
                raise ValueError("FINANCIAL_EVIDENCE_STATUS")
        elif self.evidence_status != "NOT_APPLICABLE":
            raise ValueError("NONFINANCIAL_EVIDENCE_STATUS")
        return self


class ResearchError(Exception):
    def __init__(self, code, status=409):
        self.code, self.status = code, status
        super().__init__(code)


def validate_result(value):
    try:
        public = ResearchResult.model_validate(value).model_dump(mode="json")
        public_text(public)
        return public
    except (ValidationError, ValueError, TypeError):
        raise ResearchError("RESEARCH_INVALID_RESULT", 422) from None


def public_text(value):
    """Reject physical paths in any free text, not only structured provenance.

    This is an additional fail-closed local-path boundary, not a generic secret
    detector. The trusted publisher must still provide public/sanitized content.
    """
    if isinstance(value, str):
        if re.search(r"(?i)(?:file:|[A-Z]:[\\/]|(?:^|[\s(=\"'])/\S+)", value):
            raise ValueError("PUBLIC_RESULT_CONTAINS_PHYSICAL_PATH")
    elif isinstance(value, list):
        for item in value:
            public_text(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            public_text(key)
            public_text(item)


class ResearchResults(HistoryStore):
    """Use the service's existing artifact root and atomic publication primitive."""

    def publish(self, value):
        value = validate_result(value)
        raw = canonical(value)
        if len(raw) > MAX_RESULT:
            raise ResearchError("RESEARCH_RESULT_TOO_LARGE", 413)
        result_id = "research-" + sha(raw)
        with self.locked():
            self._publish("research-results", result_id, {"result.json": raw}, file_limit=MAX_RESULT)
        return {"schema_version": "polar.research-publication/1", "result_id": result_id,
                "content_sha256": sha(raw), "review_status": "NOT_REVIEWED"}

    def read(self, result_id):
        if not isinstance(result_id, str) or not re.fullmatch(r"research-[a-f0-9]{64}", result_id):
            raise ResearchError("RESEARCH_INVALID_ID", 422)
        safe_root(self.root)
        try:
            raw = read_file(self.root, "research-results/" + result_id + "/result.json", MAX_RESULT)
        except FileNotFoundError:
            raise ResearchError("RESEARCH_NOT_FOUND", 404) from None
        directory = self.root / "research-results" / result_id
        if {p.name for p in directory.iterdir()} != {"result.json"} or sha(raw) != result_id[9:]:
            raise ResearchError("RESEARCH_CONTENT_MISMATCH")
        record = validate_result(decode(raw))
        if canonical(record) != raw:
            raise ResearchError("RESEARCH_NONCANONICAL_RESULT")
        assessment = {"technical": "NOT_REVIEWED", "product": "NOT_REVIEWED",
                      "financial": "NOT_REVIEWED", "reviews": [],
                      "financial_evidence": {"status": "NOT_RUN", "reason": "INDEPENDENT_REVIEW_NOT_RECORDED"}}
        parent = self.root / "research-reviews" / result_id
        if parent.is_symlink() or (self.root / "research-reviews").is_symlink():
            raise ResearchError("RESEARCH_UNSAFE_DIRECTORY")
        if parent.exists():
            names = list(parent.iterdir())
            if len(names) > 100:
                raise ResearchError("RESEARCH_REVIEW_BOUND")
            for entry in names:
                if entry.name.startswith(".history-partial-"):
                    continue
                if entry.is_symlink() or not re.fullmatch(r"[a-f0-9]{64}", entry.name):
                    raise ResearchError("RESEARCH_UNSAFE_DIRECTORY")
                body = read_file(self.root, f"research-reviews/{result_id}/{entry.name}/review.json", 16384)
                try:
                    review = ResearchReview.model_validate(decode(body)).model_dump(mode="json")
                    public_text(review)
                except (ValidationError, ValueError, TypeError):
                    raise ResearchError("RESEARCH_INVALID_REVIEW") from None
                if (sha(body) != entry.name or canonical(review) != body or
                        review["result_id"] != result_id or review["content_sha256"] != sha(raw) or
                        review["reviewer_id"] == record["bindings"]["producer_id"]):
                    raise ResearchError("RESEARCH_REVIEW_BINDING")
                assessment["reviews"].append({**review, "review_sha256": sha(body)})
            assessment["reviews"].sort(key=lambda r: (r["recorded_at"], r["review_sha256"]))
            for review in assessment["reviews"]:
                assessment[review["scope"].lower()] = review["verdict"]
                if review["scope"] == "FINANCIAL":
                    assessment["financial_evidence"] = {"status": review["evidence_status"], "reason": review["reason"]}
        return {"schema_version": "polar.research-detail/1", "result_id": result_id,
                "content_sha256": sha(raw), "record": record,
                "assessment": assessment}

    def review(self, value):
        try:
            review = ResearchReview.model_validate(value).model_dump(mode="json")
            public_text(review)
        except (ValidationError, ValueError, TypeError):
            raise ResearchError("RESEARCH_INVALID_REVIEW", 422) from None
        detail = self.read(review["result_id"])
        if (review["content_sha256"] != detail["content_sha256"] or
                review["reviewer_id"] == detail["record"]["bindings"]["producer_id"]):
            raise ResearchError("RESEARCH_REVIEW_BINDING")
        body = canonical(review)
        with self.locked():
            self._publish("research-reviews/" + review["result_id"], sha(body),
                          {"review.json": body}, file_limit=16384)
        return {"result_id": review["result_id"], "review_sha256": sha(body),
                "status": "RECORDED_EXTERNAL_ASSESSMENT"}

    def catalog(self, limit=10, offset=0):
        if type(limit) is not int or type(offset) is not int or not 1 <= limit <= 10 or not 0 <= offset <= 4096:
            raise ResearchError("RESEARCH_INVALID_PAGE", 422)
        safe_root(self.root)
        parent = self.root / "research-results"
        if parent.is_symlink():
            raise ResearchError("RESEARCH_UNSAFE_DIRECTORY")
        names = []
        if parent.exists():
            for p in parent.iterdir():
                if p.name.startswith(".history-partial-"):
                    continue
                if p.is_symlink() or not re.fullmatch(r"research-[a-f0-9]{64}", p.name):
                    raise ResearchError("RESEARCH_UNSAFE_DIRECTORY")
                names.append(p.name)
                if len(names) > 4096:
                    raise ResearchError("RESEARCH_CATALOG_BOUND")
        items = []
        for name in sorted(names)[offset:offset + limit]:
            detail = self.read(name)
            record = detail["record"]
            items.append({"result_id": name, "content_sha256": detail["content_sha256"],
                          "question": record["question"], "bindings": record["bindings"],
                          "basis": record["basis"], "evidence_level": record["evidence_level"],
                          "assessment": detail["assessment"]})
        return {"schema_version": "polar.research-catalog/1", "items": items,
                "limit": limit, "offset": offset, "total": len(names),
                "next_offset": offset + limit if offset + limit < len(names) else None}

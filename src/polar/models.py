from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, BeforeValidator, model_validator

from .codec import digest


def decimal_string(v):
    if not isinstance(v, str) or len(v) > 40:
        raise ValueError("DECIMAL_STRING_REQUIRED")
    n = Decimal(v)
    if not n.is_finite() or abs(n) > Decimal("1e12") or n.as_tuple().exponent < -12:
        raise ValueError("DECIMAL_OUT_OF_BOUNDS")
    return n


Number = Annotated[Decimal, BeforeValidator(decimal_string)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Provenance(Strict):
    event_time: datetime
    effective_time: datetime
    published_at: datetime
    available_at: datetime
    ingested_at: datetime
    source_revision: str = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def temporal(self):
        times = [self.event_time,self.effective_time,self.published_at,self.available_at,self.ingested_at]
        if any(t.tzinfo is None or t.utcoffset().total_seconds() != 0 for t in times):
            raise ValueError("UTC_REQUIRED")
        if self.published_at > self.available_at or self.available_at > self.ingested_at:
            raise ValueError("PROVENANCE_ORDER")
        return self


class Session(Strict):
    session_id: str = Field(min_length=1,max_length=32)
    open_at: datetime
    close_at: datetime

    @model_validator(mode="after")
    def temporal(self):
        if any(t.tzinfo is None or t.utcoffset().total_seconds() != 0 for t in [self.open_at,self.close_at]):
            raise ValueError("UTC_REQUIRED")
        if self.open_at >= self.close_at:
            raise ValueError("SESSION_ORDER")
        return self


class Bar(Provenance):
    instrument_id: str
    session_id: str
    open: Number | None
    high: Number | None
    low: Number | None
    close: Number | None
    tradable: bool
    price_status: Literal["OBSERVED", "SETTLEMENT_ONLY", "MISSING"]
    open_provenance: Provenance

    @model_validator(mode="after")
    def prices(self):
        for p in [self.open,self.high,self.low,self.close]:
            if p is not None and p <= 0:
                raise ValueError("NONPOSITIVE_PRICE")
        if self.price_status == "OBSERVED":
            if None in [self.open,self.high,self.low,self.close] or not self.tradable:
                raise ValueError("INCOMPLETE_OBSERVED_BAR")
            if self.low > min(self.open,self.close) or self.high < max(self.open,self.close):
                raise ValueError("OHLC_RANGE")
        return self


class Action(Provenance):
    action_id: str
    instrument_id: str
    kind: Literal["split", "dividend", "delisting_cash_settlement"]
    ratio_numerator: Number | None = None
    ratio_denominator: Number | None = None
    cash_per_share: Number | None = None
    currency: Literal["USD"] | None = None
    entitlement_at: datetime | None = None
    ex_at: datetime | None = None
    pay_at: datetime | None = None

    @model_validator(mode="after")
    def valid_action(self):
        if self.kind == "split":
            if self.ratio_numerator is None or self.ratio_denominator is None or min(self.ratio_numerator,self.ratio_denominator) <= 0:
                raise ValueError("INVALID_SPLIT")
        elif self.cash_per_share is None or self.cash_per_share < 0 or self.currency != "USD":
            raise ValueError("INVALID_CASH_ACTION")
        if self.kind == "dividend" and (self.ex_at != self.effective_time or self.pay_at != self.effective_time or self.entitlement_at is None):
            raise ValueError("ONLY_SAME_DAY_DIVIDEND_SUPPORTED")
        return self


class Feature(Provenance):
    instrument_id: str
    feature_id: str
    value: Number


class Ticker(Provenance):
    ticker: str
    effective_from: datetime
    effective_until: datetime


class Instrument(Strict):
    instrument_id: str = Field(min_length=1,max_length=64)
    currency: Literal["USD"]
    synthetic: Literal[True]
    ticker_history: list[Ticker] = Field(max_length=1)


class Market(Strict):
    calendar: str
    currency: Literal["USD"]
    frequency: Literal["daily"]
    price_unit: Literal["USD/share"]
    timezone: Literal["America/New_York"]


class Dataset(Strict):
    schema_version: Literal["polar.synthetic-data/1"]
    dataset_name: str = Field(min_length=1,max_length=128)
    synthetic: Literal[True]
    timing_model: Literal["synthetic_replay"]
    price_basis: Literal["raw_unadjusted"]
    seed: str
    market_profile: Market
    instruments: list[Instrument] = Field(min_length=1,max_length=1)
    sessions: list[Session] = Field(max_length=20)
    bars: list[Bar] = Field(max_length=20)
    actions: list[Action] = Field(max_length=20)
    features: list[Feature] = Field(max_length=100)

    @property
    def dataset_id(self):
        return "ds-" + digest(self.model_dump(mode="json"))

    @model_validator(mode="after")
    def consistency(self):
        sessions = {s.session_id:s for s in self.sessions}
        iid = self.instruments[0].instrument_id
        if len(sessions) != len(self.sessions):
            raise ValueError("DUPLICATE_SESSION")
        if any(a.close_at >= b.open_at for a,b in zip(self.sessions,self.sessions[1:])):
            raise ValueError("UNORDERED_SESSIONS")
        if len({b.session_id for b in self.bars}) != len(self.bars):
            raise ValueError("DUPLICATE_BAR")
        if len({a.action_id for a in self.actions}) != len(self.actions):
            raise ValueError("DUPLICATE_ACTION")
        if len({(f.feature_id,f.source_revision) for f in self.features}) != len(self.features):
            raise ValueError("DUPLICATE_FEATURE_REVISION")
        for row in [*self.bars,*self.actions,*self.features]:
            if row.instrument_id != iid:
                raise ValueError("UNKNOWN_INSTRUMENT")
        for b in self.bars:
            s = sessions.get(b.session_id)
            if not s or b.event_time != s.close_at or b.effective_time != s.close_at or b.open_provenance.event_time != s.open_at or b.open_provenance.effective_time != s.open_at:
                raise ValueError("BAR_TIME_MISMATCH")
        opens = {s.open_at for s in self.sessions}
        for a in self.actions:
            if a.effective_time not in opens or a.event_time != a.effective_time or a.available_at > a.effective_time:
                raise ValueError("UNSUPPORTED_ACTION_TIME")
            # This bounded replay requires action records at their effective open.
            # Reject delayed ingestion before any accounting, rather than applying
            # a backfilled action to already reported holdings or NAV.
            if max(a.published_at, a.available_at, a.ingested_at) > a.effective_time:
                raise ValueError("ACTION_NOT_AVAILABLE_AT_EFFECTIVE_TIME")
        return self


class FeatureRef(Strict):
    feature_id: str
    source_revision: str


class Order(Strict):
    decision_session_id: str
    quantity: Number
    features: list[FeatureRef] = Field(default_factory=list,max_length=10)


class RunConfig(Strict):
    dataset_id: str = Field(pattern=r"^ds-[a-f0-9]{64}$")
    strategy_version: Literal["accounting-tape-v1", "cash-flat-v1"] = "accounting-tape-v1"
    protocol_version: Literal["fixture-protocol-v2:3c124b8371cd4852e1cd98a78fa1d673fc87965e78d71ccfeafbf1f9f0ed1e53"]
    initial_cash: Number = Field(default="1000",validate_default=True,gt=0)
    orders: list[Order] = Field(default_factory=list,max_length=20)
    scope_ref: str = Field(min_length=1,max_length=256)
    qitem_ref: str = Field(min_length=1,max_length=128)
    actor: str = Field(min_length=1,max_length=128)
    seed: Literal[0] = 0

    @model_validator(mode="after")
    def strategy(self):
        if self.strategy_version == "cash-flat-v1" and self.orders:
            raise ValueError("CASH_STRATEGY_HAS_ORDERS")
        if len({o.decision_session_id for o in self.orders}) != len(self.orders):
            raise ValueError("DUPLICATE_DECISION")
        return self

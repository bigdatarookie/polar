"""Versioned PRIVATE projection. Does not extend or reinterpret the public wire."""
from typing import Literal, Annotated
from pydantic import BaseModel, ConfigDict, Field, model_validator

Count = Annotated[int, Field(ge=0)]


class Closed(BaseModel):
    model_config = ConfigDict(extra='forbid',strict=True)


class Point(Closed):
    date: str
    nominal_ns: Count
    cash_cents: Count
    exposure_cents: Count
    receivable_cents: Count
    position_cents: dict[str,Count]
    positions: dict[str,Count]
    nav_cents: Annotated[int,Field(gt=0)]
    flat_cents: Count
    bps_cents: Count

    @model_validator(mode='after')
    def accounting(self):
        if (set(self.position_cents)!=set(self.positions) or
            self.exposure_cents!=sum(self.position_cents.values()) or
            self.nav_cents!=self.cash_cents+self.exposure_cents+self.receivable_cents):
            raise ValueError('RAW_PRIVATE_LEDGER_ACCOUNTING')
        return self


class Series(Closed):
    id: str
    role: Literal['STRATEGY','BENCHMARK','CONTROL']
    ledger: Annotated[list[Point],Field(min_length=2,max_length=10000)]


class Basis(Closed):
    currency: Literal['USD']
    quantity: Literal['WHOLE_RAW_SHARE_DECLARED_CURRENT_SOURCE_IDENTITY']
    wealth: Literal['RAW_MARKS_PLUS_CAPTURED_NOMINAL_RECEIVABLES']
    payment: Literal['MODELED_FIRST_REFERENCE_CLOSE_CIVIL_STRICTLY_AFTER_PAYDATE']
    cash: Literal['AVAILABLE_NATIVE_CASH_ONLY']
    receivable: Literal['SEPARATE_NOMINAL_CENTS_NO_DISCOUNT_TAX']
    historical_K: None
    physical_investor_total_return: Literal['NOT_CERTIFIED']


class PrivateResult(Closed):
    schema_version: Literal['polar.private-raw-action-result/1'] = Field(alias='schema')
    phase: Literal['BASE','STRESS']
    bindings: dict
    basis: Basis
    source_context: dict
    series: Annotated[list[Series],Field(min_length=4,max_length=4)]
    primary_benchmark: Literal['RETAIN_CASH']
    evaluation: dict
    diagnostics: dict
    initial_state_control: dict
    financial: Literal['NOT_REVIEWED']
    adoption: Literal['INSUFFICIENT_EVIDENCE']
    robustness: Literal['INSUFFICIENT_EVIDENCE']
    rights: Literal['PRIVATE_ONEOFF_DEMO_NO_DATA_CONTAINING_REDISTRIBUTION_OR_CONTINUING_FEED']
    common_research_result: Literal['NOT_PUBLISHED_NO_LEGACY_FIELD_REDEFINITION']

    @model_validator(mode='after')
    def alignment(self):
        from .raw_action_native import LEGS
        if [s.id for s in self.series]!=list(LEGS):raise ValueError('RAW_PRIVATE_IDENTITIES')
        grid=[r.date for r in self.series[0].ledger]
        if grid!=sorted(set(grid)) or any([r.date for r in s.ledger]!=grid for s in self.series):
            raise ValueError('RAW_PRIVATE_GRID')
        if [s.role for s in self.series]!=['STRATEGY','BENCHMARK','CONTROL','CONTROL']:
            raise ValueError('RAW_PRIVATE_ROLES')
        return self


def validate(value):
    return PrivateResult.model_validate(value).model_dump(mode='json',by_alias=True)

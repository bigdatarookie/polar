"""Pure whole-share target arithmetic. No execution or market-data integration."""
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import (
    Context, Decimal, DecimalException, Inexact, Rounded, localcontext,
)

MAX_NAMES = 1000
MAX_QUANTITY = 10**12
MAX_NUMBER = Decimal("1e12")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}", re.ASCII)
_CURRENCY = re.compile(r"[A-Z]{3}", re.ASCII)


class AllocationError(ValueError):
    """Stable code only; never includes caller values or validation payloads."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class Position:
    instrument_id: str
    quantity: int


@dataclass(frozen=True, slots=True)
class Target:
    instrument_id: str
    weight: Decimal


@dataclass(frozen=True, slots=True)
class Mark:
    instrument_id: str
    price: Decimal
    currency: str
    as_of: datetime


@dataclass(frozen=True, slots=True)
class Snapshot:
    cash: Decimal
    currency: str
    as_of: datetime
    positions: tuple[Position, ...]
    targets: tuple[Target, ...]
    marks: tuple[Mark, ...]


@dataclass(frozen=True, slots=True)
class AllocationRow:
    instrument_id: str
    current_quantity: int
    target_weight: Decimal
    mark: Decimal
    desired_quantity: int
    delta: int


@dataclass(frozen=True, slots=True)
class Allocation:
    currency: str
    as_of: datetime
    marked_nav: Decimal
    total_target_weight: Decimal
    allocated_value: Decimal
    residual_cash: Decimal
    rows: tuple[AllocationRow, ...]
    method: str = field(default="ZERO_COST_ALLOCATION_ARITHMETIC", init=False)
    financial_verdict: str = field(default="NOT_RUN", init=False)


def _number(value):
    if not isinstance(value, Decimal):
        raise AllocationError("DECIMAL_REQUIRED")
    if (not value.is_finite() or value.copy_abs() > MAX_NUMBER
            or value.as_tuple().exponent < -12
            or len(value.as_tuple().digits) > 40 or len(str(value)) > 40):
        raise AllocationError("DECIMAL_OUT_OF_BOUNDS")
    # Avoid extreme positive exponents on numerical zeros during arithmetic.
    # No value is rounded or changed; the caller's frozen object is untouched.
    return value if value else Decimal(0)


def _utc(value):
    if not isinstance(value, datetime):
        raise AllocationError("UTC_REQUIRED")
    try:
        valid = value.tzinfo is not None and value.utcoffset() == timedelta(0)
    except (ValueError, OverflowError):
        valid = False
    if not valid:
        raise AllocationError("UTC_REQUIRED")


def _index(rows, row_type, max_names):
    if not isinstance(rows, tuple):
        raise AllocationError("IMMUTABLE_TUPLE_REQUIRED")
    if len(rows) > max_names:
        raise AllocationError("NAME_LIMIT")
    result = {}
    for row in rows:
        if not isinstance(row, row_type):
            raise AllocationError("INVALID_ROW_TYPE")
        if not isinstance(row.instrument_id, str) or not _ID.fullmatch(row.instrument_id):
            raise AllocationError("INVALID_INSTRUMENT_ID")
        if row.instrument_id in result:
            raise AllocationError("DUPLICATE_" + row_type.__name__.upper())
        result[row.instrument_id] = row
    return result


def allocate(snapshot: Snapshot, *, max_names: int) -> Allocation:
    """Use one explicit currency/UTC mark snapshot and a caller name limit.

    Inputs use existing Decimal magnitude/scale/text bounds. Derived totals and
    desired quantities are not clipped to input bounds. All held/targeted names
    (even zero rows) need exactly one mark; extra marks also reject. Invalid
    inputs raise AllocationError(code), without coercion or weight normalization.
    """
    if type(max_names) is not int or not 1 <= max_names <= MAX_NAMES:
        raise AllocationError("INVALID_NAME_LIMIT")
    if not isinstance(snapshot, Snapshot):
        raise AllocationError("INVALID_SNAPSHOT")
    if not isinstance(snapshot.currency, str) or not _CURRENCY.fullmatch(snapshot.currency):
        raise AllocationError("INVALID_CURRENCY")
    _utc(snapshot.as_of)
    cash = _number(snapshot.cash)
    if cash < 0:
        raise AllocationError("NEGATIVE_CASH")
    positions = _index(snapshot.positions, Position, max_names)
    targets = _index(snapshot.targets, Target, max_names)
    marks = _index(snapshot.marks, Mark, max_names)
    names = positions.keys() | targets.keys()
    if len(names | marks.keys()) > max_names:
        raise AllocationError("NAME_LIMIT")
    if names - marks.keys():
        raise AllocationError("MISSING_MARK")
    if marks.keys() - names:
        raise AllocationError("UNEXPECTED_MARK")
    for position in positions.values():
        if type(position.quantity) is not int or not 0 <= position.quantity <= MAX_QUANTITY:
            raise AllocationError("INVALID_POSITION_QUANTITY")
    weights = {}
    for instrument_id, target in targets.items():
        weights[instrument_id] = _number(target.weight)
        if weights[instrument_id] < 0:
            raise AllocationError("NEGATIVE_WEIGHT")
    for mark in marks.values():
        if _number(mark.price) <= 0:
            raise AllocationError("NONPOSITIVE_MARK")
        if not isinstance(mark.currency, str) or mark.currency != snapshot.currency:
            raise AllocationError("CURRENCY_MISMATCH")
        _utc(mark.as_of)
        if mark.as_of != snapshot.as_of:
            raise AllocationError("MARK_SNAPSHOT_MISMATCH")

    # <=1000 names, quantity/price<=1e12, scale<=12: NAV<=1.001e27;
    # NAV*weight has <=52 significant digits. Decimal // yields an integer
    # quotient directly, avoiding rounded division before the floor boundary.
    context = Context(prec=100)
    context.traps[Inexact] = context.traps[Rounded] = True
    try:
        with localcontext(context):
            total_weight = sum(weights.values(), Decimal(0))
            if total_weight > 1:
                raise AllocationError("WEIGHT_SUM_EXCEEDS_ONE")
            nav = cash + sum((p.quantity * marks[k].price for k, p in positions.items()), Decimal(0))
            rows, allocated = [], Decimal(0)
            for instrument_id in sorted(names):
                current = positions[instrument_id].quantity if instrument_id in positions else 0
                weight = weights.get(instrument_id, Decimal(0))
                price = marks[instrument_id].price
                desired = int((nav * weight) // price)
                allocated += desired * price
                rows.append(AllocationRow(instrument_id, current, weight, price, desired, desired-current))
            return Allocation(snapshot.currency, snapshot.as_of, nav, total_weight,
                              allocated, nav-allocated, tuple(rows))
    except DecimalException:
        raise AllocationError("ARITHMETIC_BOUND") from None

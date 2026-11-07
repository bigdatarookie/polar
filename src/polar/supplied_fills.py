"""Pure accounting for supplied executed fills; no execution/settlement model."""
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Context, Decimal, DecimalException, Inexact, Rounded, localcontext

from .allocation import Position

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}", re.ASCII)
_CURRENCY = re.compile(r"[A-Z]{3}", re.ASCII)
_MAX_INTEGER = 10**12
_MAX_DECIMAL = Decimal("1e12")


class LedgerError(ValueError):
    """Stable diagnostic only, without caller values or partial accounting."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class LedgerSnapshot:
    cash: Decimal
    currency: str
    as_of: datetime
    positions: tuple[Position, ...]
    applied_fill_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SuppliedFill:
    fill_id: str
    instrument_id: str
    quantity: int
    price: Decimal
    fee: Decimal
    currency: str
    execution_at: datetime
    receipt_at: datetime
    sequence: int


@dataclass(frozen=True, slots=True)
class Receipt:
    fill_id: str
    instrument_id: str
    quantity: int
    price: Decimal
    fee: Decimal
    currency: str
    execution_at: datetime
    receipt_at: datetime
    sequence: int
    cash_before: Decimal
    cash_after: Decimal
    position_before: int
    position_after: int


@dataclass(frozen=True, slots=True)
class LedgerResult:
    snapshot: LedgerSnapshot
    receipts: tuple[Receipt, ...]
    total_fees: Decimal
    method: str = field(default="SUPPLIED_FILL_ACCOUNTING", init=False)
    financial_verdict: str = field(default="NOT_RUN", init=False)


def _id(value):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise LedgerError("INVALID_ID")


def _utc(value):
    if not isinstance(value, datetime):
        raise LedgerError("UTC_REQUIRED")
    try:
        valid = value.tzinfo is not None and value.utcoffset() == timedelta(0)
    except (ValueError, OverflowError):
        valid = False
    if not valid:
        raise LedgerError("UTC_REQUIRED")


def _number(value):
    if not isinstance(value, Decimal):
        raise LedgerError("DECIMAL_REQUIRED")
    if (not value.is_finite() or value.copy_abs() > _MAX_DECIMAL
            or value.as_tuple().exponent < -12 or len(value.as_tuple().digits) > 40
            or len(str(value)) > 40):
        raise LedgerError("DECIMAL_OUT_OF_BOUNDS")
    return value if value else Decimal(0)


def apply_supplied_fills(snapshot: LedgerSnapshot, fills: tuple[SuppliedFill, ...],
                         cutoff: datetime, *, max_names: int, max_events: int) -> LedgerResult:
    """Atomically account in supplied order with bounded external snapshots.

    Derived totals are not clipped, but resubmission outside the input domain
    rejects, even for an empty batch. As-of records received supplied events,
    without claiming settlement or a complete arrival stream. No I/O or clock.
    """
    if any(type(n) is not int or not 1 <= n <= 1000 for n in (max_names, max_events)):
        raise LedgerError("INVALID_LIMIT")
    if not isinstance(snapshot, LedgerSnapshot):
        raise LedgerError("INVALID_SNAPSHOT")
    if any(not isinstance(v, tuple) for v in (snapshot.positions, snapshot.applied_fill_ids, fills)):
        raise LedgerError("IMMUTABLE_TUPLE_REQUIRED")
    if not isinstance(snapshot.currency, str) or not _CURRENCY.fullmatch(snapshot.currency):
        raise LedgerError("INVALID_CURRENCY")
    _utc(snapshot.as_of)
    _utc(cutoff)
    if cutoff < snapshot.as_of:
        raise LedgerError("CUTOFF_BEFORE_SNAPSHOT")
    cash = _number(snapshot.cash)
    if cash < 0:
        raise LedgerError("NEGATIVE_CASH")
    if len(snapshot.positions) > max_names:
        raise LedgerError("NAME_LIMIT")
    if len(snapshot.applied_fill_ids) + len(fills) > max_events:
        raise LedgerError("EVENT_LIMIT")
    positions, seen = {}, set()
    for position in snapshot.positions:
        if not isinstance(position, Position):
            raise LedgerError("INVALID_POSITION")
        _id(position.instrument_id)
        if position.instrument_id in positions:
            raise LedgerError("DUPLICATE_POSITION")
        if type(position.quantity) is not int or not 0 <= position.quantity <= _MAX_INTEGER:
            raise LedgerError("INVALID_POSITION_QUANTITY")
        positions[position.instrument_id] = position.quantity
    for fill_id in snapshot.applied_fill_ids:
        _id(fill_id)
        if fill_id in seen:
            raise LedgerError("DUPLICATE_FILL_ID")
        seen.add(fill_id)
    names = set(positions)
    previous_sequence, previous_execution = -1, snapshot.as_of
    numbers = []
    for fill in fills:
        if not isinstance(fill, SuppliedFill):
            raise LedgerError("INVALID_FILL")
        _id(fill.fill_id)
        _id(fill.instrument_id)
        if fill.fill_id in seen:
            raise LedgerError("DUPLICATE_FILL_ID")
        seen.add(fill.fill_id)
        names.add(fill.instrument_id)
        if len(names) > max_names:
            raise LedgerError("NAME_LIMIT")
        if type(fill.quantity) is not int or not 0 < abs(fill.quantity) <= _MAX_INTEGER:
            raise LedgerError("INVALID_FILL_QUANTITY")
        price, fee = _number(fill.price), _number(fill.fee)
        if price <= 0:
            raise LedgerError("NONPOSITIVE_PRICE")
        if fee < 0:
            raise LedgerError("NEGATIVE_FEE")
        if not isinstance(fill.currency, str) or fill.currency != snapshot.currency:
            raise LedgerError("CURRENCY_MISMATCH")
        _utc(fill.execution_at)
        _utc(fill.receipt_at)
        if (fill.execution_at < snapshot.as_of or fill.execution_at > fill.receipt_at
                or fill.receipt_at > cutoff):
            raise LedgerError("INVALID_FILL_TIME")
        if type(fill.sequence) is not int or not 0 <= fill.sequence <= _MAX_INTEGER:
            raise LedgerError("INVALID_SEQUENCE")
        if fill.sequence <= previous_sequence or fill.execution_at < previous_execution:
            raise LedgerError("UNORDERED_FILLS")
        previous_sequence, previous_execution = fill.sequence, fill.execution_at
        numbers.append((price, fee))

    context = Context(prec=100)
    context.traps[Inexact] = context.traps[Rounded] = True
    receipts = []
    try:
        with localcontext(context):
            total_fees = Decimal(0)
            for fill, (price, fee) in zip(fills, numbers):
                before = positions.get(fill.instrument_id, 0)
                after = before + fill.quantity
                new_cash = cash - fill.quantity * price - fee
                if new_cash < 0:
                    raise LedgerError("INSUFFICIENT_CASH")
                if after < 0:
                    raise LedgerError("INSUFFICIENT_POSITION")
                receipts.append(Receipt(fill.fill_id, fill.instrument_id, fill.quantity, fill.price,
                    fill.fee, fill.currency, fill.execution_at, fill.receipt_at, fill.sequence,
                    cash, new_cash, before, after))
                positions[fill.instrument_id], cash = after, new_cash
                total_fees += fee
    except DecimalException:
        raise LedgerError("ARITHMETIC_BOUND") from None
    # No partial receipts escape when a validation/accounting step raises.
    final_time = max((f.receipt_at for f in fills), default=snapshot.as_of)
    final = LedgerSnapshot(cash, snapshot.currency, final_time,
        tuple(Position(k, positions.get(k, 0)) for k in sorted(names)),
        snapshot.applied_fill_ids + tuple(f.fill_id for f in fills))
    return LedgerResult(final, tuple(receipts), total_fees)

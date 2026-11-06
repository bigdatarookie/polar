"""Literal expectations fixed before author implementation; no market/runtime I/O."""
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D, Inexact, Rounded, localcontext
from itertools import permutations

import pytest

from polar.allocation import AllocationError, Mark, Position, Snapshot, Target, allocate

AT = datetime(2026, 11, 6, 19, tzinfo=timezone.utc)


def snapshot(cash="100", positions=(), targets=(), marks=()):
    return Snapshot(D(cash), "USD", AT,
                    tuple(Position(k, v) for k, v in positions),
                    tuple(Target(k, D(v)) for k, v in targets),
                    tuple(Mark(k, D(v), "USD", AT) for k, v in marks))


def primary():
    return snapshot(positions=(("A", 2), ("C", 4)),
                    targets=(("A", "0.5"), ("B", "0.4")),
                    marks=(("A", "30"), ("B", "70"), ("C", "5")))


@pytest.mark.parametrize("case,nav,desired,deltas,allocated,residual", [
    (primary(), "180", (3, 1, 0), (1, 1, -4), "160", "20"),
    (snapshot(positions=(("A", 2), ("C", 4)), marks=(("A", "30"), ("C", "5"))),
     "180", (0, 0), (-2, -4), "0", "180"),
    (snapshot(), "100", (), (), "0", "100"),
    (snapshot(cash="0", targets=(("A", "1"),), marks=(("A", "7"),)),
     "0", (0,), (0,), "0", "0"),
    (snapshot(cash="10", targets=(("A", "0.5"), ("B", "0.5")),
              marks=(("A", "3"), ("B", "4"))), "10", (1, 1), (1, 1), "7", "3"),
    (snapshot(cash="0", positions=(("A", 1),), targets=(("B", "1"),),
              marks=(("A", "0.3"), ("B", "0.1"))),
     "0.3", (0, 3), (-1, 3), "0.3", "0"),
])
def test_predeclared_hand_literals(case, nav, desired, deltas, allocated, residual):
    result = allocate(case, max_names=3)
    assert result.marked_nav == D(nav)
    assert tuple(row.desired_quantity for row in result.rows) == desired
    assert tuple(row.delta for row in result.rows) == deltas
    assert result.allocated_value == D(allocated)
    assert result.residual_cash == D(residual) >= 0
    assert result.method == "ZERO_COST_ALLOCATION_ARITHMETIC"
    assert result.financial_verdict == "NOT_RUN"
    assert result.currency == "USD" and result.as_of == AT


def test_permutations_are_identical_and_inputs_results_immutable():
    original = primary()
    expected = allocate(original, max_names=3)
    assert tuple(r.instrument_id for r in expected.rows) == ("A", "B", "C")
    assert expected.total_target_weight == D("0.9")
    assert tuple(r.current_quantity for r in expected.rows) == (2, 0, 4)
    for positions in permutations(original.positions):
        for targets in permutations(original.targets):
            for marks in permutations(original.marks):
                case = replace(original, positions=positions, targets=targets, marks=marks)
                assert allocate(case, max_names=3) == expected
    with pytest.raises(FrozenInstanceError): original.cash = D(0)
    with pytest.raises(FrozenInstanceError): original.positions[0].quantity = 0
    with pytest.raises(FrozenInstanceError): expected.residual_cash = D(0)
    with pytest.raises(FrozenInstanceError): expected.rows[0].delta = 0
    assert original == primary()


def test_exact_floor_boundary_and_ambient_context_independence():
    cases = [primary(), snapshot(cash="0.299999999999", targets=(("A", "1"),), marks=(("A", "0.1"),)),
             snapshot(cash="1e12", targets=(("A", "1"),), marks=(("A", "0.000000000003"),))]
    with localcontext() as ctx:
        ctx.prec = 2
        ctx.Emax = 2
        ctx.Emin = -2
        ctx.traps[Inexact] = ctx.traps[Rounded] = True
        results = [allocate(case, max_names=3) for case in cases]
        assert ctx.prec == 2 and ctx.Emax == 2 and ctx.Emin == -2
        assert not any(ctx.flags.values())
    assert results[0] == allocate(primary(), max_names=3)
    assert results[1].rows[0].desired_quantity == 2
    assert results[1].residual_cash == D("0.099999999999")
    assert results[2].rows[0].desired_quantity == 333333333333333333333333
    assert results[2].allocated_value == D("999999999999.999999999999")
    assert results[2].residual_cash == D("0.000000000001")


def test_zero_target_and_zero_holdings_still_require_marks():
    case = snapshot(cash="0", positions=(("A", 0),), targets=(("B", "0"),),
                    marks=(("A", "1"), ("B", "1")))
    result = allocate(case, max_names=2)
    assert result.marked_nav == result.residual_cash == 0
    assert len(result.rows) == 2
    for key in ("A", "B"):
        with pytest.raises(AllocationError, match="^MISSING_MARK$"):
            allocate(replace(case, marks=tuple(m for m in case.marks if m.instrument_id != key)), max_names=2)


def test_input_bounds_and_derived_quantity_not_clipped():
    case = snapshot(cash="1e12", targets=(("A", "1"),), marks=(("A", "1e-12"),))
    result = allocate(case, max_names=1)
    assert result.rows[0].desired_quantity == 10**24
    assert result.residual_cash == 0
    # Exactly 1000 names at maximal positions/prices, without a derived NAV cap.
    names = tuple(f"asset-{i:04}" for i in range(1000))
    case = snapshot(cash="1e12", positions=tuple((k, 10**12) for k in names),
                    targets=((names[0], "1"),), marks=tuple((k, "1e12") for k in names))
    result = allocate(case, max_names=1000)
    assert len(result.rows) == 1000
    assert result.marked_nav == D("1000000000000001000000000000")
    assert result.rows[0].desired_quantity == 1000000000000001
    assert result.residual_cash == 0


def test_zero_representation_is_numerically_exact_without_mutation():
    zero = D("0E+999999999")
    case = replace(snapshot(targets=(("A", "0"),), marks=(("A", "1"),)), cash=zero,
                   targets=(Target("A", zero),))
    result = allocate(case, max_names=1)
    assert result.marked_nav == result.residual_cash == 0
    assert str(case.cash) == "0E+999999999"
    assert str(case.targets[0].weight) == "0E+999999999"


@pytest.mark.parametrize("quantity", [-1, 0.5, D("0.5"), D("1"), True, "1", 10**12+1])
def test_invalid_positions(quantity):
    case = replace(primary(), positions=(Position("A", quantity), Position("C", 4)))
    with pytest.raises(AllocationError, match="^INVALID_POSITION_QUANTITY$"):
        allocate(case, max_names=3)


@pytest.mark.parametrize("value,code", [
    (1.0, "DECIMAL_REQUIRED"), (1, "DECIMAL_REQUIRED"), (True, "DECIMAL_REQUIRED"),
    ("1", "DECIMAL_REQUIRED"), (D("NaN"), "DECIMAL_OUT_OF_BOUNDS"),
    (D("sNaN"), "DECIMAL_OUT_OF_BOUNDS"), (D("Infinity"), "DECIMAL_OUT_OF_BOUNDS"),
    (D("-Infinity"), "DECIMAL_OUT_OF_BOUNDS"), (D("1000000000001"), "DECIMAL_OUT_OF_BOUNDS"),
    (D("1e-13"), "DECIMAL_OUT_OF_BOUNDS"), (D("0e-13"), "DECIMAL_OUT_OF_BOUNDS"),
])
@pytest.mark.parametrize("field", ["cash", "weight", "price"])
def test_decimal_type_and_bounds(value, code, field):
    case = snapshot(targets=(("A", "1"),), marks=(("A", "1"),))
    if field == "cash": case = replace(case, cash=value)
    if field == "weight": case = replace(case, targets=(Target("A", value),))
    if field == "price": case = replace(case, marks=(Mark("A", value, "USD", AT),))
    with pytest.raises(AllocationError, match="^"+code+"$"):
        allocate(case, max_names=1)


@pytest.mark.parametrize("case,code", [
    (replace(primary(), cash=D("-1")), "NEGATIVE_CASH"),
    (replace(primary(), targets=(Target("A", D("-0.1")), Target("B", D("0.4")))), "NEGATIVE_WEIGHT"),
    (replace(primary(), targets=(Target("A", D("0.600000000001")), Target("B", D("0.4")))), "WEIGHT_SUM_EXCEEDS_ONE"),
    (replace(primary(), marks=primary().marks[1:]), "MISSING_MARK"),
    (replace(snapshot(), marks=(Mark("A", D(1), "USD", AT),)), "UNEXPECTED_MARK"),
    (replace(primary(), marks=(Mark("A", D(0), "USD", AT),)+primary().marks[1:]), "NONPOSITIVE_MARK"),
    (replace(primary(), marks=(Mark("A", D(-1), "USD", AT),)+primary().marks[1:]), "NONPOSITIVE_MARK"),
    (replace(primary(), currency="usd"), "INVALID_CURRENCY"),
    (replace(primary(), currency="US"), "INVALID_CURRENCY"),
    (replace(primary(), marks=(Mark("A", D(30), "EUR", AT),)+primary().marks[1:]), "CURRENCY_MISMATCH"),
    (replace(primary(), as_of=AT.replace(tzinfo=None)), "UTC_REQUIRED"),
    (replace(primary(), as_of=AT.astimezone(timezone(timedelta(hours=1)))), "UTC_REQUIRED"),
    (replace(primary(), as_of="2026-11-06T19:00:00Z"), "UTC_REQUIRED"),
    (replace(primary(), marks=(Mark("A", D(30), "USD", AT.replace(tzinfo=None)),)+primary().marks[1:]), "UTC_REQUIRED"),
    (replace(primary(), marks=(Mark("A", D(30), "USD", AT+timedelta(seconds=1)),)+primary().marks[1:]), "MARK_SNAPSHOT_MISMATCH"),
    (replace(primary(), marks=(Mark("A", D(30), "USD", AT-timedelta(seconds=1)),)+primary().marks[1:]), "MARK_SNAPSHOT_MISMATCH"),
    (replace(primary(), positions=primary().positions+(Position("A", 1),)), "DUPLICATE_POSITION"),
    (replace(primary(), targets=primary().targets+(Target("A", D(0)),)), "DUPLICATE_TARGET"),
    (replace(primary(), marks=primary().marks+(Mark("A", D(1), "USD", AT),)), "NAME_LIMIT"),
    (replace(primary(), positions=list(primary().positions)), "IMMUTABLE_TUPLE_REQUIRED"),
    (replace(primary(), positions=(Target("A", D(1)),)), "INVALID_ROW_TYPE"),
    (replace(snapshot(), positions=(Position("private payload", 0),)), "INVALID_INSTRUMENT_ID"),
])
def test_rejections_have_stable_sanitized_codes(case, code):
    with pytest.raises(AllocationError) as error:
        allocate(case, max_names=3)
    assert error.value.code == str(error.value) == code


def test_duplicate_mark_without_size_overflow():
    case = snapshot(targets=(("A", "1"),), marks=(("A", "1"), ("A", "2")))
    with pytest.raises(AllocationError, match="^DUPLICATE_MARK$"):
        allocate(case, max_names=2)


@pytest.mark.parametrize("limit", [0, -1, 1001, True, 1.5, "3", None])
def test_invalid_caller_limit(limit):
    with pytest.raises(AllocationError, match="^INVALID_NAME_LIMIT$"):
        allocate(primary(), max_names=limit)


def test_smaller_caller_limit_and_invalid_snapshot():
    with pytest.raises(AllocationError, match="^NAME_LIMIT$"):
        allocate(primary(), max_names=2)
    with pytest.raises(AllocationError, match="^INVALID_SNAPSHOT$"):
        allocate({}, max_names=3)

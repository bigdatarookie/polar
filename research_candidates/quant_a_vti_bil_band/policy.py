"""Fixed no-trade band on caller-qualified actual formation marks.

No source IO, policy fits, order sizing, execution or account simulation occurs
here. The accepted native caller owns actual holdings, cash and source lineage.
An instruction never attests a fill or a portfolio weight after execution.
"""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from fractions import Fraction


LOWER = Fraction(2, 5)
UPPER = Fraction(3, 5)
HALF = (("BIL", Fraction(1, 2)), ("VTI", Fraction(1, 2)))
WEIGHTS = {
    "BAND_HALF": HALF,
    "MONTHLY_HALF": HALF,
    "HOLD_INITIAL_HALF": HALF,
    "FULL_VTI": (("BIL", Fraction(0)), ("VTI", Fraction(1))),
    "FULL_BIL": (("BIL", Fraction(1)), ("VTI", Fraction(0))),
}


def instant(value):
    if (not isinstance(value, datetime) or value.tzinfo is None
            or value.utcoffset() is None):
        raise ValueError("AWARE_CLOCK_REQUIRED")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class Frame:
    source_date: date
    formation_at: datetime
    modeled_known_by: datetime
    decision_at: datetime
    execution_at: datetime

    def __post_init__(self):
        if type(self.source_date) is not date:
            raise ValueError("SOURCE_DATE_REQUIRED")
        formation = instant(self.formation_at)
        known = instant(self.modeled_known_by)
        decision = instant(self.decision_at)
        execution = instant(self.execution_at)
        expected = datetime.combine(self.source_date + timedelta(days=1),
                                    time(), tzinfo=timezone.utc)
        if (formation.date() != self.source_date or known != expected
                or decision != known + timedelta(seconds=60)
                or not formation < known <= decision < execution):
            raise ValueError("NONCAUSAL_OR_WRONG_MODELED_CLOCK")


@dataclass(frozen=True)
class FormationMark:
    """Exact values of actual native quantities at the frame's formation.

    The caller must bind them to the actual native account and eligible source
    marks. Type checks cannot establish that provenance. Fees already paid and
    residual cash must be reflected; no projected execution values belong here.
    """
    frame: Frame
    vti_cents: int
    bil_cents: int
    cash_cents: int
    nav_cents: int

    def __post_init__(self):
        if not isinstance(self.frame, Frame):
            raise ValueError("QUALIFIED_FRAME_REQUIRED")
        values = (self.vti_cents, self.bil_cents, self.cash_cents)
        if any(type(x) is not int or x < 0 for x in values):
            raise ValueError("NATIVE_NONNEGATIVE_INTEGER_CENT_MARKS_REQUIRED")
        if type(self.nav_cents) is not int or self.nav_cents != sum(values):
            raise ValueError("NATIVE_MARK_NAV_MISMATCH")
        if self.nav_cents <= 0:
            raise ValueError("NONPOSITIVE_FORMATION_NAV")

    @property
    def vti_weight(self):
        return Fraction(self.vti_cents, self.nav_cents)


@dataclass(frozen=True)
class Instruction:
    kind: str
    weights: tuple[tuple[str, Fraction], ...] | None
    observed_vti_weight: Fraction | None
    reason: str


def decide(leg, *, first, month_end_formation, terminal, frame, mark=None):
    """Terminal EXIT precedes startup and monthly decisions for every leg.

    Boundaries are inclusive HOLD. Monthly observation uses the BAND account's
    actual mark; every native account/cost case has its own observation. First
    targets initialize once; static controls then HOLD regardless of band drift.
    The caller must supply source-qualified month-end/terminal/startup metadata
    and the first eligible execution close; this module only checks clock order.
    """
    if leg not in WEIGHTS or any(type(x) is not bool for x in
                                (first, month_end_formation, terminal)):
        raise ValueError("LEG_OR_PHASE_FLAGS_INVALID")
    if not isinstance(frame, Frame):
        raise ValueError("QUALIFIED_FRAME_REQUIRED")
    if mark is not None and (not isinstance(mark, FormationMark)
                             or mark.frame != frame):
        raise ValueError("FORMATION_MARK_FRAME_MISMATCH")
    if terminal:
        return Instruction("EXIT", None, None, "COMMON_TERMINAL")
    if first:
        return Instruction("TARGET", WEIGHTS[leg], None, "INITIAL")
    if not month_end_formation:
        return Instruction("HOLD", None, None, "NO_MONTH_END_FORMATION")
    if leg == "MONTHLY_HALF":
        return Instruction("TARGET", HALF, None, "MONTH_END_FORMATION")
    if leg != "BAND_HALF":
        return Instruction("HOLD", None, None, "STATIC_CONTROL")
    if mark is None:
        raise ValueError("ACTUAL_BAND_FORMATION_MARK_REQUIRED")
    weight = mark.vti_weight
    if weight < LOWER or weight > UPPER:
        return Instruction("TARGET", HALF, weight, "OUTSIDE_CLOSED_BAND")
    return Instruction("HOLD", None, weight, "INSIDE_OR_EQUAL_BAND")

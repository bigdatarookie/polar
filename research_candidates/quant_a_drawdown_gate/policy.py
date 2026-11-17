"""Author-owned causal drawdown/recovery policy; no runner or source access."""
from dataclasses import dataclass
from datetime import date
from fractions import Fraction
from typing import Sequence

WINDOW = 252
EXIT_DRAWDOWN = Fraction(1, 5)
REENTER_DRAWDOWN = Fraction(1, 10)


@dataclass(frozen=True)
class Decision:
    kind: str
    observed_risk_on: bool | None
    formation_date: date
    vti_weight: Fraction | None
    bil_weight: Fraction | None
    drawdown: Fraction | None
    reason: str


def target(
    history: Sequence[tuple[date, Fraction]],
    previous_risk_on: bool | None,
    formation_date: date,
) -> Decision:
    """Use eligible closes only; the shared runner owns subsequent execution.

    State is the previous OBSERVED signal, independent of orders, affordability
    or fills. A rolling peak can expire: recovery is relative to the current
    trailing window, not an all-time or retrospectively chosen peak.
    """
    if previous_risk_on is not None and type(previous_risk_on) is not bool:
        raise ValueError("INVALID_OBSERVED_STATE")
    if type(formation_date) is not date or not history:
        raise ValueError("ELIGIBLE_OBSERVATION_REQUIRED")
    previous_day = None
    for day, close in history:
        if (type(day) is not date or day > formation_date
                or (previous_day is not None and day <= previous_day)):
            raise ValueError("NONCAUSAL_OR_UNORDERED_HISTORY")
        if not isinstance(close, Fraction) or close <= 0:
            raise ValueError("EXACT_POSITIVE_REFERENCE_CLOSE_REQUIRED")
        previous_day = day
    if history[-1][0] != formation_date:
        raise ValueError("FORMATION_OBSERVATION_MISSING")
    if len(history) < WINDOW:
        return Decision("HOLD", previous_risk_on, formation_date,
                        None, None, None, "INSUFFICIENT_LOOKBACK")

    closes = [close for _, close in history[-WINDOW:]]
    drawdown = 1 - closes[-1] / max(closes)
    initial = previous_risk_on is None
    risk_on = True if initial else previous_risk_on
    if risk_on and drawdown >= EXIT_DRAWDOWN:
        risk_on = False
    elif not risk_on and drawdown <= REENTER_DRAWDOWN:
        risk_on = True

    if initial:
        reason = "FIRST_OBSERVATION"
    elif risk_on != previous_risk_on:
        reason = "RECOVERY_ENTRY" if risk_on else "DRAWDOWN_EXIT"
    else:
        return Decision("HOLD", risk_on, formation_date,
                        None, None, drawdown, "NO_STATE_CHANGE")
    return Decision("TARGET", risk_on, formation_date,
                    Fraction(int(risk_on)), Fraction(int(not risk_on)),
                    drawdown, reason)

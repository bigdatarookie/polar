"""Quant A's calendar-only rule, without source IO, quantities or execution.

The caller qualifies complete episodes and causal clocks before using this module.
Every supplied price must already be authorized for this purpose. These functions
accept exact values and return instructions; no instruction proves a fill.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from fractions import Fraction


WINDOW = 200
NORMAL = (("BIL", Fraction(0)), ("VTI", Fraction(1)))
DEFENSIVE = (("BIL", Fraction(1, 2)), ("VTI", Fraction(1, 2)))
BILLS = (("BIL", Fraction(1)), ("VTI", Fraction(0)))


def instant(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("AWARE_CLOCK_REQUIRED")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class Episode:
    event_id: str
    entry: datetime
    label_end: datetime
    return_close: datetime

    def __post_init__(self):
        if not isinstance(self.event_id, str) or not self.event_id.strip():
            raise ValueError("EVENT_ID_REQUIRED")
        if not instant(self.entry) < instant(self.label_end) < instant(self.return_close):
            raise ValueError("COMPLETE_EPISODE_REQUIRED")


@dataclass(frozen=True)
class Cluster:
    event_ids: tuple[str, ...]
    entry: datetime
    label_end: datetime
    return_close: datetime


def clusters(episodes):
    """Unite touching/overlapping *risk episodes*, retaining label/return lag.

    Input must contain only source-qualified, timing-eligible, complete in-phase
    episodes. Source exclusions remain in the caller's census, never vanish here.
    """
    episodes = tuple(episodes)
    if not all(isinstance(e, Episode) for e in episodes):
        raise ValueError("EPISODE_TYPE")
    if len({e.event_id for e in episodes}) != len(episodes):
        raise ValueError("DUPLICATE_EVENT_ID")
    result = []
    for e in sorted(episodes, key=lambda x: (instant(x.entry), x.event_id)):
        if result and instant(e.entry) <= instant(result[-1].return_close):
            previous = result.pop()
            result.append(Cluster(tuple(sorted(previous.event_ids + (e.event_id,))),
                                  previous.entry,
                                  max(previous.label_end, e.label_end, key=instant),
                                  max(previous.return_close, e.return_close, key=instant)))
        else:
            result.append(Cluster((e.event_id,), e.entry, e.label_end, e.return_close))
    return tuple(result)


@dataclass(frozen=True)
class Instruction:
    kind: str
    observed_state: bool | None
    weights: tuple[tuple[str, Fraction], ...] | None
    reason: str


def transition(state, previous, weights):
    if previous is not None and type(previous) is not bool:
        raise ValueError("OBSERVED_STATE_TYPE")
    if previous is None or state != previous:
        return Instruction("TARGET", state, weights, "FIRST_OBSERVATION" if previous is None else "STATE_CHANGE")
    return Instruction("HOLD", state, None, "UNCHANGED_OBSERVED_STATE")


def daily_decisions(nav_closes):
    """First and later ordinary D=formation close+60s, Q=next close.

    The last pair is the common terminal EXIT, overriding every control target.
    Caller-qualified quote known-by remains independent of this modeled clock.
    """
    times = tuple(instant(t) for t in nav_closes)
    if len(times) < 3 or any(a >= b for a, b in zip(times, times[1:])):
        raise ValueError("ORDERED_PHASE_GRID_REQUIRED")
    pairs = tuple((a + timedelta(seconds=60), b) for a, b in zip(times, times[1:]))
    if any(d >= q for d, q in pairs):
        raise ValueError("NO_STRICT_NEXT_CLOSE_AFTER_D")
    return pairs


def fixed_target(leg, *, first, month_end_formation, terminal):
    """Monthly half targets after month-end formation, at the next close.

    month_end_formation is date/schedule metadata qualified by the caller, never
    derived from a price. Full VTI and full BIL initialize once then HOLD.
    """
    weights = {"FULL_VTI": NORMAL, "MONTHLY_FIXED_HALF": DEFENSIVE, "FULL_BIL": BILLS}
    if leg not in weights or any(type(v) is not bool for v in (first, month_end_formation, terminal)):
        raise ValueError("FIXED_CONTROL_ARGUMENTS")
    if terminal:
        return Instruction("EXIT", None, None, "COMMON_TERMINAL")
    target = first or (leg == "MONTHLY_FIXED_HALF" and month_end_formation)
    return Instruction("TARGET" if target else "HOLD", None, weights[leg] if target else None,
                       "INITIAL" if first else "MONTH_END_FORMATION" if target else "NO_REBALANCE")


def calendar_target(decision, execution, qualified_episodes, previous_defensive):
    """Choose the state for a strictly future permitted reference close.

    Q is caller-qualified geometry, not an observed fill. A cluster is defensive
    on [entry, return_close); return executes at its right endpoint. Coalescing
    touching episodes prevents a normal/protection churn pair at that close.
    Observed state is passed independently of actual holdings and affordability.
    """
    if not instant(decision) < instant(execution):
        raise ValueError("DECISION_MUST_PRECEDE_EXECUTION")
    defensive = any(instant(c.entry) <= instant(execution) < instant(c.return_close)
                    for c in clusters(qualified_episodes))
    return transition(defensive, previous_defensive, DEFENSIVE if defensive else NORMAL)


@dataclass(frozen=True)
class Close:
    close_at: datetime
    known_by: datetime | None
    price: Fraction

    def __post_init__(self):
        close = instant(self.close_at)
        if self.known_by is not None and instant(self.known_by) < close:
            raise ValueError("KNOWN_BEFORE_CLOSE")
        if not isinstance(self.price, Fraction) or self.price <= 0:
            raise ValueError("POSITIVE_FRACTION_PRICE_REQUIRED")


def sma_target(rows, decision, previous_risk_on):
    """Latest exactly 200 completed, eligible closes; strict >, equality off.

    Unknown/future known-by is ineligible. Insufficient history HOLDs and retains
    the prior observed category; it never substitutes a shorter mean or BIL.
    Unavailable observations must also remain explicit in caller diagnostics.
    """
    decision = instant(decision)
    rows = tuple(rows)
    if not all(isinstance(row, Close) for row in rows):
        raise ValueError("CLOSE_TYPE")
    times = [instant(row.close_at) for row in rows]
    if any(a >= b for a, b in zip(times, times[1:])):
        raise ValueError("ORDERED_UNIQUE_CLOSES_REQUIRED")
    if previous_risk_on is not None and type(previous_risk_on) is not bool:
        raise ValueError("OBSERVED_STATE_TYPE")
    eligible = [row for row in rows if instant(row.close_at) < decision and
                row.known_by is not None and instant(row.known_by) <= decision]
    if len(eligible) < WINDOW:
        return Instruction("HOLD", previous_risk_on, None, "INSUFFICIENT_ELIGIBLE_PREFIX")
    prices = [row.price for row in eligible[-WINDOW:]]
    risk_on = WINDOW * prices[-1] > sum(prices, Fraction())
    return transition(risk_on, previous_risk_on, NORMAL if risk_on else BILLS)

"""Fixed annual bond sleeve experiment on the existing scheduled runner.

This module defines a strategy, not an execution or source-authority adapter.
Callers supply the immutable protocol/input/calendar/timezone bindings. Retained
payloads and results never belong in this module or in public fixtures.
"""
from .scheduled_policy import profile_value


PROTOCOL_ID = "QB-ANNUAL-BOND-SLEEVE-20261117-V1"


def profile(*, protocol_sha256, input_sha256, calendar_sha256, timezone_sha256):
    """Build the closed profile; the existing service validates all source pins.

    The candidate and controls share the same equity target and annual events.
    The uninvested equity-only sleeve earns no modeled cash interest. Costs are
    executed in independent native accounts, never subtracted after the fact.
    """
    def leg(identifier, label, bil, shy, vti, rule="FIXED_WEIGHTS"):
        return {"id": identifier, "label": label, "rule": rule,
                "weights": {"BIL": bil, "SHY": shy, "VTI": vti}}

    value = {
        "schema": "polar.scheduled-reference-profile/8",
        "protocol_id": PROTOCOL_ID,
        "protocol_sha256": protocol_sha256,
        "input_sha256": input_sha256,
        "calendar_sha256": calendar_sha256,
        "timezone_sha256": timezone_sha256,
        "symbols": ["BIL", "SHY", "VTI"],
        "policy": {"kind": "FIXED_ANNUAL_RATIONAL_WEIGHTS"},
        "legs": [
            leg("BOND", "Annual equity and short Treasury sleeve", [0, 1], [1, 2], [1, 2]),
            leg("BILL", "Annual equity and bill sleeve control", [1, 2], [0, 1], [1, 2]),
            leg("EQUITY_HALF", "Annual equity and unremunerated cash control", [0, 1], [0, 1], [1, 2]),
            leg("CASH", "Unremunerated cash control", [0, 1], [0, 1], [0, 1], "CASH"),
        ],
        "primary_strategy": "BOND",
        "primary_benchmark": "BILL",
        "decision_delay_seconds": 60,
        "cost_scenarios": [
            {"id": "BASE", "cost_profile": {"flat_cents": 100, "bps": 10}},
            {"id": "COST_STRESS", "cost_profile": {"flat_cents": 200, "bps": 20}},
        ],
        "criteria": [
            {"id": kind.lower() + "_" + right.lower(), "description": description,
             "kind": kind, "left_id": "BOND", "right_id": right}
            for right in ("BILL", "EQUITY_HALF")
            for kind, description in (
                ("TERMINAL_GT", "Bond sleeve must finish above this control after actual costs."),
                ("DRAWDOWN_LE", "Bond sleeve maximum drawdown must be no worse than this control."),
                ("VOL_LE", "Bond sleeve realized volatility must be no greater than this control."),
            )
        ],
        "question_label": "Fixed annual equity and short Treasury sleeve",
        "question_summary": "Does an annual bond sleeve satisfy every declared wealth and risk comparison against both bill and unremunerated cash sleeves, under both actual cost scenarios?",
        "clock_description": "Modeled next UTC midnight availability, decision sixty seconds later, next declared reference close execution; terminal exit overrides targets.",
        "partition_description": "Exposed retrospective history, one fixed annual policy, no fitting or tuning. No untouched or prospective validation is claimed.",
        "additional_limitations": [
            ["EXPOSED_REFERENCE_HISTORY", "Vendor adjusted synthetic reference units; historical known-by, revisions and PIT remain unknown. No investor total-return or adoption claim."],
            ["NEW_CADENCE_NOT_REPLICATION", "Annual native accounts are a new cadence experiment. Retained monthly negative findings remain unchanged; linked controls are not independent replications."],
        ],
        "subperiods": [],
    }
    return profile_value(value)

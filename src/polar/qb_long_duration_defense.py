"""Predeclared duration-factor extension; retained-data fitness is separate.

No source value or outcome selects these weights, cadence or comparisons.
The existing scheduled engine owns all account and execution arithmetic.
"""
from .scheduled_policy import profile_value


PROTOCOL_ID = "QB-LONG-DURATION-DEFENSE-20261117-V1"


def profile(*, protocol_sha256, input_sha256, calendar_sha256, timezone_sha256):
    def leg(identifier, label, defensive=None, *, cash=False):
        weights = {s: [0, 1] for s in ("BIL", "SHY", "TLT", "VTI")}
        if not cash:
            weights["VTI"] = [1, 2]
            if defensive is not None:
                weights[defensive] = [1, 2]
        return {"id": identifier, "label": label,
                "rule": "CASH" if cash else "FIXED_WEIGHTS", "weights": weights}

    return profile_value({
        "schema": "polar.scheduled-reference-profile/8",
        "protocol_id": PROTOCOL_ID,
        "protocol_sha256": protocol_sha256,
        "input_sha256": input_sha256,
        "calendar_sha256": calendar_sha256,
        "timezone_sha256": timezone_sha256,
        "symbols": ["BIL", "SHY", "TLT", "VTI"],
        "policy": {"kind": "FIXED_ANNUAL_RATIONAL_WEIGHTS"},
        "legs": [
            leg("DURATION", "Annual equity and long Treasury duration sleeve", "TLT"),
            leg("SHORT", "Annual equity and short Treasury control", "SHY"),
            leg("BILL", "Annual equity and Treasury bill control", "BIL"),
            leg("EQUITY_HALF", "Annual equity and unremunerated cash control"),
            leg("CASH", "Unremunerated cash control", cash=True),
        ],
        "primary_strategy": "DURATION",
        "primary_benchmark": "SHORT",
        "decision_delay_seconds": 60,
        "cost_scenarios": [
            {"id": "BASE", "cost_profile": {"flat_cents": 100, "bps": 10}},
            {"id": "COST_STRESS", "cost_profile": {"flat_cents": 200, "bps": 20}},
        ],
        "criteria": [
            {"id": kind.lower() + "_" + right.lower(), "description": description,
             "kind": kind, "left_id": "DURATION", "right_id": right}
            for right in ("SHORT", "BILL", "EQUITY_HALF")
            for kind, description in (
                ("TERMINAL_GT", "Long duration sleeve must exceed this control after actual costs."),
                ("DRAWDOWN_LE", "Long duration sleeve drawdown must be no worse than this control."),
                ("VOL_LE", "Long duration sleeve volatility must be no greater than this control."),
            )
        ],
        "question_label": "Fixed annual equity and long Treasury duration sleeve",
        "question_summary": "Does fixed long nominal Treasury duration meet every declared net wealth and risk comparison against short Treasury, bill and cash sleeves under each actual cost scenario?",
        "clock_description": "Pinned model calendar availability followed by a sixty-second decision delay and next declared reference close; terminal exit overrides targets.",
        "partition_description": "Exploratory factor extension with a fixed rule declared before the new duration history is consumed. Related history is exposed; no untouched confirmation or tuning is claimed.",
        "additional_limitations": [
            ["SOURCE_FITNESS_SEPARATE", "Actual source identity, rights, aligned calendar and scale must be qualified before a retained run. Adjusted reference units do not establish investor total return or historical PIT."],
            ["INTENDED_EXPOSURE_ONLY", "Equity target fractions are identical across sleeves; actual fills and exposures can differ because each account independently pays costs and rounds units."],
            ["NEW_FACTOR_NOT_SCORE_REPLACEMENT", "This tests a separately qualified long-duration factor. Prior short-duration and monthly trend outcomes and all previous trials remain unchanged."],
        ],
        "subperiods": [],
    })

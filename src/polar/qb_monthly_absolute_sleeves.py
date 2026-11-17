"""Frozen monthly absolute-trend sleeves on the existing scheduled engine."""
from .scheduled_policy import profile_value

PROTOCOL_ID = "QB-MONTHLY-ABSOLUTE-SLEEVES-20261117-V1"


def profile(*, protocol_sha256, input_sha256, calendar_sha256, timezone_sha256):
    value = {
        "schema": "polar.scheduled-reference-profile/1",
        "protocol_id": PROTOCOL_ID,
        "protocol_sha256": protocol_sha256,
        "input_sha256": input_sha256,
        "calendar_sha256": calendar_sha256,
        "timezone_sha256": timezone_sha256,
        "symbols": ["BIL", "SHY", "VTI"],
        "policy": {"kind": "ABSOLUTE_MOMENTUM_SLEEVES", "lookback": 252, "skip": 21},
        "legs": [
            {"id": name, "label": label, "rule": rule, "scale": scale}
            for name, label, rule, scale in (
                ("TREND", "Fixed monthly positive absolute trend sleeves", "SLEEVES", [1, 1]),
                ("EW", "Monthly equal-weight control", "EQUAL_WEIGHT", [1, 1]),
                ("EW_HALF", "Monthly half-exposure control", "EQUAL_WEIGHT", [1, 2]),
                ("MOM", "Positive strongest-momentum control", "MOMENTUM", [1, 1]),
                ("CASH", "Unremunerated cash control", "CASH", [1, 1]),
            )
        ],
        "primary_strategy": "TREND",
        "primary_benchmark": "EW",
        "decision_delay_seconds": 60,
        "criteria": [
            {"id": "terminal_" + right.lower(), "description": "Net terminal wealth must exceed this control.",
             "kind": "TERMINAL_GT", "left_id": "TREND", "right_id": right}
            for right in ("EW", "EW_HALF")
        ] + [
            {"id": "drawdown_ew", "description": "Maximum drawdown must be no worse than full equal weight.",
             "kind": "DRAWDOWN_LE", "left_id": "TREND", "right_id": "EW"},
            {"id": "volatility_ew", "description": "Realized volatility must be no greater than full equal weight.",
             "kind": "VOL_LE", "left_id": "TREND", "right_id": "EW"},
            {"id": "sharpe_ew", "description": "Zero modeled-risk-free Sharpe must be no lower than full equal weight.",
             "kind": "SR_DELTA_GE", "left_id": "TREND", "right_id": "EW", "threshold": "0"},
            {"id": "positive_growth", "description": "Net terminal wealth must exceed initial capital.",
             "kind": "POSITIVE_GROWTH", "left_id": "TREND"},
        ],
        "question_label": "Fixed monthly absolute-trend sleeves",
        "question_summary": "Does the fixed skipped-recent-month absolute-trend filter meet every declared net wealth and risk predicate against exposure controls?",
        "clock_description": "Only the eligible formation prefix determines targets; modeled next New York midnight K, decision sixty seconds later, next declared reference close, terminal exit override.",
        "partition_description": "Fresh-capital exposed retrospective validation and final accounts; validation is descriptive and does not select parameters. The frozen point screen applies to FINAL only.",
        "additional_limitations": [
            ["EXPOSED_REFERENCE_HISTORY", "Already exposed vendor-adjusted synthetic units; historical known-by, PIT, revisions and economic continuity are not established. Not investor total return."],
            ["FIXED_BASE_COST_ONLY", "Existing profile/1 executes its actual base flat and proportional fees. No separate cost-stress account or robustness claim is supplied."],
            ["NO_PARAMETER_SELECTION", "One fixed lookback/skip and comparison set; no fitting, tuning or untouched confirmation. Earlier annual/monthly negative findings remain independent retained history."],
        ],
        "subperiods": [],
    }
    return profile_value(value)

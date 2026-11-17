"""Fixed diagonal-shrunk minimum variance on the duration-extended cohort."""
from .scheduled_policy import profile_value


PROTOCOL_ID = "QB-DURATION-SHRUNK-GMV-20261118-V1"


def profile(*, protocol_sha256, input_sha256, calendar_sha256, timezone_sha256):
    conditions = [
        {"id": kind.lower() + "_" + other.lower(), "description": description,
         "kind": kind, "left_id": "GMV", "right_id": other, **extra}
        for other in ("EW", "INV")
        for kind, extra, description in (
            ("TERMINAL_GT", {}, "Net terminal wealth must exceed this common-forecast-risk control."),
            ("SR_DELTA_GE", {"threshold": "0.10"}, "Zero-risk-free Sharpe must exceed this control by the fixed material margin."),
            ("DRAWDOWN_LE", {}, "Drawdown must be no worse than this control."),
            ("VOL_RATIO_BETWEEN", {"lower": "0.8", "upper": "1.25"}, "Realized volatility must remain within the declared comparison band."),
        )
    ]
    conditions.append({"id": "positive_growth", "description": "Net terminal wealth must exceed initial capital.",
                       "kind": "POSITIVE_GROWTH", "left_id": "GMV"})
    return profile_value({
        "schema": "polar.scheduled-reference-profile/4",
        "protocol_id": PROTOCOL_ID,
        "protocol_sha256": protocol_sha256,
        "input_sha256": input_sha256,
        "calendar_sha256": calendar_sha256,
        "timezone_sha256": timezone_sha256,
        "symbols": ["BIL", "SHY", "TLT", "VTI"],
        "policy": {"kind": "SHRUNK_GMV_COMMON_RISK", "lookback": 60, "annual_cap": "0.10", "shrinkage": [1, 2], "solver": "EXACT_ALL15_KKT"},
        "legs": [
            {"id": name, "label": label, "rule": rule, "scale": [1, 1]}
            for name, label, rule in (
                ("GMV", "Monthly fixed shrunk covariance minimum variance at common forecast risk", "SHRUNK_GMV"),
                ("EW", "Monthly equal-weight common forecast risk control", "EQUAL_WEIGHT"),
                ("INV", "Monthly inverse standalone volatility common forecast risk control", "INVERSE_VOL"),
            )
        ],
        "primary_strategy": "GMV",
        "primary_benchmark": "EW",
        "decision_delay_seconds": 1,
        "cost_scenarios": [
            {"id": "BASE", "cost_profile": {"flat_cents": 100, "bps": 10}},
            {"id": "COST_STRESS", "cost_profile": {"flat_cents": 200, "bps": 20}},
        ],
        "uncertainty": {"kind": "PAIRED_CIRCULAR_SAVED_RETURNS", "block": 63, "replicates": 1000, "seed": 37002},
        "criteria": conditions,
        "question_label": "Fixed shrunk-GMV duration cohort comparison",
        "question_summary": "Does fixed diagonal-shrunk minimum-variance allocation meet the entire net wealth, material Sharpe, drawdown and realized-risk screen against inverse-volatility and equal-weight controls in each cost scenario?",
        "clock_description": "Eligible formation prefix only; next modeled New York midnight availability, one-second decision delay, next declared reference close, terminal exit override.",
        "partition_description": "Exposed retrospective FINAL period unchanged from the inherited calendar, with separate base and stress accounts. The accepted paired-resampling profile supports FINAL only; no validation run, selection or untouched confirmation is claimed.",
        "additional_limitations": [
            ["EXPOSED_SMALL_REFERENCE_COHORT", "Only the retained bill, short and long Treasury and equity vendor-reference paths; PIT, vintage/economic continuity and investor total return remain unestablished. No untouched confirmation."],
            ["COMMON_FORECAST_NOT_REALIZED_RISK", "Common tau is the minimum of the fixed annual cap and every raw-policy forecast risk; it need not equal the cap. Covariance forecasts, rounded targets, realized risk and filled exposures are distinct."],
            ["FIXED_COVARIANCE_OPTIMIZATION_LIMITS", "The fixed covariance optimizer uses an existing exact support/KKT certificate and explicit accounting, not a predictive learned model. Optimality for the shrunk estimated covariance is not ex-post optimality, economic superiority or a selection-adjusted inference. Saved paired resampling is conditional only."],
        ],
        "subperiods": [],
    })

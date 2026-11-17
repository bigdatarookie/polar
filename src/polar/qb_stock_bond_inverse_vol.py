"""Fixed minimal stock-bond inverse-volatility comparison."""
from .scheduled_policy import profile_value


PROTOCOL_ID = "QB-STOCK-BOND-INVERSE-VOL-20261118-V1"


def profile(*, protocol_sha256, input_sha256, calendar_sha256, timezone_sha256):
    conditions = [
        {"id": kind.lower() + "_" + other.lower(), "description": description,
         "kind": kind, "left_id": "INVVOL", "right_id": other, **extra}
        for other in ("EW", "MOM")
        for kind, extra, description in (
            ("TERMINAL_GT", {}, "Net terminal wealth must exceed this common-forecast-risk control."),
            ("SR_DELTA_GE", {"threshold": "0.10"}, "Zero-risk-free Sharpe must exceed this control by the fixed material margin."),
            ("DRAWDOWN_LE", {}, "Drawdown must be no worse than this control."),
            ("VOL_RATIO_BETWEEN", {"lower": "0.8", "upper": "1.25"}, "Realized volatility must remain within the declared comparison band."),
        )
    ]
    conditions.append({"id": "positive_growth", "description": "Net terminal wealth must exceed initial capital.",
                       "kind": "POSITIVE_GROWTH", "left_id": "INVVOL"})
    return profile_value({
        "schema": "polar.scheduled-reference-profile/2",
        "protocol_id": PROTOCOL_ID,
        "protocol_sha256": protocol_sha256,
        "input_sha256": input_sha256,
        "calendar_sha256": calendar_sha256,
        "timezone_sha256": timezone_sha256,
        "symbols": ["TLT", "VTI"],
        "policy": {"kind": "COMMON_RISK_INVERSE_VOLATILITY", "lookback": 60, "annual_cap": "0.10"},
        "legs": [
            {"id": name, "label": label, "rule": rule, "scale": [1, 1]}
            for name, label, rule in (
                ("INVVOL", "Monthly inverse standalone volatility at common forecast risk", "INVERSE_VOL"),
                ("EW", "Monthly equal-weight common forecast risk control", "EQUAL_WEIGHT"),
                ("MOM", "Monthly strongest-momentum common forecast risk control", "MOMENTUM"),
            )
        ],
        "primary_strategy": "INVVOL",
        "primary_benchmark": "EW",
        "decision_delay_seconds": 1,
        "cost_scenarios": [
            {"id": "BASE", "cost_profile": {"flat_cents": 100, "bps": 10}},
            {"id": "COST_STRESS", "cost_profile": {"flat_cents": 200, "bps": 20}},
        ],
        "uncertainty": {"kind": "PAIRED_CIRCULAR_SAVED_RETURNS", "block": 63, "replicates": 1000, "seed": 37001},
        "criteria": conditions,
        "question_label": "Fixed stock-bond inverse volatility at common forecast risk",
        "question_summary": "Does inverse-volatility allocation meet the entire fixed net wealth, material Sharpe, drawdown and realized-risk screen against equal-weight and momentum controls under each cost scenario?",
        "clock_description": "Eligible formation prefix only; next modeled New York midnight availability, one-second decision delay, next declared reference close, terminal exit override.",
        "partition_description": "Exposed retrospective FINAL period unchanged from the inherited calendar, with separate base and stress accounts. The accepted paired-resampling profile supports FINAL only; no validation run, selection or untouched confirmation is claimed.",
        "additional_limitations": [
            ["EXPOSED_SMALL_REFERENCE_COHORT", "Only the fixed US equity and long-duration Treasury vendor-reference pair; PIT, vintage/economic continuity and investor total return remain unestablished. No untouched confirmation."],
            ["COMMON_FORECAST_NOT_REALIZED_RISK", "Common tau is the minimum of the fixed annual cap and every raw-policy forecast risk; it need not equal the cap. Covariance forecasts, rounded targets, realized risk and filled exposures are distinct."],
            ["TWO_ASSET_RISK_LIMIT", "Two-asset inverse standalone volatility has covariance-risk-contribution symmetry before rounding under nondegenerate assumptions; actual filled exposures, forecasts and ex-post risk are distinct. Conditional exposed-path resampling is not market confidence or a selection rule."],
        ],
        "subperiods": [],
    })

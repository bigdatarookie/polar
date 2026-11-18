"""Frozen priced residual-capital comparison on the accepted scheduled hook."""
from .qb_priced_reserve_prototype import PROTOCOL_ID
from .scheduled_policy import profile_value
from .scheduled_priced_reserve import IDS, KIND, PROTOTYPE_SHA256, SCHEMA, SPECS


def profile(*, protocol_sha256, input_sha256, calendar_sha256, timezone_sha256):
    descriptions = [
        "Net terminal wealth must exceed the forecast-risk cash control.",
        "Net terminal wealth must exceed the separately costed bill-only opportunity hurdle.",
        "Zero-risk-free Sharpe must exceed the cash control by the fixed material margin.",
        "Drawdown must be no worse than the cash control.",
        "Realized volatility must remain within the declared band relative to the cash control.",
        "Net terminal wealth must exceed initial capital.",
    ]
    return profile_value({
        "schema": SCHEMA, "protocol_id": PROTOCOL_ID,
        "protocol_sha256": protocol_sha256, "input_sha256": input_sha256,
        "calendar_sha256": calendar_sha256, "timezone_sha256": timezone_sha256,
        "symbols": ["BIL", "VTI"],
        "policy": {"kind": KIND, "lookback": 60, "annual_cap": "0.10",
                   "weight_units": 1_000_000, "prototype_sha256": PROTOTYPE_SHA256},
        "legs": [{"id": name, "label": label, "rule": name, "scale": [1, 1]}
                 for name, label in zip(IDS, (
                     "Priced bill reserve at no higher cash-control forecast risk",
                     "Equity with unremunerated residual cash at capped forecast risk",
                     "Separately costed bill-only terminal opportunity hurdle"))],
        "primary_strategy": "SWEPT", "primary_benchmark": "CASH_TARGET",
        "decision_delay_seconds": 1,
        "cost_scenarios": [
            {"id": "BASE", "cost_profile": {"flat_cents": 100, "bps": 10}},
            {"id": "COST_STRESS", "cost_profile": {"flat_cents": 200, "bps": 20}}],
        "uncertainty": {"kind": "PAIRED_CIRCULAR_SAVED_RETURNS", "block": 63,
                        "replicates": 1000, "seed": 37004},
        "criteria": [{"id": "criterion_" + str(i), "description": description,
                      "left_id": "SWEPT", **spec}
                     for i, (description, spec) in enumerate(zip(descriptions, SPECS))],
        "question_label": "Risk-matched priced reserve comparison",
        "question_summary": "Does priced residual capital meet the entire frozen net wealth, material Sharpe, drawdown and realized-risk screen against the cash control and separate terminal bill hurdle in both cost scenarios?",
        "clock_description": "Causal formation prefix; next modeled New York midnight plus one second, next declared reference close and terminal exit override.",
        "partition_description": "Inherited exposed retrospective FINAL calendar and causal prefix unchanged. No untouched, selection-adjusted or causal confirmation.",
        "additional_limitations": [
            ["FORECAST_GRID_NOT_REALIZED_RISK", "The maximal fixed-grid bill/equity target has no higher forecast variance than the capped equity/cash control; continuous equality, realized-risk equality and filled exposures are distinct."],
            ["PRICED_REFERENCE_NOT_FUNDING", "Bill vendor reference is a priced asset with actual account costs, not earned cash interest, funding, a risk-free rate or investor total return. Bill-only is a terminal hurdle, not the matched-risk control."],
            ["EXPOSED_SELECTION_AND_SOURCE_LIMITS", "Selected after prior exposed research; all negative results and source, rights, PIT, vintage, economic-continuity, historical-custody and exposure limitations persist. Saved paired resampling is conditional descriptive evidence only."],
        ], "subperiods": [],
    })

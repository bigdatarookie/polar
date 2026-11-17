"""Author checks with invented bindings; no retained duration observations."""
from copy import deepcopy
from fractions import Fraction

import pytest

from polar.qb_long_duration_defense import profile
from polar.scheduled_policy import profile_value


def candidate():
    return profile(protocol_sha256="1" * 64, input_sha256="2" * 64,
                   calendar_sha256="3" * 64, timezone_sha256="4" * 64)


def test_cohort_budget_and_separate_duration_controls():
    p = candidate()
    legs = {leg["id"]: leg for leg in p["legs"]}
    for name in ("DURATION", "SHORT", "BILL", "EQUITY_HALF"):
        assert Fraction(*legs[name]["weights"]["VTI"]) == Fraction(1, 2)
    for name, asset in (("DURATION", "TLT"), ("SHORT", "SHY"), ("BILL", "BIL")):
        assert {s for s, w in legs[name]["weights"].items() if Fraction(*w)} == {"VTI", asset}
        assert sum(Fraction(*w) for w in legs[name]["weights"].values()) == 1
    assert sum(Fraction(*w) for w in legs["EQUITY_HALF"]["weights"].values()) == Fraction(1, 2)
    assert all(Fraction(*w) == 0 for w in legs["CASH"]["weights"].values())
    assert {(c["kind"], c["right_id"]) for c in p["criteria"]} == {
        (kind, right) for right in ("SHORT", "BILL", "EQUITY_HALF")
        for kind in ("TERMINAL_GT", "DRAWDOWN_LE", "VOL_LE")}


def test_binding_and_existing_stress_contract_reject_drift():
    with pytest.raises(ValueError, match="SCHEDULED_PROFILE_HASH"):
        profile(protocol_sha256="unpinned", input_sha256="2" * 64,
                calendar_sha256="3" * 64, timezone_sha256="4" * 64)
    changed = deepcopy(candidate())
    changed["cost_scenarios"][1]["cost_profile"]["bps"] = 10
    with pytest.raises(ValueError, match="SCHEDULED_FIXED_COST_SCENARIOS"):
        profile_value(changed)


def test_profiles_do_not_share_mutable_weights():
    changed = candidate()
    changed["legs"][0]["weights"]["TLT"][0] = 0
    assert candidate()["legs"][0]["weights"]["TLT"] == [1, 2]

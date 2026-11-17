"""Public strategy-definition checks use invented hashes, never retained prices."""
from copy import deepcopy
from fractions import Fraction

import pytest

from polar.qb_annual_bond_sleeve import profile
from polar.scheduled_policy import profile_value


def candidate():
    return profile(protocol_sha256="1" * 64, input_sha256="2" * 64,
                   calendar_sha256="3" * 64, timezone_sha256="4" * 64)


def test_matched_equity_sleeves_and_joint_cost_comparisons():
    p = candidate()
    legs = {leg["id"]: leg for leg in p["legs"]}
    for name in ("BOND", "BILL", "EQUITY_HALF"):
        assert Fraction(*legs[name]["weights"]["VTI"]) == Fraction(1, 2)
    assert sum(Fraction(*w) for w in legs["BOND"]["weights"].values()) == 1
    assert sum(Fraction(*w) for w in legs["BILL"]["weights"].values()) == 1
    assert sum(Fraction(*w) for w in legs["EQUITY_HALF"]["weights"].values()) == Fraction(1, 2)
    assert legs["CASH"]["rule"] == "CASH"
    assert {(c["kind"], c["right_id"]) for c in p["criteria"]} == {
        (kind, right) for right in ("BILL", "EQUITY_HALF")
        for kind in ("TERMINAL_GT", "DRAWDOWN_LE", "VOL_LE")}
    assert p["schema"] == "polar.scheduled-reference-profile/8"
    assert p["subperiods"] == [] and "uncertainty" not in p


def test_invalid_source_binding_and_stress_drift_are_rejected():
    with pytest.raises(ValueError, match="SCHEDULED_PROFILE_HASH"):
        profile(protocol_sha256="unpinned", input_sha256="2" * 64,
                calendar_sha256="3" * 64, timezone_sha256="4" * 64)
    changed = deepcopy(candidate())
    changed["cost_scenarios"][1]["cost_profile"]["bps"] = 10
    with pytest.raises(ValueError, match="SCHEDULED_FIXED_COST_SCENARIOS"):
        profile_value(changed)


def test_builds_are_independent_and_do_not_share_mutable_parameters():
    changed = candidate()
    changed["legs"][0]["weights"]["SHY"][0] = 0
    assert candidate()["legs"][0]["weights"]["SHY"] == [1, 2]

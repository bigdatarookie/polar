"""Frozen common rational moments -> ordered Decimal50 scalar projections."""
from decimal import Decimal, localcontext
from fractions import Fraction

from .ci_research import INITIAL_CENTS, project, require
from .gym_contract import context, decimal_fraction, decimal_string


def metric(v=None, reason=None):
    return {"value": v, "status": "OK" if v is not None else "UNAVAILABLE", "reason": reason}


def evaluate_legs(simulation):
    legs = []; exact = {}
    for tape in simulation["legs"]:
        nav = tape["nav"]; require(len(nav) >= 2, "NO_RETURN_INTERVALS")
        values = [r["nav_cents"] for r in nav]
        require(all(type(v) is int and v > 0 for v in values) and values[0] == INITIAL_CENTS, "NAV_DOMAIN")
        returns = [Fraction(b, a)-1 for a,b in zip(values, values[1:])]
        mean = sum(returns)/len(returns)
        variance = sum((r-mean)**2 for r in returns)/(len(returns)-1) if len(returns) >= 2 else None
        peak = values[0]; dd = Fraction()
        for v in values:
            peak = max(peak, v); dd = max(dd, 1-Fraction(v, peak))
        elapsed = nav[-1]["nominal_ns"]-nav[0]["nominal_ns"]
        require(elapsed > 0, "ELAPSED_TIME_DOMAIN")
        with localcontext(context()):
            root252 = Decimal(252).sqrt()
            sd = decimal_fraction(variance).sqrt() if variance is not None else None
            vol = decimal_string(root252*sd) if sd is not None else None
            sharpe = decimal_string((root252*decimal_fraction(mean))/sd) if sd else None
            years = decimal_fraction(Fraction(elapsed, 31557600*10**9))
            cagr = decimal_string((decimal_fraction(Fraction(values[-1], values[0])).ln()/years).exp()-1)
        fills = tape["fills"]
        gross_micro = sum(f["exact_notional_micro"] for f in fills)
        settled_cents = sum(f["settled_cents"] for f in fills)
        sampled = nav[1:]
        exposure = sum((Fraction(r["exposure_cents"], r["nav_cents"]) for r in sampled), Fraction())/len(sampled)
        invested = Fraction(sum(any(r["positions"].values()) for r in sampled), len(sampled))
        concentration = max((Fraction(amount, r["nav_cents"]) for r in nav for amount in r["position_cents"].values()), default=Fraction())
        m = {
            "terminal_nav_usd": metric(project(Fraction(values[-1], 100))),
            "net_total_return": metric(project(Fraction(values[-1], values[0])-1)),
            "net_cagr_act36525": metric(cagr), "daily_mean_return": metric(project(mean)),
            "daily_sample_variance": metric(project(variance)) if variance is not None else metric(None, "INSUFFICIENT_INTERVALS"),
            "annual_vol_252": metric(vol, None if vol is not None else "INSUFFICIENT_INTERVALS"),
            "sharpe_252_rf0": metric(sharpe, None if sharpe is not None else "ZERO_VARIANCE" if sd == 0 else "INSUFFICIENT_INTERVALS"),
            "max_drawdown": metric(project(dd)),
            "flat_fee_usd": metric(project(Fraction(nav[-1]["flat_cents"], 100))),
            "bps_cost_usd": metric(project(Fraction(nav[-1]["bps_cents"], 100))),
            "total_cost_usd": metric(project(Fraction(nav[-1]["flat_cents"]+nav[-1]["bps_cents"], 100))),
            "gross_exact_notional_usd": metric(project(Fraction(gross_micro, 1000000))),
            "gross_settled_notional_usd": metric(project(Fraction(settled_cents, 100))),
            "gross_notional_over_initial": metric(project(Fraction(gross_micro, INITIAL_CENTS*10000))),
            "positive_fill_count": metric(str(len(fills))),
            "mean_close_exposure": metric(project(exposure)),
            "invested_session_fraction": metric(project(invested)),
            "max_close_concentration": metric(project(concentration)),
        }
        legs.append({"id": tape["id"], "metrics": m,
                     "returns": [{"numerator": str(r.numerator), "denominator": str(r.denominator), "decimal": project(r)} for r in returns]})
        exact[tape["id"]] = {"max_drawdown": dd, "terminal": values[-1]}
    return legs, exact


def evaluate(simulation, profile):
    legs, exact = evaluate_legs(simulation)
    ids = profile["legs"]; by_id = {leg["id"]: leg for leg in legs}
    left, right = ids[:2]
    a, b = by_id[left]["metrics"], by_id[right]["metrics"]
    comparisons = []
    for name in ("terminal_nav_usd", "net_cagr_act36525", "sharpe_252_rf0", "max_drawdown", "total_cost_usd"):
        av, bv = a[name]["value"], b[name]["value"]
        with localcontext(context()):
            diff = decimal_string(Decimal(av)-Decimal(bv)) if av is not None and bv is not None else None
        comparisons.append({"metric_id": name, "left_id": left, "right_id": right,
                            "result": metric(diff, None if diff is not None else "PAIRED_METRIC_UNAVAILABLE")})
    sr = next(c["result"]["value"] for c in comparisons if c["metric_id"] == "sharpe_252_rf0")
    if profile["kind"] == "A_MOMENTUM":
        conditions = [("NET_WEALTH_IMPROVEMENT", exact[left]["terminal"] > exact[right]["terminal"]),
                      ("SHARPE_IMPROVEMENT", Decimal(sr) > 0 if sr is not None else None),
                      ("DRAWDOWN_NOT_WORSE", exact[left]["max_drawdown"] <= exact[right]["max_drawdown"])]
    else:
        conditions = [("SHARPE_HURDLE", Decimal(sr) >= Decimal("0.10") if sr is not None else None),
                      ("POSITIVE_CAGR", exact[left]["terminal"] > INITIAL_CENTS),
                      ("DRAWDOWN_NOT_WORSE_THAN_FULL_BH", exact[left]["max_drawdown"] <= exact[ids[2]]["max_drawdown"])]
    criteria = [{"id": name, "description": name, "status": "UNAVAILABLE" if v is None else "MET" if v else "NOT_MET",
                 "reason": "REQUIRED_METRIC_UNAVAILABLE" if v is None else None} for name,v in conditions]
    if any(v is None for _,v in conditions):
        outcome = "INDETERMINATE"
    elif profile["kind"] == "A_MOMENTUM":
        outcome = "POINT_SUPPORT_LIMITED_PRICE_MODEL" if all(v for _,v in conditions) else "POINT_NOT_SUPPORTED"
    else:
        outcome = "SUPPORTIVE_ON_THIS_SCREEN" if all(v for _,v in conditions) else "NOT_SUPPORTIVE_ON_THIS_SCREEN"
    return {"schema": "polar.ci-research-evaluation/1", "legs": legs, "comparisons": comparisons,
            "criteria": criteria, "point_interpretation": outcome,
            "exposure_denominator": len(simulation["legs"][0]["nav"])-1,
            "financial_acceptance": "NOT_REVIEWED"}

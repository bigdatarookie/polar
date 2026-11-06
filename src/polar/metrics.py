from datetime import datetime
from decimal import Decimal, localcontext


def metrics(navs, fills, initial_cash, fees, dividends, settlement):
    """Frozen v2 formulas. Numeric computability is separate from evidence sufficiency."""
    with localcontext() as ctx:
        ctx.prec = 50
        values = [Decimal(n["nav"]) for n in navs]
        times = [datetime.fromisoformat(n["at"]) for n in navs]
        if any(v <= 0 or not v.is_finite() for v in values):
            raise ValueError("NONPOSITIVE_NAV")
        if any(b <= a for a,b in zip(times,times[1:])):
            raise ValueError("NAV_TIME_ORDER")
        result = {}
        def put(name, value, unit="fraction", reason=None):
            result[name] = {"value":str(value) if value is not None else None,
                            "unit":unit,"status":"OK" if value is not None else "INSUFFICIENT_EVIDENCE",
                            "evidence_status":"INSUFFICIENT_EVIDENCE","reason":reason}
        returns = [b/a-1 for a,b in zip(values,values[1:])]
        elapsed = Decimal(str((times[-1]-times[0]).total_seconds())) if len(times)>1 else Decimal(0)
        put("total_return",values[-1]/values[0]-1 if len(values)>1 else None)
        put("cagr",((values[-1]/values[0]).ln() * (Decimal("365.25")*86400/elapsed)).exp()-1 if elapsed>0 else None,
            reason="SYNTHETIC_ANNUALIZATION")
        mean = sum(returns)/len(returns) if returns else None
        std = (sum((r-mean)**2 for r in returns)/(len(returns)-1)).sqrt() if len(returns)>=2 else None
        put("volatility_252",std*Decimal(252).sqrt() if std is not None else None)
        put("sharpe_252",Decimal(252).sqrt()*mean/std if std else None,"ratio", "RF_DAILY_ZERO; DDOF_1")
        peak = initial_cash
        max_dd = Decimal(0)
        for v in values:
            peak = max(peak,v)
            max_dd = max(max_dd,1-v/peak)
        put("max_drawdown",max_dd if len(values)>1 else None)
        # Current underwater spell ends only on a recovered observed peak.
        peak_value = initial_cash
        peak_time = times[0] if times else None
        underwater_since = None
        for t,v in zip(times,values):
            if v >= peak_value:
                peak_value,peak_time,underwater_since = v,t,None
            elif underwater_since is None:
                underwater_since = peak_time
        put("underwater_seconds",Decimal(str((times[-1]-underwater_since).total_seconds())) if underwater_since else (Decimal(0) if times else None),"second")
        result["recovery"] = {"value":None,"status":"RIGHT_CENSORED" if underwater_since else ("NOT_UNDERWATER" if times else "INSUFFICIENT_EVIDENCE"),
                              "unit":"UTC_timestamp", "observed_until":times[-1].isoformat() if times else None}
        turnover = Decimal(0)
        for fill in fills:
            event = datetime.fromisoformat(fill["fill_at"])
            prior = [Decimal(n["nav"]) for n in navs if datetime.fromisoformat(n["at"]) < event]
            turnover += abs(Decimal(fill["quantity"])*Decimal(fill["price"]))/ (prior[-1] if prior else initial_cash)
        put("turnover",turnover)
        for name,value in [("fees",fees),("dividends",dividends),("settlement",settlement)]:
            put(name,value,"USD")
        if returns:
            tail_count = max(1,(len(returns)+19)//20)
            put("historical_es95",-sum(sorted(returns)[:tail_count])/tail_count)
            result["historical_es95"]["tail_count"] = tail_count
            worst = min(range(len(returns)),key=returns.__getitem__)
            put("worst_period",returns[worst])
            result["worst_period"]["at"] = navs[worst+1]["at"]
        else:
            put("historical_es95",None)
            put("worst_period",None)
        weights = [Decimal(n["shares"])*Decimal(n["mark"])/Decimal(n["nav"]) if n["mark"] is not None else Decimal(0) for n in navs]
        put("end_concentration",weights[-1] if weights else None)
        put("max_risky_weight",max(weights) if weights else None)
        for name in ["beta","factor_attribution","confidence_interval","alpha"]:
            result[name] = {"value":None,"unit":"ratio","status":"NOT_RUN"}
        return result

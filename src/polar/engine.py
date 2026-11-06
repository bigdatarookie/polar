"""Small deterministic raw-price ledger; no arbitrary strategy code execution."""
from datetime import timedelta
from decimal import Decimal, localcontext

from .codec import digest
from .models import Dataset, RunConfig
from .metrics import metrics


class InvalidInput(Exception):
    pass


def calculate(dataset: Dataset, config: RunConfig):
    with localcontext() as ctx:
        ctx.prec = 40
        try:
            net = _calculate(dataset, config)
            if net["status"] == "COMPLETED":
                executed = {f["decision_session_id"] for f in net["fills"]}
                gross_config = config.model_copy(update={"orders":[o for o in config.orders if o.decision_session_id in executed]})
                gross = _calculate(dataset,gross_config,fee_per_fill=Decimal(0))
                net["gross_counterfactual"] = {"final_nav":gross["nav"][-1]["nav"],"metrics":gross["metrics"],"same_quantities":True}
            return net
        except (InvalidInput,ValueError) as exc:
            return {"schema_version":"polar.report/1","status":"INVALID","diagnostic":str(exc),
                    "financial_verdict":"INVALID","qualification":"INFRASTRUCTURE_FIXTURE_ONLY",
                    "dataset_id":dataset.dataset_id,"protocol_version":config.protocol_version,
                    "fills":[],"nav":[],"metrics":{"performance":{"value":None,"status":"INVALID","reason":str(exc)}}}


def _calculate(data, config, fee_per_fill=Decimal(1)):
    if config.dataset_id != data.dataset_id:
        raise InvalidInput("DATASET_HASH_MISMATCH")
    bars = {b.session_id:b for b in data.bars}
    if data.sessions and not bars:
        raise InvalidInput("NO_DATA")
    session_ids = [s.session_id for s in data.sessions]
    orders = {o.decision_session_id:o for o in config.orders}
    if any(s not in session_ids for s in orders):
        raise InvalidInput("UNKNOWN_DECISION_SESSION")
    cash, shares = config.initial_cash, Decimal(0)
    pending = None
    fills, ledger, navs, returns, instructions, diagnostics = [], [], [], [], [], []
    previous_nav = config.initial_cash
    previous_close = None
    total_fees, dividend_cash, settlement_cash = Decimal(0), Decimal(0), Decimal(0)
    settled = False
    observed_bars, settlement_only_bars, missing_price_sessions = 0, 0, 0
    for session in data.sessions:
        prior_shares = shares
        actions = [a for a in data.actions if a.effective_time == session.open_at]
        # Distinct phases have a frozen order, independent of source row order.
        # Multiple actions within a phase have no qualified composition rule.
        if len({a.kind for a in actions}) != len(actions):
            raise InvalidInput("AMBIGUOUS_SIMULTANEOUS_ACTIONS")
        phases = {"split": 0, "dividend": 1, "delisting_cash_settlement": 2}
        actions.sort(key=lambda a: phases[a.kind])
        for a in actions:
            if a.kind == "split":
                shares *= a.ratio_numerator/a.ratio_denominator
                prior_shares *= a.ratio_numerator/a.ratio_denominator
                if pending:
                    pending = pending.model_copy(update={"quantity":pending.quantity*a.ratio_numerator/a.ratio_denominator})
                if shares != shares.to_integral_value():
                    raise InvalidInput("FRACTIONAL_SPLIT_UNSUPPORTED")
            elif a.kind == "dividend":
                if previous_close != a.entitlement_at:
                    raise InvalidInput("DIVIDEND_ENTITLEMENT_TIME")
                paid = prior_shares*a.cash_per_share
                cash += paid
                dividend_cash += paid
            else:
                if pending:
                    instructions.append({"decision_session_id":pending.decision_session_id,"status":"CANCELED","reason":"DELISTING"})
                    pending = None
                paid = shares*a.cash_per_share
                cash += paid
                settlement_cash += paid
                shares = Decimal(0)
                settled = True
            ledger.append({"at":session.open_at.isoformat(),"kind":a.kind,"action_id":a.action_id,
                           "receipt_at":max(session.open_at,a.published_at,a.available_at,a.ingested_at).isoformat(),
                           "cash":str(cash),"shares":str(shares)})
        bar = bars.get(session.session_id)
        if pending and pending.quantity:
            if not bar or not bar.tradable or bar.open is None:
                diagnostics.append({"session_id":session.session_id,"code":"NO_ELIGIBLE_OPEN_ORDER_CARRIED"})
            elif max(bar.open_provenance.available_at,bar.open_provenance.ingested_at) >= session.close_at:
                raise InvalidInput("OPEN_RECEIPT_AFTER_CLOSE_UNSUPPORTED")
            else:
                q = pending.quantity
                fee = fee_per_fill
                new_cash = cash-q*bar.open-fee
                if q != q.to_integral_value() or new_cash < 0 or shares+q < 0:
                    instructions.append({"decision_session_id":pending.decision_session_id,"status":"REJECTED","reason":"FRACTIONAL_OR_LONG_ONLY_CASH_LIMIT"})
                else:
                    cash,shares = new_cash,shares+q
                    total_fees += fee
                    fills.append({"decision_session_id":pending.decision_session_id,"fill_at":session.open_at.isoformat(),
                          "receipt_at":max(bar.open_provenance.available_at,bar.open_provenance.ingested_at).isoformat(),
                          "instrument_id":data.instruments[0].instrument_id,"quantity":str(q),
                          "price":str(bar.open),"fee":str(fee),"slippage": "0", "currency":"USD"})
                    instructions.append({"decision_session_id":pending.decision_session_id,"status":"FILLED"})
                pending = None
        if bar and not bar.tradable and bar.price_status == "SETTLEMENT_ONLY" and not settled:
            raise InvalidInput("MISSING_DELISTING_SETTLEMENT")
        if shares and (not bar or bar.close is None):
            raise InvalidInput("MISSING_HELD_MARK")
        settlement_only = bool(bar and bar.price_status == "SETTLEMENT_ONLY" and settled)
        observed = bool(bar and bar.price_status == "OBSERVED")
        missing_price = not observed and not settlement_only
        observed_bars += int(observed)
        settlement_only_bars += int(settlement_only)
        missing_price_sessions += int(missing_price)
        if missing_price:
            diagnostics.append({"session_id":session.session_id,
                                "code":"MISSING_FLAT_MARK" if not bar or bar.close is None else "MISSING_PRICE_COVERAGE"})
        nav = cash + shares*((bar.close if bar else None) or Decimal(0))
        if nav <= 0:
            raise InvalidInput("NONPOSITIVE_NAV")
        ret = nav/previous_nav-1 if navs else None
        returns.append(ret)
        navs.append({"at":session.close_at.isoformat(),"session_id":session.session_id,
                     "cash":str(cash),"shares":str(shares),"mark":str(bar.close) if bar and bar.close is not None else None,
                     "nav":str(nav),"return":str(ret) if ret is not None else None,
                     "available_at":max(bar.available_at,bar.ingested_at).isoformat() if bar else session.close_at.isoformat(),
                     "price_status":bar.price_status if bar else None,
                     "status":"MISSING" if missing_price else ("SETTLED" if settled else "OBSERVED")})
        previous_nav,previous_close = nav,session.close_at
        order = orders.get(session.session_id)
        if order:
            if settled:
                raise InvalidInput("ORDER_AFTER_DELISTING")
            decision_at = session.close_at + timedelta(seconds=2)
            if pending:
                raise InvalidInput("MULTIPLE_PENDING_ORDERS_UNSUPPORTED")
            for ref in order.features:
                from .temporal import eligible_feature
                feature,excluded = eligible_feature(data,ref.feature_id,decision_at)
                diagnostics.extend({"feature_id":ref.feature_id,**e} for e in excluded)
                if feature is None or feature.source_revision != ref.source_revision:
                    raise InvalidInput("FUTURE_OR_MISSING_FEATURE")
            if order.quantity:
                pending = order
            else:
                instructions.append({"decision_session_id":order.decision_session_id,"status":"NO_OP","reason":"ZERO_QUANTITY"})
    if pending and pending.quantity:
        instructions.append({"decision_session_id":pending.decision_session_id,"status":"UNFILLED","reason":"END_OF_DATA"})
    computed_metrics = metrics(navs,fills,config.initial_cash,total_fees,dividend_cash,settlement_cash)
    return {
        "schema_version":"polar.report/1", "status":"COMPLETED" if navs else "NO_DATA",
        "qualification":"INFRASTRUCTURE_FIXTURE_ONLY", "financial_verdict":"NOT_RUN",
        "blinding":"BLINDING_NOT_ENFORCED", "dataset_id":data.dataset_id,
        "strategy_version":config.strategy_version,"protocol_version":config.protocol_version,
        "config_hash":digest(config.model_dump(mode="json")),
        "units":{"cash":"USD","nav":"USD","quantity":"share","return":"fraction","fee":"USD"},
        "initial_cash":str(config.initial_cash),"final_cash":str(cash),"final_shares":str(shares),
        "fills":fills,"corporate_action_ledger":ledger,"nav":navs,"orders":instructions,"diagnostics":diagnostics,
        "order_tape":[{"decision_session_id":o.decision_session_id,
                       "decision_at":(next(s.close_at for s in data.sessions if s.session_id==o.decision_session_id)+timedelta(seconds=2)).isoformat(),
                       "quantity":str(o.quantity)} for o in config.orders],
        "coverage":{"expected_sessions":len(data.sessions),"present_bars":len(data.bars),
                    "observed_bars":observed_bars,"settlement_only_bars":settlement_only_bars,
                    "missing_price_sessions":missing_price_sessions,
                    "status":"INCOMPLETE" if missing_price_sessions else "COMPLETE"},
        "metrics":computed_metrics,
        "assumptions":["raw unadjusted USD", "long only; no leverage", "next session open", "USD 1 per nonzero fill", "zero spread and slippage", "synthetic replay; not actual historical ingestion", "one instrument; no ticker changes; same-day dividends only"]}

"""Selected variable-grid profiles in Nautilus1.231, exact-cent native accounts.

The exact-cent account extension is reused from the independently exercised
OBS158 single-account bridge. No full OBS158 runner or its scientific authority
is inherited. Close marks are valuation-only; orders receive open quotes only.
"""
from fractions import Fraction
import importlib.metadata
import uuid

from .ci_research import (INITIAL_CENTS, require, maximum_buy, fee_cents, cents_text)
from .obs158_math import cent_round_micro
from .gym_contract import canonical, sha
from .research_native_money import native_types


def simulate(plan, diagnostics=None):
    if not isinstance(plan, dict):
        from .calendar_study_service import StudyRequest
        if type(plan) is StudyRequest:
            from .event_study import produce_study
            return produce_study(plan.plan,plan.sidecar,plan.roles,plan.binding,diagnostics_callback=diagnostics,preserve_accounts=True)
        from .event_native import EventPlan, simulate_event_component
        if type(plan) is EventPlan:
            return simulate_event_component(plan, diagnostics)
    if plan.get('profile', {}).get('kind') == 'RAW_ACTION_REINVEST':
        from .raw_action_native import simulate as raw_simulate
        return raw_simulate(plan, diagnostics)
    cost_profile = plan.get('cost_profile')
    require('cost_profile' not in plan or cost_profile is not None, 'COST_PROFILE')
    fee_cents(0, 1, cost_profile=cost_profile)  # Closed profile admission before native setup.
    cost_profile = dict(cost_profile) if cost_profile is not None else None
    flat_charge = 100 if cost_profile is None else cost_profile['flat_cents']
    require(importlib.metadata.version("nautilus_trader") == "1.231.0", "ENGINE_VERSION")
    from nautilus_trader.accounting.factory import AccountFactory
    from nautilus_trader.backtest.engine import BacktestEngine
    from nautilus_trader.backtest.models import FeeModel, FillModel, LatencyModel
    from nautilus_trader.config import BacktestEngineConfig, LoggingConfig, StrategyConfig, RiskEngineConfig
    from nautilus_trader.trading.strategy import Strategy
    from nautilus_trader.model.data import QuoteTick, CustomData, DataType
    from nautilus_trader.core.data import Data
    from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue, ClientId
    from nautilus_trader.model.objects import Price, Quantity
    from nautilus_trader.model.currencies import USD
    from nautilus_trader.model.enums import AccountType, OmsType, OrderSide, TimeInForce

    types = native_types()
    symbols, prices, profile = plan["symbols"], plan["prices"], plan["profile"]

    class Boundary(Data):
        def __init__(self, ns): self.ns = ns
        @property
        def ts_event(self): return self.ns
        @property
        def ts_init(self): return self.ns

    class SelectedFee(FeeModel):
        def get_commission(self, order, fill_qty, fill_px, instrument):
            q = Fraction(fill_qty.as_decimal()); p = Fraction(fill_px.as_decimal())*1000000
            require(q.denominator == p.denominator == 1, "FEE_NATIVE_PRECISION")
            return types["money_from_cents"](fee_cents(q.numerator, p.numerator, cost_profile=cost_profile))

    results = []
    for leg_index, leg in enumerate(profile["legs"]):
        venue = Venue("CIRESEARCH" + uuid.uuid4().hex.upper())
        ids = {s: InstrumentId(Symbol(s), venue) for s in symbols}
        # A close may submit one sell and one buy per alias. Keep the risk engine
        # active while admitting C54's frozen same-close tape (at most108 orders).
        submit_limit = max(20, 2*len(symbols)) if profile['kind'] == 'REFERENCE_TARGETS' else 20
        engine = BacktestEngine(BacktestEngineConfig(logging=LoggingConfig(bypass_logging=True),
             risk_engine=RiskEngineConfig(bypass=False, max_order_submit_rate=f"{submit_limit}/00:00:01"),
             run_analysis=False))

        class Adapter(Strategy):
            def __init__(self):
                super().__init__(StrategyConfig(strategy_id=leg, order_id_tag="001",
                                               log_events=False, log_commands=False))
                self.held = {s: 0 for s in symbols}; self.expected_cash = INITIAL_CENTS
                self.opens = {}; self.pending = None; self.outstanding = {}
                self.intents = []; self.orders = []; self.fills = []; self.nav = []
                self.flat = 0; self.bps = 0; self.initiated = False
                self.first_market_event = False

            def cash(self):
                n = Fraction(engine.portfolio.account(venue).balances_total()[USD].as_decimal())*100
                require(n.denominator == 1 and n >= 0, "NATIVE_CASH_DOMAIN")
                return n.numerator

            def reconcile(self):
                require(not self.outstanding and self.cash() == self.expected_cash, "NATIVE_PENDING_OR_CASH")
                if self.fills:
                    self.fills[-1].setdefault("native_cash_after_cents", self.cash())
                actual = {s: 0 for s in symbols}
                for position in self.cache.positions_open():
                    q = Fraction(position.quantity.as_decimal())
                    require(q.denominator == 1 and q >= 0, "NATIVE_POSITION_DOMAIN")
                    actual[position.instrument_id.symbol.value] += q.numerator
                require(actual == self.held, "NATIVE_POSITION_MISMATCH")

            def on_start(self):
                for iid in ids.values(): self.subscribe_quote_ticks(iid)
                for i, grid in enumerate(plan["grid"]):
                    self.clock.set_time_alert_ns("nav-"+str(i), grid["sample_ns"], lambda e,g=grid:self.sample(e,g))
                for i, decision in enumerate(plan["decisions"]):
                    self.clock.set_time_alert_ns("decide-"+str(i), decision["decision_ns"], lambda e,d=decision:self.decide(e,d))
                    for j, s in enumerate(symbols):
                        self.clock.set_time_alert_ns(f"sell-{i}-{j}", decision["open_ns"]+100+j,
                                                    lambda e,d=decision,s=s:self.route(e,d,s,"SELL"))
                        self.clock.set_time_alert_ns(f"buy-{i}-{j}", decision["open_ns"]+200+j,
                                                    lambda e,d=decision,s=s:self.route(e,d,s,"BUY"))

            def on_quote_tick(self, tick):
                if not self.first_market_event:
                    self.first_market_event = True
                    if diagnostics:
                        diagnostics({"phase": "FIRST_NATIVE_MARKET_EVENT", "id": leg, "at_ns": tick.ts_event})
                p = Fraction(tick.ask_price.as_decimal())*1000000
                require(p.denominator == 1, "NATIVE_QUOTE_PRECISION")
                self.opens[tick.instrument_id.symbol.value] = (tick.ts_event, p.numerator)

            def decide(self, event, d):
                self.reconcile()
                require(d["known_ns"] < event.ts_event < d["open_ns"], "DECISION_CLOCK")
                targets = dict(self.held); budgets = {}; signal = None; sizing = None
                if profile["kind"] == "REFERENCE_TARGETS":
                    instruction = d["instructions"][leg]
                    require(set(instruction) <= {"kind", "weights", "signal"} and
                            instruction["kind"] in ("TARGET", "HOLD", "EXIT"), "REFERENCE_INSTRUCTION")
                    if instruction["kind"] == "EXIT":
                        targets = {s: 0 for s in symbols}
                    elif instruction["kind"] == "TARGET":
                        from .research_allocation import desired_targets
                        marks = {s: prices[d["formation"]][s]["close_micro"] for s in symbols}
                        weights = {s: Fraction(v[0],v[1]) for s,v in instruction["weights"].items()}
                        sizing={} if plan.get('capture_consumed_sizing') is True else None
                        targets = desired_targets(self.expected_cash, self.held, marks, weights, witness=sizing)
                        if sizing is not None:
                            if 'model_price_mapping' in plan:
                                sizing['quantity_unit']=plan['quantity_unit']
                                sizing['model_mapping_sha256']=sha(canonical(plan['model_price_mapping']))
                            sizing['eligible_quote']={'date':d['formation'],'at_ns':d['formation_close_ns'],
                                'source_identity':plan['price_evidence'][d['formation']]}
                    signal = instruction.get("signal")
                elif d["kind"] == "EXIT" and (profile["kind"] == "A_MOMENTUM" or leg_index == 0 or d["day"] == profile["end"]):
                    targets = {s: 0 for s in symbols}
                elif profile["kind"] == "A_MOMENTUM":
                    if leg_index == 0:
                        early, late = d["score_dates"]
                        scores = {s: Fraction(prices[late][s]["close_micro"], prices[early][s]["close_micro"])-1 for s in symbols}
                        winner = min(symbols, key=lambda s: (-scores[s], s))
                        marks = prices[d["formation"]]
                        nav = self.expected_cash + sum(cent_round_micro(self.held[s]*marks[s]["close_micro"]) for s in symbols)
                        targets = {s: (nav*10000//marks[s]["close_micro"] if s == winner else 0) for s in symbols}
                        signal = {"winner": winner, "score_dates": d["score_dates"],
                                  "scores": {s: {"numerator": str(v.numerator), "denominator": str(v.denominator)} for s,v in scores.items()}}
                    elif not self.initiated:
                        marks = prices[d["formation"]]
                        targets = {s: INITIAL_CENTS*10000//(3*marks[s]["close_micro"]) for s in symbols}
                        self.initiated = True
                elif leg_index == 0 and d["kind"] == "ENTER":
                    targets = {s: 1000000000 for s in symbols}  # executor computes fee-aware all-cash qmax
                    budgets = {s: self.expected_cash for s in symbols}
                elif leg_index in (1, 2) and not self.initiated:
                    targets = {s: 1000000000 for s in symbols}
                    budgets = {s: 2000000 if leg_index == 1 else INITIAL_CENTS for s in symbols}
                    self.initiated = True
                self.pending = {"day": d["day"], "targets": targets, "budgets": budgets}
                self.intents.append({"day": d["day"], "formation": d["formation"], "known_ns": d["known_ns"],
                                     "decision_ns": event.ts_event, "targets": None if budgets else targets,
                                     "spending_budgets_cents": budgets,
                                     "sizing_kind": "FEE_AWARE_SPENDING_BUDGET" if budgets else "WHOLE_REFERENCE_UNIT_TARGETS" if profile["kind"] == "REFERENCE_TARGETS" else "WHOLE_SHARE_TARGETS",
                                     "signal": signal})
                if plan.get('capture_consumed_sizing') is True:
                    self.intents[-1].update(decision_id=f"{leg}/{d['day']}",instruction_kind=instruction['kind'],
                        sizing_witness=sizing,sizing_status='CONSUMED_TARGET_OPERANDS' if sizing is not None else 'NOT_APPLICABLE_'+instruction['kind'])

            def route(self, event, d, symbol, side):
                self.reconcile()
                require(self.pending is not None and self.pending["day"] == d["day"], "MISSING_INTENT")
                require(set(self.opens) == set(symbols) and
                        all(self.opens[s][0] == d["open_ns"]+i for i,s in enumerate(symbols)), "OPEN_BARRIER")
                target = self.pending["targets"][symbol]; held = self.held[symbol]
                desired = max(held-target, 0) if side == "SELL" else max(target-held, 0)
                p = self.opens[symbol][1]
                if side == "BUY" and symbol in self.pending["budgets"]:
                    # A calendar order is a spending budget, not a fictitious
                    # billion-share target. The bound is only for exact search.
                    desired = maximum_buy(1000000000, p, self.expected_cash, self.pending["budgets"][symbol],
                                          cost_profile=cost_profile)
                clip={} if plan.get("capture_consumed_sizing") is True and side=="BUY" else None
                q = min(desired, held) if side == "SELL" else maximum_buy(desired, p, self.expected_cash,
                                                                self.pending["budgets"].get(symbol),
                                                                cost_profile=cost_profile,witness=clip)
                route_witness={"decision_id":f"{leg}/{d['day']}","target":target,"holdings_before":dict(self.held),
                    "cash_before_cents":self.expected_cash,"price_micro":p,"quote_at_ns":self.opens[symbol][0],
                    "quote_day":d["day"],"desired_delta":desired,"affordability":clip,
                    "cost_profile":dict(cost_profile) if cost_profile is not None else {"flat_cents":100,"bps":10}} if plan.get("capture_consumed_sizing") is True else None
                if not desired:
                    if route_witness is not None:
                        self.orders.append({"id":f"{leg}/{d['day']}/{side}/{symbol}","symbol":symbol,"side":side,"at_ns":event.ts_event,
                            "intended_quantity":0,"routed_quantity":0,"reason":"ZERO_DELTA_NO_ORDER","consumed_operands":route_witness})
                    return
                logical = f"{leg}/{d['day']}/{side}/{symbol}"
                self.orders.append({"id": logical, "symbol": symbol, "side": side, "at_ns": event.ts_event,
                                    "intended_quantity": desired, "routed_quantity": q,
                                    "reason": "FEE_AWARE_BUDGET_CAP" if q < desired else None})
                if route_witness is not None:self.orders[-1]["consumed_operands"]=route_witness
                if not q:
                    return
                fee, settled = fee_cents(q, p, cost_profile=cost_profile), cent_round_micro(q*p)
                require(self.expected_cash + (settled-fee if side == "SELL" else -settled-fee) >= 0,
                        "SELL_FEE_SHORTFALL")
                order = self.order_factory.market(instrument_id=ids[symbol], order_side=OrderSide.SELL if side == "SELL" else OrderSide.BUY,
                         quantity=Quantity.from_int(q), time_in_force=TimeInForce.GTC)
                self.outstanding[str(order.client_order_id)] = {"id": logical, "symbol": symbol, "side": side,
                       "q": q, "price_micro": p, "fee_cents": fee, "settled_cents": settled, "at_ns": event.ts_event}
                self.submit_order(order)

            def on_order_filled(self, event):
                row = self.outstanding.pop(str(event.client_order_id), None)
                require(row is not None and Fraction(event.last_qty.as_decimal()) == row["q"] and
                        Fraction(event.last_px.as_decimal())*1000000 == row["price_micro"] and
                        Fraction(event.commission.as_decimal())*100 == row["fee_cents"] and
                        event.ts_event == row["at_ns"], "NATIVE_FILL_PROFILE")
                sign = 1 if row["side"] == "BUY" else -1
                self.held[row["symbol"]] += sign*row["q"]
                self.expected_cash -= sign*row["settled_cents"] + row["fee_cents"]
                self.flat += flat_charge; self.bps += row["fee_cents"]-flat_charge
                self.fills.append({**row, "cash_after_cents": self.expected_cash,
                                   "exact_notional_micro": row["q"]*row["price_micro"],
                                   "settlement_epsilon_micro": row["settled_cents"]*10000-row["q"]*row["price_micro"],
                                   "cash_rounding_micro": -sign*(row["settled_cents"]*10000-row["q"]*row["price_micro"])})

            def sample(self, event, grid):
                self.reconcile()
                if grid["initial"] or grid["terminal"]:
                    require(not any(self.held.values()), "INITIAL_OR_TERMINAL_HOLDING")
                    amounts = {s: 0 for s in symbols}
                else:
                    amounts = {s: cent_round_micro(self.held[s]*prices[grid["date"]][s]["close_micro"]) for s in symbols}
                exposure = sum(amounts.values()); nav = self.expected_cash+exposure
                require(nav > 0, "NONPOSITIVE_NAV")
                self.nav.append({"date": grid["date"], "nominal_ns": grid["nominal_ns"],
                    "sample_ns": event.ts_event, "cash_cents": self.expected_cash, "exposure_cents": exposure,
                    "nav_cents": nav, "positions": dict(self.held), "position_cents": amounts,
                    "flat_cents": self.flat, "bps_cents": self.bps})

            def on_order_denied(self, event): require(False, "NATIVE_ORDER_DENIED")
            def on_order_rejected(self, event): require(False, "NATIVE_ORDER_REJECTED")
            def on_order_canceled(self, event): require(False, "NATIVE_ORDER_CANCELED")

        adapter = None
        try:
            engine.add_venue(venue=venue, oms_type=OmsType.NETTING, account_type=AccountType.CASH,
                starting_balances=[types["money_from_cents"](INITIAL_CENTS)], base_currency=USD,
                fee_model=SelectedFee(), fill_model=FillModel(prob_fill_on_limit=1., prob_slippage=0., random_seed=0),
                latency_model=LatencyModel(base_latency_nanos=0, insert_latency_nanos=0, update_latency_nanos=0, cancel_latency_nanos=0),
                bar_execution=False, trade_execution=False, allow_cash_borrowing=False, use_random_ids=False)
            AccountFactory.register_account_type(venue.value, types["account_type"])
            for s in symbols:
                engine.add_instrument(types["equity_type"](ids[s], Symbol(s), USD, 6, Price.from_str("0.000001"), Quantity.from_int(1), 0, 0))
            adapter = Adapter(); engine.add_strategy(adapter)
            quotes = []
            for d in plan["decisions"]:
                for i,s in enumerate(symbols):
                    micro = prices[d["day"]][s]["close_micro" if profile["kind"] == "REFERENCE_TARGETS" else "open_micro"]
                    try:
                        p = Price.from_str(f"{micro//1000000}.{micro%1000000:06d}")
                    except (ValueError,OverflowError):
                        if 'model_price_mapping' in plan: require(False,'MODEL_PRICE_NATIVE_DOMAIN')
                        raise
                    ns = d["open_ns"]+i
                    require(Fraction(p.as_decimal())*1000000 == micro, "NATIVE_PRICE_ROUNDTRIP")
                    quotes.append(QuoteTick(ids[s], p, p, Quantity.from_int(1000000000), Quantity.from_int(1000000000), ns, ns))
            engine.add_data(quotes)
            end = plan["grid"][-1]["sample_ns"]
            start = plan["grid"][0]["nominal_ns"]-1
            engine.add_data([CustomData(DataType(Boundary), Boundary(start)), CustomData(DataType(Boundary), Boundary(end))], client_id=ClientId("CI-CONTROL"))
            if diagnostics:
                diagnostics({"phase": "NATIVE_RUN_ENTERED", "id": leg})
            engine.run(end=end, streaming=True); engine.end()
            require(len(adapter.nav) == len(plan["grid"]) and not adapter.outstanding and
                    not any(adapter.held.values()), "NATIVE_INCOMPLETE")
            results.append({"id": leg, "nav": adapter.nav, "intents": adapter.intents,
                            "orders": adapter.orders, "fills": adapter.fills})
            if diagnostics:
                diagnostics({"phase": "ACCOUNT_COMPLETED", "id": leg, "nav_points": len(adapter.nav), "fills": len(adapter.fills)})
        except BaseException:
            if diagnostics:
                diagnostics({"phase": "ACCOUNT_PARTIAL", "id": leg, "completed_accounts": results,
                    "partial": {"nav": adapter.nav, "intents": adapter.intents, "orders": adapter.orders,
                                "fills": adapter.fills} if adapter is not None else None})
            raise
        finally:
            engine.dispose()
    return {"schema": "polar.ci-research-simulation/1", "legs": results,
            **({'cost_profile': cost_profile} if cost_profile is not None else {}),
            **({"quote_basis": "SYNTHETIC_VENDOR_ADJUSTED_REFERENCE_UNIT", "execution_phase": "REFERENCE_CLOSE",
                "quantity_unit": plan.get("quantity_unit", "WHOLE_SYNTHETIC_REFERENCE_UNIT_NOT_RAW_SHARE")} if profile["kind"] == "REFERENCE_TARGETS" else {}),
            "engine": "nautilus_trader-1.231.0", "native_account_rule": "EXACT_CENT_HALF_EVEN"}

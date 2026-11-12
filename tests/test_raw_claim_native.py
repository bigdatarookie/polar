"""Invented real-engine settlement, no retained source or financial oracle."""
from fractions import Fraction
from datetime import datetime,timezone
import uuid

from polar.distribution_claims import Action, State, Phase, recognize, settled_snapshot
from polar.raw_claim_native import settlement_module
from polar.research_native_money import native_types
from polar.ci_research import fee_cents, maximum_buy


def test_native_receivable_transfer_is_spendable_and_not_nav_gain():
    from nautilus_trader.accounting.factory import AccountFactory
    from nautilus_trader.backtest.engine import BacktestEngine
    from nautilus_trader.backtest.models import FeeModel, FillModel
    from nautilus_trader.config import BacktestEngineConfig, LoggingConfig, StrategyConfig
    from nautilus_trader.trading.strategy import Strategy
    from nautilus_trader.model.currencies import USD
    from nautilus_trader.model.objects import Price, Quantity
    from nautilus_trader.model.data import QuoteTick
    from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
    from nautilus_trader.model.enums import AccountType, OmsType, OrderSide

    types = native_types(); module = settlement_module()
    clocks = [int(datetime(2020,1,d,21,tzinfo=timezone.utc).timestamp())*10**9 for d in (1,2,4)]
    venue = Venue('CLAIM' + uuid.uuid4().hex.upper()); iid = InstrumentId(Symbol('INVENTED'), venue)
    class Fee(FeeModel):
        def get_commission(self, order, fill_qty, fill_px, instrument):
            return types['money_from_cents'](fee_cents(int(fill_qty.as_decimal()),
                int(Fraction(fill_px.as_decimal()) * 1000000)))
    class Probe(Strategy):
        def __init__(self):
            super().__init__(StrategyConfig(strategy_id='INVENTED', log_events=False, log_commands=False))
            self.fills = []; self.denied = []; self.claim_state = None
        def on_start(self):
            self.subscribe_quote_ticks(iid)
        def on_quote_tick(self, tick):
            n = tick.ts_event
            if n == clocks[0]:
                self.buy()
            elif n == clocks[1]:
                assert len(self.fills) == 1
                cash = int(engine.portfolio.account(venue).balance_total(USD).as_decimal() * 100)
                assert cash == 100
                self.claim_state = recognize(State('2020-01-01', Phase.CLOSE_SETTLED, cash,
                    (('INVENTED', 1),)), Action('DIV', 'INVENTED', 'INVENTED', '/0',
                    '2020-01-02', '2020-01-03', '10',
                    ('2020-01-01','2020-01-02','2020-01-03','2020-01-04')), '2020-01-02')
                assert maximum_buy(1, 9000000, cash) == 0
                self.buy()  # Real risk engine must refuse unfunded buy.
            elif n == clocks[2]:
                assert len(self.denied) == 1 and len(self.fills) == 1
                self.claim_state = module.settle(self.claim_state, 'DIV', '2020-01-04', {'INVENTED': 900}, expected_ns=clocks[2])
                assert maximum_buy(1, 9000000, self.claim_state.available_cash_cents) == 1
                self.buy()  # Same real risk engine now sees settled cash.
        def buy(self):
            self.submit_order(self.order_factory.market(iid, OrderSide.BUY, Quantity.from_int(1)))
        def on_order_filled(self, event):
            self.fills.append(event)
        def on_order_denied(self, event):
            self.denied.append(event)
    engine = BacktestEngine(BacktestEngineConfig(logging=LoggingConfig(bypass_logging=True), run_analysis=False))
    try:
        engine.add_venue(venue=venue, oms_type=OmsType.NETTING, account_type=AccountType.CASH,
            starting_balances=[types['money_from_cents'](10210)], base_currency=USD,
            fee_model=Fee(), fill_model=FillModel(), modules=[module],
            bar_execution=False, trade_execution=False, allow_cash_borrowing=False)
        AccountFactory.register_account_type(venue.value, types['account_type'])
        engine.add_instrument(types['equity_type'](iid, Symbol('INVENTED'), USD, 6,
            Price.from_str('0.000001'), Quantity.from_int(1), 0, 0))
        probe = Probe(); engine.add_strategy(probe)
        engine.add_data([QuoteTick(iid, Price.from_str(p), Price.from_str(p),
            Quantity.from_int(100), Quantity.from_int(100), ns, ns)
            for ns, p in zip(clocks,['100.000000','9.000000','9.000000'])])
        engine.run(); engine.end()
        assert len(probe.fills) == 2 and len(probe.denied) == 1
        assert sum(int(p.quantity.as_decimal()) for p in engine.cache.positions_open()) == 2
        cash = int(engine.portfolio.account(venue).balance_total(USD).as_decimal() * 100)
        assert cash == 99
        receipt = module.receipts[0]
        assert receipt['before']['free'] == 100 and receipt['after']['free'] == 1100
        assert receipt['claim_decrease_cents'] == 1000
        assert receipt['nav_before_cents'] == receipt['nav_after_cents'] == 2000
        assert receipt['external_cash_flow_cents'] == 0
        probe.claim_state = settled_snapshot(probe.claim_state, '2020-01-04', (('INVENTED', 2),), cash)
        assert probe.claim_state.available_cash_cents == cash and probe.claim_state.claims[0].status == 'PAID'
    finally:
        engine.dispose()

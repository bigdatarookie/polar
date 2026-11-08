"""Prospective one-engine/two-fill invented control. AUTHOR HAS NOT INVOKED IT."""
from fractions import Fraction
import json
from pathlib import Path
import sys


def run_control():
    from polar.obs158_native_money import native_types,mark_native_position
    from nautilus_trader.accounting.factory import AccountFactory
    from nautilus_trader.backtest.engine import BacktestEngine
    from nautilus_trader.backtest.models import FixedFeeModel,FillModel,LatencyModel
    from nautilus_trader.config import BacktestEngineConfig,LoggingConfig,PortfolioConfig,StrategyConfig
    from nautilus_trader.trading.strategy import Strategy
    from nautilus_trader.core.data import Data
    from nautilus_trader.model.data import QuoteTick,MarkPriceUpdate,CustomData,DataType
    from nautilus_trader.model.identifiers import Venue,Symbol,InstrumentId,ClientId
    from nautilus_trader.model.objects import Price,Quantity
    from nautilus_trader.model.currencies import USD
    from nautilus_trader.model.enums import AccountType,OmsType,OrderSide,TimeInForce
    types=native_types();venue=Venue('OBS158CENTQA');iid=InstrumentId.from_str('INVENTED.OBS158CENTQA')
    q=1577885400000000000;result={};fills=[]
    engine=BacktestEngine(BacktestEngineConfig(logging=LoggingConfig(bypass_logging=True),
        portfolio=PortfolioConfig(use_mark_prices=True,bar_updates=False),run_analysis=False))
    class Boundary(Data):
        def __init__(self,ns):self.ns=ns
        @property
        def ts_event(self):return self.ns
        @property
        def ts_init(self):return self.ns
    class Control(Strategy):
        def __init__(self):
            super().__init__(StrategyConfig(strategy_id='OBS158-CENT-QA',order_id_tag='001',
                                            log_events=False,log_commands=False))
        def cash(self):return engine.portfolio.account(venue).balances_total()[USD].as_decimal()
        def on_start(self):
            assert isinstance(engine.portfolio.account(venue),types['account_type'])
            self.subscribe_quote_ticks(iid)
            self.clock.set_time_alert_ns('buy',q+100,lambda e:self.order(OrderSide.BUY))
            self.clock.set_time_alert_ns('mark',q+10100,lambda e:self.mark())
            self.clock.set_time_alert_ns('sell',q+20000,lambda e:self.order(OrderSide.SELL))
            self.clock.set_time_alert_ns('final',q+30100,lambda e:self.final())
        def order(self,side):
            order=self.order_factory.market(instrument_id=iid,order_side=side,
                    quantity=Quantity.from_int(1),time_in_force=TimeInForce.GTC)
            self.submit_order(order)
        def on_order_filled(self,event):
            fills.append({'quantity':str(event.last_qty.as_decimal()),'price':str(event.last_px.as_decimal()),
                          'fee':str(event.commission.as_decimal()),'ts_event':event.ts_event})
        def on_order_rejected(self,event):raise AssertionError('NATIVE_ORDER_REJECTED')
        def on_order_denied(self,event):raise AssertionError('NATIVE_ORDER_DENIED')
        def mark(self):
            positions=self.cache.positions_open()
            assert len(positions)==1
            position=positions[0]
            bridged=mark_native_position(position.quantity,'1.125000')
            result['cash_after_buy']=str(self.cash())
            result['position_cents']=bridged['position_cents']
            result['native_cent_mark']=str(bridged['native_money'].as_decimal())
            result['stock_position_notional_diagnostic']=str(position.notional_value(Price.from_str('1.125000')).as_decimal())
            result['account_value_at_mark']=str(self.cash()+bridged['native_money'].as_decimal())
            assert Fraction(self.cash())==Fraction(9788,100)
            assert bridged['position_cents']=='112'
            assert Fraction(bridged['native_money'].as_decimal())==Fraction(112,100)
            assert Fraction(position.notional_value(Price.from_str('1.125000')).as_decimal())==Fraction(113,100)
        def final(self):
            result['final_cash']=str(self.cash())
            assert Fraction(self.cash())==98 and len(fills)==2 and not self.cache.positions_open()
    try:
        engine.add_venue(venue=venue,oms_type=OmsType.NETTING,account_type=AccountType.CASH,
            starting_balances=[types['money_from_cents'](10000)],base_currency=USD,
            fee_model=FixedFeeModel(types['money_from_cents'](100),charge_commission_once=True),
            fill_model=FillModel(prob_fill_on_limit=1.,prob_slippage=0.,random_seed=0),
            latency_model=LatencyModel(base_latency_nanos=0,insert_latency_nanos=0,
                                      update_latency_nanos=0,cancel_latency_nanos=0),
            bar_execution=False,trade_execution=False,allow_cash_borrowing=False,use_random_ids=False)
        # add_venue first registers calculated-account policy; the account is created
        # only at engine.run initialization. Register its exact class at this seam.
        AccountFactory.register_account_type(venue.value,types['account_type'])
        engine.add_instrument(types['equity_type'](iid,Symbol('INVENTED'),USD,6,
                            Price.from_str('0.000001'),Quantity.from_int(1),0,0))
        control=Control();engine.add_strategy(control)
        price=Price.from_str('1.125000');qty=Quantity.from_int(1000000)
        engine.add_data([QuoteTick(iid,price,price,qty,qty,q,q)])
        engine.add_data([MarkPriceUpdate(iid,price,q+10000,q+10000)])
        engine.add_data([CustomData(DataType(Boundary),Boundary(q+40000))],client_id=ClientId('OBS158-QA'))
        engine.run()
        assert len(fills)==2 and 'final_cash' in result
        assert all(Fraction(f['quantity'])==1 and Fraction(f['price'])==Fraction(1125,1000)
                   and Fraction(f['fee'])==1 for f in fills)
        return {'schema':'polar.obs158-native-cent-control/1','status':'PASS','engine_runs':1,
                'fills':fills,'observations':result,'input_classification':'INVENTED',
                'scope':'NATIVE_EXTENSION_CENT_SETTLEMENT_AND_POSITION_BRIDGE_ONLY'}
    finally:engine.dispose()


if __name__=='__main__':
    # Caller must first bind accepted harness/source and automatic observed image.
    output=Path(sys.argv[1])
    value=run_control()
    with output.open('x') as stream:stream.write(json.dumps(value,sort_keys=True,allow_nan=False)+'\n')

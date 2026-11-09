"""Prospective one-engine/two-fill invented control. AUTHOR HAS NOT INVOKED IT."""
from fractions import Fraction
import json
from pathlib import Path
import sys
import hashlib
import importlib.machinery
import os
import platform
import time
import traceback


def verify_before_import(input_path,expectations_path,config_path,output_root):
    """Standard-library-only binding before any polar/native import or scenario."""
    def check(ok,reason):
        if not ok:raise ValueError(reason)
    def read(path):
        path=Path(path);check(path.is_absolute() and path==path.resolve(),'UNSAFE_BINDING_PATH')
        with path.open('rb') as stream:raw=stream.read(1048577)
        check(len(raw)<=1048576,'BINDING_SIZE')
        return raw,json.loads(raw)
    digest=lambda raw:hashlib.sha256(raw).hexdigest()
    input_raw,inputs=read(input_path);expect_raw,_=read(expectations_path)
    config_raw,config=read(config_path)
    check(inputs['schema']=='polar.obs158-native-cent-input/1'
          and config=={'schema':'polar.obs158-native-cent-config/1',
                       'preparation_receipt_path':'/polar-launch/preparation.json'},'BINDING_SCHEMA')
    prep_raw,prep=read(config['preparation_receipt_path'])
    check(prep['schema']=='polar.observed-preparation/1' and prep['preparation']=='PREPARED',
          'PREPARATION_NOT_VERIFIED')
    check(all(prep['observed']['matches'].values())
          and prep['observed']['image_id']==inputs['expected_image_id']
          and prep['observed']['os']=='linux' and prep['observed']['architecture']=='arm64'
          and prep['expected']['candidate']==inputs['candidate'],'RUNTIME_IDENTITY_MISMATCH')
    check(sys.platform=='linux' and platform.machine()=='aarch64' and os.geteuid()==10001,
          'ACTUAL_PROCESS_PLATFORM_MISMATCH')
    refs=prep['expected']['refs']
    for name,path,raw in (('input',input_path,input_raw),('expectations',expectations_path,expect_raw),
                          ('config',config_path,config_raw),('harness',__file__,Path(__file__).read_bytes())):
        check(refs[name]['path']==str(path) and refs[name]['sha256']==digest(raw),'VISIBLE_BINDING_MISMATCH')
    source=prep['source_binding']
    check(source['packaged_source_independently_observed'] is True
          and source['observed_files']==inputs['source_files'],'PACKAGED_SOURCE_NOT_OBSERVED')
    check(not any(n=='polar' or n.startswith('polar.') for n in sys.modules),
          'CANDIDATE_IMPORTED_BEFORE_BINDING')
    module_root=Path('/app/src/polar')
    expected=inputs['source_files'];check(type(expected) is dict and 1<=len(expected)<=500,
                                        'SOURCE_MANIFEST_BOUND')
    visible={str(p) for p in module_root.rglob('*') if p.is_file() and p.suffix in ('.py','.json','.sql')}
    check(visible==set(expected),'VISIBLE_SOURCE_FILE_SET')
    observed={}
    for name,ref in sorted(expected.items()):
        path=Path(name)
        check(path==path.resolve() and path.is_relative_to(module_root),'UNSAFE_SOURCE_PATH')
        raw=path.read_bytes();actual={'sha256':digest(raw),'bytes':len(raw)}
        check(actual==ref,'VISIBLE_SOURCE_HASH_MISMATCH');observed[name]=actual
    spec=importlib.machinery.PathFinder.find_spec('polar',sys.path)
    check(spec is not None and spec.origin==str(module_root/'__init__.py')
          and list(spec.submodule_search_locations)==[str(module_root)],'AMBIENT_IMPORT_PATH')
    receipt={'schema':'polar.obs158-native-cent-prescenario/1','status':'PREPARED',
             'candidate':inputs['candidate'],'actual_image_id':prep['observed']['image_id'],
             'actual_platform':'linux/arm64','actual_uid':os.geteuid(),
             'preparation_sha256':digest(prep_raw),'config_sha256':digest(config_raw),
             'input_sha256':digest(input_raw),'expectations_sha256':digest(expect_raw),
             'harness_sha256':digest(Path(__file__).read_bytes()),'observed_source_files':observed,
             'scenario_started':False,'observed_at_ns':time.time_ns()}
    target=Path(output_root)/'pre-scenario.json';raw=(json.dumps(receipt,sort_keys=True)+'\n').encode()
    with target.open('xb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
    target.chmod(0o444)
    return digest(raw)


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


def retain_failure(output_root,receipt_sha,stage,exc):
    """Bounded invented-control diagnostics; no locals, environment or input dump."""
    text=''.join(traceback.format_exception(type(exc),exc,exc.__traceback__,limit=32))
    encoded=text.encode('utf-8',errors='replace');limit=16384
    value={'schema':'polar.obs158-native-cent-failure/1','status':'FAIL',
           'scope':'INVENTED_NATIVE_CENT_CONTROL_ONLY',
           'pre_scenario_receipt_sha256':receipt_sha,
           'entrypoint_stage':stage,
           'exception_type':type(exc).__name__[:256],
           'traceback':encoded[:limit].decode('utf-8',errors='replace'),
           'traceback_truncated':len(encoded)>limit,
           'engine_run_and_fill_completion':'UNKNOWN_UNTIL_SEPARATELY_EVIDENCED'}
    raw=(json.dumps(value,sort_keys=True,allow_nan=False)+'\n').encode()
    if len(raw)>131072:raise ValueError('FAILURE_ARTIFACT_BOUND')
    target=Path(output_root)/'failure.json'
    with target.open('xb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
    target.chmod(0o444)


if __name__=='__main__':
    # Qualified launcher command: harness INPUT EXPECTATIONS CONFIG /polar-output.
    if len(sys.argv)!=5:raise SystemExit('BOUND_LAUNCH_REQUIRED')
    receipt_sha=None;stage='PREIMPORT_VERIFICATION'
    try:
        receipt_sha=verify_before_import(*sys.argv[1:])
        stage='NATIVE_CONTROL'
        value=run_control()
        stage='RESULT_PUBLICATION'
        value['pre_scenario_receipt_sha256']=receipt_sha
        output=Path(sys.argv[4])/'result.json'
        with output.open('x') as stream:stream.write(json.dumps(value,sort_keys=True,allow_nan=False)+'\n')
    except BaseException as exc:
        try:retain_failure(sys.argv[4],receipt_sha,stage,exc)
        except Exception:pass  # Diagnostic IO failure never replaces the original failure.
        raise

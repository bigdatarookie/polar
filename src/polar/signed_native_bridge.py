"""Exact-cent signed research/native boundary, not a strategy or Service runner.

Native fills/positions are authoritative. Core admission never installs a proposed
state. Stock Position/Portfolio float PnL and mark functions are not exact oracles.
"""
from dataclasses import dataclass
from fractions import Fraction
from functools import lru_cache
from copy import deepcopy
from types import MappingProxyType

from .distribution_claims import half_even
from .research_native_money import native_types as cash_types
from .signed_account_core import (
    State, Transition, amount_cents, mark, propose_fill, record_confirmed_fill,
)


class BridgeError(ValueError):
    pass


def require(value, reason):
    if not value:
        raise BridgeError(reason)


def cents(money):
    v = Fraction(money.as_decimal()) * 100
    require(v.denominator == 1, 'NATIVE_MONEY_NOT_CENTS')
    return v.numerator


def whole(quantity):
    v = Fraction(quantity.as_decimal())
    require(v.denominator == 1 and v > 0, 'NATIVE_QUANTITY_NOT_POSITIVE_WHOLE')
    return v.numerator


@dataclass(frozen=True)
class TradingLot:
    quantity: int = 0
    # Signed remaining settled opening principal, not native cash or core escrow.
    basis_cents: int = 0


def settled_trade(lot, side, quantity, price):
    """Exact per-fill settled notional; cent basis allocated on partial closes.

    Full close releases the remaining basis exactly; cumulative principal is not
    lost by repeatedly rounding average f64 prices. Unsupported physical crossing
    can still be recorded here but is NOT a bridge admission/reconciliation PASS.
    """
    require(type(lot) is TradingLot and side in ('BUY', 'SELL') and type(quantity) is int and quantity > 0,
            'TRADING_FILL_TYPE')
    total = amount_cents(quantity, price)
    signed = quantity if side == 'BUY' else -quantity
    q, basis = lot.quantity, lot.basis_cents
    require((q == 0 and basis == 0) or (q > 0 and basis >= 0) or (q < 0 and basis <= 0), 'TRADING_BASIS_STATE')
    if q == 0 or (q > 0) == (signed > 0):
        return TradingLot(q + signed, basis + (total if signed > 0 else -total)), 0, False
    closed = min(quantity, abs(q))
    principal = abs(basis) if closed == abs(q) else half_even(Fraction(abs(basis) * closed, abs(q)))
    close_cash = total if closed == quantity else half_even(Fraction(total * closed, quantity))
    realized = close_cash - principal if q > 0 else principal - close_cash
    remaining_basis = basis - (principal if q > 0 else -principal)
    crossed = quantity > abs(q)
    if crossed:
        remaining_basis = (total - close_cash) * (1 if signed > 0 else -1)
    return TradingLot(q + signed, remaining_basis), realized, crossed


@lru_cache(maxsize=1)
def native_types():
    """Construct an extension type only; no registration/account/engine on import."""
    from nautilus_trader.accounting.accounts.margin import MarginAccount
    from nautilus_trader.model.enums import OrderSide
    from nautilus_trader.model.currencies import USD
    base = cash_types()  # pins 1.231.0 and exact native Money/Equity construction

    class ExactCentMarginAccount(MarginAccount):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.exact_lots = {}
            self.exact_fills = []
            self.exact_realized_cents = 0
            self.exact_fee_cents = 0
            self._exact_fill_ids = set()

        def calculate_pnls(self, instrument, fill, position=None):
            require(instrument.quote_currency == USD and instrument.get_base_currency() is None and
                    not instrument.is_inverse and fill.commission.currency == USD, 'EXACT_ACCOUNT_USD_EQUITY_ONLY')
            require(fill.order_side in (OrderSide.BUY, OrderSide.SELL), 'NATIVE_SIDE')
            key = (str(fill.client_order_id), str(fill.trade_id))
            require(key not in self._exact_fill_ids, 'DUPLICATE_NATIVE_ACCOUNT_FILL')
            name = str(instrument.id); qty = whole(fill.last_qty)
            price = Fraction(fill.last_px.as_decimal())
            require((price * 10**6).denominator == 1, 'NATIVE_PRICE_PRECISION')
            side = 'BUY' if fill.order_side == OrderSide.BUY else 'SELL'
            before = self.exact_lots.get(name, TradingLot())
            after, pnl, crossing = settled_trade(before, side, qty, price)
            fee = cents(fill.commission)
            require(fee >= 0, 'NEGATIVE_COMMISSION_UNSUPPORTED')
            self._exact_fill_ids.add(key); self.exact_lots[name] = after
            self.exact_realized_cents += pnl; self.exact_fee_cents += fee
            self.exact_fills.append({'client_order_id': key[0], 'trade_id': key[1], 'instrument_id': name,
                                    'side': side, 'quantity': qty, 'price_usd': str(price),
                                    'settled_notional_cents': amount_cents(qty, price),
                                    'basis_before_cents': before.basis_cents, 'basis_after_cents': after.basis_cents,
                                    'realized_pnl_cents': pnl, 'commission_cents': fee,
                                    'unsupported_crossing': crossing})
            # Commission is deliberately NOT part of this PnL return. Native
            # account machinery debits the original actual commission exactly once.
            return [base['money_from_cents'](pnl)]

        def exact_marked_trading_equity(self, marks):
            require(type(marks) is dict, 'EXACT_MARKS')
            cash = cents(self.balances_total()[USD])
            unrealized = 0
            for name, lot in self.exact_lots.items():
                require(lot.quantity == 0 or name in marks, 'EXACT_MARK_MISSING')
                if lot.quantity:
                    unrealized += amount_cents(lot.quantity, marks[name]) - lot.basis_cents
            return {'native_cash_cents': cash, 'exact_unrealized_cents': unrealized,
                    'exact_trading_equity_cents': cash + unrealized,
                    'exact_realized_cents': self.exact_realized_cents,
                    'actual_fee_cents': self.exact_fee_cents,
                    'stock_f64_position_portfolio_valuation': 'NOT_SUPPORTED_EXACT_ORACLE'}

    return MappingProxyType({**base, 'account_type': ExactCentMarginAccount})


class SignedNativeBridge:
    """One serial order gateway; integration must expose no alternate submit path.

    callbacks: submit_order(native_order), positions()->{source_name:signed_whole},
    account()->registered ExactCentMarginAccount. No portfolio controller here.
    """
    def __init__(self, state, instruments, submit_order, positions, account, *, initial_cents):
        require(type(state) is State and type(instruments) is dict and instruments and
                len(set(map(str, instruments.values()))) == len(instruments), 'BRIDGE_BINDING')
        require(type(initial_cents) is int and initial_cents == state.free_cents and
                not state.positions and not state.claims and not state.accruals and not state.escrow,
                'BRIDGE_INITIAL_FLAT_CASH')
        self.state = state; self.instruments = dict(instruments)
        self._submit = submit_order; self._positions = positions; self._account = account
        self.initial_cents = initial_cents; self.external_adjustment_cents = 0
        self.pending = None; self.halted = False; self.model_survival_failed = False; self.events = []
        self.used_intents = set(); self.used_orders = set(); self.used_fills = set()
        self.native_submission_count = 0

    def propose_and_submit(self, intent_id, order, price, fee_cents, marks, *, located_cap=None,
                           locate_provenance=None, forced=False, funding_mode='NO_CREDIT', funding_assumption=None):
        from nautilus_trader.model.enums import OrderSide
        require(not self.halted, 'BRIDGE_HALTED')
        require(not self.model_survival_failed or forced, 'STICKY_MODEL_DEFAULT_NO_DISCRETIONARY_SUBMISSION')
        require(self.pending is None, 'PENDING_SERIAL_BARRIER')
        require(isinstance(intent_id, str) and intent_id and intent_id not in self.used_intents, 'DUPLICATE_INTENT')
        oid = str(order.client_order_id)
        require(oid not in self.used_orders, 'DUPLICATE_ORDER')
        names = [n for n, iid in self.instruments.items() if str(iid) == str(order.instrument_id)]
        require(len(names) == 1 and order.side in (OrderSide.BUY, OrderSide.SELL), 'ORDER_BINDING')
        name = names[0]; side = 'BUY' if order.side == OrderSide.BUY else 'SELL'; qty = whole(order.quantity)
        proposal = propose_fill(self.state, 'proposal:'+intent_id, name, side, qty, price, fee_cents,
                                located_cap=located_cap, locate_provenance=locate_provenance,
                                forced=forced, funding_mode=funding_mode, funding_assumption=funding_assumption,
                                marks=marks)
        row = {'kind':'ADMISSION','intent_id':intent_id,'order_id':oid,'name':name,'side':side,'quantity':qty,
               'price_usd':str(price),'fee_cents':fee_cents,'status':proposal.status,
               'operands':deepcopy(proposal.operands),'native_submissions':0}
        self.events.append(row); self.used_intents.add(intent_id); self.used_orders.add(oid)
        if proposal.status != 'ADMITTED_PROPOSAL_NOT_EXECUTION':
            return deepcopy(row)
        self.pending = {'intent_id':intent_id,'order_id':oid,'name':name,'side':side,'quantity':qty,'filled':0,
                        'located_cap':located_cap,'locate_provenance':locate_provenance,
                        'funding_mode':funding_mode,'funding_assumption':funding_assumption}
        # The only submit call site. Store pending BEFORE synchronous callbacks.
        self.native_submission_count += 1; row['native_submissions'] = 1
        try:
            self._submit(order)
        except Exception as exc:
            # A throwing submit is not evidence of zero actual effects.
            self.halted = True
            self.events.append({'kind':'SUBMIT_UNKNOWN_EFFECT','order_id':oid,'error':type(exc).__name__,'reason':str(exc)})
            raise
        return deepcopy(row)

    def record_fill(self, event, marks):
        from nautilus_trader.model.enums import OrderSide
        raw = {'order_id':str(event.client_order_id),'trade_id':str(event.trade_id),
               'instrument_id':str(event.instrument_id),'side':str(event.order_side),
               'quantity_token':str(event.last_qty),'price_token':str(event.last_px),
               'commission_token':str(event.commission)}
        key = (raw['order_id'], raw['trade_id'])
        if key in self.used_fills:
            self.halted = True; self.events.append({'kind':'DUPLICATE_CALLBACK_REJECTED','actual_fill':raw})
            raise BridgeError('DUPLICATE_CALLBACK')
        self.used_fills.add(key)
        p = self.pending
        try:
            require(p is not None and raw['order_id'] == p['order_id'] and
                    raw['instrument_id'] == str(self.instruments[p['name']]), 'UNEXPECTED_ACTUAL_FILL')
            side = 'BUY' if event.order_side == OrderSide.BUY else 'SELL' if event.order_side == OrderSide.SELL else None
            from nautilus_trader.model.currencies import USD
            require(event.commission.currency == USD, 'COMMISSION_CURRENCY')
            qty = whole(event.last_qty); price = Fraction(event.last_px.as_decimal()); fee = cents(event.commission)
            require((price * 10**6).denominator == 1, 'NATIVE_PRICE_PRECISION')
            require(side == p['side'] and p['filled'] + qty <= p['quantity'], 'ACTUAL_FILL_ORDER_MISMATCH')
            result = record_confirmed_fill(self.state, 'fill:'+raw['order_id']+':'+raw['trade_id'], p['name'], side,
                                           qty, price, fee, marks, execution_provenance='ACTUAL_NATIVE_CALLBACK',
                                           located_cap=p['located_cap'], locate_provenance=p['locate_provenance'],
                                           funding_mode=p['funding_mode'], funding_assumption=p['funding_assumption'])
            self.state = result.after; p['filled'] += qty
            self.events.append({'kind':'CONFIRMED_NATIVE_FILL','actual_fill':raw,'core_status':result.status,
                                'core_operands':deepcopy(result.operands)})
            self.reconcile(marks)
            if result.status == 'CONFIRMED_EXECUTION_BREACH':
                self.halted = True
            return result
        except Exception as exc:
            self.halted = True
            self.events.append({'kind':'NON_RECONCILED_EXECUTION','actual_fill':raw,
                                'error':type(exc).__name__,'reason':str(exc)})
            raise

    def record_terminal(self, order_id, status):
        require(status in {'FILLED','CANCELLED','REJECTED','DENIED','EXPIRED'}, 'TERMINAL_STATUS')
        require(self.pending is not None and order_id == self.pending['order_id'], 'TERMINAL_ORDER_IDENTITY')
        if status == 'FILLED':
            require(self.pending['filled'] == self.pending['quantity'], 'FILLED_WITHOUT_CALLBACK_CENSUS')
        self.events.append({'kind':'ORDER_TERMINAL','status':status,**deepcopy(self.pending)})
        self.pending = None

    def apply_external(self, transition, marks):
        require(not self.halted and self.pending is None and type(transition) is Transition and
                transition.before == self.state and transition.kind in {
                    'COLLATERAL_TOPUP','EX_ENTITLEMENT','CLAIM_PAYMENT','ACCRUAL_RECOGNITION','ACCRUAL_SETTLEMENT'},
                'EXTERNAL_TRANSITION_BINDING')
        before = mark(self.state, marks)['equity_cents']
        after = mark(transition.after, marks)['equity_cents']
        adjustment = after - before
        self.state = transition.after; self.external_adjustment_cents += adjustment
        self.events.append({'kind':'EXTERNAL_CORE_TRANSITION','event_id':transition.event_id,'status':transition.status,
                            'transition_kind':transition.kind,'recognition_delta_cents':adjustment,
                            'cumulative_external_adjustment_cents':self.external_adjustment_cents,
                            'operands':deepcopy(transition.operands)})
        return self.reconcile(marks)

    def reconcile(self, marks):
        try:
            return self._reconcile(marks)
        except Exception as exc:
            self.halted = True
            self.events.append({'kind':'NON_RECONCILED_ACCOUNT','marks':deepcopy(marks),
                                'error':type(exc).__name__,'reason':str(exc)})
            raise

    def _reconcile(self, marks):
        account = self._account(); actual = self._positions()
        require(type(actual) is dict and all(type(q) is int for q in actual.values()), 'NATIVE_POSITION_TYPES')
        expected = {n:q for n,q in self.state.positions if q}
        require({n:q for n,q in actual.items() if q} == expected, 'NATIVE_CORE_POSITION_RESIDUAL')
        native_marks = {str(iid):marks[n] for n,iid in self.instruments.items() if n in marks}
        native = account.exact_marked_trading_equity(native_marks)
        require(all(account.exact_lots.get(str(iid), TradingLot()).quantity == actual.get(n,0)
                    for n,iid in self.instruments.items()), 'NATIVE_ACCOUNT_POSITION_RESIDUAL')
        require(native['native_cash_cents'] == self.initial_cents + native['exact_realized_cents'] - native['actual_fee_cents'],
                'NATIVE_CASH_PNL_FEE_RESIDUAL')
        core = mark(self.state, marks)
        self.model_survival_failed |= core['equity_cents'] <= 0
        residual = core['equity_cents'] - native['exact_trading_equity_cents'] - self.external_adjustment_cents
        row = {'kind':'RECONCILIATION','core':core,'native':native,
               'external_adjustment_cents':self.external_adjustment_cents,'residual_cents':residual,
               'sticky_model_survival_failed':self.model_survival_failed,
               'default_interpretation':'MODEL_RULE_NOT_OBSERVED_FAIR_VALUE_INSOLVENCY',
               'status':'EXACT_ZERO_RESIDUAL' if residual == 0 else 'NON_RECONCILED_EXECUTION'}
        self.events.append(deepcopy(row))
        if residual:
            self.halted = True
            raise BridgeError('TRADING_EQUITY_RESIDUAL')
        return deepcopy(row)

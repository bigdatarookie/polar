"""Prospective exact-cent extension of Nautilus1.231; no engine calls on import."""
from decimal import localcontext
from fractions import Fraction
from functools import lru_cache
import importlib.metadata
from types import MappingProxyType

from .gym_contract import context
from .obs158_math import require,cent_round_micro,microprice,whole


def cent_string(value):
    require(type(value) is int,'ACCOUNT_DOMAIN')
    sign='-' if value<0 else ''
    return f'{sign}{abs(value)//100}.{abs(value)%100:02d}'


@lru_cache(maxsize=1)
def native_types():
    """Return fixed extension types, without registering or constructing accounts."""
    require(importlib.metadata.version('nautilus_trader')=='1.231.0','ENGINE_VERSION_MISMATCH')
    from nautilus_trader.accounting.accounts.cash import CashAccount
    from nautilus_trader.model.instruments import Equity
    from nautilus_trader.model.objects import Money
    from nautilus_trader.model.currencies import USD
    from nautilus_trader.model.enums import OrderSide

    def money(cents):
        # from_str uses Decimal/HALF_EVEN -> raw integer; the already cent-valued
        # input cannot enter Money(value)'s double/round-away constructor path.
        with localcontext(context()):value=Money.from_str(cent_string(cents)+' USD')
        require(Fraction(value.as_decimal())==Fraction(cents,100),'NATIVE_CENT_ROUND_TRIP')
        return value

    def notional(quantity,price):
        q=Fraction(quantity.as_decimal())
        require(q.denominator==1 and q>=0,'NATIVE_QUANTITY_DOMAIN')
        whole(q.numerator)
        raw=Fraction(price.as_decimal())*1000000
        require(raw.denominator==1 and raw>0,'NATIVE_PRICE_PRECISION_LOSS')
        return money(cent_round_micro(q.numerator*raw.numerator))

    class CentEquity(Equity):
        def notional_value(self,quantity,price,use_quote_for_inverse=False,
                           target_currency=None,conversion_price=None):
            # Nautilus risk checks pass True even for standard equities. The
            # flag selects a currency only for inverse instruments (1.231.0).
            require(not self.is_inverse and conversion_price is None
                    and target_currency in (None,USD) and self.quote_currency==USD,
                    'UNSUPPORTED_NATIVE_NOTIONAL_PROFILE')
            return notional(quantity,price)

    class CentCashAccount(CashAccount):
        def calculate_balance_locked(self,instrument,side,quantity,price,use_quote_for_inverse=False):
            require(instrument.quote_currency==USD and instrument.get_base_currency() is None
                    and not use_quote_for_inverse,'UNSUPPORTED_NATIVE_CASH_PROFILE')
            if side==OrderSide.SELL:return None  # standard equity holds, not base-currency cash
            require(side==OrderSide.BUY,'INVALID_SIDE')
            return notional(quantity,price)

        def calculate_pnls(self,instrument,fill,position=None):
            require(instrument.quote_currency==USD and instrument.get_base_currency() is None,
                    'UNSUPPORTED_NATIVE_CASH_PROFILE')
            amount=notional(fill.last_qty,fill.last_px)
            cents=Fraction(amount.as_decimal())*100
            require(cents.denominator==1,'NATIVE_CENT_ROUND_TRIP')
            require(fill.order_side in (OrderSide.BUY,OrderSide.SELL),'INVALID_SIDE')
            return [money(-cents.numerator if fill.order_side==OrderSide.BUY else cents.numerator)]

    return MappingProxyType({'equity_type':CentEquity,'account_type':CentCashAccount,'money_from_cents':money})


def mark_native_position(quantity,raw_close,factor=1):
    """Exact cent valuation bridge from native initial units to physical units.

    This does not call Position.notional_value or Portfolio.net_exposures, whose
    stock double/round-away paths are not the canonical OBS158 mark definition.
    No cash or quantity is mutated; actual native fills/positions remain authoritative.
    """
    native=Fraction(quantity.as_decimal())
    require(native.denominator==1 and native>=0 and type(factor) is int and factor in (1,4,5),
            'SPLIT_UNIT_DOMAIN')
    physical=whole(native.numerator*factor)
    exact=physical*microprice(raw_close)
    cents=cent_round_micro(exact)
    types=native_types();value=types['money_from_cents'](cents)
    return {'native_quantity':str(native.numerator),'physical_quantity':str(physical),
            'factor':factor,'exact_mark_micro':str(exact),'position_cents':str(cents),
            'native_money':value}

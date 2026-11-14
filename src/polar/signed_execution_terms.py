"""Exact actual-fill commission and explicit side quotes for the fixed pair host.

No execution, cash ledger, market reader or independent price inference.
"""
from dataclasses import dataclass
from fractions import Fraction
from .signed_native_bridge import require


def ceiling(value):
    require(type(value) is Fraction and value>=0,'EXECUTION_NONNEGATIVE_EXACT_AMOUNT')
    return -(-value.numerator//value.denominator)


@dataclass(frozen=True)
class SideQuote:
    name: str
    source_event: str
    scenario: str
    reference: Fraction
    bid: Fraction
    ask: Fraction

    def __post_init__(self):
        require(all(type(v) is str and v for v in (self.name,self.source_event,self.scenario)), 'SIDE_QUOTE_IDENTITY')
        require(all(type(v) is Fraction and v>0 for v in (self.reference,self.bid,self.ask)) and
                self.bid<=self.reference<=self.ask,'SIDE_QUOTE_DOMAIN')
        # Source reference precision is unchanged; adverse execution may add two
        # decimal places. No source token is rounded/rescaled to fit native.
        require((self.reference*10**8).denominator==1 and
                all((v*10**8).denominator==1 for v in (self.bid,self.ask)), 'SIDE_QUOTE_PRECISION')

    def price(self,side):
        require(side in ('BUY','SELL'),'SIDE_QUOTE_SIDE')
        return self.ask if side=='BUY' else self.bid


def execution_quote(name,source_event,scenario,reference,*,adverse=False):
    require(type(adverse) is bool,'SIDE_QUOTE_ADVERSE_TYPE')
    return SideQuote(name,source_event,scenario,reference,
        reference*Fraction(99,100) if adverse else reference,
        reference*Fraction(101,100) if adverse else reference)


class OrderFees:
    """Flat once per actually filled order + cumulative ceiling bps delta.

    Caller invokes only on positive actual callbacks; proposal estimates do not
    consume this state. Native venue and saved verifier use distinct instances.
    """
    def __init__(self,flat_cents,bps):
        require(type(flat_cents) is int and flat_cents>=0 and type(bps) is int and 0<=bps<=10000,'ORDER_FEE_PARAMETERS')
        self.flat=flat_cents;self.bps=bps;self.orders={}

    def fill(self,order_id,quantity,price):
        require(type(order_id) is str and order_id and type(quantity) is int and quantity>0 and
                type(price) is Fraction and price>0,'ORDER_FEE_ACTUAL_FILL')
        previous=self.orders.get(order_id,Fraction())
        total=previous+quantity*price
        delta=ceiling(total*100*self.bps/10000)-ceiling(previous*100*self.bps/10000)
        flat=self.flat if previous==0 else 0
        self.orders[order_id]=total
        return {'order_id':order_id,'flat_cents':flat,'bps_cents':delta,'total_cents':flat+delta,
                'prior_notional_usd':previous,'cumulative_notional_usd':total}

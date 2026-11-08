"""Exact price-ledger account primitives. No engine, input reads or global context."""
from fractions import Fraction
import re


class Obs158Error(ValueError):
    pass


def require(ok,reason):
    if not ok:raise Obs158Error(reason)


def microprice(token):
    """Source lexeme -> integer micro-USD, without rounding or float conversion."""
    require(type(token) is str and len(token)<=64 and
            re.fullmatch(r'(?:0|[1-9][0-9]{0,17})(?:\.[0-9]{1,6})?',token),
            'LOSSLESS_6DP_REQUIRED')
    integer,_,fraction=token.partition('.')
    value=int(integer)*1000000+int(fraction.ljust(6,'0') or '0')
    require(value>0,'NONPOSITIVE_SOURCE_PRICE')
    return value


def whole(value):
    require(type(value) is int and 0<=value<=10**24,'INVALID_PHYSICAL_QUANTITY')
    return value


def cent_round_micro(value):
    """HALF_EVEN after multiplication; one cent equals10,000 micro-USD."""
    require(type(value) is int and abs(value)<=10**60,'ACCOUNT_DOMAIN')
    sign=-1 if value<0 else 1
    quotient,remainder=divmod(abs(value),10000)
    if 2*remainder>10000 or 2*remainder==10000 and quotient%2:quotient+=1
    return sign*quotient


def fraction_record(value):
    value=Fraction(value)
    return {'numerator':str(value.numerator),'denominator':str(value.denominator)}


def settled_fill(side,intended,held,cash_cents,open_micro):
    """One intended physical order at one open; no market simulation or retry."""
    require(side in ('BUY','SELL'),'INVALID_SIDE')
    whole(intended);whole(held)
    require(type(cash_cents) is int and 0<=cash_cents<=10**30
            and type(open_micro) is int and 0<open_micro<=10**24,'ACCOUNT_DOMAIN')
    cap=min(intended,1000000,held if side=='SELL' else intended)
    reasons=[]
    if intended>1000000:reasons.append('MODEL_DEPTH_CAP')
    if side=='SELL' and intended>held:reasons.append('HELD_QUANTITY_CAP')
    q=cap
    if side=='BUY':
        low,high=0,cap
        while low<high:
            middle=(low+high+1)//2
            if cent_round_micro(middle*open_micro)+100<=cash_cents:low=middle
            else:high=middle-1
        q=low
        if q<cap:reasons.append('FEE_AWARE_CASH_CAP')
    elif q and cash_cents+cent_round_micro(q*open_micro)-100<0:
        q=0;reasons.append('SELL_FEE_CASH_SHORTFALL')
    exact_micro=q*open_micro;settled=cent_round_micro(exact_micro);fee=100 if q else 0
    epsilon=Fraction(settled,100)-Fraction(exact_micro,1000000)
    signed=-epsilon if side=='BUY' else epsilon
    change=(-settled-fee) if side=='BUY' else (settled-fee)
    require(cash_cents+change>=0,'NEGATIVE_CASH')
    return {'side':side,'intended_quantity':str(intended),'filled_quantity':str(q),
            'unrouted_quantity':str(intended-q),'fee_cents':str(fee),
            'gross_exact_notional_USD':fraction_record(Fraction(exact_micro,1000000)),
            'settled_notional_cents':str(settled),'epsilon_USD':fraction_record(epsilon),
            'signed_cash_rounding_USD':fraction_record(signed),'cash_delta_cents':str(change),
            'cash_after_cents':str(cash_cents+change),'reasons':reasons}


def marked_account(cash_cents,holdings,close_micro,aliases):
    """Round each physical position separately. Zero positions need no mark."""
    require(type(cash_cents) is int and cash_cents>=0,'ACCOUNT_DOMAIN')
    require(set(holdings)==set(aliases) and len(set(aliases))==len(aliases),'ALIAS_JOIN_MISMATCH')
    positions=[];total=cash_cents
    for alias in aliases:
        held=whole(holdings[alias])
        if held:
            require(alias in close_micro,'MISSING_POSITION_MARK')
            price=close_micro[alias]
            require(type(price) is int and 0<price<=10**24,'ACCOUNT_DOMAIN')
            exact=held*price
        else:exact=0
        rounded=cent_round_micro(exact);total+=rounded
        positions.append({'alias':alias,'physical_quantity':str(held),
                          'exact_mark_USD':fraction_record(Fraction(exact,1000000)),
                          'position_cents':str(rounded),
                          'mark_rounding_USD':fraction_record(Fraction(rounded,100)-Fraction(exact,1000000))})
    require(total>0,'INVALID_ACCOUNT_VALUE')
    return {'cash_cents':str(cash_cents),'price_ledger_value_cents':str(total),'positions':positions}


def snapshot_targets(value_cents,closes_micro,aliases):
    require(type(value_cents) is int and value_cents>0 and len(aliases)==158
            and set(closes_micro)==set(aliases),'INVALID_QUALIFIED_SNAPSHOT')
    result={}
    for alias in aliases:
        price=closes_micro[alias]
        require(type(price) is int and 0<price<=10**24,'ACCOUNT_DOMAIN')
        result[alias]=(value_cents*10000)//(158*price)
        whole(result[alias])
    return result


def forward_unit(physical_quantity,raw_micro,factor):
    """Exact forward native-unit correspondence; never backward-adjust source."""
    whole(physical_quantity)
    require(type(factor) is int and factor in (1,4,5)
            and physical_quantity%factor==0 and type(raw_micro) is int and raw_micro>0,
            'SPLIT_UNIT_DOMAIN')
    native=physical_quantity//factor;mark=raw_micro*factor
    require(native*mark==physical_quantity*raw_micro,'SPLIT_UNIT_VALUE_MISMATCH')
    return {'native_quantity':str(native),'native_mark_micro':str(mark),
            'physical_quantity':str(physical_quantity),'factor':factor,
            'position_cents':str(cent_round_micro(native*mark))}

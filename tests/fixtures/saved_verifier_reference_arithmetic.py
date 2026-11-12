"""Independent reviewer arithmetic extracted for P2; no filesystem/producer/native calls."""
from datetime import datetime
from decimal import Context, Decimal, DivisionByZero, InvalidOperation, Overflow, ROUND_HALF_EVEN, localcontext
from fractions import Fraction
import re
YEAR_NS=31557600*10**9
def utc_ns(token):
    match = re.fullmatch('(\\d{4}-\\d\\d-\\d\\dT\\d\\d:\\d\\d:\\d\\d)(?:\\.(\\d{1,9}))?Z', token)
    if not match:
        raise ValueError('expected exact UTC nominal sample with at most9fractional digits')
    point = datetime.strptime(match[1], '%Y-%m-%dT%H:%M:%S')
    delta = point - datetime(1970, 1, 1)
    return (delta.days * 86400 + delta.seconds) * 10 ** 9 + int((match[2] or '').ljust(9, '0'))

def canonical(value):
    if value is None:
        return None
    if not value.is_finite():
        raise ValueError('nonfinite')
    token = format(value, 'f')
    if '.' in token:
        token = token.rstrip('0').rstrip('.')
    return '0' if value == 0 else token

def metrics(nav_cents, elapsed_ns):
    if len(nav_cents) < 3 or any((not isinstance(v, int) or v <= 0 for v in nav_cents)) or elapsed_ns <= 0:
        raise ValueError('requires positive exact cent NAV, n>=2 returns, positive elapsed')
    values = [Fraction(v) for v in nav_cents]
    returns = [b / a - 1 for (a, b) in zip(values, values[1:])]
    n = len(returns)
    mean = sum(returns, Fraction(0)) / n
    variance = sum(((r - mean) ** 2 for r in returns), Fraction(0)) / (n - 1)
    context = Context(prec=50, rounding=ROUND_HALF_EVEN, Emin=-999999, Emax=999999)
    for condition in (InvalidOperation, DivisionByZero, Overflow):
        context.traps[condition] = True
    with localcontext(context):
        project = lambda x: Decimal(x.numerator) / Decimal(x.denominator)
        root252 = Decimal(252).sqrt()
        sd = project(variance).sqrt()
        volatility = root252 * sd
        sharpe = root252 * project(mean) / sd if variance else None
        ratio = project(values[-1] / values[0])
        years = project(Fraction(elapsed_ns, YEAR_NS))
        cagr = (ratio.ln() / years).exp() - 1
    return {'mean_exact': mean, 'variance_exact': variance, 'sharpe': sharpe, 'volatility': volatility, 'cagr': cagr, 'returns_exact': returns}

def round_even_fraction(value):
    whole, rem=divmod(value.numerator,value.denominator)
    return whole+(2*rem>value.denominator or 2*rem==value.denominator and whole%2)
def ceil_fraction(value):
    return -(-value.numerator//value.denominator)
def amounts_micro(quantity,price_micro,flat_cents=100,bps=10):
    if type(quantity) is not int or quantity<0 or type(price_micro) is not int or price_micro<=0 or min(flat_cents,bps)<0:
        raise ValueError("outside whole-unit positive-price profile")
    if quantity==0:return (0,0)
    exact_micro=quantity*price_micro
    return (round_even_fraction(Fraction(exact_micro,10000)),flat_cents+ceil_fraction(Fraction(exact_micro*bps,100000000)))
def affordable_qty(desired,price_micro,cash_cents,flat_cents=100,bps=10):
    if type(desired) is not int or desired<0 or type(cash_cents) is not int or cash_cents<0:
        raise ValueError("outside nonnegative cash/target profile")
    lo,hi=0,desired
    while lo<hi:
        q=(lo+hi+1)//2
        amount,fee=amounts_micro(q,price_micro,flat_cents,bps)
        if amount+fee<=cash_cents:lo=q
        else:hi=q-1
    return lo

"""Shared reference-unit action wrapper using accepted exact-cent ledger primitives.

Decision targets are fixed from eligible marks. Future execution quotes may cap
buys, never enlarge targets. No model, data reading or native call on import.
"""
from fractions import Fraction
from .ci_research import require, fee_cents, maximum_buy, INITIAL_CENTS
from .obs158_math import cent_round_micro


def nav_cents(cash, held, prices):
    require(type(cash) is int and cash >= 0 and set(held) == set(prices), 'ALLOCATION_STATE')
    require(all(type(q) is int and 0 <= q <= 1000000000 for q in held.values()) and
            all(type(p) is int and p > 0 for p in prices.values()), 'ALLOCATION_DOMAIN')
    amounts = {s: cent_round_micro(held[s]*prices[s]) for s in held}
    nav = cash+sum(amounts.values()); require(nav > 0, 'ALLOCATION_NONPOSITIVE_NAV')
    return nav, amounts


def desired_targets(cash, held, prices, weights):
    nav, _ = nav_cents(cash, held, prices)
    require(type(weights) is dict and set(weights) == set(held) and
            all(type(w) is Fraction and w >= 0 for w in weights.values()) and
            sum(weights.values()) <= 1, 'ALLOCATION_WEIGHTS')
    targets = {s: (nav*10000*weights[s].numerator)//(prices[s]*weights[s].denominator) for s in held}
    require(all(q <= 1000000000 for q in targets.values()), 'ALLOCATION_TARGET_BOUND')
    return targets


class ReferenceLedger:
    def __init__(self, symbols, *, cost_profile=None):
        require(type(symbols) is list and symbols == sorted(set(symbols)) and symbols, 'ALLOCATION_SYMBOL_ORDER')
        fee_cents(0, 1, cost_profile=cost_profile)
        self.cost_profile = dict(cost_profile) if cost_profile is not None else None
        self.flat_charge = 100 if cost_profile is None else cost_profile['flat_cents']
        self.symbols = list(symbols); self.cash = INITIAL_CENTS
        self.held = {s: 0 for s in symbols}; self.previous_target = 0
        self.fills = []; self.orders = []; self.flat_cents = 0; self.bps_cents = 0

    def mark(self, prices):
        nav, amounts = nav_cents(self.cash, self.held, prices)
        return {'nav_cents': nav, 'cash_cents': self.cash, 'positions': dict(self.held),
                'position_cents': amounts, 'exposure_cents': sum(amounts.values()),
                'flat_cents': self.flat_cents, 'bps_cents': self.bps_cents}

    def intent(self, decision_prices, weights):
        return {'targets': desired_targets(self.cash, self.held, decision_prices, weights),
                'decision_nav_cents': self.mark(decision_prices)['nav_cents'],
                'decision_positions': dict(self.held), 'decision_cash_cents': self.cash}

    def action_intent(self, action, decision_prices, *, terminal=False):
        require(type(action) is int and 0 <= action <= len(self.symbols), 'ALLOCATION_ACTION')
        if terminal:
            return {'targets': {s: 0 for s in self.symbols}, 'action': 0, 'terminal': True}
        if action == self.previous_target:
            return {'targets': dict(self.held), 'action': action, 'terminal': False, 'hold': True}
        weights = {s: Fraction(int(action == i+1)) for i,s in enumerate(self.symbols)}
        return {**self.intent(decision_prices, weights), 'action': action, 'terminal': False, 'hold': False}

    def execute(self, intent, execution_prices, *, date=None):
        targets = intent['targets']
        require(set(targets) == set(self.held) == set(execution_prices) and
                all(type(q) is int and 0 <= q <= 1000000000 for q in targets.values()), 'ALLOCATION_TARGETS')
        for side in ('SELL', 'BUY'):
            for symbol in self.symbols:
                desired = max(self.held[symbol]-targets[symbol], 0) if side == 'SELL' else max(targets[symbol]-self.held[symbol], 0)
                if not desired: continue
                p = execution_prices[symbol]
                q = desired if side == 'SELL' else maximum_buy(desired, p, self.cash, cost_profile=self.cost_profile)
                self.orders.append({'date': date, 'symbol': symbol, 'side': side,
                                    'desired_quantity': desired, 'quantity': q})
                if not q: continue
                fee, settled = fee_cents(q,p,cost_profile=self.cost_profile), cent_round_micro(q*p)
                cash = self.cash+(settled-fee if side == 'SELL' else -settled-fee)
                require(cash >= 0, 'ALLOCATION_SELL_FEE_SHORTFALL')
                self.cash = cash; self.held[symbol] += q if side == 'BUY' else -q
                self.flat_cents += self.flat_charge; self.bps_cents += fee-self.flat_charge
                self.fills.append({'date': date, 'symbol': symbol, 'side': side, 'q': q,
                    'price_micro': p, 'fee_cents': fee, 'settled_cents': settled,
                    'cash_after_cents': self.cash, 'exact_notional_micro': q*p})
        if 'action' in intent: self.previous_target = intent['action']
        if intent.get('terminal'):
            require(not any(self.held.values()), 'ALLOCATION_TERMINAL_HOLDINGS')
            self.previous_target = 0
        return self.mark(execution_prices)

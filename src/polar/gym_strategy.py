"""Trusted, fixed strategy code sees eligible close observations only."""
from fractions import Fraction
from .gym_contract import SYMBOLS, STRATEGIES, GymError, fraction

def targets(strategy_id, observation, held, terminal=False):
    if strategy_id not in STRATEGIES: raise GymError('UNKNOWN_STRATEGY')
    if terminal: return {symbol:0 for symbol in SYMBOLS}
    nav=fraction(observation['nav'])
    if nav<=0: raise GymError('INVALID_NAV')
    return {symbol:int(nav // (len(SYMBOLS)*fraction(observation['closes'][symbol])))
            for symbol in SYMBOLS}

def intents(strategy_id, observation, held, decision_ns, order_date, terminal=False):
    desired=targets(strategy_id, observation, held, terminal)
    return [{'strategy_id':strategy_id, 'decision_ns':decision_ns,
             'eligible_K_ns':observation['known_by_ns'], 'observation_date':observation['date'],
             'order_date':order_date,'symbol':s,'held':held[s], 'target':desired[s],
             'signed_delta':desired[s]-held[s], 'sell_quantity':max(held[s]-desired[s],0),
             'buy_quantity':max(desired[s]-held[s],0)} for s in SYMBOLS]

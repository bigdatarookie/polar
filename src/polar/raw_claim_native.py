"""Nautilus account-state settlement of an existing exact-cent receivable.

This is an internal asset transfer, not external funding, trading PnL or a fee
rebate. The pure component remains authoritative for entitlement and once-only
payment; actual native balances and event identity are independently reconciled.
No native imports or operations occur on import.
"""
from dataclasses import asdict
from fractions import Fraction

from .ci_research import require
from .distribution_claims import Phase, transition, valuation
from .gym_contract import canonical, sha
from .research_native_money import native_types


def settlement_module():
    from nautilus_trader.backtest.modules import SimulationModule
    from nautilus_trader.backtest.config import SimulationModuleConfig
    from nautilus_trader.model.currencies import USD
    from nautilus_trader.model.objects import AccountBalance

    class ClaimSettlement(SimulationModule):
        def __init__(self):
            super().__init__(SimulationModuleConfig())
            self.receipts = []

        def process(self, ts_now):
            pass  # Explicit close scheduler owns payment ordering.

        def log_diagnostics(self, logger):
            pass

        def reset(self):
            self.receipts = []

        def balances(self):
            account = self.exchange.get_account()
            require(account is not None and not self.exchange.is_frozen_account,
                    'RAW_CLAIM_NATIVE_ACCOUNT')
            balance = account.balance(USD)
            def cents(value):
                n = Fraction(value.as_decimal()) * 100
                require(n.denominator == 1 and n >= 0, 'RAW_CLAIM_NATIVE_CENTS')
                return n.numerator
            return account, balance, {k: cents(getattr(balance, k)) for k in ('total', 'free', 'locked')}

        def settle(self, state, event_id, session_date, position_marks_cents):
            account, balance, before = self.balances()
            require(before['locked'] == 0 and before['total'] == before['free'] == state.available_cash_cents,
                    'RAW_CLAIM_NATIVE_PREPAY_RECONCILIATION')
            after, evidence = transition('pay', state, {'event_id': event_id,
                'session_date': session_date, 'phase': Phase.PRE_DECISION_CLOSE.name})
            old_nav = valuation(state, position_marks_cents)
            new_nav = valuation(after, position_marks_cents)
            amount = after.available_cash_cents - state.available_cash_cents
            require(amount >= 0 and old_nav['receivable_cents'] - new_nav['receivable_cents'] == amount
                    and old_nav['nav_cents'] == new_nav['nav_cents'], 'RAW_CLAIM_TRANSFER_CONSERVATION')
            event_hash = sha(canonical(asdict(evidence)))
            previous = len(account.events())
            if amount:
                # Supported ExecutionClient API routes through Portfolio.update_account;
                # no mutation of cached balances or shadow affordability ledger.
                money = native_types()['money_from_cents']
                self.exchange.exec_client.generate_account_state(
                    balances=[AccountBalance(money(after.available_cash_cents), money(0),
                                             money(after.available_cash_cents))],
                    margins=[], reported=True, ts_event=self.clock.timestamp_ns(),
                    info={'kind': 'INTERNAL_DISTRIBUTION_RECEIVABLE_SETTLEMENT',
                          'event_id': event_id, 'claim_evidence_sha256': event_hash,
                          'external_cash_flow_cents': 0, 'claim_decrease_cents': amount})
            _, _, actual = self.balances()
            require(actual == {'total': after.available_cash_cents,
                'free': after.available_cash_cents, 'locked': 0}, 'RAW_CLAIM_NATIVE_POSTPAY_RECONCILIATION')
            require(len(account.events()) == previous + int(amount > 0), 'RAW_CLAIM_ACCOUNT_EVENT_COUNT')
            if amount:
                require(account.events()[-1].info.get('claim_evidence_sha256') == event_hash,
                        'RAW_CLAIM_ACCOUNT_EVENT_BINDING')
            self.receipts.append({'kind': 'INTERNAL_DISTRIBUTION_RECEIVABLE_SETTLEMENT',
                'event_id': event_id, 'at_ns': self.clock.timestamp_ns(),
                'before': before, 'after': actual, 'claim_decrease_cents': amount,
                'native_balance_updates': int(amount > 0), 'external_cash_flow_cents': 0,
                'nav_before_cents': old_nav['nav_cents'], 'nav_after_cents': new_nav['nav_cents'],
                'claim_evidence': asdict(evidence)})
            return after

    return ClaimSettlement()

"""Invented affordability, causal-sizing and terminal controls for both ML/RL."""
from fractions import Fraction
import unittest
from polar.research_allocation import ReferenceLedger


class Allocation(unittest.TestCase):
    def test_future_quote_can_only_clip_frozen_target(self):
        ledger=ReferenceLedger(['AAA']); p={'AAA':10000000}
        intent=ledger.intent(p,{'AAA':Fraction(1)})
        self.assertEqual(intent['targets']['AAA'],10000)
        cheap=ReferenceLedger(['AAA']); cheap.execute(intent,{'AAA':5000000})
        self.assertEqual(cheap.held['AAA'],10000) # lower future price cannot enlarge quantity
        expensive=ReferenceLedger(['AAA']); expensive.execute(intent,{'AAA':20000000})
        self.assertLess(expensive.held['AAA'],10000)
        self.assertGreaterEqual(expensive.cash,0)

    def test_same_requested_target_hold_includes_zero_fill(self):
        ledger=ReferenceLedger(['AAA'])
        first=ledger.action_intent(1,{'AAA':10**18}); ledger.execute(first,{'AAA':10**18})
        self.assertEqual(ledger.held['AAA'],0)
        self.assertEqual(ledger.previous_target,1)
        same=ledger.action_intent(1,{'AAA':1000000}); ledger.execute(same,{'AAA':1000000})
        self.assertEqual(ledger.held['AAA'],0)
        self.assertEqual(len(ledger.fills),0)

    def test_terminal_ignores_submitted_action_and_sells_once(self):
        ledger=ReferenceLedger(['AAA','BBB']); prices={'AAA':10000000,'BBB':10000000}
        ledger.execute(ledger.action_intent(1,prices),prices)
        before=len(ledger.fills)
        terminal=ledger.action_intent(2,prices,terminal=True)
        out=ledger.execute(terminal,prices)
        self.assertEqual(len(ledger.fills),before+1)
        self.assertEqual(ledger.fills[-1]['side'],'SELL')
        self.assertEqual((out['exposure_cents'],ledger.previous_target),(0,0))

    def test_sales_precede_buys_and_fees_are_not_double_debited(self):
        ledger=ReferenceLedger(['AAA','BBB']); p={'AAA':10000000,'BBB':11000000}
        ledger.execute(ledger.action_intent(2,p),p)
        old=len(ledger.fills); ledger.execute(ledger.action_intent(1,p),p)
        self.assertEqual([r['side'] for r in ledger.fills[old:]],['SELL','BUY'])
        expected=10000000
        for row in ledger.fills:
            expected += (row['settled_cents'] if row['side']=='SELL' else -row['settled_cents'])-row['fee_cents']
        self.assertEqual(ledger.cash,expected)

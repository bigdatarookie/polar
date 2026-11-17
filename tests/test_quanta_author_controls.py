"""Causal and state-transition checks over invented controls only."""
from datetime import date, timedelta
from fractions import Fraction as F
import unittest

from research_candidates.quant_a_drawdown_gate.policy import target, WINDOW


def history(last=F(100), old=F(100), length=WINDOW):
    first = date(2000, 1, 1)
    return [(first + timedelta(days=i), last if i == length-1 else old)
            for i in range(length)]


class GateTests(unittest.TestCase):
    def decide(self, rows, state):
        return target(rows, state, rows[-1][0])

    def test_exact_exit_and_reentry_boundaries(self):
        off = self.decide(history(F(80)), True)
        self.assertEqual((off.kind, off.observed_risk_on,
                          off.vti_weight, off.bil_weight),
                         ("TARGET", False, F(0), F(1)))
        on = self.decide(history(F(90)), False)
        self.assertEqual((on.kind, on.observed_risk_on), ("TARGET", True))

    def test_hysteresis_preserves_observed_state(self):
        for state in (True, False):
            d = self.decide(history(F(85)), state)
            self.assertEqual((d.kind, d.observed_risk_on), ("HOLD", state))
            self.assertIsNone(d.vti_weight)

    def test_rolling_peak_expiration_is_explicit(self):
        rows = history(F(90), F(90), WINDOW+1)
        rows[0] = (rows[0][0], F(120))
        d = self.decide(rows, False)
        self.assertEqual((d.kind, d.observed_risk_on, d.drawdown),
                         ("TARGET", True, F(0)))

    def test_no_warmup_fabrication_and_first_target(self):
        d = self.decide(history(length=WINDOW-1), None)
        self.assertEqual((d.kind, d.observed_risk_on), ("HOLD", None))
        first = self.decide(history(F(80)), None)
        self.assertEqual((first.kind, first.observed_risk_on), ("TARGET", False))

    def test_future_duplicate_or_float_observations_rejected(self):
        rows = history()
        with self.assertRaises(ValueError):
            target(rows, True, rows[-2][0])
        with self.assertRaises(ValueError):
            self.decide(rows + [rows[-1]], True)
        with self.assertRaises(ValueError):
            self.decide(rows[:-1] + [(rows[-1][0], 100.0)], True)


if __name__ == "__main__":
    unittest.main()

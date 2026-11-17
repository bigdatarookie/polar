import unittest
from datetime import datetime, timedelta, timezone
from fractions import Fraction

from research_candidates.quant_a_fomc_calendar.policy import (
    Close, Episode, clusters, calendar_target, sma_target, daily_decisions,
    fixed_target, DEFENSIVE, NORMAL, BILLS,
)


class CalendarAuthorPolicyTest(unittest.TestCase):
    def setUp(self):
        self.t = datetime(2040, 1, 1, tzinfo=timezone.utc)

    def at(self, days):
        return self.t + timedelta(days=days)

    def test_touching_risk_episodes_do_not_trigger_return_churn(self):
        a = Episode("a", self.at(1), self.at(3), self.at(4))
        b = Episode("b", self.at(4), self.at(6), self.at(7))
        c = clusters([b, a])
        self.assertEqual(len(c), 1)
        self.assertEqual(c[0].event_ids, ("a", "b"))
        self.assertEqual(c[0].label_end, self.at(6))
        self.assertEqual(c[0].return_close, self.at(7))
        first = calendar_target(self.at(0), self.at(1), [a, b], None)
        self.assertEqual((first.kind, first.observed_state, first.weights), ("TARGET", True, DEFENSIVE))
        self.assertEqual(calendar_target(self.at(3), self.at(4), [a, b], True).kind, "HOLD")
        result = calendar_target(self.at(6), self.at(7), [a, b], True)
        self.assertEqual((result.kind, result.observed_state, result.weights), ("TARGET", False, NORMAL))

    def test_observed_state_survives_holding_or_no_fill_mismatch(self):
        e = Episode("x", self.at(2), self.at(4), self.at(5))
        target = calendar_target(self.at(1), self.at(2), [e], False)
        self.assertTrue(target.observed_state)
        # No holdings/fill argument exists: absent fills cannot prompt a retry.
        self.assertEqual(calendar_target(self.at(2), self.at(3), [e], target.observed_state).kind, "HOLD")

    def test_clocks_duplicates_and_incomplete_episode_fail(self):
        e = Episode("x", self.at(1), self.at(2), self.at(3))
        with self.assertRaisesRegex(ValueError, "DUPLICATE"):
            clusters([e, e])
        with self.assertRaisesRegex(ValueError, "COMPLETE_EPISODE"):
            Episode("bad", self.at(1), self.at(2), self.at(2))
        with self.assertRaisesRegex(ValueError, "DECISION_MUST"):
            calendar_target(self.at(1), self.at(1), [e], None)
        with self.assertRaisesRegex(ValueError, "AWARE_CLOCK"):
            calendar_target(datetime(2040, 1, 1), self.at(1), [e], None)

    def rows(self, prices):
        return [Close(self.at(i), self.at(i)+timedelta(hours=1), Fraction(p)) for i, p in enumerate(prices)]

    def test_daily_clock_month_end_formation_and_terminal_priority(self):
        points = daily_decisions([self.at(0), self.at(1), self.at(4)])
        self.assertEqual(points, ((self.at(0)+timedelta(seconds=60), self.at(1)),
                                  (self.at(1)+timedelta(seconds=60), self.at(4))))
        def control(leg, first=False, month=False, terminal=False):
            return fixed_target(leg, first=first, month_end_formation=month, terminal=terminal)
        self.assertEqual(control("MONTHLY_FIXED_HALF", first=True).weights, DEFENSIVE)
        self.assertEqual(control("MONTHLY_FIXED_HALF").kind, "HOLD")
        self.assertEqual(control("MONTHLY_FIXED_HALF", month=True).kind, "TARGET")
        self.assertEqual(control("FULL_VTI", month=True).kind, "HOLD")
        self.assertEqual(control("FULL_BIL", month=True).kind, "HOLD")
        self.assertEqual(control("MONTHLY_FIXED_HALF", first=True, month=True, terminal=True).kind, "EXIT")
        with self.assertRaisesRegex(ValueError, "NO_STRICT"):
            daily_decisions([self.at(0), self.at(0)+timedelta(seconds=30), self.at(1)])

    def test_sma_exact_window_equality_and_unavailable_prefix(self):
        equal = self.rows([10] * 200)
        result = sma_target(equal, self.at(200), None)
        self.assertEqual((result.kind, result.observed_state, result.weights), ("TARGET", False, BILLS))
        # Exactly the last 200; an old outlier must not turn 200 into 201.
        extra = self.rows([1000000] + [10] * 199 + [11])
        result = sma_target(extra, self.at(201), False)
        self.assertEqual((result.kind, result.observed_state, result.weights), ("TARGET", True, NORMAL))
        unavailable = sma_target(equal[:-1], self.at(200), True)
        self.assertEqual((unavailable.kind, unavailable.observed_state, unavailable.weights), ("HOLD", True, None))

    def test_same_close_future_and_unknown_availability_do_not_leak(self):
        rows = self.rows([10] * 200)
        unknown = rows[:-1] + [Close(rows[-1].close_at, None, Fraction(1000000))]
        self.assertEqual(sma_target(unknown, self.at(200), None).reason, "INSUFFICIENT_ELIGIBLE_PREFIX")
        # Close at D is unfinished for this strict close<D model, even when K=D.
        future = rows + [Close(self.at(200), self.at(200), Fraction(1000000))]
        result = sma_target(future, self.at(200), False)
        self.assertEqual((result.kind, result.observed_state), ("HOLD", False))
        future_k = rows + [Close(self.at(200), self.at(202), Fraction(1000000))]
        self.assertEqual(sma_target(future_k, self.at(201), False).observed_state, False)
        with self.assertRaisesRegex(ValueError, "ORDERED_UNIQUE"):
            sma_target(rows + [rows[-1]], self.at(201), None)


if __name__ == "__main__":
    unittest.main()

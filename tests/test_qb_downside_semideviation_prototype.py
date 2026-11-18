"""Invented analytic/boundary oracles; no source data or native execution."""
from fractions import Fraction as F
import unittest
from polar.qb_downside_semideviation_prototype import downside_targets, SYMBOLS, RiskBudgetError


def diagonal(values):
 return [[values[i] if i==j else F() for j in range(4)] for i in range(4)]


def raw(result,leg):
 return [F(*result['raw_weights'][leg][s]) for s in SYMBOLS]


class InventedOracles(unittest.TestCase):
 def test_hand_inverse_downside_and_complete_grid_certificate(self):
  result=downside_targets(diagonal([F(1,10000)]*4),[[-.0625,-.125,-.25,-.5] for _ in range(60)])
  self.assertEqual(raw(result,'DSV'),[F(8,15),F(4,15),F(2,15),F(1,15)])
  self.assertEqual(raw(result,'INV'),[F(1,4)]*4)
  cert=result['certificate']
  self.assertEqual([F(*v) for v in cert['lower_partial_second_moments']],[F(1,256),F(1,64),F(1,16),F(1,4)])
  target=F(*cert['annual_common_target_variance'])
  self.assertEqual(target,F(63,10000))
  for leg in ['DSV','EW','INV']:
   row=cert['scales'][leg];k=row['index'];n=row['units'];v=F(*row['annual_raw_variance'])
   self.assertEqual(F(*row['annual_selected_variance']),v*F(k,n)**2)
   self.assertLessEqual(v*F(k,n)**2,target)
   if k<n:self.assertGreater(v*F(k+1,n)**2,target)
   self.assertEqual(sum(F(*v) for v in result['weights'][leg].values())+F(*row['cash']),1)
  self.assertEqual(result['actual_counts']['downside_return_operands'],240)
  self.assertEqual(result['actual_counts']['scalar_root_reciprocal_calls'],8)
 def test_denominator_all_returns_not_negative_subset(self):
  rows=[[-.125,-.25,-.5,-.0625] for _ in range(30)]+[[.25,.5,.125,.0625] for _ in range(30)]
  result=downside_targets(diagonal([F(1,100)]*4),rows)
  self.assertEqual([F(*v) for v in result['certificate']['lower_partial_second_moments']],
                   [F(1,128),F(1,32),F(1,8),F(1,512)])
 def test_exact_zero_boundary_and_all_zero(self):
  c=diagonal([F(1,100)]*4)
  result=downside_targets(c,[[.1,-.2,.3,-.4] for _ in range(60)])
  self.assertEqual(raw(result,'DSV'),[F(1,2),F(),F(1,2),F()])
  self.assertEqual(result['certificate']['zero_downside_indices'],[0,2])
  self.assertEqual(result['actual_counts']['scalar_root_reciprocal_calls'],4)
  result=downside_targets(c,[[.1,.2,.3,.4] for _ in range(60)])
  self.assertEqual(raw(result,'DSV'),[F(1,4)]*4)
 def test_positive_magnitudes_do_not_enter_lower_partial_moment(self):
  c=diagonal([F(1,100)]*4)
  negative=[[-.1,-.2,-.3,-.4] for _ in range(30)]
  a=downside_targets(c,negative+[[.01,.02,.03,.04] for _ in range(30)])
  b=downside_targets(c,negative+[[.9,.8,.7,.6] for _ in range(30)])
  self.assertEqual(a['raw_weights']['DSV'],b['raw_weights']['DSV'])
  self.assertEqual(a['certificate']['lower_partial_second_moments'],b['certificate']['lower_partial_second_moments'])
 def test_psd_singular_admitted_and_nonsymmetric_nonpsd_rejected(self):
  rows=[[-.1,-.2,-.3,-.4] for _ in range(60)]
  result=downside_targets([[F(1,100)]*4 for _ in range(4)],rows)
  self.assertTrue(all(F(*p)>0 for p in result['certificate']['shrunk_ldl_pivots']))
  for c in [[[1,2,0,0],[2,1,0,0],[0,0,1,0],[0,0,0,1]],
            [[1,1,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]],diagonal([0,1,1,1])]:
   with self.assertRaises(RiskBudgetError):downside_targets(c,rows)
 def test_invalid_partial_work_and_no_argument_mutation(self):
  c=diagonal([F(1,100)]*4);rows=[[-.1,-.2,-.3,-.4] for _ in range(60)]
  snapshot=[r[:] for r in rows];before=[r[:] for r in c]
  downside_targets(c,rows);self.assertEqual(c,before);self.assertEqual(rows,snapshot)
  rows[0][2]=float('nan')
  with self.assertRaises(RiskBudgetError) as caught:downside_targets(c,rows)
  self.assertEqual(caught.exception.events['actual_counts']['downside_return_operands'],2)
  self.assertEqual(caught.exception.events['actual_counts']['completed_target_legs'],0)
  with self.assertRaisesRegex(RiskBudgetError,'DSV_RETURN_SHAPE'):downside_targets(c,rows[:-1])

if __name__=='__main__':unittest.main()

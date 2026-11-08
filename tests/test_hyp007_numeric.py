"""Prospective author count: THREE ridge fits and TWO invented native tree fits, one invocation."""
import json
import math
import os
from pathlib import Path
import unittest

from polar.hyp007_contract import DiagnosticError
from polar.hyp007_numeric import (THREAD_ENV, array, representations, ridge_fit, ridge_predict,
                                  tree_fit, tree_predict, losses)


@unittest.skipUnless(os.environ.get("POLAR_HYP007_NUMERIC_TESTS") == "1", "exact numeric build required")
class Numeric(unittest.TestCase):
    def test_ridge_objective_and_two_other_dimensions(self):
        import numpy as np
        x = [[float(i),float(i%3),2.,float(i%7),float(i%11),float(i%13)] for i in range(260)]
        y = [i*.002+(i%3)*.01 for i in range(260)]
        transforms,train,score = representations(x,x[:9])
        self.assertEqual(transforms["main"]["population_sd"][2],0.)
        self.assertEqual(train["ridge21"].shape,(260,21))
        self.assertEqual(transforms["product_order"][0],[0,1])
        self.assertEqual(transforms["product_order"][-1],[4,5])
        for name in ("ridge6","ridge21"):
            z = train[name]
            model = ridge_fit(z,y)  # 2 counted fits
            # Independent augmented normal equations include an unpenalized intercept.
            augmented = np.column_stack([np.ones(len(z)),z])
            penalty = np.diag([0.]+[float(len(z))]*z.shape[1])
            expected = np.linalg.solve(augmented.T@augmented+penalty,augmented.T@array(y))
            np.testing.assert_allclose([model["intercept"]]+model["coefficients"],expected,rtol=1e-10,atol=1e-12)
            self.assertEqual(len(ridge_predict(model,score[name])),9)
        model = ridge_fit([[0.]*6 for _ in range(200)],[.25]*200)  # third counted fit
        self.assertEqual(model["coefficients"],[0.]*6)
        self.assertEqual(ridge_predict(model,[[0.]*6]),[.25])
        with self.assertRaises(DiagnosticError): array([[math.nan]*6])

    def test_native_constant_and_nonconstant_persisted_predictions(self):
        defaults = json.loads(Path(os.environ["POLAR_HYP007_DEFAULTS"]).read_bytes())
        for constant in (True,False):  # exactly 2 counted native fits
            n = 250 if constant else 900
            x = [[float(i%97),float(i%31),float(i%7),float(i%17),float(i%11),float(i%13)] for i in range(n)]
            y = [.2 if constant else (0.1 if i%97<48 else -0.1) for i in range(n)]
            _,train,score = representations(x,x[:17])
            model = tree_fit(train["tree"],y,defaults)
            predictions = tree_predict(model,score["tree"])
            self.assertEqual(predictions,tree_predict(json.loads(json.dumps(model)),score["tree"]))
            self.assertEqual(model["requested_rounds"],50)
            self.assertIsNone(model["wrapper_update_calls"])
            self.assertIsNone(model["native_update_calls"])
            self.assertEqual(model["actual_trees"],len(model["leaves_per_tree"]))
            if constant:
                self.assertEqual(model["status"],"SUCCESS_NATIVE_CONSTANT")
                self.assertEqual(model["actual_trees"],1)
                self.assertLess(model["actual_iterations"],50)
            else:
                self.assertEqual(model["status"],"SUCCESS")
        result = losses([1.,2.],[0.,0.])
        self.assertEqual(result,{"losses":[1.,4.],"SSE":5.,"n":2,"MSE":2.5})


if __name__ == "__main__":
    unittest.main()

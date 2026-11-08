"""Single-thread binary64 caller arithmetic and the one fixed native learner map."""
import math
import os
from itertools import combinations

from .hyp007_contract import check, finite, canonical, sha

THREAD_ENV = {k: "1" for k in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS",
                                "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS", "BLIS_NUM_THREADS")}
TREE_PARAMETERS = {
    "boosting_type": "gbdt", "objective": "regression_l2", "n_estimators": 50,
    "learning_rate": .05, "max_depth": 2, "num_leaves": 4, "min_child_samples": 200,
    "min_child_weight": .001, "min_split_gain": 0., "max_bin": 255,
    "subsample": 1., "subsample_freq": 0, "colsample_bytree": 1.,
    "reg_alpha": 0., "reg_lambda": 0., "random_state": 0, "n_jobs": 1,
    "deterministic": True, "force_col_wise": True, "use_missing": True,
    "zero_as_missing": False, "bagging_seed": 0, "feature_fraction_seed": 0,
    "data_random_seed": 0, "drop_seed": 0, "extra_seed": 0, "objective_seed": 0,
}


def numpy():
    check(all(os.environ.get(k) == v for k,v in THREAD_ENV.items()), "HYP007_THREAD_ENV")
    import numpy as np
    from threadpoolctl import threadpool_info
    check(all(p["num_threads"] == 1 for p in threadpool_info()), "HYP007_NATIVE_THREADS")
    return np


def array(value, columns=None):
    np = numpy()
    result = np.array(value, dtype=np.float64, order="C", copy=True)
    check(result.ndim in (1,2) and np.isfinite(result).all(), "HYP007_NUMERICAL_INVALID")
    if columns is not None:
        check(result.ndim == 2 and result.shape[1] == columns, "HYP007_MATRIX_SHAPE")
    return result


def moments(matrix):
    np = numpy()
    check(matrix.ndim == 2 and len(matrix) > 0, "HYP007_MATRIX_SHAPE")
    n = len(matrix)
    means = [finite(math.fsum(float(x) for x in matrix[:,j])/n) for j in range(matrix.shape[1])]
    scales = [finite(math.sqrt(math.fsum(finite((float(x)-means[j])**2) for x in matrix[:,j])/n))
              for j in range(matrix.shape[1])]
    return {"mean": means, "population_sd": scales}


def standardize(matrix, transform):
    np = numpy()
    check(matrix.shape[1] == len(transform["mean"]) == len(transform["population_sd"]), "HYP007_MATRIX_SHAPE")
    result = np.zeros(matrix.shape, dtype=np.float64, order="C")
    for j, (mean, scale) in enumerate(zip(transform["mean"], transform["population_sd"])):
        if scale != 0.:
            result[:,j] = (matrix[:,j]-mean)/scale
    check(np.isfinite(result).all(), "HYP007_NUMERICAL_INVALID")
    return result


def products(matrix):
    np = numpy()
    result = np.column_stack([matrix[:,j]*matrix[:,k] for j,k in combinations(range(6), 2)])
    check(np.isfinite(result).all(), "HYP007_NUMERICAL_INVALID")
    return np.ascontiguousarray(result, dtype=np.float64)


def representations(train, score):
    np = numpy()
    train, score = array(train,6), array(score,6)
    main = moments(train)
    six, score_six = standardize(train, main), standardize(score, main)
    product = moments(products(six))
    twentyone = np.ascontiguousarray(np.column_stack([six, standardize(products(six), product)]))
    score_twentyone = np.ascontiguousarray(np.column_stack([score_six, standardize(products(score_six), product)]))
    return {"main": main, "products": product, "product_order": [list(pair) for pair in combinations(range(6),2)]}, \
        {"ridge6": six, "ridge21": twentyone, "tree": six}, \
        {"ridge6": score_six, "ridge21": score_twentyone, "tree": score_six}


def ridge_fit(z, y):
    np = numpy()
    z, y = array(z), array(y)
    check(z.ndim == 2 and y.ndim == 1 and len(y) == len(z) > 0, "HYP007_MATRIX_SHAPE")
    n = len(y)
    zm = np.array([math.fsum(float(x) for x in z[:,j])/n for j in range(z.shape[1])], dtype=np.float64)
    ym = finite(math.fsum(float(v) for v in y)/n)
    zc, yc = np.ascontiguousarray(z-zm), np.ascontiguousarray(y-ym)
    u, singular, vt = np.linalg.svd(zc, full_matrices=False)
    beta = vt.T @ ((singular/(singular*singular+n))*(u.T@yc))
    intercept = finite(float(ym-zm@beta))
    gradient = zc.T@(zc@beta-yc)/n+beta
    residual = finite(float(np.max(np.abs(gradient))))
    tolerance = finite(1e-8*(1+float(np.max(np.abs(zc.T@yc/n)))+float(np.max(np.abs(beta)))))
    check(np.isfinite(beta).all() and residual <= tolerance, "HYP007_RIDGE_STATIONARITY")
    return {"kind": "ridge", "coefficients": beta.tolist(), "intercept": intercept,
            "lambda": 1, "sum_loss_alpha": n, "stationarity": residual, "tolerance": tolerance,
            "precision": "IEEE754_BINARY64", "singular_values": singular.tolist()}


def ridge_predict(model, z):
    np = numpy()
    predictions = array(z)@array(model["coefficients"])+model["intercept"]
    check(np.isfinite(predictions).all(), "HYP007_PREDICTION_INVALID")
    return predictions.tolist()


def tree_fit(z, y, defaults):
    """defaults is a preverified, persisted build artifact, not inferred after training."""
    np = numpy()
    import lightgbm as lgb
    check(lgb.__version__ == "4.6.0", "HYP007_BUILD_MISMATCH")
    check(defaults["explicit_parameters"] == TREE_PARAMETERS and defaults["native_defaults"] and
          defaults["aliases"] and defaults["native_precision"], "HYP007_DEFAULTS_NOT_BOUND")
    model = lgb.LGBMRegressor(**TREE_PARAMETERS)
    expected = defaults["sklearn_parameters"]
    check(model.get_params(deep=False) == expected, "HYP007_DEFAULTS_MISMATCH")
    z, y = array(z,6), array(y)
    model.fit(z,y)
    booster = model.booster_
    text = booster.model_to_string(num_iteration=-1)
    reloaded = lgb.Booster(model_str=text)
    prediction = reloaded.predict(z, num_iteration=-1, num_threads=1)
    check(np.isfinite(prediction).all(), "HYP007_MODEL_INVALID")
    dump = reloaded.dump_model(num_iteration=-1)
    leaves = [tree["num_leaves"] for tree in dump["tree_info"]]
    check(len(leaves) == reloaded.num_trees() and len(leaves) > 0, "HYP007_MODEL_INVALID")
    return {"kind": "lightgbm", "model": text, "model_sha256": sha(text.encode()),
            "requested_rounds": 50, "wrapper_update_calls": None, "native_update_calls": None,
            "actual_iterations": reloaded.current_iteration(), "actual_trees": reloaded.num_trees(),
            "leaves_per_tree": leaves, "sklearn_n_iter": int(model.n_iter_),
            "status": "SUCCESS_NATIVE_CONSTANT" if all(n == 1 for n in leaves) else "SUCCESS",
            "parameters_sha256": sha(canonical(defaults))}


def tree_predict(model, z):
    np = numpy()
    import lightgbm as lgb
    check(sha(model["model"].encode()) == model["model_sha256"], "HYP007_MODEL_HASH")
    booster = lgb.Booster(model_str=model["model"])
    result = booster.predict(array(z,6), num_iteration=-1, num_threads=1)
    check(np.isfinite(result).all(), "HYP007_PREDICTION_INVALID")
    return result.tolist()


def losses(predictions, targets):
    check(len(predictions) == len(targets) > 0, "HYP007_LOSS_SHAPE")
    values = [finite((finite(float(p))-finite(float(y)))**2) for p,y in zip(predictions, targets)]
    sse = finite(math.fsum(values))
    return {"losses": values, "SSE": sse, "n": len(values), "MSE": finite(sse/len(values))}

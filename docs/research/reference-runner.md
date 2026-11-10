# Chronological reference-unit research

The current executable profile is `V033-A-RIDGE-LONG4-ADJREF-V1`, protocol v1.2.
It consumes the existing DE `polar.synthetic-reference-source-input/1`
manifest, its pinned quote stream and reference calendar. It never substitutes
raw OHLC for adjusted reference quotes or credits actions a second time.

Use the existing commands in the same locked environment as public CI:

```
polar research-config SEED.json
polar research-preflight CONFIG.json
polar research-run CONFIG.json
polar research-recompute reference-experiment-HASH
```

A seed names `namespace` (INVENTED or RETAINED), `profile_id`, `protocol_path`,
`input_path`, `calendar_path`, `timezone_path`, `code_revision`,
`runtime_image_id`, `candidate_id`, `experiment_id` and, for an original retained
operation, `execution_authority_path`. The command binds current packaged source
and the actual `POLAR_ARTIFACT_ROOT` identity. It does not fit or grant execution.
Files and derived results remain local under the source rights contract.

The retained operation authority is `polar.reference-research-operation/1`,
`action=ORIGINAL`, the exact config-minus-authority binding SHA-256, and
`expected_prior_attempts=[]`. It references the exact independent method binding,
reserved candidate card and exact-runner standard CI result. The runtime image,
source, dependencies and artifact-root identity must also be observed by the
operation owner. This authority is a machine binding of the existing scientific
assignment, not an additional Lead or per-test approval. The current frozen
profile permits one fit and validation/final evaluation; an existing attempt is
never automatically reset, refunded or retried.

The model uses the unchanged accepted HYP007 population-moment/scaling and
mean-loss lambda1 centered SVD ridge kernel. All six numerical thread variables
and actual native thread pools must be one. NumPy 2.2.6 and threadpoolctl 3.6.0
are required; the shared runtime provides these explicitly. Only mature training
labels enter the one fit. Later phases reuse that model and scaler. Each phase
has fresh model USD100000. Intended whole quantities use eligible decision
marks; a future next-close quote can only clip buys for cash and costs.

The semantic store retains the model, train and phase forecast diagnostics,
native simulations, evaluations, source/runtime binding and immutable manifest.
A partial failure preserves its attempt and any completed fit. Stored-only
recomputation verifies member hashes, forecast SSE/MSE from stored prediction and
label representations, and exact-cent evaluation. It performs no model, native
trading, source read or store write. Model JSON preserves binary64 round trips;
monetary/evaluation values are cents or canonical scalar strings.

The existing saved-result API receives separate VALIDATION and FINAL records,
with the same trained-model provenance, explicit
`SYNTHETIC_VENDOR_ADJUSTED_REFERENCE_UNIT` basis and no investor-total-return or
raw-share claim. Numerical point screens are producer evidence; independent
financial reviews remain separate content-bound sidecars. No client calculates
finance. The current service does not yet expose a retained PPO training route;
the causal Gymnasium environment is a separately qualified component and is not
an A execution prerequisite.

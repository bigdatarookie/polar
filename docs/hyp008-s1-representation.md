# S1 source metadata and represented arithmetic, unit 1

This component implements the prospectively frozen S1 source/mask and arithmetic
boundaries. It has no experiment/run entry point and grants no real scientific
start. Fixed model family, runtime/default lock, evaluator and immutable Service
integration are subsequent units of the same package. The exposed two-toy LP
prototype is not used or rerun here.

`polar.hyp008_s1_source` exposes frozen `Eligibility`, `Opportunity`,
`SourceBinding`, `adapt_metadata_row`, and `prepare_metadata`. The typed facade
rejects wrong shapes and preserves the whole ordered census, separate training
admission and C/I/E/P reasons, source references, clocks, basis and versions.
The retained identity is fixed to the supplied revision/content/delivery and403
rows; explicit INVENTED bindings support technical controls in a separate domain.
References are validated structurally here: the eventual bound input loader must
verify actual hash/size/JSON-pointer closure before claiming dataset integrity.
No such real loader invocation or source fitness claim is made by this unit.

The raw metadata adapter follows the delivered TYPE-DESCRIPTOR: explicit five-slot
order, original common A K, independent B evidence K/scheduled end and raw source
references. It never parses numeric X/B payloads. Defined/undefined status versus
payload presence is validated. The null-A unavailable slot pointer is retained as
a source reference, not dereferenced as a numeric child. Source publication's
UNBOUND mask marker is not used as S1 mask authority. Offset-aware instants are
compared in UTC; nominal selection uses original decision_date, not inferred UTC
calendar dates. Equal scheduled-end times preserve the last nominal grid index.

Training cutoff is2022-01-01T00:00Z; expected-ready is00:15Z and assessment is
2026-11-09T09:37:23Z. All nominal2022 opportunities remain C. I uses only source,
K/basis/version/units, expected ready and the exactly52consecutive slots ending
at the latest nominal index whose scheduled end is <=D. Choose this anchor before
checking B status/K; no sliding/topup. E is independent current B/end/K readiness;
P=I intersect E. An empty I returns NOT_STARTED/NO_ISSUE_COMPARISON, with full
metadata and zero starts. This is a component return, not a persisted lineage;
the later Service must durably record it before calling its lifecycle complete.

`polar.hyp008_s1_numeric` exposes rational `round_binary64`, `round_sqrt`,
`ProjectedValue`, `projected_payload`, `fit_transform` and `transform_score`.
Binary64 fields use16lowercase big-endian hex; rational objects are normalized
numerator/denominator decimal strings. Numeric failures raise S1NumericError;
the caller must record NUMERIC_UNVERIFIED and fail the predeclared family, never
remove a row or substitute zero. Metadata errors are S1SourceError.

Integer nearest-even quotient/remainder handles normals/subnormals, signed
finite values, overflow and canonical positive zero. Every ordinary conversion
retains original input and exact input-minus-output residual. Source payload
interpretation preserves the full fraction/radicand/method/residual object and
checks its exact projection residual. Sqrt instead returns radicand, adjacent
finite candidates, exact squared midpoint comparison and rounded-square sign;
it never invents a rational square-root residual.

Train-only constants are classified from exact rational projections before
casting. Normalized fraction versus nonnegative-root certificates can prove the
same exact value; differing exact objects under one projection fail upstream
collapse. Unknown proof types fail closed. Nonconstant cast/transform collapse
fails; no epsilon, clipping, imputation, rank deletion or ambient Decimal context.
Mean/variance use exact dyadics and population variance about the exact mean.
Frozen mean/scale are correctly rounded once; each Z then rounds the exact
centered/frozen-scale ratio once. Constants map+0 at scoring while preserving
the observed scoring payload. All five coordinates remain.

Per-call input safety: at most10000rows, lexical decimal<=256characters and
absolute decimal exponent<=4096; normalized ratio tokens<=2048characters and
rational values<=16384bits. These are arithmetic/parser bounds, not test-call or
scientific trial budgets. Linear-generation4096-bit guarded arithmetic and its
separate verifier limits/default locks are not implemented or widened here.
Closed typed records and schema-tagged component results are not the final
integrated S1 experiment semantic schema. That schema, authority ledger, model
serialization and full publication projection must be frozen before integrated
candidate invocation in later units. No real c478 numeric rows are read by the
component's author controls.

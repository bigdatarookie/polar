# Exact supplied-certificate verifier

polar.exact_certificate verifies one supplied represented-input certificate. It
does not solve, generate coefficients, standardize data, predict, read files or
qualify source population/masks/transforms. It imports only dataclasses/hashlib,
performs no proof work at import, and does not use float, Decimal, Fraction,
math.gcd, pow, solver libraries, random state, mutable caches or IO.

The public frozen, slotted dataclasses are ExactCertificateLimits,
ExactCertificateRequest and ExactCertificateResult. Rational is an exact built-in
tuple of two canonical integer strings. All six limits are mandatory:

| Field | Ceiling |
| --- | ---: |
| max_rows | 10000 |
| max_token_bytes | 2048 |
| max_rational_bits | 4096 |
| max_intermediate_bits | 65536 |
| max_exact_operations | 2000000 |
| max_input_bytes | 16777216 |

Limits are exact positive built-in ints; bool/subclass refuse. Intermediate bits
must be at least rational bits. Conservative growth guards can refuse a call
even when cancellation would have made its mathematical result fit. This is
RESOURCE_LIMIT_EXCEEDED, never proof infeasibility. Bit/token/row/input violations
have their distinct frozen codes. No default limits or hidden tolerance exists.

The function is verify_exact_certificate(request, *, limits=YOUR_LIMITS).
Request fields, in order, are row_ids, z_bits, y_bits, theta, dual, secondary.
All containers must be exact tuples; n>=1, Z width5, theta length6 and all other
lengths n. Each row ID is unique1..128ASCII bytes. Bit tokens are16lowercase hex
digits in big-endian IEEE754 order with finite exponent. Rational numerator
tokens are signed canonical ASCII integers, denominator tokens positive, no
leading zeros/plus/exponent/negative zero, gcd1; zero is only('0','1').

Limits/types/shapes precede bounded lexical/structural accounting and integer
parsing. Supplied theta/dual/secondary numerator then denominator parse in original
order before metered canonical gcd checks. IEEE tokens decode with integer shifts,
masks and rational reduction; both signed zeros are numerically0 while keeping
distinct proof identities. Duplicate IDs are rejected after admitted numeric
encodings. Duplicate/collinear numerical rows remain intact.

Structural input bytes use the frozen contract:128header+144limit slots,
16per tuple including each pair, and8+ASCII length per scalar string.
Every addition checks remaining capacity before increasing the count. This is a
versioned wire bound, not a CPython heap/CPU quota. No arbitrary recursive object
descent, iterator consumption or caller callback exists.

## Primitive inventory and accounting

All proof integers stay in private _N(value,certified_bits); rationals use private
_R(numerator,positive_denominator). _Meter is the centralized arithmetic layer.
Only fixed finite constants and bounded digit/shape/index/counter bookkeeping
are exempt from proof arithmetic charges.

| Primitive path | Charges and prospective guard |
| --- | --- |
| add/sub | Charge before integer operator; max operand bits+1 |
| multiply | Charge before product; sum of operand bits |
| negation | Charge before unary minus; operand bits |
| floor division/modulo | Charge before operator; max operand bits, nonzero divisor |
| shifts | Charged small count comparisons, then charge before shift; left bits+count, right operand bits |
| bitwise AND | Charge before operator; max operand bits |
| eq/lt/le | Charge before each proof numeric comparison |
| every operator result | Additional charge before bit_length; cache/check actual bits |
| decimal/hex parser | Charge each bounded digit-decoding update, then guarded multiply/add; decimal domain uses the caller rational-bit guard |
| gcd | Explicit sign handling, charged equality at every loop test and individually charged Euclidean modulo/result bit query |
| rational operations | Guarded products/sums plus explicit metered reduction/division; no hidden Fraction/gcd |
| output decimal encoding | Metered division/modulo by10 and charged comparisons; no unchecked bigint-to-str path |

Known certified zero shortcuts avoid an operator rather than execute it free.
Guards use cached small bit counts; loop/shape/wire/hash length bookkeeping
cannot introduce caller proof bigints. IEEE shift counts come from fixed
constants or the already bounded decoded exponent and are checked before use.
Signed division/modulo use Python floor semantics; gcd operands/remainders are
nonnegative. Normalized internal denominators are positive.

max_exact_operations is charged before a primitive; no credit means an immediate
safe error, including during parsing/gcd/rendering after earlier checks passed.
Each returned result's exact_operations is the actual counter for that call.
The fixed author fixture with144/233 and35credits specifically stops inside
GCD (after22decimal parsing primitives, denominator/sign checks and individually
metered Euclidean steps), rather than wrapping an unchecked C gcd. This is an
operation-count bound, not an instruction/CPU-seconds theorem. Stored arithmetic
is O(n*6) with bounded bit lengths, no expression tree or subset enumeration.

## Proof and result

A=(1,Z) retains all six free coordinates, alpha exactly1/10, unweighted SUM loss.
Residuals derive the primary objective; no supplied objective or face is trusted.
Seven checks retain this order:

1. DUAL_BOUNDS
2. DUAL_STATIONARITY
3. PRIMARY_DUAL_GAP
4. FACE_FEASIBILITY
5. SECONDARY_MULTIPLIER_SIGN
6. SECONDARY_STATIONARITY
7. COMPLEMENTARY_SLACKNESS

All primary checks are evaluated safely even when one fails. Any primary failure
leaves the four secondary checks NOT_RUN. On primary success each original row
derives its whole-face orientation: d=1/10 gives A*theta<=y; d=-9/10 gives
-A*theta<=-y; an interior d gives equality. Every row is checked, including
zero-multiplier constraints; equality multipliers have unrestricted sign.
Full-six secondary stationarity and inequality complementary products are exact.

Success status EXACT_REPRESENTED_INPUT_CERTIFIED returns the original canonical
six theta pairs, exact primary/dual objective pairs and all checks PASS.
CERTIFICATE_NOT_VERIFIED returns no theta/objective values, only fixed ordered
check outcomes/failure codes and proof identity. Resource/domain errors raise
ExactCertificateError exposing safe code/phase, without input values or chained
exception causes. No certificate result means solver infeasibility.

scope_status is always SOURCE_POPULATION_MASK_TRANSFORM_NOT_ASSESSED, format is
polar.exact-certificate/1. proof_id hashes that version+NUL, bounded canonical
n, ordered IDs, original Z/y bits and flattened supplied rational tokens, each as
ASCII length:token;. Hashing streams bounded tokens; it does not prove source
truth. Limits are excluded from proof identity. No row permutation equivalence,
binary64 forecast, transformed-data correctness or financial acceptance follows.

## Fixed author qualification

The prospectively sealed manifest contains32named invented families/50calls,
including the owner interval b=1 and wrong b=2 complementarity example,
all-six1/6 equality, signed zeros, adjacent finite dyadic, malformed types/bits/
rationals/dimensions, dual/gap/sign failures, immutability, ambient Decimal/random
state, byte/bit/growth bounds and operation exhaustion within gcd. It uses no
solver, random/property generator or candidate-derived optimal coefficients.

The frozen source/harness passed all32families in one50-call author attempt.
No old suite, real inputs, Service/Gym/native engine, fit or financial run was
invoked. The64author/96independent call ceilings and finite task deadlines remain;
independent exact-candidate Code/numerical review and normal merge are separate.
QA System is not applicable to this pure in-memory change.

# HYP008 invented generation feasibility probe

This development probe is not an accepted generator or forecast API. It neither
reads retained inputs nor calls Service, Gym, model fitting/prediction or the
original scientific family. Fixed input literals and expectations are source-bound
in polar.hyp008_generation_probe before any invocation.

One path only: SciPy 1.15.3 linprog(method=highs-ds), six free coefficients,
nonnegative positive/negative residuals, loss weights 0.1/0.9. Options: presolve
true, maxiter1000, time_limit10 seconds, primal/dual feasibility tolerance1e-7.
Floating optimal status and duals are candidates only. Reconstruct each dual via
Fraction(binary64).limit_denominator(1000000); exact bound/stationarity checks
must pass. No other backend, tolerance, random fixture or reconstruction sweep.

The bounded secondary prototype projects the origin onto the primary dual face
using rational Gram solves and one deterministic add/drop working set, at most32
iterations and6 independent active rows. A dependent/cycling/unsupported set is
NUMERICAL_UNVERIFIED, no fallback. This is not a production10000-row algorithm;
only the two <=10-row controls are admitted. Exact arithmetic is bounded to4096
bits in this prototype, with the independently accepted verifier's own finite
input/operation limits applied to every supplied result. All rows enter the final
proof. The candidate is never accepted merely because its floating residual or
the prototype's own algebra is small.

Control1 has ten identical augmented rows (1,1,1,1,1,1), with y=1,3,4,5,6,7,8,9,10,11.
Primary optima have coefficient sum in[1,3]; minimum Euclidean norm is all six
coefficients1/6, exact primary objective27/5. Control2 has augmented rows e0 and
e0+ej for j1..5, y=1,3,4,5,6,7. The unique exact-fit vector is(1,2,3,4,5,6), objective0.
Neither coefficient vector nor any supplied certificate is fed to the LP or
secondary solver; expectations are compared only after accepted verification.

Qualified existing numerical dependency image35bc5a28.../BUILD-LOCK7521df6f from
/private/tmp/polar-hyp007-build-2525-20261108 is selected, no install/download.
Exact new application source composition is required before execution; the old
image alone does not contain these source bytes. The accepted7db config2 launcher
must observe the actual composed image/platform and complete packaged source
before start. Inside that same container the probe validates actualUID10001,
Python3.13.18, SciPy1.15.3/NumPy2.2.6, source origins/hashes and automatic receipt;
it writes generation-preflight.json before its first solver call. The accepted
exact verifier source must remain be0b3a2a...; no source overlay guess is allowed.

Independent source/harness review precedes invocation in this development plan.
After fixtures/config/source/build/review refs are ready, one <=120-second
operation may execute the two declared controls, networknone/read-only input,
private output and exact-owned cleanup. Failed preparation runs no scenario; no
blind retry or changed harness invocation after rejection. Retain every attempt.
SRE owns source assembly, QA independent review/technical qualification, PE the
probe, QuantB consumes observed feasibility or an evidenced precise gap. This is
not a scientific trial, financial acceptance or a reusable-code acceptance claim.

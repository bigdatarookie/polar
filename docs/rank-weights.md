# Pure rank-to-weight API

`polar.rank_weights.map_rank_weights(request)` maps an asserted complete qualified
population and already represented binary64 scores to sparse Decimal targets.
It performs no IO, conversion, eligibility qualification, account sizing, model,
strategy, clock inference or execution. Valid stable tokens do not establish
economic identity. Scientific population/cap values and score conversion remain
caller choices; this API supplies no defaults for them.

All input/output records are frozen dataclasses. Built-in fields are checked by
exact type; subclass/coercion behavior is unsupported. Import `ScoreRow`,
`ScorePanel`, `CallLimits`, `RankWeightRequest` and the mapping function:

```python
from decimal import Decimal
from polar.rank_weights import (
    ScoreRow, ScorePanel, CallLimits, RankWeightRequest, map_rank_weights,
)

# Invented mechanical input, not scientific settings.
request = RankWeightRequest(
    variant="COMPLETE",
    required_methods=("example",),
    complete_population=("A", "B"),
    panels=(ScorePanel("example", (ScoreRow("A", 2.0), ScoreRow("B", 1.0))),),
    unavailable_reasons=(),
    cap=Decimal("0.2"),
    limits=CallLimits(max_population=2, max_methods=1, max_rows=2, max_selected=1),
)
result = map_rank_weights(request)
```

Tokens (instrument/method IDs and nonnull optional formation_ref/definition_ref)
are case-sensitive ASCII `[A-Za-z0-9][A-Za-z0-9._:-]{0,63}`. Population, required
methods, panels and panel rows are strict tuples; duplicates are preserved for
rejection. `ScoreRow(instrument_id, score)` accepts strict float or None. Missing
panels/rows/None and nonfinite floats are unavailable; bool/int/Decimal/string
scores are invalid. No extra IDs/methods, imputation, intersection or dropping.

`COMPLETE` requires population/panels tuples and reasons(). `UNAVAILABLE` requires
population=None, panels=None and1..5 unique upstream reasons from
POPULATION_UNAVAILABLE, ELIGIBILITY_UNAVAILABLE, FEATURE_UNAVAILABLE,
MODEL_UNAVAILABLE, READINESS_UNAVAILABLE. Partial evidence does not belong in this
minimal variant. Cap is strict finite Decimal in(0,1], exponent>=-12, at most40
tuple digits/40characters; no normalization/rounding. All four call limits are
explicit positive strict ints; max_selected additionally<=1000. They bound
per-call representation/work, not scientific eligibility or host resources.

The API docstring freezes validation order. Every failing phase returns all
observed category codes in that phase only, deduplicated/ASCII sorted, with the
first as primary. No malformed caller values or invalid IDs/references are echoed.

| Phase | Check | Failure codes |
| --- | --- | --- |
| A1 | Exact request type | INVALID_REQUEST |
| A2 | Exact limits then all scalar domains | INVALID_LIMITS alone, or INVALID_MAX_POPULATION, INVALID_MAX_METHODS, INVALID_MAX_ROWS, INVALID_MAX_SELECTED |
| A3 | Variant first, then outer shapes | INVALID_VARIANT alone, or INVALID_REQUIRED_METHODS_CONTAINER, INVALID_REASONS_CONTAINER, INVALID_POPULATION_CONTAINER, INVALID_PANELS_CONTAINER, INVALID_VARIANT_FIELDS |
| A4 | Required-method/panel/population lengths before contents | METHOD_LIMIT, PANEL_LIMIT, POPULATION_LIMIT |
| A5 | All admitted panel types/row tuple shapes, before row contents | INVALID_PANEL_TYPE, INVALID_ROWS_CONTAINER |
| A6 | Total supplied row count, including duplicates | ROW_LIMIT |
| B | All admitted semantic structure, before availability | See closed vocabulary below |
| C | Every required method and population member | MISSING_PANEL, MISSING_SCORE, NONFINITE_SCORE, or validated upstream reasons |
| D | Explicit complete empty population and each empty panel | NO_ELIGIBLE_NAMES |
| E | Required selected k exceeds max_selected | SELECTED_LIMIT |
| F | Form all methods atomically | No reasons |

A1/A2/A3/A5/B failures are STRUCTURAL_INVALID. A4/A6 failures are
CALL_DOMAIN_EXCEEDED; unvisited later fields are not claimed valid. A3 wrong
UNAVAILABLE population/panel presence uses INVALID_VARIANT_FIELDS. COMPLETE
wrong tuple containers use their named container codes. In A5 shape failures win
over observed row-count excess. Required methods may have zero length in the
outer envelope but fail structurally in B; an earlier count failure wins.

Closed B vocabulary: EMPTY_REQUIRED_METHODS, INVALID_METHOD_ID,
DUPLICATE_REQUIRED_METHOD, INVALID_POPULATION_ID, DUPLICATE_POPULATION_ID,
INVALID_PANEL_METHOD, UNDECLARED_PANEL, DUPLICATE_PANEL, INVALID_ROW_TYPE,
INVALID_ROW_ID, UNEXPECTED_ROW_ID, DUPLICATE_SCORE_ROW, INVALID_SCORE_TYPE,
INVALID_CAP, INVALID_REFERENCE, INVALID_UPSTREAM_REASON. Repeated valid identities
are duplicates even with identical payloads. All B categories are collected over
admitted inputs; unavailable flags cannot hide invalid cap/references/declarations.

C returns COMMON_FORMATION_UNAVAILABLE for the entire collection, with validated
affected required method IDs sorted ASCII (none for an upstream unavailable
variant). A missing panel records MISSING_PANEL; rows are inspected only in
present panels. Missing formation beats selected overflow. Runtime/process
exceptions are not reclassified as economic unavailable or success.

`RankWeightResult(status, reason_codes, primary_reason, methods, N, k,
unavailable_method_ids, formation_ref, definition_ref)` has six component statuses:
STRUCTURAL_INVALID, CALL_DOMAIN_EXCEEDED, COMMON_FORMATION_UNAVAILABLE,
KNOWN_EMPTY, REPRESENTATION_UNAVAILABLE, FORMED.
Failures have methods=None. Structural/domain/availability failures have N=k=None;
structural/domain failures also omit references. REPRESENTATION_UNAVAILABLE
retains known N/k. All-success methods are ASCII-method-ordered immutable tuples.

KNOWN_EMPTY requires each explicitly supplied empty panel. It returns N=k=0,
NO_ELIGIBLE_NAMES and per-method empty selected_ids/targets, cash weight1 and false
tie flag. It is distinct from unavailable and does not certify liquidation or
cash NAV. For nonempty complete inputs k=(N+4)//5. Each method ranks represented
score descending, then stable-ID ASCII bytes ascending, signed zeros equal.
Exactly k names are selected; no epsilon, tie expansion or truncation.

Let L=10^12 and cap_units be the exact cap in integer units. Each selected weight
has units=min(L//k,cap_units); cash units=L-k*units. All arithmetic uses integers;
Decimal outputs are constructed directly from digit tuples at exponent-12,
independent of ambient precision/rounding/traps. There is no remainder
redistribution or normalization. N11/cap1 gives three weights0.333333333333 and
target cash0.000000000001. `constant_score_tie` means all N scores equal, including
N1 and signed zero; it does not report a generic cutoff tie or constitute EW.

`MethodWeights(method_id, selected_ids, targets, target_cash_weight,
constant_score_tie)` preserves rank order in both ID and `allocation.Target`
tuples. TARGET_CASH_WEIGHT is a desired proportion, distinct from allocator
residual currency cash. Downstream `allocate` still needs held positions and marks
for EXACTLY held UNION selected and validates its own max_names<=1000. Mapper
success for1000 selected names plus one outside holding can fail that union;
never drop a holding/mark, truncate or rerank. Allocator rows are ID sorted and
cannot recover original score rank. No actual holdings/orders/cost/cap/financial
acceptance is implied. Independent exact-candidate Code qualification is separate
from author synthetic checks; no assembled service/API/System delta exists.

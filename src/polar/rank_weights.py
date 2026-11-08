"""Pure rank-to-Decimal-target mechanics; caller qualifications are assertions.

map_rank_weights follows the frozen envelope sequence before semantic work:
A1 exact request; A2 exact limits and all scalar domains; A3 variant first,
then outer tuple/presence shapes; A4 top-level count limits without scanning;
A5 admitted panel/row-tuple shapes (shape errors beat observed row counts);
A6 supplied total row limit. Each failing phase returns only its complete,
ASCII-sorted observed code set. B scans all admitted structural declarations;
C common availability; D known-empty; E selected representation; F formation.
No iteration/coercion of unadmitted containers, IO, model or account state.
"""
from dataclasses import dataclass
from decimal import Decimal
import math
import re

from .allocation import Target

_TOKEN = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,63}', re.ASCII)
_L = 10**12
_UPSTREAM = frozenset({'POPULATION_UNAVAILABLE', 'ELIGIBILITY_UNAVAILABLE',
                      'FEATURE_UNAVAILABLE', 'MODEL_UNAVAILABLE', 'READINESS_UNAVAILABLE'})


@dataclass(frozen=True, slots=True)
class ScoreRow:
    instrument_id: str
    score: float | None


@dataclass(frozen=True, slots=True)
class ScorePanel:
    method_id: str
    rows: tuple[ScoreRow, ...]


@dataclass(frozen=True, slots=True)
class CallLimits:
    max_population: int
    max_methods: int
    max_rows: int
    max_selected: int


@dataclass(frozen=True, slots=True)
class RankWeightRequest:
    variant: str
    required_methods: tuple[str, ...]
    complete_population: tuple[str, ...] | None
    panels: tuple[ScorePanel, ...] | None
    unavailable_reasons: tuple[str, ...]
    cap: Decimal
    limits: CallLimits
    formation_ref: str | None = None
    definition_ref: str | None = None


@dataclass(frozen=True, slots=True)
class MethodWeights:
    method_id: str
    selected_ids: tuple[str, ...]
    targets: tuple[Target, ...]
    target_cash_weight: Decimal
    constant_score_tie: bool


@dataclass(frozen=True, slots=True)
class RankWeightResult:
    status: str
    reason_codes: tuple[str, ...]
    primary_reason: str | None
    methods: tuple[MethodWeights, ...] | None
    N: int | None
    k: int | None
    unavailable_method_ids: tuple[str, ...]
    formation_ref: str | None
    definition_ref: str | None


def _token(value):
    return type(value) is str and _TOKEN.fullmatch(value) is not None


def _result(status, codes=(), *, methods=None, N=None, k=None, unavailable=(), request=None):
    reasons = tuple(sorted(set(codes)))
    return RankWeightResult(status, reasons, reasons[0] if reasons else None,
                            methods, N, k, tuple(sorted(set(unavailable))),
                            request.formation_ref if request is not None else None,
                            request.definition_ref if request is not None else None)


def _units(cap):
    # Inspect tuples before any exponent operation. No Decimal comparisons,
    # multiplication, division, normalization or context-sensitive arithmetic.
    if type(cap) is not Decimal or not cap.is_finite():
        return None
    sign, digits, exponent = cap.as_tuple()
    if sign or not -12 <= exponent <= 0 or len(digits) > 40 or len(str(cap)) > 40:
        return None
    coefficient = 0
    for digit in digits:
        coefficient = coefficient*10+digit
    units = coefficient*10**(exponent+12)
    return units if 0 < units <= _L else None


def _decimal(units):
    return Decimal((0, tuple(int(c) for c in str(units)), -12))


def map_rank_weights(request: RankWeightRequest) -> RankWeightResult:
    """Apply A1..A6/B..F above; never coerce or change caller data.

    A3: COMPLETE requires population/panels tuples and reasons(); UNAVAILABLE
    requires population/panels None and1..5 closed reasons. Wrong presence in
    UNAVAILABLE is INVALID_VARIANT_FIELDS, not an invented empty population.
    Work limits precede nested semantic validation; results never claim an
    unvisited phase valid. Failure methods=None differs from KNOWN_EMPTY.
    """
    # A1
    if type(request) is not RankWeightRequest:
        return _result('STRUCTURAL_INVALID', ('INVALID_REQUEST',))
    # A2
    limits = request.limits
    if type(limits) is not CallLimits:
        return _result('STRUCTURAL_INVALID', ('INVALID_LIMITS',))
    errors = set()
    for field, code in (('max_population', 'INVALID_MAX_POPULATION'),
                        ('max_methods', 'INVALID_MAX_METHODS'),
                        ('max_rows', 'INVALID_MAX_ROWS'),
                        ('max_selected', 'INVALID_MAX_SELECTED')):
        value = getattr(limits, field)
        if type(value) is not int or value < 1 or (field == 'max_selected' and value > 1000):
            errors.add(code)
    if errors:
        return _result('STRUCTURAL_INVALID', errors)
    # A3: variant wins before the other outer shapes.
    if type(request.variant) is not str or request.variant not in ('COMPLETE', 'UNAVAILABLE'):
        return _result('STRUCTURAL_INVALID', ('INVALID_VARIANT',))
    if type(request.required_methods) is not tuple:
        errors.add('INVALID_REQUIRED_METHODS_CONTAINER')
    if type(request.unavailable_reasons) is not tuple:
        errors.add('INVALID_REASONS_CONTAINER')
    elif ((request.variant == 'COMPLETE' and request.unavailable_reasons)
          or (request.variant == 'UNAVAILABLE' and not 1 <= len(request.unavailable_reasons) <= 5)):
        errors.add('INVALID_VARIANT_FIELDS')
    if request.variant == 'COMPLETE':
        if type(request.complete_population) is not tuple:
            errors.add('INVALID_POPULATION_CONTAINER')
        if type(request.panels) is not tuple:
            errors.add('INVALID_PANELS_CONTAINER')
    elif request.complete_population is not None or request.panels is not None:
        errors.add('INVALID_VARIANT_FIELDS')
    if errors:
        return _result('STRUCTURAL_INVALID', errors)
    # A4
    if len(request.required_methods) > limits.max_methods:
        errors.add('METHOD_LIMIT')
    panels = request.panels if request.variant == 'COMPLETE' else ()
    population = request.complete_population if request.variant == 'COMPLETE' else ()
    if len(panels) > limits.max_methods:
        errors.add('PANEL_LIMIT')
    if len(population) > limits.max_population:
        errors.add('POPULATION_LIMIT')
    if errors:
        return _result('CALL_DOMAIN_EXCEEDED', errors)
    # A5/A6
    rows = 0
    for panel in panels:
        if type(panel) is not ScorePanel:
            errors.add('INVALID_PANEL_TYPE')
        elif type(panel.rows) is not tuple:
            errors.add('INVALID_ROWS_CONTAINER')
        else:
            rows += len(panel.rows)
    if errors:
        return _result('STRUCTURAL_INVALID', errors)
    if rows > limits.max_rows:
        return _result('CALL_DOMAIN_EXCEEDED', ('ROW_LIMIT',))
    # B: complete admitted structural scan, before ALL availability decisions.
    cap_units = _units(request.cap)
    if cap_units is None:
        errors.add('INVALID_CAP')
    if any(value is not None and not _token(value)
           for value in (request.formation_ref, request.definition_ref)):
        errors.add('INVALID_REFERENCE')
    methods = set()
    if not request.required_methods:
        errors.add('EMPTY_REQUIRED_METHODS')
    for method in request.required_methods:
        if not _token(method):
            errors.add('INVALID_METHOD_ID')
        elif method in methods:
            errors.add('DUPLICATE_REQUIRED_METHOD')
        else:
            methods.add(method)
    known = set()
    for instrument in population:
        if not _token(instrument):
            errors.add('INVALID_POPULATION_ID')
        elif instrument in known:
            errors.add('DUPLICATE_POPULATION_ID')
        else:
            known.add(instrument)
    reasons = set()
    for reason in request.unavailable_reasons:
        if not _token(reason) or reason not in _UPSTREAM or reason in reasons:
            errors.add('INVALID_UPSTREAM_REASON')
        else:
            reasons.add(reason)
    observed_panels = set()
    score_maps = {}
    for panel in panels:
        if not _token(panel.method_id):
            errors.add('INVALID_PANEL_METHOD')
        else:
            if panel.method_id not in methods:
                errors.add('UNDECLARED_PANEL')
            if panel.method_id in observed_panels:
                errors.add('DUPLICATE_PANEL')
            observed_panels.add(panel.method_id)
        seen = set()
        values = {}
        for row in panel.rows:
            if type(row) is not ScoreRow:
                errors.add('INVALID_ROW_TYPE')
                continue
            if not _token(row.instrument_id):
                errors.add('INVALID_ROW_ID')
            else:
                if row.instrument_id not in known:
                    errors.add('UNEXPECTED_ROW_ID')
                if row.instrument_id in seen:
                    errors.add('DUPLICATE_SCORE_ROW')
                seen.add(row.instrument_id)
                values[row.instrument_id] = row.score
            if row.score is not None and type(row.score) is not float:
                errors.add('INVALID_SCORE_TYPE')
        if _token(panel.method_id):
            score_maps[panel.method_id] = values
    if errors:
        return _result('STRUCTURAL_INVALID', errors)
    # C: ALL required methods are unavailable if any required observation is.
    if request.variant == 'UNAVAILABLE':
        return _result('COMMON_FORMATION_UNAVAILABLE', reasons, request=request)
    unavailable = set()
    for method in sorted(methods):
        if method not in score_maps:
            errors.add('MISSING_PANEL'); unavailable.add(method)
            continue
        values = score_maps[method]
        for instrument in known:
            value = values.get(instrument)
            if value is None:
                errors.add('MISSING_SCORE'); unavailable.add(method)
            elif not math.isfinite(value):
                errors.add('NONFINITE_SCORE'); unavailable.add(method)
    if errors:
        return _result('COMMON_FORMATION_UNAVAILABLE', errors, unavailable=unavailable, request=request)
    # D
    N = len(population)
    if N == 0:
        empty = tuple(MethodWeights(m, (), (), _decimal(_L), False) for m in sorted(methods))
        return _result('KNOWN_EMPTY', ('NO_ELIGIBLE_NAMES',), methods=empty, N=0, k=0, request=request)
    # E
    k = (N+4)//5
    if k > limits.max_selected:
        return _result('REPRESENTATION_UNAVAILABLE', ('SELECTED_LIMIT',), N=N, k=k, request=request)
    # F: integer units; represented floats only determine rank.
    weight_units = min(_L//k, cap_units)
    cash = _decimal(_L-k*weight_units)
    weight = _decimal(weight_units)
    results = []
    for method in sorted(methods):
        scores = score_maps[method]
        ordered = sorted(population, key=lambda name: (-scores[name], name.encode('ascii')))
        selected = tuple(ordered[:k])
        tied = all(scores[name] == scores[ordered[0]] for name in population)
        results.append(MethodWeights(method, selected, tuple(Target(name, weight) for name in selected), cash, tied))
    return _result('FORMED', methods=tuple(results), N=N, k=k, request=request)

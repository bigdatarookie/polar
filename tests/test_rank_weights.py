"""Invented mechanical controls, no financial data/model/strategy invocation."""
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone
from decimal import Decimal, localcontext, ROUND_UP
import itertools
import sys

import pytest

from polar.allocation import AllocationError, Mark, Position, Snapshot, Target, allocate
from polar.rank_weights import (CallLimits, RankWeightRequest, ScorePanel, ScoreRow,
                                map_rank_weights)


def request(n=11, *, cap='1', methods=('learned',), **fields):
    population=tuple(f'A{i:02}' for i in range(n))
    panels=tuple(ScorePanel(m,tuple(ScoreRow(name,float(i)) for i,name in enumerate(population))) for m in methods)
    value=RankWeightRequest('COMPLETE',methods,population,panels,(),Decimal(cap),
                            CallLimits(6000,10,60000,1000),'formation-1','definition-1')
    return replace(value,**fields)


def codes(value, status, *expected):
    result=map_rank_weights(value)
    assert result.status==status
    assert result.reason_codes==tuple(sorted(expected))
    assert result.primary_reason==(min(expected) if expected else None)
    if status not in ('KNOWN_EMPTY','FORMED'):
        assert result.methods is None
    if status in ('STRUCTURAL_INVALID','CALL_DOMAIN_EXCEEDED','COMMON_FORMATION_UNAVAILABLE'):
        assert result.N is result.k is None
    if status in ('STRUCTURAL_INVALID','CALL_DOMAIN_EXCEEDED'):
        assert result.formation_ref is result.definition_ref is None
    return result


def test_binary64_and_exact_thirds_no_redistribution():
    assert sys.float_info.radix==2 and sys.float_info.mant_dig==53
    r=codes(request(),'FORMED')
    assert (r.N,r.k)==(11,3)
    m=r.methods[0]
    assert m.selected_ids==('A10','A09','A08')
    assert m.targets==tuple(Target(x,Decimal('0.333333333333')) for x in m.selected_ids)
    assert m.target_cash_weight==Decimal('0.000000000001')
    assert not m.constant_score_tie and r.unavailable_method_ids==()
    assert r.formation_ref=='formation-1'


def test_cap_and_minimum_unit_are_exact():
    r=map_rank_weights(request(10,cap='0.2')).methods[0]
    assert tuple(x.weight for x in r.targets)==(Decimal('0.2'),Decimal('0.2'))
    assert r.target_cash_weight==Decimal('0.6')
    r=map_rank_weights(request(11,cap='0.000000000001')).methods[0]
    assert {t.weight for t in r.targets}=={Decimal('0.000000000001')}
    assert r.target_cash_weight==Decimal('0.999999999997')


def test_all_equal_signed_zero_and_ascii_ties():
    pop=('z','a','Z','A','0','A:','A-','A.')
    panels=(ScorePanel('m',tuple(ScoreRow(name, -0.0 if i%2 else 0.0) for i,name in enumerate(pop))),)
    r=map_rank_weights(request(complete_population=pop,required_methods=('m',),panels=panels))
    assert r.methods[0].selected_ids==('0','A')
    assert r.methods[0].constant_score_tie
    assert map_rank_weights(request(1)).methods[0].constant_score_tie


def test_cutoff_tie_is_not_constant_score_tie():
    pop=('a','b','c','d','e','f')
    scores=(3.,2.,2.,1.,0.,-1.)
    q=request(complete_population=pop,panels=(ScorePanel('learned',tuple(ScoreRow(n,s) for n,s in zip(pop,scores))),))
    m=map_rank_weights(q).methods[0]
    assert m.selected_ids==('a','b') and not m.constant_score_tie


def test_method_and_input_order_no_mutation():
    q=request(6,methods=('z','a'))
    before=repr(q)
    expected=map_rank_weights(q)
    for perm in itertools.permutations(q.panels):
        p=replace(q,required_methods=tuple(reversed(q.required_methods)),
                  complete_population=tuple(reversed(q.complete_population)),
                  panels=tuple(replace(x,rows=tuple(reversed(x.rows))) for x in perm))
        assert map_rank_weights(p)==expected
    assert tuple(x.method_id for x in expected.methods)==('a','z') and repr(q)==before
    with pytest.raises(FrozenInstanceError): q.cap=Decimal('.1')
    with pytest.raises(FrozenInstanceError): expected.methods[0].targets[0].weight=Decimal('.1')


def test_hostile_decimal_context_does_not_change_results_or_flags():
    q=request(11)
    expected=map_rank_weights(q)
    with localcontext() as ctx:
        ctx.prec=1;ctx.rounding=ROUND_UP;ctx.Emax=0;ctx.Emin=0
        for signal in ctx.traps:ctx.traps[signal]=True
        ctx.clear_flags()
        assert map_rank_weights(q)==expected
        assert not any(ctx.flags.values())


@pytest.mark.parametrize('cap',[None,1,True,1.,'1',Decimal('NaN'),Decimal('sNaN'),Decimal('Infinity'),
    Decimal('-0'),Decimal('0'),Decimal('-1'),Decimal('1.0000000000001'),Decimal('0.0000000000001'),
    Decimal('2'),Decimal('1E+999999'),Decimal('0E+999999')])
def test_cap_strict_and_bounded(cap):
    codes(replace(request(),cap=cap),'STRUCTURAL_INVALID','INVALID_CAP')


@pytest.mark.parametrize('score',[True,1,Decimal('1'),'1',object()])
def test_no_score_conversion(score):
    q=request(1,panels=(ScorePanel('learned',(ScoreRow('A00',score),)),))
    codes(q,'STRUCTURAL_INVALID','INVALID_SCORE_TYPE')


@pytest.mark.parametrize('score',[None,float('nan'),float('inf'),float('-inf')])
def test_missing_nonfinite_atomic_overflow_precedence(score):
    q=request(11,methods=('a','b'),limits=CallLimits(100,10,1000,1))
    q=replace(q,panels=(q.panels[0],ScorePanel('b',tuple(replace(row,score=score) if i==0 else row
                                                      for i,row in enumerate(q.panels[1].rows)))))
    reason='MISSING_SCORE' if score is None else 'NONFINITE_SCORE'
    r=codes(q,'COMMON_FORMATION_UNAVAILABLE',reason)
    assert r.unavailable_method_ids==('b',)


def test_complete_availability_reason_union():
    q=request(2,methods=('z','a','b'),panels=(ScorePanel('a',(ScoreRow('A00',float('nan')),)),
                                         ScorePanel('b',(ScoreRow('A00',None),ScoreRow('A01',1.)))))
    r=codes(q,'COMMON_FORMATION_UNAVAILABLE','MISSING_PANEL','MISSING_SCORE','NONFINITE_SCORE')
    assert r.unavailable_method_ids==('a','b','z')


def test_known_empty_requires_each_explicit_panel():
    r=codes(request(0,methods=('z','a')),'KNOWN_EMPTY','NO_ELIGIBLE_NAMES')
    assert (r.N,r.k)==(0,0)
    assert all(m.selected_ids==m.targets==() and m.target_cash_weight==Decimal(1)
               and m.constant_score_tie is False for m in r.methods)
    codes(request(0,panels=()),'COMMON_FORMATION_UNAVAILABLE','MISSING_PANEL')


def test_unavailable_variant_retains_valid_reasons_not_targets():
    q=request(variant='UNAVAILABLE',complete_population=None,panels=None,
              unavailable_reasons=('MODEL_UNAVAILABLE','FEATURE_UNAVAILABLE'))
    r=codes(q,'COMMON_FORMATION_UNAVAILABLE','FEATURE_UNAVAILABLE','MODEL_UNAVAILABLE')
    assert r.unavailable_method_ids==() and r.definition_ref=='definition-1'
    codes(replace(q,cap=Decimal(0),formation_ref='private/invalid'),
          'STRUCTURAL_INVALID','INVALID_CAP','INVALID_REFERENCE')


@pytest.mark.parametrize('reasons',[('OTHER',),('MODEL_UNAVAILABLE','MODEL_UNAVAILABLE'),(None,)])
def test_upstream_reason_values(reasons):
    q=request(variant='UNAVAILABLE',complete_population=None,panels=None,unavailable_reasons=reasons)
    codes(q,'STRUCTURAL_INVALID','INVALID_UPSTREAM_REASON')


def test_selected_overflow_retains_N_k_without_truncation():
    r=codes(request(11,limits=CallLimits(20,2,50,2)),
            'REPRESENTATION_UNAVAILABLE','SELECTED_LIMIT')
    assert (r.N,r.k)==(11,3) and r.unavailable_method_ids==()


def test_A1_A2_limits_before_field_traversal():
    codes(object(),'STRUCTURAL_INVALID','INVALID_REQUEST')
    codes(request(limits=None,panels=object()),'STRUCTURAL_INVALID','INVALID_LIMITS')
    codes(request(limits=CallLimits(True,0,-1,1001),panels=object()),'STRUCTURAL_INVALID',
          'INVALID_MAX_POPULATION','INVALID_MAX_METHODS','INVALID_MAX_ROWS','INVALID_MAX_SELECTED')


def test_A3_variant_before_shapes_and_all_outer_codes():
    codes(request(variant=1,required_methods=[],panels=[]),'STRUCTURAL_INVALID','INVALID_VARIANT')
    codes(request(required_methods=[],panels=[],complete_population=[],unavailable_reasons=[]),
          'STRUCTURAL_INVALID','INVALID_REQUIRED_METHODS_CONTAINER','INVALID_PANELS_CONTAINER',
          'INVALID_POPULATION_CONTAINER','INVALID_REASONS_CONTAINER')
    codes(request(unavailable_reasons=('MODEL_UNAVAILABLE',)),'STRUCTURAL_INVALID','INVALID_VARIANT_FIELDS')
    codes(request(variant='UNAVAILABLE',unavailable_reasons=()),'STRUCTURAL_INVALID','INVALID_VARIANT_FIELDS')


def test_A4_counts_before_nested_shape_and_semantic_zero_methods():
    q=request(2,required_methods=('a','b'),panels=(None,None),limits=CallLimits(1,1,1,1))
    codes(q,'CALL_DOMAIN_EXCEEDED','METHOD_LIMIT','PANEL_LIMIT','POPULATION_LIMIT')
    codes(request(2,required_methods=(),limits=CallLimits(1,2,10,2)),
          'CALL_DOMAIN_EXCEEDED','POPULATION_LIMIT')


def test_A5_shapes_before_total_row_excess():
    q=request(panels=(None,ScorePanel('m',[]),ScorePanel('learned',(None,)*5)),
              limits=CallLimits(20,5,1,2))
    codes(q,'STRUCTURAL_INVALID','INVALID_PANEL_TYPE','INVALID_ROWS_CONTAINER')


def test_A6_counts_all_duplicate_rows_before_semantics():
    q=request(1,panels=(ScorePanel('learned',(ScoreRow('A00',True),)*2),)*2,
              limits=CallLimits(2,2,3,1))
    codes(q,'CALL_DOMAIN_EXCEEDED','ROW_LIMIT')


def test_B_complete_structural_reasons_order_independent():
    q=request(1,required_methods=('a','a','bad/id'),complete_population=('A','A','bad/id'),
      panels=(ScorePanel('a',(ScoreRow('B',True),ScoreRow('B',1.),ScoreRow('bad/id',2.),None)),
              ScorePanel('a',()),ScorePanel('z',()),ScorePanel('bad/id',())),
      cap=Decimal('NaN'),formation_ref='bad/id')
    expected=('DUPLICATE_REQUIRED_METHOD','INVALID_METHOD_ID','DUPLICATE_POPULATION_ID','INVALID_POPULATION_ID',
              'UNEXPECTED_ROW_ID','DUPLICATE_SCORE_ROW','INVALID_SCORE_TYPE','INVALID_ROW_ID','INVALID_ROW_TYPE',
              'DUPLICATE_PANEL','UNDECLARED_PANEL','INVALID_PANEL_METHOD','INVALID_CAP','INVALID_REFERENCE')
    r=codes(q,'STRUCTURAL_INVALID',*expected)
    assert map_rank_weights(replace(q,panels=tuple(reversed(q.panels)),
                                   required_methods=tuple(reversed(q.required_methods))))==r
    codes(request(required_methods=(),panels=()),'STRUCTURAL_INVALID','EMPTY_REQUIRED_METHODS')


def test_invalid_identity_not_echoed_or_normalized():
    q=request(1,complete_population=('sensitive/value',),panels=(ScorePanel('learned',(ScoreRow('é',1.),)),))
    r=codes(q,'STRUCTURAL_INVALID','INVALID_POPULATION_ID','INVALID_ROW_ID')
    assert 'sensitive' not in repr(r) and 'é' not in repr(r)


def test_direct_allocator_union_and_rank_order_are_separate():
    q=request(6,complete_population=('A','B','C','D','E','F'),
              panels=(ScorePanel('learned',tuple(ScoreRow(n,s) for n,s in zip('ABCDEF',(1.,6.,5.,4.,3.,2.)))),))
    m=map_rank_weights(q).methods[0]
    assert m.selected_ids==('B','C')
    at=datetime(2026,1,1,tzinfo=timezone.utc)
    holdings=(Position('Z',1),)
    marks=tuple(Mark(n,Decimal(10),'USD',at) for n in ('Z','B','C'))
    snapshot=Snapshot(Decimal(100),'USD',at,holdings,m.targets,marks)
    with pytest.raises(AllocationError,match='NAME_LIMIT'):
        allocate(snapshot,max_names=2)
    a=allocate(snapshot,max_names=3)
    assert tuple(row.instrument_id for row in a.rows)==('B','C','Z')
    assert a.rows[-1].target_weight==0 and m.selected_ids==('B','C')
    # Separate domain at the actual maximum: 1000 selected plus one held name.
    big=request(5000,limits=CallLimits(5000,1,5000,1000))
    formed=map_rank_weights(big)
    assert formed.status=='FORMED' and formed.k==1000
    names=tuple(x.instrument_id for x in formed.methods[0].targets)+('outside',)
    snap=Snapshot(Decimal(1),'USD',at,(Position('outside',1),),formed.methods[0].targets,
                  tuple(Mark(n,Decimal(1),'USD',at) for n in names))
    with pytest.raises(AllocationError,match='NAME_LIMIT'):allocate(snap,max_names=1000)


def test_exact_dataclass_and_builtin_subclasses_rejected():
    class Float(float): pass
    class Text(str): pass
    class Tuple(tuple): pass
    class Request(RankWeightRequest): pass
    q=request(1)
    codes(Request(**{field:getattr(q,field) for field in q.__dataclass_fields__}),
          'STRUCTURAL_INVALID','INVALID_REQUEST')
    codes(replace(q,required_methods=Tuple(('learned',))),'STRUCTURAL_INVALID','INVALID_REQUIRED_METHODS_CONTAINER')
    codes(replace(q,complete_population=(Text('A00'),),panels=()),'STRUCTURAL_INVALID','INVALID_POPULATION_ID')
    codes(replace(q,panels=(ScorePanel('learned',(ScoreRow('A00',Float(1)),)),)),
          'STRUCTURAL_INVALID','INVALID_SCORE_TYPE')


def test_adjacent_binary64_scores_are_not_rounded_into_ties():
    import math
    q=request(6,complete_population=tuple('ABCDEF'),
      panels=(ScorePanel('learned',tuple(ScoreRow(n,s) for n,s in zip('ABCDEF',
        (1.,math.nextafter(1.,2.),-sys.float_info.max,0.,-0.,sys.float_info.max)))),))
    m=map_rank_weights(q).methods[0]
    assert m.selected_ids==('F','B')


@pytest.mark.parametrize('cap',[Decimal('sNaN'),Decimal('Infinity'),Decimal('1E+999999'),Decimal('1E-13')])
def test_invalid_cap_under_hostile_context_has_no_decimal_effect(cap):
    q=replace(request(),cap=cap)
    with localcontext() as ctx:
        ctx.prec=1;ctx.Emax=0;ctx.Emin=0
        for signal in ctx.traps:ctx.traps[signal]=True
        ctx.clear_flags()
        codes(q,'STRUCTURAL_INVALID','INVALID_CAP')
        assert not any(ctx.flags.values())


def test_methods_select_independently_over_same_population():
    q=request(6,methods=('a','b'))
    p=q.panels[1]
    q=replace(q,panels=(q.panels[0],replace(p,rows=tuple(replace(r,score=-r.score) for r in p.rows))))
    r=map_rank_weights(q)
    assert tuple(m.selected_ids for m in r.methods)==(('A05','A04'),('A00','A01'))
    assert r.N==6 and r.k==2

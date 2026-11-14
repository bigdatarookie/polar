"""Pure invented ledger algebra, not a native/strategy/retained scenario."""
from dataclasses import replace
from fractions import Fraction as F
import pytest
from polar.signed_account_core import (State, Accrual, SignedAccountError, amount_cents,
    magnitude_target, propose_fill, record_confirmed_fill, top_up, recognize_distribution,
    pay_claim, accrue, settle_accrual, mark)


def short(s=None, ident='short', qty=1, price=F(113,100), **kw):
    return propose_fill(s or State(10000),ident,'S','SELL',qty,price,0,
        located_cap=qty,locate_provenance='INVENTED_LOCATE_SCENARIO',marks={'S':price},**kw)


def exp(s,ident='accrue',base=100,rate=F(1),seconds=86400,component='BORROW',stream='borrow'):
    kind={'BORROW':'MARKED_SHORT_NOTIONAL','DEBIT_INTEREST':'NEGATIVE_FREE_CASH',
          'REBATE':'DECLARED_REBATE_BASE','FREE_CASH_INTEREST':'POSITIVE_FREE_CASH'}[component]
    return accrue(s,ident,component,base,rate,seconds,'INVENTED_RATE',stream_id=stream,base_kind=kind)


def test_odd_cent_initial_restriction_ceiling_and_no_principal_income():
    t=short();s=t.after
    assert t.status=='ADMITTED_PROPOSAL_NOT_EXECUTION'
    assert s.restricted_cents==170 and t.operands['own_collateral_cents']==57
    assert s.free_cents==9943 and mark(s,{'S':F(113,100)})['equity_cents']==10000
    assert mark(s,{'S':F(113,100)})['initial_restriction_excess_cents']==F(1,2)


def test_multiple_fills_use_poststate_not_independent_half_topups():
    a=short().after;b=short(a,'increase').after
    assert b.restricted_cents==339 and b.free_cents==9887
    assert mark(b,{'S':F(113,100)})['equity_cents']==10000


def test_fill_and_mark_can_differ_and_fee_charged_once():
    t=propose_fill(State(1000),'x','S','SELL',1,F(113,100),2,
        located_cap=1,locate_provenance='SCENARIO',marks={'S':F(120,100)})
    assert t.after.restricted_cents==180 and t.operands['own_collateral_cents']==67
    assert mark(t.after,{'S':F(120,100)})['equity_cents']==991


def test_insufficient_one_cent_topup_and_equity_reject_atomic():
    s=State(56);t=short(s)
    assert t.after is s and t.status=='REJECTED_DISCRETIONARY_ADMISSION'
    assert 'NEGATIVE_FREE_CASH' in t.operands['failed_tests']
    assert 'INITIAL_EQUITY_REQUIREMENT' in t.operands['failed_tests']
    assert not s.used_ids


def test_discretionary_long_with_payable_fails_equity_despite_positive_free():
    s=State(1000,(('S',-1),),(('S',150),))
    s=recognize_distribution(s,'div','S',F(10),'2024-01-01','2024-02-01','SOURCE').after
    t=propose_fill(s,'buy','L','BUY',1,F(1),0,marks={'L':F(1),'S':F(1)})
    assert t.after is s and s.free_cents>0
    assert 'INITIAL_EQUITY_REQUIREMENT' in t.operands['failed_tests']


def test_unrelated_short_escrow_cannot_be_hidden_by_aggregate_cash():
    s=State(10000,(('S',-1),),(('S',100),))
    t=propose_fill(s,'buy','L','BUY',1,F(1),0,marks={'L':F(1),'S':F(1)})
    assert t.after is s and 'INITIAL_PER_NAME_RESTRICTION' in t.operands['failed_tests']


def test_partial_and_full_cover_release_only_actual_quantity_per_name():
    s=State(1000,(('A',-3),('B',-1)),(('A',451),('B',150)))
    t=propose_fill(s,'cover','A','BUY',1,F(1),1)
    assert t.operands['released_escrow_cents']==150
    assert dict(t.after.escrow)=={'A':301,'B':150}
    b=propose_fill(t.after,'cover-all','A','BUY',2,F(1),0)
    assert b.operands['released_escrow_cents']==301
    assert dict(b.after.escrow)=={'A':0,'B':150}


def test_unfilled_order_releases_nothing_and_has_no_fee():
    s=short().after;t=propose_fill(s,'zero','S','BUY',0,F(1),0)
    assert t.after.escrow==s.escrow and t.after.free_cents==s.free_cents
    with pytest.raises(SignedAccountError,match='ZERO_FILL_FEE'):
        propose_fill(s,'bad','S','BUY',0,F(1),1)


def test_cover_no_credit_block_and_explicit_hypothetical_debit():
    s=State(0,(('S',-1),),(('S',150),))
    t=propose_fill(s,'cover','S','BUY',1,F(2),0,forced=True)
    assert t.after is s and t.status=='SETTLEMENT_BLOCKED_INSUFFICIENT_FREE_CASH'
    funded=propose_fill(s,'cover','S','BUY',1,F(2),0,forced=True,
        funding_mode='HYPOTHETICAL_MANDATORY_FUNDING',funding_assumption='INVENTED_EMERGENCY')
    assert funded.after.free_cents==-50 and funded.after.restricted_cents==0
    assert funded.operands['funding_shortfall_cents']==50
    with pytest.raises(Exception):
        propose_fill(s,'bad','S','BUY',1,F(2),0,forced=True,funding_mode='HYPOTHETICAL_MANDATORY_FUNDING')


def test_topup_limited_and_nav_neutral():
    s=State(25,(('S',-1),),(('S',75),));before=mark(s,{'S':F(1)})
    t=top_up(s,'topup','S',55)
    assert t.after.free_cents==0 and t.after.restricted_cents==100
    assert t.operands['residual_requirement_cents']==30
    assert mark(t.after,{'S':F(1)})['equity_cents']==before['equity_cents']


def test_exact_initial_maintenance_and_valid_default_literal_identities():
    s=State(25,(('L',1),('S',-1)),(('S',75),))
    r=mark(s,{'L':F(1,2),'S':F(1,2)})
    assert r['equity_cents']==100 and r['maintenance_restriction_cents']==65
    assert r['equity_requirement_cents']==F(55,2)
    r=mark(s,{'L':F(4,5),'S':F(1)})
    assert r['equity_cents']==80 and r['equity_excess_cents']>0 and r['maintenance_restriction_excess_cents']<0
    r=mark(s,{'L':F(35,100),'S':F(2)})
    assert r['equity_cents']==-65 and r['deficit_cents']==65 and r['status']=='DEFAULT'
    assert r['positive_nav_metrics']=='INAPPLICABLE' and s.free_cents==25


@pytest.mark.parametrize('value,expected', [(F(-11,10),-1),(F(11,10),1),(F(-9,10),0)])
def test_signed_magnitude_floor_not_negative_floor(value,expected):
    assert magnitude_target(value,F(1))==expected


@pytest.mark.parametrize('shares,price,expected', [(1,F(1,200),0),(3,F(1,200),2),(-1,F(1,200),0),(-3,F(1,200),-2)])
def test_existing_half_even_signed_cent_primitive(shares,price,expected):
    assert amount_cents(shares,price)==expected


def test_short_payable_survives_cover_and_payment_nav_neutral():
    s=short().after;s=recognize_distribution(s,'ex','S',F(1,10),'2024-01-01','2024-01-02','SOURCE').after
    assert s.payables_cents==10
    s=propose_fill(s,'cover','S','BUY',1,F(113,100),0).after
    assert s.payables_cents==10 and dict(s.positions)['S']==0
    before=mark(s,{})['equity_cents'];t=pay_claim(s,'pay','ex','2024-01-02')
    assert t.after.payables_cents==0 and mark(t.after,{})['equity_cents']==before
    with pytest.raises(SignedAccountError):pay_claim(t.after,'repeat','ex','2024-01-03')


def test_long_receivable_sale_and_payment_nav_neutral():
    s=State(0,(('L',1),));s=recognize_distribution(s,'ex','L',F(1,100),'2024-01-01','2024-01-02','SOURCE').after
    assert s.receivables_cents==1
    s=propose_fill(s,'sell','L','SELL',1,F(1),0).after
    before=mark(s,{})['equity_cents'];s=pay_claim(s,'pay','ex','2024-01-03').after
    assert mark(s,{})['equity_cents']==before and s.receivables_cents==0


def test_payable_insufficient_free_blocked_not_escrow_raid():
    s=State(0,(('S',-1),),(('S',150),));s=recognize_distribution(s,'ex','S',F(1),'2024-01-01','2024-01-02','SOURCE').after
    t=pay_claim(s,'pay','ex','2024-01-02')
    assert t.after is s and t.status=='SETTLEMENT_BLOCKED_INSUFFICIENT_FREE_CASH'
    f=pay_claim(s,'pay','ex','2024-01-02',funding_mode='HYPOTHETICAL_MANDATORY_FUNDING',funding_assumption='ASSUMPTION')
    assert f.after.free_cents==-100 and f.after.restricted_cents==150 and f.after.payables_cents==0
    assert mark(f.after,{'S':F(1)})['equity_cents']==mark(s,{'S':F(1)})['equity_cents']


def test_nominal_claim_residual_payment_date_and_unsupported_currency():
    s=State(1,(('L',1),));t=recognize_distribution(s,'ex','L',F(1,200),'2024-01-01','2024-01-02','SOURCE')
    assert t.after.claims[0].cents==0 and t.operands['residual_cents']==F(-1,2)
    with pytest.raises(SignedAccountError):pay_claim(t.after,'early','ex','2024-01-01')
    with pytest.raises(SignedAccountError):recognize_distribution(s,'bad','L',F(1),'2024-01-01','2024-01-02','SOURCE',currency='EUR')


def test_cumulative_residual_persists_across_settlement():
    s=State(100);a=exp(s,base=219,seconds=86400).after # exact .6 cent
    assert a.payables_cents==1
    paid=settle_accrual(a,'pay','borrow').after
    assert paid.free_cents==99 and paid.accruals[0].exact_cents==F(3,5)
    b=exp(paid,'second',base=219,seconds=86400).after
    assert b.accruals[0].exact_cents==F(6,5)
    assert b.accruals[0].recognized_cents==1 and b.payables_cents==0


@pytest.mark.parametrize('component,base,stream', [('REBATE',100,'rebate'),('FREE_CASH_INTEREST',100,'free')])
def test_positive_income_recognition_and_settlement_once(component,base,stream):
    s=State(100);a=exp(s,base=base,seconds=365*86400,rate=F(1,10),component=component,stream=stream).after
    assert a.receivables_cents==10 and mark(a,{})['equity_cents']==110
    b=settle_accrual(a,'pay',stream).after
    assert b.free_cents==110 and b.receivables_cents==0 and mark(b,{})['equity_cents']==110


def test_calendar_three_day_accrual_and_distinct_component_streams():
    s=State(-100);a=exp(s,base=36500,seconds=3*86400).after
    assert a.payables_cents==300
    b=exp(a,'debit',base=100,seconds=365*86400,rate=F(1,10),component='DEBIT_INTEREST',stream='debit').after
    assert b.payables_cents==310 and len(b.accruals)==2
    blocked=settle_accrual(b,'pay','borrow');assert blocked.after is b
    funded=settle_accrual(b,'pay','borrow',funding_mode='HYPOTHETICAL_MANDATORY_FUNDING',funding_assumption='ASSUME')
    assert funded.after.free_cents==-400 and funded.after.payables_cents==10
    assert mark(funded.after,{})['equity_cents']==mark(b,{})['equity_cents']


def test_stream_binding_rate_sign_and_cash_base_guards():
    s=exp(State(100)).after
    with pytest.raises(SignedAccountError,match='STREAM_BINDING'):
        accrue(s,'change','BORROW',100,F(1),1,'NEW_CONTRACT',stream_id='borrow',base_kind='MARKED_SHORT_NOTIONAL')
    with pytest.raises(SignedAccountError):exp(State(100),rate=F(-1))
    with pytest.raises(SignedAccountError):exp(State(100),base=1,component='FREE_CASH_INTEREST')


def test_proposal_rejection_vs_actual_execution_breach_retention():
    s=State(0)
    p=short(s);assert p.after is s
    t=record_confirmed_fill(s,'actual','S','SELL',1,F(113,100),2,{'S':F(113,100)},execution_provenance='CONFIRMED_INVENTED')
    assert t.status=='CONFIRMED_EXECUTION_BREACH' and dict(t.after.positions)['S']==-1
    assert t.after.free_cents==-2 and t.after.restricted_cents==113
    assert 'EXECUTED_SHORT_LOCATE_UNQUALIFIED' in t.operands['breaches']
    assert 'UNQUALIFIED_EXECUTION_FUNDING' in t.operands['breaches']


def test_confirmed_cover_retains_debit_without_fabricated_funding():
    s=State(0,(('S',-1),),(('S',150),))
    t=record_confirmed_fill(s,'cover','S','BUY',1,F(2),0,{},execution_provenance='CONFIRMED_INVENTED')
    assert t.after.free_cents==-50 and t.after.restricted_cents==0
    assert 'UNQUALIFIED_EXECUTION_FUNDING' in t.operands['breaches']
    assert not t.operands['future_credit_or_fill_authority']


def test_duplicate_ids_and_reversal_reject_without_mutation():
    s=short().after;before=s
    with pytest.raises(SignedAccountError,match='DUPLICATE_ID'):short(s,'short')
    with pytest.raises(SignedAccountError,match='REVERSAL'):propose_fill(s,'cross','S','BUY',2,F(1),0)
    assert s==before


@pytest.mark.parametrize('factory', [lambda:State(True),lambda:State(1,(('S',True),)),
    lambda:State(1,(('S',-1),),(('S',-1),)),lambda:State(1,escrow=(('S',1),)),
    lambda:State(1,positions=(('S',1),('S',1))),lambda:Accrual('BORROW','x','MARKED_SHORT_NOTIONAL','p',F(1),2,0)])
def test_restore_constructor_rejects_malformed(factory):
    with pytest.raises(Exception):factory()

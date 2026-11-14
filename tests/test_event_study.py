"""Invented native producer-shaped graph; no actual market/calendar invocation."""
from dataclasses import replace,asdict
from copy import deepcopy
from fractions import Fraction as F
from datetime import datetime,timezone
import json
import os
import subprocess
import sys
import pytest

from polar.event_study import (StudyBinding,make_sidecar,plain,produce_study,evaluate_study,assess_study,
    cluster_intervals,tail_loss,protection_clause,clause,screen,duration_census,full_cycle_units,QUESTION,PROTOCOL)
from polar.event_native import EventInstruction,key
from polar.scheduled_event_controller import Calendar,CalendarEvent,request_from_event,digest
from polar.event_native_witness import encode
from polar.gym_contract import canonical,sha
from test_event_native import fixture


def iso(t):return datetime.fromtimestamp(t//10**9,timezone.utc).isoformat().replace('+00:00','Z')


def study_inputs():
    p=fixture();p=replace(p,events=p.events[:2])
    baseline=[];conditional=[];members=[]
    for instruction in p.events:
        r=instruction.request;anchor=next(q for q in p.nav_closes if iso(q)[:10]==iso(r.decision_ns)[:10])
        values={'event_id':r.event_id,'cancelled':False,'anchor_ns':anchor,'decision_ns':r.decision_ns,
            'candidate_ns':instruction.q_ns,'expiry_ns':r.expiry_ns,'reentry_decision_ns':r.reentry_decision_ns,
            'reentry_candidate_ns':r.reentry_candidate_ns,'provenance':'INVENTED_CURRENT_SOURCE_CLOCK',
            'reasons':(),'censored':False}
        for status,out in [('NOT_EXECUTABLE',baseline),('CONDITIONALLY_MODELED',conditional)]:
            clock={'schema':'polar.event-clock-projection/1','purpose':'CALENDAR_ONLY','execution_authority':False,
                'event_id':r.event_id,'status':status,'prior_reference_date':iso(anchor)[:10],
                'decision_at':iso(r.decision_ns),'execution_candidate_at':iso(instruction.q_ns),'expiry_at':iso(r.expiry_ns),
                'reentry_decision_at':iso(r.reentry_decision_ns),'reentry_candidate_at':iso(r.reentry_candidate_ns),
                'observed_calendar_K':None,'observed_quote_K':None,'prediction_observation':'NOT_APPLICABLE'}
            out.append(CalendarEvent(**values,clock_status=status,clock_pin=digest(clock),
                clock_json=json.dumps(clock,sort_keys=True,separators=(',',':'))))
        members.append({'event_id':r.event_id,'status':'SCHEDULED','provenance':'INVENTED_CALENDAR_SOURCE',
                        'source_ref':'INVENTED_SOURCE/'+r.event_id})
    cancelled=CalendarEvent('cancelled',True,None,None,None,None,None,None,'CANCELLED',None,None,
                             'INVENTED_CANCELLED_SOURCE',(),False)
    baseline.append(cancelled);conditional.append(cancelled)
    members.append({'event_id':'cancelled','status':'CANCELLED','provenance':'INVENTED_CALENDAR_SOURCE','source_ref':'INVENTED_SOURCE/cancelled'})
    def cal(events):return Calendar(tuple(events),tuple(c['members'] for c in cluster_intervals(events)),())
    assumptions={'source_pins':{'invented_panel':{'sha256':'a'*64,'bytes':123}},
        'source_basis':'SYNTHETIC_VENDOR_ADJUSTED_REFERENCE_UNIT','quantity_unit':'WHOLE_SYNTHETIC_REFERENCE_UNIT_NOT_RAW_SHARE',
        'rights_status':'INVENTED_NO_PROVIDER_DATA','input_status':'INVENTED','observed_calendar_K':None,
        'observed_quote_K':None,'modeled_calendar_K':'CUTOFF_CURRENT_REVISIONS_ASSUMED_KNOWN',
        'modeled_quote_K':'NEXT_CIVIL_UTC_MIDNIGHT','prediction_observation':'NOT_APPLICABLE',
        'model_scope':'RETROSPECTIVE_CURRENT_SCHEDULE_CONDITIONAL_MODEL'}
    side=make_sidecar(members,cal(baseline),cal(conditional),assumptions)
    roles={'schema':'polar.calendar-study-source-roles/1','input_id':p.input_id,'role_id':'INVENTED_ROLES',
        'nav_ns':list(p.nav_closes),'nav_dates':[iso(q)[:10] for q in p.nav_closes],
        'source_rows':plain([{k:v for k,v in asdict(r).items() if k!='price_micro'} for r in p.source])}
    binding=StudyBinding('INVENTED','INVENTED_STUDY',p.input_id,roles['role_id'],PROTOCOL,QUESTION,
        sha(canonical(side)),sha(canonical(roles)),tuple((r['event_id'],r['status']) for r in members),p.nav_closes,tuple(roles['nav_dates']))
    p=replace(p,account_scope=binding.account_scope,protocol_id=PROTOCOL,calendar_id=binding.calendar_sha256,
        events=tuple(EventInstruction(request_from_event(e),e.candidate_ns) for e in conditional if not e.cancelled))
    return p,side,roles,binding


@pytest.fixture(scope='module')
def native_study():return produce_study(*study_inputs())


def test_actual_ten_account_graph_six_clauses_shared_census_and_fullcycle(native_study,record_property):
    s=native_study;e=s['evaluation']
    record_property('invented_calendar_study',json.dumps(encode({'binding':asdict(s['binding']),'evaluation':e,
        'accounts':[{'context':a['context'],'native_account_id':a['native_account_id'],'fills':len(a['fills']),
                     'anchors':len(a['anchors']),'NAV':len(a['nav'])} for a in s['accounts']]}),sort_keys=True))
    assert len(s['accounts'])==10 and len({a['native_account_id'] for a in s['accounts']})==10
    assert e['full_source_census']==3 and e['cancelled_members']==['cancelled'] and e['event_E']==1
    assert all(len(v['clauses'])==6 for v in e['cost_results'].values())
    assert len({tuple(r['id'] for r in d['clusters']) for d in e['account_details'].values()})==1
    for cost,cycles in e['full_cycles'].items():
        assert len(cycles['units'])==1 and cycles['units'][0]['reentry_ns'] is not None
        endpoints={rows[0]['reentry_ns'] for rows in cycles['per_leg'].values()};assert len(endpoints)==1
        assert all(rows[0]['fee_cents']>=0 for rows in cycles['per_leg'].values())
        assert cycles['additional_independent_N'] is False and cycles['replaces_release_window_ES'] is False
    assert e['independent_financial_assessment']=='NOT_ISSUED' and e['native_calls']==e['source_reads']==e['writes']==0


def test_saved_graph_recomputes_without_native_source_or_write_open(native_study,tmp_path):
    from polar.gym_store import GymStore
    from polar.event_study_store import publish_study,verify_stored_study
    import hashlib
    store=GymStore(tmp_path,128*1024**2);ref=publish_study(store,native_study)
    files=list(tmp_path.rglob('*.json'))
    assert len(files)==22  # two graph members + existing two-member objects x10
    before={str(p.relative_to(tmp_path)):(sha(p.read_bytes()),p.stat().st_mtime_ns) for p in tmp_path.rglob('*') if p.is_file()}
    checked=verify_stored_study(tmp_path,ref['id'],native_study['binding'])
    assert checked['evaluation']==native_study['evaluation'] and checked['saved_member_reads']==22
    assert publish_study(store,native_study)==ref
    code=r'''
import sys,json,os,importlib.abc,builtins,io
class NoNative(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname.startswith('nautilus_trader'):raise RuntimeError('NATIVE_IMPORT_FORBIDDEN')
sys.meta_path.insert(0,NoNative())
from polar.event_study_store import verify_stored_study
from polar.event_study import binding_from_plain
old=os.open
def ro(p,flags,*a,**kw):
 if flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_APPEND|os.O_TRUNC):raise RuntimeError('WRITE_OPEN_FORBIDDEN')
 return old(p,flags,*a,**kw)
os.open=ro
def guard(fn):
 def wrapped(p,mode='r',*a,**kw):
  if any(c in mode for c in 'wa+x'):raise RuntimeError('WRITE_OPEN_FORBIDDEN')
  return fn(p,mode,*a,**kw)
 return wrapped
builtins.open=guard(builtins.open);io.open=guard(io.open)
r=verify_stored_study(sys.argv[1],sys.argv[2],binding_from_plain(json.loads(sys.argv[3])))
print(json.dumps({k:v for k,v in r.items() if k not in ('study','evaluation')}))
'''
    r=subprocess.run([sys.executable,'-c',code,str(tmp_path),ref['id'],json.dumps(asdict(native_study['binding']))],
        cwd=tmp_path,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'},capture_output=True,text=True,timeout=30)
    assert r.returncode==0,r.stderr
    out=json.loads(r.stdout);assert out['native_calls']==out['source_reads']==out['writes']==0
    assert before=={str(p.relative_to(tmp_path)):(sha(p.read_bytes()),p.stat().st_mtime_ns) for p in tmp_path.rglob('*') if p.is_file()}


@pytest.mark.parametrize('axis',['calendar','roles','source','cost','leg','generation','account_swap','anchor','fee_doubledebit'])
def test_unrelated_or_corrupted_saved_evidence_invalid_before_screen(native_study,axis):
    s=deepcopy(native_study)
    if axis=='calendar':s['calendar']['source_members'][0]['event_id']='WRONG'
    elif axis=='roles':s['roles']['source_rows'][0]['role']='NAV'
    elif axis in ('source','cost','leg'):
        a=s['accounts'][0];field={'source':'input_id','cost':'cost_id','leg':'leg_id'}[axis]
        a['context']=replace(a['context'],**{field:'WRONG'})
    elif axis=='generation':
        a=s['accounts'][0];a['receipts'][0]=replace(a['receipts'][0],generation=999)
    elif axis=='account_swap':s['accounts'][-1]=deepcopy(s['accounts'][0])
    elif axis=='anchor':
        a=s['accounts'][0];a['anchors'][0]=replace(a['anchors'][0],nav_cents=a['anchors'][0].nav_cents+1)
    else:s['accounts'][0]['nav'][-1]['nav_cents']-=s['accounts'][0]['nav'][-1]['flat_cents']
    out=assess_study(s['accounts'],s['calendar'],s['roles'],s['binding'])
    assert out['status']==out['producer_screen']=='INVALID'


def test_touching_and_transitive_cluster_membership_fixed_without_returns():
    def e(id,a,b):return CalendarEvent(id,False,a,None,None,b,None,None,'UNAVAILABLE',None,None,'INVENTED',(),False)
    groups=cluster_intervals([e('z',1,2),e('b',2,4),e('a',4,7),e('c',8,9)])
    assert [g['id'] for g in groups]==['a+b+z','c'] and groups[0]['anchor_ns']==1 and groups[0]['r2_ns']==7


def test_exact_tail_ties_ceil_zero_losses_and_no_complete_case_selection():
    rows=[{'id':f'{i:02d}','status':'OK','loss':F(1,10) if i<3 else F()} for i in range(21)]
    t=tail_loss(rows,[r['id'] for r in rows]);assert t['k']==2 and t['actual_tail_fraction']==F(2,21)
    assert t['selected_ids']==['00','01'] and t['value']==F(1,10)
    zeros=[{'id':str(i),'status':'OK','loss':F()} for i in range(3)]
    assert tail_loss(zeros,[r['id'] for r in zeros])['k']==1
    assert tail_loss([],[])['status']=='UNAVAILABLE'
    rows[-1]['status']='UNAVAILABLE';assert tail_loss(rows,[r['id'] for r in rows])['value'] is None
    with pytest.raises(Exception):tail_loss(rows[:-1],[r['id'] for r in rows])


def test_zero_opportunity_and_status_precedence_have_no_epsilon():
    assert protection_clause(F(),F())['reason']=='NO_POSITIVE_LOSS_OPPORTUNITY'
    assert protection_clause(F(1,10**20),F())['status']=='NOT_MET'
    assert protection_clause(F(4,5),F(1))['status']=='MET'
    assert screen([clause('known',False),clause('missing',None)],False)=='NOT_SUPPORTED'
    assert screen([clause('known',True),clause('missing',None)],True)=='INDETERMINATE_PROFILE_INCOMPLETE'
    assert screen([clause('all',True)],True)=='CONDITIONAL_POINT_SCREEN_MET'


def test_missing_control_remains_explicit_and_cannot_form_complete_graph(native_study):
    from polar.event_study_store import _check_study
    s=deepcopy(native_study);s['accounts']=[a for a in s['accounts'] if a['leg']!='FULL_BIL']
    e=evaluate_study(s['accounts'],s['calendar'],s['roles'],s['binding'])
    assert not e['profile_complete'] and len(e['missing_controls'])==2
    assert e['producer_screen']=='NOT_SUPPORTED'  # genuine strategy-duration failure in this fixture
    s['evaluation']=e
    with pytest.raises(Exception,match='TEN_ACCOUNT'):_check_study(s,s['binding'])


def test_duration_unknown_is_unavailable_and_known_false_labels_are_corruption(native_study):
    a=deepcopy(native_study['accounts'][0]);a['nav'][2]['duration_evidence_complete']=False
    d=duration_census(a);assert d['status']=='UNAVAILABLE' and d['fraction'] is None
    b=deepcopy(native_study['accounts'][0]);b['nav'][2]['conservative_reduced']=not b['nav'][2]['conservative_reduced']
    with pytest.raises(Exception,match='DURATION_RECEIPT_JOIN'):duration_census(b)


def test_fresh2x_accounts_have_distinct_fees_and_no_second_nav_debit(native_study):
    by={(a['leg'],a['cost_id']):a for a in native_study['accounts']}
    for leg in ('CALENDAR_PROTECTION','FULL_VTI'):
        a=by[leg,'BASE'];b=by[leg,'FRESH_2X']
        assert a['native_account_id']!=b['native_account_id']
        assert b['nav'][-1]['flat_cents']>a['nav'][-1]['flat_cents']
    for case in native_study['evaluation']['cost_results'].values():
        fee=next(c for c in case['clauses'] if c['id']=='EXTRA_FEES')
        assert fee['operands']['extra_NAV_debit'] is False


def test_censored_required_member_not_hidden_inside_complete_cluster(native_study):
    s=deepcopy(native_study);s['calendar']['conditional']['events'][0]['censored']=True
    # Externally selected changed metadata binding is required; old binding
    # already rejects the mutation rather than approving its own new hash.
    assert assess_study(s['accounts'],s['calendar'],s['roles'],s['binding'])['status']=='INVALID'


def test_ambient_decimal_context_does_not_change_saved_evaluation(native_study):
    from decimal import localcontext,ROUND_UP
    with localcontext() as c:
        c.prec=7;c.rounding=ROUND_UP
        e=evaluate_study(native_study['accounts'],native_study['calendar'],native_study['roles'],native_study['binding'])
    assert e==native_study['evaluation'] and e['context']['precision']==50


def test_non_cancelled_missing_member_producer_keeps_whole_census_and_tail_unavailable(record_property):
    p,side,roles,binding=study_inputs()
    for mode in ('baseline','conditional'):
        row=side[mode]['events'][0]
        for k in ('anchor_ns','decision_ns','candidate_ns','expiry_ns','reentry_decision_ns','reentry_candidate_ns',
                  'clock_pin','clock_json'):row[k]=None
        row.update(clock_status='UNAVAILABLE',reasons=['CLOCK_MISSING'],censored=True)
        side[mode]['clusters']=[[side[mode]['events'][1]['event_id']]]
        side[mode]['unclustered']=[row['event_id']]
    binding=replace(binding,calendar_sha256=sha(canonical(side)))
    p=replace(p,calendar_id=binding.calendar_sha256,events=p.events[1:])
    s=produce_study(p,side,roles,binding);e=s['evaluation']
    record_property('invented_missing_member_native_study',json.dumps(encode({'binding':asdict(binding),'evaluation':e,
        'native_account_ids':[a['native_account_id'] for a in s['accounts']]}),sort_keys=True))
    assert len(s['accounts'])==10 and e['full_source_census']==3 and e['event_E'] is None
    assert e['required_member_unavailable']==['e1'] and not e['profile_complete']
    for cost in ('BASE','FRESH_2X'):
        tail=e['account_details']['CALENDAR_PROTECTION/'+cost]['tail_loss']
        assert tail['value'] is None and tail['E'] is None and tail['k'] is None and tail['unclustered_members']==['e1']
        assert next(c for c in e['cost_results'][cost]['clauses'] if c['id']=='PROTECTION')['status']=='UNAVAILABLE'


def test_actual_failed_native_account_never_becomes_complete_study(monkeypatch,record_property):
    from nautilus_trader.backtest.models import FillModel
    from nautilus_trader.model.book import OrderBook
    from nautilus_trader.model.data import BookOrder
    from nautilus_trader.model.objects import Quantity
    from nautilus_trader.model.enums import BookType,OrderSide
    from polar.event_native import _simulate_account,COSTS
    from polar.event_study import StudyUnfinalized
    class Thin(FillModel):
        def get_orderbook_for_fill_simulation(self,instrument,order,best_bid,best_ask):
            book=OrderBook(instrument_id=instrument.id,book_type=BookType.L2_MBP)
            book.add(BookOrder(OrderSide.BUY,best_bid,Quantity.from_int(1),1),0,0)
            book.add(BookOrder(OrderSide.SELL,best_ask,Quantity.from_int(1),2),0,0)
            return book
    def partial(plan,diagnostics=None):
        _simulate_account(plan,'CALENDAR_PROTECTION',*COSTS[0],diagnostics=diagnostics,fill_model=Thin())
        raise AssertionError('Expected actual native partial failure')
    monkeypatch.setattr('polar.event_study.simulate_event_component',partial)
    with pytest.raises(StudyUnfinalized) as caught:produce_study(*study_inputs())
    e=caught.value.evidence
    record_property('invented_native_failed_study',json.dumps(encode({**e,'binding':asdict(e['binding'])}),sort_keys=True))
    assert e['status']=='FAILED_UNFINALIZED' and not e['complete_five_control_graph']
    assert e['native_partial']['actual_native_partial_observation']['positions']['VTI']==1


def test_missing_normal_receipt_cannot_be_fictional_terminal_reentry(native_study):
    a=deepcopy(native_study['accounts'][0]);intents={p.intent_id:p for p in a['issued_intents']}
    a['receipts']=[r for r in a['receipts'] if intents[r.intent_id].cause!='REENTRY']
    cycles=full_cycle_units(a,native_study['evaluation']['clusters'])
    assert all(c['reentry_ns'] is None and c['status']=='CENSORED_TERMINAL_NO_NORMAL_REENTRY' for c in cycles)
    # This helper's missing-end diagnostic is not acceptance of an altered
    # complete tape: the full verifier rejects the omitted real receipt.
    assert assess_study([a],native_study['calendar'],native_study['roles'],native_study['binding'])['status']=='INVALID'


def test_private_evaluation_mutation_or_missing_path_cannot_publish(native_study):
    from polar.event_study_store import _check_study
    s=deepcopy(native_study);s['evaluation']['cost_results']['BASE']['clauses'][0]['status']='MET' if \
        s['evaluation']['cost_results']['BASE']['clauses'][0]['status']!='MET' else 'NOT_MET'
    with pytest.raises(Exception,match='EVALUATION_MISMATCH'):_check_study(s,s['binding'])


def test_actual_zero_delta_normal_reentry_is_genuine_successful_cycle_endpoint(record_property):
    from polar.event_native import _simulate_account,COSTS
    p,side,roles,binding=study_inputs()
    source=tuple(replace(r,price_micro=10**12) if r.role=='NAV' else r for r in p.source)
    p=replace(p,source=source,account_scope='INVENTED_ZERO_DELTA',input_id='INVENTED_ZERO/'+key([asdict(r) for r in source]))
    a=_simulate_account(p,'CALENDAR_PROTECTION',*COSTS[0])
    record_property('invented_zero_delta_normal_cycle',json.dumps(encode(a),sort_keys=True))
    intents={v.intent_id:v for v in a['issued_intents']}
    reentry=next(r for r in a['receipts'] if intents[r.intent_id].cause=='REENTRY')
    assert reentry.outcome=='ZERO_DELTA_NO_ORDER' and reentry.fill_count==0
    cycles=full_cycle_units(a,cluster_intervals([CalendarEvent(**{**r,'reasons':tuple(r['reasons'])}) for r in side['conditional']['events']]))
    assert cycles[0]['reentry_ns']==reentry.q_ns and cycles[0]['status']=='OK'


def test_actual_identity_cannot_be_relabelled_as_generic_invented_namespace(native_study):
    b=native_study['binding']
    with pytest.raises(Exception,match='DOWNGRADE'):replace(b,input_id='retained-input-actual')
    with pytest.raises(Exception,match='ACTUAL_CENSUS'):replace(b,namespace='RETAINED')

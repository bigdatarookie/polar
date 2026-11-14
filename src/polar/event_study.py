"""PRIVATE saved calendar-study algebra. No source/native/Service calls on read.

The producer accepts an already prepared plan; caller authority is separate.
Exact operands and fixed membership precede returns. No predictive/PIT verdict.
"""
from dataclasses import dataclass,asdict,fields
from fractions import Fraction as F
from copy import deepcopy
from datetime import datetime,timezone
import json

from .ci_research import INITIAL_CENTS,require
from .gym_contract import canonical,decode,sha,context
from .event_native import (LEGS,COSTS,SYMBOLS,EventPlan,EventInstruction,key,
                           verify_saved_event_witnesses,simulate_event_component)
from .scheduled_event_controller import (Calendar,CalendarEvent,Context,request_from_event,ns,digest)
from . import scheduled_diagnostics as diagnostics

QUESTION='V043-A-CPI-CALENDAR-PROTECTION-PREP-V1'
PROTOCOL='V043-A-CPI-CALENDAR-PROTECTION-PROTOCOL-01'
DEFINITION='CALENDAR_ONLY_FIVE_PATHS_SIX_CLAUSES_V1'
DEFINITION_PINS={
    'CALENDAR-FIRST-MERGED-METHOD-INPUT-CLAIM-v1.2.json':'1b6c350ee1bd0062cebc66840e38bdf493964064146a38853efc1f5c111bb704',
    'EVENT-CYCLE-END-AND-FIXTURE-CENSUS-CLARIFICATION-v1.md':'52a9a6e1ef36b21a4cab6785a0ef91443874a5829de4566d259a30ba90aae041',
    'CURRENT-SCHEDULE-CENSUS-AND-CANCELLATION-v1.md':'e8c33f795570e8170813ef53698135f6b5ad71a5e9ebfe912b5dd1a7a110a746',
}
MET='MET';NOT_MET='NOT_MET';UNAVAILABLE='UNAVAILABLE'


@dataclass(frozen=True)
class StudyBinding:
    namespace: str
    account_scope: str
    input_id: str
    role_id: str
    protocol_id: str
    question_id: str
    calendar_sha256: str
    roles_sha256: str
    member_statuses: tuple[tuple[str,str], ...]
    nav_ns: tuple[int, ...]
    nav_dates: tuple[str, ...]
    definition: str = DEFINITION

    def __post_init__(self):
        require(self.namespace in ('INVENTED','RETAINED') and self.question_id==QUESTION and self.protocol_id==PROTOCOL and
                self.definition==DEFINITION and all(type(v) is str and v for v in
                    (self.account_scope,self.input_id,self.role_id)),'STUDY_BINDING')
        for h in (self.calendar_sha256,self.roles_sha256):
            require(type(h) is str and len(h)==64 and all(c in '0123456789abcdef' for c in h),'STUDY_HASH')
        require(type(self.nav_ns) is tuple and len(self.nav_ns)>=2 and all(type(v) is int and v>=0 for v in self.nav_ns)
                and all(a<b for a,b in zip(self.nav_ns,self.nav_ns[1:])) and type(self.nav_dates) is tuple and
                self.nav_dates==tuple(datetime.fromtimestamp(t//10**9,timezone.utc).date().isoformat() for t in self.nav_ns),
                'STUDY_NAV_ROLES')
        require(type(self.member_statuses) is tuple and all(type(v) is tuple and len(v)==2 and
                type(v[0]) is str and v[0] and v[1] in ('SCHEDULED','REVISED','CANCELLED','UNAVAILABLE')
                for v in self.member_statuses) and len(dict(self.member_statuses))==len(self.member_statuses),
                'STUDY_EXPECTED_MEMBERS')
        if self.namespace=='INVENTED':
            require(all(v.startswith('INVENTED') for v in (self.account_scope,self.input_id,self.role_id)),
                    'STUDY_NO_RETAINED_TO_FIXTURE_DOWNGRADE')
        else:
            require(not any(v.startswith('INVENTED') for v in (self.account_scope,self.input_id,self.role_id)) and
                    len(self.member_statuses)==33 and sum(s=='CANCELLED' for _,s in self.member_statuses)==1 and
                    sum(s=='REVISED' for _,s in self.member_statuses)==3 and
                    sum(s=='SCHEDULED' for _,s in self.member_statuses)==29,'STUDY_ACTUAL_CENSUS')


def plain(value):
    """Metadata only; tuple/list equivalence is normalized into canonical JSON."""
    return decode(canonical(value))


def binding_from_plain(value):
    require(type(value) is dict and set(value)=={f.name for f in fields(StudyBinding)},'STUDY_BINDING_FIELDS')
    return StudyBinding(**{**value,'member_statuses':tuple(tuple(v) for v in value['member_statuses']),
                           'nav_ns':tuple(value['nav_ns']),'nav_dates':tuple(value['nav_dates'])})


def make_sidecar(source_members,baseline,conditional,assumptions):
    require(type(baseline) is Calendar and type(conditional) is Calendar,'STUDY_CALENDAR_TYPE')
    return plain({'schema':'polar.calendar-study-sidecar/1','source_members':source_members,
                  'baseline':asdict(baseline),'conditional':asdict(conditional),'assumptions':assumptions})


def cluster_intervals(events):
    intervals=sorted((e.anchor_ns,e.expiry_ns,e.event_id) for e in events if not e.cancelled and
                     e.anchor_ns is not None and e.expiry_ns is not None)
    groups=[];members=[];left=right=None
    for a,b,id in intervals:
        if right is not None and a>right:
            groups.append({'id':'+'.join(sorted(members)),'members':tuple(sorted(members)),
                           'anchor_ns':left,'r2_ns':right});members=[];left=None
        members.append(id);left=a if left is None else min(left,a);right=b if len(members)==1 else max(right,b)
    if members:groups.append({'id':'+'.join(sorted(members)),'members':tuple(sorted(members)),'anchor_ns':left,'r2_ns':right})
    return groups


def validate_sidecars(sidecar,roles,binding):
    require(type(binding) is StudyBinding and sha(canonical(sidecar))==binding.calendar_sha256 and
            sha(canonical(roles))==binding.roles_sha256,'STUDY_EXTERNAL_SIDECAR_HASH')
    require(set(sidecar)=={'schema','source_members','baseline','conditional','assumptions'} and
            sidecar['schema']=='polar.calendar-study-sidecar/1','STUDY_SIDECAR_SCHEMA')
    assumptions=sidecar['assumptions']
    require(type(assumptions) is dict and set(assumptions)=={'source_pins','source_basis','quantity_unit','rights_status',
            'input_status','observed_calendar_K','observed_quote_K','modeled_calendar_K','modeled_quote_K',
            'prediction_observation','model_scope'} and
            assumptions['source_basis']=='SYNTHETIC_VENDOR_ADJUSTED_REFERENCE_UNIT' and
            assumptions['quantity_unit']=='WHOLE_SYNTHETIC_REFERENCE_UNIT_NOT_RAW_SHARE' and
            assumptions['observed_calendar_K'] is None and assumptions['observed_quote_K'] is None and
            assumptions['modeled_calendar_K']=='CUTOFF_CURRENT_REVISIONS_ASSUMED_KNOWN' and
            assumptions['modeled_quote_K']=='NEXT_CIVIL_UTC_MIDNIGHT' and
            assumptions['prediction_observation']=='NOT_APPLICABLE' and
            assumptions['model_scope']=='RETROSPECTIVE_CURRENT_SCHEDULE_CONDITIONAL_MODEL' and
            assumptions['input_status'] in ('INVENTED','QUALIFIED_CURRENT_CONDITIONAL_SOURCE','UNAVAILABLE') and
            type(assumptions['rights_status']) is str and assumptions['rights_status'], 'STUDY_EXPLICIT_SOURCE_ASSUMPTIONS')
    require((assumptions['input_status']=='INVENTED')==(binding.namespace=='INVENTED') and
            type(assumptions['source_pins']) is dict and assumptions['source_pins'] and
            all(type(k) is str and type(v) is dict and set(v)=={'sha256','bytes'} and
                type(v['sha256']) is str and len(v['sha256'])==64 and all(c in '0123456789abcdef' for c in v['sha256']) and
                type(v['bytes']) is int and v['bytes']>0 for k,v in assumptions['source_pins'].items()),
            'STUDY_SOURCE_PINS_NAMESPACE')
    source=sidecar['source_members'];expected=dict(binding.member_statuses)
    require(type(source) is list and len(source)==len(expected) and all(type(r) is dict and
            set(r)=={'event_id','status','source_ref','provenance'} and type(r['source_ref']) is str and r['source_ref'] and
            type(r['provenance']) is str and r['provenance'] for r in source) and
            {r['event_id']:r['status'] for r in source}==expected and len({r['event_id'] for r in source})==len(source),
            'STUDY_FULL_EXTERNAL_MEMBERSHIP')
    require(all(r['provenance'].startswith('INVENTED')==(binding.namespace=='INVENTED') for r in source),
            'STUDY_CALENDAR_NAMESPACE')
    calendars={}
    temporal=('anchor_ns','decision_ns','candidate_ns','expiry_ns','reentry_decision_ns','reentry_candidate_ns')
    for name in ('baseline','conditional'):
        c=sidecar[name]
        require(type(c) is dict and set(c)=={f.name for f in fields(Calendar)} and c['execution_authority'] is False,
                'STUDY_CALENDAR_CLOSED_SCHEMA')
        events=[]
        for raw in c['events']:
            require(type(raw) is dict and set(raw)=={f.name for f in fields(CalendarEvent)} and
                    type(raw['cancelled']) is bool and type(raw['censored']) is bool and
                    all(raw[k] is None or type(raw[k]) is int and raw[k]>=0 for k in temporal) and
                    type(raw['reasons']) is list and all(type(r) is str for r in raw['reasons']), 'STUDY_CALENDAR_FIELDS')
            e=CalendarEvent(**{**raw,'reasons':tuple(raw['reasons'])})
            require(e.event_id in expected and e.cancelled==(expected[e.event_id]=='CANCELLED') and
                    type(e.provenance) is str and e.provenance,'STUDY_CANCELLATION_CORRESPONDENCE')
            if e.cancelled:
                require(all(getattr(e,k) is None for k in temporal) and e.clock_json is None and e.clock_pin is None and
                        e.clock_status=='CANCELLED' and not e.censored,'STUDY_CANCELLED_HAS_NO_WINDOW')
            else:
                require(e.anchor_ns is None or e.expiry_ns is None or e.anchor_ns<=e.expiry_ns,'STUDY_CALENDAR_INTERVAL')
                require(e.censored==(e.expiry_ns is None or e.expiry_ns>binding.nav_ns[-1] or
                    e.anchor_ns is None or e.anchor_ns<binding.nav_ns[0]),'STUDY_CALENDAR_CENSOR_CORRESPONDENCE')
                if e.clock_json is not None:
                    require(type(e.clock_json) is str,'STUDY_CLOCK_JSON');r=json.loads(e.clock_json)
                    require(json.dumps(r,sort_keys=True,separators=(',',':'))==e.clock_json and
                            r.get('schema')=='polar.event-clock-projection/1' and
                            digest(r)==e.clock_pin and r.get('event_id')==e.event_id and
                            r.get('purpose')=='CALENDAR_ONLY' and r.get('execution_authority') is False and
                            r.get('status')==e.clock_status and
                            tuple(ns(r.get(k)) for k in ('decision_at','execution_candidate_at','expiry_at',
                                'reentry_decision_at','reentry_candidate_at'))==tuple(getattr(e,k) for k in temporal[1:]),
                            'STUDY_NORMALIZED_CLOCK_PIN_JOIN')
                    prior=[t for t,d in zip(binding.nav_ns,binding.nav_dates) if d==r.get('prior_reference_date')]
                    require((prior[0] if len(prior)==1 else None)==e.anchor_ns,'STUDY_PLANNED_ANCHOR_CLOCK_ROLE_JOIN')
            events.append(e)
        require(len(events)==len(expected) and {e.event_id for e in events}==set(expected),'STUDY_CALENDAR_EVENT_CENSUS')
        groups=cluster_intervals(events);missing=tuple(e.event_id for e in events if not e.cancelled and
                (e.anchor_ns is None or e.expiry_ns is None))
        require(c['clusters']==[list(g['members']) for g in groups] and c['unclustered']==list(missing),
                'STUDY_CANONICAL_CLUSTER_CENSUS')
        calendars[name]=Calendar(tuple(events),tuple(g['members'] for g in groups),missing)
    base={e.event_id:e for e in calendars['baseline'].events}
    require(all(tuple(getattr(e,k) for k in temporal)==tuple(getattr(base[e.event_id],k) for k in temporal)
                for e in calendars['conditional'].events),'STUDY_BASELINE_CONDITIONAL_TEMPORAL_CENSUS')
    require(type(roles) is dict and set(roles)=={'schema','input_id','role_id','nav_ns','nav_dates','source_rows'} and
            roles['schema']=='polar.calendar-study-source-roles/1' and roles['input_id']==binding.input_id and
            roles['role_id']==binding.role_id and roles['nav_ns']==list(binding.nav_ns) and
            roles['nav_dates']==list(binding.nav_dates),'STUDY_SOURCE_ROLE_BINDING')
    rowmap={};by_symbol={s:[] for s in SYMBOLS}
    for r in roles['source_rows']:
        require(type(r) is dict and set(r)=={'symbol','date','close_ns','available_ns','source_id','role'} and
                r['symbol'] in SYMBOLS and type(r['source_id']) is str and r['source_id'] and r['source_id'] not in rowmap and
                type(r['close_ns']) is int and (r['available_ns'] is None or type(r['available_ns']) is int and
                r['available_ns']>=r['close_ns']) and r['role'] in ('NAV','VTI_WARMUP_CANDIDATE','BIL_UNUSED_WARMUP_CONTEXT'),
                'STUDY_SOURCE_ROLE_ROWS')
        require(r['date']==datetime.fromtimestamp(r['close_ns']//10**9,timezone.utc).date().isoformat() and
                (r['role']!='VTI_WARMUP_CANDIDATE' or r['symbol']=='VTI') and
                (r['role']!='BIL_UNUSED_WARMUP_CONTEXT' or r['symbol']=='BIL'), 'STUDY_SOURCE_ROLE_DATE')
        rowmap[r['source_id']]=r;by_symbol[r['symbol']].append(r)
        require(r['source_id'].startswith('INVENTED')==(binding.namespace=='INVENTED'),'STUDY_SOURCE_ROW_NAMESPACE')
    for s,rows in by_symbol.items():
        require(all(a['close_ns']<b['close_ns'] for a,b in zip(rows,rows[1:])) and
                tuple(r['close_ns'] for r in rows if r['role']=='NAV')==binding.nav_ns,'STUDY_RECTANGULAR_NAV_ROLES')
    return calendars,groups,rowmap,by_symbol


def tail_loss(rows,expected_ids):
    require(len(set(expected_ids))==len(expected_ids) and len(rows)==len(expected_ids) and
            {r['id'] for r in rows}==set(expected_ids),'STUDY_TAIL_COMPLETE_CENSUS')
    n=len(expected_ids);k=(n+19)//20
    if not n:return {'status':UNAVAILABLE,'reason':'NO_EVENT_UNITS','E':0,'k':0,'value':None}
    if any(r['status']!='OK' for r in rows):
        return {'status':UNAVAILABLE,'reason':'REQUIRED_EVENT_UNIT_UNAVAILABLE','E':n,'k':k,'value':None,
                'missing_ids':[r['id'] for r in rows if r['status']!='OK']}
    ordered=sorted(rows,key=lambda r:(-r['loss'],r['id']))
    return {'status':'OK','reason':None,'E':n,'k':k,'actual_tail_fraction':F(k,n),
            'value':sum((r['loss'] for r in ordered[:k]),F())/k,
            'selected_ids':[r['id'] for r in ordered[:k]],'claim':'DEPENDENT_FINITE_EMPIRICAL_EVENT_UPPER_TAIL_LOSS_MEAN'}


def protection_clause(strategy,baseline):
    if strategy is None or baseline is None:return clause('PROTECTION',None,reason='REQUIRED_EVENT_LOSS_UNAVAILABLE')
    if baseline==0 and strategy==0:return clause('PROTECTION',None,reason='NO_POSITIVE_LOSS_OPPORTUNITY',
                                               strategy_loss=strategy,baseline_loss=baseline,efficacy='NOT_ASSESSABLE')
    return clause('PROTECTION',5*strategy<=4*baseline,strategy_loss=strategy,baseline_loss=baseline,
                  efficacy='NOT_ASSESSABLE' if baseline==0 else 'FINITE_POINT_ONLY')


def clause(id,passed,reason=None,**operands):
    return {'id':id,'status':UNAVAILABLE if passed is None else MET if passed else NOT_MET,
            'reason':reason,'operands':operands}


def screen(clauses,profile_complete):
    statuses=[c['status'] for c in clauses]
    if NOT_MET in statuses:return 'NOT_SUPPORTED'
    if UNAVAILABLE in statuses or not profile_complete:return 'INDETERMINATE_PROFILE_INCOMPLETE'
    return 'CONDITIONAL_POINT_SCREEN_MET'


def drawdown_exact(nav):
    peak=nav[0]['nav_cents'];value=F()
    for r in nav:
        peak=max(peak,r['nav_cents']);value=max(value,1-F(r['nav_cents'],peak))
    return value


def duration_census(account):
    receipts={r.q_ns:r for r in account['receipts']};intents={i.intent_id:i for i in account['issued_intents']}
    committed=None;conservative=False;complete=True;rows=[]
    for index,r in enumerate(account['nav']):
        receipt=receipts.get(r['nominal_ns'])
        if receipt is not None:
            p=intents[receipt.intent_id];success=receipt.outcome in ('FILLED','ZERO_DELTA_NO_ORDER')
            if receipt.outcome in ('UNKNOWN','INVALID'):conservative=None;complete=False
            elif success:conservative=p.destination=='REDUCED';committed=p.destination
            elif p.destination=='REDUCED' or committed=='REDUCED' or conservative:conservative=True
        known=(r.get('duration_evidence_complete') is True and type(r.get('conservative_reduced')) is bool)
        if known:
            require((r['committed'],r['conservative_reduced'])==(committed,conservative),'STUDY_DURATION_RECEIPT_JOIN')
        else:complete=False
        if index:rows.append({'q_ns':r['nominal_ns'],'counted':conservative if known else None,
                              'committed':committed,'receipt':None if receipt is None else receipt.intent_id})
    n=len(rows);count=sum(r['counted'] is True for r in rows)
    return {'status':'OK' if complete and n else UNAVAILABLE,'reason':None if complete and n else 'DURATION_HISTORY_UNAVAILABLE',
            'reduced_count':count,'postinitial_count':n,'fraction':F(count,n) if complete and n else None,
            'scope':'CATEGORICAL_COMMITTED_OR_ATTEMPTED_TARGET_NOT_ACTUAL_EXPOSURE','rows':rows}


def interval(account,unit):
    anchors={a.q_ns:a for a in account['anchors']};nav={r['nominal_ns']:r for r in account['nav']}
    a=anchors.get(unit['anchor_ns']);end=nav.get(unit['r2_ns'])
    if a is None or end is None:return {'id':unit['id'],'status':UNAVAILABLE,'reason':'MANDATORY_ANCHOR_OR_R2_CENSORED',
                                       'members':unit['members'],'return':None,'loss':None}
    require(a.nav_cents>0 and end['nav_cents']>0,'STUDY_INTERVAL_POSITIVE_DENOMINATOR')
    R=F(end['nav_cents'],a.nav_cents)-1
    return {'id':unit['id'],'status':'OK','reason':None,'members':unit['members'],'anchor_ns':a.q_ns,'r2_ns':unit['r2_ns'],
            'anchor_id':a.anchor_id,'pretrade_nav_cents':a.nav_cents,'end_nav_cents':end['nav_cents'],'return':R,'loss':max(F(),-R)}


def diagnostics_tape(account):
    fills=[]
    for order in account['orders']:
        for fill in order['fills']:
            q=F(fill['quantity']);p=F(fill['price'])*10**6
            require(q.denominator==p.denominator==1,'STUDY_FILL_PRECISION')
            fills.append({'at_ns':fill['at_ns'],'q':q.numerator,'exact_notional_micro':q.numerator*p.numerator,
                          'settled_cents':order['actual_settled_cents']})
    return {'id':account['leg'],'nav':account['nav'],'fills':fills}


def drift_diagnostic(account,duration):
    committed={r['q_ns']:r['committed'] for r in duration['rows']};out=[]
    weights={'NORMAL':{'VTI':F(1),'BIL':F()},'REDUCED':{'VTI':F(1,2),'BIL':F(1,2)},
             'BIL':{'VTI':F(),'BIL':F(1)},'EXIT':{'VTI':F(),'BIL':F()}}
    for row in account['nav'][1:]:
        target=weights.get(committed[row['nominal_ns']]);actual={s:F(v,row['nav_cents']) for s,v in row['position_cents'].items()}
        out.append({'q_ns':row['nominal_ns'],'reported_desired':row['desired'],'committed_from_receipts':committed[row['nominal_ns']],
                    'actual_asset_fractions':actual,'actual_cash_fraction':F(row['cash_cents'],row['nav_cents']),
                    'committed_target_fractions':target,'asset_drift':None if target is None else {s:actual[s]-target[s] for s in SYMBOLS}})
    return {'status':'DESCRIPTIVE','rows':out,'claim':'PRICE_WEIGHTED_DRIFT_NOT_TARGET_DURATION_OR_GUARANTEED_HEDGE'}


def full_cycle_units(strategy,clusters):
    intents={p.intent_id:p for p in strategy['issued_intents']}
    successes=sorted((r for r in strategy['receipts'] if r.outcome in ('FILLED','ZERO_DELTA_NO_ORDER') and
                      intents[r.intent_id].destination=='NORMAL' and intents[r.intent_id].cause=='REENTRY' and
                      any(d.get('pending_id')==r.intent_id and d.get('reason')=='QUEUED_REENTRY_LATCH_UNCHANGED' and
                          d['decision_ns']==intents[r.intent_id].decision_ns for d in strategy['decisions'])),key=lambda r:r.q_ns)
    result=[]
    for c in clusters:
        end=next((r for r in successes if r.q_ns>=c['r2_ns']),None)
        result.append({**c,'reentry_ns':None if end is None else end.q_ns,
                       'reentry_intent':None if end is None else end.intent_id,
                       'status':'OK' if end else 'CENSORED_TERMINAL_NO_NORMAL_REENTRY'})
    return result


def cycle_diagnostic(account,cycle,calendar):
    if cycle['reentry_ns'] is None:return {**cycle,'net_return':None,'reason':cycle['status']}
    unit={**cycle,'r2_ns':cycle['reentry_ns']};r=interval(account,unit)
    if r['status']!='OK':return {**cycle,'status':UNAVAILABLE,'net_return':None,'reason':r['reason']}
    a=next(a for a in account['anchors'] if a.q_ns==cycle['anchor_ns'])
    end=next(n for n in account['nav'] if n['nominal_ns']==cycle['reentry_ns'])
    start={'date':datetime.fromtimestamp(a.q_ns//10**9,timezone.utc).date().isoformat(),'nominal_ns':a.q_ns,
        'sample_ns':a.mark_ns,'nav_cents':a.nav_cents,'cash_cents':a.cash_cents,
        'positions':{v.symbol:v.quantity for v in a.positions},'position_cents':{v.symbol:v.rounded_value_cents for v in a.positions},
        'flat_cents':a.cumulative_flat_cents,'bps_cents':a.cumulative_bps_cents}
    planned=[e.reentry_candidate_ns for e in calendar.events if e.event_id in cycle['members'] and e.reentry_candidate_ns is not None]
    samples=[n for n in account['nav'] if cycle['anchor_ns']<=n['nominal_ns']<=cycle['reentry_ns']]
    return {**cycle,'net_return':r['return'],'loss':r['loss'],'pretrade_nav_cents':a.nav_cents,'end_nav_cents':end['nav_cents'],
            'fee_cents':end['flat_cents']+end['bps_cents']-a.cumulative_flat_cents-a.cumulative_bps_cents,
            'costs':diagnostics._costs(diagnostics_tape(account),start,end),
            'actual_close_exposure':diagnostics._exposure([start,*samples]),
            'exposure_census':'POST_ROUTING_CLOSES_INCLUSIVE_CYCLE_START_AND_END',
            'reentry_delay_ns':cycle['reentry_ns']-max(planned) if planned else None,
            'causal_attribution':'NOT_IDENTIFIED_FROM_DAILY_REFERENCE_MARKS'}


def _validate_account(account,binding,calendars,roles,rowmap,by_symbol):
    verify_saved_event_witnesses(account)
    c=account['context'];require(c.leg_id in LEGS and c.cost_id in dict(COSTS) and
        account['leg']==c.leg_id and account['cost_id']==c.cost_id and account['cost_profile']==dict(COSTS)[c.cost_id] and
        c.input_id==binding.input_id and c.calendar_id==binding.calendar_sha256 and c.protocol_id==binding.protocol_id and
        c.account_id==key([binding.account_scope,c.leg_id,c.cost_id,c.input_id,c.calendar_id,c.protocol_id]),'STUDY_ACCOUNT_EXTERNAL_IDENTITY')
    require(account['initial_cash_cents']==INITIAL_CENTS and account['nav'][0]['nav_cents']==INITIAL_CENTS and
            tuple(account['nav_role_grid'])==binding.nav_ns and tuple(account['nav_role_dates'])==binding.nav_dates,
            'STUDY_ACCOUNT_NAV_ROLE_JOIN')
    eligible=[]
    for e in calendars['conditional'].events:
        if not e.cancelled and e.clock_status in ('OBSERVED_METADATA_ELIGIBLE','CONDITIONALLY_MODELED'):
            request=request_from_event(e);eligible.append((e,request))
    expected=[{'event_id':e.event_id,'candidate_q':e.candidate_ns,'expiry_ns':e.expiry_ns,
               'protection_censored':e.candidate_ns>binding.nav_ns[-1],
               'reentry_censored':e.reentry_candidate_ns>binding.nav_ns[-1]} for e,_ in eligible]
    require(account['event_census']==expected,'STUDY_EFFECTIVE_REQUEST_CENSUS')
    if c.leg_id in ('CALENDAR_PROTECTION','SMA200'):
        for p in account['issued_intents']:
            require(p.intent_id==digest([vars(c),p.generation,p.destination,p.decision_ns,p.q_ns,p.cause,p.event_ids]),
                    'STUDY_CAUSAL_INTENT_IDENTITY')
    for a in account['anchors']:
        for p in a.positions:
            row=rowmap.get(p.source_id)
            require(row is not None and row['symbol']==p.symbol and row['role']=='NAV' and row['close_ns']==a.q_ns,
                    'STUDY_ANCHOR_SOURCE_ROLE_JOIN')
    for w in account['sizing'].values():
        for s,row in w['source_rows'].items():
            selected=[r for r in by_symbol[s] if r['close_ns']<w['decision_ns'] and r['available_ns'] is not None and
                      r['available_ns']<=w['decision_ns']]
            require(selected and {k:v for k,v in row.items() if k!='price_micro'}==selected[-1],
                    'STUDY_SIZING_SOURCE_ROLE_JOIN')
    for signal in account['sma']:
        selected=[r for r in by_symbol['VTI'] if r['close_ns']<signal['decision_ns'] and r['available_ns'] is not None and
                  r['available_ns']<=signal['decision_ns']]
        require(signal['eligible_count']==len(selected),'STUDY_SMA_COMPLETE_METADATA_PREFIX')
        if signal['category']!='UNAVAILABLE':
            require(tuple(r['source_id'] for r in selected[-200:])==tuple(signal['source_ids']), 'STUDY_SMA_SOURCE_ROLE_JOIN')


def evaluate_study(accounts,sidecar,roles,binding):
    """Pure saved consumer. Missing context controls remain missing, not dummy."""
    calendars,clusters,rowmap,by_symbol=validate_sidecars(sidecar,roles,binding)
    require(type(accounts) in (tuple,list),'STUDY_ACCOUNT_SET');by_pair={}
    for account in accounts:
        _validate_account(account,binding,calendars,roles,rowmap,by_symbol)
        pair=(account['leg'],account['cost_id']);require(pair not in by_pair,'STUDY_DUPLICATE_ACCOUNT')
        by_pair[pair]=account
    missing=[(leg,cost) for cost,_ in COSTS for leg in LEGS if (leg,cost) not in by_pair]
    missing_clock=[e.event_id for e in calendars['conditional'].events if not e.cancelled and
                   (e.clock_status not in ('OBSERVED_METADATA_ELIGIBLE','CONDITIONALLY_MODELED') or e.censored)]
    # A member with unknown interval might overlap any known unit: do not invent
    # a singleton cluster or an E/k while its actual cluster membership is unknown.
    unclustered=list(calendars['conditional'].unclustered)
    all_units=clusters
    ids=[c['id'] for c in all_units];details={};tails={};durations={}
    for pair,a in by_pair.items():
        code=pair[0]+'/'+pair[1]
        units=[interval(a,c) for c in all_units]
        # An unavailable/censored member cannot hide inside an otherwise valid
        # overlapping cluster and inherit its neighbour's successful anchor.
        for r,c in zip(units,all_units):
            if any(id in missing_clock for id in c['members']):r.update(status=UNAVAILABLE,reason='REQUIRED_MEMBER_CLOCK_OR_CENSOR',loss=None,**{'return':None})
        tails[pair]=(tail_loss(units,ids) if not unclustered else
                     {'status':UNAVAILABLE,'reason':'UNRESOLVED_CLUSTER_CENSUS','E':None,'k':None,'value':None,
                      'known_cluster_count':len(clusters),'unclustered_members':unclustered})
        durations[pair]=duration_census(a)
        tape=diagnostics_tape(a)
        details[code]={'context':a['context'],'clusters':units,'tail_loss':tails[pair],
            'individual_dependent_release_windows':[interval(a,{'id':e.event_id,'members':(e.event_id,),
                'anchor_ns':e.anchor_ns,'r2_ns':e.expiry_ns}) if e.event_id not in missing_clock else
                {'id':e.event_id,'status':UNAVAILABLE,'reason':'REQUIRED_MEMBER_CLOCK_OR_CENSOR','return':None,'loss':None}
                for e in calendars['conditional'].events if not e.cancelled],
            'duration':durations[pair],'statistics':diagnostics._statistics(a['nav']),
            'saved_diagnostics':diagnostics.diagnose(tape,[{'date':r['date']} for r in by_symbol['VTI']]),
            'costs':diagnostics._costs(tape,a['nav'][0],a['nav'][-1]),
            'drift':drift_diagnostic(a,durations[pair]),'SMA_complete':a['sma_control_complete']}
    numerical_missing=[code+'/'+id for code,report in details.items() for id,v in report['statistics'].items()
                       if type(v) is dict and v.get('status')=='UNAVAILABLE' and str(v.get('reason','')).startswith('NUMERICAL')]
    incomplete=bool(missing or missing_clock or numerical_missing or sidecar['assumptions']['input_status']=='UNAVAILABLE' or
                    any(not a['sma_control_complete'] for a in by_pair.values()))
    cost_results={};all_clauses=[];cycle_outputs={}
    for cost,_ in COSTS:
        s=by_pair.get(('CALENDAR_PROTECTION',cost));b=by_pair.get(('FULL_VTI',cost))
        if s is None or b is None:
            clauses=[clause(id,None,reason='REQUIRED_PRIMARY_ACCOUNT_MISSING') for id in
                     ('WEALTH','GROWTH','PROTECTION','DRAWDOWN','EXTRA_FEES','REDUCED_STATE_DURATION')]
        else:
            st=s['nav'][-1]['nav_cents'];bt=b['nav'][-1]['nav_cents']
            elapsed=F(binding.nav_ns[-1]-binding.nav_ns[0],10**9)
            extra=s['nav'][-1]['flat_cents']+s['nav'][-1]['bps_cents']-b['nav'][-1]['flat_cents']-b['nav'][-1]['bps_cents']
            allowance=F(INITIAL_CENTS,200)*elapsed/31557600
            duration=durations['CALENDAR_PROTECTION',cost]
            clauses=[clause('WEALTH',20*st>=19*bt,strategy_terminal_cents=st,baseline_terminal_cents=bt),
                clause('GROWTH',st>INITIAL_CENTS,terminal_cents=st,initial_cents=INITIAL_CENTS),
                protection_clause(tails['CALENDAR_PROTECTION',cost]['value'],tails['FULL_VTI',cost]['value']),
                clause('DRAWDOWN',drawdown_exact(s['nav'])<=drawdown_exact(b['nav']),strategy=drawdown_exact(s['nav']),baseline=drawdown_exact(b['nav'])),
                clause('EXTRA_FEES',extra<=allowance,charged_extra_cents=extra,allowance_cents=allowance,extra_NAV_debit=False),
                clause('REDUCED_STATE_DURATION',None if duration['status']!='OK' else 4*duration['reduced_count']<=duration['postinitial_count'],
                       reason=duration['reason'],reduced=duration['reduced_count'],postinitial=duration['postinitial_count'])]
            cycles=full_cycle_units(s,clusters)
            overlaps=[(a['id'],b['id']) for i,a in enumerate(cycles) for b in cycles[i+1:] if a['reentry_ns'] is not None and
                      b['reentry_ns'] is not None and max(a['anchor_ns'],b['anchor_ns'])<=min(a['reentry_ns'],b['reentry_ns'])]
            per_leg={leg:[cycle_diagnostic(by_pair[leg,cost],c,calendars['conditional']) for c in cycles]
                     for leg in LEGS if (leg,cost) in by_pair}
            if 'FULL_VTI' in per_leg:
                primary={v['id']:v for v in per_leg['FULL_VTI']}
                for leg,rows in per_leg.items():
                    for r in rows:
                        p=primary[r['id']];r['net_return_minus_fullVTI']=(r.get('net_return')-p.get('net_return') if
                            r.get('net_return') is not None and p.get('net_return') is not None else None)
            cycle_outputs[cost]={'units':cycles,'per_leg':per_leg,'overlap_pairs':overlaps,'additional_independent_N':False,
                                 'replaces_release_window_ES':False}
        benign=[]
        if s is not None and b is not None:
            sr={r['id']:r for r in details['CALENDAR_PROTECTION/'+cost]['clusters']}
            for r in details['FULL_VTI/'+cost]['clusters']:
                if r['status']=='OK' and sr[r['id']]['status']=='OK' and r['return']>=0:
                    benign.append({'id':r['id'],'fullVTI_net_return':r['return'],
                                   'strategy_minus_fullVTI_net_return':sr[r['id']]['return']-r['return']})
        cost_results[cost]={'clauses':clauses,'benign_endpoint_diagnostic':{'count':len(benign),'cluster_E':len(all_units),
             'units':benign,'prediction_false_alarm':'NOT_APPLICABLE','causal_interpretation':False,
             'census_complete':not unclustered}}
        all_clauses.extend(clauses)
    cfg=context()
    return {'schema':'polar.private-calendar-study-evaluation/1','definition':DEFINITION,'definition_pins':dict(DEFINITION_PINS),
        'producer_screen':screen(all_clauses,not incomplete),'profile_complete':not incomplete,
        'missing_controls':missing,'required_member_unavailable':missing_clock,'numerical_report_unavailable':numerical_missing,
        'cost_results':cost_results,
        'clusters':all_units,'event_E':None if unclustered else len(all_units),'unclustered_source_members':unclustered,
        'cluster_census_status':'UNAVAILABLE' if unclustered else 'COMPLETE',
        'account_details':details,'full_cycles':cycle_outputs,
        'full_source_census':len(binding.member_statuses),'cancelled_members':[id for id,s in binding.member_statuses if s=='CANCELLED'],
        'independent_financial_assessment':'NOT_ISSUED','adoption':'INSUFFICIENT_EVIDENCE','prediction_branch':'UNQUALIFIED_NOT_RUN',
        'context':{'precision':cfg.prec,'rounding':str(cfg.rounding),'Emin':cfg.Emin,'Emax':cfg.Emax,
                   'traps':{k.__name__:v for k,v in cfg.traps.items()},'ambient_context_used':False},
        'limitations':['RETROSPECTIVE_CURRENT_SCHEDULE_CONDITIONAL_MODEL_NOT_PIT','CLUSTER_UNITS_DEPENDENT_NOT_POPULATION_ES',
                      'NO_CAUSAL_DAILY_PRICE_ATTRIBUTION','SAVED_INTERNAL_CONSISTENCY_NOT_SOURCE_NATIVE_AUTHENTICATION'],
        'execution_authority':False,'source_reads':0,'native_calls':0,'Service_calls':0,'writes':0}


def assess_study(accounts,sidecar,roles,binding):
    """Typed structural disposition; invalid input never reaches a point screen."""
    from .gym_contract import GymError
    try:return {'status':'VALID_SAVED_GRAPH','evaluation':evaluate_study(accounts,sidecar,roles,binding)}
    except (ValueError,KeyError,TypeError,GymError) as exc:
        return {'status':'INVALID','producer_screen':'INVALID','reason':str(exc),'error_type':type(exc).__name__,
                'financial_assessment':'NOT_ISSUED','execution_authority':False}


class StudyUnfinalized(ValueError):
    def __init__(self,reason,evidence):
        super().__init__(reason);self.evidence=evidence


def produce_study(plan,sidecar,roles,binding,diagnostics_callback=None):
    """Explicit producer invocation only, not Service/admission or authority."""
    calendars,_,_,_=validate_sidecars(sidecar,roles,binding)
    require(type(plan) is EventPlan and (plan.account_scope,plan.input_id,plan.calendar_id,plan.protocol_id)==
            (binding.account_scope,binding.input_id,binding.calendar_sha256,binding.protocol_id) and
            plan.nav_closes==binding.nav_ns,'STUDY_PRODUCER_PLAN_BINDING')
    selected=tuple(EventInstruction(request_from_event(e),e.candidate_ns) for e in calendars['conditional'].events
                   if not e.cancelled and e.clock_status in ('OBSERVED_METADATA_ELIGIBLE','CONDITIONALLY_MODELED'))
    require(plan.events==selected,'STUDY_PRODUCER_EFFECTIVE_REQUESTS')
    projected=plain([asdict(r) for r in plan.source])
    require([{k:v for k,v in r.items() if k!='price_micro'} for r in projected]==roles['source_rows'],
            'STUDY_PRODUCER_SOURCE_ROLE_ROWS')
    from .event_native import EventNativeFailure
    try:component=simulate_event_component(plan,diagnostics=diagnostics_callback)
    except EventNativeFailure as exc:
        raise StudyUnfinalized(str(exc),{'status':'FAILED_UNFINALIZED','binding':binding,
            'native_partial':deepcopy(exc.evidence),'complete_five_control_graph':False,'execution_authority':False}) from exc
    evaluation=evaluate_study(component['accounts'],sidecar,roles,binding)
    return {'schema':'polar.private-calendar-study/1','binding':binding,'calendar':sidecar,'roles':roles,
            'accounts':component['accounts'],'evaluation':evaluation,'execution_authority':False}

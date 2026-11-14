"""Closed source identity/token and caller-owned date roles for fixed AAPL/AMZN.

Pure metadata preflight does not parse retained quote/action values. Explicit
producer use parses supplied tokens; this module never opens a provider/store.
"""
from dataclasses import dataclass
from fractions import Fraction as F
import re
from datetime import datetime,timezone
from .signed_native_bridge import require
from .signed_event_driver import Action

NAMES=('AAPL','AMZN')
CONTROLS=('DYNAMIC_SPREAD','DYNAMIC_HALF_LONG','STATIC_SPREAD','RF0_CASH')
CASES=('BASE','TRADING_2X_BORROW_5X_DEBIT_1P5X',
       'SHORT_1P5','LONG_0P7_SHORT_1P5','LOCATE_DENIED','RECALL_BLACKOUT2','BORROW_50',
       'MAINTENANCE_160','ADVERSE_100BPS','LONG_0P7_SHORT_1P5_RECALL','SHORT_2','SHORT_5')
MERGED='8f4a1ae99499a9663aa6e741e4a9da17b76f84becb3459d028dfdb912fa6760c'


@dataclass(frozen=True)
class Quote:
    name:str
    date:str
    close_ns:int
    modeled_available_ns:int
    raw_usd_token:str
    adjusted_signal_token:str
    raw_pointer:str
    signal_pointer:str
    raw_source_ref:str
    signal_source_ref:str
    local_id:str
    observed_known_ns:int|None=None


@dataclass(frozen=True)
class Formation:
    id:str
    g_index:int
    decision_ns:int
    execution_ns:int
    endpoint21_index:int
    endpoint252_index:int


@dataclass(frozen=True)
class PairInput:
    namespace:str
    input_id:str
    purpose_id:str
    source_pins:tuple[tuple[str,str],...]
    quotes:tuple[Quote,...]
    nav_closes:tuple[int,...]
    formations:tuple[Formation,...]
    actions:tuple[Action,...]
    terminal_decision_ns:int
    terminal_execution_ns:int
    nominal_action_tokens:tuple[tuple[str,str],...]=()
    protocol_sha256:str=MERGED
    price_basis:str='RAW_USD_PER_PHYSICAL_SHARE'
    signal_basis:str='CURRENT_VINTAGE_ADJUSTED_SIGNAL_ONLY'
    action_basis:str='CAPTURED_NOMINAL_UNADJUSTED_VALUE_USD_CONDITIONAL_NOT_COMPLETE'
    historical_access:str='UNQUALIFIED'


def preflight(data):
    require(type(data) is PairInput and data.namespace in ('INVENTED','RETAINED') and data.protocol_sha256==MERGED,
            'PAIR_INPUT_IDENTITY')
    require(all(type(v) is str and v for v in (data.input_id,data.purpose_id)) and
            data.input_id.startswith('INVENTED')==(data.namespace=='INVENTED'),'PAIR_INPUT_NAMESPACE')
    require(data.price_basis=='RAW_USD_PER_PHYSICAL_SHARE' and data.signal_basis=='CURRENT_VINTAGE_ADJUSTED_SIGNAL_ONLY'
        and data.action_basis=='CAPTURED_NOMINAL_UNADJUSTED_VALUE_USD_CONDITIONAL_NOT_COMPLETE' and
        data.historical_access=='UNQUALIFIED','PAIR_INPUT_BASIS')
    require(type(data.source_pins) is tuple and data.source_pins and
        all(type(name) is str and name and type(pin) is str and re.fullmatch('[a-f0-9]{64}',pin)
            for name,pin in data.source_pins) and len(dict(data.source_pins))==len(data.source_pins),'PAIR_SOURCE_PINS')
    require(type(data.quotes) is tuple and data.quotes and all(type(q) is Quote and q.name in NAMES for q in data.quotes),
            'PAIR_QUOTE_SCHEMA')
    rows={n:tuple(q for q in data.quotes if q.name==n) for n in NAMES}
    clocks=tuple(q.close_ns for q in rows[NAMES[0]])
    require(len(clocks)>252 and all(type(t) is int and t>=0 for t in clocks) and
            all(a<b for a,b in zip(clocks,clocks[1:])) and
            all(tuple(q.close_ns for q in r)==clocks for r in rows.values()),'PAIR_SOURCE_RECTANGLE')
    require(len({q.local_id for q in data.quotes})==len(data.quotes),'PAIR_QUOTE_LOCAL_ID_CENSUS')
    for q in data.quotes:
        require(type(q.modeled_available_ns) is int and q.modeled_available_ns==(q.close_ns//(86400*10**9)+1)*(86400*10**9) and
            q.date==datetime.fromtimestamp(q.close_ns//10**9,timezone.utc).date().isoformat() and
            q.observed_known_ns is None and all(type(v) is str and v for v in
             (q.date,q.raw_pointer,q.signal_pointer,q.raw_source_ref,q.signal_source_ref,q.local_id)), 'PAIR_QUOTE_PROVENANCE')
    require(type(data.nav_closes) is tuple and len(data.nav_closes)>=3 and
            tuple(t for t in clocks if t>=data.nav_closes[0])==data.nav_closes,'PAIR_NAV_ROLES')
    require(type(data.formations) is tuple and data.formations and
            len({f.id for f in data.formations})==len(data.formations),'PAIR_FORMATION_CENSUS')
    for f in data.formations:
        require(type(f) is Formation and type(f.g_index) is int and 252<=f.g_index<len(clocks) and
            f.endpoint21_index==f.g_index-21 and f.endpoint252_index==f.g_index-252 and
            type(f.decision_ns) is int and type(f.execution_ns) is int and
            clocks[f.g_index]==max(t for t in clocks if t<f.decision_ns) and
            clocks[f.g_index]<=f.decision_ns<f.decision_ns+60*10**9<=f.execution_ns and
            f.execution_ns==next((t for t in data.nav_closes if t>f.decision_ns),None) and
            all(rows[n][f.g_index].modeled_available_ns+60*10**9==f.decision_ns for n in NAMES), 'PAIR_FORMATION_EXACT_ENDPOINTS')
    require(all(a.decision_ns<b.decision_ns for a,b in zip(data.formations,data.formations[1:])), 'PAIR_FORMATION_ORDER')
    require(type(data.actions) is tuple and all(type(a) is Action and a.name in NAMES and
        a.historical_known_ns is None for a in data.actions) and len({a.id for a in data.actions})==len(data.actions),
        'PAIR_CAPTURED_ACTION_CENSUS')
    require(data.terminal_execution_ns==data.nav_closes[-1] and
        data.formations[-1].execution_ns<data.terminal_decision_ns and
        data.terminal_decision_ns+60*10**9<=data.terminal_execution_ns,'PAIR_TERMINAL_ROLE')
    require(type(data.nominal_action_tokens) is tuple and len(dict(data.nominal_action_tokens))==len(data.nominal_action_tokens) and
        set(dict(data.nominal_action_tokens))=={a.id for a in data.actions} and
        all(type(v) is str and v for _,v in data.nominal_action_tokens),'PAIR_NOMINAL_UNADJUSTED_VALUE_TOKENS')
    if data.namespace=='RETAINED':
        dates={q.close_ns:q.date for q in rows[NAMES[0]]}
        require(dates[data.nav_closes[0]]=='2022-12-30' and dates[data.nav_closes[1]]=='2023-01-03' and
            dates[data.nav_closes[-1]]=='2026-11-06' and
            all(dates[clocks[f.g_index]][:7]<'2026-11' for f in data.formations),'PAIR_RETAINED_WINDOW_TERMINAL_NO_NOV_FORMATION')
        require(len(data.nav_closes)==967 and len(data.formations)==47 and len(data.actions)==15,
                'PAIR_RETAINED_EXTERNAL_CENSUS')
    return {'status':'METADATA_SCHEMA_VALID','input_id':data.input_id,'NAV':len(data.nav_closes),
        'formations':len(data.formations),'captured_actions':len(data.actions),'accounts_shape':len(CONTROLS)*len(CASES),
        'source_payload_values_parsed':False,'execution_authority':False,'historical_access':'UNQUALIFIED',
        'actual_retained_dispatch':'NOT_AUTHORIZED_NOT_ALLOCATED'}


def price(token,*,raw):
    require(type(token) is str and re.fullmatch(r'(0|[1-9][0-9]*)(\.[0-9]+)?',token) and len(token)<=256,
            'PAIR_DECIMAL_LEXICAL_TOKEN')
    value=F(token);require(value>0,'PAIR_POSITIVE_PRICE')
    if raw:require((value*10**6).denominator==1,'PAIR_RAW_SOURCE_PRECISION_UNSUPPORTED')
    return value


def decision_targets(control,equity_cents,eligible_raw,lag21_adjusted,lag252_adjusted):
    """Only current own D NAV + declared past endpoints, never Q quote/cash."""
    require(control in CONTROLS and type(equity_cents) is int and equity_cents>0,'PAIR_D_SIZING_DOMAIN')
    require(all(type(v) is dict and set(v)==set(NAMES) for v in
        (eligible_raw,lag21_adjusted,lag252_adjusted)),'PAIR_D_SYMBOL_CENSUS')
    raw={n:price(eligible_raw[n],raw=True) for n in NAMES}
    score={n:price(lag21_adjusted[n],raw=False)/price(lag252_adjusted[n],raw=False)-1 for n in NAMES}
    long=min(NAMES,key=lambda n:(-score[n],n));short=next(n for n in NAMES if n!=long)
    if control=='STATIC_SPREAD':long,short=NAMES
    weights={n:F() for n in NAMES}
    if control!='RF0_CASH':weights[long]=F(1,2)
    if control in ('DYNAMIC_SPREAD','STATIC_SPREAD'):weights[short]=-F(1,2)
    targets={n:(1 if weights[n]>0 else -1)*int(abs(weights[n])*equity_cents/(100*raw[n])) if weights[n] else 0 for n in NAMES}
    return {'control':control,'own_D_equity_cents':equity_cents,'raw_g_prices':raw,'scores':score,
        'long':long,'short':short,'weights':weights,'targets':targets,'Q_price_consumed':False,
        'quantity_unit':'WHOLE_PHYSICAL_SHARE','signal_basis':'CURRENT_VINTAGE_ADJUSTED_SIGNAL_ONLY'}

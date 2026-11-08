"""Shared offline preflight and lossless, separately channelled event conversion."""
from datetime import datetime, date, timedelta, timezone
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo
from .gym_contract import (DATES, SYMBOLS, PUBLIC_SHA, SOURCE_BINDING_SHA, MEMBERS,
                           GymError, canonical, sha, decode, read_ref, fraction)

OBSERVED_NULLS=('event_open_at','event_close_at','observed_published_at',
                'observed_historical_available_at','economic_security_id')

def epoch_ns(day, hour, minute, tz):
    value=datetime.combine(date.fromisoformat(day),datetime.min.time()).replace(
        hour=hour,minute=minute,tzinfo=tz).astimezone(timezone.utc)
    delta=value-datetime(1970,1,1,tzinfo=timezone.utc)
    return (delta.days*86400+delta.seconds)*1_000_000_000

def convert(rows, tz_bytes):
    tz=ZoneInfo.from_file(BytesIO(tz_bytes))
    cells={(r['reference_date'],r['source_symbol']):r for r in rows}
    events=[]
    for day in DATES:
        for i,symbol in enumerate(SYMBOLS):
            row=cells[(day,symbol)]; raw=row['raw_fields_exact_tokens']
            # Feb4 is OPEN ONLY: no terminal fullbar, H/L/C/V or close mark in event roster.
            if day in (DATES[1],DATES[5],DATES[6]):
                q=epoch_ns(day,9,30,tz)+i
                events.append({'kind':'MODELED_OPEN','symbol':symbol,'date':day,
                               'ts_event':q,'ts_init':q,'price':raw['o'],'quote_size':1000000})
            if day!=DATES[-1]:
                c=epoch_ns(day,16,0,tz)+i
                kday=(date.fromisoformat(day)+timedelta(days=1)).isoformat()
                k=epoch_ns(kday,0,0,tz)
                events.append({'kind':'MODELED_CLOSE_MARK','symbol':symbol,'date':day,
                               'ts_event':c,'ts_init':c,'price':raw['c']})
                events.append({'kind':'ELIGIBLE_BAR','symbol':symbol,'date':day,
                               'ts_event':epoch_ns(day,16,0,tz),'ts_init':k,'known_by_ns':k,
                               'ohlcv':{key:raw[key] for key in ('o','h','l','c','v')}})
    events.sort(key=lambda e:(e['ts_init'],SYMBOLS.index(e['symbol']),e['kind']))
    nav=[{'date':d,'nominal_ns':epoch_ns(d,16,0,tz),
          'sample_ns':epoch_ns(d,16,0,tz)+100,'cash_only':d==DATES[-1]} for d in DATES]
    decisions=[]
    for previous,nextday,orderday in ((DATES[0],'2019-01-26',DATES[1]),
                                      (DATES[4],DATES[5],DATES[5]),
                                      (DATES[5],DATES[6],DATES[6])):
        decisions.append({'observation_date':previous,'order_date':orderday,
                          'decision_ns':epoch_ns(nextday,0,1,tz),
                          'open_ns':epoch_ns(orderday,9,30,tz),'terminal':orderday==DATES[-1]})
    return {'schema':'polar.gym-converted/1','events':events,'nav_grid':nav,
            'decisions':decisions,'source_rows':rows,'model_basis':'MODELED_NOT_OBSERVED',
            'mapping':'SOURCE_SYMBOL_ALIAS_NOT_ECONOMIC_ID','actions':'MODELED_NO_ACTIONS'}

def preflight_experiment(rows, calendar_dates, tz_bytes, converted=None, *,
                         action_rows=(), model_no_actions=True, bindings=None):
    """Same callable for standalone DE use and immediate runner admission."""
    checks=[]
    def check(code,ok,reason=None, *, required=True, basis='observed',applicable=True,scope=None):
        checks.append({'code':code,'status':('PASS' if ok else 'FAIL') if applicable else 'NOT_RUN',
                       'required':required,'applicability':applicable,'scope':scope or {'rows':len(rows)},
                       'reason':reason if not ok or not applicable else None,'basis':basis,
                       'evidence':bindings or {}})
    cells=[(r.get('reference_date'),r.get('source_symbol')) for r in rows]
    expected={(d,s) for d in DATES for s in SYMBOLS}
    missing=sorted(expected-set(cells));extra=sorted(set(cells)-expected)
    check('COMPLETE_GRID',len(rows)==21 and not missing and not extra,
          'INCOMPLETE_GRID',scope={'expected':21,'received':len(rows),'missing':missing,'extra':extra})
    check('NO_DUPLICATES',len(cells)==len(set(cells)),'DUPLICATE_CELL')
    domains=precision=basis=unknown=labels=bool(rows)
    try:tz=ZoneInfo.from_file(BytesIO(tz_bytes))
    except (ValueError,TypeError,EOFError):tz=None;labels=False
    for row in rows:
        # These inputs do not depend on numeric parsing and must be inspected even on a malformed row.
        basis &= row.get('adjustment')=='raw' and row.get('currency')=='USD_REQUEST_CONTRACT' and row.get('feed')=='sip' and row.get('requested_asof')=='2020-09-02'
        unknown &= all(row.get(k,'ABSENT') is None for k in OBSERVED_NULLS)
        try:
            values=row['raw_fields_exact_tokens']
            p={k:fraction(values[k]) for k in ('o','h','l','c','v')}
            domains &= (min(p[k] for k in ('o','h','l','c'))>0 and
                        p['l']<=min(p['o'],p['c'])<=max(p['o'],p['c'])<=p['h'] and
                        p['v']>=0 and p['v'].denominator==1)
            precision &= all((p[k]*10000).denominator==1 for k in ('o','h','l','c')) and p['v'].denominator==1
        except (GymError,KeyError,ValueError,TypeError,ArithmeticError):
            domains=False;precision=False
        try:
            aggregation=datetime.fromisoformat(row['aggregation_label'].replace('Z','+00:00'))
            labels &= tz is not None and aggregation.astimezone(tz).date().isoformat()==row['reference_date']
        except (KeyError,ValueError,TypeError,AttributeError):labels=False
    check('DECIMAL_OHLCV_DOMAIN',bool(domains),'INVALID_OHLCV')
    check('LOSSLESS_4DP_WHOLE_VOLUME',bool(precision),'PRECISION_LOSS')
    check('RAW_BASIS_UNITS_ASOF',bool(basis),'BASIS_MISMATCH')
    check('SOURCE_NULL_CLOCKS_PRESERVED',bool(unknown),'SOURCE_CLOCK_PROMOTION')
    check('AGGREGATION_DATE',bool(labels),'AGGREGATION_DATE_MISMATCH')
    check('CALENDAR_DATES',set(DATES)<=set(calendar_dates),'MISSING_REFERENCE_DATE',basis='documented')
    positive=[]
    for action in action_rows:
        subject=action.get('subject_candidate_from_source_role')
        day=action.get('subject_date_candidate_from_source_field')
        if subject in SYMBOLS and day is not None and DATES[0]<=day<=DATES[-1]: positive.append(action.get('source_id'))
    check('MODELED_ACTION_POLICY',model_no_actions and not positive,'POSITIVE_ACTION_OR_NO_MODEL',basis='modelled',scope={'captured_positive':positive,'completeness':'NOT_ESTABLISHED'})
    valid=None
    if not missing and not extra and len(cells)==len(set(cells)) and domains and labels:
        try: valid=convert(rows,tz_bytes)
        except (KeyError,ValueError,TypeError): pass
    check('CONVERSION_ROUND_TRIP',valid is not None and (converted is None or converted==valid),
          'CONVERSION_ROSTER_OR_PRECISION_MISMATCH',basis='modelled')
    if valid:
        eligible=[e for e in valid['events'] if e['kind']=='ELIGIBLE_BAR']
        clock=all(e['ts_event']<e['ts_init'] for e in eligible)
        for decision in valid['decisions']:
            ks=[e['known_by_ns'] for e in eligible if e['date']==decision['observation_date']]
            clock &= len(ks)==3 and max(ks)<decision['decision_ns']<decision['open_ns']
        check('CAUSAL_K_D_Q_PHASES',bool(clock),'CLOCK_ORDER',basis='modelled')
        check('TERMINAL_OPEN_ONLY',all(e['kind']=='MODELED_OPEN' for e in valid['events'] if e['date']==DATES[-1]),'FUTURE_FULLBAR_LEAK',basis='modelled')
    else:
        check('CAUSAL_K_D_Q_PHASES',False,'CONVERSION_UNAVAILABLE',basis='modelled')
        check('TERMINAL_OPEN_ONLY',False,'CONVERSION_UNAVAILABLE',basis='modelled')
    check('FIXED_EXECUTION_POLICY',True,basis='modelled',scope={'capital':'100000','fee':'1','whole_shares':True,'tick':'0.0001','no_short':True,'zero_latency':True,'fresh_models':True})
    check('ML_LABEL_MATURITY',False,'NO_ML_OR_LABELS_IN_THIS_PROFILE',required=False,applicable=False)
    check('OBSERVED_PIT_ACTION_COMPLETENESS',False,'UNKNOWN_SOURCE_CLOCKS_AND_INCOMPLETE_ACTION_CORPUS',required=False,applicable=False)
    return {'schema':'polar.gym-preflight/1','checks':checks,
            'execution_allowed':all(c['status']=='PASS' for c in checks if c['required'] and c['applicability']),
            'converted_sha256':sha(canonical(valid)) if valid else None}

def load_inputs(config):
    """Read refs, not arbitrary user code; paths stay in physical receipts."""
    if config.get('schema')!='polar.gym-config/1': raise GymError('INVALID_CONFIG')
    if config.get('namespace') not in ('retained','fixture'): raise GymError('INVALID_NAMESPACE')
    pins={}; physical={}
    def read(name,ref):
        raw=read_ref(ref);pins[name]={'sha256':sha(raw),'bytes':len(raw)};physical[name]=ref
        return raw
    if config['namespace']=='fixture':
        fixture=decode(read('fixture',config['fixture']))
        rows=fixture['rows'];calendar=fixture['calendar_dates'];actions=fixture.get('actions',[])
        tzraw=read('timezone',config['timezone'])
    else:
        packet=read('public_freeze',config['public_freeze'])
        if sha(packet)!=PUBLIC_SHA: raise GymError('PUBLIC_PROTOCOL_MISMATCH')
        root=Path(config['public_freeze']['path']).parent
        public={}
        for name,expected in MEMBERS.items():
            raw=read(name,{'path':str(root/name),'sha256':expected})
            if name.endswith('.json'): public[name]=decode(raw)
        scenario=public['scenario-v1.1.json']
        profile_raw=read('source_profile',config['source_profile'])
        if sha(profile_raw)!=scenario['final_source_profile_sha256']: raise GymError('SOURCE_PROFILE_MISMATCH')
        binding=read('source_binding',config['source_binding'])
        if sha(binding)!=SOURCE_BINDING_SHA: raise GymError('SOURCE_BINDING_MISMATCH')
        profile=decode(profile_raw)
        for name in ('raw_manifest','raw_receipt','action_manifest','action_receipt','calendar','timezone','selection','source_inventory','rights_evidence'):
            read(name,profile[name])
        raw_manifest=decode(read_ref(profile['raw_manifest']))
        action_manifest=decode(read_ref(profile['action_manifest']))
        def member(name,manifest,ref,member_name):
            return read(name,dict(manifest['objects'][member_name],path=str(Path(ref['path']).parent/member_name)))
        all_rows=[decode(line) for line in member('bars',raw_manifest,profile['raw_manifest'],'bars.ndjson').splitlines()]
        rows=[r for r in all_rows if r.get('source_symbol') in SYMBOLS and r.get('reference_date') in DATES]
        actions=[decode(line) for line in member('actions',action_manifest,profile['action_manifest'],'actions.ndjson').splitlines()]
        selection=decode(read_ref(profile['selection']))
        expected={(r['reference_date'],r['source_symbol']):r for r in selection['source_row_indices']}
        for ordinal,row in enumerate(all_rows):
            key=(row.get('reference_date'),row.get('source_symbol'))
            if key in expected:
                selected=expected[key]
                if ordinal!=selected['normalized_line_ordinal'] or any(row[k]!=selected[k] for k in ('source_body_sha256','source_row_ordinal','request_ordinal','source_array','aggregation_label')):
                    raise GymError('SELECTION_PROVENANCE_MISMATCH')
        calendar_obj=decode(read_ref(profile['calendar']))
        calendar=calendar_obj['sessions']
        tzraw=read_ref(profile['timezone'])
    report=preflight_experiment(rows,calendar,tzraw,action_rows=actions,bindings=pins)
    if not report['execution_allowed']: return None,report,pins,physical
    converted=convert(rows,tzraw)
    return converted,report,pins,physical

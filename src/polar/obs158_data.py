"""Fixed OBS158 shared data preflight/conversion. No strategy, native or runner calls."""
from dataclasses import dataclass
from datetime import date,datetime,timedelta,timezone
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo
import hashlib
import re

from .gym_contract import canonical,sha
from .gym_data import epoch_ns
from .history_bundle import read_file
from .hyp003_source import decode,member_stream
from .obs158_math import require,Obs158Error,microprice

PUBLIC_SHA='716fd2791a415d096ef98d1839baa5d7cde0260a6ab8ca5569d7a5981901c5a0'
METRIC_SHA='5ec3128a0142032cd012e1d894bfe35c5f7f573d338332235858675dde9ccec1'
MEMBERS={'protocol-v1.json':'8721d695368dc00502878d3b0ef2a2c604e36212b28f3e0eaa6ca6b9b1c4e68f',
         'cohort-order-v1.json':'183b654ea0d22867cca5aee7d7b5c5fde1b6d20dd87f213bfc560b377232d08c',
         'calendar-profile-v1.json':'b94b6ae000d545cb33ec91d0518ea6318d82f5642309345459b6316cb9bc939e',
         'action-profile-v1.json':'9adbf3ce94b58fd734c4c99207882fada67259f7fed2ed1e51a2b6dcd48c1491'}
REVISION='rawpv-d362a3fc2e7b05b31354760a7b95f6de61aa41bafbb1c385ed6d651709c0ea64'
QUALIFICATION='630c2ea06d980fa68672befbf7bb0ab9ca225871c5e1fae3a62f89a0aee05b93'
BAR_SHA='0629d359cce3b5771eb838db725a99e234f2c6bac324e1a76e9a13a5e0422c9f'
NATIVE_FIELDS=('event_open_at','event_close_at','observed_published_at',
               'observed_historical_available_at','economic_security_id')


@dataclass(frozen=True)
class Inputs:
    """Canonical immutable bytes, so callers cannot change an admitted dict in place."""
    profile:bytes
    rows:tuple[bytes,...]
    calendar:tuple[str,...]
    timezone:bytes
    context:bytes
    bindings:bytes
    source_class:str


def read_bound(ref,limit=128*1024**2):
    require(type(ref) is dict and {'path','sha256'}<=set(ref)<= {'path','sha256','bytes'},'INVALID_REFERENCE')
    path=Path(ref['path']);require(path.is_absolute(),'INVALID_REFERENCE')
    raw=read_file(path.parent,path.name,limit)
    require(sha(raw)==ref['sha256'] and ('bytes' not in ref or len(raw)==ref['bytes']),'REFERENCE_INTEGRITY')
    return raw


def public_profile(public_ref,metric_ref):
    packet=read_bound(public_ref,1024**2)
    require(sha(packet)==PUBLIC_SHA,'PUBLIC_PROFILE_MISMATCH')
    metric=read_bound(metric_ref,1024**2);require(sha(metric)==METRIC_SHA,'METRIC_PROFILE_MISMATCH')
    root=Path(public_ref['path']).parent
    members={name:decode(read_bound({'path':str(root/name),'sha256':expected},1024**2))
             for name,expected in MEMBERS.items()}
    return canonical({'members':members,'metric_basis':decode(metric),
                      'public_sha256':PUBLIC_SHA,'metric_sha256':METRIC_SHA})


def _profile(inputs):
    profile=decode(inputs.profile);members=profile['members']
    return profile,members['cohort-order-v1.json']['symbols_in_route_order'],\
        members['calendar-profile-v1.json']['reference_dates']


def _ns(value):
    stamp=datetime.fromisoformat(value.replace('Z','+00:00'))
    require(stamp.tzinfo is not None,'INVALID_CLOCK')
    delta=stamp.astimezone(timezone.utc)-datetime(1970,1,1,tzinfo=timezone.utc)
    return (delta.days*86400+delta.seconds)*1000000000+delta.microseconds*1000


def known_by(day,calendar,tz):
    require(day in calendar,'MISSING_REFERENCE_DATE')
    index=calendar.index(day)
    require(index+2<len(calendar),'MISSING_FUTURE_REFERENCE_DATES_FOR_K')
    after=(date.fromisoformat(calendar[index+2])+timedelta(days=1)).isoformat()
    return epoch_ns(after,0,0,tz)


def load_obs158_inputs(config):
    """Offline retained source loader. Must not be invoked as a free preparation run."""
    require(type(config) is dict and set(config)=={'schema','public_ref','metric_ref'}
            and config['schema']=='polar.obs158-input-config/1','INVALID_CONFIG')
    profile=public_profile(config['public_ref'],config['metric_ref'])
    value=decode(profile);protocol=value['members']['protocol-v1.json']
    aliases=value['members']['cohort-order-v1.json']['symbols_in_route_order']
    days=value['members']['calendar-profile-v1.json']['reference_dates']
    require(protocol['dataset_revision']==REVISION,'SOURCE_REVISION_MISMATCH')
    metadata={};bindings={};raw_by_hash={};corpus_rows={}
    def retain(name,ref):
        raw=read_bound(ref);bindings[name]={'sha256':sha(raw),'bytes':len(raw)}
        return raw
    for name,ref in protocol['data_refs'].items():metadata[name]=decode(retain(name,ref))
    require(bindings['content-manifest.json']['sha256']==QUALIFICATION,'QUALIFICATION_MISMATCH')
    inspection=metadata['inspection.json'];pins=inspection['all_source_pins']
    # Hash every declared transitive source, without converting receipts into historical clocks.
    normalized=None;bars_path=None;bars_ref=None;source_manifests={}
    for path,ref in pins.items():
        full={**ref,'path':path}
        if ref['sha256']==BAR_SHA:
            require(bars_path is None,'AMBIGUOUS_SOURCE_BINDING');bars_path=Path(path);bars_ref=full
            continue
        raw=retain(path,full)
        if Path(path).name=='content-manifest.json':
            source_manifests[path]=decode(raw)
            if sha(raw)==REVISION.removeprefix('rawpv-'):normalized=(Path(path),decode(raw))
        elif '/raw/' in path:raw_by_hash[sha(raw)]=decode(raw)
        elif Path(path).name=='bars.ndjson':
            require(ref['sha256']=='c0cfbba4d65da0d717a4c9ce183a6f1a4a2a6a9b03f7a564108bf856534abbd5',
                    'UNBOUND_REUSED_CORPUS')
            corpus_rows={i:decode(line) for i,line in enumerate(raw.splitlines(),1)}
    require(normalized is not None and bars_path is not None and normalized[0].parent==bars_path.parent,
            'SOURCE_MANIFEST_BINDING')
    norm=normalized[1]
    require(norm['schema']=='polar.partial-raw-pv-source-content/1'
            and norm['source_capture_content_sha256']==protocol['terminal_manifest_sha256'],
            'SOURCE_MANIFEST_BINDING')
    for name,ref in norm['objects'].items():
        path=str(normalized[0].parent/name)
        require(path in pins and pins[path]==ref,'SOURCE_MEMBER_BINDING')
    rows=[];hasher=hashlib.sha256();size=0;seen=set();zero=[]
    with member_stream(bars_path.parent,bars_path.name,128*1024**2) as stream:
        for line,raw in enumerate(stream,1):
            require(line<=1000000 and len(raw)<=256*1024,'SOURCE_ROW_BOUND')
            hasher.update(raw);size+=len(raw);row=decode(raw)
            require(type(row) is dict,'SOURCE_ROW_SCHEMA')
            alias=row.get('source_symbol');day=row.get('reference_date')
            if alias not in aliases or day not in days:continue
            key=(alias,day);require(key not in seen,'DUPLICATE_SOURCE_CELL');seen.add(key)
            rows.append(canonical(row))
            if row.get('raw_volume') in ('0','0.0','0.00'):zero.append((alias,day,line))
            pointer=row['source_reference']
            require(pointer['source_array']=='bars.'+alias,'SOURCE_POINTER_ARRAY')
            body=raw_by_hash.get(pointer['source_body_sha256'])
            require(body is not None,'SOURCE_BODY_NOT_BOUND')
            ordinal=pointer['source_row_ordinal']
            require(type(ordinal) is int and ordinal>=0,'SOURCE_POINTER_ORDINAL')
            array=body.get('bars',{}).get(alias)
            require(type(array) is list and ordinal<len(array),'SOURCE_POINTER_ARRAY')
            original=array[ordinal];tokens=row['raw_fields_exact_tokens']
            # Decoder preserves fractional numeric tokens; integer source values compare by exact decimal spelling.
            require(all(str(original.get(k))==str(v) for k,v in tokens.items()),'SOURCE_POINTER_TOKENS')
            if row.get('capture_origin')=='NEW_NETWORK_PAGE':
                bodypath=str(normalized[0].parent.parent/pointer['raw_file'])
                require(bodypath in pins and pins[bodypath]['sha256']==pointer['source_body_sha256'],
                        'SOURCE_POINTER_BODY')
            else:
                require(pointer.get('corpus_revision')=='multisiphist-e01012bf694a78eeb11519032eaabd74f74ba0c0f4be0ac7e3edbc42e40532d8'
                        and type(pointer.get('corpus_line')) is int and pointer['corpus_line']>0,
                        'REUSED_SOURCE_POINTER')
                intermediate=corpus_rows.get(pointer['corpus_line'])
                require(type(intermediate) is dict and intermediate.get('source_symbol')==alias
                        and intermediate.get('reference_date')==day
                        and intermediate.get('raw_fields_exact_tokens')==tokens
                        and all(intermediate.get(k)==pointer[k] for k in
                                ('source_body_sha256','source_array','source_row_ordinal')),
                        'REUSED_CORPUS_LINE_JOIN')
    require(size==bars_ref['bytes'] and hasher.hexdigest()==BAR_SHA,'SOURCE_BARS_INTEGRITY')
    bindings['bars.ndjson']={'sha256':BAR_SHA,'bytes':size}
    calendar_raw=retain('calendar',protocol['calendar']);tz=retain('timezone',protocol['timezone'])
    context={'qualification':metadata,'observed_zero_rows':zero,
             'pointer_scope':'RAW_ARRAY_TOKENS_GRAPH_HASHES_AND_REUSED_CORPUS_LINE_JOIN',
             'source_graph_files':len(pins),'source_manifests':source_manifests}
    return Inputs(profile,tuple(rows),tuple(decode(calendar_raw)['sessions']),tz,
                  canonical(context),canonical(bindings),'RETAINED')


RETAINED_ASOF = '2020-09-02_ENTITY_MAPPING_NOT_VINTAGE;FALLBACK_UNVERIFIED'


def source_basis_matches(row, source_class):
    """Exact declared metadata, not historical vintage or economic identity proof.

    The retained normalizer deliberately preserves both qualifier limitations.
    The frozen public invented fixture keeps its distinct bare request token.
    No prefix match, whitespace stripping or source-row rewrite is performed.
    """
    expected = {'RETAINED': RETAINED_ASOF, 'INVENTED': '2020-09-02'}.get(source_class)
    return (expected is not None and row.get('adjustment') == 'raw' and row.get('feed') == 'sip' and
            row.get('currency') == 'USD_REQUEST_CONTRACT' and row.get('asof') == expected)


def preflight_obs158(inputs,converted=None):
    """Same data checker for DE and runner. Part A never admits a strategy run."""
    profile,aliases,days=_profile(inputs);members=profile['members']
    rows=[decode(raw) for raw in inputs.rows];checks=[]
    def check(code,ok,reason,*,required=True,basis='SUPPLIED_SOURCE'):
        checks.append({'code':code,'status':'PASS' if ok else 'FAIL','reason':None if ok else reason,
                       'required':required,'basis':basis})
    check('FIXED_PROFILE',profile['public_sha256']==PUBLIC_SHA and profile['metric_sha256']==METRIC_SHA,
          'PUBLIC_PROFILE_MISMATCH')
    check('LEXICAL_ALIAS_GRID',len(aliases)==158 and len(set(aliases))==158 and aliases==sorted(aliases)
          and len(days)==253 and days==sorted(set(days)),'FIXED_PROFILE_GRID')
    cells=[(r.get('source_symbol'),r.get('reference_date')) for r in rows]
    expected={(s,d) for s in aliases for d in days}
    check('COMPLETE_UNIQUE_GRID',len(rows)==39974 and len(set(cells))==39974 and set(cells)==expected,
          'INCOMPLETE_OR_DUPLICATE_SOURCE_GRID')
    domains=basis=clocks=labels=lexical=True;zeros=0
    try:tz=ZoneInfo.from_file(BytesIO(inputs.timezone))
    except (ValueError,TypeError,EOFError):tz=None;labels=False;clocks=False
    for row in rows:
        # Independent checks still inspect bad numeric rows.
        basis &= source_basis_matches(row, inputs.source_class)
        clocks &= all(k in row and row[k] is None for k in NATIVE_FIELDS)
        try:
            raw=row['raw_fields_exact_tokens']
            values={k:microprice(raw[k]) for k in ('o','h','l','c')}
            domains &= values['l']<=min(values['o'],values['c'])<=max(values['o'],values['c'])<=values['h']
            domains &= type(raw['v']) is str and bool(re.fullmatch(r'[0-9]{1,24}',raw['v']))
            zeros+=raw['v']=='0'
            lexical &= all(row[field]==raw[key] for field,key in
                           (('raw_open','o'),('raw_high','h'),('raw_low','l'),('raw_close','c'),('raw_volume','v')))
            lexical &= values['o']%100==0  # source O<=4dp; closes retain6dp.
        except (Obs158Error,KeyError,TypeError,ValueError):domains=False;lexical=False
        try:
            aggregation=datetime.fromisoformat(row['aggregation_label'].replace('Z','+00:00'))
            labels &= tz is not None and aggregation.tzinfo is not None and aggregation.astimezone(tz).date().isoformat()==row['reference_date']
            clocks &= tz is not None and _ns(row['estimated_K'])==known_by(row['reference_date'],inputs.calendar,tz)
        except (KeyError,TypeError,ValueError,AttributeError):labels=False;clocks=False
    check('RAW_DOMAIN_WHOLE_VOLUME',bool(domains),'INVALID_SOURCE_DOMAIN')
    check('LOSSLESS_SOURCE_TOKENS_4DP_OPEN_6DP_CLOSE',bool(lexical),'SOURCE_TOKEN_OR_PRECISION_MISMATCH')
    check('RAW_SIP_USD_REQUEST_ASOF',bool(basis),'SOURCE_BASIS_MISMATCH')
    check('NULL_CLOCKS_AND_TWO_SESSION_K',bool(clocks),'CLOCK_PROMOTION_OR_K_MISMATCH',basis='ESTIMATED_MODEL')
    check('AGGREGATION_DATE',bool(labels),'SOURCE_DATE_MISMATCH')
    check('ZERO_VOLUME_FLAGS',zeros==960,'FIXED_ZERO_VOLUME_COUNT')
    context=decode(inputs.context);qualification=context.get('qualification',{})
    if inputs.source_class=='RETAINED':
        cohort=qualification.get('complete-source-symbols.json',{}).get('symbols',[])
        coverage=qualification.get('instrument-coverage.json',[])
        excluded=[r for r in coverage if r['source_symbol'] not in aliases]
        check('ALIAS_SET_JOIN_AND_EXCLUDED_CONTEXT',set(cohort)==set(aliases) and len(coverage)==200
              and len(excluded)==42 and sum(r['status']=='PARTIAL_REFERENCE_DATES' for r in excluded)==8
              and sum(r['status']=='EMPTY_REQUEST_RESULT_NOT_ZERO' for r in excluded)==34,'SOURCE_COHORT_CONTEXT')
    else:check('FIXTURE_LABEL',inputs.source_class=='INVENTED','UNBOUND_SOURCE_CLASS',basis='INVENTED')
    check('SOURCE_POINTER_GRAPH',inputs.source_class=='INVENTED' or context.get('pointer_scope')
          =='RAW_ARRAY_TOKENS_GRAPH_HASHES_AND_REUSED_CORPUS_LINE_JOIN','SOURCE_POINTER_GRAPH_INCOMPLETE')
    canonical_conversion=None
    if all(c['status']=='PASS' for c in checks if c['required']):
        try:canonical_conversion=convert_obs158(inputs)
        except (Obs158Error,KeyError,TypeError,ValueError):pass
    check('CONVERSION_BINDING',canonical_conversion is not None and
          (converted is None or canonical(converted)==canonical(canonical_conversion)),
          'CONVERSION_MISMATCH')
    for code in ('NATIVE_CENT_UNIT_EQUIVALENCE','INDEPENDENT_CONTROLS','RUNNER_OUTPUT_SCHEMA','ACTUAL_RUNTIME_BINDING'):
        checks.append({'code':code,'status':'NOT_RUN','reason':'PART_B_NOT_IMPLEMENTED',
                       'required':True,'basis':'ENGINEERING'})
    return {'schema':'polar.obs158-preflight/1','checks':checks,'runner_execution_allowed':False,
            'source_class':inputs.source_class,'financial_status':'INSUFFICIENT_EVIDENCE',
            'financial_scope':'PRICE_ONLY_PARTIAL_ACTION_EXECUTION_MODEL',
            'bindings':decode(inputs.bindings)}


def convert_obs158(inputs):
    """Separate executor, private mark, delayed strategy and unit channels."""
    profile,aliases,days=_profile(inputs);members=profile['members']
    tz=ZoneInfo.from_file(BytesIO(inputs.timezone))
    cells={}
    for raw in inputs.rows:
        row=decode(raw);key=(row['source_symbol'],row['reference_date'])
        require(key not in cells,'DUPLICATE_SOURCE_CELL');cells[key]=row
    require(set(cells)=={(s,d) for s in aliases for d in days},'INCOMPLETE_SOURCE_GRID')
    decisions=[]
    for original in members['calendar-profile-v1.json']['decisions']:
        k=known_by(original['snapshot_date'],inputs.calendar,tz)
        require(k==_ns(original['known_by_model']) and k<_ns(original['decision_model'])
                <_ns(original['open_model']),'K_D_Q_MISMATCH')
        decisions.append({**original,'known_by_ns':k,'decision_ns':_ns(original['decision_model']),
                          'open_ns':_ns(original['open_model']),
                          'disposition':'IN_WINDOW' if original['within_funded_window']
                                        else 'NOT_EXECUTED_OUTSIDE_PROFILE'})
    openings={d['order_date']:d['open_ns'] for d in decisions if d['within_funded_window']}
    quotes=[];marks=[];eligible=[];barriers=[];samples=[];units=[]
    for day in days:
        close=epoch_ns(day,16,0,tz);k=known_by(day,inputs.calendar,tz)
        for ordinal,alias in enumerate(aliases):
            row=cells[(alias,day)];raw=row['raw_fields_exact_tokens']
            # The raw source bytes/tokens remain unchanged in every channel.
            if day in openings:
                quotes.append({'alias':alias,'date':day,'ts_event':openings[day],
                               'ts_init':openings[day],'ordinal':ordinal,'raw_open':raw['o'],
                               'price_micro':str(microprice(raw['o'])),'depth':1000000})
            marks.append({'alias':alias,'date':day,'ts_event':close,'ts_init':close,
                          'ordinal':ordinal,'raw_close':raw['c'],
                          'price_micro':str(microprice(raw['c']))})
            eligible.append({'alias':alias,'date':day,'ts_event':close,'ts_init':k,'known_by_ns':k,
                             'ordinal':ordinal,'raw_ohlcv':{f:raw[f] for f in ('o','h','l','c','v')},
                             'source_row_sha256':sha(canonical(row))})
        barriers.append({'channel':'MARKS_COMPLETE','date':day,'ts_init':close+1,'expected_aliases':158})
        barriers.append({'channel':'ELIGIBLE_COMPLETE','date':day,'ts_init':k+1,'expected_aliases':158})
        samples.append({'date':day,'nominal_ns':close,'sample_ns':close+100,'cash_only':day<days[3],
                        'report_known_by_ns':k})
        if day in openings:
            q=openings[day]
            barriers.append({'channel':'QUOTES_COMPLETE','date':day,'ts_init':q+1,'expected_aliases':158})
    for event in members['action-profile-v1.json']['split_events']:
        factor=event['new_per_old'];require(factor in ('4/1','5/1'),'SPLIT_FACTOR_MISMATCH')
        when=epoch_ns(event['first_trading_date'],8,0,tz)
        require(all(not d['within_funded_window'] or d['open_ns']<when for d in decisions),
                'POST_SPLIT_TRADE_NOT_SUPPORTED')
        units.append({'alias':event['symbol'],'date':event['first_trading_date'],'ts_init':when,
                      'new_per_old':factor,'source_id':event['source_id'],
                      'source_line_sha256':event['source_line_sha256'],'application':'FORWARD_ONCE'})
    quote_slots={'sell_offset_ns':100,'buy_offset_ns':1000,'alias_slot_ns':1,
                 'quote_barrier_offset_ns':1,'mark_barrier_offset_ns':1,'sample_offset_ns':100,
                 'ack_required_before_next_order':True,'native_behavior':'NOT_YET_QUALIFIED'}
    return {'schema':'polar.obs158-converted/1','public_sha256':PUBLIC_SHA,'metric_sha256':METRIC_SHA,
            'executor_quotes':quotes,'private_close_marks':marks,'eligible_bars':eligible,
            'unit_events':units,'barriers':sorted(barriers,key=lambda e:(e['ts_init'],e['channel'])),
            'sample_grid':samples,'decisions':decisions,'route_slots':quote_slots,
            'raw_basis':'RAW_UNCHANGED','event_clocks':'MODELED_NOT_OBSERVED',
            'actions':'KNOWN_SPLITS_ONCE_ALL_DIVIDENDS_EXCLUDED_OTHER_FACTOR1_UNVERIFIED'}

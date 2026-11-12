"""Closed lagged Treasury curve adapter; metadata before debit, values after it.

The existing reference loader, target executor, money and metric recipes own
their respective jobs. This module neither fetches data nor pays yield to cash.
"""
from bisect import bisect_right
from datetime import date, datetime, timedelta, timezone
from fractions import Fraction

from .ci_research import require
from .gym_contract import canonical, sha, fraction
from .reference_ridge_plan import nanoseconds
from .research_reference import decode, pinned_bytes, load_reference

PROFILE = 'polar.scheduled-reference-profile/11'
INPUT = 'polar.scheduled-curve-input/1'
RIGHTS = 'TREASURY_CONDITIONAL_PRIVATE_DETERMINISTIC_RESEARCH_AND_VTI_SOLE_OWNER_PRIVATE_NONCOMMERCIAL_NO_PUBLIC_DATA_REDISTRIBUTION_NO_ML'
LEGS = ('CURVE_VTI', 'HALF_VTI', 'FULL_VTI', 'CASH')
FIELDS = ['BC_2YEAR', 'BC_10YEAR']
POLICY = {'kind': 'TREASURY_2Y10Y_SIGN', 'lag_sessions': 2,
          'max_age_days': 10, 'symbol': 'VTI', 'drawdown_peak': 'EARLIEST_EQUAL_PEAK'}


class CurveError(ValueError):
    def __init__(self, reason, events):
        super().__init__(reason)
        self.events = events


def expected_counts(n):
    return {'feature_calls': n, 'rate_operand_reads': 2*n,
            'completed_features': n, 'sign_decisions': n, 'completed_decisions': n}


def validate_profile(p):
    require(type(p['policy']) is dict and p['policy'] == POLICY and
            type(p['policy']['lag_sessions']) is int and type(p['policy']['max_age_days']) is int and p['symbols'] == ['VTI'] and
            p['decision_delay_seconds'] == 60, 'SCHEDULED_CURVE_POLICY')
    require([l['id'] for l in p['legs']] == list(LEGS) and
            [l['rule'] for l in p['legs']] == ['CURVE', 'FIXED', 'FIXED', 'CASH'] and
            [l['scale'] for l in p['legs']] == [[1,1], [1,2], [1,1], [0,1]] and
            p['primary_strategy'] == LEGS[0] and p['primary_benchmark'] == LEGS[1],
            'SCHEDULED_CURVE_LEGS')
    require(p['cost_scenarios'] == [
        {'id':'BASE','cost_profile':{'flat_cents':100,'bps':10}},
        {'id':'COST_STRESS','cost_profile':{'flat_cents':200,'bps':20}}],
        'SCHEDULED_CURVE_COSTS')
    kinds = {'TERMINAL_GT','SR_DELTA_GE','DRAWDOWN_LE','VOL_RATIO_BETWEEN','POSITIVE_GROWTH'}
    require(len(p['criteria']) == 5 and {c['kind'] for c in p['criteria']} == kinds and
            all(c['left_id'] == LEGS[0] and
                (c['kind'] == 'POSITIVE_GROWTH' or c['right_id'] == LEGS[1]) and
                (c['kind'] != 'SR_DELTA_GE' or c['threshold'] == '0.10') and
                (c['kind'] != 'VOL_RATIO_BETWEEN' or
                 (c['lower'], c['upper']) == ('0.8','1.25')) for c in p['criteria']) and
            len(p['subperiods']) <= 2, 'SCHEDULED_CURVE_CRITERIA')


def _day(v):
    require(type(v) is str and date.fromisoformat(v).isoformat() == v, 'CURVE_DATE')
    return v


def _index(value, records_pin):
    require(type(value) is dict and set(value) == {'schema','macro_records_sha256','records'} and
            value['schema'] == 'polar.scheduled-curve-index/1' and
            value['macro_records_sha256'] == records_pin['sha256'], 'CURVE_INDEX_BINDING')
    rows = value['records']
    require(type(rows) is list and 0 < len(rows) <= 10000, 'CURVE_INDEX_BOUND')
    previous = None
    for i, r in enumerate(rows):
        require(type(r) is dict and set(r) == {'date','line_1based','byte_start',
            'byte_end_exclusive','fields','conflict','historical_K'}, 'CURVE_INDEX_FIELDS')
        _day(r['date'])
        require(r['fields'] == FIELDS and r['conflict'] is False and r['historical_K'] is None,
                'CURVE_FIELD_AVAILABILITY_CONFLICT')
        require(all(type(r[k]) is int for k in ('line_1based','byte_start','byte_end_exclusive')) and
                r['line_1based'] == i+1 and r['byte_start'] == (previous['byte_end_exclusive'] if previous else 0) and
                r['byte_start'] < r['byte_end_exclusive'] <= records_pin['bytes'] and
                (previous is None or previous['date'] < r['date']), 'CURVE_INDEX_ORDER_SPANS')
        previous = r
    require(rows[-1]['byte_end_exclusive'] == records_pin['bytes'], 'CURVE_INDEX_FULL_FILE')
    return rows


def metadata(pin, namespace):
    """Only descriptor/date/index/purpose metadata; never token or quote bytes."""
    raw = pinned_bytes(pin)
    d = decode(raw)
    require(type(d) is dict and set(d) == {'schema','reference_input_ref','macro_records_ref',
        'macro_index_ref','source_date_join_ref','purpose_ref','source_delivery_ref',
        'rights','provenance','historical_K','limitations'} and d['schema'] == INPUT,
        'CURVE_INPUT_FIELDS')
    require(d['rights'] == ('INVENTED_PUBLIC_TEST' if namespace == 'INVENTED' else RIGHTS) and
            d['historical_K'] is None and type(d['limitations']) is list and d['limitations'] and
            all(type(s) is str and 0 < len(s) <= 2048 for s in d['limitations']) and
            type(d['provenance']) is dict, 'CURVE_INPUT_RIGHTS_LIMITS')
    if namespace == 'INVENTED':
        require(d['provenance'] == {'kind':'DETERMINISTIC_INVENTED_FIXTURE','source_payloads':'NONE'},
                'CURVE_INVENTED_PROVENANCE')
    # Source-purpose/review custody pins these metadata objects; do not follow
    # arbitrary nested raw/source/value references found inside them.
    for key in ('purpose_ref','source_delivery_ref'):
        pinned_bytes(d[key])
    if namespace=='RETAINED':
        require(d['provenance'].get('source_unit')=='PERCENT_ANNUALIZED_NOMINAL_PAR_YIELD_NOT_RETURN_OR_SPENDABLE_CASH' and
                d['provenance'].get('vti_unit')=='SCALE1_ADJUSTED_SYNTHETIC_REFERENCE_UNIT_NOT_PHYSICAL_SHARE', 'CURVE_DECLARED_UNITS')
        pinned_bytes(d['provenance']['source_quality'])
    index_raw = pinned_bytes(d['macro_index_ref'])
    _index(decode(index_raw), d['macro_records_ref'])
    joins_raw = pinned_bytes(d['source_date_join_ref'])
    proof = decode(joins_raw)
    require(type(proof) is dict and type(proof.get('joins')) is list, 'CURVE_DATE_PROOF')
    return {'descriptor_raw': raw.decode('utf-8'), 'index_raw': index_raw.decode('utf-8'),
            'joins_raw': joins_raw.decode('utf-8'), 'namespace': namespace}


def context(value, expected_sha):
    """Saved metadata-only context; no pin-following in stored verification."""
    d = decode(value['descriptor_raw'].encode())
    require(sha(value['descriptor_raw'].encode()) == expected_sha and d['schema'] == INPUT and
            sha(value['index_raw'].encode()) == d['macro_index_ref']['sha256'] and
            sha(value['joins_raw'].encode()) == d['source_date_join_ref']['sha256'], 'CURVE_SAVED_METADATA_BINDING')
    return d, _index(decode(value['index_raw'].encode()), d['macro_records_ref']), decode(value['joins_raw'].encode())


def date_joins(value, profile, schedule, grids):
    d, source, proof = context(value, profile['input_sha256'])
    if value['namespace']=='RETAINED':
        require(d['provenance'].get('protocol',{}).get('sha256')==profile['protocol_sha256'], 'CURVE_PROTOCOL_PURPOSE_BINDING')
    require(set(grids) == {'FINAL'}, 'CURVE_FINAL_ONLY')
    grid = grids['FINAL']; days = [r['date'] for r in schedule]; by_day = {r['date']:r for r in schedule}
    require(len(grid['decisions']) == 47 and len(grid['nav_dates']) == 967 and
            grid['return_count'] == 966 and days.index(grid['initial']) >= 2, 'CURVE_FIXED_GRID_COUNTS')
    source_days = [r['date'] for r in source]; result = []
    for event in grid['decisions']:
        formation, entry = event['signal_date'], event['execution_date']; i = days.index(formation)
        require(i >= 2 and entry == by_day[formation]['next_reference_date'], 'CURVE_REFERENCE_LAG')
        cutoff = days[i-2]; j = bisect_right(source_days, cutoff)-1
        require(j >= 0, 'CURVE_NO_ELIGIBLE_SOURCE_DATE')
        r = source[j]; age = (date.fromisoformat(formation)-date.fromisoformat(r['date'])).days
        require(0 <= age <= 10, 'CURVE_SOURCE_AGE')
        known = datetime.fromisoformat(formation).replace(tzinfo=timezone.utc)+timedelta(days=1)
        k = nanoseconds(known); decision = k+60*10**9
        q = nanoseconds(datetime.fromisoformat(by_day[entry]['reference_close_utc']))
        require(nanoseconds(datetime.fromisoformat(by_day[formation]['reference_close_utc'])) < k < decision < q,
                'CURVE_K_D_Q')
        result.append({'formation_date':formation,'execution_date':entry,'formation_index':i,
            'cutoff_date':cutoff,'source_date':r['date'],'civil_age_days':age,
            **{key:r[key] for key in ('line_1based','byte_start','byte_end_exclusive')},
            'known_ns':k,'decision_ns':decision,'close_ns':q})
    require(len(proof['joins']) == len(result), 'CURVE_DATE_PROOF_COUNT')
    for expected, observed in zip(result, proof['joins']):
        require(all(observed.get(k) == expected[v] for k,v in (
            ('formation_date','formation_date'),('execution_date','execution_date'),
            ('cutoff_date','cutoff_date'),('selected_treasury_date','source_date'),
            ('civil_age_days','civil_age_days'))), 'CURVE_DATE_PROOF_JOIN')
    terminal = grid['terminal']; previous = days[days.index(terminal)-1]
    k = nanoseconds(datetime.fromisoformat(previous).replace(tzinfo=timezone.utc)+timedelta(days=1))
    q = nanoseconds(datetime.fromisoformat(by_day[terminal]['reference_close_utc']))
    require(nanoseconds(datetime.fromisoformat(by_day[previous]['reference_close_utc'])) < k < k+60*10**9 < q,
            'CURVE_TERMINAL_K_D_Q')
    return result


def load_market(pin, profile, schedule, grids, namespace):
    value = metadata(pin, namespace)
    d, _, _ = context(value, profile['input_sha256'])
    selected = date_joins(value, profile, schedule, grids)
    market = load_reference(d['reference_input_ref'])
    raw = pinned_bytes(d['macro_records_ref'])  # Only after durable FIRST_START.
    lines=raw.splitlines(keepends=True);index=decode(value['index_raw'].encode())['records']
    require(len(lines)==len(index) and all(raw[r['byte_start']:r['byte_end_exclusive']]==line for r,line in zip(index,lines)), 'CURVE_ACTUAL_LINE_SPANS')
    return {**market, 'symbols':['VTI'],
        'prices_micro':{day:{'VTI':row['VTI']} for day,row in market['prices_micro'].items()},
        'curve_context':value,'curve_joins':selected,'curve_bytes':raw}


def targets(weight):
    return {leg:{'VTI':[v.numerator,v.denominator]} for leg,v in
            zip(LEGS,(Fraction(weight),Fraction(1,2),Fraction(1),Fraction(0)))}


def plan_phase(market, profile, grid, tz):
    validate_profile(profile)
    d, _, _ = context(market['curve_context'], profile['input_sha256'])
    selected = date_joins(market['curve_context'], profile, market['schedule'], {'FINAL':grid})
    require(selected == market['curve_joins'], 'CURVE_JOIN_CHANGED')
    signals = []; decisions = []; counts = expected_counts(0)
    for j in selected:
        witness = {'join':j,'macro_sha256':d['macro_records_ref']['sha256']}
        try:
            counts['feature_calls'] += 1
            raw = market['curve_bytes'][j['byte_start']:j['byte_end_exclusive']]
            row = decode(raw)
            require(set(row) == {'source_date','tokens','raw_ref','raw_pointers','captured_at',
                'entry_updated','feed_updated','historical_K','historical_available_at','method_context'} and
                row['source_date'] == j['source_date'] and row['historical_K'] is None and
                row['historical_available_at'] is None and set(row['tokens']) == {'NEW_DATE',*FIELDS},
                'CURVE_RATE_ROW_BINDING')
            require(type(row['tokens']['NEW_DATE']) is str and row['tokens']['NEW_DATE'][:10] == j['source_date'] and
                    set(row['raw_pointers']) == {'NEW_DATE',*FIELDS}, 'CURVE_RAW_DATE_POINTERS')
            require(type(row['raw_ref']) is dict and set(row['raw_ref'])=={'path','sha256','bytes'} and
                    type(row['raw_ref']['sha256']) is str and len(row['raw_ref']['sha256'])==64 and
                    type(row['raw_ref']['bytes']) is int and row['raw_ref']['bytes']>0, 'CURVE_RAW_SOURCE_REF')
            for field,pointer in row['raw_pointers'].items():
                require(type(pointer) is dict and set(pointer)=={'field','byte_start','byte_end_exclusive','xml_entry_ordinal_zero_based'} and
                        pointer['field']==field and all(type(pointer[k]) is int for k in ('byte_start','byte_end_exclusive','xml_entry_ordinal_zero_based')) and
                        0<=pointer['byte_start']<pointer['byte_end_exclusive']<=row['raw_ref']['bytes'] and pointer['xml_entry_ordinal_zero_based']>=0, 'CURVE_RAW_FIELD_POINTER')
            witness.update(source_row=row,source_row_raw=raw.decode('utf-8'),row_sha256=sha(raw))
            rates = {}
            for field in FIELDS:
                counts['rate_operand_reads'] += 1
                token = row['tokens'][field]
                require(type(token) is str, 'CURVE_RATE_TOKEN_STRING')
                rates[field] = fraction(token)
            spread = rates['BC_10YEAR']-rates['BC_2YEAR']; counts['completed_features'] += 1
            weight = int(spread > 0); counts['sign_decisions'] += 1
            witness.update(source_row=row, source_row_raw=raw.decode('utf-8'), row_sha256=sha(raw),
                spread=[str(spread.numerator),str(spread.denominator)], targets=targets(weight))
            counts['completed_decisions'] += 1
        except (ValueError,KeyError,ArithmeticError,TypeError) as exc:
            raise CurveError('CURVE_INVALID_OPERAND_OR_DOMAIN', {'completed_signals':signals,
                'failed_signal':witness,'actual_counts':dict(counts),'cause':str(exc)[:160]}) from exc
        witness['seal_sha256'] = sha(canonical(witness)); signals.append(witness)
        decisions.append({'day':j['execution_date'],'formation':j['formation_date'],
            'known_ns':j['known_ns'],'decision_ns':j['decision_ns'],'open_ns':j['close_ns'],
            'formation_close_ns':nanoseconds(datetime.fromisoformat(next(r['reference_close_utc'] for r in market['schedule'] if r['date']==j['formation_date']))),
            'kind':'REFERENCE','instructions':{leg:{'kind':'TARGET','weights':witness['targets'][leg],
                'signal':{'kind':'TREASURY_CURVE','index':len(signals)-1,'witness_sha256':witness['seal_sha256']}} for leg in LEGS}})
    days = market['dates']; rows = {r['date']:r for r in market['schedule']}; terminal = grid['terminal']
    previous = days[days.index(terminal)-1]
    k = nanoseconds(datetime.fromisoformat(previous).replace(tzinfo=timezone.utc)+timedelta(days=1))
    close = lambda day:nanoseconds(datetime.fromisoformat(rows[day]['reference_close_utc']))
    decisions.append({'day':terminal,'formation':previous,'known_ns':k,'decision_ns':k+60*10**9,
        'open_ns':close(terminal),'formation_close_ns':close(previous),'kind':'REFERENCE','instructions':{leg:{'kind':'EXIT'} for leg in LEGS}})
    return {'profile':{'kind':'REFERENCE_TARGETS','legs':list(LEGS),'end':terminal}, 'symbols':['VTI'],
        'prices':{day:{'VTI':{'close_micro':market['prices_micro'][day]['VTI']}} for day in days},
        'grid':[{'date':day,'nominal_ns':close(day),'sample_ns':close(day)+1000,
                 'initial':i==0,'terminal':day==terminal} for i,day in enumerate(grid['nav_dates'])],
        'decisions':decisions,'signals':signals,'actual_feature_counts':counts,
        'curve_context':market['curve_context'],'capture_consumed_sizing':True,
        'price_evidence':{day:{'VTI':market['source_evidence'][day]['VTI']} for day in days},'quote_basis':'SYNTHETIC_VENDOR_ADJUSTED_REFERENCE_UNIT',
        'clock_policy':'PINNED_REFERENCE_EARLY_CLOSE'}


def verify_plan(plan, profile, schedule, grid):
    """Pure saved-certificate check; never call original loader/planner/policy."""
    validate_profile(profile)
    selected = date_joins(plan['curve_context'], profile, schedule, {'FINAL':grid})
    require(len(plan['signals']) == len(selected) and len(plan['decisions']) == len(selected)+1 and
            plan['actual_feature_counts'] == expected_counts(len(selected)), 'CURVE_SAVED_COUNTS')
    for i, (j,w,event) in enumerate(zip(selected,plan['signals'],plan['decisions'])):
        require(w['join'] == j and w['seal_sha256'] == sha(canonical({k:v for k,v in w.items() if k!='seal_sha256'})),
                'CURVE_SAVED_WITNESS_SEAL')
        d,_,_=context(plan['curve_context'],profile['input_sha256'])
        require(w['macro_sha256']==d['macro_records_ref']['sha256'] and
                sha(w['source_row_raw'].encode())==w['row_sha256'] and
                len(w['source_row_raw'].encode())==j['byte_end_exclusive']-j['byte_start'] and
                decode(w['source_row_raw'].encode())==w['source_row'], 'CURVE_SAVED_RAW_ROW')
        row = w['source_row']; require(row['source_date']==j['source_date'] and row['historical_K'] is None and row['historical_available_at'] is None, 'CURVE_SAVED_ROW_DATE')
        spread = fraction(row['tokens']['BC_10YEAR'])-fraction(row['tokens']['BC_2YEAR'])
        require(w['spread'] == [str(spread.numerator),str(spread.denominator)] and
                w['targets'] == targets(int(spread>0)), 'CURVE_SAVED_EXACT_SUBTRACTION_TARGET')
        require(event['day']==j['execution_date'] and event['formation']==j['formation_date'] and
                (event['known_ns'],event['decision_ns'],event['open_ns']) ==
                (j['known_ns'],j['decision_ns'],j['close_ns']) and
                event['instructions']=={leg:{'kind':'TARGET','weights':w['targets'][leg],
                    'signal':{'kind':'TREASURY_CURVE','index':i,'witness_sha256':w['seal_sha256']}} for leg in LEGS},
                'CURVE_SAVED_DECISION')
    rows = {r['date']:r for r in schedule}; days=list(rows)
    close=lambda day:nanoseconds(datetime.fromisoformat(rows[day]['reference_close_utc']))
    require(plan['symbols']==['VTI'] and plan['profile']=={'kind':'REFERENCE_TARGETS','legs':list(LEGS),'end':grid['terminal']} and
            plan['grid']==[{'date':day,'nominal_ns':close(day),'sample_ns':close(day)+1000,
                'initial':i==0,'terminal':day==grid['terminal']} for i,day in enumerate(grid['nav_dates'])], 'CURVE_SAVED_GRID')
    terminal=plan['decisions'][-1];previous=days[days.index(grid['terminal'])-1]
    k=nanoseconds(datetime.fromisoformat(previous).replace(tzinfo=timezone.utc)+timedelta(days=1))
    require(terminal=={'day':grid['terminal'],'formation':previous,'known_ns':k,'decision_ns':k+60*10**9,
        'open_ns':close(grid['terminal']),'formation_close_ns':close(previous),'kind':'REFERENCE','instructions':{leg:{'kind':'EXIT'} for leg in LEGS}}, 'CURVE_SAVED_EXIT')


def diagnose_curve(tape, schedule, prices, *, subperiods=()):
    from .scheduled_fixed import diagnose_fixed, _fixed_drawdown, _fixed_exposure
    from .scheduled_diagnostics import _nav, evaluate_segment, _unavailable
    result = diagnose_fixed(tape,schedule,prices)
    result['schema']='polar.curve-saved-diagnostics/1'
    result['subperiod_semantics']='SAVED_NAV_ANCHOR_THEN_NEXT_SAVED_RETURN'
    nav,reason=_nav(tape);segments=[];indices={r['date']:i for i,r in enumerate(nav)} if not reason else {}
    for anchor,last in subperiods:
        info={'requested_initial_anchor':anchor,'last_return_date':last}
        if anchor not in indices or last not in indices or indices[anchor]>=indices[last]:
            segments.append(_unavailable(reason or 'SAVED_NAV_ANCHOR_OR_END_MISSING',**info));continue
        a,b=indices[anchor],indices[last];segment=evaluate_segment(tape,nav[a+1]['date'],last)
        require(segment['status']!='OK' or segment['initial_date']==anchor,'CURVE_SAVED_ANCHOR_MAPPING')
        segment.update(info)
        if segment['status']=='OK':
            segment['drawdown']=_fixed_drawdown(nav[a:b+1]);segment['exposure']=_fixed_exposure(nav[a:b+1],prices)
        segments.append(segment)
    result['subperiods']=segments
    return result


def verify_consumed_operands(plan, simulation):
    """Check saved actual call-site operands; never reconstruct a missing witness."""
    from .obs158_math import cent_round_micro
    from .ci_research import fee_cents
    require(plan.get('capture_consumed_sizing') is True and
            {leg['id'] for leg in simulation['legs']}==set(LEGS), 'CURVE_CONSUMED_WITNESSES_REQUIRED')
    cost=plan['cost_profile'];events={d['day']:d for d in plan['decisions']}
    for leg in simulation['legs']:
        fills=leg['fills']
        require(fills==sorted(fills,key=lambda f:f['at_ns']), 'CURVE_SAVED_FILL_ORDER')
        def before(instant):
            cash=10000000;held={'VTI':0}
            for f in fills:
                if f['at_ns']>=instant:break
                require(f['symbol']=='VTI' and f['side'] in ('BUY','SELL') and
                        f['fee_cents']==fee_cents(f['q'],f['price_micro'],cost_profile=cost) and
                        f['settled_cents']==cent_round_micro(f['q']*f['price_micro']), 'CURVE_SAVED_FILL_MONEY')
                sign=1 if f['side']=='BUY' else -1;held['VTI']+=sign*f['q']
                cash-=sign*f['settled_cents']+f['fee_cents']
                require(cash==f['cash_after_cents'] and cash>=0 and held['VTI']>=0,'CURVE_SAVED_FILL_STATE')
            return cash,held
        require(len(leg['intents'])==len(events),'CURVE_CONSUMED_INTENT_COUNT')
        intents={i['day']:i for i in leg['intents']}
        for day,d in events.items():
            i=intents[day];instruction=d['instructions'][leg['id']]
            require(i['decision_ns']==d['decision_ns'] and i['instruction_kind']==instruction['kind'] and
                    i['decision_id']==leg['id']+'/'+day,'CURVE_CONSUMED_DECISION_ID')
            if instruction['kind']=='EXIT':
                require(i['sizing_witness'] is None and i['sizing_status']=='NOT_APPLICABLE_EXIT', 'CURVE_EXIT_NO_FABRICATED_SIZING')
                continue
            w=i['sizing_witness'];cash,held=before(i['decision_ns']);prices={'VTI':plan['prices'][d['formation']]['VTI']['close_micro']}
            require(w['schema']=='polar.target-sizing-witness/1' and w['cash_cents']==cash and w['holdings']==held and
                    w['eligible_prices_micro']==prices and w['weights']==instruction['weights'] and
                    w['nav_cents']==cash+sum(cent_round_micro(held[s]*prices[s]) for s in held) and
                    w['lot_size']==1 and w['quantity_unit']=='WHOLE_SYNTHETIC_REFERENCE_UNIT_NOT_RAW_SHARE' and
                    w['eligible_quote']=={'date':d['formation'],'at_ns':d['formation_close_ns'],
                        'source_identity':plan['price_evidence'][d['formation']]},'CURVE_CONSUMED_D_OPERANDS')
            require(w['targets']==i['targets']=={s:w['nav_cents']*10000*pair[0]//(prices[s]*pair[1])
                    for s,pair in instruction['weights'].items()}, 'CURVE_CONSUMED_TARGET_FLOOR')
        require(len(leg['orders'])==2*len(events),'CURVE_CONSUMED_ROUTE_COUNT')
        for o in leg['orders']:
            w=o['consumed_operands'];day=w['quote_day'];d=events[day];cash,held=before(o['at_ns']);p=plan['prices'][day]['VTI']['close_micro']
            target=intents[day]['targets']['VTI'];desired=max(held['VTI']-target,0) if o['side']=='SELL' else max(target-held['VTI'],0)
            require(o['id']==leg['id']+'/'+day+'/'+o['side']+'/VTI' and o['symbol']=='VTI' and
                    o['at_ns']==d['open_ns']+(100 if o['side']=='SELL' else 200) and
                    w['decision_id']==leg['id']+'/'+day and w['target']==target and w['holdings_before']==held and
                    w['cash_before_cents']==cash and w['price_micro']==p and w['quote_at_ns']==d['open_ns'] and
                    w['cost_profile']==cost and w['desired_delta']==o['intended_quantity']==desired,
                    'CURVE_CONSUMED_ROUTE_OPERANDS')
            q=o['routed_quantity']
            if o['side']=='BUY':
                a=w['affordability']
                require(a['schema']=='polar.affordability-witness/1' and a['desired']==desired and
                        a['price_micro']==p and a['cash_cents']==a['effective_spend_cap_cents']==cash and
                        a['budget_cents_input'] is None and a['cost_profile']==cost and a['returned_quantity']==q and
                        0<=q<=desired and cent_round_micro(q*p)+fee_cents(q,p,cost_profile=cost)<=cash and
                        (q==desired or cent_round_micro((q+1)*p)+fee_cents(q+1,p,cost_profile=cost)>cash),
                        'CURVE_CONSUMED_AFFORDABLE_BOUND')
            else:require(q==min(desired,held['VTI']) and w['affordability'] is None,'CURVE_CONSUMED_SELL_BOUND')
            require(o['reason']==('ZERO_DELTA_NO_ORDER' if desired==0 else 'FEE_AWARE_BUDGET_CAP' if q<desired else None),
                    'CURVE_CONSUMED_ROUTE_REASON')
    return {'status':'VERIFIED_CONSUMED_OPERANDS','source_calls':0,'policy_calls':0,'native_calls':0,'store_writes':0}

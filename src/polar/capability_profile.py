"""Pure fixed score/target/allocation/metric seams. No model imports or fitting."""
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from fractions import Fraction
import json
import math
import re
import struct

from .allocation import Snapshot, Position, Target, Mark, allocate
from .rank_weights import RankWeightRequest, ScorePanel, ScoreRow, CallLimits, map_rank_weights
from .capability_contract import (CapabilityError, require, SYMBOLS, TOKENS, MAPPING, METHODS, ACCOUNTS,
    PROFILE_ID, D, I, CLOSE_DATES, OPEN_DATES, NumberToken, canonical, digest, validate, cents,
    money, rational, fraction, weight, ns, microtime, envelope, decimal_money)


def identity(symbol):
    require(symbol in SYMBOLS,'MAPPING_MISMATCH')
    return dict(MAPPING[SYMBOLS.index(symbol)])


def decimal_fraction(token):
    require(type(token) in (str,NumberToken) and len(token)<=1024 and
            re.fullmatch(r'-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]+)?',token),
            'SCORE_REPRESENTATION')
    value=Decimal(token)
    require(value.is_finite(),'SCORE_REPRESENTATION')
    sign,digits,exponent=value.as_tuple()
    require(abs(exponent)<=1024 and len(digits)<=1024,'SCORE_REPRESENTATION')
    n=0
    for digit in digits:
        n=n*10+digit
    if sign:n=-n
    return Fraction(n*10**max(exponent,0),10**max(-exponent,0))


def token_matches_binary64(token,value,bits):
    """Verify round-nearest/ties-even cell without restoring from decimal text."""
    exact=decimal_fraction(token)
    encoded=int(bits,16)
    if value==0.0:
        require(token.startswith('-')==bool(encoded>>63),'SCORE_REPRESENTATION')
    center=Fraction(*value.as_integer_ratio())
    previous=math.nextafter(value,-math.inf)
    following=math.nextafter(value,math.inf)
    low=(center+Fraction(*previous.as_integer_ratio()))/2 if math.isfinite(previous) else center-(Fraction(*following.as_integer_ratio())-center)/2
    high=(center+Fraction(*following.as_integer_ratio()))/2 if math.isfinite(following) else center+(center-Fraction(*previous.as_integer_ratio()))/2
    even=encoded&1==0
    require((low<=exact<=high if even else low<exact<high),'SCORE_REPRESENTATION')


def restore(entry,method):
    require(type(entry) is dict and method in METHODS,'SCORE_REPRESENTATION')
    bits=entry.get('binary64_bits_be');text=entry.get('binary64_hex')
    require(type(bits) is str and re.fullmatch(r'[0-9a-f]{16}',bits) and
            type(text) is str and len(text)<=64,'SCORE_REPRESENTATION')
    value=struct.unpack('>d',bytes.fromhex(bits))[0]
    try: by_hex=float.fromhex(text)
    except (ValueError,OverflowError):raise CapabilityError('SCORE_REPRESENTATION') from None
    require(math.isfinite(value) and math.isfinite(by_hex) and
            struct.pack('>d',by_hex).hex()==bits,'SCORE_REPRESENTATION')
    token=entry.get('value')
    require(type(token) in (NumberToken,int) and type(token) is not bool,'SCORE_REPRESENTATION')
    token_matches_binary64(str(token),value,bits)
    if method not in METHODS[:2]:
        token_matches_binary64(entry.get('original_json_numeric_token'),value,bits)
    # Raw REV's input_RET5 token is NOT the negated output's representation.
    return value


def targets(score_rows):
    require(type(score_rows) is list and len(score_rows)==4,'SCORE_COHORT_MISMATCH')
    by_key={}
    for row in score_rows:
        require(type(row) is dict and row.get('key') in TOKENS and
                row.get('source_witness')==SYMBOLS[TOKENS.index(row['key'])] and
                row['key'] not in by_key and set(row.get('scores',{}))==set(METHODS),'SCORE_COHORT_MISMATCH')
        require(row.get('D')==D and ns(row.get('I_D'))==ns(I) and ns(row.get('K'))<=ns(D),'CLOCK_ORDER')
        by_key[row['key']]=row
    require(set(by_key)==set(TOKENS),'SCORE_COHORT_MISMATCH')
    restored={method:tuple(ScoreRow(token,restore(by_key[token]['scores'][method],method))
                           for token in TOKENS) for method in METHODS}
    # Exactly one mapper call per full packet; references are separate operators.
    result=map_rank_weights(RankWeightRequest('COMPLETE',METHODS,TOKENS,
        tuple(ScorePanel(m,restored[m]) for m in METHODS),(),Decimal('0.2'),CallLimits(4,5,20,1),None,None))
    require(result.status=='FORMED' and result.N==4 and result.k==1 and
            result.unavailable_method_ids==() and len(result.methods)==5,'MAPPER_RESULT_INVALID')
    mapped={row.method_id:row for row in result.methods}
    require(set(mapped)==set(METHODS),'METHOD_JOIN_MISMATCH')
    def encode_target(t):return {'instrument_id':t.instrument_id,'weight':weight(t.weight)}
    methods=[{'method_id':m.method_id,'selected_ids':list(m.selected_ids),
              'targets':[encode_target(t) for t in m.targets],
              'target_cash_weight':weight(m.target_cash_weight),'constant_score_tie':m.constant_score_tie}
             for m in result.methods]
    raw={'status':result.status,'reason_codes':list(result.reason_codes),'primary_reason':result.primary_reason,
         'methods':methods,'N':result.N,'k':result.k,'unavailable_method_ids':[],
         'formation_ref':result.formation_ref,'definition_ref':result.definition_ref}
    accounts=[]
    for account in ACCOUNTS:
        if account in mapped:
            rows=mapped[account].targets;cash=mapped[account].target_cash_weight;origin='MAPPER';method=account
        elif account=='REF_EW4_CAP':
            rows=tuple(Target(t,Decimal('0.2')) for t in TOKENS);cash=Decimal('0.2');origin='CAPPED_FULL_COHORT_REFERENCE';method=None
        else:
            rows=();cash=Decimal(1);origin='PURE_CASH_REFERENCE';method=None
        accounts.append({'account_id':account,'origin':origin,'method_id':method,
                         'targets':[{**identity(SYMBOLS[TOKENS.index(t.instrument_id)]),'weight':weight(t.weight)}
                                    for t in rows],'target_cash_weight':weight(cash)})
    payload={'D':D,'I':I,'mapper_result':raw,'accounts':accounts}
    validate(payload,'targets_payload')
    return payload


def allocation(account,phase,Q,cash,held,quotes,target_rows):
    """Exact public allocator snapshot; quotes retain event time separately."""
    require(account in ACCOUNTS and phase in ('entry','exit') and type(Q) is int,'ALLOCATION_DOMAIN')
    require(type(cash) is int and cash>=0 and set(held)==set(SYMBOLS) and
            all(type(v) is int and 0<=v<=1000000 for v in held.values()),'UNEXPECTED_ACCOUNT_STATE')
    require(set(quotes)==set(SYMBOLS) and
            all(quotes[s]['quote_event_ns']==str(Q+i) for i,s in enumerate(SYMBOLS)),
            'QUOTE_PHASE_MISMATCH')
    require(phase!='entry' or cash==10000000 and not any(held.values()),'UNEXPECTED_ACCOUNT_STATE')
    snapshot_at=Q+1000;asof=datetime.fromisoformat(microtime(snapshot_at).replace('Z','+00:00'))
    selected=target_rows if phase=='entry' else []
    for row in selected:
        require(all(row.get(k)==v for k,v in identity(row.get('source_symbol')).items()),'MAPPING_MISMATCH')
    requested=tuple(Target(r['opportunity_token'],Decimal(r['weight'])) for r in selected)
    positions=tuple(Position(TOKENS[i],held[s]) for i,s in enumerate(SYMBOLS) if held[s])
    names={p.instrument_id for p in positions}|{t.instrument_id for t in requested}
    marks=tuple(Mark(t,Decimal(quotes[SYMBOLS[TOKENS.index(t)]]['price']),'USD',asof) for t in sorted(names))
    snapshot=Snapshot(Decimal(money(cash)),'USD',asof,positions,requested,marks)
    try:result=allocate(snapshot,max_names=4)
    except ValueError:raise CapabilityError('ALLOCATION_DOMAIN') from None
    rows=[];orders=[]
    for row in result.rows:
        require(0<=row.desired_quantity<=1000000 and 0<=row.current_quantity<=1000000
                and abs(row.delta)<=1000000,'NATIVE_REPRESENTATION')
        require(row.delta>=0 if phase=='entry' else row.delta<=0,'UNEXPECTED_ACCOUNT_STATE')
        rows.append({'instrument_id':row.instrument_id,'current_quantity':row.current_quantity,
                     'target_weight':weight(row.target_weight),'mark':decimal_money(row.mark),
                     'desired_quantity':row.desired_quantity,'delta':row.delta})
        if row.delta:
            symbol=SYMBOLS[TOKENS.index(row.instrument_id)]
            orders.append({**identity(symbol),'side':'BUY' if row.delta>0 else 'SELL',
                           'quantity':abs(row.delta),'price':quotes[symbol]['price'],'source':quotes[symbol]['source']})
    raw={'currency':result.currency,'as_of':microtime(snapshot_at),
         'marked_nav':decimal_money(result.marked_nav),
         'total_target_weight':weight(result.total_target_weight),
         'allocated_value':decimal_money(result.allocated_value),
         'residual_cash':decimal_money(result.residual_cash),
         'rows':rows,'method':result.method,'financial_verdict':result.financial_verdict}
    snapshot_row={'currency':'USD','as_of':microtime(snapshot_at),'cash':money(cash),
        'positions':[{**identity(s),'quantity':held[s]} for s in SYMBOLS if held[s]],
        'targets':[{'instrument_id':t.instrument_id,'weight':weight(t.weight)} for t in requested],
        'marks':[quotes[SYMBOLS[TOKENS.index(t)]] for t in sorted(names)]}
    output={'phase':phase,'boundary':'O1' if phase=='entry' else 'O6','nominal_ns':str(Q),
            'snapshot_ns':str(snapshot_at),'snapshot':snapshot_row,'allocation':raw,
            'domain_checks':{n:'PASS' for n in ('expected_state','exact_mark_union','positive_cent_prices','native_representation','single_side_only')}}
    validate(output,'allocation_phase')
    return output,orders


def evaluate(account,samples,events):
    """Canonical cents/rational accounting from actual matched native receipts."""
    require(account in ACCOUNTS and len(samples)==7,'MISSING_SAMPLE')
    navs=[];concentrations=[];by_order={};fills=[];gross=0;fees=0
    running_cash=10000000;running_held={s:0 for s in SYMBOLS}
    routes={'entry':0,'exit':0};seen_exit=False
    for sequence,event in enumerate(events):
        validate(event,'event')
        require(event['sequence']==sequence,'ORDER_SEQUENCE_MISMATCH')
        symbol=event['source_symbol']
        require(all(event[k]==v for k,v in identity(symbol).items()),'MAPPING_MISMATCH')
        phase=event['phase']
        Q=ns(OPEN_DATES[0 if phase=='entry' else 1]+'T14:30:00.000000Z')
        require(int(event['logical_route_ns'])==Q+1000*(event['route_sequence']+1)
                and event['native_event_ns']==event['logical_route_ns']
                and event['native_init_ns']==event['logical_route_ns'],'ORDER_SEQUENCE_MISMATCH')
        require(event['side']==('BUY' if phase=='entry' else 'SELL')
                and event['logical_order_id']==account+'/'+phase+'/'+str(event['route_sequence']),
                'ORDER_SEQUENCE_MISMATCH')
        if event['kind']=='ORDER_SUBMITTED':
            require(not by_order and event['logical_order_id'] not in by_order,'ORDER_SEQUENCE_MISMATCH')
            require(phase!='entry' or not seen_exit,'ORDER_SEQUENCE_MISMATCH')
            seen_exit=seen_exit or phase=='exit'
            routes[phase]+=1
            require(event['route_sequence']==routes[phase]
                    and cents(event['cash_before'])==running_cash
                    and event['held_before']==running_held[symbol],'METRIC_MISMATCH')
            by_order[event['logical_order_id']]=event
        else:
            require(event['kind']=='ORDER_FILLED' and event['logical_order_id'] in by_order,'NATIVE_FILL_MISMATCH')
            order=by_order.pop(event['logical_order_id'])
            require(all(event[k]==order[k] for k in ('phase','route_sequence','opportunity_token','source_symbol',
                        'simulated_instrument_id','side','logical_route_ns','quantity')),'NATIVE_FILL_MISMATCH')
            require(event['native_event_ns']==event['logical_route_ns'] and
                    cents(event['fill_price'],positive=True)==cents(order['price_reference'],positive=True),'NATIVE_FILL_MISMATCH')
            require(event['fee_receipt']['amount']=='1.00' and event['fee_receipt']['currency']=='USD'
                    and event['fee_receipt']['native_receipt_kind']=='ORDER_FILLED_COMMISSION'
                    and event['fee_receipt']['logical_fee_id']==event['logical_order_id']+'/fee','FEE_RECEIPT_MISMATCH')
            require(event['quantity']>0 and event['logical_fill_id']==event['logical_order_id']+'/fill/1','NATIVE_FILL_MISMATCH')
            delta=event['quantity']*cents(event['fill_price'],positive=True)
            expected=cents(order['cash_before'])+(-delta if event['side']=='BUY' else delta)-100
            held=order['held_before']+(event['quantity'] if event['side']=='BUY' else -event['quantity'])
            require(expected>=0 and held>=0 and cents(event['cash_after'])==expected and event['held_after']==held,'METRIC_MISMATCH')
            running_cash=expected;running_held[symbol]=held
            gross+=delta;fees+=100;fills.append(event)
    require(not by_order,'PENDING_ORDER')
    for index,row in enumerate(samples):
        validate(row,'sample')
        require(row['sample_index']==index and row['logical_sample_id']==account+'/'+str(index),'MISSING_SAMPLE')
        expected_role='INITIAL' if index==0 else ('TERMINAL' if index==6 else 'CLOSE')
        nominal=ns(I) if index==0 else (ns(OPEN_DATES[1]+'T14:30:00.000000Z') if index==6
                                      else ns(CLOSE_DATES[index-1]+'T21:00:00.000000Z'))
        require(row['role']==expected_role and row['effective_nominal_ns']==str(nominal)
                and row['native_sample_ns']==str(nominal+10000),'MISSING_SAMPLE')
        sample_cash=10000000;sample_held={s:0 for s in SYMBOLS}
        for fill in fills:
            if int(fill['native_event_ns'])<int(row['native_sample_ns']):
                sample_cash=cents(fill['cash_after'])
                sample_held[fill['source_symbol']]=fill['held_after']
        require(cents(row['cash'])==sample_cash,'METRIC_MISMATCH')
        exposure=0;parts=[]
        for symbol,position in zip(SYMBOLS,row['positions']):
            require(all(position[k]==v for k,v in identity(symbol).items()),'MAPPING_MISMATCH')
            qty=position['quantity']
            require(qty==sample_held[symbol],'METRIC_MISMATCH')
            if qty:
                require(position['mark_requirement']=='ADMITTED_HELD_MARK' and
                        position['mark'] is not None and position['mark_source'] is not None,'MISSING_HELD_MARK')
                require(index in range(1,6) and position['mark_event_ns']==str(nominal+SYMBOLS.index(symbol))
                        and position['mark_source']['field']=='c'
                        and position['mark_source']['role']=='EX_POST_REFERENCE_CLOSE','MISSING_HELD_MARK')
                amount=qty*cents(position['mark'],positive=True)
            else:
                require(position['mark_requirement']=='NOT_REQUIRED_ZERO_QUANTITY' and
                        position['mark'] is position['mark_event_ns'] is position['mark_source'] is None,'MISSING_HELD_MARK')
                amount=0
            exposure+=amount;parts.append(amount)
        nav=cents(row['cash'])+exposure
        require(nav>0 and cents(row['nav'])==nav and cents(row['native_exposure_usd'])==exposure
                and fraction(row['nav_exact_usd'])==Fraction(nav,100),'INVALID_NAV')
        navs.append(nav);concentrations.extend(Fraction(p,nav) for p in parts)
    require(navs[0]==10000000 and not any(p['quantity'] for p in samples[0]['positions']) and
            not any(p['quantity'] for p in samples[-1]['positions']) and
            cents(samples[-1]['cash'])==navs[-1],'UNEXPECTED_ACCOUNT_STATE')
    peak=navs[0];drawdown=Fraction()
    for nav in navs:
        peak=max(peak,nav);drawdown=max(drawdown,Fraction(peak-nav,peak))
    result={'account_id':account,'terminal_cash_usd':money(navs[-1]),'terminal_nav_usd':money(navs[-1]),
        'terminal_nav_exact_usd':rational(Fraction(navs[-1],100)),
        'terminal_net_return':rational(Fraction(navs[-1]-10000000,10000000)),
        'fees_usd':money(fees),'fees_exact_usd':rational(Fraction(fees,100)),'filled_order_count':len(fills),
        'gross_notional_usd':money(gross),'gross_notional_exact_usd':rational(Fraction(gross,100)),
        'sampled_max_drawdown':rational(drawdown),'sampled_max_single_name_concentration':rational(max(concentrations))}
    return result

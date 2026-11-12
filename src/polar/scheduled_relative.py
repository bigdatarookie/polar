"""Exact lagged relative ranking on the existing shared target-ledger plan."""
from datetime import datetime,date,time,timedelta
from fractions import Fraction
from .ci_research import require
from .gym_contract import canonical,sha
from .reference_ridge_plan import nanoseconds


class RelativeSignalError(ValueError):
    def __init__(self,reason,events):
        super().__init__(reason);self.events=events


def expected_counts(n):
    return {'score_calls':3*n,'completed_scores':3*n,'operand_reads':6*n,
            'rank_calls':n,'completed_decisions':n}


def validate_profile(p):
    policy=p['policy'];symbols=p['symbols'];legs=p['legs']
    require(type(policy) is dict and set(policy)=={'kind','lookback','skip','full_symbol','drawdown_peak'} and
            policy['kind']=='RELATIVE_MOMENTUM_EXACT_LAGS' and type(policy['lookback']) is int and policy['lookback']==252 and
            type(policy['skip']) is int and policy['skip']==21 and policy['full_symbol'] in symbols and
            policy['drawdown_peak']=='LATEST_EQUAL_PEAK' and len(symbols)==3 and p['decision_delay_seconds']==60,
            'SCHEDULED_RELATIVE_POLICY')
    require(len(legs)==4 and {l['rule'] for l in legs}=={'RELATIVE_MOMENTUM','EQUAL_WEIGHT','FULL','CASH'} and
            all(l['scale']==[1,1] for l in legs),'SCHEDULED_RELATIVE_LEGS')
    roles={l['rule']:l['id'] for l in legs}
    require(p['primary_strategy']==roles['RELATIVE_MOMENTUM'] and p['primary_benchmark']==roles['EQUAL_WEIGHT'],
            'SCHEDULED_RELATIVE_ROLES')
    require(p['cost_scenarios']==[{'id':'BASE','cost_profile':{'flat_cents':100,'bps':10}},
            {'id':'COST_STRESS','cost_profile':{'flat_cents':200,'bps':20}}] and
            p['uncertainty']=={'kind':'RELATIVE_PAIRED_DESCRIPTIVE','block':63,'replicates':1000,'seed':37004},
            'SCHEDULED_RELATIVE_SCENARIOS')
    conditions=p['criteria']
    require(len(conditions)==5 and {c['kind'] for c in conditions}==
            {'TERMINAL_GT','SR_DELTA_GE','DRAWDOWN_LE','VOL_LE','POSITIVE_GROWTH'} and
            all(c['left_id']==roles['RELATIVE_MOMENTUM'] and
                (c['kind']=='POSITIVE_GROWTH' or c['right_id']==roles['EQUAL_WEIGHT']) and
                (c['kind']!='SR_DELTA_GE' or c['threshold']=='0.10') for c in conditions),
            'SCHEDULED_RELATIVE_CRITERIA')
    require(len(p['subperiods'])<=3,'SCHEDULED_RELATIVE_ERAS')


def validate_clock_metadata(schedule,grids,tz):
    """All formation and terminal clocks, before price reads/start/scoring."""
    rows={r['date']:r for r in schedule};days=list(rows)
    for grid in grids.values():
        events=[(e['signal_date'],e['execution_date']) for e in grid['decisions']]
        terminal=grid['terminal'];events.append((days[days.index(terminal)-1],terminal))
        for formation,entry in events:
            known=datetime.combine(date.fromisoformat(formation)+timedelta(days=1),time(),tzinfo=tz)
            decision=known+timedelta(seconds=60)
            close=datetime.fromisoformat(rows[entry]['reference_close_utc'])
            require(known.utcoffset()==timedelta(0) and nanoseconds(known)<nanoseconds(decision)<nanoseconds(close),
                    'SCHEDULED_RELATIVE_PREFLIGHT_CLOCK')


def _weights(profile,winner):
    symbols=profile['symbols'];full=profile['policy']['full_symbol']
    return {l['id']:{s:([1,3] if l['rule']=='EQUAL_WEIGHT' else
                       [int(s==(winner if l['rule']=='RELATIVE_MOMENTUM' else full)),1]
                       if l['rule'] in ('RELATIVE_MOMENTUM','FULL') else [0,1]) for s in symbols}
            for l in profile['legs']}


def plan_phase(market,profile,grid,tz):
    """Only invoked after durable start. Save scores once for both cost accounts."""
    validate_profile(profile)
    symbols=profile['symbols'];days=market['dates'];rows={r['date']:r for r in market['schedule']}
    require(market['symbols']==symbols,'SCHEDULED_RELATIVE_SYMBOLS')
    validate_clock_metadata(market['schedule'],{'FINAL':grid},tz)
    close=lambda d:nanoseconds(datetime.fromisoformat(rows[d]['reference_close_utc']))
    signals=[];decisions=[];counts=expected_counts(0)
    for event in grid['decisions']:
        formation,entry=event['signal_date'],event['execution_date'];index=days.index(formation)
        witness={'schema':'polar.exact-relative-score-witness/1','input_sha256':profile['input_sha256'],
                 'formation':formation,'execution':entry,'formation_index':index,'operands':[]}
        try:
            require(index>=252,'SCHEDULED_RELATIVE_HISTORY')
            a,b=days[index-252],days[index-21];scores={}
            for symbol in symbols:
                counts['score_calls']+=1
                operand={'symbol':symbol,'start_date':a,'end_date':b};witness['operands'].append(operand)
                for name,d in [('start_micro',a),('end_micro',b)]:
                    value=market['prices_micro'][d][symbol];counts['operand_reads']+=1
                    require(type(value) is int and value>0,'SCHEDULED_RELATIVE_OPERAND')
                    operand[name]=value
                score=Fraction(operand['end_micro'],operand['start_micro'])-1
                operand['score']=[str(score.numerator),str(score.denominator)]
                scores[symbol]=score;counts['completed_scores']+=1
            counts['rank_calls']+=1
            rank=sorted(symbols,key=lambda s:(-scores[s],s));winner=rank[0]
            witness.update(rank=rank,winner=winner,operand_dates=[a,b]);counts['completed_decisions']+=1
        except (ValueError,KeyError,ArithmeticError) as exc:
            raise RelativeSignalError('SCHEDULED_RELATIVE_INVALID_OPERAND_OR_DOMAIN',{
                'completed_signals':signals,'failed_signal':witness,'actual_counts':dict(counts),'cause':str(exc)[:160]}) from exc
        witness['targets']=_weights(profile,winner)
        witness['seal_sha256']=sha(canonical(witness));signals.append(witness)
        known=datetime.combine(date.fromisoformat(formation)+timedelta(days=1),time(),tzinfo=tz)
        decision=known+timedelta(seconds=60)
        require(known.utcoffset()==timedelta(0) and nanoseconds(known)<nanoseconds(decision)<close(entry),'SCHEDULED_RELATIVE_CLOCK')
        weights=witness['targets']
        decisions.append({'day':entry,'formation':formation,'known_ns':nanoseconds(known),'decision_ns':nanoseconds(decision),
            'open_ns':close(entry),'kind':'REFERENCE','instructions':{l['id']:{'kind':'TARGET','weights':weights[l['id']],
                'signal':{'kind':'EXACT_RELATIVE_LAGS','signal_index':len(signals)-1,'witness_sha256':witness['seal_sha256']}} for l in profile['legs']}})
    terminal=grid['terminal'];previous=days[days.index(terminal)-1]
    known=datetime.combine(date.fromisoformat(previous)+timedelta(days=1),time(),tzinfo=tz);decision=known+timedelta(seconds=60)
    require(nanoseconds(known)<nanoseconds(decision)<close(terminal),'SCHEDULED_RELATIVE_TERMINAL_CLOCK')
    decisions.append({'day':terminal,'formation':previous,'known_ns':nanoseconds(known),'decision_ns':nanoseconds(decision),
        'open_ns':close(terminal),'kind':'REFERENCE','instructions':{l['id']:{'kind':'EXIT'} for l in profile['legs']}})
    return {'profile':{'kind':'REFERENCE_TARGETS','legs':[l['id'] for l in profile['legs']],'end':terminal},
        'symbols':symbols,'prices':{d:{s:{'close_micro':market['prices_micro'][d][s]} for s in symbols} for d in days},
        'grid':[{'date':d,'nominal_ns':close(d),'sample_ns':close(d)+1000,'initial':i==0,'terminal':d==terminal} for i,d in enumerate(grid['nav_dates'])],
        'decisions':decisions,'signals':signals,'actual_signal_counts':dict(counts),
        'quote_basis':'SYNTHETIC_VENDOR_ADJUSTED_REFERENCE_UNIT','clock_policy':'PINNED_REFERENCE_EARLY_CLOSE'}


def verify_plan(plan,profile,schedule,grid):
    """Validate saved certificates/joins; no score routine, sort, source or policy run."""
    days=[r['date'] for r in schedule];rows={r['date']:r for r in schedule};symbols=profile['symbols']
    require(plan['symbols']==symbols and [r['date'] for r in plan['grid']]==grid['nav_dates'],'SCHEDULED_RELATIVE_SAVED_GRID')
    signals=plan['signals'];decisions=plan['decisions']
    require(len(signals)==len(grid['decisions']) and [(e['formation'],e['day']) for e in decisions[:-1]]==
            [(e['signal_date'],e['execution_date']) for e in grid['decisions']],'SCHEDULED_RELATIVE_CALENDAR_BINDING')
    for index,row in enumerate(plan['grid']):
        close=nanoseconds(datetime.fromisoformat(rows[row['date']]['reference_close_utc']))
        require(row=={'date':row['date'],'nominal_ns':close,'sample_ns':close+1000,'initial':index==0,
                'terminal':row['date']==grid['terminal']},'SCHEDULED_RELATIVE_SAMPLE_CLOCK')
    for event in decisions:
        known=nanoseconds(datetime.fromisoformat(event['formation']+'T00:00:00+00:00')+timedelta(days=1))
        close=nanoseconds(datetime.fromisoformat(rows[event['day']]['reference_close_utc']))
        require(event['kind']=='REFERENCE' and event['known_ns']==known and event['decision_ns']==known+60000000000 and
                event['open_ns']==close and known<known+60000000000<close,'SCHEDULED_RELATIVE_SAVED_CLOCK')
    require(decisions[-1]['day']==grid['terminal'] and decisions[-1]['formation']==days[days.index(grid['terminal'])-1] and
            set(decisions[-1]['instructions'])=={l['id'] for l in profile['legs']},'SCHEDULED_RELATIVE_TERMINAL_BINDING')
    require(len(decisions)==len(signals)+1,'SCHEDULED_RELATIVE_EVENT_COUNT')
    require(plan['actual_signal_counts']==expected_counts(len(signals)),'SCHEDULED_RELATIVE_COUNT_BINDING')
    for k,(signal,event) in enumerate(zip(signals,decisions[:-1])):
        body={a:b for a,b in signal.items() if a!='seal_sha256'}
        require(sha(canonical(body))==signal['seal_sha256'],'SCHEDULED_RELATIVE_WITNESS_SEAL')
        index=days.index(event['formation']);require(index>=252,'SCHEDULED_RELATIVE_HISTORY')
        require(signal['input_sha256']==profile['input_sha256'] and signal['formation']==event['formation'] and
                signal['execution']==event['day'] and signal['formation_index']==index and
                signal['operand_dates']==[days[index-252],days[index-21]],'SCHEDULED_RELATIVE_CUTOFF_BINDING')
        require([o['symbol'] for o in signal['operands']]==symbols,'SCHEDULED_RELATIVE_OPERANDS')
        certificates={}
        for operand in signal['operands']:
            symbol=operand['symbol'];a,b=signal['operand_dates']
            require(operand['start_date']==a and operand['end_date']==b and
                    operand['start_micro']==plan['prices'][a][symbol]['close_micro'] and
                    operand['end_micro']==plan['prices'][b][symbol]['close_micro'],'SCHEDULED_RELATIVE_OPERAND_BINDING')
            start,end=operand['start_micro'],operand['end_micro'];num,den=map(int,operand['score'])
            require(type(start) is int and type(end) is int and start>0 and end>0 and den>0 and
                    num*start==(end-start)*den,'SCHEDULED_RELATIVE_SCORE_CERTIFICATE')
            certificates[symbol]=(num,den)
        rank=signal['rank'];require(len(rank)==len(symbols) and set(rank)==set(symbols) and signal['winner']==rank[0],
                                    'SCHEDULED_RELATIVE_RANK_SET')
        for a,b in zip(rank,rank[1:]):
            an,ad=certificates[a];bn,bd=certificates[b]
            require(an*bd>bn*ad or an*bd==bn*ad and a<b,'SCHEDULED_RELATIVE_RANK_CERTIFICATE')
        weights=signal['targets']
        require(set(weights)=={l['id'] for l in profile['legs']},'SCHEDULED_RELATIVE_SAVED_TARGET_SET')
        for leg in profile['legs']:
            require(set(weights[leg['id']])==set(symbols),'SCHEDULED_RELATIVE_SAVED_TARGET_SYMBOLS')
            for symbol,value in weights[leg['id']].items():
                expected=([1,3] if leg['rule']=='EQUAL_WEIGHT' else [0,1] if leg['rule']=='CASH' else
                          [int(symbol==(signal['winner'] if leg['rule']=='RELATIVE_MOMENTUM' else profile['policy']['full_symbol'])),1])
                require(value==expected,'SCHEDULED_RELATIVE_SAVED_TARGET_CERTIFICATE')
        require(event['day']==rows[event['formation']]['next_reference_date'] and
                set(event['instructions'])==set(weights),'SCHEDULED_RELATIVE_INSTRUCTION_JOIN')
        for leg in profile['legs']:
            require(event['instructions'][leg['id']]=={'kind':'TARGET','weights':weights[leg['id']],
                'signal':{'kind':'EXACT_RELATIVE_LAGS','signal_index':k,'witness_sha256':signal['seal_sha256']}},'SCHEDULED_RELATIVE_TARGET_BINDING')
    require(all(i=={'kind':'EXIT'} for i in decisions[-1]['instructions'].values()),'SCHEDULED_RELATIVE_EXIT')
    return plan['actual_signal_counts']


def diagnose_relative(tape,schedule,*,subperiods=()):
    """Versioned latest-equal-peak recipe; eras retain generic FIRST_RETURN meaning."""
    from .scheduled_diagnostics import diagnose,_nav,_drawdown
    result=diagnose(tape,schedule,subperiods=subperiods)
    result['schema']='polar.relative-saved-diagnostics/1';result['peak_convention']='LATEST_EQUAL_RUNNING_PEAK'
    result['subperiod_semantics']='INCLUSIVE_FIRST_RETURN_WITH_PRECEDING_SAVED_NAV_ANCHOR'
    nav,reason=_nav(tape)
    if not reason:
        result['drawdown']=_drawdown(nav,latest_equal_peak=True)
        for segment in result['subperiods']:
            if segment['status']=='OK':
                selected=[r for r in nav if segment['initial_date']<=r['date']<=segment['last_return_date']]
                segment['drawdown']=_drawdown(selected,latest_equal_peak=True)
    return result

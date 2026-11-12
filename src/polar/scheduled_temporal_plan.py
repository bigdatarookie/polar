"""Single-asset temporal exposure on the shared scheduled ledger; no extra engine."""
from datetime import datetime,date,time,timedelta
from fractions import Fraction

from .ci_research import require
from .gym_contract import canonical,sha
from .reference_ridge_plan import nanoseconds
from .scheduled_temporal import estimate_temporal, verify_temporal_witness, TemporalEstimationError


def counts(witnesses):
    names=('estimator_calls','calibration_estimates','rolling_estimates','completed_estimates')
    return {k:sum(w.get('actual_counts',{}).get(k,0) for w in witnesses) for k in names}


def plan_phase(market,profile,grid,tz):
    symbol=profile['symbols'][0];days=market['dates'];rows={r['date']:r for r in market['schedule']}
    close=lambda d:nanoseconds(datetime.fromisoformat(rows[d]['reference_close_utc']))
    policy=profile['policy'];start,end=policy['calibration']
    labels=[d for d in days if start<=d<=end]
    require(len(labels)==1259 and labels[0]==start and labels[-1]==end and end<grid['initial'],
            'SCHEDULED_TEMPORAL_CALIBRATION_GRID')
    source={'input_sha256':profile['input_sha256'],'symbol':symbol}
    witnesses=[];signals=[]
    def estimate(labels,kind):
        try:
            answer=estimate_temporal([market['prices_micro'][d][symbol] for d in labels],labels,
                                     kind=kind,source_ref=source)
        except TemporalEstimationError as exc:
            exc.events={'completed_witnesses':witnesses,'failed_witness':exc.witness,
                        'actual_counts':counts(witnesses+[exc.witness])}
            raise
        witnesses.append(answer['witness']);return answer
    calibration=estimate(labels,'STATIC_CALIBRATION')
    decisions=[]
    for event in grid['decisions']:
        formation,entry=event['signal_date'],event['execution_date'];i=days.index(formation)
        require(i>=60 and days[i-60:i+1][-1]==formation,'SCHEDULED_TEMPORAL_LOOKBACK')
        rolling=estimate(days[i-60:i+1],'ROLLING_60')
        known=datetime.combine(date.fromisoformat(formation)+timedelta(days=1),time(),tzinfo=tz)
        decision=known+timedelta(seconds=1)
        require(nanoseconds(known)<nanoseconds(decision)<close(entry),'SCHEDULED_CLOCK')
        instructions={}
        for leg in profile['legs']:
            if leg['rule']=='CASH':instructions[leg['id']]={'kind':'HOLD'};continue
            weight=rolling['weight'] if leg['rule']=='TEMPORAL_VOL' else calibration['weight'] if leg['rule']=='STATIC_VOL' else Fraction(1)
            instructions[leg['id']]={'kind':'TARGET','weights':{symbol:[weight.numerator,weight.denominator]},
                                    'signal':{'kind':leg['rule'],'temporal_signal_index':len(signals)}}
        decisions.append({'day':entry,'formation':formation,'known_ns':nanoseconds(known),
            'decision_ns':nanoseconds(decision),'open_ns':close(entry),'kind':'REFERENCE','instructions':instructions})
        signals.append({'formation':formation,'execution':entry,'witness':rolling['witness']})
    terminal=grid['terminal'];previous=days[days.index(terminal)-1]
    known=datetime.combine(date.fromisoformat(previous)+timedelta(days=1),time(),tzinfo=tz)
    decision=known+timedelta(seconds=1)
    require(nanoseconds(known)<nanoseconds(decision)<close(terminal),'SCHEDULED_TERMINAL_CLOCK')
    decisions.append({'day':terminal,'formation':previous,'known_ns':nanoseconds(known),
        'decision_ns':nanoseconds(decision),'open_ns':close(terminal),'kind':'REFERENCE',
        'instructions':{leg['id']:{'kind':'EXIT'} for leg in profile['legs']}})
    return {'profile':{'kind':'REFERENCE_TARGETS','legs':[l['id'] for l in profile['legs']],'end':terminal},
        'symbols':[symbol],'prices':{d:{symbol:{'close_micro':market['prices_micro'][d][symbol]}} for d in days},
        'grid':[{'date':d,'nominal_ns':close(d),'sample_ns':close(d)+1000,'initial':i==0,'terminal':d==terminal}
                for i,d in enumerate(grid['nav_dates'])],
        'decisions':decisions,'signals':signals,'temporal_calibration':calibration['witness'],
        'actual_estimator_counts':counts(witnesses),'quote_basis':'SYNTHETIC_VENDOR_ADJUSTED_REFERENCE_UNIT',
        'clock_policy':'PINNED_REFERENCE_EARLY_CLOSE'}


def verify_plan(plan,profile,schedule):
    """Saved identity/projection validation, explicitly no re-estimation."""
    symbol=profile['symbols'][0];days=[r['date'] for r in schedule]
    source={'input_sha256':profile['input_sha256'],'symbol':symbol}
    calibration=plan['temporal_calibration'];signals=plan['signals']
    start,end=profile['policy']['calibration']
    expected=[d for d in days if start<=d<=end]
    require(calibration['labels']==expected and len(expected)==1259 and expected[0]==start and expected[-1]==end,
            'SCHEDULED_TEMPORAL_CALIBRATION_BINDING')
    witnesses=[calibration]+[s['witness'] for s in signals]
    require(calibration['kind']=='STATIC_CALIBRATION' and all(s['witness']['kind']=='ROLLING_60' for s in signals),
            'SCHEDULED_TEMPORAL_WITNESS_KINDS')
    for w in witnesses:
        require(w['price_operands_sha256']==sha(canonical([plan['prices'][d][symbol]['close_micro'] for d in w['labels']])),
                'SCHEDULED_TEMPORAL_OPERAND_BINDING')
        require(w['source_ref']==source and verify_temporal_witness(w)['status']=='OK','SCHEDULED_TEMPORAL_WITNESS')
    require(plan['actual_estimator_counts']==counts(witnesses),'SCHEDULED_TEMPORAL_COUNT_BINDING')
    require(len(plan['decisions'])==len(signals)+1 and end<plan['grid'][0]['date'],'SCHEDULED_TEMPORAL_DECISIONS')
    fraction=lambda w:Fraction(int(w['weight']['numerator']),int(w['weight']['denominator']))
    for event,signal in zip(plan['decisions'][:-1],signals):
        formation=event['formation'];idx=days.index(formation)
        require(signal['formation']==formation and signal['execution']==event['day'] and
                signal['witness']['labels']==days[idx-60:idx+1],'SCHEDULED_TEMPORAL_CUTOFF')
        require(set(event['instructions'])=={l['id'] for l in profile['legs']},'SCHEDULED_TEMPORAL_LEGS')
        for leg in profile['legs']:
            instruction=event['instructions'][leg['id']]
            if leg['rule']=='CASH':require(instruction=={'kind':'HOLD'},'SCHEDULED_TEMPORAL_CASH');continue
            w=fraction(signal['witness']) if leg['rule']=='TEMPORAL_VOL' else fraction(calibration) if leg['rule']=='STATIC_VOL' else Fraction(1)
            require(instruction['kind']=='TARGET' and instruction['weights']=={symbol:[w.numerator,w.denominator]},
                    'SCHEDULED_TEMPORAL_TARGET_BINDING')
    require(all(x=={'kind':'EXIT'} for x in plan['decisions'][-1]['instructions'].values()),'SCHEDULED_TEMPORAL_EXIT')

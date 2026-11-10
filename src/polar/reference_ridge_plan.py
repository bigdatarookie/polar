"""A's frozen monthly model/controls -> the shared next-close native plan."""
from datetime import datetime, timezone, timedelta
from fractions import Fraction
from .ci_research import require
from .research_learning import eligible_at, score_ridge

LEGS = ['RIDGE_TOP1_OR_CASH','MOM252_21_TOP1_OR_CASH','EW4_MONTHLY','CASH']


def nanoseconds(dt):
    require(dt.utcoffset() is not None,'REFERENCE_TIMESTAMP_ZONE')
    delta=dt.astimezone(timezone.utc)-datetime(1970,1,1,tzinfo=timezone.utc)
    return (delta.days*86400+delta.seconds)*10**9+delta.microseconds*1000


def weights_instruction(symbols, winner=None, equal=False, signal=None):
    return {'kind':'TARGET','weights':{s:[1,len(symbols)] if equal else [int(s==winner),1] for s in symbols},
            'signal':signal}


def ridge_phase_plan(market, fitted, grid_contract, tz):
    days=market['dates']; symbols=market['symbols']; schedules={r['date']:r for r in market['schedule']}
    initial,terminal=grid_contract['initial'],grid_contract['terminal']
    require(initial in days and terminal in days and initial<terminal,'RIDGE_PHASE_BOUNDARIES')
    selected=[d for d in days if initial<=d<=terminal]
    require(len(selected)==grid_contract['nav_points'] and len(selected)-1==grid_contract['returns'], 'RIDGE_PHASE_GRID')
    close=lambda d:nanoseconds(datetime.fromisoformat(schedules[d]['reference_close_utc']))
    grid=[{'date':d,'nominal_ns':close(d),'sample_ns':close(d)+1000,'initial':i==0,'terminal':d==terminal}
          for i,d in enumerate(selected)]
    decisions=[];forecasts=[]
    for day in days:
        if not initial<=day<terminal or schedules[day]['month_end_in_reference_range'] is not True:continue
        entry=schedules[day]['next_reference_date']
        if entry is None or entry>=terminal:continue # terminal liquidation overrides monthly rebalance
        known=eligible_at(day,tz);decision=known+timedelta(minutes=1)
        require(nanoseconds(known)<nanoseconds(decision)<close(entry),'RIDGE_PHASE_CLOCK')
        forecast=score_ridge(market,fitted,day,decision,tz);forecasts.append(forecast)
        index=days.index(day);mom={s:Fraction(market['prices_micro'][days[index-21]][s],
                                            market['prices_micro'][days[index-252]][s])-1 for s in symbols}
        winner=min(symbols,key=lambda s:(-mom[s],symbols.index(s)))
        winner=winner if mom[winner]>0 else None
        instructions={LEGS[0]:weights_instruction(symbols,forecast['selected_symbol'],signal=forecast),
            LEGS[1]:weights_instruction(symbols,winner,signal={'momentum':{s:[v.numerator,v.denominator] for s,v in mom.items()}}),
            LEGS[2]:weights_instruction(symbols,equal=True),LEGS[3]:{'kind':'HOLD'}}
        decisions.append({'day':entry,'formation':day,'known_ns':nanoseconds(known),
            'decision_ns':nanoseconds(decision),'open_ns':close(entry),'kind':'REFERENCE','instructions':instructions})
    require(len(decisions)==grid_contract['monthly_decisions'],'RIDGE_DECISION_GRID')
    previous=days[days.index(terminal)-1];known=eligible_at(previous,tz)
    require(nanoseconds(known)+60*10**9<close(terminal),'RIDGE_TERMINAL_CLOCK')
    decisions.append({'day':terminal,'formation':previous,'known_ns':nanoseconds(known),
        'decision_ns':nanoseconds(known)+60*10**9,'open_ns':close(terminal),'kind':'REFERENCE',
        'instructions':{leg:{'kind':'EXIT'} for leg in LEGS}})
    return {'profile':{'kind':'REFERENCE_TARGETS','legs':LEGS,'end':terminal},'symbols':symbols,
            'prices':{d:{s:{'close_micro':market['prices_micro'][d][s]} for s in symbols} for d in days},
            'grid':grid,'decisions':decisions,'forecasts':forecasts,
            'quote_basis':'SYNTHETIC_VENDOR_ADJUSTED_REFERENCE_UNIT','clock_policy':'PINNED_REFERENCE_EARLY_CLOSE'}

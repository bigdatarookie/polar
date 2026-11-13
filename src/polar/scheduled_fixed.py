"""Fixed rational weights on a declared annual calendar, no signal or estimator."""
from datetime import date,datetime,time,timedelta,timezone
from fractions import Fraction

from .ci_research import require
from .reference_ridge_plan import nanoseconds

CALENDAR='polar.prospective-fixed-allocation-calendar/1'


def validate_legs(legs,symbols):
    for leg in legs:
        require(type(leg) is dict and set(leg)=={'id','label','rule','weights'}
                and leg['rule'] in ('FIXED_WEIGHTS','CASH'),'SCHEDULED_FIXED_LEG')
        weights=leg['weights']
        require(type(weights) is dict and set(weights)==set(symbols),'SCHEDULED_FIXED_WEIGHTS')
        for pair in weights.values():
            require(type(pair) is list and len(pair)==2 and all(type(v) is int for v in pair)
                    and pair[0]>=0 and pair[1]>0,'SCHEDULED_FIXED_WEIGHTS')
        total=sum((Fraction(*p) for p in weights.values()),Fraction())
        require(total<=1 and (total==0 if leg['rule']=='CASH' else total>0),'SCHEDULED_FIXED_WEIGHTS')


def calendar_value(calendar,schedule):
    fields={'schema','parent_schedule','dates','initial_date','terminal_date','nav_points','returns',
            'annual_targets','terminal_EXIT','clock_scope'}
    require(type(calendar) is dict and set(calendar)==fields and calendar['schema']==CALENDAR,
            'SCHEDULED_FIXED_CALENDAR')
    days=[r['date'] for r in schedule];rows={r['date']:r for r in schedule}
    require(days==sorted(set(days)),'SCHEDULED_SOURCE_DATES')
    initial,terminal=calendar['initial_date'],calendar['terminal_date']
    require(initial in rows and terminal in rows and initial<terminal,'SCHEDULED_BOUNDARIES')
    selected=[d for d in days if initial<=d<=terminal]
    require(calendar['dates']==selected and type(calendar['nav_points']) is int
            and calendar['nav_points']==len(selected) and type(calendar['returns']) is int
            and calendar['returns']==len(selected)-1,'SCHEDULED_GRID')
    expected=[initial]+[max(d for d in selected if date.fromisoformat(d).year==year)
                       for year in range(date.fromisoformat(initial).year,date.fromisoformat(terminal).year)]
    expected=list(dict.fromkeys(expected))
    require(all(rows[d]['next_reference_date'] in selected and rows[d]['next_reference_date']<terminal
                for d in expected),'SCHEDULED_FIXED_TARGET_BOUNDARY')
    targets=calendar['annual_targets']
    require(type(targets) is list and [r.get('formation_date') for r in targets]==expected,
            'SCHEDULED_FIXED_ANNUAL_GRID')
    def event(value,formation,entry):
        require(type(value) is dict and set(value)=={'formation_date','K','D','execution_date','reference_execution_close_utc'}
                and value['formation_date']==formation and value['execution_date']==entry,
                'SCHEDULED_FIXED_EVENT')
        known=datetime.combine(date.fromisoformat(formation)+timedelta(days=1),time(),tzinfo=timezone.utc)
        decision=known+timedelta(seconds=60)
        close=datetime.fromisoformat(rows[entry]['reference_close_utc'].replace('Z','+00:00'))
        parse=lambda text:datetime.fromisoformat(text.replace('Z','+00:00'))
        require(parse(value['K'])==known and parse(value['D'])==decision and
                parse(value['reference_execution_close_utc'])==close and known<decision<close,
                'SCHEDULED_FIXED_CLOCK')
        return {'signal_date':formation,'signal_index':days.index(formation),'execution_date':entry,
                'execution_reference_close_utc':rows[entry]['reference_close_utc'],
                'known_ns':nanoseconds(known),'decision_ns':nanoseconds(decision)}
    decisions=[event(v,d,rows[d]['next_reference_date']) for v,d in zip(targets,expected)]
    exit_event=event(calendar['terminal_EXIT'],days[days.index(terminal)-1],terminal)
    require(not any(d['execution_date']==terminal for d in decisions),'SCHEDULED_FIXED_EXIT_OVERRIDE')
    return {'FINAL':{'initial':initial,'terminal':terminal,'nav_dates':selected,'nav_points':len(selected),
                     'return_count':len(selected)-1,'decisions':decisions,'decision_count':len(decisions),
                     'terminal_exit':exit_event}}


def plan_phase(market,profile,grid):
    symbols=profile['symbols'];require(market['symbols']==symbols,'SCHEDULED_MARKET_SYMBOLS')
    rows={r['date']:r for r in market['schedule']}
    close=lambda d:nanoseconds(datetime.fromisoformat(rows[d]['reference_close_utc'].replace('Z','+00:00')))
    nav=[{'date':d,'nominal_ns':close(d),'sample_ns':close(d)+1000,'initial':i==0,'terminal':d==grid['terminal']}
         for i,d in enumerate(grid['nav_dates'])]
    decisions=[]
    for event in grid['decisions']:
        instructions={leg['id']:({'kind':'HOLD'} if leg['rule']=='CASH' else
                     {'kind':'TARGET','weights':leg['weights'],'signal':{'kind':'FIXED_DECLARED_WEIGHTS'}})
                      for leg in profile['legs']}
        decisions.append({'day':event['execution_date'],'formation':event['signal_date'],
            'known_ns':event['known_ns'],'decision_ns':event['decision_ns'],'open_ns':close(event['execution_date']),
            'kind':'REFERENCE','instructions':instructions})
    final=grid['terminal_exit']
    decisions.append({'day':grid['terminal'],'formation':final['signal_date'],'known_ns':final['known_ns'],
        'decision_ns':final['decision_ns'],'open_ns':close(grid['terminal']),'kind':'REFERENCE',
        'instructions':{leg['id']:{'kind':'EXIT'} for leg in profile['legs']}})
    return {'profile':{'kind':'REFERENCE_TARGETS','legs':[x['id'] for x in profile['legs']],'end':grid['terminal']},'symbols':symbols,
            'prices':{d:{s:{'close_micro':market['prices_micro'][d][s]} for s in symbols} for d in grid['nav_dates']},
            'grid':nav,'decisions':decisions,
            'signals':[],'quote_basis':'SYNTHETIC_VENDOR_ADJUSTED_REFERENCE_UNIT','clock_policy':'PINNED_REFERENCE_EARLY_CLOSE'}


def _fixed_drawdown(nav):
    from .scheduled_diagnostics import _drawdown, _elapsed, _metric
    result=_drawdown(nav)
    if result['status']=='NO_DRAWDOWN':
        point={'date':nav[0]['date'],'nav_cents':str(nav[0]['nav_cents'])}
        result.update(peak=point,trough=point,recovery=point,recovery_status='NO_DRAWDOWN',
            peak_to_trough_intervals=0,peak_to_trough_seconds=_metric(0),
            peak_to_recovery_intervals=0,trough_to_recovery_intervals=0,
            peak_to_recovery_seconds=_metric(0))
    trough=next((i for i,r in enumerate(nav) if result['trough'] and r['date']==result['trough']['date']),0)
    recovered=result['status']=='RECOVERED'
    if recovered:
        recovery=next(i for i,r in enumerate(nav) if r['date']==result['recovery']['date'])
        result['trough_to_recovery_seconds']=_elapsed(nav,trough,recovery)
    else:
        result['trough_to_recovery_seconds']=_metric(0) if result['status']=='NO_DRAWDOWN' else None
    missing=result['status']=='UNRECOVERED_BY_TERMINAL'
    result['censored_trough_to_terminal_intervals']=len(nav)-1-trough if missing else None
    result['censored_trough_to_terminal_seconds']=_elapsed(nav,trough,len(nav)-1) if missing else None
    return result


def _fixed_exposure(nav, prices):
    from .scheduled_diagnostics import _metric, _unavailable, _exposure
    checked=_exposure(nav)
    if checked['status']!='OK':return checked
    sampled=nav[1:];symbols=sorted(sampled[0]['positions']);n=len(sampled)
    values=[]
    for r in sampled:
        if r['date'] not in prices or set(prices[r['date']])!=set(symbols):
            return _unavailable('SAVED_REFERENCE_PRICE_GRID_MISSING')
        row={}
        for symbol in symbols:
            price=prices[r['date']][symbol].get('close_micro')
            if type(price) is not int or price<=0:return _unavailable('SAVED_REFERENCE_PRICE_DOMAIN')
            row[symbol]=Fraction(r['positions'][symbol]*price,10000*r['nav_cents'])
        values.append(row)
    means={s:sum((r[s] for r in values),Fraction())/n for s in symbols}
    # Iteration order supplies earliest grid index then lexical symbol on ties.
    maximum,idx,symbol=max(((r[s],i,s) for i,r in enumerate(values) for s in symbols),
                           key=lambda item:(item[0],-item[1],-symbols.index(item[2])))
    return {**checked,'mean_asset_fractions':{s:_metric(v) for s,v in means.items()},
            'mean_gross_exposure_fraction':_metric(sum(means.values(),Fraction())),
            'maximum_single_asset_fraction':_metric(maximum),
            'maximum_single_asset_point':{'date':sampled[idx]['date'],'symbol':symbol},
            'valuation':'EXACT_Q_TIMES_CLOSE_MICRO_OVER_10000_NAV_CENTS',
            'sample_scope':'POSTINITIAL_ONLY_TERMINAL_INCLUDED',
            'maximum_tie_rule':'EARLIEST_GRID_THEN_LEXICAL_SYMBOL'}


def diagnose_fixed(tape,schedule,prices,*,subperiods=()):
    """Versioned saved-only recipe; leaves all legacy diagnostics unchanged."""
    from .scheduled_diagnostics import diagnose, _nav, _unavailable, _holdings, _statistics, _costs
    result=diagnose(tape,schedule)
    result['schema']='polar.fixed-allocation-saved-diagnostics/1'
    nav,reason=_nav(tape)
    if reason:return result
    result['drawdown']=_fixed_drawdown(nav)
    result['exposure']=_fixed_exposure(nav,prices)
    by_date={r['date']:i for i,r in enumerate(nav)}
    segments=[]
    for first,last in subperiods:
        if first not in by_date or last not in by_date or by_date[first]>by_date[last]:
            segments.append(_unavailable('SUBPERIOD_BOUNDARY_MISSING',first_return_date=first,last_return_date=last));continue
        begin,end=by_date[first],by_date[last]
        # A segment beginning at the original cash anchor uses that anchor;
        # otherwise keep the immediately preceding saved close, including its costs.
        rows=nav[max(0,begin-1):end+1]
        segments.append({'status':'OK','reason':None,'first_return_date':rows[1]['date'] if len(rows)>1 else first,
            'requested_first_date':first,'last_return_date':last,'initial_date':rows[0]['date'],
            'intervals':len(rows)-1,'initial_holdings':_holdings(rows[0]),'terminal_holdings':_holdings(rows[-1]),
            'metrics':_statistics(rows),'costs':_costs(tape,rows[0],rows[-1]),
            'exposure':_fixed_exposure(rows,prices),'drawdown':_fixed_drawdown(rows),
            'account_treatment':'CARRIED_SAVED_HOLDINGS_NO_RESET_NO_EXTRA_LIQUIDATION'})
    result['subperiods']=segments
    return result


def diagnose_fixed_anchors(tape, schedule, prices, *, subperiods=()):
    """Profile12 pairs name saved NAV anchors; legacy first-return API is unchanged.

    Only translate exact saved dates. Keep the fixed recipe's costs, carried
    holdings, exposure and earliest-equal-peak drawdown, not temporal defaults.
    """
    from .scheduled_diagnostics import _nav, _unavailable
    nav, reason = _nav(tape)
    indices = {r['date']: i for i, r in enumerate(nav)} if not reason else {}
    mapped, slots = [], []
    for anchor, last in subperiods:
        context = {'requested_initial_anchor': anchor, 'last_return_date': last,
                   'subperiod_semantics': 'SAVED_NAV_ANCHOR_THEN_NEXT_SAVED_RETURN'}
        problem = reason
        if not problem:
            if anchor not in indices: problem = 'SAVED_NAV_ANCHOR_MISSING'
            elif last not in indices: problem = 'SUBPERIOD_BOUNDARY_MISSING'
            elif indices[anchor] >= indices[last]:
                problem = ('NO_RETURN_AFTER_SAVED_NAV_ANCHOR' if anchor == last else
                           'SAVED_NAV_ANCHOR_AFTER_END')
        if problem:
            slots.append(_unavailable(problem, **context))
        else:
            slots.append(context)
            mapped.append((nav[indices[anchor]+1]['date'], last))
    result = diagnose_fixed(tape, schedule, prices, subperiods=mapped)
    segments = iter(result['subperiods'])
    result['subperiod_semantics'] = 'SAVED_NAV_ANCHOR_THEN_NEXT_SAVED_RETURN'
    result['subperiods'] = [slot if slot.get('status') == 'UNAVAILABLE' else
                            {**next(segments), **slot} for slot in slots]
    return result

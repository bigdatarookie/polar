"""Invented close-quote final-replay control against the shared cent ledger."""
from fractions import Fraction
from datetime import timezone
from polar.ci_research import instant
from polar.ci_research_native import simulate
from polar.research_allocation import ReferenceLedger


def test_native_reference_close_frozen_targets_and_exact_trace():
    symbols=['AAA','BBB']; days=['2020-01-02','2020-01-03','2020-01-06','2020-01-07']
    prices=[{'AAA':10000000,'BBB':10000000}, {'AAA':20000000,'BBB':10000000},
            {'AAA':21000000,'BBB':5000000}, {'AAA':22000000,'BBB':6000000}]
    grid=[{'date':d,'nominal_ns':instant(d,21,0,timezone.utc),
           'sample_ns':instant(d,21,0,timezone.utc)+1000,'initial':i==0,'terminal':i==3}
          for i,d in enumerate(days)]
    instructions=[{'kind':'TARGET','weights':{'AAA':[1,1],'BBB':[0,1]}},
                  {'kind':'TARGET','weights':{'AAA':[0,1],'BBB':[1,1]}}, {'kind':'EXIT'}]
    decisions=[{'day':days[i+1],'formation':days[i], 'known_ns':instant(days[i+1],0,0,timezone.utc),
                'decision_ns':instant(days[i+1],0,1,timezone.utc), 'open_ns':grid[i+1]['nominal_ns'],
                'kind':'REFERENCE','instructions':{'REFERENCE_TEST':instruction}}
               for i,instruction in enumerate(instructions)]
    plan={'symbols':symbols, 'profile':{'kind':'REFERENCE_TARGETS','legs':['REFERENCE_TEST'],'end':days[-1]},
          'grid':grid,'decisions':decisions,
          'prices':{d:{s:{'close_micro':p[s]} for s in symbols} for d,p in zip(days,prices)}}
    native=simulate(plan)['legs'][0]
    ledger=ReferenceLedger(symbols); expected=[ledger.mark(prices[0])]
    for i,instruction in enumerate(instructions):
        intent={'targets':{s:0 for s in symbols},'terminal':True} if instruction['kind']=='EXIT' else ledger.intent(
            prices[i],{s:Fraction(*v) for s,v in instruction['weights'].items()})
        expected.append(ledger.execute(intent,prices[i+1],date=days[i+1]))
    for actual,wanted in zip(native['nav'],expected):
        for key in ['nav_cents','cash_cents','positions','position_cents','flat_cents','bps_cents']:
            assert actual[key]==wanted[key], (key,actual,wanted)
    assert native['intents'][0]['targets']['AAA']==10000 # sized at previous10, not future20
    assert native['fills'][0]['q']==4994
    assert native['fills'][0]['cash_after_cents']==1912
    assert all(v==0 for v in native['nav'][-1]['positions'].values())
    assert [(x['symbol'],x['side'],x['q'],x['fee_cents'],x['settled_cents']) for x in native['fills']]==[
           (x['symbol'],x['side'],x['q'],x['fee_cents'],x['settled_cents']) for x in ledger.fills]

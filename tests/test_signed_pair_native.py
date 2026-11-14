from dataclasses import replace
from fractions import Fraction as F
from polar.signed_event_driver import PairEvent,AccountContext,Locate
from polar.signed_native_bridge import MarkEvent,MarkIdentity
from polar.signed_execution_terms import execution_quote
from polar.signed_pair_native import run_pair_timeline


def test_actual_pair_adverse_prices_ceiling_fees_and_source_absent_replay(record_property):
    ctx=AccountContext('INVENTED_ACCOUNT','PATH7','INVENTED_CONFIG','INVENTED_SOURCE',('AAPL','AMZN'))
    times=(1700000000000000000,1700086400000000000)
    def factory(i,driver):
        t=times[i];eid='event-'+str(i);raw=F(1234567,1000000)
        marks=(('AAPL',raw),('AMZN',raw))
        identities=tuple(MarkIdentity(n,'INVENTED_ROW/'+n,'INVENTED_SOURCE/'+n,t,None,'MODELED','INVENTED_CONDITIONAL_REFERENCE') for n in ctx.names)
        return PairEvent(eid,t,'CLOSE',marks,MarkEvent(eid,t,identities),
            instruction='TARGET' if i==0 else 'EXIT',formation='formation-'+str(i),decision_ns=t-60*10**9,
            targets=(('AAPL',2 if i==0 else 0),('AMZN',-2 if i==0 else 0)),
            locates=(Locate('locate',ctx.path,ctx.account,'formation-0','AMZN','SHORT',eid,2,True,'INVENTED_LOCATE'),) if i==0 else (),
            side_quotes=tuple(execution_quote(n,eid,ctx.path,raw,adverse=True) for n in ctx.names),terminal=i==1)
    out=run_pair_timeline(ctx,times,factory)
    assert out['verification']['status']=='VERIFIED_SAVED_SIGNED_EVENTS'
    fills=[r for r in out['packet']['records'] if r['kind']=='FILL']
    assert len(fills)==4
    assert all(r['transition'].operands['fee_cents']==101 for r in fills)
    assert all(r['transition'].operands['price_usd']!=F(1234567,1000000) for r in fills)
    assert not any(q for _,q in out['packet']['final_state'].positions)


def test_native_partial_cancel_terminates_construction_and_saves_fee_exposure():
    ctx=AccountContext('INVENTED_PARTIAL','BASE','INVENTED_CONFIG','INVENTED_SOURCE',('AAPL','AMZN'))
    times=(1700000000000000000,1700086400000000000)
    def factory(i,driver):
        t=times[i];eid='partial-'+str(i);raw=F(3)
        identities=tuple(MarkIdentity(n,'INVENTED/'+n,'INVENTED_SOURCE/'+n,t,None,'MODELED','INVENTED_CONDITIONAL_REFERENCE') for n in ctx.names)
        return PairEvent(eid,t,'CLOSE',tuple((n,raw) for n in ctx.names),MarkEvent(eid,t,identities),
            instruction='TARGET' if i==0 else 'EXIT',formation='formation-'+str(i),decision_ns=t-60*10**9,
            targets=(('AAPL',2 if i==0 else 0),('AMZN',-2 if i==0 else 0)),
            locates=(Locate('locate',ctx.path,ctx.account,'formation-0','AMZN','SHORT',eid,2,True,'INVENTED'),) if i==0 else (),
            side_quotes=tuple(execution_quote(n,eid,ctx.path,raw) for n in ctx.names),terminal=i==1)
    out=run_pair_timeline(ctx,times,factory,capital_cents=1000,invented_partial_order=True)
    records=out['packet']['records'];fills=[r for r in records if r['kind']=='FILL']
    assert len(fills)==2 and all(r['transition'].operands['actual_quantity']==1 for r in fills)
    assert fills[0]['command'].quantity==2 and fills[0]['command'].side=='SELL'
    assert not any(r['command'].phase=='NEW_LONG' for r in fills)
    assert any(r['kind']=='CONSTRUCTION_TERMINATED' for r in records)
    assert any(r['kind']=='EXPOSURE_RESPONSE_CHECKPOINT' and r['checkpoint']=='COMPLETED_OR_TERMINATED_CONSTRUCTION' and r['failed'] for r in records)
    assert len([r for r in records if r['kind']=='TRANSIENT_FILL_EXPOSURE'])==2
    fees=[r['fee'] for r in records if r['kind']=='ACTUAL_ORDER_FEE_CENSUS']
    assert sum(r['flat_cents'] for r in fees)==200 and sum(r['bps_cents'] for r in fees)==2

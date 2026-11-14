"""PRIVATE source-absent consumed signed-event verification, no native runtime.

Replays declared events and supplied actual callbacks through pure arithmetic.
It does not generate prices, native fills, scores, policy or financial verdicts.
"""
from dataclasses import fields, is_dataclass
from fractions import Fraction
from copy import deepcopy
from types import SimpleNamespace
from pathlib import Path
import math
import re

from .signed_event_driver import (AccountContext,Rate,Action,Locate,Event,OrderRequest,RoutingBoundary,SignedEventDriver)
from .signed_account_core import (State,Claim,Accrual,Transition,record_confirmed_fill,propose_fill,amount_cents)
from .signed_native_bridge import (SignedNativeBridge,MarkEvent,MarkIdentity,TradingLot,settled_trade,require)
from .gym_contract import canonical,decode,sha,MAX_BYTES
from .history_bundle import read_file

TYPES={c.__name__:c for c in (AccountContext,Rate,Action,Locate,Event,OrderRequest,RoutingBoundary,State,Claim,Accrual,
                             Transition,MarkEvent,MarkIdentity,TradingLot)}


def encode(value):
    if is_dataclass(value):
        require(type(value) in TYPES.values(),'SIGNED_PACKET_TYPE')
        return {'$type':type(value).__name__,'fields':{f.name:encode(getattr(value,f.name)) for f in fields(value)}}
    if type(value) is Fraction:return {'$fraction':[value.numerator,value.denominator]}
    if type(value) is tuple:return {'$tuple':[encode(v) for v in value]}
    if type(value) is list:return [encode(v) for v in value]
    if type(value) is dict:
        require(all(type(k) is str and not k.startswith('$') for k in value),'SIGNED_PACKET_KEY')
        return {k:encode(v) for k,v in value.items()}
    require(value is None or type(value) in (str,int,bool),'SIGNED_PACKET_SCALAR');return value


def restore(v,depth=0):
    require(depth<50,'SIGNED_PACKET_DEPTH')
    if type(v) is list:
        require(len(v)<=200000,'SIGNED_PACKET_ARRAY');return [restore(x,depth+1) for x in v]
    if type(v) is dict:
        if set(v)=={'$fraction'}:
            p=v['$fraction'];require(type(p) is list and len(p)==2 and all(type(x) is int for x in p)
                and p[1]>0 and math.gcd(*p)==1,'SIGNED_PACKET_FRACTION');return Fraction(*p)
        if set(v)=={'$tuple'}:
            require(type(v['$tuple']) is list,'SIGNED_PACKET_TUPLE');return tuple(restore(v['$tuple'],depth+1))
        if set(v)=={'$type','fields'}:
            c=TYPES.get(v['$type']) if type(v['$type']) is str else None
            require(c is not None and type(v['fields']) is dict and set(v['fields'])=={f.name for f in fields(c)},
                    'SIGNED_PACKET_CLOSED_TYPE')
            return c(**{k:restore(x,depth+1) for k,x in v['fields'].items()})
        require(all(type(k) is str and not k.startswith('$') for k in v),'SIGNED_PACKET_KEY')
        return {k:restore(x,depth+1) for k,x in v.items()}
    require(v is None or type(v) in (str,int,bool),'SIGNED_PACKET_SCALAR');return v


class _SavedAccount:
    def __init__(self,initial,identity):
        self.initial=initial;self.id=identity;self.exact_lots={};self.pnl=0;self.fees=0
    def exact_marked_trading_equity(self,marks):
        unrealized=sum(amount_cents(lot.quantity,marks[n])-lot.basis_cents
            for n,lot in self.exact_lots.items() if lot.quantity)
        cash=self.initial+self.pnl-self.fees
        return {'native_cash_cents':cash,'exact_unrealized_cents':unrealized,
                'exact_trading_equity_cents':cash+unrealized,'exact_realized_cents':self.pnl,
                'actual_fee_cents':self.fees,'stock_f64_position_portfolio_valuation':'NOT_SUPPORTED_EXACT_ORACLE'}


class _SavedBridge(SignedNativeBridge):
    """No native imports: actual fill tokens are inputs, never regenerated fills."""
    def __init__(self,packet):
        account=_SavedAccount(packet['initial_state'].free_cents,packet['native_account_id'])
        instruments=packet['native_instruments'];self.saved_account=account
        def positions():return {n:account.exact_lots.get(i,TradingLot()).quantity for n,i in instruments.items()}
        super().__init__(packet['initial_state'],instruments,None,positions,lambda:account,
                         initial_cents=account.initial,continue_economic_events=True)

    def admit(self,command,oid,marks,event):
        require(self.pending is None and not self.halted and command.intent_id not in self.used_intents and
                oid not in self.used_orders,'SIGNED_SAVED_SERIAL_SUBMISSION')
        self._observe_current_book(marks,MarkEvent(command.intent_id+':admission-mark',event.at_ns,event.mark_event.identities),command.intent_id)
        require(not (self.model_survival_failed or self.economic_execution_breach) or command.forced,
                'SIGNED_SAVED_DEFAULT_SUBMISSION')
        proposal=propose_fill(self.state,'proposal:'+command.intent_id,command.name,command.side,command.quantity,
            command.price,command.fee_cents,marks=marks,forced=command.forced,located_cap=command.located_cap,
            locate_provenance=None if command.locate_id is None else
                next(v.provenance for v in event.locates if v.id==command.locate_id))
        require(proposal.status=='ADMITTED_PROPOSAL_NOT_EXECUTION','SIGNED_SAVED_UNADMITTED_SUBMISSION')
        provenance=None if command.locate_id is None else next(v.provenance for v in event.locates if v.id==command.locate_id)
        self.events.append({'kind':'ADMISSION','intent_id':command.intent_id,'order_id':oid,'name':command.name,
            'side':command.side,'quantity':command.quantity,'price_usd':str(command.price),'fee_cents':command.fee_cents,
            'status':proposal.status,'operands':deepcopy(proposal.operands),'native_submissions':1})
        self.pending={'intent_id':command.intent_id,'order_id':oid,'name':command.name,'side':command.side,
                      'quantity':command.quantity,'filled':0,'located_cap':command.located_cap,
                      'locate_provenance':provenance,'funding_mode':'NO_CREDIT','funding_assumption':None}
        self.used_intents.add(command.intent_id);self.used_orders.add(oid);self.native_submission_count+=1

    def record_fill(self,event,marks):
        raw=event.raw;p=self.pending;key=(raw['order_id'],raw['trade_id'])
        require(p is not None and key not in self.used_fills and raw['order_id']==p['order_id'] and
                raw['instrument_id']==self.instruments[p['name']], 'SIGNED_SAVED_ACTUAL_FILL_JOIN')
        side={'1':'BUY','2':'SELL','BUY':'BUY','SELL':'SELL'}.get(raw['side'])
        q=Fraction(raw['quantity_token']);price=Fraction(raw['price_token'])
        commission=raw['commission_token'].split()
        require(len(commission)==2 and commission[1]=='USD','SIGNED_SAVED_COMMISSION_CURRENCY')
        fee=Fraction(commission[0].replace(',',''))*100
        require(q.denominator==fee.denominator==1 and q>0 and fee>=0 and side==p['side'] and
                p['filled']+q<=p['quantity'],'SIGNED_SAVED_ACTUAL_FILL_OPERANDS')
        q=q.numerator;fee=fee.numerator
        result=record_confirmed_fill(self.state,'fill:'+raw['order_id']+':'+raw['trade_id'],p['name'],side,q,price,fee,marks,
            execution_provenance='ACTUAL_NATIVE_CALLBACK',located_cap=p['located_cap'],locate_provenance=p['locate_provenance'],
            funding_mode=p['funding_mode'],funding_assumption=p['funding_assumption'])
        a=self.saved_account;before=a.exact_lots.get(raw['instrument_id'],TradingLot())
        lot,pnl,cross=settled_trade(before,side,q,price);require(not cross,'SIGNED_SAVED_UNSUPPORTED_CROSSING')
        a.exact_lots[raw['instrument_id']]=lot;a.pnl+=pnl;a.fees+=fee
        self.used_fills.add(key);self.state=result.after;p['filled']+=q
        self.events.append({'kind':'CONFIRMED_NATIVE_FILL','actual_fill':deepcopy(raw),
                            'core_status':result.status,'core_operands':deepcopy(result.operands)})
        self.reconcile(marks)
        if result.status=='CONFIRMED_EXECUTION_BREACH':self.economic_execution_breach=True
        return result


def verify_packet(packet,expected_context):
    require(type(packet) is dict and set(packet)=={'schema','context','initial_state','native_instruments','native_account_id',
        'records','final_state','native_submission_count','execution_authority','scope'} and
        packet['schema']=='polar.private-signed-events/1' and packet['context']==expected_context and
        type(expected_context) is AccountContext and packet['execution_authority'] is False,
        'SIGNED_SAVED_CONTEXT_SCHEMA')
    require(type(packet['records']) is list and packet['records'],'SIGNED_SAVED_RECORDS')
    bridge=_SavedBridge(packet);driver=SignedEventDriver(expected_context,bridge);saved=packet['records']
    def check():
        n=len(driver.records)
        actual=encode(driver.records);expected=encode(saved[:n])
        def diff(a,b,path='records'):
            if type(a) is not type(b):return path+':type'
            if type(a) is dict:
                if set(a)!=set(b):return path+':keys'
                for k in a:
                    if a[k]!=b[k]:return diff(a[k],b[k],path+'.'+k)
            elif type(a) is list:
                if len(a)!=len(b):return path+':length'
                for i,(x,y) in enumerate(zip(a,b)):
                    if x!=y:return diff(x,y,path+'['+str(i)+']')
            return path
        require(n<=len(saved) and actual==expected,'SIGNED_SAVED_CONSUMED_EVENT_MISMATCH:'+diff(actual,expected))
    while len(driver.records)<len(saved):
        i=len(driver.records);row=saved[i]
        if driver.event is None:
            require(row.get('kind')=='BEGIN','SIGNED_SAVED_MISSING_EVENT_BEGIN')
            driver.begin_event(row['event'],row['boundary']);check()
        else:
            c=driver.next_order();check()
            if c is None:continue
            i=len(driver.records);require(i<len(saved) and saved[i].get('kind')=='SUBMIT','SIGNED_SAVED_MISSING_SUBMISSION')
            r=saved[i];oid=r['order_id']
            driver._submission_evidence(c,oid,r['native_submission_ns'],r['order_init_ns'])
            bridge.admit(c,oid,driver.current_marks,driver.event);check()
            while driver.command is not None:
                i=len(driver.records);require(i<len(saved),'SIGNED_SAVED_MISSING_TERMINAL_CALLBACK')
                r=saved[i]
                if r.get('kind')=='FILL':
                    f=r['actual_fill'];driver.on_fill(SimpleNamespace(raw=f,client_order_id=f['order_id'],trade_id=f['trade_id'],
                        ts_event=f['execution_ns'],ts_init=f['native_init_ns']),received_ns=r['native_clock']['received_ns'])
                elif r.get('kind')=='TERMINAL_ORDER':driver.on_terminal(r['order_id'],r['status'])
                else:require(False,'SIGNED_SAVED_CALLBACK_CENSUS')
                check()
    require(driver.event is None and driver.packet()==packet,'SIGNED_SAVED_FINAL_STATE_CENSUS')
    return {'status':'VERIFIED_SAVED_SIGNED_EVENTS','events':len(driver.history),'actual_fills':len(bridge.used_fills),
            'source_reads':0,'native_calls':0,'feature_calls':0,'writes':0,'financial_verdict':'NOT_ASSESSED'}


def packet_bytes(packet):
    verify_packet(packet,packet['context']);raw=canonical(encode(packet))
    require(len(raw)<=MAX_BYTES,'SIGNED_PACKET_BYTES');return raw


def verify_bytes(raw,expected_context):
    require(type(raw) is bytes and len(raw)<=MAX_BYTES,'SIGNED_PACKET_BYTES')
    value=decode(raw);require(canonical(value)==raw,'SIGNED_PACKET_CANONICAL')
    packet=restore(value);return packet,verify_packet(packet,expected_context)


def publish_packet(store,packet):
    raw=packet_bytes(packet)
    manifest={'schema':'polar.private-signed-event-manifest/1','context':encode(packet['context']),
              'file':{'name':'events.json','sha256':sha(raw),'bytes':len(raw)}}
    m=canonical(manifest);name='signed-events-'+sha(m)
    with store.locked():store._publish('signed-event-components',name,{'manifest.json':m,'events.json':raw},file_limit=MAX_BYTES)
    return {'id':name,'manifest_sha256':sha(m),'payload_sha256':sha(raw),'bytes':len(raw)}


def verify_stored(root,name,expected_context):
    require(type(name) is str and re.fullmatch(r'signed-events-[a-f0-9]{64}',name),'SIGNED_PACKET_ID')
    parent='signed-event-components/'+name;m=read_file(root,parent+'/manifest.json',65536);d=decode(m)
    require(canonical(d)==m and name=='signed-events-'+sha(m) and
            set(d)=={'schema','context','file'} and d['schema']=='polar.private-signed-event-manifest/1' and
            restore(d['context'])==expected_context,'SIGNED_PACKET_MANIFEST')
    directory=Path(root)/parent
    require({v.name for v in directory.iterdir()}=={'manifest.json','events.json'} and
            not any(v.is_symlink() for v in directory.iterdir()),'SIGNED_PACKET_MEMBERS')
    f=d['file'];require(set(f)=={'name','sha256','bytes'} and f['name']=='events.json','SIGNED_PACKET_MEMBER')
    raw=read_file(root,parent+'/events.json',MAX_BYTES)
    require(sha(raw)==f['sha256'] and len(raw)==f['bytes'],'SIGNED_PACKET_MEMBER_HASH')
    packet,result=verify_bytes(raw,expected_context)
    return {**result,'packet':packet,'saved_member_reads':2,'id':name}

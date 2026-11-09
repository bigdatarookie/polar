"""Prospectively fixed invented component cases. No retained operands or native constructor."""
import copy
from decimal import Decimal
from fractions import Fraction
import json
from pathlib import Path
import shutil
import struct

import pytest

from polar.capability_contract import (CapabilityError, NumberToken, METHODS, ACCOUNTS, SYMBOLS,
    TOKENS, MAPPING, D, I, OPEN_DATES, CLOSE_DATES, SCHEMA_SHA, canonical, sha, digest, ns,
    money, rational, envelope, fixed)
from polar.capability_profile import restore, targets, allocation, evaluate, identity
from polar.capability_inputs import source_clock, source_json
from polar.capability_store import FamilyStore, immutable, descriptor, record, _replace


def represented(value):
    return {'value':NumberToken(repr(value)),'original_json_numeric_token':repr(value),
            'binary64_bits_be':struct.pack('>d',value).hex(),'binary64_hex':value.hex()}


def cohort(values=(4.,3.,2.,1.)):
    return [{'key':token,'source_witness':symbol,'D':D,'I_D':I,
             'K':'2021-12-31T05:00:00.000000Z',
             'scores':{method:represented(value) for method in METHODS}}
            for symbol,token,value in zip(SYMBOLS,TOKENS,values)]


def source(field):
    return {'record_token':'invented/source/'+field,'source_record_sha256':'a'*64,
        'field':field,'estimated_fullbar_K':'2022-01-07T05:00:00.000000Z',
        'observed_event_at':None,'observed_historical_available_at':None,
        'role':'EXECUTOR_MODELED_OPEN' if field=='o' else 'EX_POST_REFERENCE_CLOSE'}


def quotes(Q):
    return {symbol:{**identity(symbol),'quote_event_ns':str(Q+i),
        'snapshot_as_of':'2022-01-05T14:30:00.000001Z','price':'10.00','source':source('o')}
        for i,symbol in enumerate(SYMBOLS)}


def tape(trade=False):
    events=[]
    if trade:
        for phase,day,price,before,after,held_before,held_after,side in (
            ('entry',OPEN_DATES[0],'10.00','100000.00','99989.00',0,1,'BUY'),
            ('exit',OPEN_DATES[1],'12.00','99989.00','100000.00',1,0,'SELL')):
            Q=ns(day+'T14:30:00.000000Z');logical='REF_CASH/'+phase+'/1'
            common={'logical_order_id':logical,'phase':phase,'route_sequence':1,**identity('AAPL'),
                    'side':side,'logical_route_ns':str(Q+2000),'quantity':1,
                    'native_event_ns':str(Q+2000),'native_init_ns':str(Q+2000)}
            events.append({**common,'kind':'ORDER_SUBMITTED','sequence':len(events),
                'price_reference':price,'cash_before':before,'held_before':held_before})
            events.append({**common,'kind':'ORDER_FILLED','sequence':len(events),
                'logical_fill_id':logical+'/fill/1','fill_price':price,'cash_after':after,
                'held_after':held_after,'fee_receipt':{'logical_fee_id':logical+'/fee',
                    'amount':'1.00','currency':'USD','native_receipt_kind':'ORDER_FILLED_COMMISSION'}})
    samples=[]
    for i in range(7):
        nominal=ns(I) if i==0 else (ns(OPEN_DATES[1]+'T14:30:00.000000Z') if i==6
                                   else ns(CLOSE_DATES[i-1]+'T21:00:00.000000Z'))
        held=trade and 1<=i<=5
        positions=[]
        for symbol in SYMBOLS:
            qty=int(held and symbol=='AAPL')
            positions.append({**identity(symbol),'quantity':qty,'mark':'10.00' if qty else None,
                'mark_event_ns':str(nominal) if qty else None,'mark_source':source('c') if qty else None,
                'mark_requirement':'ADMITTED_HELD_MARK' if qty else 'NOT_REQUIRED_ZERO_QUANTITY'})
        cash=9998900 if held else 10000000;exposure=1000 if held else 0;nav=cash+exposure
        samples.append({'logical_sample_id':'REF_CASH/'+str(i),'sample_index':i,
            'role':'INITIAL' if i==0 else ('TERMINAL' if i==6 else 'CLOSE'),
            'effective_nominal_ns':str(nominal),'native_sample_ns':str(nominal+10000),
            'cash':money(cash),'positions':positions,'native_exposure_usd':money(exposure),
            'nav':money(nav),'nav_exact_usd':rational(Fraction(nav,100)),
            'outstanding_order_count':0,'claims_count':0})
    return samples,events


@pytest.mark.parametrize('method',METHODS)
def test_pure_valid_binary64_method(method):
    assert struct.pack('>d',restore(represented(1.5),method)).hex()=='3ff8000000000000'


@pytest.mark.parametrize('field,value',[
    ('binary64_bits_be','7ff0000000000000'),('binary64_hex','0x1.0p+2'),
    ('original_json_numeric_token','1.50000000000001')])
def test_pure_representation_disagreement(field,value):
    row=represented(1.5);row[field]=value
    with pytest.raises(CapabilityError,match='SCORE_REPRESENTATION'):restore(row,'ridge6')


def test_pure_signed_zero():
    row=represented(-0.0)
    assert struct.pack('>d',restore(row,'tree')).hex()=='8000000000000000'


def test_pure_subnormal_exact():
    row=represented(float.fromhex('0x0.0000000000001p-1022'))
    assert struct.pack('>d',restore(row,'tree')).hex()=='0000000000000001'


def test_pure_mapper_constant_tie():
    result=targets(cohort((0.,0.,0.,0.)))
    assert all(r['constant_score_tie'] and r['selected_ids']==[TOKENS[0]]
               for r in result['mapper_result']['methods'])


def test_pure_mapper_join_and_reference_separation():
    result=targets(cohort())
    assert [r['method_id'] for r in result['mapper_result']['methods']]==sorted(METHODS)
    assert [r['account_id'] for r in result['accounts']]==list(ACCOUNTS)
    assert all(r['targets']==[{**identity('AAPL'),'weight':'0.200000000000'}]
               for r in result['accounts'][:5])
    assert result['accounts'][5]['target_cash_weight']=='0.200000000000'
    assert result['accounts'][6]['targets']==[]


def test_pure_duplicate_score_cohort():
    rows=cohort();rows[1]=rows[0]
    with pytest.raises(CapabilityError,match='SCORE_COHORT_MISMATCH'):targets(rows)


def test_pure_empty_cash_allocation():
    Q=ns(OPEN_DATES[0]+'T14:30:00.000000Z')
    result,orders=allocation('REF_CASH','entry',Q,10000000,dict.fromkeys(SYMBOLS,0),quotes(Q),[])
    assert result['snapshot']['marks']==[] and result['allocation']['rows']==[]
    assert result['allocation']['allocated_value']=='0.00' and orders==[]


def test_pure_sparse_target_allocation():
    Q=ns(OPEN_DATES[0]+'T14:30:00.000000Z')
    result,orders=allocation('tree','entry',Q,10000000,dict.fromkeys(SYMBOLS,0),quotes(Q),
                            [{**identity('AAPL'),'weight':'0.200000000000'}])
    assert len(result['snapshot']['marks'])==1 and result['snapshot']['positions']==[]
    assert orders[0]['quantity']==2000 and orders[0]['source_symbol']=='AAPL'


def test_pure_exit_marks_exact_held_union():
    Q=ns(OPEN_DATES[1]+'T14:30:00.000000Z');held=dict.fromkeys(SYMBOLS,0);held['TSLA']=2
    result,orders=allocation('tree','exit',Q,10000,held,quotes(Q),[])
    assert len(result['snapshot']['marks'])==1
    assert orders[0]['quantity']==2 and orders[0]['side']=='SELL'


def test_pure_cash_metrics():
    samples,events=tape()
    result=evaluate('REF_CASH',samples,events)
    assert result['terminal_cash_usd']=='100000.00'
    assert result['terminal_net_return']==rational(0)
    assert result['sampled_max_drawdown']==rational(0)
    assert result['sampled_max_single_name_concentration']==rational(0)


def test_pure_fee_tape_exact_metrics():
    samples,events=tape(True)
    result=evaluate('REF_CASH',samples,events)
    assert result['fees_usd']=='2.00' and result['gross_notional_usd']=='22.00'
    assert result['terminal_net_return']==rational(0)
    assert result['sampled_max_drawdown']==rational(Fraction(1,100000))
    assert result['sampled_max_single_name_concentration']==rational(Fraction(10,99999))


def test_pure_missing_held_mark():
    samples,events=tape(True);samples[1]['positions'][0]['mark']=None
    with pytest.raises(CapabilityError,match='MISSING_HELD_MARK'):evaluate('REF_CASH',samples,events)


def test_pure_wrong_fee_rejected():
    samples,events=tape(True);events[1]['fee_receipt']['amount']='0.00'
    with pytest.raises(CapabilityError):evaluate('REF_CASH',samples,events)


def test_pure_terminal_ledger_tamper():
    samples,events=tape(True);samples[-1]['cash']='100001.00'
    with pytest.raises(CapabilityError,match='METRIC_MISMATCH'):evaluate('REF_CASH',samples,events)


def test_pure_wrong_route_timestamp():
    samples,events=tape(True);events[0]['native_event_ns']=str(int(events[0]['native_event_ns'])+1)
    with pytest.raises(CapabilityError,match='ORDER_SEQUENCE_MISMATCH'):evaluate('REF_CASH',samples,events)


def test_pure_canonical_no_float_or_inert_token():
    with pytest.raises(CapabilityError):canonical({'value':1.})
    with pytest.raises(CapabilityError):canonical({'value':NumberToken('1.0')})
    assert canonical({'z':0,'a':'x'})==b'{"a":"x","z":0}\n'


def test_pure_clock_canonicalization():
    assert source_clock('2022-01-05T09:00:00-05:00')==I
    with pytest.raises(CapabilityError):source_clock('2022-01-05T14:00:00')


def test_pure_source_subobject_numeric_lexeme():
    assert source_json({'b':NumberToken('1.5'),'a':1})=='{"a":1,"b":1.5}'


def test_pure_protocol_schema_and_status_domains():
    assert sha(Path('src/polar/capability_schema.json').read_bytes())==SCHEMA_SHA
    failed=envelope('metrics.json',None,'FAILED',['METRIC_MISMATCH'])
    assert failed['payload'] is None
    with pytest.raises(CapabilityError):envelope('metrics.json',None)


def family(tmp_path,case='case0'):
    anchor=tmp_path/'anchor'
    if not anchor.exists():
        anchor.mkdir(mode=0o700);(anchor/'assignments').mkdir();(anchor/'qualification').mkdir()
        immutable(anchor/'anchor.json',{'schema':'polar.capability-anchor/1','descriptor':descriptor(anchor)})
        qualification={'schema':'polar.capability-qualification/1',
            'family_id':'HYP007_FIXED_SCORE_CAPABILITY_V1','authorization_sha256':'a'*64,
            'ceilings':{'starts':6,'accounts':20,'cpu_us':600000000,
                       'wall_ns':900000000000,'native_wall_ns':300000000000}}
        immutable(anchor/'qualification/header.json',qualification)
        immutable(anchor/'qualification/projection.json',{'count':0,'tail':digest(qualification)})
    root=tmp_path/case;root.mkdir()
    proof=immutable(root/'mock-review.json',{'schema':'invented-mock-authority/1'})
    ref={**{k:proof[k] for k in ('path','sha256')},'record_token':'invented/review'}
    cfg={'mode':'TECHNICAL_FIXTURE','technical_case':case,'expected_image_id':'sha256:'+'a'*64,
         'protocol_refs':{},'launch':{'review_ref':ref},'input_refs':{},'auxiliary_refs':[]}
    authority={'schema':'polar.capability-execution-assignment/1','family_id':'HYP007_FIXED_SCORE_CAPABILITY_V1',
        'mode':'TECHNICAL_FIXTURE','bindings':copy.deepcopy(cfg),'qa_refs':[ref],'granted_at_ns':'1',
        'input_classification':'INVENTED','approved_input_hashes':[]}
    auth=immutable(anchor/'assignments'/(case+'.json'),authority)
    cfg['execution_authorization']={'assignment_id':case,'sha256':auth['sha256']}
    store=FamilyStore(root,anchor,technical=True,case_id=case);store.provision(cfg)
    return store,cfg


def test_mock_failed_original_forbids_replay(tmp_path):
    store,cfg=family(tmp_path);start=store.reserve(cfg,'ORIGINAL');aid=start['payload']['attempt_id']
    store.resources(aid,1,1,0);store.finish(aid,'FAILED','INPUT_INTEGRITY',None,0,[])
    with pytest.raises(CapabilityError,match='FAMILY_ALREADY_FAILED'):store.reserve(cfg,'REPLAY','b'*64)
    assert len(store.state()['attempts'])==1


def test_mock_unfinalized_forbids_retry(tmp_path):
    store,cfg=family(tmp_path);store.reserve(cfg,'ORIGINAL')
    assert store.state()['remaining_known'] is False
    with pytest.raises(CapabilityError,match='FAMILY_ALREADY_FAILED'):store.reserve(cfg,'ORIGINAL')


def test_mock_constructor_failure_charge_is_retained(tmp_path):
    store,cfg=family(tmp_path);aid=store.reserve(cfg,'ORIGINAL')['payload']['attempt_id']
    store.runtime(aid,{'path':'invented','sha256':'a'*64},cfg['expected_image_id'])
    store.account(aid,ACCOUNTS[0])
    # No native constructor is called: this is the frozen fake constructor boundary.
    with pytest.raises(RuntimeError):
        assert store.state()['attempts'][0]['accounts'][0]['account_id']==ACCOUNTS[0]
        raise RuntimeError('invented constructor failure')
    assert len(store.state()['attempts'][0]['accounts'])==1


def test_mock_registration_survives_lost_family(tmp_path):
    store,cfg=family(tmp_path)
    shutil.rmtree(store.directory)  # Exact disposable fixture mutation, never owner state.
    with pytest.raises(CapabilityError,match='FAMILY_ROOT_MISMATCH'):store.provision(cfg)


def test_mock_projection_loss_is_not_zero_budget(tmp_path):
    store,cfg=family(tmp_path);store.reserve(cfg,'ORIGINAL')
    _replace(store.directory/'projection.json',{'count':2,'tail':'a'*64})
    with pytest.raises(CapabilityError,match='FAMILY_ROOT_MISMATCH'):store.state()


def test_mock_technical_accounts_exceed_old_pool_with_all_history_preserved(tmp_path):
    for index in range(7):
        store,cfg=family(tmp_path,'case'+str(index))
        aid=store.reserve(cfg,'ORIGINAL')['payload']['attempt_id']
        store.runtime(aid,{'path':'invented','sha256':'a'*64},cfg['expected_image_id'])
        for account in ACCOUNTS:store.account(aid,account)
    directory=tmp_path/'anchor/qualification'
    rows=[record(path) for path in sorted(directory.glob('charge-*.json'))]
    assert sum(row['kind']=='ACCOUNT' for row in rows)==49
    assert sum(row['kind']=='START' for row in rows)==7
    assert record(directory/'header.json')['ceilings']['accounts']==20

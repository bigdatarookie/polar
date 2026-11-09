"""Prospective inert accounting controls; no provisioning/native/runtime invocation."""
from contextlib import nullcontext

import pytest

from polar.capability_contract import ACCOUNTS,CapabilityError
from polar.capability_store import FamilyStore

A='00000000-0000-4000-8000-000000000001'
B='00000000-0000-4000-8000-000000000002'
PACKET='a'*64
IMAGE='sha256:'+'b'*64


class MemoryFamily(FamilyStore):
    technical=False
    """Only journal arithmetic is real; all IO/global qualification is inert."""
    def __init__(self):self.rows=[];self.charges=[]
    def records(self):return self.rows,'invented-tail'
    def header(self,config=None):return {'expected_image_id':IMAGE}
    def locked(self):return nullcontext()
    def qualification(self,kind,payload):self.charges.append((kind,payload))
    def append(self,kind,payload):
        row={'kind':kind,'payload':payload};self.rows.append(row);return row


def start(family,aid,ordinal):
    family.append('START',{'attempt_id':aid,'kind':'ORIGINAL' if ordinal==0 else 'REPLAY',
                          'ordinal':ordinal,'replay_of':None if ordinal==0 else PACKET})
    family.append('RUNTIME',{'attempt_id':aid,'receipt_ref':{'invented':True},'observed_image_id':IMAGE})
    for i,account in enumerate(ACCOUNTS):
        family.append('ACCOUNT',{'attempt_id':aid,'account_id':account,'packet_ordinal':i,
                                 'family_ordinal':ordinal*7+i})


def resource(family,aid,native):
    family.append('RESOURCE',{'attempt_id':aid,'cpu_us':1,'wall_ns':350000000000,'native_wall_ns':native})


def finish(family,aid):
    family.append('FINISH',{'attempt_id':aid,'state':'SUCCESS','reason':None,'packet_id':PACKET,
                           'completed_accounts':7,'resource_evidence':'VERIFIED','physical_refs':{}})


def test_state_sums_latest_native_measurements_without_double_counting():
    family=MemoryFamily();start(family,A,0)
    resource(family,A,100000000000);resource(family,A,200000000000);finish(family,A)
    start(family,B,1);resource(family,B,50000000000)
    assert family.state()['spent']=={'cpu_us':2,'wall_ns':700000000000,'native_wall_ns':250000000000}


def test_resource_update_accepts_exact_family_native_boundary():
    family=MemoryFamily();start(family,A,0);resource(family,A,200000000000);finish(family,A)
    start(family,B,1)
    family.resources(B,1,350000000000,100000000000)
    assert family.state()['spent']['native_wall_ns']==300000000000


def test_overflow_is_rejected_and_stays_irreversibly_spent():
    family=MemoryFamily();start(family,A,0);resource(family,A,200000000000);finish(family,A)
    start(family,B,1)
    with pytest.raises(CapabilityError,match='NATIVE_WALL_LIMIT'):
        family.resources(B,1,350000000000,101000000000)
    assert family.state()['spent']['native_wall_ns']==301000000000
    assert family.rows[-1]['kind']=='RESOURCE'
    with pytest.raises(CapabilityError,match='INTERNAL_EXECUTION_ERROR'):
        family.resources(B,1,350000000000,100000000000)


def test_repeated_resource_update_does_not_charge_previous_value_twice():
    family=MemoryFamily();start(family,A,0);resource(family,A,200000000000);finish(family,A)
    start(family,B,1);resource(family,B,50000000000)
    family.resources(B,1,350000000000,100000000000)
    family.resources(B,1,350000000000,100000000000)
    assert family.state()['spent']['native_wall_ns']==300000000000


@pytest.mark.parametrize('native',[300000000000,301000000000])
def test_start_cannot_reset_exhausted_native_allowance(native):
    family=MemoryFamily();start(family,A,0);resource(family,A,native);finish(family,A)
    before=list(family.rows)
    with pytest.raises(CapabilityError,match='NATIVE_WALL_LIMIT'):
        family.reserve({},'REPLAY',PACKET)
    assert family.rows==before and family.charges==[]


def test_success_cannot_hide_preexisting_aggregate_overflow():
    family=MemoryFamily();start(family,A,0);resource(family,A,200000000000);finish(family,A)
    start(family,B,1);resource(family,B,101000000000)
    with pytest.raises(CapabilityError,match='NATIVE_WALL_LIMIT'):
        family.finish(B,'SUCCESS',None,PACKET,7,{})
    assert family.rows[-1]['kind']=='RESOURCE'


def test_no_resource_for_new_attempt_does_not_reset_prior_spent():
    family=MemoryFamily();start(family,A,0);resource(family,A,200000000000);finish(family,A)
    start(family,B,1)
    assert family.state()['spent']['native_wall_ns']==200000000000


def test_technical_history_over_old_pools_remains_spent_without_admission_gate():
    family=MemoryFamily();family.technical=True
    start(family,A,0)
    family.resources(A,700000000,1000000000000,400000000000)
    family.finish(A,'SUCCESS',None,PACKET,7,{})
    assert family.state()['spent']=={'cpu_us':700000000,'wall_ns':1000000000000,'native_wall_ns':400000000000}
    replay=family.reserve({},'REPLAY',PACKET)
    assert replay['payload']['ordinal']==1
    assert family.state()['spent']['cpu_us']==700000000
    with pytest.raises(CapabilityError,match='START_LIMIT'):
        family.reserve({},'ORIGINAL')


def test_technical_resource_monotonicity_and_success_integrity_are_not_waived():
    family=MemoryFamily();family.technical=True;start(family,A,0)
    family.resources(A,700000000,1000000000000,400000000000)
    with pytest.raises(CapabilityError,match='INTERNAL_EXECUTION_ERROR'):
        family.resources(A,699999999,1000000000000,400000000000)
    with pytest.raises(CapabilityError,match='FAMILY_ALREADY_FAILED'):
        family.finish(A,'SUCCESS',None,PACKET,7,{},resource_evidence='INCOMPLETE')

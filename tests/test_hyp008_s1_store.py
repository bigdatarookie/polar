"""Isolated invented record/accounting controls, no Service/models/real authority."""
import copy
import json
from pathlib import Path
import shutil

import pytest

from polar.hyp008_s1_contract import (canonical,decode,sha,ref,validate,NumberToken,
    FAMILY,GRANT,STAGES,SEMANTIC,COMMON,S1ContractError)
from polar.hyp008_s1_store import Deployment,S1Store
from polar.hyp008_s1_source import OWNER_PINS


def store(tmp_path):
    root=tmp_path/'objects';root.mkdir();auth=tmp_path/'authority';auth.mkdir()
    binding={'schema':'polar.hyp008-s1-store-binding/1','store_id':'invented-store',
        'canonical_root':str(root),'ledger_relative':'s1-families/'+FAMILY,'namespace':'S1','mode':'INVENTED'}
    st=root.stat();deployment=Deployment(root,binding,(st.st_dev,st.st_ino),auth)
    return S1Store(deployment,64*1024**3)


def seal(s,grant=True,variant='a'):
    registration={'schema':'polar.hyp008-s1-registration/1','candidate_id':'HYP008','variant_id':FAMILY,
        'family_key':FAMILY,'owner_pins':list(OWNER_PINS),'claim_scope':'DESCRIPTIVE_DEVELOPMENT_SOURCE_COHORT',
        'limits':dict(GRANT),'lineage_refs':[]}
    pin=s.object({'invented':variant})
    value={'schema':'polar.hyp008-s1-seal/1','prepared_ref':pin,'registration_ref':s.object(registration),
        'store_binding_ref':s.object(s.deployment.binding),'code_ref':pin,'build_ref':pin,'qa_ref':pin,
        'execution_assignment_ref':pin,'runtime_plan_ref':pin}
    value['seal_id']=sha(canonical(value));validate('Seal',value)
    if grant:
        authority={'schema':'polar.hyp008-s1-authority/1','seal_id':value['seal_id'],
            'registration_id':sha(canonical(registration)),'store_binding_id':s.deployment.binding_id,
            'family_key':FAMILY,'execution_assignment_ref':pin,'grant':dict(GRANT)}
        (s.deployment.authority_directory/(value['seal_id']+'.json')).write_bytes(canonical(authority))
    return value


def semantic():
    family={'schema':'polar.hyp008-s1-family/1','status':'NOT_STARTED','component_status':'NOT_STARTED',
        'reason':'NO_ISSUE_COMPARISON','stage':None,'detail':None,'stages':dict.fromkeys(STAGES,'NOT_RUN'),
        'components':{name:{'status':'NOT_RUN','reason':'NO_ISSUE_COMPARISON','ref':None}
                      for name in set(SEMANTIC)-COMMON},'claim_scope':'DESCRIPTIVE_DEVELOPMENT_SOURCE_COHORT'}
    return {**{n:canonical({'invented':n}) for n in COMMON-{'family.json'}},'family.json':canonical(family)}


def test_token_reader_preserves_source_number_and_rejects_duplicate_nonfinite():
    value=decode(b'{"proof":0.10000000000000000000001,"index":2,"literal":"2"}',opaque=True)
    assert value['proof']==NumberToken('0.10000000000000000000001')
    assert value['index']==NumberToken('2') and value['literal']=='2'
    for raw in (b'{"x":1,"x":2}',b'{"x":NaN}',b'{"x":Infinity}'):
        with pytest.raises(S1ContractError):decode(raw,opaque=True)


def test_closed_schema_rejects_unknown_and_bool_integer(tmp_path):
    s=store(tmp_path);good=seal(s)
    with pytest.raises(S1ContractError):validate('Seal',{**good,'authority_ref':good['qa_ref']})
    with pytest.raises(S1ContractError):validate('Ref',{'sha256':'a'*64,'bytes':True})
    with pytest.raises(S1ContractError):validate('Grant',{**GRANT,'tree':True})


def test_no_authority_does_not_charge_family(tmp_path):
    s=store(tmp_path);value=seal(s,False)
    with pytest.raises(S1ContractError,match='EXECUTION_NOT_AUTHORIZED'):s.begin(value)
    assert not (s.root/s.family()).exists()


def test_family_stage_order_and_irreversible_failed_attempt(tmp_path):
    s=store(tmp_path);value=seal(s);aid=s.begin(value)
    with pytest.raises(S1ContractError,match='FAMILY_ALREADY_STARTED'):s.begin(seal(s,variant='different-config-seal'))
    s.stage_intent(aid,'TREE')
    with pytest.raises(S1ContractError,match='STAGE_ALREADY_CHARGED'):s.stage_intent(aid,'TREE')
    with pytest.raises(Exception):s.stage_intent(aid,'LINEAR')
    s.witness(aid,'TREE','CALL_BOUNDARY_OBSERVED',{'kind':'invented-call'})
    s.witness(aid,'TREE','COMPLETED',{'model_sha':'invented'})
    s.stage_intent(aid,'LINEAR')
    s.witness(aid,'LINEAR','NOT_REACHED',{'positive_control_flow':'invented failure before LP hook'})
    result=s.finish(aid,'PLANNED_FAMILY_UNAVAILABLE','INVENTED_FAILURE')
    assert result['stage_records']['LINEAR']['intent']['scientific_stage_attempt_charged'] is True
    assert not result['stage_records']['HISTORICAL_PASS']
    assert s.attempt(aid)==result
    with pytest.raises(S1ContractError):s.begin(value)


def test_crash_after_family_before_attempt_is_consumed(tmp_path,monkeypatch):
    s=store(tmp_path);value=seal(s);original=s._record
    def fail(parent,name,record):
        if parent.startswith('s1-attempts/'):raise RuntimeError('invented publication crash')
        return original(parent,name,record)
    monkeypatch.setattr(s,'_record',fail)
    with pytest.raises(RuntimeError):s.begin(value)
    assert (s.root/s.family()/'start'/'record.json').exists()
    monkeypatch.setattr(s,'_record',original)
    with pytest.raises(S1ContractError,match='FAMILY_ALREADY_STARTED'):s.begin(value)


def test_root_clone_cannot_reuse_trusted_deployment(tmp_path):
    s=store(tmp_path);value=seal(s)
    clone=tmp_path/'clone';shutil.copytree(s.root,clone)
    old=s.deployment
    with pytest.raises(S1ContractError,match='ROOT_IDENTITY'):
        S1Store(Deployment(clone,old.binding,old.root_identity,old.authority_directory),s.limit)
    s.root=clone
    with pytest.raises(S1ContractError,match='ROOT_CHANGED'):s.begin(value)


def test_immutable_publication_identity_and_readonly_report(tmp_path):
    s=store(tmp_path);files=semantic();manifest=s.publish(files);eid=manifest['experiment_id']
    before={str(p):p.read_bytes() for p in s.root.rglob('*') if p.is_file()}
    assert s.report(eid)['manifest']==manifest
    assert before=={str(p):p.read_bytes() for p in s.root.rglob('*') if p.is_file()}
    assert s.publish(files)==manifest
    bad=copy.deepcopy(files);bad['not-declared.json']=canonical({})
    with pytest.raises(S1ContractError):s.publish(bad)
    parent=s.root/'s1-experiments'/eid
    (parent/'source.json').chmod(0o600);(parent/'source.json').write_bytes(canonical({'tampered':True}))
    with pytest.raises(S1ContractError,match='SEMANTIC_HASH'):s.report(eid)


def test_orphan_actual_call_cannot_claim_completed(tmp_path):
    s=store(tmp_path);aid=s.begin(seal(s));s.stage_intent(aid,'TREE')
    with pytest.raises(Exception):s.witness(aid,'TREE','COMPLETED',{'invented':'no boundary'})
    result=s.attempt(aid)
    assert result['terminal_status']=='UNFINALIZED' and result['resumption_allowed'] is False

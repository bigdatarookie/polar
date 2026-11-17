"""Invented retained-contract fixtures; no private source or science execution."""
import json

import pytest

from polar import offline_author_binding as module
from polar.gym_contract import canonical,sha
from polar.history_store import HistoryStore
from polar.research_results import ResearchError
from polar.scheduled_service import authority_for


def config():
    return {'schema':'polar.scheduled-reference-config/1','namespace':'RETAINED',
        'execution_authority_ref':None,'code_revision':'a'*40,
        'runtime_image_id':'sha256:'+'b'*64,'input_ref':{'sha256':'c'*64}}


def profile():
    return {'schema':'polar.scheduled-reference-profile/8','protocol_id':'invented-offline',
            'legs':[{},{}],'cost_scenarios':[{'id':'BASE'},{'id':'COST_STRESS'}]}


def context(monkeypatch):
    monkeypatch.setattr(module,'loaded_revision',lambda:'a'*40)
    monkeypatch.setenv('POLAR_RUNTIME_IMAGE_ID','sha256:'+'b'*64)


def test_plain_retained_missing_legacy_file_forms_binding_not_permission(monkeypatch):
    context(monkeypatch)
    class Engine:pass
    value=authority_for(Engine(),config(),profile(),{'FINAL':{}})
    assert value['schema']=='polar.offline-author-binding/1'
    assert value['candidate_sha']=='a'*40 and value['expected_native_accounts']==4
    assert value['config_sha256']==sha(canonical({k:v for k,v in config().items() if k!='execution_authority_ref'}))
    assert value['expected_prior_attempts']==[] and value['scientific_acceptance']=='NOT_REVIEWED'
    assert not any(k in value for k in ('method_ref','method_verdict','candidate_ref','reviewer_id','grantor'))


@pytest.mark.parametrize('field,wrong,error',[
    ('code_revision','d'*40,'RESEARCH_CANDIDATE_REVISION_MISMATCH'),
    ('runtime_image_id','sha256:'+'e'*64,'RESEARCH_OFFLINE_AUTHOR_RUNTIME_MISMATCH'),
])
def test_actual_binding_mismatches_rejected_before_start(monkeypatch,field,wrong,error):
    context(monkeypatch); c=config();c[field]=wrong
    with pytest.raises(ResearchError,match=error):module.create(c,profile(),{'FINAL':{}})


def test_automatic_original_stays_nonresetting_and_failure_not_refunded(tmp_path,monkeypatch):
    from polar import scheduled_service as scheduled
    context(monkeypatch); c=config();p=profile()
    class Engine:store=HistoryStore(tmp_path,10**8)
    monkeypatch.setattr(scheduled,'prepare',lambda *a,**k:(p,{},[],{'FINAL':{}},None,None))
    def stop(*a):raise ValueError('INVENTED_STOP_BEFORE_NUMERICAL_EXECUTION')
    monkeypatch.setattr(scheduled,'load_market',stop)
    with pytest.raises(ValueError,match='INVENTED_STOP_BEFORE_NUMERICAL_EXECUTION'):
        scheduled.run(Engine(),c)
    roots=list((tmp_path/'scheduled-reference-attempts').glob('*/*'));assert len(roots)==1
    value=json.loads((roots[0]/'authority.json').read_bytes())
    finish=json.loads((roots[0]/'finish/record.json').read_bytes())
    assert value['schema']=='polar.offline-author-binding/1' and value['scientific_acceptance']=='NOT_REVIEWED'
    assert finish['refund'] is False and finish['automatic_retry'] is False
    assert finish['completed_native_accounts']==0
    with pytest.raises(ValueError,match='SCHEDULED_ORIGINAL_ALREADY_RECORDED'):
        scheduled.run(Engine(),c)


def test_supplied_legacy_file_does_not_fall_back_to_automatic_binding(tmp_path,monkeypatch):
    context(monkeypatch);path=tmp_path/'invalid-legacy.json';raw=canonical({'schema':'forged'})
    path.write_bytes(raw);c=config();c['execution_authority_ref']={'path':str(path),'sha256':sha(raw)}
    class Engine:pass
    with pytest.raises(ValueError,match='SCHEDULED_OPERATION_NOT_BOUND'):
        authority_for(Engine(),c,profile(),{'FINAL':{}})


def test_retained_contract_full_cli_family_without_permission_file(tmp_path,monkeypatch):
    import os,platform
    if platform.system()!='Linux' or platform.python_version()!='3.13.18':
        pytest.skip('locked CI runtime required; all input operands are invented')
    from reference_fixture import write
    from test_scheduled_fixed_costs import cost_fixture
    from polar.candidate_binding import loaded_revision
    from polar.reference_service import ReferenceResearchService
    from polar.research_results import ResearchResults
    from polar.scheduled_service import binding
    root,cfg,p,_=cost_fixture(tmp_path,monkeypatch)
    manifest=json.loads(open(cfg['input_ref']['path'],'rb').read())
    assert manifest['provenance']['kind']=='DETERMINISTIC_INVENTED_FIXTURE'
    assert manifest['parent_dataset_revision'].startswith('INVENTED-')
    # Exercise the retained contract using only deterministic public operands;
    # this label is a fixture branch, not a grant for an actual licensed source.
    manifest['rights']='SOLE_OWNER_PRIVATE_NONCOMMERCIAL_NO_PUBLIC_DATA_OR_DATA_CONTAINING_RESULT_REDISTRIBUTION'
    cfg['input_ref']=write(tmp_path/'invented-retained-contract.json',manifest)
    p['input_sha256']=cfg['input_ref']['sha256'];cfg['profile_ref']=write(tmp_path/'invented-retained-profile.json',p)
    cfg['namespace']='RETAINED';cfg['code_revision']=loaded_revision()
    cfg['runtime_image_id']=os.environ['POLAR_CI_RUNTIME_IMAGE_ID']
    monkeypatch.setenv('POLAR_RUNTIME_IMAGE_ID',cfg['runtime_image_id'])
    assert cfg['execution_authority_ref'] is None
    service=ReferenceResearchService(root,128*1024**2)
    ready=service.preflight(cfg)
    assert ready['execution_binding_status']=='AUTOMATIC_OFFLINE_BINDING_READY_NOT_REVIEWED'
    assert not list(root.rglob('start.json'))
    result=service.run(cfg)
    assert result['status']=='SUCCESS' and result['financial_acceptance']=='NOT_REVIEWED'
    assert len(list(root.rglob('start.json')))==1
    value=json.loads(next(root.rglob('authority.json')).read_bytes())
    assert value['schema']=='polar.offline-author-binding/1' and 'method_ref' not in value
    for item in result['results'].values():
        detail=ResearchResults(root,128*1024**2).read(item['result_id'])
        assert detail['record']['bindings']['run_id']==result['attempt_id']
        assert detail['record']['bindings']['config_sha256']==sha(canonical(binding(cfg)))
        assert detail['assessment']['financial']=='NOT_REVIEWED'
    with pytest.raises(ValueError,match='SCHEDULED_ORIGINAL_ALREADY_RECORDED'):
        service.preflight(cfg)
    with pytest.raises(ValueError,match='SCHEDULED_ORIGINAL_ALREADY_RECORDED'):
        service.run(cfg)


@pytest.mark.parametrize('message,expected',[
    ('SCHEDULED_OPERATION_NOT_BOUND','SCHEDULED_OPERATION_NOT_BOUND'),
    ('private failure at /Users/owner/input.json','RESEARCH_OPERATION_FAILED'),
])
def test_cli_errors_are_actionable_without_private_text(tmp_path,monkeypatch,capsys,message,expected):
    from polar.cli import main
    from polar.config import Settings
    from polar.service import Service
    path=tmp_path/'config.json';path.write_text('{}')
    monkeypatch.setattr(Settings,'load_artifacts',classmethod(lambda cls:Settings('unused',tmp_path)))
    def stop(*a):raise ValueError(message)
    monkeypatch.setattr(Service,'research_run',stop)
    with pytest.raises(SystemExit,match='1'):main(['research-run',str(path)])
    assert json.loads(capsys.readouterr().err)=={'status':'ERROR','code':expected}

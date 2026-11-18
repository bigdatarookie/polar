"""Invented failed-publication recovery; no retained data, policy or account."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from polar import band_reconciliation as rec, band_source as source, native_selected_tool as tool
from polar.history_bundle import canonical, sha
from polar.research_reference import load_reference
from polar.research_native_review import inherited_queue
from test_band_source import fixture as source_fixture, Queue as SourceQueue, TASK as ORIGINAL, ACTOR
from test_reference_input import put

OBSERVER = 'qitem-INVENTED-band-observer'


class Queue(SourceQueue):
    def __init__(self, original_row, original_events):
        super().__init__()
        self.original_row = deepcopy(original_row)
        self.original_events = deepcopy(original_events)
        self.task.update(qitemId=OBSERVER)
        self.task['claimedAt'] = '2026-01-02T00:00:00Z'
        self.events[0]['transitionId'] = 4

    def read(self, *args):
        if args == ('queue', 'show', ORIGINAL, '--full'):
            self.calls.append(args);return deepcopy(self.original_row)
        if args == ('queue', 'transitions', ORIGINAL, '--full'):
            self.calls.append(args);return deepcopy(self.original_events)
        if args == ('queue', 'show', OBSERVER, '--full'):
            self.calls.append(args);return deepcopy(self.task)
        if args == ('queue', 'transitions', OBSERVER, '--full'):
            self.calls.append(args);return deepcopy(self.events)
        return super().read(*args)

    def terminalize(self, result):
        self.task.update(state='done', closureReason='no-follow-on', resolution=json.dumps(result))
        self.events.append({'transitionId':5,'state':'done','actorSession':ACTOR,
                            'identityProvenance':'transport:v1','ts':datetime.now(timezone.utc).isoformat()})


def fixture(tmp_path, monkeypatch, *, captured=False):
    root, config, spec, _ = source_fixture(tmp_path, monkeypatch)
    if captured:
        from test_captured_reference_input import captured_fixture
        from polar.reference_input import prepare_input
        sub=tmp_path/'captured';sub.mkdir()
        capture_root,capture_config,_=captured_fixture(sub)
        captured_input=prepare_input(capture_config,capture_root,10**8)
        spec['leaf_inputs'][0]['input_ref']=captured_input['input_ref']
        config['spec_ref']=put(tmp_path/'captured-band-spec.json',spec)
    initial = SourceQueue()
    proof = source.task_custody(config, initial)
    import polar.selected_component_input as component
    # One invented setup publication, then every test forbids rematerialization.
    prepared = component.prepare_selected_components(spec, root, 10**8, source_binding={**proof,'config':config})
    failure = {'schema':'engineering.band-source-producer-failure/1',
               'status':'SOURCE_PUBLICATION_UNQUALIFIED_NATIVE_POSTCHECK_REJECTED',
               'error_code':'BAND_SOURCE_GENERATION','consumer_task':ORIGINAL,
               'manifest':{k:prepared['input_ref'][k] for k in ('path','sha256')},
               'source_preparation_replayed':False,'financial_run':'NOT_RUN'}
    initial.task.update(state='done',closureReason='no-follow-on',resolution=json.dumps(failure))
    initial.events.append({'transitionId':3,'state':'done','actorSession':ACTOR,'identityProvenance':'transport:v1'})
    queue = Queue(initial.task, initial.events)
    request = {k:config[k] for k in ('namespace','question_id','actor_session','code','code_revision',
               'runtime_image_id','artifact_root_identity')}
    request.update(schema=rec.REQUEST,consumer_task=OBSERVER,input_ref=prepared['input_ref'],
                   original_failure_ref=ORIGINAL+'#3')
    def forbidden(*a,**k):raise AssertionError('RECONCILIATION_REBUILD_FETCH_OR_FINANCE')
    monkeypatch.setattr(component,'prepare_selected_components',forbidden)
    monkeypatch.setattr(source,'prepare_source_input',forbidden)
    import polar.ci_research_service as native
    monkeypatch.setattr(native,'bounded_native',forbidden)
    return root,request,queue


def files(directory):
    return {str(p.relative_to(directory)):sha(p.read_bytes()) for p in directory.rglob('*') if p.is_file()}


@pytest.mark.parametrize('captured',[False,True])
def test_actual_saved_linkage_and_reader_need_distinct_native_terminal(tmp_path,monkeypatch,captured):
    root,request,queue=fixture(tmp_path,monkeypatch,captured=captured)
    original=deepcopy(queue.original_row);source_dir=Path(request['input_ref']['path']).parent
    before=files(source_dir)
    out=rec.reconcile(request,root,10**8,queue=queue)
    assert out['status']==rec.STATUS
    assert out['input_ref']['sha256']==request['input_ref']['sha256']
    assert queue.original_row==original and files(source_dir)==before
    with inherited_queue(queue):
        with pytest.raises(ValueError,match='BAND_SOURCE_TERMINAL_CUSTODY'):
            load_reference(out['input_ref'])
        queue.terminalize(out['producer_terminal_result'])
        market=load_reference(out['input_ref'])
        assert market['symbols']==['BIL','VTI']
        from polar.reference_input import preflight_input
        assert preflight_input(out['input_ref'])['status']=='STRUCTURALLY_VALID_SOURCE_ONLY'
    assert files(source_dir)==before and queue.original_row==original
    # Reader adds no publications; original failure and new success are distinct.
    all_before=files(root)
    with inherited_queue(queue):load_reference(out['input_ref'])
    assert files(root)==all_before
    assert json.loads(queue.original_row['resolution'])['schema']=='engineering.band-source-producer-failure/1'
    assert json.loads(queue.task['resolution'])['schema']==rec.TERMINAL
    with pytest.raises(ValueError,match='BAND_RECONCILIATION_ALREADY_RECORDED'):
        rec.reconcile(request,root,10**8,queue=queue)


@pytest.mark.parametrize('field',['code','revision','runtime','root','actor','namespace','task','schema'])
def test_wrong_current_request_rejected_before_input_read(tmp_path,monkeypatch,field):
    root,request,queue=fixture(tmp_path,monkeypatch)
    if field=='code':request['code']={}
    elif field=='revision':request['code_revision']='f'*40
    elif field=='runtime':request['runtime_image_id']='sha256:'+'f'*64
    elif field=='root':request['artifact_root_identity']={}
    elif field=='actor':request['actor_session']='forged@engineering-rig'
    elif field=='namespace':request['namespace']='RETAINED'
    elif field=='task':request['consumer_task']=ORIGINAL
    else:request['schema']='polar.reference-input-conversion-config/11'
    monkeypatch.setattr(rec,'pinned_bytes',lambda *a:pytest.fail('OPEN_BEFORE_CURRENT_BINDING'))
    with pytest.raises(ValueError,match='BAND_'):rec.reconcile(request,root,10**8,queue=queue)


@pytest.mark.parametrize('part',['generation','fallback','missing','actor','claim','scope','terminal','resolution','omit_failure'])
def test_actual_native_rejections_record_safe_operands_without_source_bodies(tmp_path,monkeypatch,part):
    root,request,queue=fixture(tmp_path,monkeypatch)
    if part=='generation':queue.task['claimedByGeneration']='foreign-generation'
    elif part=='actor':queue.actor='quant-a@polar-rig'
    elif part=='claim':queue.events[0]['identityProvenance']='caller:v1'
    elif part=='scope':queue.task['tags']=[]
    elif part=='terminal':queue.original_events[-1]['identityProvenance']='caller:v1'
    elif part=='resolution':queue.original_row['resolution']='{}'
    elif part=='omit_failure':
        queue.original_row['resolution']=json.dumps({'schema':'polar.band-source-result/1','status':'SOURCE_ONLY_PREPARED_WITH_LIMITS'})
    else:
        read=queue.read
        def changed(*args):
            value=read(*args)
            if args==source.generation_read(queue.actor):
                if part=='fallback':value['entries'][0]['agentActivity']['fallback']=True
                else:value['entries']=[]
            return value
        queue.read=changed
    before=files(Path(request['input_ref']['path']).parent)
    with pytest.raises(ValueError,match='BAND_'):rec.reconcile(request,root,10**8,queue=queue)
    assert not list(root.glob('band-source-reconciliation-attempts/*/finish'))
    diagnostics=next(root.glob('band-source-reconciliation-attempts/*/failure/custody-comparisons.json'))
    entries=json.loads(diagnostics.read_bytes());assert entries
    assert any('expected_generation' in e for e in entries)
    forbidden=('reference_quote','resolution','source_adjusted_close_token','source_reference','body')
    assert not any(k in e.get('actual',{}) for e in entries if isinstance(e.get('actual'),dict) for k in forbidden)
    assert files(Path(request['input_ref']['path']).parent)==before
    if part in ('claim','terminal'):
        if part=='claim':
            cell=next(e for e in entries if e['read']=='queue' and isinstance(e.get('actual'),list))
            assert cell['expected']['identityProvenance']=='transport:v1'
            assert cell['actual'][0]['identityProvenance']=='caller:v1'
        else:
            comparisons=json.loads(next(root.glob('band-source-reconciliation-attempts/*/failure/comparison-operands.json')).read_bytes())
            cell=next(e for e in comparisons if e['check']=='ORIGINAL_NATIVE_TRANSITIONS')
            assert cell['expected']['terminal_transition']==3
            assert cell['expected']['identityProvenance']=='transport:v1'
            assert cell['actual']['terminal']['identityProvenance']=='caller:v1'


@pytest.mark.parametrize('part',['manifest','quotes','schedule','source-relations','quality','missing','foreign'])
def test_existing_object_integrity_rejection_never_rebuilds(tmp_path,monkeypatch,part):
    root,request,queue=fixture(tmp_path,monkeypatch)
    directory=Path(request['input_ref']['path']).parent
    if part=='foreign':
        request['input_ref']=put(tmp_path/'foreign.json',{'schema':'OTHER'})
    elif part=='missing':(directory/'quality.json').unlink()
    else:
        name=part+'.ndjson' if part=='quotes' else part+'.json'
        path=directory/name;path.chmod(0o600);path.write_bytes(path.read_bytes()+b' ')
    with pytest.raises(ValueError):rec.reconcile(request,root,10**8,queue=queue)
    assert not list(root.glob('band-source-reconciliation-attempts/*/finish'))
    evidence=json.loads(next(root.glob('band-source-reconciliation-attempts/*/failure/comparison-operands.json')).read_bytes())
    if part=='missing':
        item=next(e for e in evidence if e['check']=='SAVED_FILE_PRESENCE' and e['actual']['file']=='quality.json')
        assert item['expected']['present'] is True and item['actual']['present'] is False
    elif part=='foreign':
        item=next(e for e in evidence if e['check']=='SAVED_INPUT_ROOT')
        assert item['actual']['path']!=item['expected']['root']+'/manifest.json'
    else:
        item=next(e for e in evidence if e['check']=='SAVED_FILE_INTEGRITY' and
                  e['actual'].get('sha256') and e['expected']['sha256']!=e['actual']['sha256'])
        assert len(item['expected']['sha256'])==len(item['actual']['sha256'])==64
        assert item['actual']['bytes']==item['expected']['bytes']+1
        assert len(item['actual']['identity'])==5
        assert 'reference_quote' not in json.dumps(evidence)


@pytest.mark.parametrize('part',['observer_task','observer_resolution','failed_terminal','missing_terminal',
                                 'terminal_transport','original_failure','receipt','original_mutation','clock'])
def test_reader_rejects_mutated_or_unlinked_new_terminal(tmp_path,monkeypatch,part):
    root,request,queue=fixture(tmp_path,monkeypatch);out=rec.reconcile(request,root,10**8,queue=queue)
    queue.terminalize(out['producer_terminal_result'])
    pin=deepcopy(out['input_ref'])
    if part=='observer_task':pin['reconciliation_ref']['observer_task']='qitem-INVENTED-other'
    elif part=='observer_resolution':queue.task['resolution']=json.dumps({'schema':rec.TERMINAL,'status':rec.STATUS})
    elif part=='failed_terminal':queue.task['resolution']=json.dumps({'status':'FAILED'})
    elif part=='missing_terminal':queue.task['state']='in-progress'
    elif part=='terminal_transport':queue.events[-1]['identityProvenance']='caller:v1'
    elif part=='original_failure':queue.original_row['resolution']='{}'
    elif part=='original_mutation':
        path=Path(request['input_ref']['path']).parent/'quotes.ndjson';path.chmod(0o600);path.write_bytes(path.read_bytes()+b' ')
    elif part=='clock':queue.events[-1]['ts']='2000-01-01T00:00:00Z'
    else:
        obs=pin['reconciliation_ref']['observation_ref'];path=Path(obs['path'])
        path.chmod(0o600);path.write_bytes(path.read_bytes()+b' ')
    with inherited_queue(queue):
        with pytest.raises(ValueError):load_reference(pin)


def test_current_native_generation_race_after_saved_verification_fails_closed(tmp_path,monkeypatch):
    root,request,queue=fixture(tmp_path,monkeypatch)
    original=rec.verify_publication
    def race(*a,**k):
        value=original(*a,**k);queue.generation='changed-generation';return value
    monkeypatch.setattr(rec,'verify_publication',race)
    with pytest.raises(ValueError,match='BAND_SOURCE_GENERATION'):
        rec.reconcile(request,root,10**8,queue=queue)
    assert list(root.glob('band-source-reconciliation-attempts/*/failure/failure.json'))
    assert not list(root.glob('band-source-reconciliation-attempts/*/finish'))


def test_closed_stdio_operations_and_read_allowlist(tmp_path,monkeypatch):
    root,request,queue=fixture(tmp_path,monkeypatch)
    assert tool.selected_config('research-input-reconcile',request)==request
    for task in (ORIGINAL,OBSERVER):
        assert tool.permitted(['queue','show',task,'--full'],request)
        assert tool.permitted(['queue','transitions',task,'--full'],request)
    assert not tool.permitted(['queue','claim',OBSERVER],request)
    assert not tool.permitted(['queue','show','qitem-other','--full'],request)
    out=rec.reconcile(request,root,10**8,queue=queue)
    assert tool.selected_config('research-input-preflight',out['input_ref'])==request
    assert queue.original_row['state']=='done'


def test_original_failure_cannot_be_relabelled_by_pure_prepare_result_formatter(tmp_path,monkeypatch):
    root,request,queue=fixture(tmp_path,monkeypatch)
    manifest=json.loads(Path(request['input_ref']['path']).read_bytes())
    proof=manifest['conversion_metadata']['source_native_binding']
    # Exercise historical retained terminal semantics on invented metadata only:
    # no fit/source pins are opened before this native failure rejection.
    old=deepcopy(proof['config']);old['namespace']='RETAINED'
    before=deepcopy(queue.original_row)
    with pytest.raises(ValueError,match='BAND_SOURCE_TERMINAL_RESULT'):
        source.authorize(old,root,queue=queue,prior=proof,
                         terminal_result=source.producer_result(old,manifest),historical=True)
    assert queue.original_row==before


def test_source_purpose_file_failure_preserves_hash_operands_not_body(tmp_path,monkeypatch):
    root,request,queue=fixture(tmp_path,monkeypatch)
    manifest=json.loads(Path(request['input_ref']['path']).read_bytes())
    config=manifest['conversion_metadata']['source_native_binding']['config']
    spec=json.loads(Path(config['spec_ref']['path']).read_bytes())
    pin=spec['purpose_ref'];path=Path(pin['path'])
    path.write_bytes(path.read_bytes()+b' ')
    with pytest.raises(ValueError):rec.reconcile(request,root,10**8,queue=queue)
    evidence=json.loads(next(root.glob('band-source-reconciliation-attempts/*/failure/comparison-operands.json')).read_bytes())
    cell=next(e for e in evidence if e['check']=='SAVED_FILE_INTEGRITY' and
              e['expected']['sha256']==pin['sha256'])
    assert cell['actual']['sha256']!=pin['sha256']
    assert cell['actual']['bytes']==pin['bytes']+1
    assert 'source_qualification_refs' not in json.dumps(evidence)

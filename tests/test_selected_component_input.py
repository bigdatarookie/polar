"""Invented selected spans: excluded assets/dates never enter the decoder."""
import json
from pathlib import Path
from copy import deepcopy
import pytest
from test_reference_input import put
from test_selected_reference_input import selected_fixture
from test_captured_reference_input import captured_fixture
from polar.reference_input import prepare_input
from polar.research_reference import load_reference
from polar.selected_component_input import prepare_selected_components


def selected_fixture_graph(tmp_path):
    folder=tmp_path/'mixed';folder.mkdir()
    store,selected,_,_=selected_fixture(folder,targets=['AAA','BBB'])
    parent=prepare_input(selected,store,10**8)['input_ref']
    manifest=json.loads(Path(parent['path']).read_bytes())
    folder=tmp_path/'leaf';folder.mkdir()
    leafstore,capture,_=captured_fixture(folder)
    leaf=prepare_input(capture,leafstore,10**8)['input_ref']
    dates=['2024-02-01','2024-02-02']
    purpose=put(tmp_path/'purpose.json',{'scope':'INVENTED_SELECTED_ONLY_NO_AUTHORIZATION'})
    spec={'schema':'polar.selected-component-materialization/1','namespace':'INVENTED',
          'leaf_inputs':[{'input_ref':leaf,'symbol':'BIL'}],
          'normalized_inputs':[{'input_ref':parent,'binding_ref':selected['binding'],'symbol':'AAA'}],
          'schedule':manifest['schedule'],'date_range':{'start':dates[0],'end':dates[-1],'count':len(dates)},
          'purpose_ref':purpose,'qualification_refs':[purpose]}
    output=tmp_path/'output';output.mkdir()
    return output,spec,parent,capture


def test_selected_before_excluded_decode_and_never_read_parent_quotes_or_raw(tmp_path,monkeypatch):
    root,spec,parent,capture=selected_fixture_graph(tmp_path)
    import polar.selected_component_input as module
    actual_read,actual_decode=module.pinned_bytes,module.decode
    native=json.loads(Path(parent['path']).read_bytes())
    cap=json.loads(Path(capture['capture_return']['path']).read_bytes())
    forbidden={native['quotes']['sha256'],cap['body_ref']['sha256']}
    def only_selected_reads(pin):
        assert pin['sha256'] not in forbidden,'EXCLUDED_PARENT_OR_ORIGINAL_RAW_BODY_OPENED'
        return actual_read(pin)
    def only_selected_decodes(raw):
        assert b'"query_symbol":"BBB"' not in raw,'EXCLUDED_ASSET_DECODED'
        assert not (b'"query_symbol":"AAA"' in raw and b'"reference_date":"2024-01-31"' in raw),'OFFRANGE_ASSET_DECODED'
        assert not (b'"symbol":"BIL"' in raw and b'"date":"2024-01-31"' in raw),'OFFRANGE_LEAF_DECODED'
        return actual_decode(raw)
    monkeypatch.setattr(module,'pinned_bytes',only_selected_reads)
    monkeypatch.setattr(module,'decode',only_selected_decodes)
    binding={'scope':'INVENTED_SOURCE_FREE_TEST'}
    result=prepare_selected_components(spec,root,10**8,source_binding=binding)
    assert prepare_selected_components(spec,root,10**8,source_binding=binding)==result
    market=load_reference(result['input_ref']);assert market['symbols']==['AAA','BIL']
    assert market['dates']==['2024-02-01','2024-02-02']
    reference=load_reference(parent)
    for day in market['dates']:
        assert market['source_evidence'][day]['AAA']==reference['source_evidence'][day]['AAA']
        assert market['prices_micro'][day]['AAA']==reference['prices_micro'][day]['AAA']
        assert market['source_evidence'][day]['BIL']['source_ref']['kind']=='CAPTURED_ALL_ADJUSTED_SOURCE'
    out=json.loads(Path(result['input_ref']['path']).read_bytes())
    assert out['conversion_metadata']['source_native_binding']==binding
    assert out['conversion_metadata']['spec']==spec


@pytest.mark.parametrize('case,error',[
    ('broad_leaf','LEAF_SCOPE'),('duplicate','DUPLICATE'),('purpose','REFERENCE_FILE_HASH'),
    ('binding_record','BINDING'),('coverage','CONVERSION_SCHEDULE'),('namespace','BASIS_RIGHTS'),
    ('missing_binding','CALLER_BINDING'),('member_bytes','REFERENCE_FILE_HASH')])
def test_failure_before_publication_and_scope_access(tmp_path,monkeypatch,case,error):
    root,spec,parent,capture=selected_fixture_graph(tmp_path)
    native=json.loads(Path(parent['path']).read_bytes())
    import polar.selected_component_input as module
    actual_read=module.pinned_bytes
    if case=='broad_leaf':spec['leaf_inputs']=[{'input_ref':parent,'symbol':'AAA'}];spec['normalized_inputs']=[]
    if case=='duplicate':spec['normalized_inputs'].append(deepcopy(spec['normalized_inputs'][0]))
    if case=='purpose':
        p=Path(spec['purpose_ref']['path']);p.write_bytes(b' '*p.stat().st_size)
    if case=='binding_record':
        binding=json.loads(Path(spec['normalized_inputs'][0]['binding_ref']['path']).read_bytes())
        binding['records'][0]['selected_for_purpose']=False
        spec['normalized_inputs'][0]['binding_ref']=put(tmp_path/'bad-binding.json',binding)
    if case=='coverage':spec['date_range']['start']='2000-01-01'
    if case=='namespace':spec['namespace']='RETAINED'
    if case=='member_bytes':
        binding=json.loads(Path(spec['normalized_inputs'][0]['binding_ref']['path']).read_bytes())
        segment=binding['records'][0]['segments'][-1];p=Path(segment['normalized_member'])
        p.write_bytes(b' '*p.stat().st_size)
    def forbid_parent(pin):
        assert pin['sha256']!=native['quotes']['sha256'],'PARENT_QUOTES_OPENED'
        return actual_read(pin)
    monkeypatch.setattr(module,'pinned_bytes',forbid_parent)
    with pytest.raises(ValueError,match=error):
        prepare_selected_components(spec,root,10**8,source_binding={} if case=='missing_binding' else {'scope':'INVENTED'})
    assert not (root/'reference-inputs').exists()


def test_conversion10_dispatches_only_through_closed_source_owner(tmp_path,monkeypatch):
    import sys
    from types import ModuleType
    owner=ModuleType('polar.fomc_source');seen=[]
    def guarded(config,root,limit,*,queue):
        seen.append((config,root,limit,queue))
        return {'status':'INVENTED_OWNER_REJECTED_BEFORE_SOURCE_ACCESS'}
    owner.prepare_source_input=guarded
    monkeypatch.setitem(sys.modules,'polar.fomc_source',owner)
    config={'schema':'polar.reference-input-conversion-config/10'};queue=object()
    assert prepare_input(config,tmp_path,100,native_queue=queue)=={'status':'INVENTED_OWNER_REJECTED_BEFORE_SOURCE_ACCESS'}
    assert seen==[(config,tmp_path,100,queue)]


def test_all_selected_graph_metadata_rejected_before_any_value_member(tmp_path,monkeypatch):
    root,spec,parent,capture=selected_fixture_graph(tmp_path)
    native=json.loads(Path(parent['path']).read_bytes())
    relation=json.loads(Path(native['source_relations']['path']).read_bytes())
    record=next(r for r in relation['records'] if r['literal_alias']=='AAA')
    relation['jobs'][record['canonical_job_id']]['request']['adjustment']='raw'
    native['source_relations']=put(tmp_path/'changed-relations.json',relation)
    spec['normalized_inputs'][0]['input_ref']=put(tmp_path/'changed-native-metadata.json',native)
    leaf=json.loads(Path(spec['leaf_inputs'][0]['input_ref']['path']).read_bytes())
    binding=json.loads(Path(spec['normalized_inputs'][0]['binding_ref']['path']).read_bytes())
    selected=next(r for r in binding['records'] if r['literal_alias']=='AAA')
    forbidden={leaf['quotes']['sha256'],native['quotes']['sha256']} | {s['normalized_member_sha256'] for s in selected['segments']}
    import polar.selected_component_input as module
    original=module.pinned_bytes
    def metadata_only(pin):
        assert pin['sha256'] not in forbidden,'VALUE_MEMBER_OPENED_BEFORE_GRAPH_REJECTION'
        return original(pin)
    monkeypatch.setattr(module,'pinned_bytes',metadata_only)
    with pytest.raises(ValueError,match='SELECTED_COMPONENT_PARENT_BINDING'):
        prepare_selected_components(spec,root,10**8,source_binding={'scope':'INVENTED'})
    assert not (root/'reference-inputs').exists()
